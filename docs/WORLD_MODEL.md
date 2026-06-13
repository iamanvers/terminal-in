# Module 6 — World-Model Decisioning Core (design)

> Status: **DESIGN / NOT BUILT.** This document plans a forward-looking
> replacement for the heart of the decision pipeline. It is staged so each
> phase ships and is eval-gated independently; nothing here weakens the
> hard invariants in [CLAUDE.md](../CLAUDE.md) or the risk gate.
>
> Owner ask (2026-06-13): *"the decisioning core … will only look back and
> try and guess. I came across JEPA and world models … a combo to make a
> financially sound judge and stock picking at the 99th percentile."*

---

## 1. The gap in today's core (why the intuition is right)

Today's flow, end to end:

```
6 rule lenses ──▶ noise filters ──▶ EV = conf·RR·vol·convergence
(RSI/EMA/52w…)    (persistence,        ──▶ LLM Trade Planner ──▶ M2 risk gate ──▶ broker
                   conf-EMA, EV hyst)        (one Ollama call, JSON verdict)
   feedback: DecisionMemory hindsight re-prices rejects 4–72h later
```

Every box above is **backward-looking**:

- The lenses compute indicators on *past* bars. RSI<38 is a statement about
  what already happened.
- The EV formula is a static heuristic — `conf · RR · vol · convergence` — with
  no model of where price goes next. RR is just the ATR multiples we chose
  (1.5/2.5), not an estimate of the actual path distribution.
- The LLM judge reasons over a **text prompt of current features plus a
  hindsight record** ("setups like this won 47% of the time"). It pattern-matches
  against its training distribution. It does not *simulate* the future; it
  recalls the past and guesses.
- The hindsight loop is, literally, looking back.

So the owner's read is correct: the core **observes and recalls; it never
imagines forward.** It has no internal model of market dynamics it can roll
forward to ask *"if I take this position, what is the distribution of outcomes
over the next 5/10/20 days, and how confident am I in that — right now, in this
regime?"* That question is what separates a reactive screener from a judge.

### What the attached papers actually tell us (the honest read)

- **Chang et al. 2026 (Eng. Proc. 128, 42)** — LSTM + technical indicators +
  sentiment feeding a rule-based auto-trader on the Taiwan exchange. The result
  worth internalising: their automated system **underperformed an equal-weighted
  buy-and-hold** in the 1-year (1.87% vs 5.18%) and 11-year (179% vs 243%)
  backtests, and only edged it mid-term. A competent supervised price predictor
  bolted onto rule-based execution **does not reliably beat owning the basket.**
  Reactive prediction is not an edge by itself.
- **Zhu et al. 2026 (Information 17, 548)** — LSTM-RF hybrid via *short-term
  directional probability-based model selection.* Three usable findings:
  1. **Different models own different directions.** LSTM was better at *up*
     moves (HR+ ≈ 50.7%), Random Forest better at *down* moves (HR− ≈ 63.4%).
     They pick the model per-prediction by each model's **trailing-60-day hit
     rate for that direction.** This is a competence-weighted meta-layer.
  2. Direction accuracy tops out around **54%** even for the winning hybrid —
     barely above a coin flip, but statistically significant (DM + McNemar).
  3. `tanh` (bounded, symmetric) beats `ReLU` for price models; the nets
     converge ~240 iterations. Small-data, heavy-regularization regime.

The combined lesson: **prediction accuracy has a low ceiling and is not where
the money is.** The edge is in *process* — breadth across many names, a
forward model that quantifies the outcome *distribution* (not a point guess),
honest self-knowledge of when the model is reliable, abstention when it isn't,
and disciplined risk control. That is what "99th percentile" must mean here, and
it is reachable. "99th-percentile predictive accuracy" is not, and any doc that
promised it would be lying.

---

## 2. The three ideas, and what each contributes

### 2a. JEPA — predict in representation space, not price space

**Joint-Embedding Predictive Architecture** (LeCun; I-JEPA for images, and the
emerging T-JEPA / time-series variants). Core moves:

- Encode an observation window into a **latent** `z`. Train a **predictor** to
  predict the *latent* of a future (masked) window from the context latent —
  **not** to reconstruct future prices.
