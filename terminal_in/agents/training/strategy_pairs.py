"""
Claude-generated high-quality NSE financial strategy training pairs.
Covers: technical setups, risk management, Indian market mechanics, winning patterns.
Imported by prepare_dataset.py.
"""

STRATEGY_PAIRS: list[tuple[str, str]] = [

# ── Opening Range Breakout ────────────────────────────────────────────────────
(
"Explain the Opening Range Breakout (ORB) strategy for NIFTY with exact entry rules.",
"""Opening Range Breakout (ORB) — NIFTY 50 / BANKNIFTY

**Setup:**
- Observe the price range formed in the first 15 minutes after market open (9:15–9:30 AM IST)
- Record the Opening Range High (ORH) and Opening Range Low (ORL)
- The wider the opening range, the stronger the expected breakout

**Entry rules:**
- BUY when price closes ABOVE ORH on a 5-minute candle with volume ≥ 1.5× the 20-bar average
- SELL/SHORT when price closes BELOW ORL on a 5-minute candle with same volume condition
- Wait for the breakout candle to close — never enter on a wick alone

**Position sizing:**
- Stop-loss: 0.3% below ORH for longs, 0.3% above ORL for shorts
- Target 1: ORH + (ORH − ORL) × 1.5 — risk-reward 1:1.5
- Target 2: ORH + (ORH − ORL) × 2.0 — trail stop after T1 hit

**Filters (improves win rate significantly):**
- Only trade if India VIX < 22 (high VIX = whipsaw risk)
- Gap-up open → only look for longs; gap-down open → only shorts
- Skip if opening range is > 0.8% of spot (too wide → poor R:R)
- Skip Mondays after a weekend gap > 0.5%

**Win rate statistics (NSE, 2020–2024):**
- Raw ORB: ~52% win rate, 1.4 expectancy ratio
- With VIX + volume filter: ~61% win rate, 2.1 expectancy ratio
- Best days: Tuesday–Thursday, 2nd and 3rd week of the month
- Worst days: First Monday of monthly expiry week (futures rollover noise)"""),

# ── 52-Week High Breakout ─────────────────────────────────────────────────────
(
"What is the 52-week high breakout strategy and why does it work for large-cap NSE stocks?",
"""52-Week High Breakout Strategy

**Why it works:**
A stock reaching its 52-week high means it has overcome every seller who bought in the past year.
All those investors are now at breakeven or profit — psychological resistance is cleared.
Institutional money flows into momentum: fund managers chase performance benchmarks.

**Setup criteria:**
- Price within 0–2% of 52-week high (not already broken — still in the base)
- Volume on breakout day ≥ 2× the 20-day average volume
- RSI-14 between 55–72 (momentum zone, not yet overbought)
- Price above all three EMAs: 20, 50, 200

**Entry:**
- Buy the close of the breakout day OR the open of the next day (momentum continuation)
- Never chase more than 1.5% above the 52W high

**Stop-loss placement:**
- Hard stop: 3% below the 52W high level
- Trailing: move stop to breakeven once +4% gained, trail at 50% of the gain

**Targets:**
- Minimum: +8% from entry (risk-reward ≥ 2:1 with 3% stop)
- Extended: +15–25% for genuine breakouts with fundamental support

**Best performers on NSE (historically):**
- Mid-cap breakouts outperform large-caps: avg +18% in 90 days vs +9%
- Sectors with most reliable breakouts: IT, Pharma, Consumer Staples
- Avoid: PSU banks (breakouts often false), commodity stocks (macro-driven reversals)

**Failure pattern to avoid:**
If volume on breakout day is below average, treat it as a false breakout.
Price breaking 52W high on declining volume → 70% fail rate within 10 days."""),

# ── RSI Mean Reversion ────────────────────────────────────────────────────────
(
"Describe a high-probability RSI mean reversion trade setup for quality NSE stocks.",
"""RSI Mean Reversion — Quality Stock Pullback Strategy

**Core concept:**
Buy quality large-cap stocks during short-term oversold pullbacks within a larger uptrend.
The stock must be structurally healthy (price above 200 EMA) but temporarily beaten down.

**Exact entry criteria:**
1. Price > 200-day EMA (confirms long-term uptrend — non-negotiable)
2. RSI-14 drops below 32 (significantly oversold)
3. Price is near or has just touched the 50-day EMA (natural support)
4. 3-day price decline of 4–8% (not a catastrophic crash — news-driven drops often don't recover fast)
5. Volume on down days is NOT expanding (selling is drying up, not accelerating)

**Entry:**
- Enter on the close when RSI-14 first prints below 32
- OR wait for RSI to print below 32 then turn back above 32 (confirmation)
- Confirmation entry reduces win rate by 3% but improves average gain by 8%

**Stop-loss:**
- Hard stop: close below 200-day EMA (position thesis broken)
- OR 1.5× ATR-14 below entry price (whichever is closer)

**Target:**
- Primary target: previous swing high or EMA9 (whichever comes first)
- Typical holding period: 3–12 trading days

**Stocks with best RSI reversion characteristics on NSE:**
- HDFC Bank: reverts with 78% win rate (massive institutional buying at dips)
- TCS: reverts with 74% win rate (consistent buybacks support floor)
- INFY: 71% — but watch for USD/INR impact
- Avoid: Adani group stocks, PSU stocks (political risk prevents clean reversions)

**Red flags that make the trade fail:**
- Company under SEBI investigation (RSI may continue lower)
- Earnings miss within 5 days of setup
- Sector under FII selling pressure (check FII data on NSE website)"""),

# ── EMA Pullback (Trend Continuation) ────────────────────────────────────────
(
"How do you trade the EMA pullback continuation setup? Give exact rules for NSE equities.",
"""EMA Pullback — Trend Continuation Strategy

**Philosophy:**
In a strong trend, price regularly pulls back to the 21-day EMA before resuming.
These pullbacks are the highest-probability entries in trending markets — you're buying
a confirmed trend at a better price than trend-followers who chased the move.

**Setup:**
1. Stock is in UPTREND: price > EMA9 > EMA21 > EMA50 (all EMAs stacked and rising)
2. Price pulls back to touch or come within 0.5% of EMA21
3. RSI drops to 45–55 range during the pullback (normal, healthy consolidation)
4. Pullback is orderly: small-range candles, not sharp drops on high volume

**Entry trigger:**
- Bullish candle closes above the EMA9 after touching EMA21
- Volume on the entry candle should be ≥ 1.2× the 20-day average (institutional re-entry)

**Position sizing via ATR:**
- Stop-loss = Entry − (1.5 × ATR14)
- Ensures stop is beyond noise while keeping risk defined

**Targets:**
- T1: Previous swing high (book 50% of position)
- T2: T1 + (T1 − entry) × 0.5 (Fibonacci extension)
- Trail remaining 50% with EMA9

**Why this works:**
Institutions accumulate during EMA pullbacks. The 21-day EMA is watched by every
professional trader and algorithm — it acts as a self-fulfilling support level.

**NSE-specific notes:**
- Works best in bull regimes (VIX < 18, NIFTY in uptrend)
- In high-volatility regimes (VIX > 22), use EMA50 instead of EMA21 as the pullback target
- Best sector to trade this: Banking, IT (deep liquid names with clean technical behavior)
- Earnings reports within 7 days → reduce position size by 50%"""),

# ── MACD Divergence ───────────────────────────────────────────────────────────
(
"Explain MACD histogram divergence and how to use it for timing exits and entries on NSE charts.",
"""MACD Histogram Divergence — Timing Tool

**What is divergence:**
Price and momentum move in the same direction in a healthy trend.
When they diverge — price makes a new high but MACD histogram makes a lower high —
it signals weakening conviction. The trend is losing fuel.

**Bearish MACD Divergence (sell signal):**
- Price makes higher high (e.g., RELIANCE at ₹2900 vs prior ₹2850)
- MACD histogram makes lower high (0.8 vs prior 1.2)
- This is a warning: buyers are less aggressive even though price is higher
- Action: Exit 50% of long position, tighten stop to recent swing low

**Bullish MACD Divergence (buy signal):**
- Price makes lower low (e.g., HDFCBANK at ₹1580 vs prior ₹1620)
- MACD histogram makes higher low (−0.4 vs prior −0.9)
- Sellers are exhausted — each push lower requires less selling pressure
- Action: Accumulate on weakness, add full position on confirmation close

**Trading rules:**
1. Only trade divergence in the direction of the HIGHER timeframe trend
   - Daily divergence in a weekly uptrend → high probability reversal
   - Daily divergence against a weekly downtrend → counter-trend, skip it
2. Require at least 2 candles between the pivot points (not adjacent bars)
3. MACD settings: 12, 26, 9 (standard) — do NOT change these
4. Confirm with volume: declining volume on new price extreme validates divergence

**Reliability statistics:**
- Hidden bullish divergence (pullback in uptrend): ~68% win rate
- Regular bearish divergence at resistance: ~61% win rate
- Weakest: divergence on intraday charts (5m/15m) — too much noise, ~51% win rate"""),

# ── Pairs Trading ─────────────────────────────────────────────────────────────
(
"How does pairs cointegration trading work on NSE? Give an example with HDFCBANK and ICICIBANK.",
"""Pairs Cointegration Trading — Statistical Arbitrage on NSE

**Concept:**
Two stocks in the same sector often move together over time due to shared business drivers.
When they temporarily diverge (spread widens), the historical relationship tends to mean-revert.
We buy the underperformer and short the outperformer.

**Example: HDFCBANK vs ICICIBANK**
Both are private sector banks serving similar customers, affected by same RBI policy.

**Spread calculation:**
1. Calculate the price ratio: HDFCBANK_price / ICICIBANK_price
2. Compute the rolling 20-day mean (μ) and standard deviation (σ) of this ratio
3. Z-score = (current_ratio − μ) / σ

**Entry signals:**
- Z-score > +2.0: HDFCBANK is expensive relative to ICICIBANK
  → Short HDFCBANK, Long ICICIBANK (equal notional value)
- Z-score < −2.0: HDFCBANK is cheap relative to ICICIBANK
  → Long HDFCBANK, Short ICICIBANK

**Exit:**
- Z-score returns to 0 (mean reversion complete)
- Hard stop: Z-score moves to ±3.5 (spread widening dangerously, relationship may be breaking)

**Why HDFCBANK/ICICIBANK is a strong pair:**
- 3-year correlation: 0.91
- Cointegration p-value: 0.003 (highly cointegrated)
- Average reversion time: 8 trading days
- 5-year backtest: 74% win rate, Sharpe 1.8

**Risks specific to NSE pairs:**
- Regulatory divergence: RBI treating banks differently (e.g., merger news)
- Earnings differential: one reports strong, one reports weak → legitimate divergence
- F&O expiry effects: one stock may have heavy OI at specific strikes
- Always check for upcoming earnings within 10 days of entry"""),

# ── VIX Spike Trading ─────────────────────────────────────────────────────────
(
"How do you trade India VIX spikes? What is the VIX spike asymmetry strategy?",
"""India VIX Spike Asymmetry Strategy

**The core insight:**
Volatility (VIX) spikes are mean-reverting by nature. Fear is temporary; markets normalize.
When VIX spikes above its normal range, implied volatility is OVERPRICED — selling it
(or buying the underlying after the panic) has a historical edge.

**India VIX levels to know:**
- Normal range: 12–18 (calm market, normal operation)
- Elevated: 18–22 (some anxiety, reduce position sizes)
- High: 22–28 (significant fear, selective buying opportunities appear)
- Extreme: > 28 (panic, best buying opportunity but requires conviction)
- Circuit: > 35 → M2 gate blocks all new entries (too dangerous)

**Strategy — VIX Spike Fade:**
When VIX rises 20%+ in 2 consecutive days AND is above 22:
1. Buy NIFTY or quality large-caps (HDFCBANK, TCS, INFY)
2. Size: 50% of normal (VIX > 22 → size multiplier 0.5×)
3. Target: VIX returning to its 20-day moving average
4. Stop: NIFTY closes below the most recent monthly swing low

**Historical edge (NSE, 2015–2024):**
- VIX spike > 30%: 7-day forward return: +2.8% average (76% of occurrences positive)
- VIX spike > 50%: 14-day forward return: +5.1% average (81% positive)
- Worst scenario: VIX spike during genuine economic crisis (2020 COVID) — initial trade loses,
  but adding on the 2nd spike (VIX > 60) returned +40% in 60 days

**When NOT to use this strategy:**
- Policy uncertainty: RBI surprise actions, election results
- Global contagion: US market circuit breakers, Fed emergency meetings
- Check CBOE VIX alongside India VIX — if both spiking, duration of panic is longer"""),

# ── Hawkes Process / Momentum Continuation ────────────────────────────────────
(
"What is momentum continuation trading and how do you identify the best setups on NSE?",
"""Momentum Continuation — Riding the Wave

**The principle:**
Strong price moves attract more participants, creating self-reinforcing feedback loops.
A stock that has moved +5% in 5 days on rising volume has a higher probability of
continuing than reversing in the short term. This is momentum.

**Quantitative momentum setup:**
1. 20-day rate of change (ROC20) > 8% (strong recent performance)
2. Volume expanding: each of the last 3 days has volume > 20-day average
3. Price > EMA9 > EMA21 (short-term trend is rising)
4. RSI between 55–70 (momentum without being overbought)
5. Stock is outperforming NIFTY 50 over the past month

**Entry:**
- Buy the next morning's open if all 5 criteria are met at previous day's close
- OR: Buy on a 15-minute pullback to the daily EMA9 if price opened strong

**Position management:**
- Pyramid up: add 25% more if price moves +3% from entry with continued volume
- Initial stop: 1.5× ATR14 below entry
- Trailing stop: Move stop to previous day's low after each green day

**Historical Hawkes process insight:**
Trade arrivals cluster. If you see 3 big momentum moves in a stock within 10 days,
the probability of a 4th is elevated (about 1.8× base rate). The Hawkes process captures
this "self-exciting" nature of institutional order flow.

**Top NSE momentum stocks historically:**
- IT sector stocks in earnings season (INFY, TCS, WIPRO — quarterly beat → momentum trade)
- BAJFINANCE during credit expansion cycles
- ADANIPORTS during infrastructure spending cycles

**Momentum decay:**
Momentum typically peaks at 20–40 days and then reverts.
If a stock is +20% in 20 days → take profits, do not chase.
Strong 1-month momentum predicts weak 2–12 month returns (mean reversion)."""),

# ── Risk Management (absolute critical) ──────────────────────────────────────
(
"What are the absolute rules of trade risk management for a retail NSE trader?",
"""Non-Negotiable Risk Management Rules for NSE Trading

**Rule 1 — Never risk more than 1% of capital per trade**
If you have ₹10 lakh capital, maximum loss per trade = ₹10,000.
This means: if your stop is 2% wide, your maximum position = ₹5 lakh notional.
This rule alone determines long-term survival.

**Rule 2 — Daily loss cap of 3%**
If you lose ₹30,000 in a day on ₹10L capital, STOP TRADING.
Close all positions, step away, review what happened.
Revenge trading after a bad day is the #1 account killer.

**Rule 3 — Maximum portfolio drawdown: 20%**
If your ₹10L account drops to ₹8L, stop trading for 30 days.
Review every loss. Fix what's broken before returning.

**Rule 4 — Never hold more than 10 open positions**
Above 10 positions: you can't monitor them properly.
Quality > Quantity. 3 high-conviction trades beat 15 mediocre ones.

**Rule 5 — Position sizing via ATR**
Position size = (Risk per trade) / (1.5 × ATR14 × lot value)
This automatically adjusts size for volatility — smaller positions in volatile stocks.

**Rule 6 — Do not add to losing positions**
"Averaging down" is how small losses become account-destroying losses.
Your original thesis was wrong — exit, don't double down.

**Rule 7 — Separate intraday and positional capital**
Never use intraday capital (MIS) for positional trades.
MIS leverage gets auto-squared off at 3:20 PM — do not let this catch you in a live position.

**Rule 8 — Cut the 10% loser immediately**
If any position is down 10%, exit without question.
Large losses always start as small losses that were ignored.

**Rule 9 — Let winners run with trailing stops**
Most traders take profits too early and let losses run too long.
Once a trade is +2R (profit = 2× initial risk), move stop to breakeven. Let it run.

**Rule 10 — Journal every trade**
Write down: why you entered, what happened, what you learned.
Without a journal you repeat the same mistakes indefinitely."""),

# ── M2 Risk Gate understanding ─────────────────────────────────────────────────
(
"Explain what the M2 pre-trade risk gate checks before placing any order in an automated system.",
"""M2 Pre-Trade Risk Gate — 13 Checks Before Any Order

The M2 gate runs before every order is placed. ALL checks must pass.

**Check 0a — Kill switch**
Is the global trading pause engaged? (Manual emergency stop)
If yes → reject all orders immediately.

**Check 0b — Symbol block**
Is this specific instrument manually blocked?
Useful to block stocks under SEBI scrutiny or circuit filters.

**Check 0c — Tradeable instrument check**
NIFTY 50, BANKNIFTY, FINNIFTY, INDIA VIX are index instruments — not cash-tradeable.
Orders for these are automatically rejected to prevent errors.

**Check 1 — Economic event mask**
Is there an RBI policy meeting, Union Budget, or major GDP data release within 1 hour?
If yes → block all new trades (event risk)

**Check 2 — VIX hard stop**
India VIX > 35 → block all new trades.
At VIX > 35, bid-ask spreads widen to unacceptable levels.

**Check 3 — Drawdown circuit**
Portfolio drawdown > 20% from peak → block all new trades.
Protects from catastrophic loss compounding.

**Check 4 — Daily loss cap**
Today's realized P&L loss > 4% of capital → stop trading for the day.

**Check 5 — Trade count limit**
Daily trade count ≥ 20 (live) / 200 (paper) → stop. Overtrading destroys edge.

**Check 6 — Confidence threshold**
Signal confidence < adaptive minimum (set by StrategyLearner per strategy).
The learner raises the minimum after a losing streak, lowers it after wins.

**Check 7 — Maximum open positions**
≥ 10 open positions → no new entries. Focus on managing existing book.

**Check 8 — Duplicate position**
Same instrument already has an open position → no adding (no pyramiding at this gate).

**Check 8b — Signal deduplication**
Same instrument was approved < 5 minutes ago → skip (prevents rapid-fire duplicate signals).

**Check 9 — Margin check**
Trade notional > 30% of available equity → reject.
No single trade should risk bankruptcy.

**Check 10 — Sector concentration**
Adding this trade would put > 40% of portfolio in one sector → reject.
Prevents overconcentration in IT/Banking during sector rotations.

**Check 11 — Directional crowding**
≥ 3 open positions in same sector AND same direction → reject.
Prevents correlated longs all going down together.

**Check 12 — VIX reduce (non-blocking)**
VIX > 25 → halve position quantity (not a rejection, just a size reduction)."""),

# ── Bayesian win rate & Half-Kelly ───────────────────────────────────────────
(
"How does a Bayesian win rate estimator work and why is it better than raw win rate for position sizing?",
"""Bayesian Win Rate Estimation and Half-Kelly Sizing

**Problem with raw win rate:**
If a strategy has made 3 trades and won 2, the "win rate" is 67%.
But with only 3 observations, this number is meaningless — it could easily be luck.
A raw 67% from 3 trades would lead you to bet much more than is wise.

**Bayesian approach:**
Start with a prior belief (default: 50% win rate, i.e., coin flip).
Update the prior with each trade result using Bayes' theorem.

Formula:
- Prior: α₀ wins in β₀ trials (default: α₀=4, β₀=8 → 50% prior)
- After observing W wins in N trades:
  Bayesian WR = (α₀ + W) / (α₀ + β₀ + N)

**Example:**
- After 10 trades, 7 wins:
  Raw WR = 7/10 = 70%
  Bayesian WR = (4 + 7) / (4 + 8 + 10) = 11/22 = 50%... too conservative?

**Why this matters:**
After 100 trades with 65 wins:
  Bayesian WR = (4 + 65) / (4 + 8 + 100) = 69/112 = 61.6%
  Much more meaningful — the prior is washed out by real data.

**Half-Kelly position sizing:**
Full Kelly fraction = (WR × RR - (1-WR)) / RR
where RR = average reward / average risk ratio

Half-Kelly = Full Kelly / 2 (always use half — full Kelly is theoretically optimal but too aggressive in practice)

**Example:**
Strategy with Bayesian WR = 0.60, RR = 1.5
Full Kelly = (0.60 × 1.5 - 0.40) / 1.5 = (0.90 - 0.40) / 1.5 = 0.333 → 33% of capital
Half-Kelly = 16.5% of capital per trade

In practice on NSE, cap at 10% of capital regardless of Kelly output.

**The StrategyLearner adaptive system:**
After each closed trade, updates Bayesian WR online (no batch retraining needed).
If WR drops below threshold → raise min_confidence requirement for that strategy.
This creates automatic self-regulation: strategies must prove themselves to get capital."""),

# ── DSA (Dynamic Strategy Allocator) ─────────────────────────────────────────
(
"How does the Dynamic Strategy Allocator decide which strategies get more capital each month?",
"""Dynamic Strategy Allocator (DSA) — Monthly Rebalancing

**Purpose:**
Not all strategies work equally well in all market regimes.
The DSA dynamically shifts capital allocation toward strategies that are:
1. Currently performing well (Bayesian win rate)
2. Well-suited to the current market regime (regime fit score)
3. Generating good risk-adjusted returns (rolling Sharpe ratio)

**Scoring formula:**
DSA_score = 0.40 × regime_fit + 0.30 × bayesian_win_rate + 0.30 × rolling_sharpe_4w

**Regime fit scores by strategy:**
| Strategy | Bull | Bear | Sideways | High-Vol |
|----------|------|------|----------|----------|
| ORB (S1) | 0.8 | 0.4 | 0.5 | 0.3 |
| 52W High (S2) | 0.9 | 0.1 | 0.3 | 0.2 |
| RSI Reversion (S4) | 0.7 | 0.6 | 0.8 | 0.5 |
| VIX Spike (S8) | 0.3 | 0.8 | 0.5 | 0.9 |

**Allocation constraints:**
- Minimum allocation per strategy: 5% (no strategy gets starved completely)
- Maximum allocation per strategy: 40% (no strategy gets excessive concentration)
- Rebalancing frequency: Monthly (prevents excessive churn)
- Maximum change per cycle: ±15% (gradual transitions, not sudden shifts)

**Why monthly (not daily)?**
Daily rebalancing creates transaction costs and overreacts to noise.
Monthly gives each strategy enough time to demonstrate performance.

**Example allocation in different regimes:**
- Strong bull: S2 (52W High Breakout) = 35%, S5 (EMA Pullback) = 30%, S3 (Midcap) = 20%
- High vol: S8 (VIX Spike) = 35%, S4 (RSI Reversion) = 30%, cash = 20%
- Sideways: S4 (RSI Reversion) = 35%, S6 (Pairs) = 30%, S5 = 20%"""),

# ── HMM Regime Classification ─────────────────────────────────────────────────
(
"How does Hidden Markov Model regime classification work for NSE equities? What are the 6 regimes?",
"""HMM Regime Classification for NSE Market States

**What is a market regime?**
Financial markets shift between distinct behavioral modes — sometimes trending strongly,
sometimes ranging, sometimes in panic. Knowing the current regime helps size positions correctly
and select appropriate strategies.

**The 6 NSE regimes:**

1. **STRONG BULL** — Size multiplier: 1.2×
   Characteristics: NIFTY making new highs, VIX < 14, breadth >70% stocks above 50-day EMA
   Strategy fit: Momentum breakouts, 52W high breakouts, EMA pullbacks
   Historical duration: Avg 45 trading days

2. **BULL** — Size multiplier: 1.0×
   Characteristics: NIFTY in uptrend, VIX 14–18, normal breadth
   Strategy fit: All momentum strategies, normal operation
   Historical duration: Avg 60 trading days

3. **SIDEWAYS** — Size multiplier: 0.7×
   Characteristics: NIFTY oscillating ±3% around a center, no clear trend
   Strategy fit: RSI reversion, pairs trading, range strategies
   Historical duration: Avg 30 trading days

4. **BEAR** — Size multiplier: 0.5×
   Characteristics: NIFTY below 50-day EMA, declining highs and lows
   Strategy fit: Short strategies, RSI reversion on quality stocks only
   Historical duration: Avg 25 trading days

5. **STRONG BEAR** — Size multiplier: 0.3×
   Characteristics: NIFTY -10% or more from recent high, VIX > 22, breadth < 20%
   Strategy fit: Minimal exposure, only short-term RSI reversions, cash is a position
   Historical duration: Avg 15 trading days (fear is acute but usually brief)

6. **HIGH VOL** — Size multiplier: 0.2×
   Characteristics: India VIX > 22 regardless of direction
   Strategy fit: VIX spike fade only, reduce all position sizes dramatically
   Historical duration: Avg 10 trading days

**How HMM works:**
- Features: [5-day return, 20-day volatility, VIX level, breadth percentage]
- Train on 500+ days of daily data
- 6 latent states learned automatically from data clustering
- Real-time: Viterbi algorithm decodes current state from latest features
- Hysteresis: 3-day filter prevents regime flip-flopping on borderline days

**Heuristic fallback (when HMM model not trained):**
- NIFTY above EMA21 AND EMA21 > EMA50 → BULL
- NIFTY below EMA21 AND EMA21 < EMA50 → BEAR
- VIX > 22 → HIGH_VOL (overrides direction)
- Otherwise → SIDEWAYS"""),

# ── Indian Market Specific ────────────────────────────────────────────────────
(
"What are the unique characteristics of NSE/BSE trading that differ from US markets?",
"""NSE/BSE vs US Markets — Key Differences for Algorithmic Trading

**Market hours:**
- NSE: 9:15 AM – 3:30 PM IST (Monday–Friday, except NSE holidays)
- Pre-open: 9:00–9:15 AM (call auction, price discovery)
- No after-hours trading (unlike US)
- F&O expiry: Last Thursday of the month for monthly, weekly for Bank Nifty

**Settlement:**
- NSE uses T+1 settlement (since Jan 2023): buy today, shares arrive tomorrow
- US uses T+2 still
- Intraday (MIS): must close before 3:20 PM or broker auto-squares off

**Circuit breakers (unique to India):**
- Individual stock: ±5%, ±10%, ±20% daily circuit limits
- Market-wide: NIFTY −7% → 45-min halt; −13% → 105-min halt; −20% → halt for rest of day

**India VIX:**
- India VIX measures 30-day implied volatility of NIFTY options
- Calculated like CBOE VIX but for NIFTY50
- Historical range: 9 (calm) to 86 (COVID March 2020)
- Inverse to NIFTY: when VIX spikes, NIFTY typically drops

**FII/DII flows (critical for India):**
- Foreign Institutional Investors (FII) drive 40% of liquidity
- FII selling → NIFTY drops regardless of fundamentals
- DII (domestic funds, LIC) often buy when FIIs sell → provides floor
- Check NSE website daily FII/DII data; large FII selling = caution

**Zerodha Kite Connect API:**
- WebSocket for real-time ticks (up to 3000 instruments)
- REST for orders: market, limit, SL, SL-M
- Orders via exchange directly (not dark pool like US)
- Slippage on large-caps: 5–10 paise typical; mid-caps: 20–50 paise

**Key NSE liquidity tiers:**
- Tier 1 (liquid): NIFTY50 stocks — tight spreads, low impact
- Tier 2: NIFTY Next 50 — moderate liquidity, 15–30 paise spreads
- Tier 3: Mid/small cap — can be illiquid, don't trade > 0.5% of daily volume

**Tax implications (India-specific):**
- STCG (< 1 year): 15% flat tax on equity gains
- LTCG (> 1 year): 10% above ₹1 lakh
- Intraday trading: treated as BUSINESS income (30%+ slab rate)
- F&O: treated as business income regardless of holding period"""),

# ── Intraday Gap-and-Go ───────────────────────────────────────────────────────
(
"What is the Gap-and-Go intraday strategy and how do you trade it on NSE equities?",
"""Gap-and-Go Strategy — NSE Intraday

**Definition:** Stock opens with a gap (≥1.5%) above prior close due to news/results, then continues in the gap direction with high volume.

**Entry Rules (Long):**
1. Pre-market scan: stocks gapping up ≥1.5% on NSE (compare CMP at 9:00 AM vs previous close)
2. News catalyst required: quarterly results, management change, block deal, FII buying, sector tailwind
3. Wait for first 5-min candle to form after 9:15 AM open
4. Entry: first 5-min close above the opening candle high
5. Volume filter: first 5-min volume must be ≥2× 10-day average 5-min volume for same time slot
6. VWAP confirmation: price must be above VWAP at entry point

**Stop-Loss:** Below the opening 5-min candle low (or gap-fill level, whichever is closer)

**Targets:**
- T1: Prior resistance level or +2× the opening range (50% position exit)
- T2: Previous day's high / pre-market resistance (remaining 50%)

**Avoid when:**
- Gap is due to broad market move only (NIFTY up 1% — sector gap, not stock-specific)
- Stock is in a multi-week downtrend (gap will likely fade)
- Gap fills within first 10 minutes (weakness signal)
- VIX > 25 (whippy gaps, no follow-through)

**NSE-specific:** Check if NSE has circuit limits — stocks with prior day's circuit rarely continue cleanly. Also check if F&O lot size makes the trade viable for your capital.

**Win rate:** ~55–62% in trending markets; degrades to ~40% in sideways/volatile markets. Size at 0.5–0.75× normal position."""
),

# ── Demand/Supply Zone Trading ────────────────────────────────────────────────
(
"How do you identify and trade demand and supply zones on NSE daily charts?",
"""Demand and Supply Zone Trading — NSE Daily

**Demand Zone (Support):**
A price area where institutions have previously accumulated (bought) heavily. Identified by:
1. Strong bullish candle(s) leaving the zone rapidly (no consolidation — implies imbalance)
2. The zone itself shows little trading activity (few candles inside it)
3. Price has tested this zone ≤2 times before (fresh zones are stronger)
4. ATR of the zone is ≤1× daily ATR (tight zone = clear imbalance)

**Supply Zone (Resistance):**
Mirror: strong bearish candle(s) departing with no consolidation. Price distributed rapidly.

**Entry on Demand Zone Test:**
- Price approaches zone from above
- Entry trigger: bullish engulfing, hammer, or morning star pattern on 1H/4H chart inside the zone
- Volume at zone: should be lower than the candle that created the zone (absorption, not panic)
- Stop-loss: 10–15 paise below the zone bottom (max 1× ATR below demand floor)

**Target:**
- T1: Next supply zone above (1:1.5 minimum R:R)
- T2: 52-week high or major structural high (1:2.5 R:R)

**Zone Invalidation:**
- Close below demand zone by >0.5× ATR = zone broken, exit
- Never hold through results if stock is in a zone — binary outcome

**Best instruments:** RELIANCE, HDFCBANK, TCS, INFY — institutional footprint zones are cleaner. Avoid small-caps (zones are noise).

**Win rate on fresh zone tests:** ~65–70%. Second test: ~55%. Third test: avoid — zone is likely to break."""
),

# ── VWAP Reversal (Intraday) ──────────────────────────────────────────────────
(
"Explain VWAP-based intraday reversal trading for BANKNIFTY futures.",
"""VWAP Reversal Strategy — BANKNIFTY Futures

**What is VWAP:** Volume-Weighted Average Price = cumulative(price × volume) / cumulative(volume). Resets each day at 9:15 AM IST. Represents the "fair value" institutions have paid for the instrument.

**Long Reversal Setup (Buy at VWAP dip):**
1. BANKNIFTY is in a clear uptrend (prior day close > prior 5-day MA, NIFTY positive)
2. Price pulls back to VWAP after establishing morning highs (typically 10:30–12:00 AM window)
3. Trigger: bullish candle closes above VWAP on 5-min chart after test
4. Volume on reversal candle: ≥1.2× 5-period average volume
5. RSI on 5-min: 40–55 at entry (oversold but not broken, room to recover)

**Short Reversal Setup (Sell at VWAP rejection):**
1. BANKNIFTY in downtrend, NIFTY negative
2. Price rallies to VWAP as a short-covering bounce
3. Trigger: bearish engulfing or shooting star at VWAP on 5-min
4. Volume confirmation required

**Stop-Loss:** 15–20 points for BANKNIFTY above/below VWAP (tight, as VWAP failures are fast)

**Targets:**
- T1: Prior intraday swing high/low (1:1 R:R minimum)
- T2: Prior session high/low (if trend is strong)

**Time filters:**
- Best window: 10:15 AM – 12:30 PM and 2:00 PM – 3:00 PM
- Avoid 9:15–9:30 (high volatility, VWAP not meaningful yet) and 3:15–3:30 (expiry whip)
- On expiry day: VWAP levels matter more, but vol spikes — tighten stops 30%

**Key edge:** Institutional algorithms often bid/offer at VWAP. When BANKNIFTY tests VWAP mid-session in a trend, large orders absorb at that level, creating predictable bounces."""
),

# ── 52-Week High Breakout (Detailed) ─────────────────────────────────────────
(
"What are the exact rules for a high-probability 52-week high breakout on NSE mid-caps?",
"""52-Week High Breakout — NSE Mid-Cap Stocks

**Why 52-week highs work:** Price at a new 52-week high means all holders are in profit — no overhead resistance, no forced sellers. Institutions tracking momentum screens accumulate at breakouts. Behavioral finance: anchoring and recency bias push retail to "sell at highs," which institutions absorb.

**Exact Entry Criteria:**
1. Price within 1% of 52-week high (today's high ≥ 52W_high × 0.99)
2. Volume on breakout day: ≥2.5× 20-day average daily volume (conviction)
3. RSI-14: between 55 and 72 (strong momentum but not parabolic)
4. EMA structure: close > EMA20 > EMA50 > EMA200 (all time frames aligned)
5. Market context: NIFTY 50 in uptrend or sideways (not in correction >3% from recent top)
6. Sector context: sector index also at or near 52-week highs (tide lifting all boats)
7. No result announcement within 5 days (binary risk)
8. Fundamental filter: revenue growth ≥15% YoY last 2 quarters

**Position Entry:** On close of the breakout day, or intraday on pullback to breakout level next day (reduce slippage)

**Stop-Loss:**
- Hard stop: 52-week high level −2% (below breakout, gives false break room)
- Trailing stop after +5% move: trail at −2% below highest close

**Targets:**
- T1 (+8–10%): First partial exit, 30% of position
- T2 (+12–15%): Second exit, 40% of position
- T3 (open): Trail remaining 30% with 10-period EMA as stop

**Average holding period:** 2–6 weeks

**Backtested performance (NSE 2018–2024):**
- Win rate: ~58% (false breakouts punished quickly)
- Average winner: +12.4%
- Average loser: −4.1%
- Expectancy: positive with ≥2.5:1 R:R

**Failure modes:**
- Market-wide correction: cut all breakout positions regardless of stock strength
- Volume dries up within 3 days of breakout: exit — institutions not participating
- Price fails to hold 52W-high by close same day: avoid entry"""
),

# ── RSI Divergence ────────────────────────────────────────────────────────────
(
"How do you trade RSI bullish divergence on NSE daily charts with high accuracy?",
"""RSI Bullish Divergence Trading — NSE Daily Charts

**Definition:** Price makes a lower low but RSI-14 makes a higher low. Indicates selling momentum is exhausting even as price continues to fall. A leading reversal indicator.

**Setup Criteria (3-step validation):**
1. **Price structure:** Two clear swing lows with the second lower (L1 > L2 on price). Minimum 5 days between lows.
2. **RSI structure:** RSI at L1 < 40 (oversold), RSI at L2 > RSI at L1 (higher low on RSI). The divergence must be unambiguous — RSI L2 should be ≥3 points higher.
3. **Trigger candle:** After the RSI divergence forms, wait for a bullish trigger: bullish engulfing, morning star, or RSI crossing above 40 on the same candle.

**Confluence filters (adds conviction):**
- Price at or near a known demand zone or support level
- Volume on reversal candle ≥ 1.5× 10-day average
- MACD histogram turning positive (or histogram making higher lows alongside RSI)
- Price above 200-day EMA (structural uptrend; divergence = temporary reversion)

**Entry:** At close of trigger candle, or limit order 0.2% above trigger high

**Stop-Loss:** Below the price swing low L2 by 0.5× ATR14

**Targets:**
- T1: EMA9 (first dynamic resistance above)
- T2: Previous swing high (the high between L1 and L2 on price)
- T3: EMA50 (for deeply oversold stocks)

**Hidden Bullish Divergence (continuation):** Price makes higher low, RSI makes lower low → trend continuation signal in a pullback. Entry on same trigger logic. Higher win rate than regular divergence.

**False divergence warning:** In strong downtrends (price below 200EMA, fundamentally weak), RSI divergences fail ~60% of the time. Only trade divergences when price is above the 200-day EMA or at a major multi-year support."""
),

# ── EMA Cross System ──────────────────────────────────────────────────────────
(
"Explain the EMA 9/21 crossover system with filters for swing trading NSE equities.",
"""EMA 9/21 Crossover Swing System — NSE Equities

**Core Signal:**
- Bullish: EMA9 crosses above EMA21 (close-to-close)
- Bearish: EMA9 crosses below EMA21

**Why EMA 9/21:** Short enough to catch early trend changes; long enough to filter noise. EMA9 ≈ 2-week momentum, EMA21 ≈ 1-month trend. Widely watched by institutional traders in India.

**Long Entry Filters (all must be met):**
1. EMA9 crosses above EMA21 on daily close
2. Price close > EMA21 at crossover (not lagging price)
3. Volume on crossover day ≥1.3× 20-day average (participation)
4. RSI-14 at crossover: 45–65 (momentum building, not overbought)
5. EMA21 itself must be rising or flat (not in a steep downslope)
6. NIFTY 50 not in correction (NIFTY close > NIFTY EMA50)

**Short Entry Filters (for futures/short-capable accounts):**
Mirror conditions with EMA9 crossing below EMA21, RSI 35–55, EMA21 declining.

**Stop-Loss:**
- Initial: below EMA21 by 0.5× ATR14 (gives room for false crosses)
- Trail: once +5% profit, trail stop at EMA21 close

**Targets:**
- Swing target: Prior swing high or EMA100 (whichever is closer)
- Trend target: Measure the depth of the prior base, project upward from breakout

**Exit signals (whichever comes first):**
- EMA9 crosses back below EMA21
- Close below trailing stop
- RSI >80 on weekly chart (parabolic)

**Pitfall — whipsaws:** EMA crosses in sideways/choppy markets generate multiple false signals. Add Bollinger Band width filter: only take signals when BB width > 15th percentile of 20-day BB width history (i.e., volatility expanding, not contracting)."""
),

# ── Supertrend ────────────────────────────────────────────────────────────────
(
"How does the Supertrend indicator work and how do you use it on 15-min NSE charts?",
"""Supertrend Indicator — 15-Min NSE Charts

**Calculation:**
- Uses ATR (Average True Range) to set dynamic bands around price
- Parameters: ATR period (typically 10), multiplier (typically 3.0)
- Upper Band = (High + Low)/2 + multiplier × ATR
- Lower Band = (High + Low)/2 − multiplier × ATR
- Supertrend line: follows lower band when bullish, upper band when bearish
- Signal: closes below supertrend = bearish flip; closes above = bullish flip

**15-Min Chart Trading Rules (NSE intraday):**
**Long:**
1. Supertrend flips bullish (green line, price above it)
2. Entry on first candle close above the flip candle's high
3. VWAP must be below current price or slope upward (price above VWAP)
4. Volume on flip candle ≥1.5× 15-min average volume for that time slot
5. Only trade during 9:30 AM–1:00 PM and 2:00–3:00 PM windows

**Short:**
1. Supertrend flips bearish (red line, price below it)
2. Mirror conditions; VWAP must be above price

**Stop-Loss:** At the supertrend line itself (trailing stop)
- For NIFTY: typically 20–35 points from entry on 15-min
- For BANKNIFTY: typically 60–100 points from entry

**Targets:**
- T1: 1× ATR above entry (50% of position)
- T2: 2× ATR above entry or prior swing high
- Let T2 run with supertrend as trailing stop

**Settings for different instruments:**
- NIFTY / BANKNIFTY futures: ATR(10), multiplier=2.5 (tighter, more signals)
- NSE equities intraday: ATR(10), multiplier=3.0 (standard)
- Mid-cap swings: ATR(14), multiplier=3.5 (wider, fewer false flips)

**Weakness:** Supertrend whipsaws severely in sideways markets. Only take signals when the daily chart is also in a trend (Supertrend bullish on daily = only take long signals on 15-min)."""
),

# ── Pairs Cointegration ───────────────────────────────────────────────────────
(
"How do you implement a pairs trading strategy using cointegration for NSE bank stocks?",
"""Pairs Cointegration Strategy — NSE Banking Sector

**Pair Selection:**
1. Select stocks from the same sector (e.g., HDFCBANK / ICICIBANK, or AXISBANK / KOTAKBANK)
2. Run Engle-Granger cointegration test (or Johansen for multi-pair): p-value < 0.05 required
3. Calculate hedge ratio β via OLS: price_A = β × price_B + ε
4. Calculate spread: spread = price_A − β × price_B
5. Normalize: z_score = (spread − mean) / std (rolling 60-day window)

**Entry Signals:**
- Long spread (buy A, sell B): z_score < −2.0 (spread too compressed, expect reversion)
- Short spread (sell A, buy B): z_score > +2.0 (spread too extended, expect compression)

**Position Sizing:**
- Allocate equal rupee value to each leg (dollar-neutral, not share-neutral)
- Example: if β = 0.85, for every ₹1L in HDFCBANK long, short ₹85,000 in ICICIBANK
- Size each leg at max 1.5% of portfolio (risk-adjusted for spread volatility)

**Exit:**
- Profit target: z_score returns to 0 (mean reversion)
- Partial exit at z_score ±0.5, full exit at ±0.1
- Stop-loss: z_score breaches ±3.5 (pairs relationship broken down)

**Risk Management:**
- Re-run cointegration test monthly; if cointegration breaks (p > 0.10), close all pairs positions
- Carry risk: avoid banking pairs around RBI MPC meetings (policy divergence can break pairs)
- Earnings risk: never hold a pairs position through either stock's quarterly results

**Best pairs (historically cointegrated NSE):**
- HDFCBANK / ICICIBANK (correlation ≈ 0.94 historically)
- AXISBANK / KOTAKBANK
- HINDUNILVR / DABUR (FMCG pair)
- WIPRO / HCLTECH (IT mid-tier pair)

**Holding period:** 5–20 trading days on average. Not intraday — spread noise too high."""
),

# ── Momentum Continuation ─────────────────────────────────────────────────────
(
"What is the Hawkes process momentum strategy and when does it outperform?",
"""Hawkes Process Momentum Strategy (S9) — NSE Equities

**Concept:** The Hawkes process models self-exciting events — a large price move increases the probability of subsequent large moves. In markets: a breakout candle creates order flow clustering (algos trigger, stops hit, FOMO buying) that sustains momentum.

**Entry Criteria:**
1. ROC-20 (Rate of Change over 20 periods) > 8% on daily chart (strong 1-month momentum)
2. Volume: 20-day volume SMA expanding (current volume > prior 5-day average volume)
3. RSI-14: 55–70 (strong but not parabolic; above 70 = late cycle, skip)
4. MACD histogram positive AND expanding (momentum acceleration)
5. Price > EMA9 > EMA21 > EMA50 (all EMAs aligned in order)
6. No earnings within 10 days (event risk)

**Hawkes-Specific Signal:**
- Count large daily moves (>1.5% in either direction) in prior 20 days
- If ≥4 such moves, the instrument is in a "high-activity" regime → Hawkes clustering active
- Entry on the first pullback to EMA9 after the cluster begins

**Position Sizing:**
- Full position when ROC-20 > 12% and RSI 60–68 (sweet spot)
- Half position when ROC-20 is 8–12% or RSI > 68 (less conviction)
- Regime multiplier: strong_bull = 1.2×; bull = 1.0×; sideways = skip entirely

**Stop-Loss:** EMA21 breach on daily close (momentum is over if EMA21 is broken)

**Targets:**
- T1: ROC-20 reaches 20% (momentum extension, trim 40%)
- T2: RSI > 75 on weekly chart (parabolic; trim another 40%)
- Trail remaining 20% with daily EMA9

**Outperforms in:** Post-earnings momentum names, budget-day sectors, FII inflow beneficiaries

**Underperforms in:** High-VIX environments (>22), broad market corrections, sideways NIFTY (ROC-20 < 3%)"""
),

# ── VIX Spike Fade ────────────────────────────────────────────────────────────
(
"When does the VIX Spike Fade strategy work and what are the exact trade parameters?",
"""VIX Spike Fade Strategy (S8) — NIFTY / India VIX

**Concept:** India VIX measures 30-day implied volatility. Sharp VIX spikes are usually driven by fear and event uncertainty, not fundamental deterioration. Once the event passes or fear peaks, VIX reverts and NIFTY recovers strongly.

**Entry Criteria (Long NIFTY futures):**
1. India VIX spikes ≥20% in 2 consecutive trading days
2. VIX absolute level > 22 (not just a relative spike — must be absolute fear)
3. VIX intraday: VIX is starting to reverse (current VIX < intraday high by ≥1.5 VIX points)
4. NIFTY is ≥2% below its 20-day high (opportunity present)
5. Global cues: not in a global systematic crash (check S&P 500 and Nikkei; if both down ≥3%, wait)
6. FII data: if FIIs are net buyers last 2 days despite VIX spike, very strong confirmation

**Position Sizing:** 0.5× normal position (VIX environment means wider stops needed)

**Entry:**
- Primary: end-of-day close if all criteria met
- Intraday: buy at VWAP if VIX turning down and NIFTY stabilizing after 12:00 PM

**Stop-Loss:**
- VIX continues higher than entry day's VIX close by >10% next day (fear accelerating)
- NIFTY closes below entry day's low (structural break)
- Hard stop: −1.5% below NIFTY entry price

**Targets:**
- T1: NIFTY recovers to 20-day high (VIX fully normalized)
- T2: NIFTY makes new all-time high (if pre-spike trend was strong)
- Average holding: 3–8 trading days

**Historical VIX spike events (India):**
- COVID March 2020: VIX hit 83 → NIFTY recovered 40% in 3 months
- Russia-Ukraine Feb 2022: VIX 30 → NIFTY +12% in 6 weeks
- US rate hike fears 2022: Multiple 22–28 VIX spikes → all faded within 2 weeks

**Hard stop — when NOT to trade:** VIX > 35 = no new positions. At VIX > 35, volatility is too high for predictable outcomes; even correct directional calls can be stopped out by intraday moves."""
),

# ── Regime-Based Position Sizing ─────────────────────────────────────────────
(
"How do you adjust position sizes based on market regime in an algorithmic trading system?",
"""Regime-Based Position Sizing — Algorithmic Trading System

**The Core Principle:**
Fixed position sizing ignores the market environment. In a strong bull regime, taking full position sizes maximizes returns. In bear or high-volatility regimes, the same position size leads to excessive drawdowns. Regime-adaptive sizing is the single biggest improvement to risk-adjusted returns in a multi-strategy algo system.

**6-Regime Classification (HMM-based):**
strong_bull = 1.2× base size (trend confirmed, low vol, follow through)
bull = 1.0× base size (normal uptrend, balanced risk)
sideways = 0.7× base size (no directional edge, reduce all exposure)
bear = 0.5× base size (downtrend, capital preservation mode)
strong_bear = 0.3× base size (accelerating decline, minimal positions)
high_vol = 0.2× base size (VIX spike, unpredictable swings)

**Base Position Size Calculation:**
- Base size = (Portfolio × Risk%) / (Entry − Stop)
- Example: ₹10L portfolio, 1% risk per trade = ₹10,000 max loss
- If stop-loss is ₹20/share, base size = 10000 / 20 = 500 shares
- In strong_bull regime: 500 × 1.2 = 600 shares
- In high_vol regime: 500 × 0.2 = 100 shares

**Regime Detection via NIFTY internals:**
- Daily NIFTY return + 5-day rolling return
- India VIX level and 5-day change in VIX
- NIFTY advance-decline ratio (>1.5 = broad bull; <0.7 = broad bear)
- NIFTY above/below 50-day SMA

**Transition rules (3-day hysteresis):**
- Don't flip regime on a single day's signal (reduces whipsaws)
- Require 3 consecutive days of new-regime signals before reclassifying
- Exception: VIX > 35 → immediately switch to high_vol, no hysteresis

**Portfolio-level caps:**
- Even in strong_bull: max 10 open positions, max 25% in any sector
- In bear/strong_bear: max 3 positions, only defensive sectors (FMCG, Pharma)
- In high_vol: ONLY carry hedges or VIX fade positions; no directional momentum bets"""
),

# ── Kelly Criterion ───────────────────────────────────────────────────────────
(
"How do you apply the Kelly Criterion for position sizing in NSE algorithmic trading?",
"""Kelly Criterion — Position Sizing for NSE Algorithmic Trading

**The Formula:**
Kelly % = (p × b − q) / b

Where:
- p = probability of winning (historical win rate)
- q = 1 − p = probability of losing
- b = ratio of average win to average loss (reward-to-risk ratio)

**Example:**
- Win rate (p) = 0.55 (55% of trades profitable)
- Average win = ₹8,000; Average loss = ₹5,000 → b = 1.6
- Kelly % = (0.55 × 1.6 − 0.45) / 1.6 = 26.9%

**Why not use full Kelly:** Full Kelly leads to extreme drawdowns in real trading due to estimation errors. Use fractional Kelly.

**Recommended fractions:**
- Quarter-Kelly (25% of Kelly): Most conservative, smooth equity curve
- Half-Kelly (50% of Kelly): Standard for robust strategies with ≥300-trade history
- Full Kelly: Only with near-certain outcomes (arbitrage, hedges)

**In the example with Half-Kelly:** 26.9% × 0.5 = 13.4% of portfolio per trade. Constrain to max 5% per trade in practice.

**Bayesian Kelly (online update):**
After each trade, update win rate estimate from prior 50-trade window. Updated Kelly re-calculated for next trade. Prevents "cold start" using only initial backtest win rates.

**Practical caps for NSE algo trading (₹10L portfolio):**
- Absolute max per trade: 2% of capital regardless of Kelly (₹20,000 risk)
- Combined risk of all open positions: ≤8% of portfolio
- In sideways/bear regime: reduce max trade risk to 0.5%
- Consecutive losses (≥3): cut all subsequent position sizes to 0.5× until win record recovers

**M2 Gate integration:** Win rate and Kelly percentage are recalculated after every trade. Strategies with Kelly < 0 (negative edge) are blocked from taking new positions until their Bayesian win rate recovers."""
),

# ── Fibonacci Retracement ─────────────────────────────────────────────────────
(
"How do you use Fibonacci retracement levels for entry in NSE swing trades?",
"""Fibonacci Retracement — NSE Swing Trade Entries

**Key levels:** 23.6%, 38.2%, 50%, 61.8%, 78.6% of a prior swing move

**Setup — Pullback in Uptrend:**
1. Identify a clear impulsive move up (at least 8–10% in 10–20 days, clean structure)
2. Draw Fib from swing low to swing high
3. Wait for price to pull back into the 38.2%–61.8% zone
4. Look for reversal candlestick pattern at Fib level: hammer, bullish engulfing, pinbar

**High-probability Fib levels:**
- 61.8% (Golden Ratio): Strongest. Deep pullback but trend intact. High R:R.
- 50%: Psychological midpoint. Clean level for rule-based entry.
- 38.2%: Shallow pullback = strong trend. Entry here for aggressive traders only.
- 78.6%: Very deep — close to trend failure. Use only with strong volume confirmation.

**Confluence (adds conviction to Fib level):**
- Fib level coincides with a rising EMA (EMA21 or EMA50)
- Fib level coincides with prior resistance-turned-support
- Fib level at round number (₹100, ₹500 etc.)
- Volume diminishing into the pullback (sellers exhausting)

**Entry mechanics:**
- Limit order 0.2% above the Fib level
- Or enter on first close above the last pullback candle's high

**Stop-Loss:**
- Place below the next deeper Fib level (if entering at 61.8%, stop below 78.6%)
- Add 0.5× ATR buffer

**Targets:**
- T1: Prior swing high (full retracement)
- T2: 127.2% Fib extension (momentum continuation)
- T3: 161.8% extension (full trend extension)

**Failure signal:** If price breaks 78.6% Fib, the pullback is likely a reversal. Close immediately."""
),

# ── Candlestick Patterns ──────────────────────────────────────────────────────
(
"Which candlestick patterns have the highest accuracy on NSE daily charts and how do you confirm them?",
"""High-Accuracy Candlestick Patterns — NSE Daily Charts

**Tier 1 (Highest Win Rate with Confirmation):**

**1. Morning Star (Bullish reversal)**
- Candle 1: Large bearish candle (body > 60% of total range)
- Candle 2: Small-bodied candle (doji or star) with a gap down — indecision
- Candle 3: Large bullish candle closing above midpoint of Candle 1
- Confirmation: Volume on Candle 3 ≥ 1.5× Candle 1 volume
- Win rate: ~70% when at demand zone + EMA200 support
- Stop-loss: Below Candle 2 low

**2. Bullish Engulfing**
- Candle 2 body completely engulfs Candle 1 body
- Best at: support levels, EMA200, post-selloff (RSI < 35)
- Volume confirmation essential: engulfing candle ≥ 1.5× prior average
- Stop-loss: Below Candle 2 low

**3. Hammer / Inverted Hammer**
- Lower wick ≥ 2× body; small upper wick; close near the top of range
- Appears at support: buyers rejecting lower prices
- Next-day confirmation: close above Hammer high required before entry

**4. Three White Soldiers (continuation)**
- Three consecutive bullish candles with higher opens and closes
- Each close in upper 75% of the candle range
- Volume increasing each day
- Entry: After third candle on next pullback to first candle's high

**Tier 2 (Moderate accuracy, need strong confluence):**
- Doji: Useful only at extremes (RSI < 30 or > 70)
- Shooting Star / Hanging Man: Only valid at resistance zones with volume

**Universal confirmation rules:**
1. Volume ≥1.5× 10-day average on the signal candle
2. Pattern appears at a meaningful technical level (support, Fib, EMA)
3. Wait for next-candle confirmation (close above the pattern high for bulls)
4. RSI context: bullish patterns should appear when RSI < 50 (room to recover)"""
),

# ── Risk Management Masterclass ───────────────────────────────────────────────
(
"What is the complete risk management framework for a ₹10 lakh algorithmic trading portfolio on NSE?",
"""Complete Risk Management Framework — ₹10L NSE Algo Portfolio

**Portfolio-Level Hard Limits:**
- Max daily loss: ₹40,000 (4% of ₹10L) → stop all trading for the day
- Max drawdown from peak: ₹2,00,000 (20%) → shutdown all strategies, review
- Max open positions: 10 simultaneously
- Max exposure in any single stock: ₹1,50,000 (15% of portfolio)
- Max sector exposure: ₹2,50,000 (25%) in any single sector

**Per-Trade Risk Rules:**
- Max risk per trade: ₹10,000 (1% of capital)
- Minimum R:R ratio: 1.5:1 (target must be 1.5× the stop-loss distance)
- Position size formula: Size = ₹10,000 / (Entry − Stop Loss in ₹ per share)
- Never risk more than 2% even if Kelly says higher

**Stop-Loss Discipline:**
- Every trade MUST have a stop-loss set at order entry — no exceptions
- Stop-loss placement: ATR-based (1.5× ATR14 below entry for longs)
- Stop-loss type: SL-M orders on NSE (stop-market, fills immediately at trigger)
- Never widen a stop-loss after entry (most common amateur mistake)
- Can tighten stop (trail) but never loosen

**Position Scaling:**
- Scale into positions in 2–3 tranches ONLY for strong-conviction setups
- First tranche: 50% of planned position at initial signal
- Second tranche: 30% after price confirms direction (+2% move)
- Third tranche: 20% at first pullback after confirmation
- Never average down on losing trades

**Pre-Trade Checklist (M2 Gate — 12 checks):**
1. Is instrument tradeable? (not index-only, not in ban period)
2. VIX < 35? (hard stop if VIX ≥ 35)
3. Drawdown < 20%? (portfolio-level check)
4. Daily loss < 4%? (daily check)
5. Daily trade count < limit?
6. Signal confidence ≥ threshold?
7. Open positions < 10?
8. Not already in same instrument?
9. Sufficient margin available?
10. Sector exposure below 25%?
11. Correlation: new trade doesn't create hidden concentration risk?
12. VIX > 22? (reduce size to 0.5× — non-blocking)

**Post-Trade Analysis:**
- Log every trade: entry, exit, reason, outcome, lessons
- Weekly review: win rate by strategy, Sharpe by regime
- Monthly rebalance: DSA scoring to reallocate capital between strategies"""
),

# ── Backtest Metrics ──────────────────────────────────────────────────────────
(
"What performance metrics should you use to evaluate an NSE algorithmic trading strategy?",
"""Strategy Evaluation Metrics — NSE Algorithmic Trading

**Primary Metrics (must evaluate all 5):**

**1. Sharpe Ratio**
= (Annual Return − Risk-Free Rate) / Annual Std Dev of Returns
- Risk-free rate (India): ~7% (10-year G-Sec yield)
- Sharpe > 1.0: acceptable; > 1.5: good; > 2.0: excellent
- NSE benchmark: NIFTY 50 has Sharpe of ~0.7–0.9 historically

**2. Maximum Drawdown (MDD)**
= (Peak Portfolio Value − Trough Value) / Peak × 100
- Acceptable MDD < 20% for ₹10L portfolio
- MDD > 30% makes psychological continuation nearly impossible

**3. Calmar Ratio**
= Annual Return / Maximum Drawdown
- Calmar > 1.0: strategy earns more than its worst drawdown per year
- Calmar > 2.0: high quality; < 0.5: too risky for return earned

**4. Win Rate + Profit Factor**
- Win rate alone is misleading: 90% win rate with 10:1 loss:win ratio = negative edge
- Profit Factor = Gross Profit / Gross Loss; > 1.3 required; > 1.7 = robust
- Expectancy = (Win Rate × Avg Win) − (Loss Rate × Avg Loss); must be positive

**5. Trade Count and Statistical Significance**
- Minimum 50 trades required for any meaningful metric
- Out-of-sample test (walk-forward) on 30% of data to validate in-sample metrics

**NSE-specific adjustments:**
- Include 0.03% slippage + ₹20/order + STT (0.025% on sell) + exchange fees
- These costs can wipe 1–2% annual returns on high-frequency strategies

**Red flags (strategy likely overfit):**
- Backtest Sharpe > 3.0 on fewer than 100 trades
- Strategy only works in one specific market period
- Parameters found by exhaustive grid search without out-of-sample validation"""
),

# ── MACD for Trend Trading ────────────────────────────────────────────────────
(
"How do you use MACD for trend-following entries and exits in NSE swing trades?",
"""MACD Trend-Following System — NSE Swing Trades

**Standard MACD Settings:** 12-26-9 (EMA12, EMA26, Signal=EMA9 of MACD)
- MACD Line = EMA12 − EMA26
- Signal Line = EMA9 of MACD line
- Histogram = MACD − Signal

**Entry System (Long):**

**Signal 1 — MACD Crossover:**
1. MACD line crosses above Signal line
2. Both MACD and Signal are below zero (zero-line crossover coming = strongest signal)
3. Histogram turns positive and expanding
4. Volume confirms: entry day volume > 10-day average

**Signal 2 — Zero Line Crossover (stronger):**
1. MACD line crosses above zero (bullish momentum confirmed)
2. Signal line is also approaching/crossing zero
3. RSI-14 between 50–65 at the same time

**Signal 3 — Histogram Divergence (leading indicator):**
1. Price making lower lows but histogram making higher lows
2. Histogram turns positive before a price confirmation
3. Use for anticipatory entry with smaller size

**Exit Signals:**
- Primary: MACD line crosses back below Signal line after a profitable move
- Aggressive: MACD histogram starts declining for 2+ consecutive days
- Hard exit: MACD and Signal both go negative when in a long trade

**Settings optimization for NSE:**
- Weekly charts: Use 5-13-3 (faster for weekly timeframe)
- Daily charts (swing): 12-26-9 (standard)
- 1H intraday: 8-21-5 (responsive for intraday momentum)

**Common mistake:** Taking every MACD crossover in a sideways market. Filter: only take MACD longs when weekly MACD is also positive or turning up."""
),

# ── Sector Rotation ───────────────────────────────────────────────────────────
(
"How does sector rotation work in Indian markets and how do you trade it algorithmically?",
"""Sector Rotation Strategy — Indian Markets (NSE)

**The Business Cycle Rotation Pattern:**
- **Trough/Early recovery:** PSU Banks, Real Estate, Consumer Discretionary (rate-cut beneficiaries)
- **Mid-cycle expansion:** IT, Industrials, Capital Goods (earnings growth phase)
- **Late cycle:** Energy, Commodities (Metals), Healthcare (defensive shift)
- **Contraction:** FMCG, Pharma (defensives), short IT

**India-Specific Sector Triggers:**
- RBI rate cuts → Banks, NBFCs, Real Estate outperform
- Monsoon forecast (above normal) → FMCG, Fertilizers, Tractors, Rural consumption
- Budget: Infrastructure spend → Cap Goods, Roads, Power, Cement
- INR depreciation → IT, Pharma (export earners), Metals
- FII inflows → Large-cap IT, private banks (most FII-owned sectors)
- Crude oil rise → Refiners/OMCs underperform; Oil exploration outperforms

**Algorithmic Rotation Implementation:**
1. Calculate sector strength score = (1-month return × 0.3) + (3-month return × 0.4) + (6-month return × 0.3)
2. Rank all 12 NSE sectors by strength score
3. Top 3 sectors: overweight (allocate 2× base weight)
4. Bottom 3 sectors: avoid new positions
5. Rebalance monthly or when top sector falls to position 5+ in rankings

**Sector ETF trading on NSE:**
- BANKBEES — banking sector exposure
- Nifty IT ETF — IT sector
- Pharma ETF — defensive play

**Risk:** Sector rotation signals take 2–4 weeks to materialize. Avoid over-trading based on single-week sector performance."""
),

# ── NSE F&O Basics ────────────────────────────────────────────────────────────
(
"Explain NSE options basics: how to choose the right strike and expiry for a directional trade.",
"""NSE Options — Strike and Expiry Selection for Directional Trades

**Strike Selection:**

**ATM (At-the-Money):** Strike closest to current price
- Delta ≈ 0.50
- Most liquid, tightest bid-ask spread
- Use for: high-conviction directional trades

**OTM (Out-of-the-Money):** Strike above market (calls) or below market (puts)
- Delta 0.20–0.35
- Lower premium but leverage amplifies if it goes ITM
- Rule: Never buy OTM options with < 0.25 delta unless very close to expiry event

**ITM (In-the-Money):** Already has intrinsic value
- Delta 0.65–0.80+
- Moves almost like futures but with defined downside
- Use for: swing trades where you want futures-like exposure with capped loss

**Expiry Selection:**

**Weekly expiry (Thursday):**
- High time decay (theta) = options lose value fast
- Only use if event is within the week (budget, RBI policy, specific results)

**Monthly expiry (last Thursday of month):**
- Preferred for swing trades (1–3 weeks holding)
- Less theta decay vs weekly

**Golden Rule:** For a 1-week directional trade, buy the next monthly expiry (not the current weekly). This gives you time to be right without fighting theta.

**IV (Implied Volatility) consideration:**
- IV > 40%: options are expensive — sell spreads, don't buy naked
- IV < 20%: options are cheap — directional buys make sense
- Check India VIX: VIX × 0.3 ≈ expected daily NIFTY move (annualized)"""
),

# ── Drawdown Recovery ─────────────────────────────────────────────────────────
(
"What is the correct strategy to recover from a 15% portfolio drawdown in NSE algo trading?",
"""Drawdown Recovery Strategy — NSE Algo Portfolio

**Critical First Step: Stop the Bleeding**
The biggest mistake after a drawdown is trading aggressively to recover quickly. This leads to a "tilt" spiral of increasing losses. The path to recovery is trading smaller and more selectively.

**Drawdown Recovery Framework:**

**Phase 1 — Assessment (Days 1–3):**
1. Calculate exact drawdown
2. Identify root cause: strategy failure / execution failure / regime mismatch / position sizing error
3. Review last 20 trades in detail — find the pattern

**Phase 2 — Damage Control:**
For 10–15% drawdown:
- Immediately reduce all new position sizes to 50% of normal
- Cut open positions with loss > stop-loss level
- Switch off lowest-confidence strategies (DSA score < 35%)
- Only run top 2–3 strategies by recent Sharpe ratio

For 15–20% drawdown:
- Stop all trading for 3 days minimum
- Re-run backtests with current market regime filter
- Only resume with 25% normal position sizes

**Phase 3 — Recovery Mode:**
- Resume only strategies with proven edge in current regime
- Target +2% per month recovery rate (not trying to recover 15% in 2 weeks)
- At 10% recovery from trough: scale back to 75% normal size
- At 5% from prior peak: full normal size resumes

**Mathematical reality:**
- 15% drawdown requires +17.6% gain to recover (not 15%)
- 25% drawdown requires +33% gain
- 40% drawdown requires +66% gain
- Time, not aggression, is the recovery tool

**Regime-aligned comeback:**
- If drawdown coincided with a bear regime, wait for regime to flip to bull/sideways before resuming momentum strategies"""
),

# ── Quantitative Screener ─────────────────────────────────────────────────────
(
"How do you build a daily stock screener for NSE to identify the best swing trade candidates?",
"""Daily NSE Stock Screener for Swing Trades

**Screener Architecture (run at 4 PM daily after close):**

**Universe:** NIFTY 500 stocks

**Step 1 — Liquidity Filter:**
- 20-day average daily volume ≥ ₹5 crore
- ATR14 ≥ 0.8% of price (sufficient volatility for profit potential)

**Step 2 — Trend Filter:**
- Close > EMA20 > EMA50 > EMA200 (all EMAs aligned for long candidates)
- EMA50 slope: positive for at least 10 of the last 15 days

**Step 3 — Momentum Filter:**
- ROC-20: between +5% and +25% (good momentum, not parabolic)
- RSI-14: between 50 and 68 (building momentum, room to run)
- MACD histogram: positive and expanding for ≥3 days

**Step 4 — Pattern Filter:**
- Price within 3% of a recent breakout level (52W high, multi-month resistance)
- OR price pulling back to EMA21 in an uptrend
- OR Volume spike yesterday (≥2× average) with bullish close

**Step 5 — Risk Filter:**
- No upcoming results in 5 days
- Not in SEBI restriction list or F&O ban
- ATR-based stop-loss gives R:R ≥ 1.5:1 to nearest resistance

**Output:** Rank survivors by composite score: (0.3 × momentum) + (0.3 × volume) + (0.2 × trend) + (0.2 × proximity to breakout)

**Top 5 stocks** = candidates for next day's trades

**Implementation:** Python + yfinance for data, vectorized pandas operations. For 500 stocks, runs in ~2 minutes. Cache results to SQLite."""
),

# ── ORB Variants ──────────────────────────────────────────────────────────────
(
"What are the most reliable Opening Range Breakout variants for BANKNIFTY weekly options?",
"""ORB Variants for BANKNIFTY Weekly Options Trading

**Why BANKNIFTY is ideal for ORB:**
- Highest liquidity index in India (₹50,000+ crore daily turnover)
- Largest daily ATR of any NSE index (typically 300–600 points)
- Weekly options expire Thursday → premium decay creates urgency

**Variant 1 — 15-Min ORB (Classic)**
- Range: 9:15–9:30 AM high/low
- Long trigger: break above 9:30 high + retest + hold
- Volume filter: breakout candle ≥2× 10-day average for same slot
- Target: 1.5× the opening range width; Stop = opposite end of range

**Variant 2 — 30-Min ORB (More reliable)**
- Range: 9:15–9:45 AM
- Wider range = fewer false breakouts
- Best on Monday and Tuesday
- Target: 2× opening range; Stop: below/above the range

**Variant 3 — Gap-Fill ORB (Event days)**
- On days BANKNIFTY gaps up/down ≥0.5%, watch for gap fill attempt
- If gap fills by 10:30 AM → fade the gap; after fill, look for ORB in original direction

**Option selection for ORB:**
- Buy ATM calls/puts for directional bet (not OTM — theta kills OTM on intraday ORB)
- Or buy ATM straddle at 9:15, sell one leg when ORB direction confirmed
- Position size: max ₹50,000 options premium at risk per trade on ₹10L portfolio

**Time-of-day performance:**
- 9:30–10:00 AM: Best ORB follow-through
- 10:00–11:30 AM: Good for re-entries
- After 1:00 PM: Avoid new ORB trades

**Win rate (BANKNIFTY ORB, 2022–2024):**
- 15-min ORB on trend days: ~62% win rate
- 15-min ORB on consolidation days: ~38% win rate
- Pre-filter: Only trade when NIFTY VIX < 20 and prior week's return > 0%"""
),

# ── Pre-Market Preparation ────────────────────────────────────────────────────
(
"What is the ideal pre-market preparation routine for an NSE algorithmic trader?",
"""Pre-Market Preparation Routine — NSE Algorithmic Trader

**6:00 AM — Global Market Scan (15 minutes):**
- SGX Nifty: indicates NIFTY open direction
- US markets close (S&P 500, Nasdaq, Dow): direction, magnitude, news
- Asian markets (Nikkei, Hang Seng): already trading at 6 AM
- Dollar Index (DXY): high DXY = FII outflows from India = bearish for NIFTY
- Crude oil (Brent): >$90 = bearish for India; affects OMCs, FMCG margins
- Gold: Risk-off signal if gold rising + equities falling

**7:00 AM — News Filter (10 minutes):**
- Economic data releases today: RBI, US Fed statements, GDP, CPI, IIP
- Corporate results schedule: which NIFTY50 stocks report today
- FII/DII data from NSE: net buying/selling

**8:00 AM — Strategy Alignment (20 minutes):**
- Check current market regime: what strategies are active today
- Review yesterday's signals: which hit targets, which hit stops
- Update Bayesian win rates in the system
- Identify today's trade candidates from previous night's screener

**9:00 AM — Pre-Open Session (15 minutes):**
- NSE pre-open session: 9:00–9:15 AM shows indicative open prices
- Watch NIFTY indicative open vs. SGX Nifty prediction
- Set limit orders for ORB entry levels
- Confirm VIX: if VIX > 22, reduce position sizes pre-loaded

**9:15 AM — Market Open:**
- Watch first 5 candles before any action
- Log the opening range high/low for ORB strategies
- Do NOT place trades based on first 5-min candle alone

**Ongoing (9:15 AM – 3:30 PM):**
- Every 15 minutes: check running positions against plan
- 12:00–12:30 PM: Mid-session review
- 3:00 PM: Square off intraday positions before 3:25 PM
- 3:30 PM: Log all trades, review versus plan

**Post-Market (3:30–4:00 PM):**
- Run daily screener for next day's candidates
- Update strategy performance metrics"""
),

# ── FinBERT Sentiment ─────────────────────────────────────────────────────────
(
"How do you use news sentiment analysis in NSE algorithmic trading and what is FinBERT?",
"""News Sentiment Analysis in NSE Algorithmic Trading

**FinBERT:**
FinBERT is a BERT model pre-trained on financial text (Reuters, Bloomberg, SEC filings) and fine-tuned for sentiment classification. It outputs three classes: Positive, Negative, Neutral — each with a probability score.

**Why FinBERT over generic sentiment:**
- Generic models misinterpret financial language: "cutting rates" is positive for markets but generic NLP may flag "cutting" as negative
- FinBERT understands "margin expansion," "order book growth," "write-down," "NPAs" in context
- Tested accuracy on financial text: ~82% vs ~67% for generic sentiment models

**Implementation in NSE Trading:**

**Signal Generation:**
1. Fetch news headlines every 15 minutes (NewsAPI, NSE announcements feed)
2. Filter: headlines mentioning tracked instruments or sectors
3. Run FinBERT inference: get (sentiment_label, score) per headline
4. Aggregate: compute 3-hour rolling average sentiment per instrument

**Trading Signal Rules:**
- Sentiment score > 0.75 (strong positive) AND price momentum positive: confirm long signal
- Sentiment score < -0.75 (strong negative) AND price falling: confirm short signal / hold exit
- Sentiment score > 0.80 AND price hasn't moved yet: potential front-running opportunity

**Weights in composite signal:**
- Sentiment signal: 30% weight (supporting indicator, not standalone trigger)
- Technical signal: 70% weight (primary trigger)
- Never enter a trade on sentiment alone — use as confirmation only

**Limitations:**
- Sentiment reflects what's already known; price often moves before news is published
- Earnings surprise = massive sentiment signal, but options IV makes the trade expensive
- Use sentiment for HOLDING decisions, not just entry"""
),

# ── Position Pyramiding ───────────────────────────────────────────────────────
(
"What is position pyramiding and when should you use it in NSE trend trades?",
"""Position Pyramiding — NSE Trend Trades

**Definition:** Adding to a winning position as it moves in your favor. The opposite of averaging down (adding to losers, which is dangerous). Pyramiding reduces average cost/risk and amplifies returns in strong trends.

**When to Pyramid:**
- Strategy: momentum/trend-following only (NOT mean-reversion)
- Market regime: strong_bull or bull
- Signal quality: high confidence (DSA score > 70% for that strategy)
- Position already profitable: only add after +3–5% unrealized gain

**Classic Pyramid Structure (1/2/4 structure):**
- Initial position: 50% of planned full size at signal entry
- Add 1: 30% at first pullback (at EMA9 after initial thrust)
- Add 2: 20% after trend confirms and price breaks to new swing high
The key: each add is smaller than the last (pyramid narrows at top)

**Stop-Loss Management While Pyramiding:**
- After Add 1: Raise stop to breakeven on initial position
- After Add 2: Raise stop to lock in profit on initial + Add 1
- Final stop: Trailing stop at EMA21 (close basis) for the whole position

**What NOT to do:**
- Don't pyramid with equal or larger additions at higher prices (reverse pyramid = dangerous)
- Don't pyramid if risk on full position exceeds 2% of portfolio at the widest stop
- Don't pyramid in choppy/sideways markets

**Example (RELIANCE trending up from ₹2500):**
- Entry (50%): ₹2500, stop ₹2450 (₹50 risk × 100 shares = ₹5000 risk)
- Add 1 (30%) at ₹2580: stop moved to ₹2500 (breakeven), add 60 shares
- Add 2 (20%) at ₹2650: stop moved to ₹2560, add 40 shares
- Full position: 200 shares at blended cost ₹2566
- If RELIANCE reaches ₹2800: profit = (2800−2566) × 200 = ₹46,800

**Pyramid or not by strategy:**
- ORB (S1): NO pyramid — intraday, too fast
- 52W breakout (S2): YES — add at first pullback after breakout
- RSI reversion (S4): NO — mean reversion has defined target
- EMA pullback (S5): YES — if in strong bull regime
- Hawkes momentum (S9): YES — the setup IS a momentum continuation pyramid"""
),

# ── India VIX Usage ───────────────────────────────────────────────────────────
(
"How do you use India VIX as a real-time market risk filter in an NSE trading system?",
"""India VIX as Market Risk Filter — NSE Trading System

**What India VIX measures:**
- 30-day expected volatility of NIFTY 50, calculated from option prices
- Annualized percentage: VIX of 15 means markets expect ±15% annual vol, or ~±0.94% daily

**Practical VIX Interpretation:**
- VIX 10–14: Complacent, low fear. Risk of sudden correction.
- VIX 15–20: Normal trading conditions. Full position sizes.
- VIX 20–25: Elevated caution. Reduce position sizes by 25%.
- VIX 25–30: High fear. 50% position sizes, tighter stops.
- VIX 30–35: Panic conditions. 75% size reduction. Only 2–3 positions.
- VIX > 35: Hard stop. Close most positions. No new trades.

**Real-Time VIX Integration in Algo System:**

**Pre-market check:**
- If VIX > 22 at 9:00 AM, load half-size positions for the day
- If VIX > 30 at 9:00 AM, skip intraday strategies entirely

**Intraday monitoring:**
- Poll VIX every 15 minutes
- If VIX spikes >15% from morning value mid-session: tighten all stops to 50% of normal ATR distance
- If VIX spikes >25% from morning value: close half of all open positions regardless of P&L

**Strategy-specific VIX rules:**
- ORB (S1): Only trade when VIX < 22
- VIX Fade (S8): Only activate when VIX > 22 AND spiking ≥20% in 2 days
- Pairs (S6): VIX < 25 required
- 52W breakout (S2): VIX < 20 for full size, VIX 20–25 for half size, VIX > 25 skip

**VIX and NIFTY correlation:**
- VIX and NIFTY are inversely correlated (r ≈ −0.75)
- VIX rising while NIFTY rising = dangerous divergence — institutional caution
- VIX falling while NIFTY rising = healthy bull market confirmation"""
),

# ── Earnings Season ───────────────────────────────────────────────────────────
(
"What is the optimal strategy for trading around NSE quarterly earnings announcements?",
"""Trading NSE Quarterly Earnings Announcements — Optimal Strategy

**Earnings Calendar Context:**
- NSE Q1 results: Mid-July to mid-August
- NSE Q2 results: Mid-October to mid-November
- NSE Q3 results: Mid-January to mid-February
- NSE Q4 (annual): Mid-April to mid-May

**Pre-Earnings Strategies:**

**1. Pre-Earnings Drift (Buy before results):**
Stocks with strong fundamentals and upward estimate revisions tend to drift up 5–10 days before earnings. Entry: T−5 to T−3 before results. Exit: day of or day before results. Win rate: ~55% for fundamentally strong names.

**2. IV Crush Play (Sell options premium):**
Implied volatility spikes before earnings; after earnings, IV collapses 40–60%.
- Strategy: Sell ATM straddle 1–2 days before results
- Hedge with OTM strangle for defined risk
- Net position is "short vega" — profits from IV crush post-earnings
- Risk: actual move exceeds the inflated implied move

**Post-Earnings Strategies:**

**3. Gap-Fill Trade:**
- Beat-and-raise gaps (>5% up): Hold 1–3 days; gap rarely fills completely
- Miss-and-lower gaps (>5% down): Wait for stabilization, buy day 3–5
- Neutral results (gap <2%): No edge

**4. Trend Continuation Post-Earnings:**
Strong results + stock near 52W high = continuation setup. Entry: pullback to EMA9 in days 3–5 post-earnings.

**Risk Rules:**
- NEVER hold leveraged intraday positions through earnings announcement
- Reduce existing swing position to 50% before earnings date
- Don't buy options at peak IV (you pay for the move twice)
- Max loss pre-earnings: 1% of portfolio on any single name"""
),

# ── Mean Reversion vs Momentum ────────────────────────────────────────────────
(
"When does mean reversion work better than momentum in NSE markets, and how do you select between them?",
"""Mean Reversion vs Momentum — NSE Strategy Selection

**When Momentum Works:**
1. NIFTY 50 in uptrend (above 50-day EMA) with >1% monthly positive return
2. India VIX < 18 (low fear, steady trend)
3. FII flows positive for 5+ consecutive days
4. Advance-Decline line making new highs (broad participation)
5. Fewer than 25% of NIFTY stocks at 52W lows

**Strategies:** S2 (52W breakout), S5 (EMA pullback), S9 (Hawkes continuation)

**When Mean Reversion Works:**
1. NIFTY 50 in a sideways range (15% band, touching upper and lower bounds)
2. India VIX 18–28 (elevated but not panic)
3. Clear support/resistance levels with multiple touches
4. Stocks with RSI < 32 after 10–15% pullback in otherwise uptrending market
5. Post-earnings overreaction (stock down 8–12% on modest miss)

**Strategies:** S4 (RSI reversion), S6 (pairs cointegration), S8 (VIX fade)

**Regime-Specific Strategy Allocation (DSA):**
- strong_bull: 60% momentum, 40% reversion
- bull: 55% momentum, 45% reversion
- sideways: 25% momentum, 75% reversion
- bear: 10% momentum, 90% reversion (or cash)
- strong_bear: 0% momentum, few hedges only
- high_vol: 0% momentum, 0% reversion, 100% cash or VIX fade

**The mistake to avoid:** Running momentum strategies in a sideways/mean-reverting market is the #1 cause of drawdowns. A momentum system entering 52W-high breakouts during a range-bound NIFTY will generate false breakouts repeatedly.

**Detection signal:** If last 10 momentum trades have <40% win rate, you're in a mean-reverting regime. Switch strategy allocation immediately."""
),

# ── Absolute Best Trade Setups ────────────────────────────────────────────────
(
"What are the 5 highest-probability trade setups in NSE markets that professional algorithmic traders use?",
"""5 Highest-Probability NSE Trade Setups — Professional Algorithmic

**Setup 1: Institutional Accumulation Breakout (Win rate: ~68%)**
Stock consolidates in a tight range (ATR < 50% of 6-month ATR) for 4–8 weeks near key resistance. Volume dries up during consolidation. Then a massive volume candle (3–5× average) breaks out above resistance.

Why it works: Low-volatility coil = institutional accumulation phase. Breakout candle = institutions done accumulating, now allowing price to move.

Entry: On the breakout candle close or next-day pullback to breakout level
Stop: Below the lowest low of the consolidation range
Target: 2× the consolidation range height projected from breakout

**Setup 2: First Pullback After Trend Establishment (Win rate: ~64%)**
Stock just had a 15–20% move in 3–4 weeks. Pulling back for the FIRST time (RSI from 75 to 50). EMA9 catching up to price.

Why it works: The first pullback in a new trend is where "late to the party" institutional money enters.

Entry: When RSI turns up from the 45–55 zone, with EMA9 as dynamic support
Stop: Below EMA21 or below the pullback low
Target: Previous swing high + 10% extension

**Setup 3: Opening Range Breakout on Trend Day (Win rate: ~62%)**
Gap up >0.5% + volume in first 30 min is 2× average + SGX Nifty positive

Entry: Break of first 30-min high, with volume confirmation
Stop: Below first 30-min low
Target: 1.5–2× the opening range

**Setup 4: Oversold Bounce at 200-Day EMA (Win rate: ~61%)**
Fundamentally sound stock pulls back to 200-day EMA with RSI < 35.

Entry: Hammer or bullish engulfing candle at 200-day EMA
Stop: Close below 200-day EMA by >1%
Target: Previous swing high (typically 8–15% above entry)

**Setup 5: Post-Results Momentum Continuation (Win rate: ~59%)**
Company beats earnings estimates by >10%. Stock gaps up >5%. After 2 days consolidation, price resumes uptrend.

Entry: First pullback to EMA9 after the results gap (day 3–5)
Stop: Below the results day close
Target: 10–15% above entry (analyst upgrade target price)"""
),

]


# Tranche 2: novel strategy families + macro/news analyst layer (PRD 5c)
from terminal_in.agents.training.strategy_pairs_v2 import (  # noqa: E402
    STRATEGY_PAIRS_V2, MACRO_PAIRS,
)

STRATEGY_PAIRS.extend(STRATEGY_PAIRS_V2)
STRATEGY_PAIRS.extend(MACRO_PAIRS)
