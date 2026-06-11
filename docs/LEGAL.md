# TERMINAL//IN — Legal Notices

**Effective:** 12 June 2026 · applies to all distributions of the TERMINAL//IN software ("the Software").

---

## 1. Ownership & intellectual property

The Software — its source code, architecture, design system, brand mark (the
TERMINAL//IN tile-and-candles logo), documentation, and any models fine-tuned
from the operator's own trading record — is the property of its owner
(**Anmol Verma**). **All rights reserved.** No license to copy, modify,
distribute, sublicense, or commercially exploit the Software is granted by
possession of a copy, except as the owner grants in writing.

Models fine-tuned on the operator's own trades and decisions
("personal-layer models") contain information derived from private trading
activity and must never be redistributed. Distributed builds may include only
base models trained on public corpora (see §4).

## 2. Not investment advice — trading disclaimer

The Software is an **analysis and automation tool**, not an investment
adviser, broker, or portfolio manager.

- Nothing the Software produces — signals, planner verdicts, reports,
  AI-analyst chat output, or anything else — constitutes investment advice,
  research, or a recommendation under SEBI (Investment Advisers) Regulations
  or any other law.
- Trading in securities and derivatives involves substantial risk of loss.
  Past performance, including backtested or paper-traded performance, does
  not indicate future results. Paper-mode fills are simulations and
  systematically optimistic versus live execution.
- The operator bears sole responsibility for every order placed in live
  mode, for compliance with their broker's terms (including Zerodha Kite
  Connect's API terms), and for compliance with applicable SEBI/exchange
  rules on automated and algorithmic order placement by retail clients.
- LLM components can produce incorrect, outdated, or fabricated statements.
  The Software constrains them (the planner cannot bypass the risk gate),
  but their text output must not be relied on as fact.

## 3. Privacy

TERMINAL//IN is local-first by design. There is **no telemetry, no
analytics, no account system, and no vendor cloud**.

| Data | Where it lives | Where it goes |
|---|---|---|
| Trades, positions, P&L, decisions | Local SQLite (`data/` or `%LOCALAPPDATA%\TerminalIN`) | Nowhere — never leaves the machine |
| Broker API keys, SMTP credentials | Local `.env` / local settings DB | Sent only to Zerodha / your SMTP server, respectively, over TLS |
| Market data requests | — | Yahoo Finance, RSS feeds of news outlets, NewsAPI (if keyed), Zerodha (live mode) — these third parties see standard request metadata (your IP) |
| Daily report PDFs | Local `data/reports/` | Emailed only if SMTP is configured, to the recipient the operator sets |
| LLM prompts (planner, analyst chat) | Processed by the **local** Ollama/llama.cpp runtime | Nowhere — inference is on-device |
| Fine-tuning data (own trades, judged decisions) | Local training runs | Never leaves the machine; personal-layer adapters are non-distributable (§1) |

Uninstalling = deleting the install directory and the data directory.
Nothing else exists.

## 4. Third-party components

The Software stands on open-source components, each under its own license,
which this Software does not alter: Python (PSF), Flask/Werkzeug (BSD),
PyTorch (BSD-3), Hugging Face transformers/peft/trl/datasets (Apache-2.0),
FinBERT — ProsusAI (CC-BY-4.0 model card terms), TinyLlama (Apache-2.0),
Qwen 2.5 (Apache-2.0), llama.cpp + GGUF tooling (MIT), Ollama (MIT),
Next.js/React (MIT), reportlab (BSD), yfinance (Apache-2.0).

Market data obtained via yfinance originates from Yahoo Finance and is
subject to Yahoo's terms of service; it is used here for personal,
non-commercial analysis. News headlines are fetched from publishers' public
RSS feeds with links back to the source; headlines and links remain the
publishers' property. NSE/BSE index names and trademarks belong to their
respective owners; the Software is not affiliated with, endorsed by, or
sponsored by NSE, BSE, SEBI, Zerodha, or any data provider.

## 5. No warranty, limitation of liability

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
NON-INFRINGEMENT. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM,
DAMAGES, OR OTHER LIABILITY — INCLUDING TRADING LOSSES, LOST PROFITS, OR
DATA LOSS — ARISING FROM THE SOFTWARE OR ITS USE. Software defects, data
errors, third-party API failures, and model misjudgments can and will
occur; the kill switch, risk gate, and paper mode exist for this reason,
and the operator is responsible for using them.

## 6. Acceptable use

The Software must not be used to violate exchange rules, broker API terms,
or market-manipulation laws (including spoofing, layering, or wash trading);
to trade on accounts the operator does not own or control; or to provide
unregistered advisory services to third parties.

---

*This document is a practical notice, not a substitute for legal advice.
For commercial distribution beyond personal use, consult a lawyer regarding
SEBI algo-trading circulars, data-provider licensing, and model licenses.*
