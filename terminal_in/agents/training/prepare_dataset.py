"""
Prepare fine-tuning dataset for the financial SLM.

Sources:
  1. FinancialPhraseBank — 4845 sentences with sentiment labels (positive/negative/neutral)
  2. FiQA — financial QA pairs from HuggingFace (ibm/fiqa)
  3. Local SQLite trades — signal → outcome pairs from your own paper trades

Output: HuggingFace Dataset saved to ./data/training/financial_sft

Run:
    .venv/Scripts/python -m terminal_in.agents.training.prepare_dataset
"""

import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

OUTPUT_DIR = Path('./data/training/financial_sft')
DB_PATH    = Path('./data/trading.db')


# ── Alpaca instruction format ─────────────────────────────────────────────

def _alpaca(instruction: str, input_text: str, response: str) -> dict:
    text = (
        f'### Instruction:\n{instruction}\n\n'
        f'### Input:\n{input_text}\n\n'
        f'### Response:\n{response}'
    ) if input_text else (
        f'### Instruction:\n{instruction}\n\n'
        f'### Response:\n{response}'
    )
    return {'instruction': instruction, 'input': input_text, 'output': response, 'text': text}


# ── Source 1: FinancialPhraseBank ─────────────────────────────────────────

def _load_financial_phrasebank() -> list[dict]:
    """Download FinancialPhraseBank from HuggingFace and convert to sentiment classification pairs."""
    try:
        from datasets import load_dataset
    except ImportError:
        log.warning('datasets not installed — skipping FinancialPhraseBank. pip install datasets')
        return []

    try:
        ds = load_dataset('financial_phrasebank', 'sentences_allagree', trust_remote_code=True)
        split = ds['train'] if 'train' in ds else list(ds.values())[0]
    except Exception as e:
        log.warning(f'FinancialPhraseBank load failed: {e}')
        return []

    label_map = {0: 'negative', 1: 'neutral', 2: 'positive'}
    samples = []
    for row in split:
        sentence = row.get('sentence', '')
        label    = label_map.get(row.get('label', 1), 'neutral')
        response = (
            f'Sentiment: {label.upper()}\n\n'
            f'Analysis: This financial statement has a {label} tone. '
        )
        if label == 'positive':
            response += 'It signals favorable business conditions or improving financial performance.'
        elif label == 'negative':
            response += 'It signals deteriorating conditions, headwinds, or financial stress.'
        else:
            response += 'It presents factual information without a clear directional bias.'

        samples.append(_alpaca(
            instruction='Classify the sentiment of the following financial news sentence and explain your reasoning.',
            input_text=sentence,
            response=response,
        ))
    log.info(f'FinancialPhraseBank: {len(samples)} samples')
    return samples


# ── Source 2: FiQA ────────────────────────────────────────────────────────

def _load_fiqa() -> list[dict]:
    """Download FiQA QA dataset for financial question answering."""
    try:
        from datasets import load_dataset
    except ImportError:
        log.warning('datasets not installed — skipping FiQA')
        return []

    try:
        ds = load_dataset('ibm/fiqa', 'qa', trust_remote_code=True)
    except Exception as e:
        try:
            ds = load_dataset('fiqa', trust_remote_code=True)
        except Exception as e2:
            log.warning(f'FiQA load failed: {e}, {e2}')
            return []

    samples = []
    for split_name in ['train', 'validation', 'test']:
        if split_name not in ds:
            continue
        for row in ds[split_name]:
            question = row.get('question', '') or row.get('query', '')
            answer   = row.get('answer', '') or row.get('answer_text', '')
            if not question or not answer:
                continue
            samples.append(_alpaca(
                instruction='Answer the following financial question based on your knowledge of markets, accounting, and investing.',
                input_text=question,
                response=str(answer),
            ))

    log.info(f'FiQA: {len(samples)} samples')
    return samples


# ── Source 3: NSE-specific instruction pairs ──────────────────────────────

