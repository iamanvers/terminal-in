"""
Ollama-powered NSE/BSE financial analyst agent.
Uses open-source SLMs (qwen2.5:3b, phi4-mini, mistral) via local Ollama server.
Supports function-calling tool loop: LLM decides which tools to call → backend executes → LLM synthesises.
Falls back to rule-based analysis if Ollama is offline.
"""

import json
import logging
import os
from typing import Any

import requests

from terminal_in.agents.tools.yfinance_tools import (
    get_stock_data, get_fundamentals, get_index_data,
    scan_momentum, scan_breakout, scan_rsi_oversold,
)
from terminal_in.data_ingest.nse_symbols import search as symbol_search, get_all_symbols

log = logging.getLogger(__name__)

OLLAMA_BASE  = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')

_SYSTEM_PROMPT = """\
You are a professional NSE/BSE equity analyst with deep expertise in Indian financial markets.
You help traders and investors analyse stocks, indices, and market conditions.

Available tools let you fetch real-time price data, technical indicators, fundamental metrics,
and run market scans. Always use tools to retrieve live data before drawing conclusions.
Respond in a clear, structured format. Cite specific numbers (prices, RSI, EMA levels) in your analysis.
When giving recommendations, always state the basis (technicals, fundamentals, or both) and relevant risk factors.
Never fabricate prices or indicators — use the tools."""

# ── Tool definitions (OpenAI-compatible schema for Ollama) ─────────────────

_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'get_stock_data',
            'description': 'Fetch OHLCV price data and compute RSI, EMA, MACD, ATR, Bollinger Bands, 52-week range, volume ratio for an NSE stock.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string', 'description': 'NSE ticker e.g. RELIANCE, INFY, HDFCBANK'},
                    'period': {'type': 'string', 'enum': ['1d', '5d', '1mo', '3mo', '6mo', '1y'], 'description': 'Historical period', 'default': '3mo'},
                },
                'required': ['symbol'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_fundamentals',
            'description': 'Fetch PE ratio, PB ratio, market cap, EPS, dividend yield, ROE, debt-to-equity, analyst ratings for an NSE stock.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string', 'description': 'NSE ticker e.g. RELIANCE, INFY'},
                },
                'required': ['symbol'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_index_data',
            'description': 'Fetch latest price and change% for key indices: NIFTY50, BANKNIFTY, INDIA VIX, SENSEX, S&P500, NASDAQ, DOW, NIKKEI, FTSE, USD/INR.',
            'parameters': {'type': 'object', 'properties': {}, 'required': []},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'scan_momentum',
            'description': 'Scan a list of NSE symbols and rank by momentum score (RSI zone + trend + volume). Returns top-N candidates.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'symbols': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of NSE tickers to scan'},
                    'top_n':   {'type': 'integer', 'description': 'Number of top results to return', 'default': 10},
                },
                'required': ['symbols'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'scan_breakout',
            'description': 'Scan for stocks near 52-week high breakout (within 3% of 52W high with above-average volume).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'symbols': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of NSE tickers to scan'},
                    'top_n':   {'type': 'integer', 'description': 'Number of top results to return', 'default': 10},
                },
                'required': ['symbols'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'scan_rsi_oversold',
            'description': 'Scan for RSI oversold mean-reversion candidates (RSI < 35 but price above EMA50 — quality stocks in temporary dip).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'symbols': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of NSE tickers to scan'},
                    'top_n':   {'type': 'integer', 'description': 'Number of top results to return', 'default': 10},
                },
                'required': ['symbols'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_nse_symbols',
            'description': 'Search NSE equity symbols by ticker code or company name. Returns matching symbols with full company name.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query':       {'type': 'string', 'description': 'Ticker symbol or partial company name'},
                    'max_results': {'type': 'integer', 'description': 'Maximum results to return', 'default': 10},
                },
                'required': ['query'],
            },
        },
    },
]

# ── Tool execution dispatcher ───────────────────────────────────────────────

_DEFAULT_SCAN_SYMBOLS = [
    'RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'ICICIBANK', 'SBIN', 'AXISBANK',
    'KOTAKBANK', 'BAJFINANCE', 'HINDUNILVR', 'WIPRO', 'LT', 'MARUTI',
    'ADANIPORTS', 'SUNPHARMA', 'TATAMOTORS', 'TATASTEEL', 'ASIANPAINT',
    'TITAN', 'HCLTECH', 'TECHM', 'ULTRACEMCO', 'NESTLEIND', 'JSWSTEEL',
    'DRREDDY', 'BAJAJFINSV', 'DIVISLAB', 'HINDALCO', 'NTPC', 'POWERGRID',
]


def _execute_tool(name: str, args: dict) -> Any:
    try:
        if name == 'get_stock_data':
            return get_stock_data(args['symbol'], args.get('period', '3mo'))
        if name == 'get_fundamentals':
            return get_fundamentals(args['symbol'])
        if name == 'get_index_data':
            return get_index_data()
        if name == 'scan_momentum':
            symbols = args.get('symbols') or _DEFAULT_SCAN_SYMBOLS
            return scan_momentum(symbols, args.get('top_n', 10))
        if name == 'scan_breakout':
            symbols = args.get('symbols') or _DEFAULT_SCAN_SYMBOLS
            return scan_breakout(symbols, args.get('top_n', 10))
        if name == 'scan_rsi_oversold':
            symbols = args.get('symbols') or _DEFAULT_SCAN_SYMBOLS
            return scan_rsi_oversold(symbols, args.get('top_n', 10))
        if name == 'search_nse_symbols':
            results = symbol_search(args['query'], args.get('max_results', 10))
            return results
        return {'error': f'Unknown tool: {name}'}
    except Exception as e:
        log.warning(f'Tool {name} failed: {e}')
        return {'error': str(e), 'tool': name}


