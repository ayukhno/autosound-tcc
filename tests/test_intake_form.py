"""The intake form's child process: started once, its URL read from one line, stopped on demand."""

from __future__ import annotations

import sys
import time

import pytest

from autosound_tcc.core import intake_form

_SERVES = """\
import sys, time
print("  intake form: http://127.0.0.1:45678/ (human line, translated)", flush=True)
print("INTAKE_URL: http://127.0.0.1:45678/", flush=True)
time.sleep(60)
"""

_SILENT = """\
import sys, time
print("boom: no url today", file=sys.stderr, flush=True)
time.sleep(60)
"""

_EXITS = """\
import sys
print("intake: no such project directory", file=sys.stderr, flush=True)
sys.exit(1)
"""


def _script(tmp_path, body):
    path = tmp_path / "intake_form.py"
    path.write_text(body, encoding="utf-8")
    return path


def _form(tmp_path, body, **kw):
    spawned = []

    def popen(*args, **kwargs):
        import subprocess
        proc = subprocess.Popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    form = intake_form.IntakeForm(tmp_path, "uk", popen=popen, script=_script(tmp_path, body),
                                  interpreter=sys.executable, **kw)
    return form, spawned


def test_open_url_returns_the_url_the_form_printed(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    try:
        assert form.open_url() == "http://127.0.0.1:45678/"
        assert form.running() and form.was_opened
    finally:
        form.stop()


def test_a_second_open_reuses_the_running_form(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    try:
        first = form.open_url()
        assert form.open_url() == first
        assert len(spawned) == 1, "one form process per project"
    finally:
        form.stop()


def test_stop_ends_the_process_and_is_idempotent(tmp_path):
    form, spawned = _form(tmp_path, _SERVES)
    form.open_url()
    form.stop()
    assert spawned[0].poll() is not None
    assert not form.running()
    form.stop()  # a second stop is a no-op, not an error


def test_a_form_that_prints_no_url_is_stopped_and_named(tmp_path):
    form, spawned = _form(tmp_path, _SILENT, timeout_s=1.0)
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert caught.value.kind == "failed"
    assert "boom" in caught.value.detail
    assert spawned[0].poll() is not None, "a form that never answered is not left running"
    assert not form.was_opened


def test_a_form_that_exits_says_why_without_waiting_out_the_timeout(tmp_path):
    form, _ = _form(tmp_path, _EXITS, timeout_s=8.0)
    started = time.monotonic()
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert time.monotonic() - started < 5.0
    assert "no such project directory" in caught.value.detail


def test_a_method_without_the_form_is_no_form_and_starts_nothing(tmp_path):
    spawned = []
    form = intake_form.IntakeForm(tmp_path, "uk", popen=lambda *a, **k: spawned.append(a),
                                  script=tmp_path / "absent.py", interpreter=sys.executable)
    with pytest.raises(intake_form.IntakeFormError) as caught:
        form.open_url()
    assert caught.value.kind == "no_form"
    assert spawned == []


def test_the_command_carries_the_interface_language_and_port_zero(tmp_path):
    form = intake_form.IntakeForm(tmp_path, "de", script=tmp_path / "intake_form.py",
                                  interpreter="py")
    assert form.command() == ["py", str(tmp_path / "intake_form.py"), "serve", str(tmp_path),
                              "--lang", "de", "--port", "0"]
