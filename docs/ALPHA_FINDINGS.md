# Alpha findings — does this system capture alpha? (honest record)

> Status as of 2026-06-17. This document records what the validation harness
> (`terminal_in/backtest/validation.py`) has actually proven, out-of-sample,
> net of real Indian transaction costs. It is deliberately blunt: a clean
> negative is a result, and chasing the numbers until they pass is the
> overfitting trap (WORLD_MODEL.md §8). Every number here is walk-forward-fenced
> unless explicitly labelled in-sample.

## Headline

**No configuration tested beats buy-and-hold NIFTY, net of costs.** Across five
independent, rigorously-fenced experiments, every price- and event-derived signal
is statistically indistinguishable from noise / passive ownership. The bottleneck
is **signal, not model or reasoning.**

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
