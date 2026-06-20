"""India-context macro sentiment priors.

FinBERT scores generic financial-English sentiment ("X rises" -> positive, "Y drops"
-> negative) but is blind to the DIRECTIONAL MACRO IMPACT on Indian equities. Two real
misreads it produced: a rising dollar-vs-rupee (rupee depreciation) scored POSITIVE, and
a fuel-price DROP scored NEGATIVE — both backwards for India.

India is a net oil importer with an inflation-sensitive, FII-driven equity market, so the
broad-market sign is frequently the OPPOSITE of the headline's surface verb:
  - rupee WEAKER (dollar up vs rupee)        -> NEGATIVE (imported inflation, FII outflow)
  - crude / fuel prices DOWN                  -> POSITIVE (lower inflation + input costs)
  - inflation / CPI UP                        -> NEGATIVE
  - RBI repo rate CUT                         -> POSITIVE (cheaper credit)
  - FII/FPI INFLOWS                           -> POSITIVE
  - bond yields UP                            -> NEGATIVE (for equities)
  - GDP / growth / GST collections UP         -> POSITIVE
  - trade / fiscal / current-account deficit widening -> NEGATIVE
  - monsoon normal/good                       -> POSITIVE (rural demand, food inflation)

When a headline is PRIMARILY about one of these, this layer overrides FinBERT with the
India-correct sign (flagged in the result as `macro_rule`, never silent). These are
deliberate, well-established economic priors — NOT learned alpha — and operate at the
BROAD-MARKET level (some sectors, e.g. IT/pharma exporters, benefit from a weak rupee;
that nuance is out of scope for a single market-wide sentiment tag). Pure-stdlib regex,
so it also corrects sentiment when FinBERT is unavailable (degraded mode).
"""

import re

# shared direction lexicons (whole text, case-insensitive)
_UP = (r'(?:rise|rises|rising|rose|gain|gains|gaining|gained|jump|jumps|jumped|surge|surges|'
       r'surged|climb|climbs|climbed|soar|soars|soared|spike|spikes|spiked|higher|increase|'
       r'increases|increased|increasing|widen|widens|widened|widening|accelerat\w*|'
       r'strengthen|strengthens|strengthened|appreciat\w*|record high|all-time high|lifetime high)')
_DOWN = (r'(?:fall|falls|falling|fell|drop|drops|dropped|dropping|declin\w*|slump|slumps|slumped|'
         r'slip|slips|slipped|ease|eases|eased|easing|cool|cools|cooled|cooling|lower|decrease|'
         r'decreases|decreased|soften|softens|softened|narrow|narrows|narrowed|narrowing|plunge|'
         r'plunges|plunged|tumble|tumbles|tumbled|sink|sinks|slide|slides|weaken|weakens|'
         r'weakened|depreciat\w*|record low|all-time low|lifetime low)')

_UP_RE = re.compile(_UP, re.I)
_DOWN_RE = re.compile(_DOWN, re.I)

# themes scored purely by direction. up_good = is an UP move good for Indian equities?
_THEMES = [
    ('crude_oil',    r'\b(crude|brent|wti|oil price|oil prices|fuel|petrol|diesel|lpg|gas price)\b', False),
    ('inflation',    r'\b(inflation|cpi|wpi|retail price|consumer price|wholesale price|price rise)\b', False),
    ('bond_yield',   r'\b(bond yield|bond yields|10[- ]?year yield|g-?sec yield|treasury yield|yields?)\b', False),
    ('deficit',      r'\b(trade deficit|current account deficit|fiscal deficit|\bcad\b)\b', False),
    ('gdp_growth',   r'\b(gdp|economic growth|growth forecast|industrial output|\biip\b|factory output|core sector)\b', True),
    ('pmi',          r'\b(pmi|purchasing managers)\b', True),
    ('gst',          r'\b(gst collection|gst collections|gst revenue|tax collection|tax collections)\b', True),
]

# per-rule confidence (deliberate priors; well-established relationships score higher)
_CONF = {
    'rupee_depreciation': 0.85, 'rupee_appreciation': 0.82,
    'crude_oil': 0.85, 'inflation': 0.82, 'bond_yield': 0.78, 'deficit': 0.80,
    'gdp_growth': 0.80, 'pmi': 0.76, 'gst': 0.78,
    'rate_cut': 0.82, 'rate_hike': 0.80, 'fii_inflow': 0.80, 'fii_outflow': 0.82,
    'monsoon_good': 0.76, 'monsoon_deficient': 0.78,
}


# single-token direction lexicons for nearest-subject currency attribution (no bare
# 'low'/'high' — too ambiguous; record-low/high handled as phrases)
_UP_TOK = frozenset((
    'rise rises rising rose gain gains gaining gained jump jumps jumped surge surges surged '
    'climb climbs climbed soar soars soared spike spikes spiked higher up increase increases '
    'increased increasing strengthen strengthens strengthened strengthening appreciate '
    'appreciates appreciated appreciating appreciation').split())
_DOWN_TOK = frozenset((
    'fall falls falling fell drop drops dropped dropping decline declines declined declining '
    'slump slumps slumped slip slips slipped ease eases eased easing cool cools cooled cooling '
    'lower decrease decreases decreased soften softens softened weaken weakens weakened '
    'weakening depreciate depreciates depreciated depreciating depreciation plunge plunges '
    'plunged tumble tumbles tumbled sink sinks sank slide slides slid down').split())

