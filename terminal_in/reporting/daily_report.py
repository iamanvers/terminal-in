"""
Daily strategy report — PDF generation + email delivery.

Two scheduled runs (IST):
  08:55  PRE-OPEN  — trade suggestions for the day: latest orchestrator
                     candidates + planner verdicts, regime/VIX context,
                     yesterday's hindsight record
  15:45  EOD       — the day's record: best/worst trades, long/short
                     breakdown, F&O index signals, planner performance,
                     equity curve summary

Email is optional (SMTP_* in .env); the PDF always lands in
data/reports/ either way. Gmail: use an App Password, not the account
password (https://myaccount.google.com/apppasswords).
"""

import json
import logging
import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Event

from terminal_in.bus import bus

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
REPORTS_DIR = Path('./data/reports')

PRE_OPEN_HHMM = (8, 55)
EOD_HHMM      = (15, 45)

# ── Data assembly ───────────────────────────────────────────────────────────

def _symbol_of(token) -> str:
    try:
        from terminal_in.data_ingest.instruments import registry
        return registry.symbol(int(token)) or str(token)
    except Exception:
        return str(token)


def build_report_data(db, kind: str) -> dict:
    """kind: 'pre_open' | 'eod'. Pulls everything from DB + bus hot cache."""
    now = datetime.now(IST)
    regime  = bus.get_cached('regime.update') or {}
    pnl     = bus.get_cached('pnl.update') or {}
    planner = bus.get_cached('planner.verdict') or {}
    scan    = bus.get_cached('orchestrator.scan_done') or {}

    today_start_ms = int(datetime(now.year, now.month, now.day, tzinfo=IST).timestamp() * 1000)

    closed_today = []
    try:
        for t in db.get_closed_trades(limit=200):
            if (t.get('exit_time') or 0) >= today_start_ms:
                closed_today.append(t)
    except Exception:
        log.exception('report: closed trades query failed')

    open_positions = []
    try:
        open_positions = db.get_open_trades()
    except Exception:
        pass

    decisions = []
    try:
        decisions = db.get_recent_agent_decisions(limit=40)
    except Exception:
        pass

    closed_sorted = sorted(closed_today, key=lambda t: float(t.get('net_pnl') or 0), reverse=True)
    longs  = [t for t in closed_today if t.get('side') == 'BUY']
    shorts = [t for t in closed_today if t.get('side') == 'SELL']

    # F&O view: index-complex candidates from the latest scan
    index_tokens = {256265, 260105, 257801}
    fno_signals = [r for r in (scan.get('top_results') or []) if r.get('token') in index_tokens]

    # Suggestions: actionable candidates from the latest scan + verdicts
    suggestions = [
        r for r in (scan.get('top_results') or [])
        if r.get('side') in ('BUY', 'SELL') and r.get('ev', 0) > 0
    ][:8]

    judged = [d for d in decisions if d.get('hindsight_outcome')]
    rejected_judged = [d for d in judged if d['planner_action'] in ('reject', 'filtered')]
    hindsight = {
        'judged': len(judged),
        'rejected_would_win': sum(1 for d in rejected_judged if d['hindsight_outcome'] == 'would_win'),
        'rejected_would_lose': sum(1 for d in rejected_judged if d['hindsight_outcome'] == 'would_lose'),
    }

    return {
        'kind':        kind,
        'generated':   now.strftime('%d %b %Y, %H:%M IST'),
        'date':        now.strftime('%Y-%m-%d'),
        'regime':      str(regime.get('regime', '?')),
        'india_vix':   float(regime.get('india_vix') or 0),
        'size_mult':   float(regime.get('size_multiplier') or 1),
        'equity':      float(pnl.get('equity') or 0),
        'daily_pnl':   float(pnl.get('daily_pnl') or 0),
        'closed':      closed_sorted,
        'longs':       longs,
        'shorts':      shorts,
        'open':        open_positions,
        'fno_signals': fno_signals,
        'suggestions': suggestions,
        'planner':     {'mode': planner.get('mode'), 'verdicts': planner.get('verdicts') or []},
        'hindsight':   hindsight,
    }


# ── PDF rendering ───────────────────────────────────────────────────────────

def _logo_drawing(size: float = 26.0):
    """The TERMINAL//IN brand mark (same artwork as the app favicon),
    drawn vectorially for the PDF header."""
    from reportlab.graphics.shapes import Drawing, Rect, Line
    from reportlab.lib.colors import HexColor
    s = size / 64.0
    d = Drawing(size, size)
    d.add(Rect(0, 0, 64 * s, 64 * s, rx=14 * s, ry=14 * s,
               fillColor=HexColor('#0A0B0D'), strokeColor=HexColor('#23272E'),
               strokeWidth=1))
    for x, y, h, color in ((12, 18, 16, '#004AF8'), (26, 24, 20, '#0094FB'),
                           (40, 36, 16, '#00B9FC')):
        d.add(Rect(x * s, y * s, 7 * s, h * s, rx=1.5 * s, ry=1.5 * s,
                   fillColor=HexColor(color), strokeColor=None))
    for x1 in (30, 39):
        d.add(Line(x1 * s, 8 * s, (x1 + 8) * s, 24 * s,
                   strokeColor=HexColor('#ECEEF1'), strokeWidth=2.6 * s,
                   strokeLineCap=1))
    return d


