"""Experiment Lab, fase 6: de pure logica van walk-forward - vensters,
kandidatenset, selectie en validatiebeslissing. Vaste data, geen klok."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
from vaste_bars import VAST_BEGIN  # noqa: E402

from gold_scalper.const import STRATEGY_WINDOW_BARS  # noqa: E402
from gold_scalper.experiment_lab import walk_forward as W  # noqa: E402

BAR = 900
TS = [VAST_BEGIN + BAR * i for i in range(STRATEGY_WINDOW_BARS + 2000)]
START = TS[STRATEGY_WINDOW_BARS]
DAG = 96 * BAR


def _vensters(soort=W.ROLLING, modus=W.CANDIDATE_SELECTION, val=DAG, **extra):
    args = dict(first_train_start=START, train_length=3 * DAG, validation_length=val,
                test_length=DAG, step_size=DAG, window_count=4, max_hold_seconds=900)
    args.update(extra)
    return W.build_windows(modus, soort, TS, BAR, **args)


def test_rolling_windows_shift_forward():
    v = _vensters()
    for k, w in enumerate(v):
        tr = w.segment("TRAIN")
        assert tr.start_ts == START + k * DAG and tr.end_ts == tr.start_ts + 3 * DAG
        assert w.segment("VALIDATION").start_ts == tr.end_ts
        assert w.segment("TEST").start_ts == w.segment("VALIDATION").end_ts


def test_expanding_windows_grow_from_the_same_start():
    v = _vensters(W.EXPANDING)
    for k, w in enumerate(v):
        assert w.segment("TRAIN").start_ts == START
        assert w.segment("TRAIN").end_ts == START + 3 * DAG + k * DAG


def test_test_windows_never_overlap_and_are_ascending():
    v = _vensters()
    for a, b in zip(v, v[1:]):
        assert b.segment("TEST").start_ts >= a.segment("TEST").end_ts
    with pytest.raises(W.WalkForwardError, match="overlappen"):
        _vensters(step_size=DAG // 2)


def test_half_open_and_warmup_and_cutoff_per_window():
    for w in _vensters():
        for s in w.segments:
            assert s.warmup_start_ts <= s.start_ts < s.open_cutoff_ts < s.end_ts
            assert s.open_cutoff_ts == s.end_ts - 900 - BAR


def test_a_window_past_the_dataset_is_refused():
    with pytest.raises(W.WalkForwardError, match="einde van de dataset"):
        _vensters(window_count=40)


def test_sequential_oos_has_only_test_segments():
    v = _vensters(modus=W.SEQUENTIAL_OOS)
    assert all([s.kind for s in w.segments] == ["TEST"] for w in v)


def test_candidate_set_hash_ignores_order_but_not_content():
    a = [("A", "h1"), ("B", "h2"), ("C", "h3")]
    assert W.candidate_set_hash(a) == W.candidate_set_hash(list(reversed(a)))
    assert W.candidate_set_hash(a) != W.candidate_set_hash([("A", "h1"), ("B", "h2"), ("C", "h4")])
    with pytest.raises(W.WalkForwardError):
        W.candidate_set_hash([("A", "h1"), ("B", "h1")])


def _m(**waarden):
    return {k: ({"value": v, "calculation_status": "VALID"} if v is not None
                else {"value": None, "calculation_status": "INSUFFICIENT_DATA"})
            for k, v in waarden.items()}


REGEL = W.SelectionRule("net_pnl", W.MAXIMIZE, tie_break=(("maximum_drawdown", W.MINIMIZE),))
HASHES = {"a": "h-a", "b": "h-b", "c": "h-c"}


def test_selection_takes_the_best_by_the_registered_rule():
    s = W.select(REGEL, {"a": _m(net_pnl=5.0), "b": _m(net_pnl=9.0), "c": _m(net_pnl=1.0)}, HASHES)
    assert s.status == W.SELECTED and s.selected == "b"
    assert [e["rank_position"] for e in s.evaluations] == [2, 1, 3]


def test_minimize_direction():
    r = W.SelectionRule("maximum_drawdown", W.MINIMIZE)
    s = W.select(r, {"a": _m(maximum_drawdown=5.0), "b": _m(maximum_drawdown=2.0)}, HASHES)
    assert s.selected == "b"


def test_tie_break_is_deterministic():
    k = {"a": _m(net_pnl=5.0, maximum_drawdown=3.0), "b": _m(net_pnl=5.0, maximum_drawdown=2.0)}
    for _ in range(3):
        assert W.select(REGEL, k, HASHES).selected == "b"
    s = W.select(REGEL, k, HASHES)
    assert all(e["rank_position"] is None for e in s.evaluations)    # geen rangorde bij gelijke waarden


def test_an_unresolvable_tie_gives_no_selection():
    k = {"a": _m(net_pnl=5.0, maximum_drawdown=2.0), "b": _m(net_pnl=5.0, maximum_drawdown=2.0)}
    s = W.select(REGEL, k, HASHES)
    assert s.status == W.NO_SELECTION and s.selected is None


def test_config_hash_breaks_a_tie_only_when_registered():
    k = {"a": _m(net_pnl=5.0, maximum_drawdown=2.0), "b": _m(net_pnl=5.0, maximum_drawdown=2.0)}
    r = W.SelectionRule("net_pnl", W.MAXIMIZE,
                        tie_break=(("maximum_drawdown", W.MINIMIZE), W.CONFIG_HASH_TIEBREAK))
    assert W.select(r, k, HASHES).selected == "a"


def test_missing_metric_policies():
    k = {"a": _m(net_pnl=None), "b": _m(net_pnl=3.0)}
    assert W.select(REGEL, k, HASHES).selected == "b"                              # DISQUALIFY
    streng = W.SelectionRule("net_pnl", W.MAXIMIZE, missing_metric_policy=W.NO_SELECTION_POLICY)
    assert W.select(streng, k, HASHES).status == W.NO_SELECTION
    geen = W.select(REGEL, {"a": _m(net_pnl=None)}, HASHES)
    assert geen.status == W.NO_SELECTION and "geldige" in geen.reason


def test_an_invalid_metric_is_never_treated_as_zero():
    k = {"a": _m(net_pnl=None), "b": _m(net_pnl=-3.0)}
    s = W.select(REGEL, k, HASHES)
    assert s.selected == "b"                  # een NULL van a is geen 0 die -3 zou verslaan


def test_validation_decision_checks_only_the_selected_candidate():
    r = W.SelectionRule("net_pnl", W.MAXIMIZE, validation_policy=W.TRAIN_THEN_VALIDATION,
                        validation_condition={"metric": "net_pnl", "operator": ">", "threshold": 0})
    assert W.validation_decision(r, _m(net_pnl=2.0))[0] == W.PASSED
    assert W.validation_decision(r, _m(net_pnl=-1.0))[0] == W.FAILED
    assert W.validation_decision(r, _m(net_pnl=None))[0] == W.FAILED
    assert W.validation_decision(REGEL, None)[0] == W.NOT_REQUIRED


def test_the_rule_is_checked_before_use():
    for kapot in (W.SelectionRule("bestaat_niet", W.MAXIMIZE),
                  W.SelectionRule("net_pnl", "HOOG"),
                  W.SelectionRule("net_pnl", W.MAXIMIZE, validation_policy=W.TRAIN_THEN_VALIDATION),
                  W.SelectionRule("net_pnl", W.MAXIMIZE,
                                  tie_break=(W.CONFIG_HASH_TIEBREAK, ("maximum_drawdown", W.MINIMIZE)))):
        with pytest.raises(W.WalkForwardError):
            kapot.check()


def test_window_state_machine_has_terminal_states_without_exits():
    for s in W.WINDOW_TERMINAL:
        assert W.WINDOW_ALLOWED[s] == ()
    assert "COMPLETED" in W.WINDOW_ALLOWED["TESTING"]
    assert "TESTING" not in W.WINDOW_ALLOWED["TRAINING"]           # nooit TEST zonder selectie
