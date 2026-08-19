"""What is installed, as one pasteable block — and never an exception."""

from __future__ import annotations

from autosound_tcc.core import install_report


def test_every_section_is_present_and_the_text_is_pasteable():
    text = install_report.as_text()

    for head in ("[Autosound TCC]", "[The method]", "[Command-line tools]", "[This machine]",
                 "[Where things are]"):
        assert head in text
    assert "\t" not in text, "aligned with spaces, so it survives a chat and a screenshot"


def test_a_tool_that_is_not_there_is_a_line_and_not_a_crash(monkeypatch):
    """A report that dies on one missing tool reports nothing at all — and "not found" IS the
    finding, most of the time."""
    monkeypatch.setattr(install_report.shutil, "which", lambda _name: None)

    text = install_report.as_text()

    assert "not found" in text
    assert "[Command-line tools]" in text


def test_a_probe_that_hangs_or_explodes_is_swallowed(monkeypatch):
    def _boom(*_a, **_kw):
        raise OSError("no such thing")

    monkeypatch.setattr(install_report.subprocess, "run", _boom)

    assert install_report.as_text()  # still a report


def test_the_windows_facts_the_window_passes_in_are_in_the_report():
    text = install_report.as_text(install_report.report(extra={"MCP": "not running: ValueError"}))

    assert "MCP" in text and "not running: ValueError" in text
