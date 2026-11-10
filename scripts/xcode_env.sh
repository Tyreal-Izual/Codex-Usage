#!/bin/bash
# Source this file before native builds/tests so they select the same full Xcode.
if [[ -z "${DEVELOPER_DIR:-}" ]]; then
  if [[ -d /Applications/Xcode.app/Contents/Developer ]]; then
    DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
  else
    DEVELOPER_DIR="$(xcode-select -p)"
  fi
fi
if [[ ! -d "$DEVELOPER_DIR/Platforms/MacOSX.platform" ]]; then
  echo "Full Xcode is required; standalone Command Line Tools cannot build this app." >&2
  echo "Set DEVELOPER_DIR to your Xcode.app/Contents/Developer directory." >&2
  return 1
fi
export DEVELOPER_DIR
