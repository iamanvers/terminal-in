"""
Claude-distilled REASONING traces for the trade-judge SLM.

Why this exists: the public corpora (sentiment, finance-alpaca) teach facts and
tone, and strategy_pairs.py teaches strategy definitions — but none of them teach
the model the *actual job* the TradePlanner does at inference: read a batch of
pre-screened candidates + portfolio + regime + hindsight, then reason through
approve / reject / size for each one and emit the planner's JSON schema.

This module supplies two complementary Claude-authored sources, folded into the
SFT set by prepare_dataset.py:

  1. PLANNER_TRACES — examples in the planner's EXACT I/O format. The `input`
     mirrors trade_planner._build_messages (REGIME/VIX/EQUITY · OPEN POSITIONS ·
     CANDIDATES · PAST DECISIONS), and the `output` is the verdict JSON
     {"decisions":[...],"market_note":...} with a specific, factor-citing reason
     per decision. Training on these aligns the model with the production task
     under Ollama's format='json' constraint (reasoning lives in `reason`).

  2. REASONING_TRACES — prose chain-of-thought Q&A ("how it ties back"): given a
     setup across technical + regime + portfolio + macro planes, walk through the
     decision step by step. These teach the underlying judgment that the JSON
     `reason` strings compress, and also serve the AI ANALYST chat tab.

Imported by prepare_dataset.py → source 6.  Pure data + renderers, no I/O.
"""

import json

# ── Fixed task framings (match the production system prompt's intent) ──────────

_JUDGE_INSTRUCTION = (
    'You are the final trade judge for an NSE algorithmic trading desk. '
    'Deterministic strategy lenses have pre-screened these candidates. Approve only '
    'the trades worth making (approving everything, or approving correlated bets, is a '
    'failure mode), reject the rest with a specific reason, and size with conviction. '
    'Weigh regime fit, lens convergence, persistence across scans, portfolio '
    'concentration, VIX, and the hindsight record. Respond with ONLY the JSON schema: '
    '{"decisions":[{"symbol":..,"action":"approve|reject","size_factor":0.25-1.5,'
    '"reason":..}],"market_note":..}.'
)

_REASON_INSTRUCTION = (
    'You are a senior NSE trading analyst. Reason step by step through the setup, '
    'tying together the technical, regime, portfolio, and macro factors, and state a '
    'clear verdict with sizing.'
)


# ── 1 · Planner-format scenarios ──────────────────────────────────────────────
# Each scenario renders to one (input, output) pair in the planner's exact format.
# `decisions` reasons are authored to cite specifics the way a good judge would.

