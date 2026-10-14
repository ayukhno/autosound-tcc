"""Sign-in to Codex by a TCC button (`core/codex_login.py`, W-10 tcc#181 task 9).

Against the stand-in (`tests/fakes/fake_codex_app_server.py`) replaying the recorded login
(`login-cancel.jsonl`): the recording's own `account/read` is cut, since the sign-in does not ask
it, and its end is rewritten for success and failure. The stand-in's verdict (every server request
answered once) is read from its log; the child is gone after close.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from autosound_tcc.core import codex_cli, codex_login, codex_rpc
from autosound_tcc.core.codex_cli import Found
from autosound_tcc.core.codex_login import SignIn, SignInError

HERE = Path(__file__).parent
FAKE = HERE / "fakes" / "fake_codex_app_server.py"
RECORDED = HERE / "fixtures" / "codex" / "login-cancel.jsonl"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="a POSIX script stands in for codex")


def _frames() -> list[dict]:
    """The recorded login without its `account/read` (id 2) and the notification beside it."""
    out = []
    for line in RECORDED.read_text(encoding="utf-8").splitlines():
        frame = json.loads(line)
        msg = frame.get("msg") or {}
        if msg.get("id") == 2 or msg.get("method") == "remoteControl/status/changed":
            continue
        out.append(frame)
    return out


def _completed(frames: list[dict]) -> dict:
    return next(f for f in frames if (f.get("msg") or {}).get("method") == "account/login/completed")


def _scenario(tmp_path: Path, name: str) -> Path:
    frames = _frames()
    start = next(i for i, f in enumerate(frames)
                 if (f.get("msg") or {}).get("method") == "account/login/start")
    if name == "cancel":
        chosen = frames
    else:
        done = _completed(frames)
        params = dict(done["msg"]["params"])
        if name == "success":
            params.update(success=True, error=None)
        else:
            params.update(success=False, error="Login server error: the browser said no")
        # login/start and its answer, then the end of the sign-in — no cancel
        chosen = frames[:start + 2] + [{**done, "msg": {**done["msg"], "params": params}}]
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(f) for f in chosen) + "\n", encoding="utf-8")
    return path


def _busy_port(tmp_path: Path) -> Path:
    frames = _frames()
    start = next(i for i, f in enumerate(frames)
                 if (f.get("msg") or {}).get("method") == "account/login/start")
    error = {"dir": "in", "t": 0.3, "msg": {"id": 3, "error": {
        "code": -32603, "message": "failed to start login server: Address already in use (os error 48)"}}}
    path = tmp_path / "busy.jsonl"
    path.write_text("\n".join(json.dumps(f) for f in frames[:start + 1] + [error]) + "\n",
                    encoding="utf-8")
    return path


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """`codex` = the stand-in on `scenario`; returns the log path to read its verdict."""
    wrapper = tmp_path / "fake-bin" / "codex"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(f"#!{sys.executable}\nimport os, sys\n"
                       f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, *sys.argv[1:]])\n")
    wrapper.chmod(0o755)
    log = tmp_path / "stand-in.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_CODEX_TIMEOUT", "5")
    found = Found(str(wrapper), codex_cli.SOURCE_PATH)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    probes: list[bool] = []
    monkeypatch.setattr(codex_cli, "probe", lambda force=False: probes.append(force))

    def use(scenario: Path) -> tuple[Path, list]:
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", str(scenario))
        return log, probes

    return use


def _verdict(log: Path) -> dict:
    for _ in range(50):  # the stand-in writes it as it exits
        lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        verdicts = [x["verdict"] for x in lines if "verdict" in x]
        if verdicts:
            return verdicts[-1]
        time.sleep(0.05)
    raise AssertionError("the stand-in wrote no verdict")


def _sent(log: Path) -> list[str]:
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [x["msg"].get("method") for x in lines if x.get("dir") == "out" and "method" in x["msg"]]


def _gone(sign_in: SignIn) -> bool:
    return sign_in.server is not None and sign_in.server.returncode is not None


def test_begin_gives_the_browser_address_and_a_success_is_true(tmp_path, stand_in):
    log, probes = stand_in(_scenario(tmp_path, "success"))
    sign_in = SignIn()

    url = sign_in.begin()

    assert url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "127.0.0.1%3A1455" in url, "the fixed callback port"
    assert sign_in.wait(timeout=10) is True
    assert sign_in.error == ""
    assert probes == [True], "a forced probe after success: signed_in() and the models are fresh"
    assert _gone(sign_in)
    assert _verdict(log)["breaches"] == []
    assert _sent(log)[:3] == ["initialize", "initialized", "account/login/start"]
    start = next(x for x in (json.loads(y) for y in log.read_text().splitlines())
                 if x.get("dir") == "out" and x["msg"].get("method") == "account/login/start")
    assert start["msg"]["params"] == {"type": "chatgpt"}


def test_a_failed_sign_in_keeps_codex_s_own_sentence(tmp_path, stand_in):
    log, probes = stand_in(_scenario(tmp_path, "failure"))
    sign_in = SignIn()
    sign_in.begin()

    assert sign_in.wait(timeout=10) is False

    assert sign_in.error == "Login server error: the browser said no"
    assert probes == []
    assert _gone(sign_in)
    assert _verdict(log)["breaches"] == []


def test_a_cancel_asks_codex_to_cancel_and_leaves_no_child(tmp_path, stand_in):
    log, probes = stand_in(_scenario(tmp_path, "cancel"))
    sign_in = SignIn()
    sign_in.begin()
    threading.Timer(0.3, sign_in.cancel).start()

    assert sign_in.wait(timeout=10) is False

    assert sign_in.cancelled
    assert probes == []
    assert _gone(sign_in)
    assert _sent(log).count("account/login/cancel") == 1
    cancel = next(x for x in (json.loads(y) for y in log.read_text().splitlines())
                  if x.get("dir") == "out" and x["msg"].get("method") == "account/login/cancel")
    assert cancel["msg"]["params"] == {"loginId": "f3b86f58-e3e6-4863-8320-b1fd64e10547"}
    assert _verdict(log)["breaches"] == []


def test_wait_reads_a_cancel_request_from_its_caller(tmp_path, stand_in):
    """The worker's `isInterruptionRequested`: a window closing mid-wait cancels."""
    log, _probes = stand_in(_scenario(tmp_path, "cancel"))
    sign_in = SignIn()
    sign_in.begin()
    asked = time.monotonic() + 0.3

    assert sign_in.wait(timeout=10, cancelled=lambda: time.monotonic() > asked) is False

    assert sign_in.cancelled and _gone(sign_in)
    assert _sent(log).count("account/login/cancel") == 1


