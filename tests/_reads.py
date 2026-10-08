"""Which files a call reads: for the memos that must read nothing the second time (#172)."""

from __future__ import annotations

import builtins
import io
import os


def opened_under(monkeypatch, root) -> list[str]:
    """Every file under `root` opened for reading from here on, in order.

    Seen at `open()`, which the method's own readers call, and at `io.open`, which `Path`'s readers
    call. Each read still happens; the list only says which. An open to write is not a read and is
    left out, so a test can rewrite a file while it watches."""
    root = os.path.abspath(os.fspath(root))
    opened: list[str] = []
    real = io.open

    def spy(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)) and not any(c in mode for c in "wax"):
            where = os.path.abspath(os.fsdecode(file))
            if where.startswith(root + os.sep):
                opened.append(where)
        return real(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    return opened