- **Why this matters for markets specifically:** raw next-day returns are
  almost pure noise (near-efficient markets, microstructure). A model that
  tries to predict the exact close wastes all its capacity fitting noise — which
  is exactly the modest-accuracy ceiling both papers hit. But the *conditional
  structure* of markets — volatility regime, factor exposure, cross-asset
  lead-lag, momentum-vs-reversion phase, risk-on/off — is far more predictable
  and lives naturally in a low-dimensional latent. Predicting *"the latent is
  drifting toward a high-vol risk-off configuration"* is both more achievable
  and more actionable than predicting tomorrow's price.
- **Non-generative** ⇒ no decoder reconstructing every bar ⇒ cheap enough for a
  laptop, and it sidesteps the noise trap.
- Collapse avoidance: EMA target-encoder (I-JEPA) + VICReg variance/covariance
  regularisation.

JEPA gives us a **learned market-state representation** — strictly richer than
the 6-state HMM, which becomes a coarse, interpretable *projection* of `z`.

### 2b. World models — latent dynamics + imagination

**World models** (Ha & Schmidhuber; DreamerV3). Core moves:

- A **latent transition model** predicts `z_{t+1..t+H}` (a *distribution*, with
  uncertainty) from `z_t`. This is the forward simulator the current core lacks.
- **Imagination:** roll the transition model forward to generate trajectories in
  latent space, then read out the quantities we care about (forward-return
  distribution, downside, P(stop-before-target), regime-transition odds).
- In Dreamer, a policy is trained on these imagined rollouts. We will use
  imagination first for **valuation** (model-based EV) and only later, gated,
  for a policy.

World models give us the **forward simulation** — the judge can ask "what
happens *if*" before acting, instead of recalling "what happened when."

### 2c. Directional competence / model selection (from Zhu et al.)

Generalise the LSTM-RF idea: for each **lens × direction × latent-regime**, track
the **trailing hit rate** (HR+, HR−). We already compute realized outcomes in the
hindsight loop. The judge then **weights each candidate by the recent, calibrated
reliability of that signal source in this direction and this regime** — and
**abstains** when no source clears a competence threshold. This is the cheap,
high-value meta-layer, and it is buildable today with zero new ML.

---

## 3. Target architecture — Module 6

M6 sits **between** the lenses and the LLM judge. It does not replace them; it
turns the judge from a text-recall guesser into a reasoner over a quantified
forward distribution. The risk gate is untouched and final.

```
 lenses (feature generators, unchanged)
        │  per-symbol multivariate window + cross-sectional + macro + sentiment
        ▼
 ┌─────────────────────────  MODULE 6  ─────────────────────────┐
 │  (A) JEPA encoder  ──▶ z_t  (market-state latent, per symbol  │
 │                              + cross-sectional Z_t)           │
 │        │  linear probe ──▶ regime read (replaces/【explains HMM)│
 │        ▼                                                       │
 │  (B) latent world model ──▶ z_{t+1..t+H} distribution         │
 │        │  imagination rollout (FENCED — never written as OHLCV)│
 │        ▼                                                       │
 │  (D) model-based EV: E[ret], CVaR downside, P(tgt before sl), │
 │        horizon — per candidate, from the rolled-out latent    │
 │  (C) competence weights: trailing HR+/HR− per lens×dir×regime │
 └───────────────────────────────┬──────────────────────────────┘
                                  ▼
        LLM Trade Planner  (now consumes: candidate + model-based EV
        distribution + competence + latent regime + hindsight memory)
        → reasons over a SIMULATED FORWARD DISTRIBUTION, explains, sizes
                                  ▼
                 M2 risk gate (13 checks, UNCHANGED, final)
                                  ▼
                               broker
  (E, later) latent policy proposes size/timing, trained in imagination,
             validated ONLY on real walk-forward + paper record
```

### Component detail

**(A) Market-State Encoder — JEPA-lite, self-supervised.**
- Input per symbol: rolling window (e.g. 60d) of returns, log-vol, RSI, EMA
  ratios, volume z-score, ATR + cross-sectional context (sector return, market
  breadth, index return) + macro (NIFTY, India VIX) + FinBERT sentiment (already
  computed). Z-score standardised (per Zhu et al.: standardisation matters).
