import os
from dataclasses import dataclass, field
from typing import List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    mode: str                     # 'paper' or 'live'
    initial_capital: float
    max_dd: float                 # 0.20 = 20%
    daily_loss_cap: float         # 0.04 = 4%

    kite_api_key: str
    kite_api_secret: str
    kite_access_token: str

    newsapi_key: str

    jwt_secret: str
    log_level: str
    timezone: str

    tracked_symbols: List[str] = field(default_factory=lambda: [
        'NIFTY 50', 'NIFTY BANK', 'NIFTY FIN SERVICE', 'INDIA VIX', 'NIFTYBEES',
        # Original equities
        'RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'ICICIBANK',
        'KOTAKBANK', 'HINDUNILVR', 'SBIN', 'BAJFINANCE', 'AXISBANK', 'WIPRO',
        # Additional Nifty 50 large caps
        'LT', 'MARUTI', 'ASIANPAINT', 'TATAMOTORS', 'SUNPHARMA', 'TATASTEEL',
        'POWERGRID', 'NTPC', 'ONGC', 'TITAN', 'HCLTECH', 'TECHM',
        'ADANIPORTS', 'ULTRACEMCO', 'NESTLEIND', 'JSWSTEEL',
        'DRREDDY', 'BAJAJFINSV', 'DIVISLAB', 'HINDALCO',
        # Nifty 100 expansion
        'BHARTIARTL', 'ITC', 'M&M', 'BAJAJ-AUTO', 'EICHERMOT', 'HEROMOTOCO',
        'GRASIM', 'CIPLA', 'APOLLOHOSP', 'COALINDIA', 'BPCL', 'INDUSINDBK',
        'TATACONSUM', 'BRITANNIA', 'HDFCLIFE', 'SBILIFE', 'ADANIENT', 'LTTS',
        'TRENT', 'BEL', 'DMART', 'PIDILITIND', 'HAVELLS', 'AMBUJACEM',
        'DABUR', 'GODREJCP', 'SIEMENS', 'DLF', 'VEDL', 'TVSMOTOR',
        'BANKBARODA', 'IOC', 'GAIL', 'JINDALSTEL', 'SHRIRAMFIN', 'CHOLAFIN',
    ])

    ollama_host:  str = 'http://localhost:11434'
    ollama_model: str = 'qwen2.5:3b'

    # LLM TradePlanner judge between orchestrator and risk gate.
    # When Ollama is down the planner degrades to a stricter deterministic
    # bar (flagged, never silent) — so this is safe to leave on.
    planner_enabled: bool = True

    use_kite_live: bool = False

    @property
    def is_live(self) -> bool:
        return self.mode == 'live'

    @property
    def sqlite_path(self) -> Path:
        return Path(os.environ.get('SQLITE_PATH', './data/trading.db'))

    @property
    def db_path(self) -> Path:
        return self.sqlite_path

    @property
    def duckdb_path(self) -> str:
        return os.environ.get('DUCKDB_PATH', './data/terminal_metadata.duckdb')

    @property
    def artifacts_dir(self) -> Path:
        return Path(os.environ.get('ARTIFACTS_DIR', './data/artifacts'))

    @property
    def data_dir(self) -> Path:
        return Path('./data')


def load_config() -> Config:
    mode = os.environ.get('MODE', 'paper').lower()
    access_token = os.environ.get('KITE_ACCESS_TOKEN', '').strip()

    return Config(
        mode=mode,
        initial_capital=float(os.environ.get('INITIAL_CAPITAL', '1000000')),
        max_dd=float(os.environ.get('MAX_DD_PCT', '0.20')),
        daily_loss_cap=float(os.environ.get('DAILY_LOSS_CAP_PCT', '0.04')),
        kite_api_key=os.environ.get('KITE_API_KEY', ''),
        kite_api_secret=os.environ.get('KITE_API_SECRET', ''),
        kite_access_token=access_token,
        newsapi_key=os.environ.get('NEWSAPI_KEY', ''),
        jwt_secret=os.environ.get('JWT_SECRET', 'dev-secret-change-me'),
        log_level=os.environ.get('LOG_LEVEL', 'INFO'),
        timezone=os.environ.get('TIMEZONE', 'Asia/Kolkata'),
        use_kite_live=bool(access_token and mode == 'live'),
        ollama_host=os.environ.get('OLLAMA_HOST', 'http://localhost:11434'),
        ollama_model=os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b'),
        planner_enabled=os.environ.get('PLANNER_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
    )
