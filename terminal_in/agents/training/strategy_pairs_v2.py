"""
Strategy QA pairs, tranche 2 — novel families beyond the system's S1–S9
playbook (Claude-as-teacher, PRD 5c). Quality bar: every pair states the
MECHANISM (why the edge exists and who is on the other side), not just the
rule. Citations are to the originating academic work or documented market
structure; statistics are qualitative unless a primary source is named.

Appended to STRATEGY_PAIRS by strategy_pairs.py.
"""

STRATEGY_PAIRS_V2: list[tuple[str, str]] = [

(
"What is post-earnings announcement drift (PEAD) and how would you trade it on NSE stocks?",
"""Post-Earnings Announcement Drift (PEAD) — Bernard & Thomas (1989)

**Mechanism:** prices underreact to earnings surprises because investors anchor
on prior expectations and update slowly; institutions also scale in over days
to limit impact. The surprise therefore *continues* to move price for weeks.

**Rules (NSE adaptation):**
- Compute standardized unexpected earnings (SUE) = (actual − consensus) / σ of
  past surprises; no consensus data → use earnings vs 4-quarter trailing trend
- Enter within 2 sessions of the result in the direction of the surprise,
  but only if the day-1 reaction agrees (gap + close in surprise direction)
- Hold 20–40 sessions; stop = day-1 reaction low/high
- Strongest in mid-caps with thin analyst coverage; weak in Nifty-50 names

**Caveats:** earnings season clusters risk; avoid names with simultaneous
corporate actions; India's T+1 and 20% circuit limits can trap exits on
re-rating days.""",
),

(
"Explain 12-1 cross-sectional momentum and why it persists.",
"""Cross-Sectional Momentum (12-1) — Jegadeesh & Titman (1993)

**Mechanism:** winners keep winning over 3–12 months due to underreaction to
fundamentals, herding into confirmed trends, and the disposition effect
(holders sell winners too early, slowing — not stopping — the move). Skipping
the latest month avoids short-term reversal contamination.

**Rules:** rank the universe by return over months t−12..t−2; long the top
decile, avoid (or short via futures) the bottom decile; rebalance monthly;
equal-weight or vol-weight.

**India notes:** momentum has been among the strongest documented factors on
NSE; Nifty200 Momentum 30 index exists as a benchmark. Crash risk is real —
momentum portfolios suffer violent reversals at regime turns (2009-style),
so pair with a drawdown brake or 200-DMA regime filter.

**Caveats:** monthly turnover ≈ 30–40% → costs matter; STT and slippage eat
naive backtests.""",
),

(
"What is the low-volatility anomaly and how is it expressed as a strategy?",
"""Low-Volatility Anomaly — Haugen & Baker; Frazzini & Pedersen 'Betting
Against Beta' (2014)

**Mechanism:** leverage-constrained investors (most of the market) overpay
for high-beta lottery-like stocks to reach return targets, leaving low-beta
quality names underpriced per unit of risk. The edge is structural — it
exists because others *can't* lever.

**Rules:** rank by trailing 1y daily volatility (or beta); hold the lowest
quintile, rebalanced quarterly; optionally lever modestly toward market beta.

**India notes:** NSE publishes Nifty Low Volatility 50 — the factor is live
and investable. Works best as a core long sleeve, not a trading signal;
underperforms in sharp bull runs (it's a bear/chop outperformer).

**Caveats:** sector concentration (FMCG/IT heavy at times) — cap sector
weights; rate-sensitive phases hurt bond-proxy names.""",
),

(
"Describe the 52-week-high momentum effect — how does it differ from plain momentum?",
"""52-Week-High Anchoring — George & Hwang (2004)

**Mechanism:** traders anchor on the 52-week high as a reference price and
hesitate to buy near it ('too expensive'), causing systematic underreaction
exactly where information says they should buy. Nearness to the high — not
past return — carries the signal; it works even controlling for momentum.

**Rules:** rank by price / 52-week high; long names in the top decile
(within ~5% of the high) on fresh breakouts with volume confirmation; hold
1–3 months; stop below the consolidation that preceded the breakout.

**Relation to S2:** TERMINAL//IN's S2 lens is the single-name expression of
this effect; the cross-sectional version ranks the whole universe instead
of waiting for individual triggers.

**Caveats:** fails in bear regimes (everything is far from highs — ranks
become noise); needs a market filter.""",
),

(
"Explain short-term reversal and where it does NOT work.",
"""Short-Term Reversal — Jegadeesh (1990), Lehmann (1990)

**Mechanism:** 1-week to 1-month losers bounce and winners fade because
liquidity providers demand compensation for absorbing order-flow imbalances;
the reversal is the market-maker's premium being paid back.

**Rules:** over a 5–20 session window, fade extreme moves that happened on
NO news: long the worst decile, short the best; hold 5–15 sessions;
equal-weight many names (single-name reversal is coin-flip).

**Where it fails:** moves WITH fresh information (earnings, orders, policy)
continue — PEAD dominates reversal. The filter 'no identifiable catalyst'
is the strategy. Also fails in cascading liquidations (2020-03) where
imbalance persists for weeks.

**India notes:** intraday-to-weekly reversal in liquid Nifty-100 names;
respect circuit limits — a locked lower circuit cannot be bought.""",
),

(
"What is the overnight vs intraday return anomaly?",
"""Overnight/Intraday Return Split — documented by Cooper, Cliff & Gulen
(2008) for US; replicated across markets

**Mechanism:** the bulk of equity index returns accrue OVERNIGHT (close→open)
— news lands off-hours, and opening auctions absorb global information —
while intraday (open→close) returns are roughly flat or negative net of the
overnight gap. Retail buys the open (paying the gap); institutions trade the
close.

**Strategy expressions:** hold positional exposure across closes rather than
day-trading the open; time fresh entries late-session rather than at the
open; in F&O, overnight gap risk = why MIS margin is cheap and CNC carry is
where index return lives.

**India notes:** NSE opens after SGX/GIFT Nifty and US close have moved —
the 9:15 open already embeds overnight world news; chasing it intraday has
negative expectancy on average.

**Caveats:** this is an *average* tilt, not a daily signal; overnight carry
includes crash exposure (you own every gap down).""",
),

(
"Explain the volatility risk premium and a defined-risk way to harvest it.",
"""Volatility Risk Premium (VRP)

**Mechanism:** implied volatility systematically exceeds subsequently
realized volatility because option buyers pay for insurance and crash
protection; sellers earn the premium as compensation for negative skew.
India VIX has historically traded above realized NIFTY vol most of the time.

**Defined-risk expressions (never naked):**
- Short straddle/strangle WITH wings (iron fly / iron condor) on monthly
  NIFTY expiry when VIX > its 60-day median and term structure is flat
- Exit at 50% of max profit or 2× credit loss; never hold through binary
  events (budget, RBI policy, elections)

**Caveats:** the premium is payment for tail risk — sizing is everything
(≤1–2% of equity at risk per expiry). One 2024-06-04-style election day
erases months of theta. This family belongs in TERMINAL//IN only after P2
multi-leg support and SPAN margining exist.""",
),

(
"What is the turn-of-month effect?",
"""Turn-of-Month Effect — Lakonishok & Smidt (1988); persists in many markets

**Mechanism:** systematic month-end flows — salary SIPs (huge in India),
pension contributions, fund window-dressing and rebalancing — concentrate
buying in the last trading day through the first 3 days of the month.

**Rules:** overweight long exposure from T−1 (last session of the month)
through T+3; avoid initiating shorts in that window; combine with trend
filter rather than trading it standalone.

**India notes:** SIP flows (₹20,000+ crore monthly, dated around month
start) give the Indian version unusual structural support; expiry week
(last Thursday) immediately precedes it — disentangle expiry effects.

**Caveats:** a few basis points per day — meaningful for *timing* entries
you already wanted, too small to overcome costs as a standalone system.""",
),

(
"How do FII/DII flows work as a trading signal on NSE?",
"""FII/DII Flow Following (India-specific market structure)

**Mechanism:** foreign institutional investors trade in persistent multi-week
campaigns (allocation decisions move slowly), and their flows are DISCLOSED
daily (NSE/NSDL provisional + final data). Persistent FII buying tends to
continue and lifts large-caps with high foreign ownership headroom; DII
(mutual fund) flows are steadier and contrarian-stabilizing.

**Rules:**
- Signal = 5–10 day cumulative FII cash-market net flow, z-scored
- Sustained positive z → favor large-cap longs (FII favorites: banks, IT);
  sustained negative → reduce beta, prefer DII-supported domestic cyclicals
- Confirm with USDINR (FII selling + rupee weakness = risk-off cluster)

**Caveats:** the data is T+1 disclosed and partially front-run; index
arbitrage flows pollute the cash number. Use as a REGIME tilt (like the
existing regime multiplier), never a standalone entry trigger.""",
),

(
"Explain expiry-day dynamics and 'max pain' on NSE index options.",
"""Expiry-Day Dynamics / Max Pain (NSE market structure)

**Mechanism (the defensible part):** as expiry approaches, option writers
(net short gamma sellers, often institutions) hedge dynamically; when spot
sits near large open-interest strikes, dealer hedging flows can pin price
to the strike ('pinning'). 'Max pain' — the strike minimizing option-buyer
payoff — is a crude summary of where writer hedging pressure points.

**Observable rules:**
- Identify the 2–3 largest OI strikes for the weekly expiry
- Inside the final 2 sessions, fade moves AWAY from the OI cluster when VIX
  is low and no catalyst exists (pin gravity); abandon instantly on news
- Never trade pin logic through events — gamma flips from stabilizing to
  accelerating

**Caveats:** academic support for max pain as *prediction* is weak; treat it
as a hedging-flow map, not a target. Expiry-day moves are violent when the
pin breaks (short-covering cascades). Requires P2 option-chain data in
TERMINAL//IN before any systematic use.""",
),

(
"What is the index inclusion/rebalance effect?",
"""Index Rebalance Effect — Harris & Gurel (1986); NSE semi-annual rebalances

**Mechanism:** index funds and ETFs MUST buy additions and sell deletions at
the rebalance close, regardless of price — a fully predictable, size-known
demand shock. Arbitrageurs front-run it, then provide liquidity into the
event.

**Rules (NSE):**
- NSE announces Nifty changes weeks before effective date (late Feb/Aug)
- Long candidates on announcement, exit INTO the effective-date closing
  auction (when passive buying peaks); the post-inclusion drift is flat to
  negative — don't overstay
- Deletions: avoid catching the passive-selling knife until effective date

**Caveats:** the easy spread has compressed as more players front-run; sizing
must respect liquidity (mid-caps entering Nifty Next 50 move violently).
News-lens (NEWS) can catch announcements; systematic version needs the
announcement calendar ingested.""",
),

(
"Explain trend-filtered timing with the 200-day moving average (Faber model).",
"""Trend Filter / Tactical 200-DMA — Faber (2007), 'A Quantitative Approach
to Tactical Asset Allocation'

**Mechanism:** deep drawdowns cluster below long-term trend; a simple
monthly 200-DMA (or 10-month MA) filter sidesteps the fat left tail not by
prediction but by regime classification. The cost is whipsaw in sideways
markets; the payment is missing 2008/2020-style halves.

**Rules:** monthly close > 10-month MA → risk-on (hold equities); below →
risk-off (cash/short-duration). Evaluate ONLY monthly — daily checks
multiply whipsaws.

**Use inside TERMINAL//IN:** this is the cheapest possible regime classifier
— a sanity backstop for the HMM. When the HMM (heuristic mode) and the
200-DMA disagree on risk-on/off, size down.

**Caveats:** underperforms buy-and-hold in long bulls; taxes/costs on
switches; in India, structural drift is up — the filter's value is drawdown
control, not return enhancement.""",
),

(
"What is the accruals anomaly (earnings quality)?",
"""Accruals Anomaly — Sloan (1996)

**Mechanism:** earnings = cash flow + accruals; accruals (receivables,
inventory build) are estimates that mean-revert and are manipulable.
Investors price headline EPS without decomposing it, so high-accrual
earnings disappoint later. The edge is doing the accounting others skip.

**Rules:** accruals = (ΔWC − depreciation) / total assets; long low-accrual
(cash-rich earnings) names, avoid/short high-accrual; annual rebalance after
results season.

**India notes:** screen on cash conversion (CFO/EBITDA > 0.8 sustained) —
a practical proxy; promoter-driven small-caps with deteriorating receivables
are the classic short-side trap to AVOID rather than short (borrow is
unavailable; SLB illiquid).

**Caveats:** slow factor (annual horizon) — belongs in the quality screen of
a positional book, not the intraday loop.""",
),

(
"How does gap trading work statistically — fade or follow?",
"""Opening Gap: Fade vs Follow (intraday market structure)

**Mechanism:** gaps split into (a) liquidity/noise gaps — overnight order
imbalance with no news, which FILL as the auction's mispricing corrects;
and (b) information gaps — earnings/news repricings, which RUN (the gap is
the first step of PEAD). The strategy is the classification, not the trade.

**Classification rules:**
- Gap < 0.4% with no news + against prior trend → fade toward yesterday's
  close (target = gap fill, stop = day's extreme)
- Gap > 0.8% WITH identifiable catalyst + opening 15-min holds the gap
  direction → follow (treat as ORB with pre-confirmed direction)
- Middle zone → no trade; ambiguity is the majority case

**India notes:** NSE gaps embed overnight US/SGX moves — check whether the
gap merely matches GIFT Nifty (no domestic information) or exceeds it
(domestic news component).

**Caveats:** fade entries fight momentum — require hard stops; never fade
limit-up/down or post-result gaps.""",
),

(
"Explain volatility targeting for position sizing — why does it improve Sharpe?",
"""Volatility Targeting (risk-based sizing)

**Mechanism:** volatility clusters (high vol today → high vol tomorrow) while
returns don't; sizing positions inversely to current vol equalizes risk per
trade across regimes. Because vol spikes coincide with negative returns,
de-sizing into vol mechanically reduces exposure exactly when expectancy is
worst — a free risk-timing effect documented across asset classes
(Moreira & Muir 2017, 'Volatility-Managed Portfolios').

**Rules:** position notional = (target daily risk) / (ATR or σ of the
instrument); recompute at entry; cap leverage; portfolio version targets
total book vol (e.g., 1% daily).

**Use inside TERMINAL//IN:** the regime size-multiplier is a coarse version;
per-position ATR sizing (risk ÷ stop distance) is the exact version —
S1's ATR stop already implies it. Making EVERY strategy size as
risk/stop-distance instead of fixed 5% notional is the upgrade.

**Caveats:** vol targeting trims the right tail too (smaller positions in
recoveries); transaction churn if rebalanced continuously.""",
),

(
"What seasonal effects matter on Indian markets specifically?",
"""India-Specific Seasonality (documented calendar structure)

**Documented effects:**
- **Budget day (Feb 1):** binary volatility event — historically among the
  highest-vol sessions; vol strategies stand down, directional only on the
  post-speech trend, never the rumor
- **Muhurat trading (Diwali):** ceremonial 1-hour session, thin and
  gap-prone with a positive drift bias driven by auspicious buying — a
  sentiment marker, not a tradable edge
- **Monthly expiry week (last Thursday):** rollover flows distort cash —
  futures basis; avoid initiating positional entries on expiry ±1 day
- **Advance-tax outflow dates (Jun/Sep/Dec/Mar 15):** transient liquidity
  drain in money markets, occasionally spills into equity weakness
- **Election cycles:** the single largest Indian vol events (2024-06-04:
  NIFTY −6% intraday); event-mask these dates in the risk gate

**Mechanism:** all are FLOW-driven (taxes, rituals, rollovers, mandates) —
predictable in timing, variable in size.

**Caveats:** seasonality is a filter/mask layer, not an entry engine; the
event calendar in TERMINAL//IN (risk/event_calendar.py) is the right home.""",
),

(
"Explain pairs selection by the distance method versus cointegration — which is more robust?",
"""Pairs Selection: Distance vs Cointegration — Gatev, Goetzmann &
Rouwenhorst (2006) vs Engle-Granger approaches

**Distance method (GGR):** normalize both price series to 1 at formation
start; pick pairs minimizing sum of squared differences over 12 months;
trade when spread > 2σ of formation-period spread. Simple, no parameters
to overfit, and it produced the original documented ~11% annual excess
returns.

**Cointegration method:** test residuals of log-price regression for
stationarity (ADF); trade z-score of the cointegrating residual. More
statistically principled, but the test is fragile out-of-sample — pairs
drift out of cointegration silently.

**Verdict:** distance is more ROBUST (fewer estimated parameters);
cointegration is more SELECTIVE. Production systems run distance selection
with a cointegration confirmation, then a structural-break kill rule:
abandon the pair if spread > 3.5σ or half-life doubles — the relationship,
not the position, has broken. TERMINAL//IN's S6 should adopt the kill rule
regardless of selection method.

**India pairs that historically co-move:** HDFCBANK/ICICIBANK, TCS/INFY,
MARUTI/M&M — same-sector large caps with common flow drivers.""",
),

(
"What does 'quality minus junk' mean as a factor?",
"""Quality Minus Junk (QMJ) — Asness, Frazzini & Pedersen (2019)

**Mechanism:** stocks with high profitability, stable growth, low leverage
and high payout persistently outperform their junk opposites on a
risk-adjusted basis — investors systematically underpay for boring
compounders and overpay for speculative stories (same behavioral root as
the low-vol anomaly).

**Quality score components:** profitability (ROE, ROA, CFO/assets, gross
margin), growth stability (5y trends), safety (low beta, low leverage,
low earnings variance), payout discipline.

**India notes:** quality has been the dominant Indian factor for long
stretches (consumer franchises, private banks); Nifty200 Quality 30 tracks
it. Crowding made it expensive — pair the quality screen with a valuation
guardrail (avoid top-decile P/E within the quality basket).

**Use inside TERMINAL//IN:** as a UNIVERSE filter — restrict positional
(CNC) strategies to the top-half quality names; let intraday lenses trade
the full universe. Quality data needs a fundamentals ingest (yfinance
provides the raw fields).""",
),

]


