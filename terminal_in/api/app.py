"""
Flask + SocketIO application factory.
Call create_app(components) after all engine components are wired up.
"""

import logging

from flask import Flask
from flask_socketio import SocketIO

from terminal_in.api import websocket
from terminal_in.api.routes import chat, market, portfolio, risk, strategies, trades

log = logging.getLogger(__name__)


def create_app(components: dict) -> tuple[Flask, SocketIO]:
    """
    components keys: db, supervisor, broker, dsa, analyst, instruments
    Returns (flask_app, socketio).
    """
    app = Flask(__name__, static_folder=None)
    app.config['SECRET_KEY'] = components.get('jwt_secret', 'dev-secret')

    sio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

    # Init route modules
    db = components.get('db')
    supervisor = components.get('supervisor')
    broker = components.get('broker')
    dsa = components.get('dsa')
    analyst = components.get('analyst')
    learner = components.get('learner')
    instruments = components.get('instruments')
    orchestrator = components.get('orchestrator')

    portfolio.init(supervisor, broker, db=db)
    strategies.init(dsa, analyst, db=db, instruments=instruments,
                    learner=learner, orchestrator=orchestrator)
    trades.init(db)
    risk.init(supervisor)
    market.init(db)
    chat.init(db)

    # Register blueprints
    app.register_blueprint(portfolio.bp)
    app.register_blueprint(strategies.bp)
    app.register_blueprint(trades.bp)
    app.register_blueprint(risk.bp)
    app.register_blueprint(market.bp)
    app.register_blueprint(chat.bp)

    # Wire WebSocket fan-out
    websocket.init(sio)

    @app.route('/api/health')
    def health():
        from flask import jsonify
        return jsonify({'status': 'ok'})

    @sio.on('connect')
    def on_connect():
        log.info('WebSocket client connected')

    @sio.on('disconnect')
    def on_disconnect():
        log.info('WebSocket client disconnected')

    log.info('Flask app created')
    return app, sio