_NSE_PAIRS = [
    (
        'What does RSI-14 above 70 mean for a stock?',
        'RSI above 70 indicates the stock is in overbought territory. The 14-period Relative Strength Index measures momentum on a 0–100 scale. RSI > 70 suggests the recent upward price movement has been unusually strong and the stock may be due for a consolidation or pullback. However, in strong trending markets, RSI can remain overbought for extended periods. A trader would look for RSI divergence (price making new highs while RSI makes lower highs) as a stronger reversal signal.',
    ),
    (
        'Explain the significance of price crossing above EMA21 with high volume.',
        'When price crosses above the 21-period EMA with above-average volume, it is considered a bullish signal. The EMA21 is a medium-term trend indicator. A cross above it suggests the short-term momentum has shifted upward. The volume confirmation is critical — without it, the move could be a false breakout. High volume (typically 1.5x or more of the 20-day average) indicates institutional participation and conviction behind the move, increasing the probability that the trend change is sustained.',
    ),
    (
        'What is the opening range breakout strategy for NIFTY 50?',
        'The Opening Range Breakout (ORB) strategy for NIFTY 50 identifies the high and low formed in the first 15–30 minutes after market open (9:15–9:45 AM IST). A buy signal is generated when price breaks above the opening range high, and a sell/short signal when it breaks below the opening range low. Stop-loss is placed at the opposite end of the range. The target is typically 2x the range width (giving a 2:1 risk-reward). The strategy works best on trend days with high opening range volatility, so VIX and gap analysis are often used as filters.',
    ),
    (
        'How do you calculate Bollinger Band position percentage (BB%)?',
        'Bollinger Band position (BB%) = (Price − Lower Band) / (Upper Band − Lower Band). This normalises price position within the bands on a 0–1 scale. BB% of 0 means price is exactly at the lower band, 1 means at the upper band, and 0.5 means at the mid-band (20-day SMA). Values above 1 or below 0 indicate price is outside the bands, which happens roughly 5% of the time. Traders use BB% above 0.8 as overbought and below 0.2 as oversold in mean-reversion strategies.',
    ),
    (
        'What is the MACD histogram and what does a histogram divergence indicate?',
        'The MACD histogram = MACD line − Signal line. When the histogram is positive and growing, upward momentum is strengthening. When positive but shrinking, momentum is decelerating (potential topping). MACD histogram divergence occurs when price makes a new high or low but the histogram does not confirm it. For example, if price makes a higher high but the MACD histogram makes a lower high, it signals weakening momentum despite the price advance — often preceding a reversal. This is considered one of the more reliable technical signals.',
    ),
    (
        'How do you assess sector concentration risk in an equity portfolio?',
        'Sector concentration risk is assessed by calculating each sector\'s weight as a percentage of total portfolio value. A common rule: no single sector should exceed 25–40% of the portfolio. For an Indian equity portfolio, key sectors to watch are: Banking & Finance (often over-represented in NIFTY 50), IT, Energy (Reliance dominant), and Pharma. Concentration risk can be measured by the Herfindahl-Hirschman Index (HHI) of sector weights. To reduce it, diversify across 6+ sectors and cap any single sector position.',
    ),
    (
        'What does ATR (Average True Range) measure and how is it used for stop-loss placement?',
        'ATR measures market volatility as the average of true ranges over a lookback period (typically 14 days). True Range = max(High−Low, |High−Previous Close|, |Low−Previous Close|). ATR is volatility-adjusted and useful for stop-loss placement: a common approach is to set stop-loss at Entry Price − (1.5 × ATR) for longs. This ensures the stop is beyond normal intraday noise. For example, if RELIANCE has ATR14 of ₹40 and you buy at ₹2800, stop-loss at ₹2800 − ₹60 = ₹2740. This avoids getting stopped out by normal price fluctuations.',
    ),
    (
        'What is the difference between trailing PE and forward PE, and which is more useful?',
        'Trailing PE = Current Price / Earnings Per Share (last 12 months). Forward PE = Current Price / Expected EPS (next 12 months analyst estimates). Trailing PE is backward-looking and based on actual reported earnings — it is reliable but may not reflect future growth. Forward PE incorporates analyst growth expectations and is more relevant for valuing growth stocks, but is only as good as the earnings forecasts. For Indian markets: trailing PE above 30 is expensive for most sectors; below 15 is cheap. IT sector typically trades at higher PE (25–40) than cyclicals like metals or PSU banks (8–15).',
    ),
    (
        'Explain how HMM-based regime classification works for Indian equities.',
        'A Hidden Markov Model (HMM) classifies the market into discrete latent states (regimes) based on observable features like daily returns, volatility, and volume. For Indian equities, a 6-state HMM can identify: strong_bull (trending hard up, low volatility), bull (moderate uptrend), sideways (range-bound), bear (downtrend), strong_bear (accelerating decline), and high_vol (spike in volatility regardless of direction). The model is trained on NSE daily OHLCV data and learns transition probabilities between states. Once trained, real-time observations are decoded using the Viterbi algorithm. Regime classification helps size positions: reduce exposure in bear/high_vol regimes, increase in bull regimes.',
    ),
    (
        'What is Zerodha Kite Connect and how is it used for algorithmic trading?',
        'Kite Connect is Zerodha\'s REST + WebSocket API for programmatic trading. It provides: (1) WebSocket streaming for real-time tick data (bid/ask, LTP, OHLC, volume), (2) REST API for order placement (market, limit, SL, SL-M orders), position tracking, portfolio data, and historical OHLCV candles. Key endpoints: POST /orders/{variety} to place orders, GET /portfolio/positions for positions, GET /instruments for the master contract list, GET /historical_data for candles. Authentication requires a daily access token obtained via the OAuth2 flow. The API costs ₹2000/month. For automated strategies, orders are placed with variety=regular, exchange=NSE, product=CNC (delivery) or MIS (intraday).',
    ),
]


