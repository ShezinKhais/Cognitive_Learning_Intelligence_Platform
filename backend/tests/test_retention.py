"""The purge runner deletes what has outlived its retention period, politely.

Owner: General CS, Phase 7.

The tasks here are fakes that return a scripted count per call and note what
they were asked. The runner is given a pause of a few hundredths of a second
(or none) so a purge of several batches does not slow the suite down.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services import retention as retention_module
from app.services.retention import BATCH_SIZE, MAX_BATCHES_PER_TASK, PurgeReport, PurgeRunner

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)
BATCH = 3


class FakeTask:
    """Returns the scripted counts in turn, and 0 once the script is spent.
    An exception in the script is raised instead of returned."""

    def __init__(self, name: str, script: list[int | Exception], log: list[str] | None = None):
        self.name = name
        self._script = list(script)
        self._log = log
        self.calls: list[tuple[datetime, int]] = []

    async def purge(self, cutoff: datetime, limit: int) -> int:
        self.calls.append((cutoff, limit))
        if self._log is not None:
            self._log.append(self.name)
        if not self._script:
            return 0
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class Endless:
    """A task that always says it filled the batch."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def purge(self, cutoff: datetime, limit: int) -> int:
        self.calls += 1
        return limit


def make_runner(**kwargs: object) -> PurgeRunner:
    options: dict[str, object] = {
        "retention": lambda: RETENTION,
        "clock": lambda: NOW,
        "batch_size": BATCH,
        "pause": 0,
    }
    options.update(kwargs)
    return PurgeRunner(**options)  # type: ignore[arg-type]


# -- the basics ---------------------------------------------------------------------


async def test_a_run_with_no_tasks_deletes_nothing_and_says_so() -> None:
    report = await make_runner().run()

    assert report.total == 0
    assert report.summary() == "no purge task is registered"
    assert report.interrupted is False


async def test_every_task_is_called_with_the_clock_minus_the_retention_period() -> None:
    task = FakeTask("a", [1])
    runner = make_runner()
    runner.register(task)

    report = await runner.run()

    assert report.cutoff == NOW - RETENTION
    assert task.calls == [(NOW - RETENTION, BATCH)]


async def test_the_retention_period_is_read_afresh_on_every_run() -> None:
    days = [30]
    task = FakeTask("a", [])
    runner = make_runner(retention=lambda: timedelta(days=days[0]))
    runner.register(task)

    await runner.run()
    days[0] = 7
    await runner.run()

    assert [cutoff for cutoff, _ in task.calls] == [
        NOW - timedelta(days=30),
        NOW - timedelta(days=7),
    ]


async def test_a_task_is_called_again_until_it_returns_fewer_than_the_batch_size() -> None:
    task = FakeTask("a", [BATCH, BATCH, 1])
    runner = make_runner()
    runner.register(task)

    report = await runner.run()

    assert len(task.calls) == 3
    assert all(limit == BATCH for _, limit in task.calls)
    assert report.deleted == {"a": 2 * BATCH + 1}
    assert report.total == 2 * BATCH + 1
    assert report.interrupted is False


async def test_a_batch_that_exactly_fills_is_followed_by_one_more_call() -> None:
    task = FakeTask("a", [BATCH, 0])
    runner = make_runner()
    runner.register(task)

    report = await runner.run()

    assert len(task.calls) == 2
    assert report.total == BATCH


async def test_counts_add_up_across_tasks() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", [BATCH, 2]))
    runner.register(FakeTask("b", [1]))

    report = await runner.run()

    assert report.deleted == {"a": BATCH + 2, "b": 1}
    assert report.total == BATCH + 3


async def test_tasks_run_in_name_order_whatever_order_they_were_registered_in() -> None:
    log: list[str] = []
    runner = make_runner()
    runner.register(FakeTask("charlie", [], log))
    runner.register(FakeTask("alpha", [], log))
    runner.register(FakeTask("bravo", [], log))

    await runner.run()

    assert runner.task_names == ["alpha", "bravo", "charlie"]
    assert log == ["alpha", "bravo", "charlie"]


def test_a_second_task_with_the_same_name_is_refused() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", []))

    with pytest.raises(ValueError):
        runner.register(FakeTask("a", []))


def test_the_default_batch_size_and_limit_stay_small_enough_to_be_polite() -> None:
    assert BATCH_SIZE <= 1000
    assert MAX_BATCHES_PER_TASK * BATCH_SIZE < 1_000_000


# -- a retention period that would delete everything --------------------------------


@pytest.mark.parametrize("days", [0, -1])
async def test_a_retention_period_of_zero_or_less_is_refused_and_nothing_is_called(
    days: int,
) -> None:
    task = FakeTask("a", [BATCH])
    runner = make_runner(retention=lambda: timedelta(days=days))
    runner.register(task)

    with pytest.raises(ValueError):
        await runner.run()

    assert task.calls == []


# -- failure ------------------------------------------------------------------------


async def test_a_task_that_raises_is_listed_as_failed_and_the_others_still_run() -> None:
    bad = FakeTask("a-bad", [BATCH, RuntimeError("disk gone")])
    good = FakeTask("b-good", [2])
    runner = make_runner()
    runner.register(bad)
    runner.register(good)

    report = await runner.run()

    assert report.failed == ("a-bad",)
    assert report.deleted["b-good"] == 2
    assert good.calls != []
    assert report.interrupted is False


