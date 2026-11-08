import csv
import random

import pytest

from quizleak import cli, email_step, events, funnel, segments, stats, synth, users
from quizleak.events import Session


# ---------------------------------------------------------------- stats
def test_two_prop_z_known_value():
    z, p = stats.two_prop_z(50, 100, 40, 100)
    assert z == pytest.approx(1.421, abs=0.01)
    assert p == pytest.approx(0.155, abs=0.01)


def test_two_prop_z_degenerate():
    assert stats.two_prop_z(0, 0, 5, 10) == (0.0, 1.0)
    assert stats.two_prop_z(10, 10, 10, 10)[1] == 1.0


def test_benjamini_hochberg():
    q = stats.benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_sample_size_matches_textbook():
    assert 380 <= stats.sample_size_per_arm(0.5, 0.1) <= 395   # classic: ~387 per arm


# ---------------------------------------------------------------- loading and funnel
def write_events(path, rows, cols=("session_id", "ts", "event", "os")):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols); w.writerows(rows)


def test_missing_required_column(tmp_path):
    p = tmp_path / "e.csv"
    write_events(p, [["s1", "x"]], cols=("session_id", "foo"))
    with pytest.raises(events.InputError, match="event"):
        events.load(str(p))


def test_missing_file():
    with pytest.raises(events.InputError):
        events.load("/nope/nothing.csv")


def test_funnel_chain_breaks_on_missing_step(tmp_path):
    p = tmp_path / "e.csv"
    write_events(p, [["a", "", "s1", "iOS"], ["a", "", "s2", "iOS"], ["a", "", "s3", "iOS"],
                     ["b", "", "s1", "iOS"], ["b", "", "s3", "iOS"]])    # b skipped s2 -> counted as stopped at s1
    sess, _ = events.load(str(p))
    funnel.annotate(sess, ["s1", "s2", "s3"])
    assert sess["a"].depth == 3 and sess["b"].depth == 1


def test_unknown_step_gives_helpful_error(tmp_path):
    p = tmp_path / "e.csv"
    write_events(p, [["a", "", "s1", "iOS"]])
    sess, _ = events.load(str(p))
    with pytest.raises(events.InputError, match="not found"):
        funnel.check_steps(sess, ["s1", "zzz"])


# ---------------------------------------------------------------- end-to-end on data with planted problems
@pytest.fixture(scope="module")
def analysed(tmp_path_factory):
    path = tmp_path_factory.mktemp("d") / "quiz.csv"
    synth.write(str(path), 20000, seed=7)
    sess, dims = events.load(str(path))
    steps = funnel.DEFAULT_STEPS
    funnel.check_steps(sess, steps)
    funnel.annotate(sess, steps)
    trs = funnel.transitions(sess, steps)
    focus = funnel.default_focus(trs)
    k = steps.index(focus.src)
    pop = [s for s in sess.values() if s.depth > k]
    moved = [s.depth > k + 1 for s in pop]
    use, _ = segments.select_dims(sess, dims, 25)
    down = funnel.reached(sess, steps, steps[-1]) / focus.n_dst
    found, n_tests = segments.find_leaks(pop, moved, use, max_segments=10, min_n=150, depth=2, min_gap_pp=2.0,
                                         downstream_rate=down, scale=350_000 / len(sess), ltv=68.0)
    mail = email_step.analyse(sess, steps, focus.src, focus.dst, scale=350_000 / len(sess), downstream=down, ltv=68.0)
    return dict(sess=sess, steps=steps, trs=trs, focus=focus, found=found, n_tests=n_tests, mail=mail, dims=use)


def test_funnel_matches_data_room(analysed):
    n0 = len(analysed["sess"])
    share = {st: funnel.reached(analysed["sess"], analysed["steps"], st) / n0 * 100 for st in analysed["steps"]}
    for step, target in [("quiz_open", 88), ("step_3", 61), ("step_4", 58), ("step_5", 36), ("offer_view", 31), ("purchase", 2.0)]:
        assert share[step] == pytest.approx(target, abs=1.0), step


def test_default_focus_is_email_step(analysed):
    assert analysed["focus"].src == "step_4"