PLANNER_SCENARIOS: list[dict] = [
    {
        'regime': 'strong_bull', 'vix': 12.4, 'equity': 1_012_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'RELIANCE', 'side': 'BUY', 'ev': 2.10, 'conf': 0.71, 'persist': 3,
             'lenses': 'S2+S5+MOM', 'rr': 2.4, 'rsi': 63, 'vol': 1.8, 'price': 2940.0},
            {'sym': 'TATAMOTORS', 'side': 'BUY', 'ev': 1.35, 'conf': 0.52, 'persist': 1,
             'lenses': 'MOM', 'rr': 1.6, 'rsi': 69, 'vol': 1.1, 'price': 985.0},
        ],
        'decisions': [
            {'symbol': 'RELIANCE', 'action': 'approve', 'size_factor': 1.2,
             'reason': '3 lenses converge (52W-high S2 + EMA-pullback S5 + momentum), 3-scan '
                       'persistence, RSI 63 still has room, 1.8x volume confirms. strong_bull '
                       'fits all three lenses — size up.'},
            {'symbol': 'TATAMOTORS', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'single lens, persistence 1 (not yet debounced), RSI 69 nearing overbought '
                       'with only 1.1x volume — no conviction. Wait for a second scan.'},
        ],
        'market_note': 'strong_bull, VIX 12 — lean into multi-lens convergence, skip thin single-lens momentum.',
    },
    {
        'regime': 'bull', 'vix': 16.1, 'equity': 998_000, 'throttle': False,
        'positions': [
            {'sym': 'HDFCBANK', 'side': 'BUY', 'qty': 40, 'upnl': 3200},
            {'sym': 'ICICIBANK', 'side': 'BUY', 'qty': 55, 'upnl': 1100},
        ],
        'candidates': [
            {'sym': 'AXISBANK', 'side': 'BUY', 'ev': 1.72, 'conf': 0.61, 'persist': 2,
             'lenses': 'S2+MOM', 'rr': 2.0, 'rsi': 60, 'vol': 1.5, 'price': 1180.0},
            {'sym': 'INFY', 'side': 'BUY', 'ev': 1.65, 'conf': 0.58, 'persist': 2,
             'lenses': 'S5+MOM', 'rr': 1.9, 'rsi': 57, 'vol': 1.4, 'price': 1820.0},
        ],
        'decisions': [
            {'symbol': 'AXISBANK', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'setup is clean on its own, but book already holds HDFCBANK + ICICIBANK '
                       'long — a third bank long is directional crowding (correlation ~0.9). '
                       'Reject to keep sector concentration sane, not because the signal is weak.'},
            {'symbol': 'INFY', 'action': 'approve', 'size_factor': 1.0,
             'reason': 'S5 EMA-pullback + momentum, 2-scan persistence, RSI 57 mid-band, 1.4x '
                       'volume. IT exposure is currently zero — adds genuine diversification vs '
                       'the existing banking book. Approve at full Kelly.'},
        ],
        'market_note': 'bull — book is bank-heavy; prefer cross-sector adds over more financials.',
    },
    {
        'regime': 'high_vol', 'vix': 24.8, 'equity': 965_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'NIFTY 50', 'side': 'BUY', 'ev': 1.90, 'conf': 0.64, 'persist': 2,
             'lenses': 'S8', 'rr': 2.2, 'rsi': 38, 'vol': 1.0, 'price': 22150.0},
            {'sym': 'BAJFINANCE', 'side': 'BUY', 'ev': 1.55, 'conf': 0.56, 'persist': 2,
             'lenses': 'MOM', 'rr': 1.8, 'rsi': 66, 'vol': 1.3, 'price': 7150.0},
        ],
        'decisions': [
            {'symbol': 'NIFTY 50', 'action': 'approve', 'size_factor': 0.5,
             'reason': 'S8 VIX-spike fade is the one lens built for this regime — VIX 24.8 is '
                       'elevated-but-not-circuit, RSI 38 oversold, 2-scan persistence. Approve but '
                       'halve size: high_vol multiplier + wide stops demand it.'},
            {'symbol': 'BAJFINANCE', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'momentum longs are the wrong tool at VIX 24.8 — whippy tape gives '
                       'no follow-through, RSI 66 is late-cycle. high_vol regime says minimal '
                       'directional exposure. Reject.'},
        ],
        'market_note': 'high_vol VIX 24.8 — only the VIX-fade lens earns capital, and at half size.',
    },
    {
        'regime': 'bear', 'vix': 21.0, 'equity': 940_000, 'throttle': True,
        'positions': [
            {'sym': 'SUNPHARMA', 'side': 'BUY', 'qty': 30, 'upnl': -1800},
        ],
        'candidates': [
            {'sym': 'TCS', 'side': 'BUY', 'ev': 1.48, 'conf': 0.55, 'persist': 2,
             'lenses': 'S4', 'rr': 1.7, 'rsi': 31, 'vol': 1.2, 'price': 3820.0},
            {'sym': 'MARUTI', 'side': 'BUY', 'ev': 1.62, 'conf': 0.59, 'persist': 2,
             'lenses': 'S2+MOM', 'rr': 1.9, 'rsi': 64, 'vol': 1.4, 'price': 12800.0},
        ],
        'decisions': [
            {'symbol': 'TCS', 'action': 'approve', 'size_factor': 0.5,
             'reason': 'S4 RSI-reversion on a quality name above its 200EMA is the only setup that '
                       'survives a bear regime — RSI 31 oversold, 2-scan persistence. System is '
                       'throttled, so half-size and treat as a tactical bounce, not a trend bet.'},
            {'symbol': 'MARUTI', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'breakout/momentum long fights the bear regime (S2 regime-fit ~0.1 in bear) '
                       'and the system is throttled after recent losses. Counter-trend breakout = '
                       'reject; the regime has to turn first.'},
        ],
        'market_note': 'bear + throttled — defensive only: quality mean-reversion at half size, no breakouts.',
    },
    {
        'regime': 'sideways', 'vix': 15.5, 'equity': 1_005_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'HINDUNILVR', 'side': 'BUY', 'ev': 1.58, 'conf': 0.57, 'persist': 3,
             'lenses': 'S4', 'rr': 1.8, 'rsi': 34, 'vol': 1.1, 'price': 2380.0},
            {'sym': 'WIPRO', 'side': 'BUY', 'ev': 1.22, 'conf': 0.49, 'persist': 2,
             'lenses': 'MOM', 'rr': 1.4, 'rsi': 58, 'vol': 0.9, 'price': 530.0},
            {'sym': 'ADANIPORTS', 'side': 'BUY', 'ev': 1.41, 'conf': 0.53, 'persist': 1,
             'lenses': 'S2', 'rr': 1.7, 'rsi': 62, 'vol': 1.6, 'price': 1410.0},
        ],
        'decisions': [
            {'symbol': 'HINDUNILVR', 'action': 'approve', 'size_factor': 1.0,
             'reason': 'sideways regime favours mean-reversion: S4 RSI 34 oversold on a defensive '
                       'FMCG name, 3-scan persistence, EV 1.58. Best regime-fit of the three. Full size.'},
            {'symbol': 'WIPRO', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'momentum in a sideways tape is low-edge (ROC near flat), EV 1.22 barely '
                       'clears the bar, sub-1x volume (0.9x) = no participation. Reject.'},
            {'symbol': 'ADANIPORTS', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'persistence 1 (un-debounced) and Adani names mean-revert poorly (political/'
                       'headline risk breaks clean technicals). Pass even though volume is decent.'},
        ],
        'market_note': 'sideways — reward mean-reversion on quality, starve momentum and headline-risk names.',
    },
    {
        'regime': 'bull', 'vix': 14.0, 'equity': 1_020_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'TCS', 'side': 'BUY', 'ev': 2.30, 'conf': 0.74, 'persist': 3,
             'lenses': 'S2+S5+MOM', 'rr': 2.5, 'rsi': 61, 'vol': 2.1, 'price': 3850.0},
            {'sym': 'RELIANCE', 'side': 'BUY', 'ev': 2.05, 'conf': 0.70, 'persist': 3,
             'lenses': 'S2+MOM', 'rr': 2.3, 'rsi': 64, 'vol': 1.7, 'price': 2960.0},
            {'sym': 'INFY', 'side': 'BUY', 'ev': 1.95, 'conf': 0.67, 'persist': 2,
             'lenses': 'S5+MOM', 'rr': 2.1, 'rsi': 59, 'vol': 1.6, 'price': 1840.0},
            {'sym': 'LT', 'side': 'BUY', 'ev': 1.88, 'conf': 0.66, 'persist': 2,
             'lenses': 'S2', 'rr': 2.0, 'rsi': 60, 'vol': 1.5, 'price': 3640.0},
        ],
        'decisions': [
            {'symbol': 'TCS', 'action': 'approve', 'size_factor': 1.2,
             'reason': 'best of the batch — 3-lens convergence, EV 2.30, 2.1x volume, RSI 61. '
                       'strong fit. Size up.'},
            {'symbol': 'RELIANCE', 'action': 'approve', 'size_factor': 1.0,
             'reason': 'S2 breakout + momentum, EV 2.05, 3-scan persistence. Different sector to '
                       'TCS — clean diversification. Full size.'},
            {'symbol': 'INFY', 'action': 'approve', 'size_factor': 1.0,
             'reason': 'EV 1.95, S5+MOM, 2-scan persistence. Third approval — at the cap.'},
            {'symbol': 'LT', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'genuinely good (EV 1.88) but I cap approvals at 3 per scan and the other '
                       'three outrank it on EV/convergence. Reject on the cap, not on merit — '
                       'revisit next scan if it persists.'},
        ],
        'market_note': 'bull, rich opportunity set — approve the 3 highest-conviction, hold the cap, note LT for next scan.',
    },
    {
        'regime': 'bull', 'vix': 17.2, 'equity': 1_000_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'SBIN', 'side': 'BUY', 'ev': 1.44, 'conf': 0.54, 'persist': 2,
             'lenses': 'S2', 'rr': 1.7, 'rsi': 78, 'vol': 1.9, 'price': 840.0},
        ],
        'decisions': [
            {'symbol': 'SBIN', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'breakout with strong 1.9x volume, but RSI 78 is firmly overbought — '
                       'chasing here means buying the top of the move with poor R:R into resistance. '
                       'PSU-bank breakouts also false often. Reject; better entry on a pullback to EMA21.'},
        ],
        'market_note': 'bull — even with volume, RSI 78 is a chase; demand a pullback entry.',
    },
    {
        'regime': 'bull', 'vix': 15.8, 'equity': 1_000_000, 'throttle': False,
        'positions': [],
        'past': [
            'reject BUY SBIN | RSI 77 overbought | hindsight: would_lose (-1.8%) — correct',
            'approve BUY HINDUNILVR | S4 RSI 33 | hindsight: actual_win (+2.6%) — correct',
        ],
        'candidates': [
            {'sym': 'SBIN', 'side': 'BUY', 'ev': 1.50, 'conf': 0.56, 'persist': 2,
             'lenses': 'S2+MOM', 'rr': 1.8, 'rsi': 76, 'vol': 1.7, 'price': 855.0},
            {'sym': 'NESTLEIND', 'side': 'BUY', 'ev': 1.62, 'conf': 0.58, 'persist': 3,
             'lenses': 'S4', 'rr': 1.9, 'rsi': 35, 'vol': 1.2, 'price': 2510.0},
        ],
        'decisions': [
            {'symbol': 'SBIN', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'same overbought breakout pattern the hindsight log just flagged: last SBIN '
                       'reject at RSI 77 would_lose -1.8%. RSI 76 again, near resistance. The record '
                       'says do not chase this — reject.'},
            {'symbol': 'NESTLEIND', 'action': 'approve', 'size_factor': 1.0,
             'reason': 'mirrors the HINDUNILVR pattern that won +2.6%: S4 RSI-reversion (RSI 35) on '
                       'a defensive name with 3-scan persistence. The hindsight record supports this '
                       'archetype. Full size.'},
        ],
        'market_note': 'bull — leaning on hindsight: oversold-quality reversion is paying, overbought PSU chases are not.',
    },
    {
        'regime': 'strong_bull', 'vix': 13.1, 'equity': 1_050_000, 'throttle': False,
        'positions': [
            {'sym': 'TCS', 'side': 'BUY', 'qty': 25, 'upnl': 4200},
            {'sym': 'RELIANCE', 'side': 'BUY', 'qty': 30, 'upnl': 2600},
        ],
        'candidates': [
            {'sym': 'TCS', 'side': 'BUY', 'ev': 2.00, 'conf': 0.69, 'persist': 3,
             'lenses': 'S2+MOM', 'rr': 2.3, 'rsi': 62, 'vol': 1.8, 'price': 3900.0},
        ],
        'decisions': [
            {'symbol': 'TCS', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'signal is strong, but the book is already long TCS (+4200 unrealized). '
                       'Pyramiding into an existing winner is blocked at the gate anyway and '
                       'concentrates single-name risk. Reject — let the runner run with its trailing stop.'},
        ],
        'market_note': 'strong_bull — no adding to an existing TCS long; manage the winner, do not stack it.',
    },
    {
        'regime': 'bull', 'vix': 18.5, 'equity': 1_000_000, 'throttle': False,
        'positions': [],
        'candidates': [
            {'sym': 'CIPLA', 'side': 'BUY', 'ev': 1.33, 'conf': 0.51, 'persist': 2,
             'lenses': 'S5', 'rr': 1.6, 'rsi': 55, 'vol': 1.0, 'price': 1490.0},
            {'sym': 'DRREDDY', 'side': 'BUY', 'ev': 1.28, 'conf': 0.50, 'persist': 2,
             'lenses': 'S4', 'rr': 1.5, 'rsi': 40, 'vol': 1.0, 'price': 6200.0},
        ],
        'decisions': [
            {'symbol': 'CIPLA', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'marginal: EV 1.33 just over the bar, conf 0.51, volume exactly 1.0x (no '
                       'participation). Nothing wrong, but nothing compelling — in a bull tape I '
                       'can do better. Reject the mediocre.'},
            {'symbol': 'DRREDDY', 'action': 'reject', 'size_factor': 1.0,
             'reason': 'same story — EV 1.28 is the weakest in the batch, flat volume. Both pharma '
                       'names are low-conviction; preserve capital for a real setup rather than '
                       'forcing activity.'},
        ],
        'market_note': 'bull — a thin batch; rejecting both is correct. Not trading is a position.',
    },
]