def render_pdf(data: dict, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib.styles import ParagraphStyle

    BLUE  = colors.HexColor('#0057C2')
    GREEN = colors.HexColor('#15803D')
    RED   = colors.HexColor('#B91C1C')
    GREY  = colors.HexColor('#555555')

    h1   = ParagraphStyle('h1', fontName='Times-Bold', fontSize=18, spaceAfter=2)
    sub  = ParagraphStyle('sub', fontName='Helvetica', fontSize=8.5, textColor=GREY, spaceAfter=10)
    h2   = ParagraphStyle('h2', fontName='Times-Bold', fontSize=12.5, spaceBefore=12, spaceAfter=5, textColor=BLUE)
    body = ParagraphStyle('body', fontName='Helvetica', fontSize=8.5, leading=12)

    def money(v: float) -> str:
        return f"Rs {v:,.0f}"

    def trade_rows(trades, limit=8):
        rows = [['Symbol/ID', 'Side', 'Qty', 'Entry', 'Exit', 'P&L', 'Reason']]
        for t in trades[:limit]:
            pnl_v = float(t.get('net_pnl') or 0)
            rows.append([
                _symbol_of(t.get('instrument_token') or 0)[:16] if t.get('instrument_token') else str(t.get('trade_id', ''))[:16],
                str(t.get('side', '')),
                str(t.get('quantity', '')),
                f"{float(t.get('entry_price') or 0):,.1f}",
                f"{float(t.get('exit_price') or 0):,.1f}",
                f"{pnl_v:+,.0f}",
                str(t.get('exit_reason', ''))[:18],
            ])
        return rows

    def styled_table(rows, pnl_col: int | None = None):
        t = Table(rows, repeatRows=1)
        style = [
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 7.5),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 7.5),
            ('TEXTCOLOR', (0, 0), (-1, 0), GREY),
            ('LINEBELOW', (0, 0), (-1, 0), 0.6, GREY),
            ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]
        if pnl_col is not None:
            for i, row in enumerate(rows[1:], start=1):
                try:
                    v = float(str(row[pnl_col]).replace(',', '').replace('+', ''))
                    style.append(('TEXTCOLOR', (pnl_col, i), (pnl_col, i), GREEN if v >= 0 else RED))
                except ValueError:
                    pass
        t.setStyle(TableStyle(style))
        return t

    title = 'PRE-OPEN BRIEF' if data['kind'] == 'pre_open' else 'END-OF-DAY REPORT'
    brand = Table(
        [[_logo_drawing(26), Paragraph(f'TERMINAL//IN — {title}', h1)]],
        colWidths=[34, None],
    )
    brand.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story = [
        brand,
        Paragraph(f"{data['generated']} · regime {data['regime'].upper()} · "
                  f"India VIX {data['india_vix']:.1f} · size ×{data['size_mult']:.1f} · "
                  f"equity {money(data['equity'])} · day P&L {data['daily_pnl']:+,.0f}", sub),
        HRFlowable(width='100%', thickness=0.8, color=BLUE),
    ]

    if data['kind'] == 'pre_open':
        story.append(Paragraph('Trade Suggestions (latest scan + planner verdicts)', h2))
        if data['suggestions']:
            rows = [['Symbol', 'Side', 'Verdict', 'EV', 'Conf', 'Entry≈', 'SL', 'Target', 'Lenses']]
            for r in data['suggestions']:
                rows.append([
                    r.get('symbol', ''), r.get('side', ''), r.get('verdict', ''),
                    f"{r.get('ev', 0):.2f}", f"{r.get('confidence', 0)*100:.0f}%",
                    f"{r.get('price', 0):,.1f}", f"{r.get('suggested_sl', 0):,.1f}",
                    f"{r.get('suggested_target', 0):,.1f}",
                    '+'.join(l.get('strategy', '') for l in (r.get('lenses') or [])),
                ])
            story.append(styled_table(rows))
        else:
            story.append(Paragraph('No actionable candidates in the latest scan.', body))
        verdicts = data['planner'].get('verdicts') or []
        if verdicts:
            story.append(Paragraph('Planner Reasoning', h2))
            for v in verdicts[:6]:
                color = 'green' if v.get('action') == 'approve' else 'red'
                story.append(Paragraph(
                    f"<font color={color}><b>{str(v.get('action', '')).upper()}</b></font> "
                    f"{v.get('symbol', '')} {v.get('side') or ''} — {v.get('reason', '')}", body))

    else:  # EOD
        story.append(Paragraph('Best & Worst Trades', h2))
        if data['closed']:
            story.append(styled_table(trade_rows(data['closed'][:5] + data['closed'][-3:]), pnl_col=5))
        else:
            story.append(Paragraph('No trades closed today.', body))

        story.append(Paragraph(
            f"Longs: {len(data['longs'])} closed, "
            f"P&amp;L {sum(float(t.get('net_pnl') or 0) for t in data['longs']):+,.0f} · "
            f"Shorts: {len(data['shorts'])} closed, "
            f"P&amp;L {sum(float(t.get('net_pnl') or 0) for t in data['shorts']):+,.0f}", body))

        story.append(Paragraph('Open Positions (carried)', h2))
        if data['open']:
            rows = [['Symbol', 'Side', 'Qty', 'Entry', 'SL', 'Target']]
            for t in data['open'][:10]:
                rows.append([
                    _symbol_of(t.get('instrument_token', 0)),
                    str(t.get('side', '')), str(t.get('quantity', '')),
                    f"{float(t.get('entry_price') or 0):,.1f}",
                    f"{float(t.get('stop_loss') or 0):,.1f}",
                    f"{float(t.get('target') or 0):,.1f}",
                ])
            story.append(styled_table(rows))
        else:
            story.append(Paragraph('Flat — no open positions.', body))

    story.append(Paragraph('F&amp;O — Index Complex', h2))
    if data['fno_signals']:
        rows = [['Index', 'Side', 'Verdict', 'EV', 'RSI', 'Summary']]
        for r in data['fno_signals']:
            rows.append([r.get('symbol', ''), r.get('side', ''), r.get('verdict', ''),
                         f"{r.get('ev', 0):.2f}", f"{r.get('rsi', 0):.0f}",
                         str(r.get('summary', ''))[:60]])
        story.append(styled_table(rows))
    else:
        story.append(Paragraph('No index signals in the latest scan.', body))

    hs = data['hindsight']
    story.append(Paragraph('Agent Performance (hindsight)', h2))
    story.append(Paragraph(
        f"{hs['judged']} decisions judged · rejections that would have won: "
        f"{hs['rejected_would_win']} · rejections correctly avoided: {hs['rejected_would_lose']}", body))

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4,
                      leftMargin=16*mm, rightMargin=16*mm,
                      topMargin=14*mm, bottomMargin=14*mm).build(story)
    return path