def test_finds_exactly_the_planted_segments(analysed):
    labels = {s.label for s in analysed["found"]}
    assert labels == {"os=Android + browser=Instagram IAB", "creative_id=c07"}


def test_noise_attributes_are_not_reported(analysed):
    used = {d for s in analysed["found"] for d, _ in s.parts}
    assert not used & {"weekday", "daypart", "utm_source", "country", "device"}


def test_later_segments_are_counted_only_on_sessions_left_after_earlier_ones(analysed):
    """Peeling: segment 2's session count must equal the c07 sessions that are NOT in segment 1."""
    first, second = analysed["found"]
    k = analysed["steps"].index(analysed["focus"].src)
    pop = [s for s in analysed["sess"].values() if s.depth > k]
    left = [s for s in pop if not segments._matches(s, first.parts)]
    assert second.n == sum(segments._matches(s, second.parts) for s in left)
    assert second.n < sum(segments._matches(s, second.parts) for s in pop)   # i.e. overlap really was removed


def test_email_micro_funnel(analysed):
    mail = analysed["mail"]
    quit_by_error = {c: q for c, _, q, _ in mail.errors}
    assert quit_by_error["plus_sign_rejected"] > quit_by_error["typo_domain"] > 0
    assert {"gmial.com", "hotmial.com"} <= {d for d, _, _ in mail.bad_domains}
    assert mail.egp_all_errors > 0
    assert sum(c for c, _ in mail.groups.values()) == mail.n


# ---------------------------------------------------------------- false-positive control
def test_dropped_users_list(analysed):
    a = analysed
    rows = users.dropped_rows(a["sess"], a["steps"], a["focus"].src, a["dims"], a["found"], email_events=True)
    assert len(rows) == a["focus"].n_src - a["focus"].n_dst          # exactly the people who left at that step
    assert len({r["Користувач (session_id)"] for r in rows}) == len(rows)
    flags = [bool(r["Група, до якої належить"]) for r in rows]
    assert flags == sorted(flags, reverse=True) and any(flags)       # users from the found groups come first
    assert {"Коли відпав", "Де зупинився", "Що сталося", "os", "browser"} <= set(rows[0])
    in_group = [r for r in rows if r["Група, до якої належить"]]
    assert all(r["os"] == "Android" or r["creative_id"] == "c07" for r in in_group)


def test_amplitude_layout_gives_the_same_answer_as_generic(tmp_path):
    """The same synthetic sessions, once as a plain events CSV and once laid out like an Amplitude export
    (event_type, JSON properties, session_id in ms). The analysis must agree."""
    gen, amp = tmp_path / "g.csv", tmp_path / "a.csv"
    synth.write(str(gen), 6000, seed=3)
    synth.write_amplitude(str(amp), 6000, seed=3)
    assert events.detect_format(str(gen)) == "generic" and events.detect_format(str(amp)) == "amplitude"

    def run(path, extra=()):
        out = tmp_path / ("o_" + path.stem)
        cli.main([str(path), "--out", str(out), "--min-n", "100", *extra])
        return (out / "segments.csv").read_text(encoding="utf-8-sig").splitlines(), \
               (out / "dropped_users.csv").read_text(encoding="utf-8-sig").splitlines()

    seg_g, users_g = run(gen)
    seg_a, users_a = run(amp)
    cols = lambda lines: [r.split(",")[1:5] for r in lines[1:]]       # sessions, rate, rest_rate, gap
    assert cols(seg_g) == cols(seg_a) and len(seg_g) > 1
    assert len(users_g) == len(users_a)


def test_amplitude_event_names_and_json_properties():
    from quizleak import amplitude
    assert amplitude.event_name("Quiz Step Viewed", {"step": 4}) == "step_4"
    assert amplitude.event_name("Email Focused", {}) == "email_focus"
    assert amplitude.event_name("Purchase", {"revenue": 68}) == "purchase"
    assert amplitude.default_steps({"quiz_started", "step_1", "step_2", "step_10", "offer_viewed", "purchase", "email_focus"}) == \
        ["quiz_started", "step_1", "step_2", "step_10", "offer_viewed", "purchase"]