def _render_planner_input(s: dict) -> str:
    cand_lines = [
        f"{c['sym']} {c['side']} ev={c['ev']:.2f} conf={c['conf']:.2f} "
        f"persist={c['persist']} lenses={c['lenses']} rr={c['rr']:.1f} "
        f"rsi={c['rsi']:.0f} vol={c['vol']:.1f}x price={c['price']:.1f}"
        for c in s['candidates']
    ]
    pos = s.get('positions') or []
    pos_lines = [f"{p['sym']} {p['side']} qty={p['qty']} upnl={p['upnl']:+.0f}" for p in pos] or ['none']
    block = (
        f"REGIME: {s['regime']} | VIX: {s['vix']:.1f} | EQUITY: {s['equity']:,.0f}\n"
        + ('SYSTEM THROTTLED (recent losses) — be extra selective.\n' if s.get('throttle') else '')
        + 'OPEN POSITIONS:\n' + '\n'.join(pos_lines) + '\n'
        + 'CANDIDATES:\n' + '\n'.join(cand_lines)
    )
    if s.get('past'):
        block += '\nPAST DECISIONS (hindsight):\n' + '\n'.join(s['past'])
    return block


def _render_planner_output(s: dict) -> str:
    return json.dumps(
        {'decisions': s['decisions'], 'market_note': s['market_note']},
        ensure_ascii=False,
    )