- Encoder: small — 1–2 layer GRU or temporal-conv → `z` (dim ~32–64). `tanh`
  activations (paper-2 finding). Target encoder = EMA of the online encoder.
- Loss: smooth-L1 between predicted and target future-window latent + VICReg
  variance/covariance terms (collapse guard).
- Interpretability: a linear probe `z → 6 regime states`, supervised against the
  HMM labels, so we keep the explainable regime read while `z` carries far more.

**(B) Latent World Model — forward dynamics.**
- Transition: `z_t → distribution over z_{t+1..t+H}` (H ∈ {5,10,20}). Probabilistic
  — predict mean + variance, or a small **ensemble** for epistemic uncertainty
  (the uncertainty is what powers abstention).
- Heads off the rolled-out latent: forward-return distribution, downside/vol,
  P(hit stop before target | entry, sl, tgt), regime-transition odds.

**(C) Calibrated Directional Competence.**
- Rolling HR+/HR− per (lens, direction, latent-regime), fed by the existing
  hindsight outcomes. Down-weights a lens that's been wrong lately in *this*
  regime; abstains when nothing clears threshold `th₁` (Zhu et al. use 0.6).

**(D) World-Model Judge — model-based EV.**
- Replace the static `conf·RR·vol·convergence` with a **model-based EV**: roll
  the world model forward under the candidate position and integrate the outcome
  distribution → `E[return]`, `CVaR` downside, `P(target before stop)`, expected
  horizon. Forward-looking, distributional, regime-conditioned.
- The LLM planner now receives candidate + this distribution summary +
  competence + latent regime + (still) hindsight memory, and reasons/sizes/
  explains over it. The LLM becomes the reasoning + communication + sanity layer
  over a quantitative core — not the sole arbiter guessing from text.

**(E) Latent Policy — optional, last, RL-in-imagination (DreamerV3-style).**
- Actor-critic on imagined rollouts proposing size/timing to maximise a
  risk-adjusted, drawdown-penalised reward. **Promoted only** after beating the
  incumbent on real walk-forward backtest + a paper-trading record. Imagination
  trains the policy; it never reports performance.

---

## 4. Training & data — and why the 10-year backfill matters

The deep-history backfill (Change_46: all 72 symbols to 2016, ~2,470 daily bars
each) is exactly the substrate a JEPA needs. ~177k symbol-days of **real** data.

- **(A) encoder + (B) world model:** self-supervised on the real daily history
  (later 5m, limited to the 60d we retain). Small models, heavy regularisation,
  `tanh`, ~hundreds of iterations (paper-2 regime). CPU-feasible at these dims
  with `hw.py` threading + the same offline-trainer pattern as `nphmm`.
- **(C) competence:** supervised by realized hindsight outcomes — no new labels.
- **(E) policy:** RL in imagination, validated only on real walk-forward.

This is **small-data deep learning.** We favour tiny latents, ensembles for
uncertainty, dropout, and walk-forward validation — and we expect the encoder/
world-model to *fail gracefully into abstention*, not to be oracular.

---

## 5. Hard invariants & fences (PR-blocking)

1. **Imagination is never persisted as market data.** The world model's rolled-out
   latents and return distributions live in memory/latent space only. They are
   **never** written to `ohlcv_*`, never fed to strategies/lenses as if they were
   bars, never shown as quotes. This preserves the REAL-DATA-ONLY mandate exactly
   — imagination is a *planning* tool inside the judge, fenced off from the data
   path. (New invariant, added to CLAUDE.md.)
2. **The risk gate stays final.** M6 can veto, shrink, or abstain; it can never
   bypass the 13-check M2 gate. Unchanged from the current planner invariant.
3. **No silent degradation.** Each M6 component reports to `/api/health`. If the
   encoder/world-model is untrained or unavailable, the judge falls back to the
   current heuristic-EV + LLM path, flagged (`m6_mode: world_model | fallback`),
   badged in the UI — same discipline as `regime_heuristic`/`ollama_offline`.
4. **Eval-gated promotion.** The M6 judge must **beat the current judge on
   walk-forward backtest** (now possible: 10y data + backtest engine v2) before it
   routes live, with no >5pt category regression — the same gate that correctly
   *rejected* financial-analyst-v2. The backtest engine becomes the promotion gate.
