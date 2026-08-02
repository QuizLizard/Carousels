#!/usr/bin/env bash
# One-time setup. Downloads the two fonts (not committed - they are large).
set -e
cd "$(dirname "$0")"
mkdir -p fonts
[ -f fonts/Nunito.ttf ] || curl -sL -o fonts/Nunito.ttf \
  "https://raw.githubusercontent.com/google/fonts/main/ofl/nunito/Nunito%5Bwght%5D.ttf"
[ -f fonts/NotoColorEmoji.ttf ] || curl -sL -o fonts/NotoColorEmoji.ttf \
  "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/NotoColorEmoji.ttf"
python3 -m pip install --quiet --break-system-packages pillow 2>/dev/null || pip install --quiet pillow
echo "setup complete"
