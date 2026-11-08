import argparse
import sys
from pathlib import Path

from . import amplitude, email_step, events, funnel, report, segments, stats, users as users_mod


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="quizleak", description="Find where and for whom the quiz leaks users, from an events CSV.")
    ap.add_argument("csv", help="events CSV (columns: session_id, event, [ts, error, email_domain, ...attributes])")
    ap.add_argument("--format", choices=["auto", "generic", "amplitude"], default="auto",
                    help="CSV layout: generic (session_id,event,ts) or amplitude (event_type, amplitude_id, JSON properties). Default: detect")
    ap.add_argument("--steps", default=None, help="funnel event names, comma-separated, in order (default: guessed for Amplitude, "
                    "session_start,quiz_open,step_2..step_5,offer_view,purchase otherwise)")
    ap.add_argument("--focus", help="analyse the exit from this step (default: biggest loss inside the quiz)")
    ap.add_argument("--min-n", type=int, default=150, help="minimum sessions in a segment (default 150)")
    ap.add_argument("--depth", type=int, choices=[1, 2], default=2, help="1 = single attributes, 2 = also pairs (default)")
    ap.add_argument("--min-gap", type=float, default=2.0, help="minimum gap vs the rest, percentage points (default 2)")
    ap.add_argument("--max-card", type=int, default=25, help="skip attributes with more unique values than this")
    ap.add_argument("--monthly-clicks", type=int, default=350_000, help="clicks per month to scale to (data room: $350k / $1 CPC)")
    ap.add_argument("--ltv", type=float, default=68.0, help="value of one extra purchase, USD (data room LTV)")
    ap.add_argument("--target-lift", type=float, default=0.02, help="lift to size an A/B test for (default 0.02 = 2 pp)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", default="out")
    a = ap.parse_args(argv)

    try:
        fmt = events.detect_format(a.csv, a.format)
        sessions, dims = events.load(a.csv, fmt)
        if a.steps:
            steps = [s.strip() for s in a.steps.split(",") if s.strip()]
        elif fmt == "amplitude":
            steps = amplitude.default_steps(set().union(*(s.events for s in sessions.values())))
            if len(steps) < 3:
                raise events.InputError("Could not guess the quiz steps from the event names. Events present: "
                                        + ", ".join(sorted(set().union(*(s.events for s in sessions.values()))))
                                        + ". Use --steps to set your own order.")
        else:
            steps = list(funnel.DEFAULT_STEPS)
        funnel.check_steps(sessions, steps)
        funnel.annotate(sessions, steps)
        trs = funnel.transitions(sessions, steps)
        if a.focus:
            if a.focus not in steps[:-1]:
                raise events.InputError(f"--focus must be one of: {', '.join(steps[:-1])}")
            focus = next(t for t in trs if t.src == a.focus)
            note = "(вибрано вручну)"
        else:
            focus = funnel.default_focus(trs)
            note = "(найбільша втрата всередині квізу; змінюється через --focus)"
    except events.InputError as e:
        sys.exit(f"Error: {e}")

    k = steps.index(focus.src)
    pop = [s for s in sessions.values() if s.depth > k]
    moved = [s.depth > k + 1 for s in pop]
    n_start = trs[0].n_src
    n_dst, n_last = focus.n_dst, funnel.reached(sessions, steps, steps[-1])
    downstream = n_last / n_dst if n_dst else 0.0
    scale = a.monthly_clicks / n_start

    use_dims, skipped = segments.select_dims(sessions, dims, a.max_card)
    found, n_tests = segments.find_leaks(pop, moved, use_dims, max_segments=a.top, min_n=a.min_n, depth=a.depth,
                                         min_gap_pp=a.min_gap, downstream_rate=downstream, scale=scale, ltv=a.ltv)
    shown = found
    flagged_dims = {d for s in found for d, _ in s.parts}
    clean = [d for d in use_dims if d not in flagged_dims]

    n_sample = stats.sample_size_per_arm(focus.rate, a.target_lift)
    daily = a.monthly_clicks / 30 * (focus.n_src / n_start)           # sessions reaching the step per day
    days = 2 * n_sample / daily

    email = email_step.analyse(sessions, steps, focus.src, focus.dst, scale=scale, downstream=downstream, ltv=a.ltv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    seen_events = set().union(*(s.events for s in sessions.values()))
    has_email_events = bool({"email_focus", "email_submit", "email_error"} & seen_events)
    by_step, dropped = users_mod.write_by_step(out / "dropped_by_step", sessions, steps, dims, focus.src, shown)
    md = report.build_markdown(src=Path(a.csv).name, n_sessions=n_start, trs=trs, focus=focus, focus_note=note,
                               segs=shown, n_tests=n_tests, email=email, clean_dims=clean, skipped_dims=skipped,
                               sample_n=n_sample, sample_days=days, target_lift=a.target_lift,
                               monthly_clicks=a.monthly_clicks, ltv=a.ltv, min_n=a.min_n, users=dropped, by_step=by_step)
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.html").write_text(report.build_html(trs, focus, shown, "QuizLeak", src=Path(a.csv).name, n_sessions=n_start, users=dropped, by_step=by_step), encoding="utf-8")
    report.write_segments_csv(out / "segments.csv", found)
    users_mod.write_csv(out / "dropped_users.csv", dropped)

    print(f"table {Path(a.csv).name} ({fmt}) | steps {steps[0]}..{steps[-1]} | {n_start} sessions | focus {focus.src}->{focus.dst} {focus.rate:.1%} | {n_tests} segments tested, "
          f"{len(found)} significant | top: {shown[0].label if shown else '-'}")
    print(f"-> {out}/report.md, report.html, segments.csv, dropped_users.csv, dropped_by_step/ ({len(by_step)} файлів)")


if __name__ == "__main__":
    main()
