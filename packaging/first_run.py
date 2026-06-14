"""First-run onboarding wizard (PRD 5b.1).

On the very first launch of the packaged app (no ``.onboarded`` marker in the
per-user data dir) we collect the essentials — capital, risk tier, mode, and
optional Kite / e-mail keys — and persist them to the settings DB BEFORE the
backend builds its Config, so they take effect on this first boot. Everything
here is editable later from the in-app Settings panel; subsequent launches skip
straight to the terminal.

The wizard runs in its OWN process (run_app re-invokes the exe with TIN_WIZARD=1)
because pywebview's event loop can only be started once per process — isolating
it keeps the main window's lifecycle clean.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

MARKER = '.onboarded'

# Risk tier → (max drawdown, daily loss cap) as fractions. Mirrors the PRD tiers.
RISK_TIERS = {
    'conservative': {'MAX_DD_PCT': '0.10', 'DAILY_LOSS_CAP_PCT': '0.02'},
    'balanced':     {'MAX_DD_PCT': '0.15', 'DAILY_LOSS_CAP_PCT': '0.03'},
    'aggressive':   {'MAX_DD_PCT': '0.20', 'DAILY_LOSS_CAP_PCT': '0.04'},
}

# form field → settings env key (optional secrets/contact, persisted only if set)
_OPTIONAL = (
    ('kite_key', 'KITE_API_KEY'), ('kite_secret', 'KITE_API_SECRET'),
    ('kite_token', 'KITE_ACCESS_TOKEN'), ('report_email', 'REPORT_EMAIL_TO'),
    ('smtp_user', 'SMTP_USER'), ('smtp_pass', 'SMTP_PASS'),
)


def needs_onboarding(appdata: Path) -> bool:
    return not (Path(appdata) / MARKER).exists()


def mark_done(appdata: Path) -> None:
    (Path(appdata) / MARKER).write_text('1', encoding='utf-8')


def build_changes(form: dict) -> dict:
    """Map the wizard form to validated settings changes (pure — unit-tested)."""
    changes: dict[str, str] = {}
    try:
        cap = int(float(form.get('capital') or 1_000_000))
    except (TypeError, ValueError):
        cap = 1_000_000
    changes['INITIAL_CAPITAL'] = str(max(10_000, cap))
    tier = str(form.get('tier') or 'aggressive').lower()
    changes.update(RISK_TIERS.get(tier, RISK_TIERS['aggressive']))
    changes['MODE'] = 'live' if str(form.get('mode')) == 'live' else 'paper'
    for k_form, k_env in _OPTIONAL:
        v = str(form.get(k_form) or '').strip()
        if v:
            changes[k_env] = v
    return changes


def persist(appdata: Path, form: dict) -> dict:
    """Validate + persist the wizard answers through the same path the Settings
    panel uses, then drop the onboarded marker. Returns the applied changes."""
    from terminal_in.config import load_config
    from terminal_in.db import DB
    from terminal_in import app_settings

    changes = build_changes(form)
    db = DB(load_config().sqlite_path)
    try:
        app_settings.update(db, changes)   # validates, persists, sets os.environ
    except Exception:
        log.exception('first-run: settings validation/persist failed')
        # best-effort: write what validates individually so the app still boots
        for env, val in changes.items():
            try:
                app_settings.update(db, {env: val})
            except Exception:
                log.warning('first-run: skipped invalid setting %s', env)
    mark_done(appdata)
    log.info('first-run onboarding complete: %d settings', len(changes))
    return changes


# ── Native wizard window (pywebview) ────────────────────────────────────────────

_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
:root{--bg:#0A0B0D;--panel:#121419;--card:#1C1F25;--border:#23272E;--text:#ECEEF1;
--sub:#AEB3BB;--muted:#71767F;--accent:#0094FB;--warn:#FFB02E;--green:#2DBD80}
*{box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{background:var(--bg);color:var(--text);margin:0;padding:28px 30px}
h1{font-size:16px;letter-spacing:.16em;margin:0 0 2px}
.sub{color:var(--muted);font-size:11px;margin-bottom:20px}
label{display:block;font-size:10.5px;color:var(--sub);letter-spacing:.04em;margin:14px 0 5px}
input,select{width:100%;background:#0A0B0D;border:1px solid var(--border);border-radius:6px;
color:var(--text);font-size:12px;padding:8px 9px}
.row{display:flex;gap:12px}.row>div{flex:1}
.adv{margin-top:18px;border-top:1px solid var(--border);padding-top:8px}
summary{cursor:pointer;font-size:10.5px;color:var(--muted);letter-spacing:.06em}
.note{font-size:9.5px;color:var(--muted);margin-top:4px}
.warn{color:var(--warn)}
.actions{display:flex;gap:10px;margin-top:24px}
button{flex:1;padding:10px 0;border-radius:6px;border:none;font-size:12px;font-weight:700;
letter-spacing:.06em;cursor:pointer}
.primary{background:var(--accent);color:#06070A}.ghost{background:#1C1F25;color:var(--sub)}
</style></head><body>
<h1>TERMINAL//IN</h1><div class="sub">First-run setup — all of this is editable later in Settings.</div>
<label>INITIAL CAPITAL (₹)</label>
<input id="capital" type="number" value="1000000" min="10000" step="10000">
<div class="row"><div>
<label>RISK TIER</label>
<select id="tier"><option value="conservative">Conservative · 10% DD / 2% daily</option>
<option value="balanced">Balanced · 15% DD / 3% daily</option>
<option value="aggressive" selected>Aggressive · 20% DD / 4% daily</option></select>
</div><div>
<label>MODE</label>
<select id="mode" onchange="document.getElementById('kite').style.display=this.value=='live'?'block':'none'">
<option value="paper" selected>Paper (simulated fills)</option>
<option value="live">Live (Zerodha Kite)</option></select>
</div></div>
<div id="kite" style="display:none">
<div class="note warn">Live mode needs a Kite API key/secret and a fresh daily access token.</div>
<label>KITE API KEY</label><input id="kite_key" type="text" autocomplete="off">
<label>KITE API SECRET</label><input id="kite_secret" type="password" autocomplete="off">
<label>KITE ACCESS TOKEN (daily)</label><input id="kite_token" type="password" autocomplete="off">
</div>
<details class="adv"><summary>Optional — daily e-mail report</summary>
<label>REPORT RECIPIENT</label><input id="report_email" type="text" autocomplete="off">
<label>SMTP USER</label><input id="smtp_user" type="text" autocomplete="off">
<label>SMTP APP PASSWORD</label><input id="smtp_pass" type="password" autocomplete="off">
</details>
<div class="actions">
<button class="ghost" onclick="skip()">USE DEFAULTS</button>
<button class="primary" onclick="go()">START</button></div>
<script>
function val(id){var e=document.getElementById(id);return e?e.value:'';}
function go(){var f={};['capital','tier','mode','kite_key','kite_secret','kite_token',
'report_email','smtp_user','smtp_pass'].forEach(function(k){f[k]=val(k);});
window.pywebview.api.submit(f);}
function skip(){window.pywebview.api.skip();}
</script></body></html>"""


class _Api:
    def __init__(self, appdata: Path):
        self._appdata = Path(appdata)
        self.window = None
        self.completed = False

    def submit(self, form):
        try:
            persist(self._appdata, form or {})
        except Exception:
            log.exception('onboarding submit failed')
        self.completed = True
        if self.window:
            self.window.destroy()

    def skip(self):
        mark_done(self._appdata)        # defaults; don't nag again
        self.completed = True
        if self.window:
            self.window.destroy()


def run_wizard_window(appdata: Path, icon: str | None = None) -> bool:
    """Show the native onboarding window; blocks until the user finishes.
    Returns True if it ran to completion. Safe no-op (returns False) if pywebview
    is unavailable — the app then boots with defaults."""
    try:
        import webview
    except Exception:
        log.warning('first-run: pywebview unavailable, skipping wizard')
        return False
    api = _Api(appdata)
    api.window = webview.create_window(
        'TERMINAL//IN — Setup', html=_HTML, js_api=api,
        width=560, height=760, resizable=False, background_color='#0A0B0D')
    webview.start(icon=icon)
    return api.completed