def test_close_is_idempotent_and_cancels_a_pending_sign_in(tmp_path, stand_in):
    log, _probes = stand_in(_scenario(tmp_path, "cancel"))
    sign_in = SignIn()
    sign_in.begin()

    sign_in.close()
    sign_in.close()

    assert _gone(sign_in)
    assert _sent(log).count("account/login/cancel") == 1
    assert _verdict(log)["breaches"] == []


def test_a_busy_callback_port_is_codex_s_own_sentence(tmp_path, stand_in):
    stand_in(_busy_port(tmp_path))
    sign_in = SignIn()

    with pytest.raises(SignInError) as caught:
        sign_in.begin()

    assert "Address already in use" in str(caught.value)
    assert _gone(sign_in)


def test_no_usable_codex_is_a_sentence_and_nothing_spawned(monkeypatch):
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: None)

    with pytest.raises(SignInError):
        SignIn().begin()


def test_the_sign_in_spawns_the_native_binary_never_a_shim(monkeypatch):
    found = Found("/native/codex", codex_cli.SOURCE_FOLDER, shim="/usr/local/bin/codex")
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    assert codex_login.binary() == "/native/codex"


def test_a_success_keeps_the_versions_already_read(tmp_path, stand_in, monkeypatch):
    """The review's M1: the sign-in forgets where Codex is and probes again; it does not wipe a
    too-old reading, or `find()` would answer the old Codex until the probe ended."""
    old = tmp_path / "old" / "codex"
    old.parent.mkdir()
    old.write_bytes(b"old")
    found_old = Found(str(old), codex_cli.SOURCE_PATH)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found_old), (0, 150, 0))
    _log, probes = stand_in(_scenario(tmp_path, "success"))
    sign_in = SignIn()
    sign_in.begin()

    assert sign_in.wait(timeout=10) is True

    assert probes == [True]
    assert codex_cli.known_version(found_old) == (0, 150, 0)


def test_a_success_stays_a_success_when_the_probe_after_it_fails(tmp_path, stand_in, monkeypatch):
    """Group fix I2: the probe after a sign-in raised (an `RpcError` on `initialize`), and the
    caller read that as «did not finish» over a sign-in that had succeeded."""
    stand_in(_scenario(tmp_path, "success"))

    def refused(force=False):
        raise codex_rpc.RpcError(-32600, "refused")

    monkeypatch.setattr(codex_cli, "probe", refused)
    sign_in = SignIn()
    sign_in.begin()

    assert sign_in.wait(timeout=10) is True
    assert sign_in.error == ""
