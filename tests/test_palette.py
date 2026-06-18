"""Palette-consistency audit — PRD "Design maturation" (PR-blocking ratchet).

The design system is a single source of truth: ``terminal_ui/lib/theme.ts`` +
``terminal_ui/styles/globals.css``. Inline hex colour literals scattered through
``app/`` and ``components/`` are how a palette drifts. Fully tokenising 800+
existing literals is a large, visually-risky migration, so this guard enforces
the direction instead of a big-bang:

  1. RATCHET — the total count of hex literals outside the design-system files
     may never EXCEED the recorded baseline. New code must use THEME tokens; the
     baseline only moves DOWN as literals are migrated (lower it when you do).
  2. OFF-PALETTE — the number of DISTINCT colours that do not resolve to a
     sanctioned palette value (a THEME token or a globals.css custom property)
     may never exceed its baseline either: a brand-new rogue colour fails here.

When this test fails it prints exactly which file/colour pushed the count up.
"""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / 'terminal_ui'

# Baselines captured 2026-06-14; ratcheted down 2026-06-18 (HoldingsPanel color
# consts). RATCHET DOWN ONLY — never raise these.
BASELINE_TOTAL = 815
BASELINE_OFF_DISTINCT = 36

_HEX = re.compile(r'#[0-9A-Fa-f]{3,8}\b')


def _base(h: str) -> str:
    """Normalise a hex token to a lowercase 6-digit base (drop alpha, expand #abc)."""
    h = h.lower().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    elif len(h) == 4:                 # #rgba → rgb
        h = ''.join(c * 2 for c in h[:3])
    elif len(h) == 8:                 # #rrggbbaa → rrggbb
        h = h[:6]
    return h


def _palette() -> set[str]:
    allowed: set[str] = set()
    for rel in ('lib/theme.ts', 'styles/globals.css'):
        text = (UI / rel).read_text(encoding='utf-8')
        allowed |= {_base(m) for m in _HEX.findall(text)}
    return allowed


def _scan():
    allowed = _palette()
    total = 0
    off: dict[str, list[str]] = {}
    files = []
    for sub in ('app', 'components'):
        for ext in ('*.tsx', '*.ts', '*.css'):
            files += list((UI / sub).rglob(ext))
    for path in files:
        for m in _HEX.findall(path.read_text(encoding='utf-8')):
            total += 1
            b = _base(m)
            if b not in allowed:
                off.setdefault(b, []).append(path.relative_to(UI).as_posix())
    return total, off


def test_no_new_hex_literals():
    total, _ = _scan()
    assert total <= BASELINE_TOTAL, (
        f'Hex-literal count rose to {total} (baseline {BASELINE_TOTAL}). '
        'Use THEME tokens from lib/theme.ts instead of inline hex. If you '
        'genuinely reduced the count, lower BASELINE_TOTAL to ratchet.')


def test_no_new_offpalette_colors():
    _, off = _scan()
    distinct = sorted(off)
    assert len(distinct) <= BASELINE_OFF_DISTINCT, (
        f'Distinct off-palette colours rose to {len(distinct)} '
        f'(baseline {BASELINE_OFF_DISTINCT}). New rogue colours:\n' +
        '\n'.join(f'  #{c}  in {sorted(set(off[c]))[:3]}' for c in distinct))
