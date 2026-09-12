#!/usr/bin/env bash
# `#19` under a native debugger, on the Windows runner. Run by `ci.yml` only when a series is
# dispatched with `native_debug: true`; a push never reaches it.
#
# Why it exists: the Python dump stops at `QThread.__init__` on the main thread with no other
# Python thread alive (2026-09-12: 36 crashes over three series and a control on v0.1.37, every
# one a real death). Whatever decides the question happens BELOW that frame, where faulthandler
# cannot look. cdb can: on a second-chance access violation, or on heap corruption at first sight,
# it prints the native stack of the faulting thread and of every thread, then ends the process.
#
# `page_heap: true` also turns on full page heap for python.exe, which moves a heap corruption
# from where it is NOTICED to where it is DONE — the Windows counterpart of the libgmalloc run
# that found nothing on macOS the same day.
set -u

dbg="/c/Program Files (x86)/Windows Kits/10/Debuggers/x64"
if [ ! -x "$dbg/cdb.exe" ]; then
  echo "::error title=#19 native::cdb.exe is not on this runner (looked in $dbg)"
  ls "/c/Program Files (x86)/Windows Kits/10/" 2>&1 || true
  exit 2
fi

uv sync --extra dev --python 3.12 --quiet
python_exe="$(cygpath -w "$PWD/.venv/Scripts/python.exe")"

if [ "${PAGE_HEAP:-false}" = "true" ]; then
  "$dbg/gflags.exe" /p /enable python.exe /full
fi

# `stale_check: true` — see scripts/pytest_stale_wrappers.py. Freed Python memory gets a marker,
# and every test ends by walking the wrapper map, so a left-behind entry crashes at the end of
# the test that left it.
plugin=()
if [ "${STALE_CHECK:-false}" = "true" ]; then
  export PYTHONMALLOC=debug
  export PYTHONPATH="$(cygpath -w "$PWD/scripts")"
  plugin=(-p pytest_stale_wrappers)
fi

on_crash='.echo ===NATIVE CRASH===; |; ~.; .ecxr; kn 80; .echo ===ALL THREADS===; ~*kn 40; .echo ===MODULES===; lmvm Qt6Core; lm m *shiboken*; lm m *pyside*; .echo ===END===; q'
# -o follows child processes: `.venv\Scripts\python.exe` is a launcher that starts the base
# interpreter as a child, and the child is the one that crashes.
cat > /d/cdb-19.txt <<EOF
.symfix D:\\symbols
sxn ibp
sxn cpr
sxn epr
sxi ld
sxi ud
sxd -c2 "$on_crash" av
sxe -c "$on_crash" c0000374
g
EOF

attempts=5
for i in $(seq 1 $attempts); do
  "$dbg/cdb.exe" -o -cf 'D:\cdb-19.txt' "$python_exe" -m pytest "$@" "${plugin[@]}" -q -p no:cacheprovider \
    2>&1 | tee /tmp/native-out.txt
  if grep -q "===NATIVE CRASH===" /tmp/native-out.txt; then
    grep "\[stale-check\] after" /tmp/native-out.txt | tail -1 | sed "s/^/last test before the crash: /"
    echo "::warning title=#19 native::attempt $i captured a native stack — read from ===NATIVE CRASH=== to ===END==="
    echo "- native stack captured on attempt **$i** of $attempts" >> "$GITHUB_STEP_SUMMARY"
    exit 1
  fi
  if grep -q "Windows fatal exception" /tmp/native-out.txt; then
    echo "::warning title=#19 native::attempt $i printed a fatal exception but cdb never stopped"
  else
    echo "attempt $i: no crash"
  fi
done
echo "- no native stack in $attempts attempts" >> "$GITHUB_STEP_SUMMARY"
exit 0
