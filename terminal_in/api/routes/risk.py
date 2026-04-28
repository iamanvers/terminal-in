"""Risk and event calendar endpoints."""

from flask import Blueprint, jsonify

bp = Blueprint('risk', __name__, url_prefix='/api/risk')

_supervisor = None


def init(supervisor):
    global _supervisor
    _supervisor = supervisor


@bp.route('/stats')
def stats():
    if _supervisor is None:
        return jsonify({})
    return jsonify(_supervisor.daily_stats)


@bp.route('/events')
def events():
    from terminal_in.risk.event_calendar import calendar
    return jsonify(calendar.upcoming(days=30))
