"""The outside watcher's error-spike alerts and webhook delivery (#173)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "watch_readiness.py"
spec = importlib.util.spec_from_file_location("watch_readiness_alerts", SCRIPT)
assert spec is not None and spec.loader is not None
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def test_a_spike_alerts_once_and_says_when_it_ends() -> None:
    w = watch.Watch()
    said = [w.step(True, spike) for spike in (False, True, True, False, False)]
    assert said == [[], [watch.SPIKE], [], [watch.CALM], []]


def test_a_server_that_is_down_reports_no_spike() -> None:
    w = watch.Watch()
    assert w.step(False, True) == []
    assert w.step(False, True) == [watch.DOWN]
    assert w.step(True, False) == [watch.UP]


class _Answer:
    def __init__(self, body: dict) -> None:
        self.status = 200
        self._body = json.dumps(body).encode()

    def read(self, *_):  # noqa: ANN002, ANN202
        return self._body

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_):  # noqa: ANN002, ANN204
        return False

    def close(self) -> None:
        pass


def test_the_webhook_gets_the_alert_but_never_the_addresses(monkeypatch, capsys) -> None:
    secret = "hook-secret-token"
    sent = []

    def fake_urlopen(target, timeout):  # noqa: ANN001, ANN202
        if isinstance(target, str):
            return _Answer({"ready": True, "server_error_spike": True})
        sent.append(json.loads(target.data))
        return _Answer({})

    class Finished(Exception):
        pass

    monkeypatch.setattr(watch, "urlopen", fake_urlopen)
    monkeypatch.setattr(watch.time, "sleep", lambda _: (_ for _ in ()).throw(Finished()))
    monkeypatch.setenv("CLIP_ALERT_WEBHOOK", f"https://hooks.example.test/{secret}")
    monkeypatch.setattr(sys, "argv", ["watch_readiness.py", "https://private.example.test/ready"])

    with pytest.raises(Finished):
        watch.main()

    assert sent == [{"text": watch.SPIKE}]
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert "private.example.test" not in out.out + out.err


def test_an_unreachable_webhook_is_reported_without_its_address(monkeypatch, capsys) -> None:
    def broken(target, timeout):  # noqa: ANN001, ANN202
        raise OSError("connection refused to https://hooks.example.test/secret")

    monkeypatch.setattr(watch, "urlopen", broken)
    watch.notify(watch.DOWN, "https://hooks.example.test/secret")
    out = capsys.readouterr().out
    assert watch.DOWN in out and "could not be reached" in out
    assert "secret" not in out.replace(watch.DOWN, "")
