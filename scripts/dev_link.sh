#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER_VERSION="${BLENDER_VERSION:-5.2}"
TARGET="$HOME/.config/blender/${BLENDER_VERSION}/extensions/user_default"

mkdir -p "$TARGET"
ln -sfn "$REPO/rastersheet" "$TARGET/rastersheet"
echo "linked $TARGET/rastersheet -> $REPO/rastersheet"
