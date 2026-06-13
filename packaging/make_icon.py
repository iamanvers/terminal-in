"""Render the TERMINAL//IN logo (terminal_ui/app/icon.svg) to a multi-size
Windows .ico for the packaged exe + native window. Pure Pillow — no SVG dep.
Run: .venv/Scripts/python.exe packaging/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 16  # supersample factor from the 64px viewBox → 1024px master
N = 64 * S
OUT = Path(__file__).parent / 'terminalin.ico'


def r(*v):  # scale a tuple of viewBox units
    return [x * S for x in v]


def main() -> None:
    img = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # dark tile + steel border
    d.rounded_rectangle(r(0, 0, 64, 64), radius=14 * S, fill='#0A0B0D')
    d.rounded_rectangle(r(1, 1, 63, 63), radius=13 * S, outline='#23272E', width=2 * S)

    # candle bars (body + wick) in the electric-blue ramp
    bars = [
        ('#004AF8', (12, 30, 19, 46), (15, 25, 16.6, 46)),
        ('#0094FB', (26, 20, 33, 40), (29, 14, 30.6, 40)),
        ('#00B9FC', (40, 12, 47, 28), (43, 7, 44.6, 35)),
    ]
    for col, body, wick in bars:
        d.rounded_rectangle(r(*body), radius=int(1.5 * S), fill=col)
        d.rectangle(r(*wick), fill=col)

    # double-slash glyph, round caps
    w = int(3.4 * S)
    for x0, y0, x1, y1 in [(36, 56, 44, 40), (45, 56, 53, 40)]:
        p0, p1 = (x0 * S, y0 * S), (x1 * S, y1 * S)
        d.line([p0, p1], fill='#ECEEF1', width=w)
        for px, py in (p0, p1):
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill='#ECEEF1')

    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(OUT, format='ICO', sizes=sizes)
    print(f'wrote {OUT} ({", ".join(f"{s[0]}" for s in sizes)})')


if __name__ == '__main__':
    main()