def _load_nse_pairs() -> list[dict]:
    samples = []
    for question, answer in _NSE_PAIRS:
        samples.append(_alpaca(
            instruction=question,
            input_text='',
            response=answer,
        ))
    log.info(f'NSE instruction pairs: {len(samples)} samples')
    return samples


# ── Source 4: Local trade outcomes ────────────────────────────────────────

def _load_local_trades() -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT strategy_id, instrument_id, direction, confidence, pnl, exit_reason "
            "FROM trades WHERE exit_reason IS NOT NULL AND pnl IS NOT NULL LIMIT 500"
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f'Could not load trades from DB: {e}')
        return []

    samples = []
    for strategy, symbol, direction, confidence, pnl, exit_reason in rows:
        outcome = 'profitable' if (pnl or 0) > 0 else 'loss-making'
        response = (
            f'Trade outcome: {outcome} (PnL: ₹{pnl:.2f})\n'
            f'Strategy {strategy} entered {direction} on {symbol} with {confidence:.0%} confidence. '
            f'Exit reason: {exit_reason}. '
        )
        if (pnl or 0) > 0:
            response += 'The trade was successful — signal confidence and exit discipline were sound.'
        else:
            response += 'The trade was unsuccessful — review signal quality and risk management for this setup.'

        samples.append(_alpaca(
            instruction=f'Analyse this paper trade result and identify key lessons.',
            input_text=f'Strategy: {strategy} | Symbol: {symbol} | Direction: {direction} | Confidence: {confidence:.0%} | Exit: {exit_reason}',
            response=response,
        ))

    log.info(f'Local trades: {len(samples)} samples')
    return samples


# ── Main ──────────────────────────────────────────────────────────────────

def prepare(output_dir: Path = OUTPUT_DIR) -> None:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info('Loading datasets...')
    all_samples = []
    all_samples.extend(_load_financial_phrasebank())
    all_samples.extend(_load_fiqa())
    all_samples.extend(_load_nse_pairs())
    all_samples.extend(_load_local_trades())

    log.info(f'Total samples: {len(all_samples)}')

    # Save as JSONL
    jsonl_path = output_dir / 'dataset.jsonl'
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    log.info(f'Saved {len(all_samples)} samples → {jsonl_path}')

    # Try to also save as HuggingFace Dataset
    try:
        from datasets import Dataset
        ds = Dataset.from_list(all_samples)
        ds.save_to_disk(str(output_dir))
        log.info(f'HuggingFace Dataset saved → {output_dir}')
    except ImportError:
        log.warning('datasets not installed — only JSONL saved. pip install datasets')

    print(f'\nDataset ready: {len(all_samples)} samples in {output_dir}')
    print('Next step: python -m terminal_in.agents.training.train_lora')


if __name__ == '__main__':
    prepare()