5. **Honesty of claims.** Reported performance comes only from real walk-forward
   and paper-trading records — never from imagined rollouts.

---

## 6. Compute & laptop realism

Ryzen 7 7730U, 8C/16T, 16 GB, CPU-only (no CUDA; iGPU via DirectML/Vulkan only).

- (A)+(B) at latent dim 32–64 over 177k symbol-days: **feasible** as an offline
  nightly/weekend train, same footprint as the LoRA runs. Daily timeframe first.
- (E) Dreamer-scale RL is the expensive, research-y part — explicitly last, and
  optional. We may stop at (D) and still have transformed the core.
- Inference (encode + short rollout per scan) must fit the 120s scan budget; with
  small dims this is milliseconds, dominated as ever by the one Ollama call.

---

## 7. Staged delivery (each phase ships + is eval-gated)

| Phase | Deliverable | Ships when | Gate |
|------|-------------|-----------|------|
| **A** | JEPA-lite encoder + regime probe; `z_t` in bus cache; `/api/health.m6` | encoder trains, regime probe ≈ HMM agreement, no collapse (VICReg variance floor) | probe matches HMM ≥70% of days; latent variance non-degenerate |
| **C** | Directional competence weights + abstention (cheapest, do early/parallel) | trailing HR+/HR− per lens×dir×regime wired from hindsight | backtest: competence-weighting ≥ flat on Sharpe |
| **B** | Latent world model + uncertainty ensemble; imagination rollout (fenced) | transition model trains; rollouts produce calibrated return bands | rollout return-bands calibrated on held-out (coverage ≈ nominal) |
| **D** | Model-based EV replaces heuristic EV; LLM judge consumes forward distribution | (A)+(B)+(C) live | **walk-forward backtest beats current judge, no >5pt category regression** |
| **E** | Latent policy (RL-in-imagination) for size/timing — *optional* | (D) promoted + stable | real walk-forward + 60-day paper record beats (D) |

Phase **C** is buildable now with no new ML and likely the best
effort/reward ratio — do it first, alongside (A).

---

## 8. Risks & honest failure modes

- **Non-stationarity:** a world model trained on past regimes can mislead in a
  novel one. Mitigation: epistemic-uncertainty ensemble → **abstain** when
  out-of-distribution; walk-forward (never random-split) validation.
- **Representation collapse:** JEPA's failure mode. Mitigation: EMA target +
  VICReg; the variance floor is a gate criterion.
- **Overfitting on small data:** 177k symbol-days is small for DL. Mitigation:
  tiny latents, dropout, `tanh`, early stopping (~240-iter regime from paper 2),
  ensembles.
- **The efficiency ceiling:** even done well, direction accuracy stays ~55% (both
  papers). The edge is risk-adjusted consistency + abstention + breadth + the
  gate — not prediction supremacy. We will measure success in **Sharpe / max-DD /
  hit-rate-when-not-abstaining**, not in headline accuracy.
- **Complexity vs payoff:** (E) may not beat (D). That's an acceptable outcome —
  (A)–(D) already replace a backward-looking guesser with a forward-looking,
  self-aware judge, which is the point.

---

## 9. References

- A. van den Oord-lineage / Y. LeCun, *A Path Towards Autonomous Machine
  Intelligence* (JEPA); I-JEPA (Assran et al., 2023); time-series JEPA variants.
- D. Ha, J. Schmidhuber, *World Models* (2018); Hafner et al., *DreamerV3* (2023).
- Chang, Wei, Weng, Cho, Hsiao, *Stock Market Analysis, Forecasting, and Automated
  Trading Using Deep Learning*, Eng. Proc. 2026, 128, 42.
- Zhu, Dawod, Yu, Zhou, *LSTM-RF Stock Prediction via Short-Term Directional
  Probability-Based Model Selection*, Information 2026, 17, 548.
- VICReg (Bardes et al., 2022) — collapse-free joint-embedding regularisation.

---

*This is a plan, not a promise. It is sequenced so we learn cheaply (Phase C, A)
before committing to the expensive parts (B, D, E), and so every step is gated on
beating what we already ship.*
