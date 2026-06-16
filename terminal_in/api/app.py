"""
Flask + SocketIO application factory.
Call create_app(components) after all engine components are wired up.
"""

import logging

from flask import Flask
from flask_socketio import SocketIO

from terminal_in.api import websocket
from terminal_in.api.routes import agent_query, agents, backtest, chat, fno, market, portfolio, risk, settings, strategies, trades, training

log = logging.getLogger(__name__)


def create_app(components: dict) -> tuple[Flask, SocketIO]:
    """
    components keys: db, supervisor, broker, dsa, analyst, instruments
    Returns (flask_app, socketio).
    """
    app = Flask(__name__, static_folder=None)
    app.config['SECRET_KEY'] = components.get('jwt_secret', 'dev-secret')

    # threading mode: real OS threads (engine/orchestrator/FinBERT stay preemptive).
    # eventlet was greening all threads — one CPU-heavy task stalled the whole
    # process including Flask. simple-websocket provides native WS in this mode.
    sio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

    # Init route modules
    db = components.get('db')
    supervisor = components.get('supervisor')
    broker = components.get('broker')
    dsa = components.get('dsa')
    analyst = components.get('analyst')
    learner = components.get('learner')
    instruments = components.get('instruments')
    orchestrator = components.get('orchestrator')
    engine = components.get('engine')

    portfolio.init(supervisor, broker, db=db)
    strategies.init(dsa, analyst, db=db, instruments=instruments,
                    learner=learner, orchestrator=orchestrator)
    trades.init(db)
    risk.init(supervisor)
    market.init(db)
    chat.init(db)
    agents.init(engine=engine, db=db,
                planner=components.get('planner'),
                trading_supervisor=components.get('trading_supervisor'))
    training.init(trainer=components.get('trainer'), db=db)
    settings.init(db=db)
    backtest.init(db=db)
    fno.init(db=db, fno_broker=components.get('fno_broker'), kite=components.get('kite'))

    # Initialise EventBus ring buffer
    from terminal_in.api import event_buffer
    event_buffer.init()

    # Register blueprints
    app.register_blueprint(portfolio.bp)
    app.register_blueprint(strategies.bp)
    app.register_blueprint(trades.bp)
    app.register_blueprint(risk.bp)
    app.register_blueprint(market.bp)
    app.register_blueprint(chat.bp)
    app.register_blueprint(agents.bp)
    app.register_blueprint(agent_query.bp)
    app.register_blueprint(training.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(backtest.bp)
    app.register_blueprint(fno.bp)

    # Wire WebSocket fan-out
    websocket.init(sio)

    # Central error handling: JSON error responses with traceable ids
    from terminal_in import errors as _errors
    _errors.install_flask_handlers(app)

    # ── Packaged single-process mode ──────────────────────────────────────
    # When the UI has been static-exported (cd terminal_ui && BUILD_STATIC=1
    # npx next build), Flask serves it directly — no Node process needed.
    # The whole app then runs on :5000 alone.
    import os as _os
    from pathlib import Path as _Path
    # packaged exe sets UI_OUT_DIR to the bundled static export
    ui_out = _Path(_os.environ.get('UI_OUT_DIR', './terminal_ui/out'))
    if ui_out.exists():
        from flask import abort, send_from_directory

        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_ui(path: str):
            if path.startswith('api/') or path.startswith('socket.io'):
                abort(404)   # never shadow the API with the SPA fallback
            root = ui_out.resolve()
            target = (root / path) if path else (root / 'index.html')
            if path and target.is_file():
                return send_from_directory(root, path)
            # Next static export emits <route>.html for each page
            html = root / f'{path}.html'
            if path and html.is_file():
                return send_from_directory(root, f'{path}.html')
            return send_from_directory(root, 'index.html')

        log.info('Packaged mode: serving static UI from %s on :5000', ui_out)

    @app.route('/api/health')
    def health():
        """Liveness + degraded-mode report. Anything not 'ok'/full-strength
        is surfaced so the UI can badge it — no silent fallbacks."""
        from flask import jsonify
        import requests as _requests
        from terminal_in.strategy_engine.regime.classifier import classifier as _clf
        from terminal_in.news import sentiment as _sentiment

        # Ollama reachability (cheap probe, cached 30s)
        import time as _time
        now = _time.monotonic()
        cached = app.config.get('_ollama_probe')
        if cached and now - cached[0] < 30:
            ollama_online = cached[1]
        else:
            try:
                import os as _os
                base = _os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
                ollama_online = _requests.get(f'{base}/api/tags', timeout=2).status_code == 200
            except Exception:
                ollama_online = False
            app.config['_ollama_probe'] = (now, ollama_online)

        # Data freshness: latest real daily bar for NIFTY 50
        data_fresh = None
        try:
            if db is not None and instruments:
                nifty_tok = instruments.get('NIFTY 50')
                if nifty_tok:
                    last = db.get_ohlcv_last_dates([nifty_tok]).get(nifty_tok)
                    data_fresh = last
        except Exception:
            pass

        sent = _sentiment.status()
        degraded = []
        if _clf.mode == 'heuristic':
            degraded.append('regime_heuristic')
        if not sent['available']:
            degraded.append('sentiment_disabled')
        if not ollama_online:
            degraded.append('ollama_offline')

        from terminal_in import errors as _err
        recent_errors = _err.recent(5)
        if recent_errors:
            degraded.append('recent_errors')

        # hardware inventory (gpu_unused=True flags an idle GPU until the
        # DirectML/Vulkan path ships — visible here, not an amber badge)
        from terminal_in import hw as _hw
        hardware = _hw.detect()

        # Module 6 forward-EV head (Phase D₀). Trained/gated in the backtest;
        # not promoted to the LIVE judge yet, so the live EV source is the
        # heuristic — flagged here (invariant #3: untrained → flagged fallback),
        # not an amber badge (nothing is broken; M6 is simply not enabled live).
        try:
            from terminal_in.m6 import ev_head as _ev
            from terminal_in.data_ingest import events as _events
            m6 = {'ev_source': 'heuristic', 'mode': 'fallback',
                  'lightgbm_available': _ev.available(),
                  'event_plane': _events.freshness(),
                  'note': 'D0 EV head is gated in the backtest (validation.py --m6); '
                          'not yet promoted to the live judge'}
        except Exception:
            m6 = {'ev_source': 'heuristic', 'mode': 'unavailable'}

        return jsonify({
            'status': 'degraded' if degraded else 'ok',
            'degraded': degraded,
            'hardware': hardware,
            'regime_mode': _clf.mode,
            'sentiment': sent,
            'ollama_online': ollama_online,
            'm6': m6,
            'last_daily_bar': data_fresh,
            'recent_errors': [
                {k: e[k] for k in ('id', 'ts', 'source', 'message')} for e in recent_errors
            ],
        })

    @sio.on('connect')
    def on_connect():
        log.info('WebSocket client connected')

    @sio.on('disconnect')
    def on_disconnect():
        log.info('WebSocket client disconnected')

    log.info('Flask app created')
    return app, sio
