"""
Application settings — DB-backed overrides on top of .env defaults.

The packaged app (PRD 5b.2) has no editable .env, so every operator-tunable
variable lives here: a typed SCHEMA, an `app_settings` key-value table, and
GET/POST /api/settings. Precedence: settings table > .env > coded default.

Hot vs restart: settings marked hot=True take effect immediately (the value
is pushed into os.environ, and consumers read it at use-time); the rest are
applied to Config at boot via apply_overrides() and flagged restart-required
in the UI. The .env file is never modified.
"""

import logging
import os

log = logging.getLogger(__name__)

# type: 'bool' | 'number' | 'text' | 'select' | 'password'
# env: the os.environ key the value maps to (also the settings-table key)
SCHEMA: list[dict] = [
    # ── Trading ──────────────────────────────────────────────────────────
    dict(env='MODE', group='Trading', label='Mode', type='select',
         options=['paper', 'live'], default='paper', hot=False,
         help='live requires a fresh Kite access token'),
    dict(env='INITIAL_CAPITAL', group='Trading', label='Initial capital (Rs)',
         type='number', min=10000, max=1e9, default=1000000, hot=False),
    dict(env='MAX_DD_PCT', group='Trading', label='Max drawdown (fraction)',
         type='number', min=0.01, max=0.5, default=0.20, hot=False),
    dict(env='DAILY_LOSS_CAP_PCT', group='Trading', label='Daily loss cap (fraction)',
         type='number', min=0.005, max=0.2, default=0.04, hot=False),
    dict(env='AUTO_TRADE', group='Trading', label='Auto-trade (execute signals)',
         type='bool', default=True, hot=True,
         help='off = advise-only: signals still shown, but the gate blocks fills'),

    dict(env='SECTOR_CAP_PCT', group='Trading', label='Sector cap (fraction of book)',
         type='number', min=0.2, max=1.0, default=0.40, hot=True),
    dict(env='SECTOR_SMALL_BOOK_FLOOR', group='Trading', label='Small-book sector floor',
         type='bool', default=True, hot=True,
         help='always allow 2 positions per sector; cap applies beyond'),

    # ── Planner ──────────────────────────────────────────────────────────
    dict(env='PLANNER_ENABLED', group='Planner', label='LLM planner', type='bool',
         default=True, hot=False,
         help='off = deterministic pipeline only (no LLM judge)'),
    dict(env='OLLAMA_HOST', group='Planner', label='Ollama host', type='text',
         default='http://localhost:11434', hot=False),
    # type stays 'text' for validation; the GET route upgrades it to a
    # dropdown of installed models when Ollama is reachable
    dict(env='OLLAMA_MODEL', group='Planner', label='Model', type='text',
         default='qwen2.5:3b', hot=False),
    dict(env='LLM_BACKEND', group='Planner', label='LLM backend', type='select',
         options=['ollama', 'openai'], default='ollama', hot=False,
         help="'ollama' (default) or 'openai' for any OpenAI-compatible server (e.g. local llama-server)"),
    dict(env='LLM_BASE_URL', group='Planner', label='OpenAI-compatible base URL', type='text',
         default='http://localhost:8080', hot=False,
         help='used only when backend = openai'),
    dict(env='LLM_MODEL', group='Planner', label='Model name (openai backend)', type='text',
         default='', hot=False, help='served model name; blank = use Ollama model'),
    dict(env='PLANNER_GATES_ENGINE', group='Planner', label='LLM judge gates engine signals',
         type='bool', default=True, hot=True,
         help='deterministic strategies AND the LLM judge must both concur'),
    dict(env='PLANNER_TIMEOUT_S', group='Planner', label='LLM timeout (s)',
         type='number', min=10, max=110, default=60, hot=False,
         help='must stay below the 120s scan interval'),

    # ── Broker (live) ────────────────────────────────────────────────────
    dict(env='KITE_API_KEY', group='Broker', label='Kite API key',
         type='password', default='', hot=False),
    dict(env='KITE_API_SECRET', group='Broker', label='Kite API secret',
         type='password', default='', hot=False),
    dict(env='KITE_ACCESS_TOKEN', group='Broker', label='Kite access token (daily)',
         type='password', default='', hot=False),

    # ── Data ─────────────────────────────────────────────────────────────
    dict(env='NEWSAPI_KEY', group='Data', label='NewsAPI key (optional)',
         type='password', default='', hot=False),

    # ── Reports ──────────────────────────────────────────────────────────
    # Hot: daily_report reads these from os.environ at send time
    dict(env='REPORTS_ENABLED', group='Reports', label='Daily PDF reports',
         type='bool', default=True, hot=True),
    dict(env='REPORT_EMAIL_TO', group='Reports', label='Report recipient',
         type='text', default='', hot=True),
    dict(env='SMTP_HOST', group='Reports', label='SMTP host', type='text',
         default='smtp.gmail.com', hot=True),
    dict(env='SMTP_PORT', group='Reports', label='SMTP port', type='number',
         min=1, max=65535, default=587, hot=True),
    dict(env='SMTP_USER', group='Reports', label='SMTP user', type='text',
         default='', hot=True),
    dict(env='SMTP_PASS', group='Reports', label='SMTP password (app password)',
         type='password', default='', hot=True),

    # ── System ───────────────────────────────────────────────────────────
    dict(env='LOG_LEVEL', group='System', label='Log level', type='select',
         options=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO', hot=True),
    dict(env='LOW_LATENCY', group='System', label='High process priority',
         type='bool', default=False, hot=False),
    dict(env='PYTHON_JIT', group='System', label='Python JIT (experimental)',
         type='bool', default=False, hot=False),

    # ── Training ─────────────────────────────────────────────────────────
    dict(env='LORA_BASE_MODEL', group='Training', label='LoRA base model (HF id)',
         type='text', default='Qwen/Qwen2.5-1.5B-Instruct', hot=False,
         help='1.5B fp32 fits 16GB locally; 3B+ trains on a cloud GPU'),

    # Deliberately NOT exposed: JWT_SECRET, SQLITE_PATH/DUCKDB_PATH/
    # ARTIFACTS_DIR (moving the DB under a live process corrupts state),
    # TIMEZONE (NSE-only product), LORA_DATASET_DIR/OUTPUT_DIR/MAX_STEPS
    # (owned per-run by the TRAIN module).
]

_BY_ENV = {s['env']: s for s in SCHEMA}
SECRET_TYPES = {'password'}


def _coerce(spec: dict, raw: str):
    """Validate + coerce a raw string against the spec. Raises ValueError."""
    if spec['type'] == 'bool':
        if str(raw).lower() not in ('true', 'false', '1', '0', 'yes', 'no'):
            raise ValueError(f"{spec['env']}: expected true/false")
        return str(raw).lower() in ('true', '1', 'yes')
    if spec['type'] == 'number':
        v = float(raw)
        if 'min' in spec and v < spec['min']:
            raise ValueError(f"{spec['env']}: below minimum {spec['min']}")
        if 'max' in spec and v > spec['max']:
            raise ValueError(f"{spec['env']}: above maximum {spec['max']}")
        return v
    if spec['type'] == 'select':
        if raw not in spec['options']:
            raise ValueError(f"{spec['env']}: must be one of {spec['options']}")
        return raw
    return str(raw)


def current_values(db) -> dict:
    """Effective value per setting: DB override > os.environ > default."""
    overrides = db.get_app_settings()
    out = {}
    for s in SCHEMA:
        if s['env'] in overrides:
            out[s['env']] = overrides[s['env']]
        else:
            out[s['env']] = os.environ.get(s['env'], str(s['default']))
    return out


def describe(db) -> list[dict]:
    """Schema + effective values for the UI. Secrets are masked."""
    values = current_values(db)
    overrides = db.get_app_settings()
    items = []
    for s in SCHEMA:
        v = values[s['env']]
        masked = s['type'] in SECRET_TYPES and bool(v)
        items.append({
            'env': s['env'], 'group': s['group'], 'label': s['label'],
            'type': s['type'], 'options': s.get('options'),
            'min': s.get('min'), 'max': s.get('max'),
            'help': s.get('help'), 'hot': s['hot'],
            'value': '••••••••' if masked else v,
            'overridden': s['env'] in overrides,
        })
    return items


def update(db, changes: dict) -> dict:
    """Validate + persist changes. Returns {applied: [...], restart_required: [...]}.
    Masked sentinel values ('••••••••') are ignored, so re-saving a form
    never clobbers a stored secret."""
    applied, restart = [], []
    for env, raw in changes.items():
        spec = _BY_ENV.get(env)
        if spec is None:
            raise ValueError(f'unknown setting: {env}')
        if raw == '••••••••':
            continue
        _coerce(spec, str(raw))  # raises on invalid
        db.set_app_setting(env, str(raw))
        # push into the process env so use-time readers see it immediately
        os.environ[env] = str(raw)
        if spec['hot']:
            applied.append(env)
            if env == 'LOG_LEVEL':
                logging.getLogger().setLevel(str(raw).upper())
        else:
            restart.append(env)
    if applied or restart:
        log.info('settings updated: hot=%s restart_required=%s', applied, restart)
    return {'applied': applied, 'restart_required': restart}


def apply_overrides(db) -> int:
    """At boot, before load_config(): push every stored override into
    os.environ so load_config() (which reads the environment) sees them.
    Returns the number of overrides applied."""
    overrides = db.get_app_settings()
    for env, value in overrides.items():
        if env in _BY_ENV:
            os.environ[env] = value
    if overrides:
        log.info('settings: %d stored overrides applied over .env', len(overrides))
    return len(overrides)
