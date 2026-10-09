#!/usr/bin/env bash
# Run the unit tests on Linux (cloud Claude sessions), without Leo's PC.
# Windows-only modules are replaced by stand-ins in ./shims; tests that need
# real Windows (registry, user32, pwsh) still fail here and must be checked
# on Windows before a release.  Qt needs libegl1 (apt-get install -y libegl1);
# the release-notes tests need PowerShell 7 (pwsh) on PATH.
# Usage: tools/linux_tests/run.sh [unittest args]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
venv="${BD2_LINUX_VENV:-$HOME/.cache/bd2-linux-venv}"
if [ ! -x "$venv/bin/python" ]; then
  uv venv -q -p 3.12 "$venv"
  # requirements-dev.txt pins everything for win32; take the same versions
  # minus the packages that only exist on Windows.
  sed -E "s/ ; sys_platform == 'win32'.*$//" "$root/requirements-dev.txt" \
    | grep -vE '^\s*(#|$)' \
    | grep -vE '^(pywin32|msvc-runtime|comtypes|pycaw|evdev|python-xlib|opencv-python|ok-script|onnxocr-ppocrv5|pyappify|adbutils|mouse|pynput|pydirectinput)==' \
    > "$venv/requirements-linux.txt"
  echo "opencv-python-headless==$(grep -oP '^opencv-python==\K[0-9.]+' "$root/requirements-dev.txt")" >> "$venv/requirements-linux.txt"
  VIRTUAL_ENV="$venv" uv pip install -q -r "$venv/requirements-linux.txt"
  # These declare Windows-only dependencies; their own code imports on Linux.
  VIRTUAL_ENV="$venv" uv pip install -q --no-deps \
    $(grep -E '^(ok-script|onnxocr-ppocrv5|pyappify|adbutils|mouse|pynput|pydirectinput)==' "$root/requirements-dev.txt" | sed -E 's/ ;.*$//')
  # win32con/winerror are plain constant tables; take the real ones from the
  # pinned pywin32 wheel so flag arithmetic in the code under test is right.
  VIRTUAL_ENV="$venv" uv pip install -q pip
  wheel_dir="$(mktemp -d)"
  "$venv/bin/python" -m pip download -q --no-deps --only-binary=:all: \
    --platform win_amd64 --python-version 3.12 -d "$wheel_dir" \
    "$(grep -oE '^pywin32==[0-9.]+' "$root/requirements-dev.txt")"
  "$venv/bin/python" - "$wheel_dir" <<'PY'
import glob, sys, sysconfig, zipfile
wheel = zipfile.ZipFile(glob.glob(f"{sys.argv[1]}/pywin32-*.whl")[0])
for name in ("win32/lib/win32con.py", "win32/lib/winerror.py"):
    target = f"{sysconfig.get_paths()['purelib']}/{name.rsplit('/', 1)[1]}"
    open(target, "wb").write(wheel.read(name))
PY
  rm -rf "$wheel_dir"
fi
cd "$root"
if [ "$#" -eq 0 ]; then set -- discover -s tests; fi
QT_QPA_PLATFORM=offscreen PYTHONPATH="$here/shims" exec "$venv/bin/python" -m unittest "$@"
