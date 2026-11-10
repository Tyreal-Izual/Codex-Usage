#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "This app builds on macOS only." >&2
  exit 1
fi
MODE="${1:---release}"
if [[ "$MODE" != --release && "$MODE" != --development ]]; then
  echo "Usage: $0 [--release | --development]" >&2
  exit 1
fi
source "$ROOT/scripts/xcode_env.sh"
PYTHON="${USAGE_PYTHON:-python3}"
APP="$ROOT/dist/Usage.app"
mkdir -p "$ROOT/.build" "$APP/Contents/MacOS" "$APP/Contents/Resources"
CONFIG=release
[[ "$MODE" == --development ]] && CONFIG=debug
xcrun swift build --package-path macOS --scratch-path "$ROOT/.build/swift" -c "$CONFIG"
BIN_DIR="$(xcrun swift build --package-path macOS --scratch-path "$ROOT/.build/swift" -c "$CONFIG" --show-bin-path)"
cp "$BIN_DIR/UsageMac" "$APP/Contents/MacOS/UsageMac"
if [[ "$MODE" == --development ]]; then
  # This runner deliberately keeps the checkout dependency for fast iteration.
  HELPER_SOURCE="$ROOT/.build/development-helper"
  rm -rf "$HELPER_SOURCE"
  "$PYTHON" - "$HELPER_SOURCE/usage-helper" "$ROOT/native_backend.py" <<'PY'
import pathlib, shlex, sys
path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -B ' + shlex.quote(sys.argv[2]) + ' "$@"\n')
path.chmod(0o755)
PY
else
  if [[ ! -x .build/python/bin/python ]]; then "$PYTHON" -m venv .build/python; fi
  .build/python/bin/python -m pip install --disable-pip-version-check -r scripts/requirements-build.txt
  export PYINSTALLER_CONFIG_DIR="$ROOT/.build/pyinstaller-cache"
  .build/python/bin/python -m PyInstaller --noconfirm --onedir --name usage-helper \
    --distpath "$ROOT/.build/frozen" --workpath "$ROOT/.build/pyinstaller" \
    --specpath "$ROOT/.build" --log-level WARN native_backend.py
  HELPER_SOURCE="$ROOT/.build/frozen/usage-helper"
fi
# Replace the entire generated helper in either mode, including old frozen libraries.
rm -rf "$APP/Contents/Resources/helper"
cp -R "$HELPER_SOURCE" "$APP/Contents/Resources/helper"
cp macOS/Info.plist "$APP/Contents/Info.plist"
cp LICENCE "$APP/Contents/Resources/LICENCE"
xcrun swift scripts/make_icon.swift "$ROOT/.build/Usage.iconset"
iconutil -c icns "$ROOT/.build/Usage.iconset" -o "$APP/Contents/Resources/Usage.icns"
# Local builds are ad-hoc signed. Developer ID signing/notarization is a release step.
codesign --force --sign - "$APP/Contents/MacOS/UsageMac"
codesign --force --sign - "$APP"
echo "Built: $APP ($MODE, $(uname -m))"
