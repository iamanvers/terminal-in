"""
Model evaluation set (PRD P2) — the promotion gate for fine-tuned models.

Objectively graded categories:
  technical  — market-mechanics MCQs (single letter answer)
  system     — TERMINAL//IN strategy/playbook MCQs (single letter)
  sentiment  — headline classification (POSITIVE/NEGATIVE/NEUTRAL)
  verdict    — planner-format checks: must emit parseable JSON with a
               valid action for a candidate scenario

Usage:
  .venv/Scripts/python.exe -m terminal_in.agents.training.evalset qwen2.5:3b
  .venv/Scripts/python.exe -m terminal_in.agents.training.evalset financial-analyst-v2

Results land in data/training/eval/<model>_<ts>.json. Promotion rule
(PRD): a candidate model must beat the incumbent's TOTAL accuracy and not
regress >5 points in any category.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
OUT_DIR = Path('./data/training/eval')

MCQ_SYS = ('Answer with ONLY the single letter of the correct option. '
           'No explanation.')
SENT_SYS = ('Classify the headline sentiment for the named stock/market. '
            'Answer with ONLY one word: POSITIVE, NEGATIVE, or NEUTRAL.')
VERDICT_SYS = (
    'You are a trade-plan judge. Reply with ONLY a JSON object: '
    '{"action": "approve"|"reject", "size_factor": number 0.25-1.5, '
    '"reason": "short text"}. No other text.')

# (question, correct_letter)
TECHNICAL: list[tuple[str, str]] = [
    ("RSI at 24 indicates: A) overbought B) oversold C) neutral D) trending", "B"),
    ("RSI at 78 indicates: A) overbought B) oversold C) no signal D) low volume", "A"),
    ("A stop-loss on a LONG position is placed: A) above entry B) below entry C) at entry D) anywhere", "B"),
    ("A stop-loss on a SHORT position is placed: A) below entry B) at target C) above entry D) at the low", "C"),
    ("Risk-reward of entry 100, stop 95, target 115 is: A) 1:1 B) 1:2 C) 1:3 D) 3:1", "C"),
    ("NSE cash market hours (IST): A) 9:00-15:00 B) 9:15-15:30 C) 9:30-16:00 D) 10:00-15:30", "B"),
    ("MIS product positions are: A) carried overnight B) squared off same day C) weekly D) delivered", "B"),
    ("CNC product means: A) intraday only B) delivery/carry overnight C) options only D) margin trading", "B"),
    ("India VIX rising sharply usually means: A) complacency B) fear/expected volatility C) low volume D) bullishness", "B"),
    ("A golden cross is: A) 50-DMA crossing above 200-DMA B) RSI crossing 50 C) price crossing VWAP D) MACD at zero", "A"),
    ("Higher ATR means: A) lower volatility B) higher volatility C) higher volume D) stronger trend", "B"),
    ("If price gaps up 2% on no news with weak volume, the statistical tendency is to: A) keep rising B) fill the gap C) circuit up D) nothing", "B"),
]

SYSTEM_Q: list[tuple[str, str]] = [
    ("In a momentum strategy, you buy: A) recent losers B) recent winners C) lowest PE D) highest dividend", "B"),
    ("Mean-reversion strategies profit when price: A) trends B) returns toward average C) gaps D) stays flat", "B"),
    ("Post-earnings announcement drift means price: A) reverses the surprise B) continues in surprise direction for weeks C) goes flat D) doubles", "B"),
    ("The low-volatility anomaly says low-vol stocks: A) underperform B) outperform risk-adjusted C) never fall D) track bonds", "B"),
    ("Pairs trading enters when the spread is: A) at mean B) beyond ~2 sigma C) at zero D) trending", "B"),
    ("A 52-week-high breakout strategy buys: A) near 52w lows B) near/above 52w highs with volume C) mid-range D) after -20%", "B"),
    ("Position sizing by ATR means risking: A) fixed shares B) fixed rupees per unit of volatility C) all capital D) 50%", "B"),
    ("A persistence/debounce filter on signals exists to: A) speed entries B) avoid acting on one-scan noise C) raise leverage D) skip stops", "B"),
    ("If 3 consecutive losses come from one strategy lens, a sound control system should: A) double size B) suppress that lens temporarily C) ignore it D) disable all trading", "B"),
    ("VIX spike-fade strategies sell volatility when VIX is: A) at lows B) extremely elevated vs history C) unchanged D) negative", "B"),
    ("Walk-forward backtesting exists to avoid: A) slippage B) overfitting to one period C) taxes D) data gaps", "B"),
    ("Sector exposure caps in a risk gate prevent: A) profits B) concentration risk C) diversification D) hedging", "B"),
]

SENTIMENT: list[tuple[str, str]] = [
    ("TCS reports record quarterly profit, beats estimates by 12%", "POSITIVE"),
    ("HDFC Bank announces massive NPA write-off as defaults surge", "NEGATIVE"),
    ("Reliance Industries AGM scheduled for next month", "NEUTRAL"),
    ("SEBI bars promoter from markets over fund diversion at Zee", "NEGATIVE"),
    ("Maruti Suzuki sales jump 18% on festive demand", "POSITIVE"),
    ("Infosys cuts FY revenue guidance citing client spending slowdown", "NEGATIVE"),
    ("NIFTY ends flat in rangebound session ahead of Fed decision", "NEUTRAL"),
    ("Adani Ports wins 30-year concession for major container terminal", "POSITIVE"),
    ("RBI imposes business restrictions on bank over IT governance lapses", "NEGATIVE"),
    ("Sun Pharma receives USFDA approval for key generic launch", "POSITIVE"),
    ("Tata Steel announces date for quarterly results", "NEUTRAL"),
    ("Vodafone Idea shares slide as AGR dues clarity remains elusive", "NEGATIVE"),
]

# (scenario, expected_action or None when either is defensible)
VERDICTS: list[tuple[str, str | None]] = [
    ("Candidate: RELIANCE BUY, EV 2.1, confidence 0.71, persistence 4 scans, regime trend_up, "
     "VIX 12, no open position in it, 2 lenses agree.", "approve"),
    ("Candidate: INFY BUY, EV 0.4, confidence 0.31, persistence 1 scan, regime sideways, VIX 24.", "reject"),
    ("Candidate: HDFCBANK SELL, EV 1.6, confidence 0.66, persistence 3, but the book already holds "
     "a correlated ICICIBANK short and daily loss is at 80% of the cap.", "reject"),
    ("Candidate: TATASTEEL BUY, EV 1.9, confidence 0.69, persistence 3, regime trend_up, VIX 13, "
     "hindsight shows this lens 7-for-9 recently.", "approve"),
    ("Candidate: WIPRO BUY, EV 1.3, confidence 0.52, persistence 2, regime volatile, VIX 28, "
     "data quality flagged LOW (stale bars).", "reject"),
    ("Candidate: SBIN BUY, EV 1.5, confidence 0.6, persistence 2, regime sideways, VIX 15.", None),
]


def _ask(model: str, system: str, user: str, max_tokens: int = 60) -> str:
    r = requests.post(f'{OLLAMA}/api/chat', json={
        'model': model, 'stream': False, 'keep_alive': '30m',
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user}],
        'options': {'temperature': 0.0, 'num_predict': max_tokens},
    }, timeout=180)
    r.raise_for_status()
    return (r.json().get('message') or {}).get('content', '').strip()


def run_eval(model: str) -> dict:
    scores: dict[str, dict] = {}

    def grade(cat: str, items, check):
        ok, details = 0, []
        for q, expected in items:
            try:
                out = check(q, expected)
            except Exception as e:
                out = (False, f'ERR {e}')
            ok += bool(out[0])
            details.append({'q': q[:70], 'expected': expected, 'pass': bool(out[0]), 'got': str(out[1])[:90]})
        scores[cat] = {'correct': ok, 'total': len(items),
                       'pct': round(100 * ok / len(items), 1), 'details': details}
        print(f'  {cat:10s} {ok}/{len(items)}')

    print(f'Evaluating {model} …')

    def mcq(q, expected):
        ans = _ask(model, MCQ_SYS, q, 8)
        m = re.search(r'\b([A-D])\b', ans.upper())
        return (m and m.group(1) == expected, ans)

    grade('technical', TECHNICAL, mcq)
    grade('system', SYSTEM_Q, mcq)

    def sent(q, expected):
        ans = _ask(model, SENT_SYS, q, 8).upper()
        m = re.search(r'(POSITIVE|NEGATIVE|NEUTRAL)', ans)
        return (m and m.group(1) == expected, ans)

    grade('sentiment', SENTIMENT, sent)

    def verdict(q, expected):
        ans = _ask(model, VERDICT_SYS, q, 120)
        m = re.search(r'\{.*\}', ans, re.S)
        if not m:
            return (False, 'no JSON')
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return (False, 'bad JSON')
        action = str(d.get('action', '')).lower()
        if action not in ('approve', 'reject'):
            return (False, f'bad action {action}')
        try:
            sf = float(d.get('size_factor', 1.0))
        except (TypeError, ValueError):
            return (False, 'bad size_factor')
        if not (0.0 <= sf <= 2.0):
            return (False, f'size_factor {sf}')
        if expected is not None and action != expected:
            return (False, f'action {action}, expected {expected}')
        return (True, action)

    grade('verdict', VERDICTS, verdict)

    total_ok = sum(s['correct'] for s in scores.values())
    total_n = sum(s['total'] for s in scores.values())
    result = {
        'model': model, 'ts': int(time.time() * 1000),
        'total': {'correct': total_ok, 'total': total_n,
                  'pct': round(100 * total_ok / total_n, 1)},
        'categories': {k: {kk: vv for kk, vv in v.items() if kk != 'details'}
                       for k, v in scores.items()},
        'details': {k: v['details'] for k, v in scores.items()},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{model.replace(':', '_').replace('/', '_')}_{int(time.time())}.json"
    out.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(f'TOTAL {total_ok}/{total_n} ({result["total"]["pct"]}%) -> {out}')
    return result


if __name__ == '__main__':
    run_eval(sys.argv[1] if len(sys.argv) > 1 else 'qwen2.5:3b')
