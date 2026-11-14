"""Tests for privacy-safe service readiness alerts."""

import importlib.util
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "watch_readiness.py"

spec = importlib.util.spec_from_file_location("watch_readiness", SCRIPT)
assert spec is not None
assert spec.loader is not None
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def test_readiness_alert_does_not_leak_secrets(monkeypatch, capsys):
    secret = "synthetic-private-token"
    checks = 0

    class SimulationFinished(Exception):
        pass

    def failed_request(url, timeout):
        raise URLError(f"failure containing {secret}")

    def fake_sleep(seconds):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise SimulationFinished

    monkeypatch.setattr(watch, "urlopen", failed_request)
    monkeypatch.setattr(watch.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        ["watch_readiness.py", f"https://example.test/{secret}/api/v1/ready"],
    )

    with pytest.raises(SimulationFinished):
        watch.main()

    output = capsys.readouterr()
    assert output.out.count("ALERT:") == 1
    assert "C.L.I.P is not ready" in output.out
    assert secret not in output.out
    assert secret not in output.err


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([False, True], []),
        (
            [False, False, False, True],
            ["ALERT:", "RECOVERED:"],
        ),
        (
            [False, False, True, False, False, True],
            ["ALERT:", "RECOVERED:", "ALERT:", "RECOVERED:"],
        ),
    ],
)
def test_alert_and_recovery_lifecycle(monkeypatch, capsys, states, expected):
    observations = iter(states)

    class SimulationFinished(Exception):
        pass

    def fake_ready(url):
        return next(observations)

    checks = 0

    def fake_sleep(seconds):
        nonlocal checks
        checks += 1
        if checks >= len(states):
            raise SimulationFinished

    monkeypatch.setattr(watch, "ready", fake_ready)
    monkeypatch.setattr(watch.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        ["watch_readiness.py", "https://example.test/api/v1/ready"],
    )

    with pytest.raises(SimulationFinished):
        watch.main()

    output = capsys.readouterr().out
    alerts = [line for line in output.splitlines() if line.startswith(("ALERT:", "RECOVERED:"))]

    assert len(alerts) == len(expected)

    for actual, prefix in zip(alerts, expected, strict=True):
        assert actual.startswith(prefix)

    assert "https://example.test" not in output