# ── Email ───────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str, pdf_path: Path) -> bool:
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ.get('SMTP_USER', '')
    pwd  = os.environ.get('SMTP_PASS', '')
    to   = os.environ.get('REPORT_EMAIL_TO', user)
    if not user or not pwd:
        log.info('Report email skipped — SMTP_USER/SMTP_PASS not configured')
        return False
    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = user
        msg['To'] = to
        msg.set_content(body)
        msg.add_attachment(pdf_path.read_bytes(), maintype='application',
                           subtype='pdf', filename=pdf_path.name)
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        log.info('Report emailed to %s (%s)', to, pdf_path.name)
        return True
    except Exception:
        log.exception('Report email failed')
        return False


# ── Orchestration ───────────────────────────────────────────────────────────

def generate(db, kind: str, email: bool = True) -> dict:
    """Build + render + (optionally) email one report. Returns metadata."""
    data = build_report_data(db, kind)
    fname = f"{data['date']}_{kind}.pdf"
    path = render_pdf(data, REPORTS_DIR / fname)
    emailed = False
    if email:
        title = 'Pre-open brief' if kind == 'pre_open' else 'EOD report'
        emailed = send_email(
            subject=f"TERMINAL//IN {title} — {data['date']}",
            body=(f"{title} attached.\n"
                  f"Regime {data['regime']} · VIX {data['india_vix']:.1f} · "
                  f"equity ₹{data['equity']:,.0f} · day P&L {data['daily_pnl']:+,.0f}"),
            pdf_path=path,
        )
    bus.publish('report.generated', {'kind': kind, 'path': str(path), 'emailed': emailed})
    return {'kind': kind, 'path': str(path), 'emailed': emailed}


class ReportScheduler:
    """Fires the pre-open brief at 08:55 IST (after triggering a fresh scan
    at 08:50 so suggestions are current) and the EOD report at 15:45 IST."""

    def __init__(self, db):
        self._db = db
        self._fired: set[str] = set()   # '{date}:{kind}' once-per-day guards

    def run(self, stop_event: Event):
        log.info('ReportScheduler started (pre-open 08:55 / EOD 15:45 IST)')
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception('ReportScheduler tick failed')
            stop_event.wait(60)

    def _tick(self):
        now = datetime.now(IST)
        if now.weekday() >= 5:   # market closed on weekends
            return
        key_scan = f'{now.date()}:scan'
        key_pre  = f'{now.date()}:pre_open'
        key_eod  = f'{now.date()}:eod'
        hhmm = (now.hour, now.minute)

        if hhmm >= (8, 50) and hhmm < PRE_OPEN_HHMM and key_scan not in self._fired:
            self._fired.add(key_scan)
            bus.publish('orchestrator.scan_now', {})   # fresh candidates for the brief
        if hhmm >= PRE_OPEN_HHMM and hhmm < (9, 30) and key_pre not in self._fired:
            self._fired.add(key_pre)
            generate(self._db, 'pre_open')
        if hhmm >= EOD_HHMM and key_eod not in self._fired:
            self._fired.add(key_eod)
            generate(self._db, 'eod')
