"""What the chat says when an omp session cannot reach TCC through `.mcp.json` (#173, the review of
Task 19, M4). Qt-free, so it is tested as a function: `main_window.py` may not grow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autosound_tcc.ui.tcc import i18n, mcp_view


def test_a_file_tcc_could_not_read_is_named_and_not_blamed_on_the_folder():
    """A read refusal reached the advice «Make the project folder writable», which does not fit: the
    file is there and could not be opened, and the folder's write permission does not open it. The
    sentence names the file and says to check it."""
    path = Path("project") / ".mcp.json"
    error = (f"StoreUnreadable: {path} could not be read (Permission denied); "
             "TCC will not write over it")
    server = SimpleNamespace(config_error=error, config_unreadable=path)

    said = mcp_view.omp_without_config(server)

    assert said == i18n.t("mcpConfigUnreadOmp").format(path=path, error=error)
    assert said.count(str(path)) == 2, "named, besides the reason"
    for lang, folder_advice in (("en", "writable"), ("uk", "для запису")):
        sentence = i18n.T[lang]["mcpConfigUnreadOmp"]
        assert folder_advice not in sentence and "{path}" in sentence, (lang, sentence)


def test_a_damaged_file_tcc_could_not_move_aside_is_not_told_to_be_opened():
    """The re-review of Task 19, N2. TCC read this file, found it damaged, and the move into
    `.tcc/` was refused — a read-only folder, a lock on the rename. «Check that it can be opened»
    points away from that: the file opened fine. Its own sentence names it, says it is damaged,
    and gives what fits — fix or remove it, or make the folder writable."""
    path = Path("project") / ".mcp.json"
    error = (f"StoreNotSetAside: {path} could not be read (Expecting value) and could not be set "
             "aside (Permission denied); TCC will not write over it")
    server = SimpleNamespace(config_error=error, config_unmoved=path, config_unreadable=None)

    said = mcp_view.omp_without_config(server)

    assert said == i18n.t("mcpConfigUnmovedOmp").format(path=path, error=error)
    assert said.count(str(path)) == 2, "named, besides the reason"
    for lang, open_advice in (("en", "can be opened"), ("uk", "можна відкрити")):
        sentence = i18n.T[lang]["mcpConfigUnmovedOmp"]
        assert open_advice not in sentence and "{path}" in sentence, (lang, sentence)


def test_a_file_tcc_could_not_write_keeps_the_folder_advice():
    """A write that failed is the folder's to fix: that sentence stays as it was."""
    server = SimpleNamespace(config_error="PermissionError: read-only")

    assert mcp_view.omp_without_config(server) == i18n.t("mcpNoConfigOmp").format(
        error="PermissionError: read-only")
