#!/bin/bash
# Build the AI-2 GRUB theme into the ISO root-overlay.
#
# The theme lands in /usr/share/grub/themes/artix/ ON PURPOSE: artools copies
# exactly that directory into the ISO's /boot/grub/themes and the Artix live
# grub.cfg + the installed system's /etc/default/grub both point at
# themes/artix/theme.txt. We only ship OUR files (background, panel/highlight/
# slider pixmaps, fonts, entry icons, theme.txt); the generic glyph icons stay
# the ones from Artix's GPL artix-grub-theme package, which we do not copy.
#
# Needs: python3, rsvg-convert, magick (ImageMagick 7), grub-mkfont, DejaVu Sans Mono.
# Usage: branding/grub-theme/build.sh   (run from anywhere)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)                       # www/ai-2
OUT="$ROOT/iso/profiles/ai2/root-overlay/usr/share/grub/themes/artix"
DESIGN="$ROOT/../../000/design"
FONT=/usr/share/fonts/TTF/DejaVuSansMono.ttf
PNG_RGBA=(-define png:color-type=6 -define png:bit-depth=8 -interlace none)   # GRUB's decoder: 8-bit, non-interlaced

mkdir -p "$OUT/icons"
python3 "$HERE/gen-background.py" "$HERE/background.svg"
rsvg-convert -w 1024 -h 768 "$HERE/background.svg" -o "$OUT/background.png"
magick "$OUT/background.png" -define png:color-type=2 -define png:bit-depth=8 -interlace none "$OUT/background.png"

# selected-item bar: solid phosphor green, rounded ends, item_height tall
H=40; tmp=$(mktemp -d)
magick -size 48x$H xc:none -fill '#35D07F' -draw "roundrectangle 0,0 47,$((H-1)) 6,6" "$tmp/hl.png"
magick "$tmp/hl.png" -crop 16x${H}+0+0  +repage "${PNG_RGBA[@]}" "$OUT/highlight_w.png"
magick "$tmp/hl.png" -crop 1x${H}+24+0  +repage "${PNG_RGBA[@]}" "$OUT/highlight_c.png"
magick "$tmp/hl.png" -crop 16x${H}+32+0 +repage "${PNG_RGBA[@]}" "$OUT/highlight_e.png"

# menu panel behind the items: translucent near-black (alpha 0x59 = 35%),
# 9-slice with 12 px rounded borders. Dark enough for the text, light enough
# for the neon mark to show through.
magick -size 48x48 xc:none -fill '#0B0F0D59' -draw "roundrectangle 0,0 47,47 10,10" "$tmp/panel.png"
for spec in "nw 0 0 12 12" "n 12 0 1 12" "ne 36 0 12 12" "w 0 12 12 1" "c 12 12 1 1" "e 36 12 12 1" "sw 0 36 12 12" "s 12 36 1 12" "se 36 36 12 12"; do
  set -- $spec
  magick "$tmp/panel.png" -crop ${4}x${5}+${2}+${3} +repage "${PNG_RGBA[@]}" "$OUT/menu_$1.png"
done

# scrollbar thumb: muted 12 px bar centered in the 32 px column
magick -size 32x40 xc:none -fill '#6B7A72' -draw "roundrectangle 10,0 21,39 6,6" "$tmp/sl.png"
magick "$tmp/sl.png" -crop 32x16+0+0  +repage "${PNG_RGBA[@]}" "$OUT/slider_n.png"
magick "$tmp/sl.png" -crop 32x1+0+20  +repage "${PNG_RGBA[@]}" "$OUT/slider_c.png"
magick "$tmp/sl.png" -crop 32x16+0+24 +repage "${PNG_RGBA[@]}" "$OUT/slider_s.png"

# fonts (GRUB pf2). unifont.pf2 from Artix stays in the dir as CJK fallback.
grub-mkfont -s 20 -o "$OUT/dejavu-sans-mono-20.pf2" "$FONT"
grub-mkfont -s 16 -o "$OUT/dejavu-sans-mono-16.pf2" "$FONT"

# entry icons: the AI-2 tile for the kernel entries (live: class artix.x86_64;
# installed: class from GRUB_DISTRIBUTOR, "artix" or "ai_2")
rsvg-convert -w 32 -h 32 "$DESIGN/ai2-favicon.svg" -o "$tmp/ai2.png"
for n in artix.x86_64 artix.i686 artix ai_2 ai-2 ai2; do
  magick "$tmp/ai2.png" "${PNG_RGBA[@]}" "$OUT/icons/$n.png"
done

cp "$HERE/theme.txt" "$OUT/theme.txt"
rm -rf "$tmp"
echo "GRUB theme built into $OUT"
find "$OUT" -type f | sort