async def test_what_a_task_deleted_before_it_failed_is_still_counted() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", [BATCH, BATCH, RuntimeError("boom")]))

    report = await runner.run()

    assert report.deleted == {"a": 2 * BATCH}
    assert report.failed == ("a",)


async def test_a_task_that_fails_at_once_is_counted_as_zero() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", [RuntimeError("boom")]))

    report = await runner.run()

    assert report.deleted == {"a": 0}
    assert report.failed == ("a",)


# -- yielding to a class ------------------------------------------------------------


async def test_nothing_is_purged_when_a_class_is_already_running() -> None:
    task = FakeTask("a", [BATCH])
    runner = make_runner(busy=lambda: True)
    runner.register(task)

    report = await runner.run()

    assert task.calls == []
    assert report.total == 0
    assert report.interrupted is True


async def test_the_run_stops_between_batches_when_a_class_starts() -> None:
    first = FakeTask("a", [BATCH, BATCH, BATCH])
    second = FakeTask("b", [1])
    runner = make_runner(busy=lambda: len(first.calls) >= 1)
    runner.register(first)
    runner.register(second)

    report = await runner.run()

    assert len(first.calls) == 1
    assert second.calls == []
    assert report.deleted["a"] == BATCH
    assert report.interrupted is True


async def test_a_task_that_is_never_empty_stops_at_the_batch_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retention_module, "MAX_BATCHES_PER_TASK", 4)
    endless = Endless("a")
    runner = make_runner()
    runner.register(endless)

    report = await runner.run()

    assert endless.calls == 4
    assert report.deleted == {"a": 4 * BATCH}
    assert report.interrupted is True


async def test_the_tasks_after_one_that_never_empties_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retention_module, "MAX_BATCHES_PER_TASK", 3)
    after = FakeTask("b", [1])
    runner = make_runner()
    runner.register(Endless("a"))
    runner.register(after)

    report = await runner.run()

    assert len(after.calls) == 1
    assert report.deleted["b"] == 1
    assert report.interrupted is True


async def test_a_task_that_empties_on_its_last_allowed_batch_is_not_marked_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retention_module, "MAX_BATCHES_PER_TASK", 3)
    runner = make_runner()
    runner.register(FakeTask("a", [BATCH, BATCH, 1]))

    report = await runner.run()

    assert report.total == 2 * BATCH + 1
    assert report.interrupted is False


async def test_a_negative_count_from_a_task_does_not_reduce_the_total() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", [BATCH, -5]))

    report = await runner.run()

    assert report.deleted == {"a": BATCH}


# -- letting everything else run ----------------------------------------------------


async def test_other_work_gets_to_run_between_batches() -> None:
    """A purge of a term's data must not hold the event loop for its length."""
    ticks = 0
    seen: list[int] = []

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    class Noting:
        name = "a"

        def __init__(self) -> None:
            self.script = [BATCH, BATCH, BATCH, 1]

        async def purge(self, cutoff: datetime, limit: int) -> int:
            seen.append(ticks)
            return self.script.pop(0)

    runner = make_runner(pause=0.05)
    runner.register(Noting())
    other = asyncio.create_task(ticker())
    try:
        report = await runner.run()
    finally:
        other.cancel()

    assert report.total == 3 * BATCH + 1
    assert len(seen) == 4
    # The ticker ran at least once in every gap between two batches.
    assert all(later > earlier for earlier, later in zip(seen, seen[1:], strict=False))


# -- the summary --------------------------------------------------------------------


def test_the_summary_gives_the_total_the_cutoff_date_and_each_task_in_name_order() -> None:
    report = PurgeReport(cutoff=datetime(2026, 5, 2, 3, 0, tzinfo=UTC), deleted={"b": 2, "a": 5})

    assert report.summary() == "deleted 7 item(s) older than 2026-05-02 (a: 5, b: 2)"


def test_the_summary_names_the_tasks_that_failed() -> None:
    report = PurgeReport(cutoff=NOW, deleted={"a": 1, "b": 0}, failed=("b", "c"))

    assert report.summary().endswith("; failed: b, c")


def test_the_summary_says_when_a_run_stopped_early() -> None:
    report = PurgeReport(cutoff=NOW, deleted={"a": 1}, interrupted=True)

    assert "stopped early" in report.summary()


def test_a_clean_summary_has_neither_a_failure_nor_a_stop() -> None:
    summary = PurgeReport(cutoff=NOW, deleted={"a": 1}).summary()

    assert "failed" not in summary
    assert "stopped early" not in summary


def test_a_report_with_only_failures_still_has_a_summary_of_what_was_tried() -> None:
    summary = PurgeReport(cutoff=NOW, failed=("a",)).summary()

    assert "deleted 0 item(s)" in summary
    assert "failed: a" in summary


async def test_the_summary_of_a_real_run_reports_what_it_deleted() -> None:
    runner = make_runner()
    runner.register(FakeTask("a", [2]))

    report = await runner.run()

    assert report.summary() == "deleted 2 item(s) older than 2026-05-02 (a: 2)"