# ── 2 · Prose chain-of-thought reasoning ("how it ties back") ─────────────────

REASONING_TRACES: list[tuple[str, str]] = [
    (
        "A momentum breakout fires on TATASTEEL (RSI 71, 1.9x volume, EV 1.7) but the HMM "
        "regime just flipped to high_vol with India VIX at 25. Walk through whether to take it.",
        """Step 1 — Regime first. high_vol (VIX 25) is the single most important input here. The 6-state model assigns momentum/breakout lenses a regime-fit near 0.3 in high_vol — these setups need follow-through, and follow-through is exactly what a whippy 25-VIX tape denies. So the regime is already arguing against the trade before I look at the signal quality.

Step 2 — Signal quality in isolation. RSI 71 is overbought; 1.9x volume is real participation but at a stretched RSI that often marks a blow-off rather than a base breakout. EV 1.7 is decent but EV is computed on historical conditions, not this volatility.

Step 3 — Tie it together. A genuinely good breakout signal in the wrong regime is still the wrong trade. The volatility multiplier (high_vol = 0.2x size) is the system telling me the same thing quantitatively. Even if I believed the direction, position sizing would shrink it to noise.

Step 4 — Verdict. Reject, or at most take 0.2x size with a stop well beyond one ATR. The cleaner action is reject: in high_vol the only lens that earns capital is the VIX-spike fade (S8), which is a *mean-reversion* bet, not a momentum chase. Wait for VIX to come back under ~18 before trusting breakouts again.""",
    ),
    (
        "Explain how you'd decide between two equally-ranked BUY candidates (both EV ~1.8, "
        "both 2-scan persistence) when the portfolio already holds two banking longs.",
        """The EV and persistence are a tie, so the deciding factor moves up a level — to portfolio construction, not signal strength.

Factor 1 — Correlation / sector overlap. If candidate A is a third bank (say AXISBANK) and B is in IT or FMCG, they are not equivalent additions. Two bank longs already mean ~0.9 pairwise correlation; a third turns three independent-looking bets into one leveraged bet on the banking sector and on FII flows into financials. The M2 gate's directional-crowding check (≥3 same-sector same-direction) would likely reject A anyway.

Factor 2 — Marginal diversification. B reduces portfolio variance for the same expected return — that is free Sharpe. In a mean-variance sense, the lower-correlation add is strictly better even at identical standalone EV.

Factor 3 — Regime cross-check. If the regime favours the sector B sits in (e.g. IT in a bull tech tape), that tilts further toward B.

Verdict: approve B at full size, reject A with the reason 'sector concentration — book already bank-heavy', and note that A's rejection is about the book, not the setup. If a bank slot later opens (one of the existing longs closes), A can be revisited.""",
    ),
    (
        "The system has taken 4 consecutive losses today and the supervisor has thrown a "
        "throttle. A clean S4 RSI-reversion setup appears (RSI 30, above 200EMA, EV 1.6). "
        "How does the throttle change your judgment?",
        """The throttle is a control-system signal, not a market signal — it changes the bar, not the setup.

Step 1 — What the throttle means. Five-ish consecutive losses is evidence that either the regime read is wrong, slippage is worse than modelled, or variance is simply against me today. None of those are fixed by trading more. The throttle exists to cut exposure while the edge is unverified.

Step 2 — Judge the setup honestly anyway. S4 RSI-reversion at RSI 30 on a name above its 200EMA is a textbook high-probability bounce — the best archetype to take when you must take something, because it's mean-reverting (doesn't need a trending tape) and defined-risk (stop below the 200EMA).

Step 3 — Reconcile. So this isn't a reject; it's an approve-but-shrink. Throttle says raise the EV bar (this clears it at 1.6) and halve size. I'd approve at size_factor 0.5, tight stop, and treat it as a probe that also tells me whether the tape is starting to cooperate again.

Step 4 — Guardrail. If this one also loses, the loss counter approaches the hard-stop (8 → KillSwitch). I respect that — the supervisor, not my conviction, governs when to stop. Verdict: approve at half size, no exceptions to the stop.""",
    ),
    (
        "Company-news plane: a stock you hold reports earnings tomorrow, but a fresh momentum "
        "signal also fires on it today. Reconcile the technical and event planes.",
        """This is a case where two data planes disagree and the event plane wins.

Technical plane says: momentum is intact, add or hold. Event plane says: a binary, unpredictable outcome lands in <24h.

The reconciliation rule is that earnings convert a probabilistic edge into a coin flip. Whatever the technical EV was, it was estimated on normal sessions, not on a gap that can be ±8% on a result. My edge is in repeatable, modellable setups — an earnings gap is neither. The M2 event-mask check blocks entries within the event window for exactly this reason.

So: reject the new momentum entry (don't initiate risk into a binary). For the *existing* position, the decision is about the original thesis, not the new signal — if it's a positional CNC winner with a trailing stop, I'd consider trimming to half into the print to bank gains and cut gap risk, letting the rest ride on the trailing stop. The new signal doesn't get acted on; it just confirms the name still has momentum, which I already own. Verdict: no new entry; manage the existing book down, not up, into the event.""",
    ),
    (
        "Why is rejecting every candidate in a scan sometimes the correct judgment, and how do "
        "you defend that against the pressure to 'do something'?",
        """Rejecting the whole batch is correct whenever no candidate clears the bar that *this* regime and *this* book justify — and cash is itself a position.

The reasoning chain: every trade has a cost (slippage + ₹20/order + the risk-budget it consumes and the correlation it adds). A marginal setup — EV barely over 1.2, 1.0x volume, single lens, un-debounced persistence — has an expected value that, after costs and after the variance it injects, is roughly zero or negative. Taking ten of those doesn't diversify into an edge; it launders fees into losses.

The pressure to 'do something' is a behavioural bias (action bias), and the system is explicitly designed to resist it: the persistence debounce, the EV hysteresis band, the confidence EMA, and the approve-cap all exist to make *not* trading the default and trading the exception. The supervisor's throttle does the same at the portfolio level.

So I defend a full-reject scan by pointing at the bar: 'none of these cleared conviction in this regime; forcing a trade here is negative-EV after costs.' The right next action is to wait for the next scan — good setups recur; capital spent on bad ones doesn't. A judge that never returns an empty verdict isn't judging.""",
    ),
    (
        "Tie together the relational/graph plane: NIFTY is up but breadth is narrow (advance-"
        "decline 0.7, only mega-caps rising). A mid-cap breakout signal fires. What does the "
        "breadth context do to your decision?",
        """Breadth is the relational plane telling me the index move is not broad-based — and that directly undercuts a mid-cap breakout.

Step 1 — Read the divergence. NIFTY green with A/D at 0.7 means a handful of heavyweights (Reliance, HDFCBank, the index-movers) are carrying the tape while most stocks fall. The 'market' looks bullish; the median stock is not. This is classic late-cycle / distribution behaviour.

Step 2 — Map to the candidate. A mid-cap breakout depends on the broad risk appetite that breadth measures. With money concentrating into mega-caps, mid-caps are where liquidity is *leaving*. A breakout there is more likely to be a false break — thin participation, no rotation to sustain it.

Step 3 — Tie back. The same signal in a >1.5 breadth tape (broad participation) would be a high-quality momentum add; in a 0.7 tape it's a trap. The technical plane and the relational plane disagree, and breadth is the better forward indicator of follow-through.

Verdict: reject the mid-cap breakout, or demand a much higher bar (multi-lens + 2.5x volume + a sector index also breaking out). Narrow breadth is a regime caution that the HMM may not yet have flipped on — I front-run it by tightening selectivity, especially down the cap curve.""",
    ),
    (
        "How should position size scale across the six HMM regimes, and what's the reasoning "
        "behind the multipliers rather than a fixed size?",
        """Fixed sizing ignores that the *distribution* of outcomes changes with regime, not just the mean. The multipliers (strong_bull 1.2, bull 1.0, sideways 0.7, bear 0.5, strong_bear 0.3, high_vol 0.2) scale exposure to the regime's risk-adjusted reward.

The reasoning, plane by plane:
- strong_bull / bull: trends persist, drawdowns are shallow, breakouts follow through. Realized volatility is low, so the same rupee stop corresponds to a smaller % move — I can carry more notional for the same risk. Hence ≥1.0x.
- sideways (0.7): no directional edge; most of the return comes from mean-reversion which has smaller, choppier payoffs. Cutting size preserves capital for when a trend resumes.
- bear / strong_bear (0.5 / 0.3): downside skew dominates, gaps go against longs, and correlations spike (everything falls together), so diversification stops working when you need it most. Smaller size is the only honest hedge for a long-biased book.
- high_vol (0.2): outcome variance is so wide that even correct direction gets stopped by intraday noise. Tiny size keeps any single bad fill from mattering.

The deeper point: this is volatility-targeting in disguise. By shrinking size as the regime's volatility and tail-risk rise, I hold roughly constant *risk* per trade rather than constant *notional* — which is what produces a smoother equity curve and survives the regimes that blow up fixed-size books. The 3-day hysteresis on regime changes stops the multiplier from flip-flopping on a single noisy day.""",
    ),
    (
        "A pairs signal says short HDFCBANK / long ICICIBANK at z-score +2.3. What checks across "
        "fundamentals and events would make you reject an otherwise valid statistical signal?",
        """The z-score is the statistical plane saying 'spread is stretched, expect reversion.' But pairs trading's fatal failure is a spread that's stretched because the relationship genuinely *broke*, not because it's noise. So I check whether the divergence is mean-reverting or structural.

Reject checks:
1. Earnings / events. If either bank reports within ~10 days, a result can re-rate one leg permanently — the spread won't revert, it'll re-base. Event-mask the trade.
2. Cointegration freshness. If a re-run of the Engle-Granger test shows p > 0.10 (cointegration weakening), the historical relationship I'm betting on is decaying. Reject — the z-score is meaningless without cointegration.
3. Idiosyncratic news. RBI action affecting one bank differently (a penalty, a merger, an asset-quality disclosure), management change, large block deal. Any of these is a fundamental reason the cheap leg is cheap.
4. Regime. Around RBI MPC meetings the whole banking complex can move on policy in ways that break pairwise relationships short-term.

If all clear, the trade is valid: dollar-neutral legs, stop at z ±3.5 (relationship-broken exit), target z→0. The discipline is that a pure statistical signal must be vetoed by the fundamental/event planes — 'the spread is wide' is necessary but never sufficient. Verdict: approve only if no earnings within 10 days and cointegration p < 0.05; otherwise reject and wait.""",
    ),
]