_RUPEE_TOK = {'rupee', 'inr'}
_DOLLAR_TOK = {'dollar', 'usd', 'greenback'}
# explicit USD/INR PAIR phrase: by convention the pair quotes dollars-per-rupee, so the
# pair RISING = rupee weaker (this is the 'dollar vs rupee increases' case)
_PAIR_RE = re.compile(r'\b(usd ?/? ?inr|usdinr|dollar[- ]rupee|rupee[- ]dollar)\b'
                      r'|\b(dollar|usd|greenback)\b[^.]{0,20}\b(vs|versus|against|to)\b[^.]{0,20}\b(rupee|inr)\b', re.I)


def _nearest_dir(words, positions, gap=4):
    """The up/down token closest to any subject position (within `gap`)."""
    best = None
    for i, w in enumerate(words):
        d = 'up' if w in _UP_TOK else ('down' if w in _DOWN_TOK else None)
        if d is None:
            continue
        dist = min((abs(i - p) for p in positions), default=999)
        if dist <= gap and (best is None or dist < best[0]):
            best = (dist, d)
    return best[1] if best else None


def _rupee_sign(t: str):
    """Currency is the most error-prone: the impact is on the RUPEE, but headlines frame
    it via the dollar or the USD/INR pair. We (1) handle record-low/high phrases, (2)
    treat an explicit dollar-rupee PAIR as USD/INR (up = rupee weaker), else (3) attribute
    each direction word to its NEAREST subject (rupee-side vs dollar-side) and resolve."""
    if not re.search(r'\b(rupee|inr|usd ?/? ?inr|usdinr|dollar[- ]rupee)\b', t):
        return 0, None
    if re.search(r'\brupee\b[^.]{0,40}(record low|all-time low|lifetime low|new low|fresh low)', t) \
            or re.search(r'(record low|all-time low|lifetime low|new low|fresh low)[^.]{0,40}\brupee\b', t):
        return -1, 'rupee_depreciation'
    if re.search(r'\brupee\b[^.]{0,40}(record high|all-time high|lifetime high|fresh high)', t) \
            or re.search(r'(record high|all-time high|lifetime high|fresh high)[^.]{0,40}\brupee\b', t):
        return 1, 'rupee_appreciation'
    words = re.findall(r'[a-z]+', t)
    rupee_pos = [i for i, w in enumerate(words) if w in _RUPEE_TOK]
    dollar_pos = [i for i, w in enumerate(words) if w in _DOLLAR_TOK]
    # (2) explicit pair → USD/INR convention
    if _PAIR_RE.search(t):
        d = _nearest_dir(words, rupee_pos + dollar_pos)
        if d == 'up':
            return -1, 'rupee_depreciation'
        if d == 'down':
            return 1, 'rupee_appreciation'
    # (3) nearest-subject attribution
    rdir = _nearest_dir(words, rupee_pos, gap=3)
    if rdir == 'down':
        return -1, 'rupee_depreciation'
    if rdir == 'up':
        return 1, 'rupee_appreciation'
    ddir = _nearest_dir(words, dollar_pos, gap=3)
    if ddir == 'up':
        return -1, 'rupee_depreciation'     # dollar up vs rupee → rupee weaker
    if ddir == 'down':
        return 1, 'rupee_appreciation'
    return 0, None


def _action_sign(t: str):
    """Action-based themes whose sign is the DIRECTION OF ACTION, not an up/down number."""
    if re.search(r'\b(repo rate|rbi|monetary policy|policy rate|interest rate|mpc)\b', t):
        if re.search(r'\b(cut|cuts|cutting|lower|lowers|lowered|reduce|reduces|reduced|ease|eases|easing|slash|slashes|dovish)\b', t):
            return 1, 'rate_cut'
        if re.search(r'\b(hike|hikes|hiked|raise|raises|raised|tighten|tightens|tightening|hawkish)\b', t):
            return -1, 'rate_hike'
    if re.search(r'\b(fiis?|fpis?|foreign (institutional |portfolio )?investors?|foreign funds?)\b', t):
        if re.search(r'\b(inflow|inflows|buy|buys|buying|bought|pour|pours|poured|invest|invests|invested|net buy)\b', t):
            return 1, 'fii_inflow'
        if re.search(r'\b(outflow|outflows|sell|sells|selling|sold|pull out|pulled out|exit|exits|withdraw|withdrew|withdrawn|net sell|offload|offloads)\b', t):
            return -1, 'fii_outflow'
    if re.search(r'\bmonsoon\b', t):
        # check deficient FIRST — 'below normal' contains 'normal' and must not read as good
        if re.search(r'\b(deficient|below normal|below-normal|weak|poor|delay|delayed|deficit|fail|fails|failure|scanty|sluggish)\b', t):
            return -1, 'monsoon_deficient'
        if re.search(r'\b(normal|above normal|good|surplus|abundant|robust|revive|revives|revival|on track|progress|progresses|advance|advances)\b', t):
            return 1, 'monsoon_good'
    return 0, None


def _theme_sign(t: str):
    for name, subj, up_good in _THEMES:
        if not re.search(subj, t, re.I):
            continue
        up, down = bool(_UP_RE.search(t)), bool(_DOWN_RE.search(t))
        if up == down:                      # both or neither direction → ambiguous, skip
            continue
        if up:
            return (1 if up_good else -1), name
        return (-1 if up_good else 1), name
    return 0, None


def adjust(text: str) -> dict | None:
    """If `text` is primarily about a known India-macro theme with a clear direction,
    return the India-correct sentiment override {sentiment, score, rule}; else None.
    Currency first (most error-prone), then action themes, then direction themes."""
    if not text:
        return None
    t = text.lower()
    for fn in (_rupee_sign, _action_sign, _theme_sign):
        sign, rule = fn(t)
        if sign:
            return {'sentiment': 'positive' if sign > 0 else 'negative',
                    'score': _CONF.get(rule, 0.80), 'rule': rule}
    return None
