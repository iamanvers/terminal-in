# Alpha findings — does this system capture alpha? (honest record)

> Status as of 2026-06-17. This document records what the validation harness
> (`terminal_in/backtest/validation.py`) has actually proven, out-of-sample,
> net of real Indian transaction costs. It is deliberately blunt: a clean
> negative is a result, and chasing the numbers until they pass is the
> overfitting trap (WORLD_MODEL.md §8). Every number here is walk-forward-fenced
> unless explicitly labelled in-sample.

## Headline

**No LONG-ONLY configuration beats buy-and-hold NIFTY, net of costs.** Across the
directional experiments, every price- and event-derived signal is indistinguishable
from noise / passive ownership — the bottleneck is **signal, not model or reasoning.**
The one exception, and it is a *lead* not an edge: a **market-neutral 1-month
cross-sectional reversal** book shows a borderline pulse (IC-IR ≈ 2, net Sharpe ~0.4,
but −31% DD, 80% turnover, needs a futures short book we don't run). See the
cross-sectional section below — this is the structure the literature points to, and
the only non-null in six experiments.

The single most important number: over 10 years (67 symbols, 1,484 trades), the
full decision stack returns **~3% CAGR net** while **buy-and-hold NIFTY returns
~11.6%** and **equal-weighting the same 67 names returns ~21%**. The machinery
*subtracts* ~18 points of CAGR versus simply owning the basket — it is a
low-turnover, cash-heavy filter that mostly keeps capital *out* of the market
during the decade equities ran.

## The five negatives

| # | Experiment | Harness | Result (OOS, net) |
|---|-----------|---------|-------------------|
| 1 | Price-only technical strategy | `validation.py` | net Sharpe **0.57** < NIFTY 0.76 < equal-weight 1.07; 53rd pct vs random-symbol null; only MOM survives multiple-testing |
| 2 | LLM / planner marginal value | `validation.py` (planner isolation) | planner adds **+0.0155 Sharpe, within ±0.067 noise** — decorative |
| 3 | Learned forward EV head (D₀, LightGBM, 78k point-in-time labels) | `validation.py --m6` | net Sharpe **−0.02** vs heuristic +0.44; loses to buy-hold; **0 DSR survivors**; features led by VIX/sector (not relearning the heuristic — the signal simply isn't there) |
| 4 | Directional competence weighting (Phase C) | `validation.py --m6` | **abstains the winners** (abstained trades +0.0027 vs kept −0.0006); net Sharpe 0.44→0.03 |
| 5 | Event-reaction / PEAD plane (NSE archive, 87k events) | `validation.py --events` | **no OOS lift** (Δ −0.064 within ±0.20); PEAD core flat: corr(reaction, fwd-ret) = **0.004**; 0 DSR survivors |
| 5b | VIX-conditioned reaction matrix | `m6/reaction.py` | OOS dir-hit **0.515**, corr(expected, realized drift) **−0.0008**; no VIX pocket |
| 6 | Cross-sectional market-neutral (A1 IC + A2 L/S) | `validation.py --longshort` | 12-1 momentum **null** (IC-IR 0.88, L/S −8%); 1-month **reversal = the first PULSE** — IC +0.039, **IC-IR +1.96**, market-neutral L/S net **+58% / Sharpe 0.39** over 10y (caveats below) |

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
market-neutral), and it is the only thing in six experiments that isn't flat — worth
developing carefully, but it is **not** a deployable edge as measured.

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