# ── Ollama client ────────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        r = requests.get(f'{OLLAMA_BASE}/api/tags', timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    payload: dict = {
        'model':  OLLAMA_MODEL,
        'messages': messages,
        'stream': False,
        'options': {'temperature': 0.1, 'num_predict': 1024},
    }
    if tools:
        payload['tools'] = tools

    r = requests.post(
        f'{OLLAMA_BASE}/api/chat',
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


# ── Rule-based fallback ──────────────────────────────────────────────────────

def _rule_based_analysis(query: str) -> str:
    """Minimal fallback when Ollama is offline: detect symbol → fetch data → format."""
    words  = query.upper().split()
    all_sym = set(get_all_symbols())
    symbols = [w.strip('.,?!') for w in words if w.strip('.,?!') in all_sym]

    if not symbols:
        indices = get_index_data()
        lines = ['**Market Overview** *(Ollama offline — rule-based fallback)*\n']
        for name, d in indices.items():
            chg = d.get('change_pct', 0)
            sign = '+' if chg >= 0 else ''
            lines.append(f'- **{name}**: {d["price"]:,.2f} ({sign}{chg:.2f}%)')
        return '\n'.join(lines)

    parts = []
    for sym in symbols[:3]:
        data = get_stock_data(sym)
        if 'error' in data:
            parts.append(f'**{sym}**: data unavailable')
            continue
        fund = get_fundamentals(sym)
        lines = [
            f'**{sym}** — ₹{data["price"]:,.2f} ({data["change_1d_pct"]:+.2f}%)',
            f'Trend: {data["trend"]} | RSI-14: {data["rsi_14"]} ({data["rsi_signal"]})',
            f'EMA9/21/50: {data["ema9"]}/{data["ema21"]}/{data["ema50"]}',
            f'MACD: {data["macd"]} | Signal: {data["macd_signal"]} | Hist: {data["macd_histogram"]}',
            f'BB: {data["bb_lower"]}/{data["bb_mid"]}/{data["bb_upper"]} ({data["bb_pct"]:.0%} position)',
            f'52W: {data["52w_low"]} – {data["52w_high"]} | From high: {data["pct_from_52w_high"]:+.1f}%',
            f'Volume ratio: {data["volume_ratio"]}x',
        ]
        if 'error' not in fund:
            pe  = fund.get('pe_ratio') or 'N/A'
            cap = fund.get('market_cap_cr')
            cap_str = f'₹{cap:,.0f} Cr' if cap else 'N/A'
            lines.append(f'PE: {pe} | Mkt Cap: {cap_str} | Sector: {fund.get("sector", "N/A")}')
        parts.append('\n'.join(lines))

    header = f'*(Ollama offline — rule-based analysis)*\n\n'
    return header + '\n\n---\n\n'.join(parts)


# ── Agentic loop ─────────────────────────────────────────────────────────────

class FinancialAgent:
    def __init__(self):
        self._online = False

    def query(self, user_text: str, history: list[dict] | None = None) -> dict:
        """
        Run the agent on a natural-language query.
        Returns {answer: str, tool_calls: list[dict], model: str, online: bool}
        """
        self._online = _ollama_available()

        if not self._online:
            log.warning('Ollama offline — using rule-based fallback')
            return {
                'answer':     _rule_based_analysis(user_text),
                'tool_calls': [],
                'model':      'rule-based',
                'online':     False,
            }

        messages: list[dict] = [{'role': 'system', 'content': _SYSTEM_PROMPT}]
        if history:
            messages.extend(history[-10:])  # keep last 10 turns for context
        messages.append({'role': 'user', 'content': user_text})

        executed_calls: list[dict] = []
        max_rounds = 6

        for round_num in range(max_rounds):
            try:
                resp = _ollama_chat(messages, tools=_TOOLS if round_num < max_rounds - 1 else None)
            except Exception as e:
                log.error(f'Ollama request failed (round {round_num}): {e}')
                return {
                    'answer':     f'LLM request failed: {e}\n\n' + _rule_based_analysis(user_text),
                    'tool_calls': executed_calls,
                    'model':      OLLAMA_MODEL,
                    'online':     True,
                }

            msg = resp.get('message', {})
            tool_calls = msg.get('tool_calls') or []

            if not tool_calls:
                # No more tool calls → final answer
                return {
                    'answer':     msg.get('content', '').strip(),
                    'tool_calls': executed_calls,
                    'model':      OLLAMA_MODEL,
                    'online':     True,
                }

            # Execute each tool call and append results
            messages.append({'role': 'assistant', 'content': msg.get('content', ''), 'tool_calls': tool_calls})

            for tc in tool_calls:
                fn   = tc.get('function', {})
                name = fn.get('name', '')
                try:
                    raw_args = fn.get('arguments', {})
                    args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    args = {}

                log.info(f'Executing tool: {name}({args})')
                result = _execute_tool(name, args)

                executed_calls.append({'tool': name, 'args': args, 'result': result})
                messages.append({
                    'role':    'tool',
                    'content': json.dumps(result, default=str),
                })

        # Exceeded max rounds — return last assistant message
        last_content = messages[-1].get('content', 'Analysis complete — see tool results above.')
        return {
            'answer':     last_content,
            'tool_calls': executed_calls,
            'model':      OLLAMA_MODEL,
            'online':     True,
        }

    @property
    def is_online(self) -> bool:
        return _ollama_available()

    @property
    def model(self) -> str:
        return OLLAMA_MODEL


# ── Singleton ────────────────────────────────────────────────────────────────

_agent: FinancialAgent | None = None


def get_agent() -> FinancialAgent:
    global _agent
    if _agent is None:
        _agent = FinancialAgent()
    return _agent
