"""Plant Operations report PDFs — daily (attendance + work log) and the pieces
the monthly report reuses. Branded to match the expense reports (same fonts,
logos, blue/ink palette). Low-level reportlab canvas, y measured from the top.

Daily  = 2 pages: attendance (labour + contractors, with OT) then work logs.
Monthly is built in expense_pdf-style elsewhere; the shared drawing helpers
live here so both reports look identical.
"""
import io
import os
from datetime import date, datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas

BLUE = "#1F7CCB"; INK = "#0d1421"; MUTED = "#6b7689"; LINE = "#d6dde6"
SOFT = "#eef2f7"; GREEN = "#059669"; AMBER = "#b45309"; RED = "#dc2626"; WHITE = "#ffffff"
W, H = A4
L = 40
R = W - 40

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_DIR = os.path.join(_BASE, "assets", "fonts")
_EA = os.path.join(_BASE, "static", "expense", "assets")
_FONTS = False


def _ensure():
    global _FONTS
    if _FONTS:
        return
    try:
        pdfmetrics.registerFont(TTFont("PHelv", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("PHelv-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
        _FONTS = True
    except Exception:
        _FONTS = False


def _f(b=False):
    if _FONTS:
        return "PHelv-Bold" if b else "PHelv"
    return "Helvetica-Bold" if b else "Helvetica"


def _hx(c):
    return HexColor(c)


def _fmt(n, dec=2):
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.{dec}f}" if dec else f"{v:,.0f}"


def _header(c, subtitle, title, ref):
    top = 28
    try:
        g = ImageReader(os.path.join(_EA, "group-logo.png"))
        gw, gh = g.getSize(); h = 20
        c.drawImage(g, L, H - top - h, width=h * gw / gh, height=h, mask="auto")
    except Exception:
        pass
    try:
        m = ImageReader(os.path.join(_EA, "metfraa-logo.png"))
        iw, ih = m.getSize(); bw, bh = 100, 24
        sc = min(bw / iw, bh / ih)
        c.drawImage(m, R - iw * sc, H - top - ih * sc, width=iw * sc, height=ih * sc, mask="auto")
    except Exception:
        pass
    c.setStrokeColor(_hx(LINE)); c.setLineWidth(.5); c.line(L, H - top - 34, R, H - top - 34)
    c.setFont(_f(True), 8); c.setFillColor(_hx(MUTED)); c.drawString(L, H - top - 52, subtitle.upper())
    c.setFont(_f(True), 19); c.setFillColor(_hx(INK)); c.drawString(L, H - top - 74, title)
    c.setFont(_f(), 9); c.setFillColor(_hx(MUTED)); c.drawString(L, H - top - 90, ref)
    return H - top - 118


def _footer(c, txt, pg):
    c.setStrokeColor(_hx(LINE)); c.setLineWidth(.5); c.line(L, 34, R, 34)
    c.setFont(_f(), 8); c.setFillColor(_hx(MUTED))
    c.drawString(L, 24, txt); c.drawRightString(R, 24, f"Page {pg}")


def _section(c, y, text):
    c.setFont(_f(True), 9); c.setFillColor(_hx(BLUE)); c.drawString(L, y, text.upper())
    y -= 6; c.setStrokeColor(_hx(LINE)); c.setLineWidth(.5); c.line(L, y, R, y)
    return y - 16


def _thead(c, y, cols):
    c.setFillColor(_hx(INK)); c.rect(L, y - 4, R - L, 20, fill=1, stroke=0)
    c.setFont(_f(True), 8); c.setFillColor(_hx(WHITE))
    for t, dx in cols:
        c.drawString(L + 8 + dx, y + 3, t.upper())
    return y - 4


def _clip(c, s, font, size, width):
    s = "" if s is None else str(s)
    if pdfmetrics.stringWidth(s, font, size) <= width:
        return s
    while s and pdfmetrics.stringWidth(s + "…", font, size) > width:
        s = s[:-1]
    return s + "…"


def _date_disp(d: date) -> str:
    return d.strftime("%d %b %Y")


def _month_disp(period: str) -> str:
    try:
        y, m = period.split("-")
        return datetime(int(y), int(m), 1).strftime("%B %Y")
    except Exception:
        return period


STATUS_COL = {"P": GREEN, "H": AMBER, "A": RED}


# ---------------------------------------------------------------------------
#  DAILY REPORT
# ---------------------------------------------------------------------------

def build_daily_pdf(d: date, labour: list, contractors: list,
                    labour_worklog: list, contractor_worklog: list,
                    summary: dict) -> bytes:
    """labour: [{name, designation, status, half_part, ot, ot_till, ot_half_hours, ot_amount}]
       contractors: [{name, skilled, helper, ot, ot_persons, ot_till, ot_amount}]
       labour_worklog: [{nature_of_work, skilled, helper, qty_nos, weight_kg, remarks}]
       contractor_worklog: [{contractor, nature_of_work, workers, qty_nos, weight_kg, remarks}]
       summary: {present, half, absent, ot_amount}"""
    _ensure()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    ref = "Date · " + _date_disp(d)
    foot = "Metfraa · Plant Operations · Daily Report · " + _date_disp(d)

    # ---- page 1: attendance ----
    y = _header(c, "Metfraa / Plant Operations", "Daily Attendance Report", ref)

    def chip(x, label, val, col):
        c.setFillColor(_hx(SOFT)); c.roundRect(x, y - 38, 118, 34, 3, fill=1, stroke=0)
        c.setFont(_f(True), 7); c.setFillColor(_hx(MUTED)); c.drawString(x + 10, y - 16, label.upper())
        c.setFont(_f(True), 16); c.setFillColor(_hx(col)); c.drawString(x + 10, y - 33, str(val))
    chip(L, "Present", summary.get("present", 0), GREEN)
    chip(L + 126, "Half", summary.get("half", 0), AMBER)
    chip(L + 252, "Absent", summary.get("absent", 0), RED)
    chip(L + 378, "OT amount", "₹ " + _fmt(summary.get("ot_amount", 0), 0), BLUE)
    y -= 64

    y = _section(c, y, "Own labour")
    y = _thead(c, y, [("Name", 0), ("Designation", 140), ("Status", 255),
                      ("OT till", 315), ("OT hrs", 395), ("OT amt", 455)])
    c.setFont(_f(), 9)
    for i, l in enumerate(labour):
        rh = 18
        if y - rh < 60:
            _footer(c, foot, "1"); c.showPage(); y = _header(c, "Metfraa / Plant Operations",
                                                             "Daily Attendance Report", ref)
            y = _thead(c, y, [("Name", 0), ("Designation", 140), ("Status", 255),
                              ("OT till", 315), ("OT hrs", 395), ("OT amt", 455)])
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        st = l["status"]
        st_disp = st + ((" (1st)" if l.get("half_part") == 1 else " (2nd)") if st == "H" and l.get("half_part") else "")
        c.setFillColor(_hx(INK)); c.setFont(_f(), 9)
        c.drawString(L + 8, y - 13, _clip(c, l["name"], _f(), 9, 128))
        c.setFillColor(_hx(MUTED)); c.drawString(L + 148, y - 13, _clip(c, l.get("designation", ""), _f(), 9, 110))
        c.setFillColor(_hx(STATUS_COL.get(st, INK))); c.setFont(_f(True), 9); c.drawString(L + 263, y - 13, st_disp)
        c.setFillColor(_hx(INK)); c.setFont(_f(), 9)
        if l.get("ot"):
            c.drawString(L + 323, y - 13, l.get("ot_till", "") or "")
            c.drawString(L + 403, y - 13, str(l.get("ot_half_hours", 0)))
            c.drawString(L + 463, y - 13, "₹" + _fmt(l.get("ot_amount", 0), 0))
        y -= rh
    y -= 18

    y = _section(c, y, "Contractor attendance")
    y = _thead(c, y, [("Team", 0), ("Skilled", 210), ("Helper", 280),
                      ("OT persons", 350), ("OT amt", 455)])
    c.setFont(_f(), 9)
    for i, ct in enumerate(contractors):
        rh = 18
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(True), 9)
        c.drawString(L + 8, y - 13, _clip(c, ct["name"], _f(True), 9, 195))
        c.setFont(_f(), 9)
        c.drawString(L + 218, y - 13, str(ct.get("skilled", 0)))
        c.drawString(L + 288, y - 13, str(ct.get("helper", 0)))
        if ct.get("ot"):
            c.drawString(L + 358, y - 13, f"{ct.get('ot_persons', 0)} till {ct.get('ot_till', '')}")
            c.drawString(L + 463, y - 13, "₹" + _fmt(ct.get("ot_amount", 0), 0))
        else:
            c.setFillColor(_hx(MUTED)); c.drawString(L + 358, y - 13, "—")
            c.drawString(L + 463, y - 13, "—")
        y -= rh
    _footer(c, foot, "1")
    c.showPage()

    # ---- page 2: work logs ----
    y = _header(c, "Metfraa / Plant Operations", "Daily Work Log", ref)
    y = _section(c, y, "Own-team work log")
    hdr = [("Nature of Work", 0), ("Sk", 190), ("Hp", 225), ("Qty", 260),
           ("Weight (Kg)", 315), ("Remarks", 400)]
    y = _thead(c, y, hdr)
    c.setFont(_f(), 9)
    for i, w in enumerate(labour_worklog):
        rh = 18
        if y - rh < 60:
            _footer(c, foot, "2"); c.showPage(); y = _header(c, "Metfraa / Plant Operations",
                                                             "Daily Work Log", ref)
            y = _thead(c, y, hdr)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK))
        c.drawString(L + 8, y - 13, _clip(c, w.get("nature_of_work", ""), _f(), 9, 178))
        c.drawString(L + 198, y - 13, str(w.get("skilled", 0)))
        c.drawString(L + 233, y - 13, str(w.get("helper", 0)))
        c.drawString(L + 268, y - 13, "" if w.get("qty_nos") is None else _fmt(w["qty_nos"]))
        c.drawString(L + 323, y - 13, "" if w.get("weight_kg") is None else _fmt(w["weight_kg"]))
        c.drawString(L + 408, y - 13, _clip(c, w.get("remarks", ""), _f(), 9, R - L - 408 - 8))
        y -= rh
    if not labour_worklog:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9); c.drawString(L + 8, y - 13, "No work lines."); y -= 18
    y -= 18

    y = _section(c, y, "Contractor work log")
    hdr2 = [("Contractor", 0), ("Nature of Work", 100), ("Workers", 270),
            ("Qty", 325), ("Weight (Kg)", 375), ("Remarks", 460)]
    y = _thead(c, y, hdr2)
    c.setFont(_f(), 9)
    for i, w in enumerate(contractor_worklog):
        rh = 18
        if y - rh < 60:
            _footer(c, foot, "2"); c.showPage(); y = _header(c, "Metfraa / Plant Operations",
                                                             "Daily Work Log", ref)
            y = _thead(c, y, hdr2)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(True), 9)
        c.drawString(L + 8, y - 13, _clip(c, w.get("contractor", ""), _f(True), 9, 90))
        c.setFont(_f(), 9)
        c.drawString(L + 108, y - 13, _clip(c, w.get("nature_of_work", ""), _f(), 9, 165))
        c.drawString(L + 278, y - 13, str(w.get("workers", 0)))
        c.drawString(L + 333, y - 13, "" if w.get("qty_nos") is None else _fmt(w["qty_nos"]))
        c.drawString(L + 383, y - 13, "" if w.get("weight_kg") is None else _fmt(w["weight_kg"]))
        c.drawString(L + 468, y - 13, _clip(c, w.get("remarks", ""), _f(), 9, R - L - 468 - 8))
        y -= rh
    if not contractor_worklog:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9); c.drawString(L + 8, y - 13, "No work lines."); y -= 18
    _footer(c, foot, "2")
    c.showPage()
    c.save()
    return buf.getvalue()
