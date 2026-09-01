#!/bin/zsh
set -eu

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "ERROR: run this setup in a native arm64 Terminal, not under Rosetta." >&2
  echo "Current architecture: $(uname -m)" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.12}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: native Python not found at $PYTHON_BIN" >&2
  echo "Install Homebrew python@3.12 or set PYTHON_BIN to a native arm64 Python 3.12 executable." >&2
  exit 2
fi

PY_MINOR="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PY_MINOR" != "3.12" ]]; then
  echo "ERROR: current CASA macOS wheels require Python 3.12; found $PY_MINOR." >&2
  exit 2
fi

if [[ -d .venv ]]; then
  VENV_MINOR="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  if [[ "$VENV_MINOR" != "$PY_MINOR" ]]; then
    echo "ERROR: .venv uses Python $VENV_MINOR. Move it aside, then rerun setup." >&2
    exit 2
  fi
fi

"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install \
  "casatasks>=6.7.2" \
  "casatools>=6.7.2" \
  "cubevis==1.0.14" \
  "bokeh>=3.8" \
  matplotlib astropy numpy

python - <<'PY'
import platform
from importlib.metadata import version

assert platform.machine() == "arm64", platform.machine()
for package in ("casatasks", "casatools", "cubevis"):
    print(f"{package}={version(package)}")
from cubevis import iclean  # noqa: F401
print("iclean import: OK")
PY

echo "Environment ready. Activate it with: source .venv/bin/activate"