# ── Macro & news interpretation — the analyst layer ──────────────────────────

MACRO_PAIRS: list[tuple[str, str]] = [

(
"How does an RBI repo rate decision flow through to NSE sectors?",
"""RBI Policy Transmission Map

**Rate HIKE (or hawkish hold):** banks see short-term NIM expansion (assets
reprice faster than deposits) — positive for high-CASA lenders, negative for
wholesale-funded NBFCs. Rate-sensitives fall: autos (financing cost), real
estate (EMI demand), infra (project IRR). INR supportive → IT mildly negative.

**Rate CUT (or dovish pivot):** NBFCs, real estate, autos rally first (most
rate-starved); bond proxies (utilities, FMCG) re-rate as yields fall.

**What matters more than the decision:** the STANCE wording and the inflation
forecast revision — markets price the path, not the step. A cut delivered
with hawkish guidance sells off.

**Discipline:** policy day = event mask in the risk gate; trade the
post-statement trend after 30 minutes, never the headline tick.""",
),

(
"How should a CPI inflation print be interpreted for Indian equities?",
"""CPI Print → Equity Translation (India)

**The chain:** CPI vs RBI's 4% (±2%) band → expected policy path → real
yields → equity multiples. India CPI is food-heavy (~46% weight): monsoon
and vegetable prices drive headline; RBI looks through transient food
spikes but not generalized core inflation.

**Reading a print:** headline hot but core stable and food-driven → RBI
looks through it, shallow reaction — buy rate-sensitive dips. CORE above
consensus → policy tight for longer; banks fine, NBFC and growth multiples
compress. Below-target prints open cut expectations — small/mid risk
appetite expands first.

**Cross-checks:** US CPI the same week (Fed path drives FII flows), crude
trend (imported inflation), USDINR (pass-through).

**Discipline:** the print lands 17:30 IST post-close — the trade is the next
morning's gap classification (information gap → follow, not fade).""",
),

(
"Why do US Fed decisions move NIFTY, and what is the transmission chain?",
"""Fed → NIFTY Transmission

**Chain:** Fed rate path → US real yields and DXY → EM carry math → FII
flows → NIFTY heavyweights and USDINR. Hawkish = higher US risk-free, EM
risk premium less attractive, FII selling, rupee pressure. Dovish pivot =
the reverse, with small/mid breadth expansion.

**Watch in order:** the dots (path) > statement > press-conference tone.
NSE reacts at the next 9:15 open — the gap embeds the full repricing, so
do not chase the open (overnight/intraday anomaly).

**Decoupling caveat:** monthly SIP flows have made NIFTY far less
Fed-sensitive than in 2013's taper tantrum — DII bids absorb FII selling at
the index level, though FII-heavy single names still swing.

**F&O note:** India VIX bids up into FOMC nights; selling that vol before
the event is the classic blow-up — the premium is high for a reason.""",
),

(
"How does crude oil affect Indian markets and which sectors move?",
"""Crude Oil → India Map

**Macro:** India imports ~85% of crude. +$10/bbl ≈ +0.3–0.4% CPI and a
wider current account → rupee pressure → imported-inflation loop. Sustained
above ~$95 is an index-level headwind.

**Winners on crude FALL:** OMC marketing margins (HPCL/BPCL/IOC), paints
(crude-derivative inputs), aviation (ATF ~40% of cost), tyres, FMCG
(packaging). **Losers:** upstream ONGC/OIL realizations; Reliance is mixed
(refining margins matter more than direction).

**Discipline:** the crude→sector trade works on sustained 20-day trends,
not daily wiggles; government pricing policy can sever the OMC link
entirely in election windows.

**Real signal:** Brent and USDINR moving together = double impact on the
import bill — that combination matters, not either alone.""",
),

(
"What does USDINR movement signal for equity positioning?",
"""USDINR as an Equity Signal

**Mechanism:** the rupee aggregates FII flows, the dollar cycle, crude, and
RBI intervention; equities and INR share the FII driver, so sharp INR
weakness usually accompanies or precedes large-cap selling.

**Reading it:** gradual depreciation (1–2%/quarter) is normal carry — IT
exporters gain ~30–40bps margin per 1% (USD revenue, INR costs). SHARP
depreciation (>1% in days) is a risk-off cluster: expect FII equity
selling, bank/NBFC pressure, defensives outperforming. Unusual INR
stability during global stress = RBI is in the market — fade nothing until
intervention exhausts.

**Spread expression:** long IT / short rate-sensitives is the classic
rupee-weakness pair.

**Roadmap:** USDINR futures (NSE CDS) are the direct instrument in P3;
until then the IT-sector tilt is the proxy.""",
),

(
"How do bond yields and the yield curve inform equity allocation in India?",
"""India Yield Curve → Equity Read

**Levels:** the 10y G-sec yield is the discount rate on Indian equity
multiples — sustained rises compress P/E (growth and small-caps first).

**Curve shape:** steepening with growth = reflation, the best bank regime
(borrow short, lend long). Flattening toward inversion = policy too tight —
late cycle, rotate to quality/FMCG/pharma. AAA credit spreads widening over
G-secs = funding stress — the NBFC warning light (IL&FS 2018 pattern).

**Equity-bond yield gap:** NIFTY earnings yield (1/PE) minus the 10y —
deeply negative marks expensive equities (2021 pattern); near zero or
positive marks the cheap zone (March 2020).

**Use inside TERMINAL//IN:** regime INPUTS — candidates for HMM features at
the 500-day retrain, not direct entry triggers.""",
),

(
"Translate a headline like 'Company X wins large government order' into a trading decision framework.",
"""News → Trade Translation Framework

**1 — Materiality:** order value vs market cap and annual revenue. Under 2%
of revenue = noise (fade any spike); over 10% = genuine repricing event.

**2 — Freshness:** was it pre-announced (L1 status known for weeks)?
Anticipated news gets SOLD on confirmation. If the 20-day chart already ran,
the headline is exit liquidity.

**3 — Quality of the gain:** margin profile (government infra orders are
low-margin, long-receivable), execution timeline, funding need (dilution?).

**4 — Expression:** fresh + material + clean balance sheet → PEAD-style
entry on the day-1 confirmation candle, hold weeks, stop at the pre-news
level. Already-run + confirmation → no trade.

**The 99th-percentile habit:** the question is never 'is the news good?' —
it is 'who does not already know this, and what will they do next?'""",
),

(
"What is sector rotation and how do you read it on NSE in real time?",
"""Sector Rotation Reading (NSE)

**Mechanism:** institutional money migrates across sectors as the cycle
advances; relative strength of sector indices vs NIFTY is the footprint.

**Cycle map:** early recovery → banks, autos, real estate. Mid-cycle →
industrials, cap goods. Late-cycle → metals, energy. Slowdown/risk-off →
IT, pharma, FMCG.

**Real-time read:** rank 20-day relative returns of each sector index vs
NIFTY; a sector crossing from bottom-half to top-3 WITH internal breadth
(advancers within the sector) marks rotation in.

**Use:** rotation chooses which sector deserves the positional slots the
risk gate's sector cap allows. **Caveat:** rotation lags at turns — require
relative strength actually turning, not the narrative that it should.""",
),

(
"How should results season be traded systematically?",
"""Results Season Playbook (NSE)

**Before:** flat into binaries by default — mask single-name entries one
session before scheduled results (event calendar). Exception: PEAD
continuation names from last quarter without a run-up.

**On the print:** compare to the whisper (price action into results), not
just consensus — a beat after a 15% pre-results rally can still gap down.
Margin trajectory beats revenue beat; guidance revision fuels the
multi-week drift.

**After:** day-1 direction with volume = the PEAD direction (enter day 1–2
close). Gap-and-fade (strong open, weak close) = distribution — stand aside.

**India specifics:** mid-session prints swing mid-caps 5–10% instantly and
circuit limits can lock exits — size for the gap, not the average day.

**F&O:** post-results IV crush is structural; long options into results must
beat the implied move — usually a losing bet.""",
),

(
"What macro dashboard should an Indian equities analyst check every morning?",
"""The 9:00 AM Macro Dashboard

**Overnight (sets the gap):** US close + US 10y + DXY; GIFT Nifty vs
yesterday's NSE close (the expected open); Asia morning; Brent and offshore
USDINR drift.

**Domestic:** yesterday's FII/DII provisional flows (campaign status);
India VIX vs its 20-day median (sizing regime); today's calendar — RBI
speakers, CPI/IIP/PMI, results list, expiry proximity, global events
tonight.

**Synthesis discipline:** classify the day BEFORE 9:15 — trend day
(information gap, aligned globals), range day (no catalyst, low VIX), or
event day (mask until the event). The classification chooses which strategy
families may fire — exactly what the 08:55 pre-open brief automates.""",
),

(
"How do you assess whether the market is in risk-on or risk-off mode?",
"""Risk-On / Risk-Off Diagnosis

**Risk-ON:** small/mid outperform large (breadth), INR stable-to-strong,
VIX under ~14 and falling, FII cash buying + index futures long buildup,
cyclicals over defensives, advance/decline sustained above 1.5.

**Risk-OFF:** index holds while midcaps bleed (narrowing leadership — the
classic pre-correction tell), INR weak with VIX bid, FII short buildup in
index futures, defensives leading, falling breadth on up days.

**The most reliable Indian tell:** BREADTH DIVERGENCE — index flat/up while
advance-decline deteriorates for 2+ weeks precedes corrections more
reliably than any single indicator.

**Use inside TERMINAL//IN:** maps onto the regime classifier and size
multiplier; A/D and midcap relative strength are computable from the
72-symbol universe and are natural HMM features for the 500-day retrain.""",
),

(
"What separates a 99th-percentile analyst's process from an average one?",
"""The 99th-Percentile Analyst Process

1. **Mechanism over pattern:** never act on a correlation without naming who
   is on the other side and why they are systematically constrained
   (leverage limits, mandates, anchoring) — every edge is someone's
   constraint.
2. **Base rates first:** what is the historical win rate and payoff of THIS
   setup class? (Bayesian WR tracking exists for exactly this.)
3. **Pre-mortem every position:** write the exit condition before entry —
   price, time stop, or thesis-break event (mandatory SL/target on every
   signal encodes this).
4. **Judge decisions, not outcomes:** a stopped-out positive-expectancy
   trade was a good decision — hindsight re-pricing measures decisions,
   not luck.
5. **Size is the strategy:** identical signals with different sizing produce
   opposite long-run results; constant risk-per-trade (ATR sizing) beats
   conviction sizing.
6. **Macro as context, never trigger:** macro sets which families are
   allowed (regime); single-name evidence pulls the trigger.
7. **Written record:** reasoning logged at decision time — memory rewrites
   itself, ink does not (the agent_decisions table).""",
),

]
