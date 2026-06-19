# Alpha findings — does this system capture alpha? (honest record)

> Status as of 2026-06-19. This document records what the validation harness
> (`terminal_in/backtest/validation.py`) has actually proven, out-of-sample,
> net of real Indian transaction costs. It is deliberately blunt: a clean
> negative is a result, and chasing the numbers until they pass is the
> overfitting trap (WORLD_MODEL.md §8). Every number here is walk-forward-fenced
> unless explicitly labelled in-sample.

## Headline

**Nothing tested survives proper scrutiny** — nine independent negatives now. Long-only
directional signals are indistinguishable from passive. The cross-sectional
market-neutral frame (the right one for *selection* skill) gave two apparent pulses —
1-month **reversal** (large-cap) and 12-1 **momentum** (wide large+midcap universe) — but
**both DIE under hardening** (realistic futures+borrow cost, square-root market impact, and
a **deflated Sharpe that corrects for the horizon search**): reversal large-cap DSR 0.605,
reversal wide 0.290, and momentum wide **0.867 < 0.95** — the closest any factor has come,
but still short, *and* flattered by survivorship (the wide universe is today's survivors).
The fenced *dynamic* variants don't rescue it. The bottleneck is **signal, not model or
reasoning** — confirmed nine ways now.

**One genuine open lead (not a negative): the FUNDABLE long-only momentum tilt.** The
hardened deaths above are *market-neutral* books (futures short leg, unfundable on midcaps).
The form a real account can trade — long-only momentum vs equal-weight — shows a **+0.63
risk-adjusted excess at beta 1.06** on the wide universe (reversal's is exactly 0.00 = pure
beta). That is *not* size/beta and is the strongest fundable result the program has produced.
It is gated by **survivorship** (momentum's worst bias; the wide universe is today's survivors)
and an un-deflated long-only significance test — so it's a LEAD pending the point-in-time
midcap-membership fix, not an established edge. See "BUT the FUNDABLE form is not pure beta".

The single most important number: over 10 years (67 symbols, 1,484 trades), the
full decision stack returns **~3% CAGR net** while **buy-and-hold NIFTY returns
~11.6%** and **equal-weighting the same 67 names returns ~21%**. The machinery
*subtracts* ~18 points of CAGR versus simply owning the basket — it is a
low-turnover, cash-heavy filter that mostly keeps capital *out* of the market
during the decade equities ran.

## The negatives

| # | Experiment | Harness | Result (OOS, net) |
|---|-----------|---------|-------------------|
| 1 | Price-only technical strategy | `validation.py` | net Sharpe **0.57** < NIFTY 0.76 < equal-weight 1.07; 53rd pct vs random-symbol null; only MOM survives multiple-testing |
| 2 | LLM / planner marginal value | `validation.py` (planner isolation) | planner adds **+0.0155 Sharpe, within ±0.067 noise** — decorative |
| 3 | Learned forward EV head (D₀, LightGBM, 78k point-in-time labels) | `validation.py --m6` | net Sharpe **−0.02** vs heuristic +0.44; loses to buy-hold; **0 DSR survivors**; features led by VIX/sector (not relearning the heuristic — the signal simply isn't there) |
| 4 | Directional competence weighting (Phase C) | `validation.py --m6` | **abstains the winners** (abstained trades +0.0027 vs kept −0.0006); net Sharpe 0.44→0.03 |
| 5 | Event-reaction / PEAD plane (NSE archive, 87k events) | `validation.py --events` | **no OOS lift** (Δ −0.064 within ±0.20); PEAD core flat: corr(reaction, fwd-ret) = **0.004**; 0 DSR survivors |
| 5b | VIX-conditioned reaction matrix | `m6/reaction.py` | OOS dir-hit **0.515**, corr(expected, realized drift) **−0.0008**; no VIX pocket |
| 6 | Cross-sectional market-neutral (A1 IC + A2 L/S) | `validation.py --longshort` | 12-1 momentum **null** (IC-IR 0.88, L/S −8%); 1-month **reversal = the first PULSE** — IC +0.039, **IC-IR +1.96**, market-neutral L/S net **+58% / Sharpe 0.39** over 10y (but fails hardening — see below) |
| 7 | Directional long/short across OUR signals | `validation.py --longshort-directional` | **the system's own lens score has NEGATIVE cross-sectional IC (−1.35)** — lens-favoured names underperform equal-weight (excess Sharpe −1.20); shorting adds no edge (L/S Sharpes lens −0.81, reversal 0.39, mom 0.04; short-leg contribution ≈0 and sign-unstable) |
| 8 | F&O variance-risk-premium harvester (monthly NIFTY iron condor) | `backtest/fno_engine.py` | 75% win but CAGR **+0.74% / Sharpe 0.13 / −25% DD** *theoretical* (BS premiums, upper bound) — worse than cash |
| 9 | Cross-sectional factors HARDENED (reversal + 12-1 momentum, wide universe) | `validation.py --longshort --hard [--wide] [--mom]` | every fundable book DIES on Deflated Sharpe: reversal large **0.605**, reversal wide **0.290**, momentum wide **0.867** (< 0.95) — and momentum is survivorship-flattered |

## The one non-null: cross-sectional 1-month reversal (a lead, not an edge)

The right frame for *selection* skill is cross-sectional and market-neutral — "rank
names against each other," not "out-return a bull index" (long-only structurally
can't). Tested on the 67-name universe, rebalanced every 20 days, **short leg via
single-stock futures** (Indian cash can't hold overnight shorts), benchmark = cash/0:

- **12-1 momentum: null** (IC-IR 0.88; crashes at regime turns — negative IC 2020/2022).
- **1-month reversal: the first signal with a pulse** — mean IC +0.039, **IC-IR +1.96**
  (positive in 8/10 years), dollar-neutral L/S net **+58% total / Sharpe 0.39** over 10y.

Why this is a *lead*, not a green light — read every caveat:
1. **IC-IR 1.96 is just under the 2-SE bar** — borderline, best-of-two-signals (mild
   multiple-testing), not slam-dunk significant.
2. **Sharpe 0.39 with −31% max drawdown** is mediocre risk-adjusted (Calmar ≈ 0.1).
3. **80% turnover/rebalance** → highly sensitive to the short-leg cost estimate
   (~6 bps futures, flagged) and to real market-impact our flat slippage understates.
4. Requires a **market-neutral single-stock-futures book the system does not run**, and
   assumes every bottom-quintile name is F&O-eligible (not always true).

Honest status: this is the *structure the literature points to* (cross-sectional +
market-neutral), and it was the only thing that wasn't flat at first look — so we
**hardened it before any engine work** (`validation.py --longshort --hard`):

- **Capacity (sqrt market-impact vs AUM):** net Sharpe +0.44 at ₹10L, +0.43 at ₹1cr,
  +0.38 at ₹10cr, +0.23 at ₹100cr. At retail scale impact is *not* the killer.
- **Deflated Sharpe (corrects for the 5-horizon search): 0.724 → FAILS** (<0.95). The
  undeflated per-period Sharpe is only ~0.12 (PSR ≈ 0.90, already borderline); after
  deflation the tradeable edge is not significant. The IC-IR 1.96 was largely
  best-of-five selection.
- **Fenced dynamic reversal makes it worse:** walk-forward horizon selection → Sharpe
  0.24; a-priori regime-conditioning (trade only non-strong-bull tape, 61% in-market) →
  0.28. Both below the static 0.44 — i.e. the static 21d only looked best in hindsight,
  and adapting OOS doesn't recover it.

**Verdict: the reversal is not a deployable edge** — do NOT build an engine sleeve for
it. This is precisely why hardening precedes engine integration: we spent a few CPU
seconds instead of weeks of futures-execution plumbing to learn it.

### Decomposition — where the reversal "edge" actually lived (and why it's not alpha)

Because a market-neutral single-stock-futures book is **not fundable at ₹10L** (lot
sizes ≈ ₹5–10L notional, ~₹1–2L margin each; a diversified 13×13 book needs ₹30L+), we
checked the only retail-fundable form — **long-only "buy recent losers" (cash CNC)** —
and decomposed the spread:

| 10y, net | total | Sharpe | beta |
|---|--:|--:|--:|
| Long-only reversal (buy losers) | +513% | 1.01 | 1.10 |
| **Equal-weight universe** (correct long-only benchmark) | +410% | **1.11** | — |
| NIFTY (cap-weighted) | +148% | 0.68 | — |

- The reversal spread came **entirely from the long leg** (losers − market +0.0045/reb);
  the **short leg was a drag** (market − winners **−0.0012/reb** — recent winners kept
  winning). So shorting *hurts* — there is no short-side edge to fund.
- Long-only "buy losers" makes more *raw* return than equal-weight but at a **lower
  Sharpe (1.01 < 1.11)** — it merely takes more beta (1.10) and vol. **Not risk-adjusted
  alpha.** The beta-stripped (market-neutral) version is ~0 and fails the DSR.
- The one robust outperformance anywhere is **not a signal**: equal-weight (Sharpe 1.11)
  ≫ cap-weighted NIFTY (0.68) — a **weighting/size effect**, and even that is
  **survivorship-inflated** (equal-weighting *today's* index back to 2016 overweights the
  smaller names that survived/were promoted). It is not skill this system adds.

Net: the one-month reversal does **not** work as risk-adjusted alpha in any fundable
form. The only thing beating the index is passive equal-weighting — a portfolio
construction choice, not selection — and it is biased upward by survivorship.

### Directional long/short across our signals (`--longshort-directional`)

The sharpest finding about the system itself: **the lens score has NEGATIVE
cross-sectional IC (IC-IR −1.35).** Ranking names by how much the lenses like them is
*worse than random* — the lens-favoured names underperform even naive equal-weighting
(excess Sharpe −1.20). It's coherent: 3 of 4 lenses (S2 breakout, S5 pullback-in-uptrend,
MOM) buy recent **strength**, which mean-reverts over the next month — so the lenses
systematically pick names about to fade. That is *why* the long-only stack loses to
passive. Shorting adds no edge either (L/S net Sharpe: lens −0.81, reversal 0.39,
momentum 0.04; the short-leg contribution is ≈0 and flips sign across H=20/21 — noise).
**Conclusion: long/short across our signals yields no deployable edge** — confirmed in
the backtest layer before any short-execution plumbing was built.

## F&O — variance-risk-premium harvester (negative #8)

The one *options* idea with a documented structural edge prior is selling index
variance (the short-vol risk premium). Tested as a **monthly NIFTY short iron
condor** over 10y of real NIFTY + India-VIX daily bars (`terminal_in/backtest/fno_engine.py`),
shorts placed at the **VIX-implied ~1-SD expected move** (the principled placement —
fixed-step shorts sit ~0.75% OTM and lose 72% of months), 4-step wings, sized to
~5% defined risk/cycle, with a realistic NSE-options cost estimate at entry+exit:

- **118 cycles, 75.4% win rate** (correct for 1-SD condors), **+7.5% TOTAL over 10y
  → CAGR +0.74%, Sharpe 0.13, max drawdown −25.3%.** Economically negligible — a
  worse risk-adjusted return than holding cash, with index-like drawdowns.

And this is the **theoretical UPPER BOUND**: premiums are Black-Scholes from real
spot + VIX (no real bid/ask, no smile/term dynamics, no early-assignment or
liquidity), and theoretical pricing *systematically flatters short-premium sellers*
— it can't see the fat tails and slippage that actually bite. The real-world number
is almost certainly worse, likely negative. **Verdict: not a deployable edge** — the
F&O strategies (condor, futures pair, covered call, straddle, spreads) are built and
risk-capped as honest CAPABILITIES, not as an alpha source. Eighth independent
negative; the variance premium, our best options prior, joins the list.

## Universe capacity — adding mid / small caps (evaluation)

Would a broader universe help? Cross-sectional alpha (especially reversal) is documented
*stronger* in less-covered names, so more breadth = more dispersion to rank. But for a
turnover-heavy market-neutral book the frictions bite hardest exactly there:
- **Liquidity/impact:** mid/small spreads + depth make real slippage far exceed our flat
  model; the 80%-turnover reversal book is the worst case for impact cost.
- **Shortability:** the short leg needs futures; F&O covers ~190 names. Most small-caps
  and many mid-caps are **not F&O-eligible → cannot be shorted** → the neutral book breaks.
- **Survivorship/data:** today's mid/small list is heavily survivor-skewed (many 2016
  names died/were relegated); yfinance adjustment is messier. Bias would dominate.
- **Cost:** none are backfilled — a real ingest project.

**Recommendation:** add the **Nifty Midcap 150 (F&O-eligible, liquid subset)** to the
cross-sectional ranking + long sleeve to widen dispersion where reversal is strongest and
most names remain shortable; **avoid small-caps** for the neutral book. Do this ONLY after
(a) point-in-time index membership incl. delisted names (fix survivorship) and (b) a
liquidity-aware impact model replaces flat slippage — otherwise any mid/small "alpha" is
mostly bias.

### RAN IT (2026-06-18): wide universe (large 67 + 84 midcap), `--longshort --wide`

Added the research midcap universe and re-ran the cross-sectional test. The picture
**flips** vs large-cap-only: cross-sectional **MOMENTUM strengthens** (12-1: IC-IR
0.78→**1.99**, L/S net Sharpe 0.10→**0.58**, +108% / −28% DD) while **reversal weakens**
(IC-IR 2.10→1.13, Sharpe 0.30→0.09). Tempting — but **almost certainly a survivorship
artifact, NOT an edge**, for the textbook reason: the midcap universe here is a CURRENT
SNAPSHOT (today's survivors back to 2016), and **momentum is the factor MOST inflated by
survivorship** — today's midcap list is precisely the names that kept winning and survived;
the ones that crashed and delisted are absent, so a "buy winners" book looks great in
hindsight. This is exactly the bias the universe-capacity caveat above warns about, now
demonstrated. **Verdict: a LEAD, not a result.** It means nothing until (a) point-in-time
membership incl. delisted names removes the survivorship inflation and (b) it survives the
hardened gate (impact/capacity + Deflated Sharpe). Recorded so the flip isn't mistaken for
alpha. (Reversal weakening in the wider set is also consistent — more momentum-laden
survivors dilute the large-cap reversal pulse.)

### HARDENED IT (2026-06-19): the wide momentum "lead" DIES — negative #9

The cheap, decisive test before doing any survivorship-data work: **survivorship can only
flatter momentum**, so if the survivorship-INFLATED wide-momentum book already fails the
hardened multiple-testing gate, the true point-in-time result is worse and the lead is
dead without needing the reconstitution data. I generalized `validate_longshort_hardened`
to run the **12-1 momentum** book (formation-horizon search [126,189,252,378,504]) and to
honor `--wide`, then ran the full fundable matrix (long cash CNC + short single-stock
futures + borrow + sqrt market-impact, Deflated Sharpe over the horizon search):

| Book | Universe | best IC-IR | net Sharpe @₹1M | Deflated Sharpe | Verdict |
|---|---|---|---|---|---|
| Reversal | large-72 | 2.10 | 0.31 | 0.605 | **DIES** |
| Reversal | wide-151 | 1.13 | 0.07 | 0.290 | **DIES** |
| Momentum | wide-151 | 1.66 | 0.56 | **0.867** | **DIES** |

Momentum on the wide universe is the **closest any factor has come** (DSR 0.867, raw
net Sharpe ~0.56, +90% with healthy capacity to ₹1cr, and even the fenced dynamic /
regime-conditioned variants hold up at ~0.56–0.63) — but the deflation for the
five-horizon search still puts it **below the 0.95 bar**, and that is *with* survivorship
on its side. So: the flip from large-cap reversal to wide momentum was a survivorship
artifact exactly as predicted, and **no cross-sectional factor — reversal or momentum, in
any fundable form, on either universe — survives the hardened gate.** Negative #9.

### BUT the FUNDABLE form is not pure beta (2026-06-19, correction to the over-reject)

The hardened table above is the **market-neutral L/S book** — whose short leg is single-stock
futures, **unfundable on midcaps** (most aren't F&O-eligible). The form a real ₹10L account
*can* trade is **long-only momentum tilt** (no short leg). Running the directional probe on the
wide universe (`--longshort-directional --wide`, long-only judged vs EQUAL-WEIGHT — the correct
benchmark, not cap-weighted NIFTY):

| Signal | IC-IR | long-only Sharpe | **LO − equal-weight Sharpe** | long beta | short-leg helps |
|---|---|---|---|---|---|
| reversal_1m | 1.13 | 0.93 | **0.00** (pure beta/size) | 1.22 | +0.0015 |
| **mom_12_1** | 1.99 | 1.28 | **+0.63** | **1.06** | +0.0036 |

This is the **one place I was over-rejecting.** Reversal's long-only excess over equal-weight is
*exactly zero* (it's all beta/size, confirmed earlier). **Wide momentum's is +0.63 at beta only
1.06** — i.e. it beats equal-weighting on a *risk-adjusted* basis without taking extra beta, so it
is **not** explainable as size/beta. It's the strongest fundable lead the program has produced.
Two threats keep it a LEAD, not an edge: (1) **survivorship** — the wide universe is today's
surviving midcaps, and momentum is the factor *most* inflated by that bias (this is exactly how a
spurious +0.63 would be manufactured); (2) the long-only tilt has **not** been deflated for
multiple testing the way the L/S book was. **Consequence: the survivorship-correction data project
goes BACK on the critical path — specifically for this fundable long-only-momentum tilt** (it
stays correctly *off* for the unfundable market-neutral books, whose answer is already negative).
The decisive next test: point-in-time midcap membership (incl. delisted) → re-run the long-only
momentum tilt vs equal-weight + a deflated significance check. If +0.63 survives PIT membership,
it is the first thing in the program worth a (long-only, risk-defined) sleeve.

## Why a "better LLM" would not help

The LLM's job in the architecture is to reason/size/abstain over a quantitative
core — not to generate the predictive signal. Evidence: (a) the planner already
adds nothing beyond a deterministic bar (#2); (b) a *proper* learned forward model
on 78k labels has no edge (#3); (c) the literature ceiling is ~54% direction
accuracy regardless of model size. A smarter reasoner over an edgeless EV reasons
more eloquently over noise. A better LLM improves **explanations and decision-time
tool-use to fetch new data** — but there the lever is the *data*, not the model.

## What this does and does not mean

- It does **not** mean the engineering is wrong. The cost model, the walk-forward
  fences, the point-in-time event archive, and the abstention logic are all sound
  — they are *why these negatives are trustworthy.*
- It **does** mean the premise — extract selection/timing alpha from a 67-name
  large-cap universe over a positional horizon, on a laptop, from free price +
  event data — is not supported by evidence. Price-only technicals and
  event-reaction are exhausted.
- The only untested levers with a non-trivial prior are **orthogonal forward
  information we do not have point-in-time**: real point-in-time fundamentals,
  analyst-estimate revisions (SUE/consensus), relational/supply-chain signal, and
  alternative data. Each requires a data-acquisition project, not a model change,
  and the consensus tier in particular has **0% free point-in-time coverage** for
  this universe (see event plane).

## Honest recommendations

1. **Treat the system as a risk-managed execution + research terminal, not an
   alpha engine.** Its real value is the cockpit, the agentic plumbing, the cost
   honesty, and the validation harness — not stock selection.
2. **If alpha is the goal, change the inputs, not the model.** Forward-accumulate
   timestamped firm news now (no honest 10y archive exists) and evaluate on a true
   forward holdout; pursue point-in-time fundamentals/estimates if a clean source
   can be licensed.
3. **Do not tune the existing signals until they pass.** That is the documented
   overfitting trap; the negatives above are the value.