def test_no_findings_when_nothing_is_wrong():
    rng = random.Random(1)
    pop = [Session(props={"os": rng.choice(["iOS", "Android", "Win"]), "browser": rng.choice(["A", "B", "C", "D"]),
                          "creative_id": rng.choice(["c1", "c2", "c3", "c4", "c5"])}) for _ in range(6000)]
    moved = [rng.random() < 0.6 for _ in pop]       # conversion independent of every attribute
    found, n_tests = segments.find_leaks(pop, moved, ["os", "browser", "creative_id"], max_segments=10, min_n=150,
                                         depth=2, min_gap_pp=2.0, downstream_rate=0.05, scale=10, ltv=68)
    assert n_tests > 20 and found == []


def test_broad_parent_does_not_hide_the_real_sub_segment():
    """Regression: the whole of 'device=mobile' looked bad only because Android + Instagram IAB inside it is broken.
    The report must name the sub-segment (and its smaller EGP), not the parent."""
    rng = random.Random(5)
    pop, moved = [], []
    for _ in range(12000):
        os_ = rng.choice(["iOS", "Android", "Windows"])
        br = rng.choice(["Safari", "Chrome", "Instagram IAB"])
        bad = os_ == "Android" and br == "Instagram IAB"
        pop.append(Session(props={"os": os_, "device": "desktop" if os_ == "Windows" else "mobile", "browser": br}))
        moved.append(rng.random() < (0.40 if bad else 0.65))
    found, _ = segments.find_leaks(pop, moved, ["os", "device", "browser"], max_segments=5, min_n=150, depth=2,
                                   min_gap_pp=2.0, downstream_rate=0.05, scale=10, ltv=68)
    assert [sg.label for sg in found] == ["os=Android + browser=Instagram IAB"]


# ---------------------------------------------------------------- CLI
def test_cli_writes_outputs(tmp_path):
    data = tmp_path / "q.csv"
    synth.write(str(data), 4000, seed=3)
    out = tmp_path / "out"
    cli.main([str(data), "--out", str(out), "--min-n", "100"])
    assert (out / "report.md").exists() and (out / "report.html").exists() and (out / "segments.csv").exists()
    assert (out / "dropped_users.csv").read_text(encoding="utf-8-sig").startswith("Користувач (session_id)")
    assert 'id="u"' in (out / "report.html").read_text(encoding="utf-8")
    assert "Воронка" in (out / "report.md").read_text(encoding="utf-8")


def test_cli_bad_focus_exits_cleanly(tmp_path):
    data = tmp_path / "q.csv"
    synth.write(str(data), 500, seed=3)
    with pytest.raises(SystemExit):
        cli.main([str(data), "--out", str(tmp_path / "o"), "--focus", "nonsense"])


def test_cli_writes_dropped_users_per_step(tmp_path):
    import csv
    data = tmp_path / "q.csv"
    synth.write(str(data), 4000, seed=3)
    out = tmp_path / "out"
    cli.main([str(data), "--out", str(out), "--min-n", "100"])
    folder = out / "dropped_by_step"
    files = sorted(folder.glob("*.csv"))
    assert len(files) == len(funnel.DEFAULT_STEPS) - 1
    sess = events.load(str(data))[0]
    funnel.annotate(sess, funnel.DEFAULT_STEPS)
    trs = funnel.transitions(sess, funnel.DEFAULT_STEPS)
    for f, t in zip(files, trs):
        rows = list(csv.DictReader(f.open(encoding="utf-8-sig")))
        assert len(rows) == t.n_src - t.n_dst, f.name          # exactly those who reached the step but not the next
    step2 = list(csv.DictReader(next(f for f in files if "step_2__step_3" in f.name).open(encoding="utf-8-sig")))
    assert step2 and "Помилка" not in step2[0]                  # email columns only on the email step
    step4 = list(csv.DictReader(next(f for f in files if "step_4__step_5" in f.name).open(encoding="utf-8-sig")))
    assert "Помилка" in step4[0]
    assert "dropped_by_step/03_step_2__step_3.csv" in (out / "report.html").read_text(encoding="utf-8")
