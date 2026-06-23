"""Tests for the debounced, watch-driven reconcile worker orchestration."""

from __future__ import annotations

from dataclasses import replace

from kaos_sync.config import Settings
from kaos_sync.main import DirtyTracker, reconcile_loop

BASE = Settings.from_env({})


def _counting_pass(counter: list[int]):
    def run_pass() -> None:
        counter.append(1)

    return run_pass


def test_initial_pass_runs_before_any_event():
    settings = replace(BASE, reconcile_interval_seconds=0)
    dirty = DirtyTracker()
    passes: list[int] = []
    # Stop right after the initial pass.
    runs = {"n": 0}

    def should_continue() -> bool:
        runs["n"] += 1
        return False

    reconcile_loop(
        settings,
        _counting_pass(passes),
        dirty,
        should_continue=should_continue,
        sleep=lambda _s: None,
    )
    assert len(passes) == 1


def test_dirty_triggers_a_pass():
    settings = replace(BASE, reconcile_interval_seconds=60, watch_debounce_seconds=0)
    dirty = DirtyTracker()
    dirty.mark_dirty()
    passes: list[int] = []
    iterations = {"n": 0}

    def should_continue() -> bool:
        iterations["n"] += 1
        return iterations["n"] <= 1

    reconcile_loop(
        settings,
        _counting_pass(passes),
        dirty,
        should_continue=should_continue,
        sleep=lambda _s: None,
    )
    # Initial pass + one dirty-triggered pass.
    assert len(passes) == 2


def test_burst_coalesces_into_single_pass_via_debounce():
    settings = replace(BASE, reconcile_interval_seconds=60, watch_debounce_seconds=0.01)
    dirty = DirtyTracker()
    dirty.mark_dirty()
    passes: list[int] = []
    iterations = {"n": 0}
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        # Simulate more events arriving during the debounce window.
        dirty.mark_dirty()
        dirty.mark_dirty()

    def should_continue() -> bool:
        iterations["n"] += 1
        return iterations["n"] <= 1

    reconcile_loop(
        settings,
        _counting_pass(passes),
        dirty,
        should_continue=should_continue,
        sleep=fake_sleep,
    )
    # Initial + one coalesced pass; debounce slept exactly once.
    assert len(passes) == 2
    assert slept == [0.01]


def test_safety_net_pass_with_no_events():
    settings = replace(BASE, reconcile_interval_seconds=0, watch_debounce_seconds=0)
    dirty = DirtyTracker()  # never marked dirty
    passes: list[int] = []
    iterations = {"n": 0}

    def should_continue() -> bool:
        iterations["n"] += 1
        return iterations["n"] <= 2

    reconcile_loop(
        settings,
        _counting_pass(passes),
        dirty,
        should_continue=should_continue,
        sleep=lambda _s: None,
    )
    # Initial + two safety-net passes even without events.
    assert len(passes) == 3


def test_dirty_tracker_auto_clears():
    dirty = DirtyTracker()
    dirty.mark_dirty()
    assert dirty.wait_dirty(0) is True
    assert dirty.wait_dirty(0) is False


class _ScriptedBackend:
    """A fake Lease backend returning a scripted acquire/renew sequence."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def try_acquire_or_renew(self) -> bool:
        self.calls += 1
        if not self._results:
            return False
        value = self._results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _run_elector(results, max_iters):
    from kaos_sync.main import LeaderElector

    events: list[str] = []
    iters = {"n": 0}

    def should_continue() -> bool:
        iters["n"] += 1
        return iters["n"] <= max_iters

    elector = LeaderElector(
        _ScriptedBackend(results),
        on_started_leading=lambda: events.append("start"),
        on_stopped_leading=lambda: events.append("stop"),
        retry_period_seconds=0,
        should_continue=should_continue,
        sleep=lambda _s: None,
    )
    elector.run()
    return events


def test_election_acquires_and_starts_leading_once():
    # Stays leader across renewals: start fires once, no stop.
    assert _run_elector([True, True, True], max_iters=3) == ["start"]


def test_election_relinquishes_on_renewal_failure():
    # Becomes leader then a renewal returns False: start then stop.
    assert _run_elector([True, False], max_iters=2) == ["start", "stop"]


def test_election_backend_error_is_treated_as_not_leading():
    # An exception while leading relinquishes leadership rather than crashing.
    assert _run_elector([True, RuntimeError("boom")], max_iters=2) == ["start", "stop"]


def test_election_standby_never_leads():
    # Never acquires: no callbacks fire.
    assert _run_elector([False, False], max_iters=2) == []
