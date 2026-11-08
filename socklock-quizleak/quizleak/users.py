"""A per-user list: WHO dropped at the focus step, WHERE exactly they stopped, WHEN, and what they have in common."""
import csv
from datetime import datetime
from pathlib import Path

from .events import Session
from .report import human_label
from .segments import Segment, _matches

WHAT = {"never_touched": "не торкнувся поля email", "typed_and_left": "почав вводити й пішов без помилки",
        "error_then_quit": "отримав помилку й пішов"}
LAST_EVENT_LABELS = {"email_focus": "клікнув у поле email", "email_error": "побачив помилку email",
                     "email_submit": "відправив email"}


def dropped_rows(sessions: dict[str, Session], steps: list[str], src: str, dims: list[str],
                 segs: list[Segment], email_events: bool) -> list[dict]:
    """Sessions that reached `src` but not the next step. Users from the found leaking segments come first."""
    k = steps.index(src)
    rows = []
    for sid, s in sessions.items():
        if not (s.depth > k and s.depth <= k + 1):
            continue
        rank, seg_label = 999, ""
        for i, sg in enumerate(segs):
            if _matches(s, sg.parts):
                rank, seg_label = i, human_label(sg)
                break
        if not email_events:
            what = ""
        elif s.errors:
            what = WHAT["error_then_quit"]
        elif "email_focus" in s.events:
            what = WHAT["typed_and_left"]
        else:
            what = WHAT["never_touched"]
        last = s.last_ts
        spent = ""
        if last and src in s.event_ts:
            spent = int((last - s.event_ts[src]).total_seconds())
        row = {
            "Користувач (session_id)": sid,
            "Коли відпав": last.strftime("%Y-%m-%d %H:%M:%S") if last else "",
            "Де зупинився": LAST_EVENT_LABELS.get(s.last_event, s.last_event) if s.last_event != src else f"на кроці {src}, нічого не зробив",
            "Що сталося": what,
            "Помилка": ", ".join(sorted({c for c, _ in s.errors})),
            "Домен у помилці": ", ".join(sorted({d for _, d in s.errors if d})),
            "Секунд на кроці": spent,
            "Група, до якої належить": seg_label,
        }
        for d in dims:
            row[d] = s.props.get(d, "")
        row["_rank"] = rank
        row["_ts"] = last or datetime.min
        rows.append(row)
    rows.sort(key=lambda r: (r["_rank"], r["_ts"]))
    for r in rows:
        r.pop("_rank"); r.pop("_ts")
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


EMAIL_COLS = ("Що сталося", "Помилка", "Домен у помилці")


def email_step(sessions: dict[str, Session], steps: list[str]) -> str | None:
    """The funnel step on which the email field lives: the last step reached before the first email event."""
    votes: dict[str, int] = {}
    for s in sessions.values():
        t_email = [s.event_ts[e] for e in ("email_focus", "email_error", "email_submit") if e in s.event_ts]
        if not t_email:
            continue
        before = [st for st in steps if st in s.event_ts and s.event_ts[st] <= min(t_email)]
        if before:
            votes[before[-1]] = votes.get(before[-1], 0) + 1
    return max(votes, key=votes.get) if votes else None


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


STEP_COL = "Крок, де відпав"


def write_by_step(folder: Path, sessions: dict[str, Session], steps: list[str], dims: list[str],
                  focus_src: str, focus_segs: list[Segment]) -> tuple[list[dict], list[dict]]:
    """One CSV per funnel hop (everyone who reached `src` but not the next step).
    Returns ([{src, dst, n, file}], combined) where `combined` is every dropped user of every hop in one list."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.csv"):
        old.unlink()
    em = email_step(sessions, steps)
    meta, combined = [], []
    for i in range(len(steps) - 1):
        src, dst = steps[i], steps[i + 1]
        rows = dropped_rows(sessions, steps, src, dims, focus_segs if src == focus_src else [], src == em)
        if src != em:
            for r in rows:
                for c in EMAIL_COLS:
                    r.pop(c, None)
        if src != focus_src:
            for r in rows:
                r.pop("Група, до якої належить", None)
        name = f"{i + 1:02d}_{_safe(src)}__{_safe(dst)}.csv"
        write_csv(folder / name, rows)
        meta.append({"src": src, "dst": dst, "n": len(rows), "file": f"{folder.name}/{name}"})
        for r in rows:
            combined.append({"Користувач (session_id)": r["Користувач (session_id)"], STEP_COL: f"{src} → {dst}",
                             **{k: v for k, v in r.items() if k != "Користувач (session_id)"}})
    cols = list(dict.fromkeys(k for r in combined for k in r))          # union of columns, first-seen order
    for r in combined:
        for c in cols:
            r.setdefault(c, "")
    combined = [{c: r[c] for c in cols} for r in combined]
    return meta, combined
