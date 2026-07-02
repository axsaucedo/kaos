"""Background runner tests: bounded concurrency, bounded retry, graceful drain."""

import threading
import time

from kaos_memory.app import BackgroundRunner


def test_concurrency_is_bounded():
    runner = BackgroundRunner(concurrency=2)
    running = 0
    peak = 0
    lock = threading.Lock()
    release = threading.Event()
    done = threading.Event()
    started = 0

    def task():
        nonlocal running, peak, started
        with lock:
            running += 1
            started += 1
            peak = max(peak, running)
        release.wait(timeout=5)
        with lock:
            running -= 1
            if started == 5 and running == 0:
                done.set()

    for _ in range(5):
        runner.submit(task)

    time.sleep(0.2)  # let the bounded pool pick up what it can
    with lock:
        assert peak <= 2  # never more than the concurrency cap run at once
    release.set()
    runner.shutdown(wait=True)
    assert peak <= 2


def test_retries_then_gives_up_without_crashing():
    attempts = []
    giveups = []
    runner = BackgroundRunner(
        concurrency=1, max_retries=2, on_giveup=lambda exc: giveups.append(exc)
    )

    def always_fails():
        attempts.append(1)
        raise RuntimeError("nope")

    runner.submit(always_fails)
    runner.shutdown(wait=True)

    assert len(attempts) == 3  # initial + 2 retries
    assert runner.failures == 1
    assert len(giveups) == 1 and isinstance(giveups[0], RuntimeError)


def test_pending_work_drains_on_shutdown():
    runner = BackgroundRunner(concurrency=2)
    completed = []

    def task(i):
        time.sleep(0.05)
        completed.append(i)

    for i in range(6):
        runner.submit(lambda i=i: task(i))
    runner.shutdown(wait=True)

    assert sorted(completed) == [0, 1, 2, 3, 4, 5]


def test_successful_task_does_not_count_as_failure():
    runner = BackgroundRunner(concurrency=1)
    ran = []
    runner.submit(lambda: ran.append(1))
    runner.shutdown(wait=True)
    assert ran == [1]
    assert runner.failures == 0