# ── Public builders (consumed by prepare_dataset.py) ──────────────────────────

def planner_trace_samples() -> list[dict]:
    """Planner-format I/O pairs (instruction + scenario input → verdict JSON)."""
    out = []
    for s in PLANNER_SCENARIOS:
        inp = _render_planner_input(s)
        resp = _render_planner_output(s)
        text = (
            f'### Instruction:\n{_JUDGE_INSTRUCTION}\n\n'
            f'### Input:\n{inp}\n\n'
            f'### Response:\n{resp}'
        )
        out.append({'instruction': _JUDGE_INSTRUCTION, 'input': inp, 'output': resp, 'text': text})
    return out


def reasoning_trace_samples() -> list[dict]:
    """Prose chain-of-thought reasoning pairs."""
    out = []
    for question, answer in REASONING_TRACES:
        text = (
            f'### Instruction:\n{_REASON_INSTRUCTION}\n\n'
            f'### Input:\n{question}\n\n'
            f'### Response:\n{answer}'
        )
        out.append({'instruction': _REASON_INSTRUCTION, 'input': question, 'output': answer, 'text': text})
    return out


def all_samples() -> list[dict]:
    return planner_trace_samples() + reasoning_trace_samples()


if __name__ == '__main__':
    s = all_samples()
    print(f'{len(s)} reasoning samples '
          f'({len(planner_trace_samples())} planner-format + {len(reasoning_trace_samples())} prose)')
    print('\n--- sample planner trace ---\n')
    print(s[0]['text'][:900])
