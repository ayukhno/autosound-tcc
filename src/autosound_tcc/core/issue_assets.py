"""Screenshots that go WITH a problem report, published through the method's gate.

The gate is the method's and stays there (`rew_tool/gates/side_effect.py`). It pins the repo and
the branch in code, refuses without `consented=True`, cuts `dest_name` down to a basename, and
post-verifies the URL that comes back. None of that is re-implemented here: a second place that
decides where an image may be published is a second place that can be talked into publishing it
somewhere else.

What belongs to the app is the half the gate cannot do: **showing a person what they are about to
publish.** A screenshot of a DSP window carries a file path with somebody's name in it, the car,
the installer's branding — and what is published to a public repository cannot be un-published.
So consent here is not a checkbox; it is the pictures still on screen when Send is pressed
(SKL-019, and `feedback-loop.md` now draws the line by what is in frame rather than by file type).

`available()` is what the window asks before offering the control at all. The gate's uploader
lands with a method newer than this checkout's pin, and a button that attaches images nothing can
carry is worse than no button — the same posture `core/eq_export.py` keeps for the exporter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import vendor_loader

#: The method's side-effect gate. Present since long before this feature; `upload_issue_asset` is
#: the part that arrives later, so the module being importable is NOT the same question as the
#: uploader existing, and `available()` asks the second one.
_MODULE = "gates/side_effect.py"

#: What the window may offer. Anything else the gate would take is still not something a person
#: can judge from a thumbnail.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


@dataclass(frozen=True)
class Published:
    """URLs for what went up, and — when something stopped — what and how far it got.

    `urls` is filled in even when `problem` is set, and that is deliberate: an upload that failed
    on the third file leaves two files PUBLISHED. Reporting only the failure would leave a person
    believing nothing was sent when two pictures are already public.
    """

    urls: tuple[str, ...] = ()
    problem: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def _gate():
    try:
        return vendor_loader.load(_MODULE)
    except Exception:  # noqa: BLE001 — no skill checked out at all
        return None


def available() -> bool:
    """Whether this installation can publish an image with a report."""
    gate = _gate()
    return gate is not None and hasattr(gate, "upload_issue_asset")


def dest_name(stamp: str, index: int, source: Path) -> str:
    """`20260903-201500-1.png` — named by the RUN, not by the file it came from.

    A local file name is the one part of a screenshot nobody looks at before sending and everybody
    can read afterwards: `passat-ivanenko-final.png` publishes a name that was never in the frame.
    The suffix is kept because the store serves by it; unknown ones become `.png` rather than
    travelling as-is.
    """
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".png"
    return f"{stamp}-{index}{suffix}"


def _url_of(result) -> Optional[str]:
    """The raw URL out of whatever the gate handed back.

    Tolerant on purpose: `guarded_run` answers with a dict, and the uploader is documented as
    answering with the verified raw URL. Both are read rather than one of them assumed, because
    this call cannot be exercised against the real gate until the pin reaches it (#60).
    """
    if isinstance(result, str):
        return result.strip() or None
    if isinstance(result, dict):
        for key in ("url", "download_url", "raw_url", "stdout", "detail"):
            value = result.get(key)
            if isinstance(value, str):
                for token in value.split():
                    if token.startswith("https://"):
                        return token.strip().rstrip(".,)")
    return None


def publish(
    paths: Sequence[Path],
    *,
    consented: bool,
    runner=None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Published:
    """Publish each file, in order, and give back the URLs.

    `consented` is passed through rather than decided here: the gate refuses without it, and the
    only thing that can honestly set it is the window that showed the pictures.
    """
    gate = _gate()
    if gate is None or not hasattr(gate, "upload_issue_asset"):
        return Published(problem="this build cannot publish images with a report")
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    extra = {} if runner is None else {"runner": runner}
    urls: list[str] = []
    for index, path in enumerate(paths, start=1):
        try:
            result = gate.upload_issue_asset(
                str(path),
                dest_name(stamp, index, Path(path)),
                consented=consented,
                dry_run=dry_run,
                **extra,
            )
        except Exception as exc:  # noqa: BLE001 — the gate's refusal is an answer, not a crash
            return Published(tuple(urls), problem=f"{type(exc).__name__}: {exc}")
        if dry_run:
            continue
        url = _url_of(result)
        if url is None:
            return Published(tuple(urls), problem=f"no URL came back for {Path(path).name}")
        urls.append(url)
    return Published(tuple(urls))
