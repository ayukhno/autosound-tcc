"""Headless CLI for the DSP-profile onboarding interview — the same
`core.agent_session.OnboardingSession` the Qt dialog uses, driven from a terminal instead.

This is the acceptance-test harness for the DSP-profile mechanism (docs/TCC-TZ.md §4a plan): it
lets the interview be validated end-to-end against a real DSP (e.g. MUSWAY M6V4) before any
"new project" GUI wizard exists.

Usage:
    python -m autosound_tcc.dsp_profile_interview --vendor Musway --model M6V4 \\
        --project-dir /path/to/project

Type answers at the prompt; Ctrl-D (EOF) or an empty line ends the session. If the agent already
called finalize_profile, the profile is on disk regardless of how the session ends.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from autosound_tcc.core.agent_session import OnboardingSession


async def _run(project_dir: Path, vendor: str, model: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    session = OnboardingSession(project_dir, vendor, model)
    print(f"--- DSP profile onboarding: {vendor} {model} ({project_dir}) ---")
    print("(empty line or Ctrl-D to end the session)\n")
    try:
        async for chunk in session.start():
            print(chunk, end="", flush=True)
        print("\n")
        while True:
            try:
                user_text = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: input("> ")
                )
            except EOFError:
                break
            if not user_text.strip():
                break
            async for chunk in session.send(user_text):
                print(chunk, end="", flush=True)
            print("\n")
    finally:
        await session.close()

    profile_path = project_dir / "dsp_profile.json"
    if profile_path.is_file():
        print(f"Profile saved: {profile_path}")
    else:
        print("Session ended without a saved profile (finalize_profile was never called).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, help="DSP vendor, e.g. Musway")
    parser.add_argument("--model", required=True, help="DSP model, e.g. M6V4")
    parser.add_argument("--project-dir", required=True, type=Path,
                         help="Project directory to write dsp_profile.json into")
    args = parser.parse_args(argv)
    asyncio.run(_run(args.project_dir, args.vendor, args.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
