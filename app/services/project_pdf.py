"""Project Operations report PDFs — daily (all contractors) and per-contractor
weekly. Branded like the plant/expense reports (same fonts, logos, palette).
Column widths are set to stay inside the A4 right margin."""
import io
import os
from datetime import date

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas

BLUE = "#1F7CCB"; INK = "#0d1421"; MUTED = "#6b7689"; LINE = "#d6dde6"
SOFT = "#eef2f7"; GREEN = "#059669"; WHITE = "#ffffff"
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
        pdfmetrics.registerFont(TTFont("POHelv", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("POHelv-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
        _FONTS = True
    except Exception:
        _FONTS = False


def _f(b=False):
    if _FONTS:
        return "POHelv-Bold" if b else "POHelv"
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
    c.setFont(_f(True), 18); c.setFillColor(_hx(INK)); c.drawString(L, H - top - 74, title)
    c.setFont(_f(), 9); c.setFillColor(_hx(MUTED)); c.drawString(L, H - top - 90, ref)
    return H - top - 116


def _footer(c, txt, pg):
    c.setStrokeColor(_hx(LINE)); c.setLineWidth(.5); c.line(L, 34, R, 34)
    c.setFont(_f(), 8); c.setFillColor(_hx(MUTED))
    c.drawString(L, 24, txt); c.drawRightString(R, 24, f"Page {pg}")


def _section(c, y, t):
    c.setFont(_f(True), 9); c.setFillColor(_hx(BLUE)); c.drawString(L, y, t.upper())
    y -= 6; c.setStrokeColor(_hx(LINE)); c.line(L, y, R, y)
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


def _att_table(c, y, foot, rows, page_lbl, title):
    """Attendance table (site, contractor, type, head, OT, amount). rows are
    dicts: {site, contractor, worker_type, headcount, ot_text, amount}."""
    cols = [("Site / Job", 0), ("Contractor", 120), ("Worker type", 235),
            ("Head", 320), ("OT", 360), ("Amount", 440)]
    y = _thead(c, y, cols)
    c.setFont(_f(), 9)
    total = 0.0
    for i, r in enumerate(rows):
        rh = 18
        if y - rh < 60:
            _footer(c, foot, page_lbl); c.showPage()
            y = _header(c, "Metfraa / Project Operations", title, foot.split("· ")[-1])
            y = _thead(c, y, cols)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(), 9)
        c.drawString(L + 8, y - 13, _clip(c, r["site"], _f(), 9, 108))
        c.drawString(L + 128, y - 13, _clip(c, r["contractor"], _f(), 9, 103))
        c.drawString(L + 243, y - 13, _clip(c, r["worker_type"], _f(), 9, 78))
        c.drawString(L + 328, y - 13, str(r["headcount"]))
        c.drawString(L + 368, y - 13, r.get("ot_text", "") or "—")
        c.drawString(L + 448, y - 13, "₹" + _fmt(r["amount"], 0))
        total += r["amount"]
        y -= rh
    return y, total


def _work_table(c, y, foot, rows, page_lbl, title):
    cols = [("Site", 0), ("Part", 60), ("Nature", 110), ("Workers", 230),
            ("Qty", 320), ("Wt(Kg)", 360), ("Time", 420), ("Equipment", 470)]
    y = _thead(c, y, cols)
    c.setFont(_f(), 8)
    for i, r in enumerate(rows):
        rh = 18
        if y - rh < 60:
            _footer(c, foot, page_lbl); c.showPage()
            y = _header(c, "Metfraa / Project Operations", title, foot.split("· ")[-1])
            y = _thead(c, y, cols)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(), 8)
        c.drawString(L + 6, y - 13, _clip(c, r["site"], _f(), 8, 48))
        c.drawString(L + 66, y - 13, _clip(c, r.get("part_mark", ""), _f(), 8, 42))
        c.drawString(L + 116, y - 13, _clip(c, r.get("nature_of_work", ""), _f(), 8, 112))
        c.drawString(L + 236, y - 13, _clip(c, r.get("workers", ""), _f(), 8, 82))
        c.drawString(L + 326, y - 13, "" if r.get("qty_nos") is None else _fmt(r["qty_nos"]))
        c.drawString(L + 366, y - 13, "" if r.get("weight_kg") is None else _fmt(r["weight_kg"]))
        c.drawString(L + 426, y - 13, _clip(c, r.get("time", ""), _f(), 8, 44))
        c.drawString(L + 476, y - 13, _clip(c, r.get("equipment", ""), _f(), 8, R - L - 476 - 6))
        y -= rh
    return y




def _grid_table(c, y, foot, title_for_cont, cols, rows, min_y=70):
    """Fully-bordered table. cols = [(header, width, align)] where align in
    {'l','r','c'}. rows = list of lists of cell strings (already formatted).
    Column x positions are derived from widths; the table spans L..R by scaling
    the last column if needed. Returns the y below the table."""
    total_w = sum(w for _, w, _ in cols)
    avail = R - L
    scale = avail / total_w if total_w else 1
    xs = []
    x = L
    for _, w, _a in cols:
        xs.append(x); x += w * scale
    right = x
    rh = 20

    def header():
        c.setFillColor(_hx(INK)); c.rect(L, y0 - rh, right - L, rh, fill=1, stroke=0)
        c.setFont(_f(True), 8); c.setFillColor(_hx(WHITE))
        for (h, w, a), xx in zip(cols, xs):
            cw = w * scale
            if a == "r":
                c.drawRightString(xx + cw - 6, y0 - 14, h.upper())
            elif a == "c":
                c.drawCentredString(xx + cw / 2, y0 - 14, h.upper())
            else:
                c.drawString(xx + 6, y0 - 14, h.upper())

    y0 = y
    header()
    yy = y0 - rh
    c.setFont(_f(), 8.5)
    for i, row in enumerate(rows):
        if yy - rh < min_y:
            # column borders for the drawn block, then new page
            _grid_borders(c, L, y0, right, yy, xs, rh)
            _footer(c, foot, "·"); c.showPage()
            y0 = _header(c, "Metfraa / Project Operations", title_for_cont, foot.split("· ")[-1])
            header(); yy = y0 - rh; c.setFont(_f(), 8.5)
        if i % 2 == 1:
            c.setFillColor(_hx(SOFT)); c.rect(L, yy - rh, right - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK))
        for (h, w, a), xx, val in zip(cols, xs, row):
            cw = w * scale
            txt = _clip(c, str(val), _f(), 8.5, cw - 10)
            if a == "r":
                c.drawRightString(xx + cw - 6, yy - 14, txt)
            elif a == "c":
                c.drawCentredString(xx + cw / 2, yy - 14, txt)
            else:
                c.drawString(xx + 6, yy - 14, txt)
        yy -= rh
    _grid_borders(c, L, y0, right, yy, xs, rh)
    return yy


def _grid_borders(c, x0, y_top, x_right, y_bot, xs, rh):
    """Draw the outer box + vertical column separators + horizontal row lines."""
    c.setStrokeColor(_hx(LINE)); c.setLineWidth(.5)
    # outer box
    c.rect(x0, y_bot, x_right - x0, y_top - y_bot, fill=0, stroke=1)
    # header separator
    c.line(x0, y_top - rh, x_right, y_top - rh)
    # vertical separators
    for xx in xs[1:]:
        c.line(xx, y_bot, xx, y_top)
    # horizontal row lines
    yy = y_top - rh
    while yy - rh >= y_bot - 0.5:
        yy -= rh
        c.line(x0, yy, x_right, yy)

# ---------------------------------------------------------------------------
#  DAILY (all contractors)
# ---------------------------------------------------------------------------

def build_daily_pdf(d: date, att_rows, work_rows, summary) -> bytes:
    _ensure()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    ref = "Date · " + d.strftime("%d %b %Y")
    foot = "Metfraa · Project Operations · Daily Report · " + d.strftime("%d %b %Y")

    y = _header(c, "Metfraa / Project Operations", "Daily Site Report", ref)

    def chip(x, label, val, col):
        c.setFillColor(_hx(SOFT)); c.roundRect(x, y - 38, 160, 34, 3, fill=1, stroke=0)
        c.setFont(_f(True), 7); c.setFillColor(_hx(MUTED)); c.drawString(x + 10, y - 16, label.upper())
        c.setFont(_f(True), 15); c.setFillColor(_hx(col)); c.drawString(x + 10, y - 33, str(val))
    chip(L, "Labour pay", "₹ " + _fmt(summary.get("pay", 0), 0), BLUE)
    chip(L + 168, "Weight", _fmt(summary.get("weight", 0), 0) + " Kg", INK)
    chip(L + 336, "Work lines", summary.get("work_lines", 0), GREEN)
    y -= 64

    y = _section(c, y, "Site Attendance")
    y, total = _att_table(c, y, foot, att_rows, "1", "Daily Site Report")
    y -= 6
    c.setFillColor(_hx(BLUE)); c.rect(L, y - 24, R - L, 26, fill=1, stroke=0)
    c.setFont(_f(True), 9); c.setFillColor(_hx(WHITE))
    c.drawString(L + 12, y - 16, "DAY LABOUR TOTAL")
    c.drawRightString(R - 12, y - 16, "₹ " + _fmt(total, 0))
    _footer(c, foot, "1")
    c.showPage()

    y = _header(c, "Metfraa / Project Operations", "Daily Work Progress", ref)
    y = _section(c, y, "Work Lines")
    if work_rows:
        y = _work_table(c, y, foot, work_rows, "2", "Daily Work Progress")
    else:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9); c.drawString(L + 8, y - 13, "No work lines.")
    _footer(c, foot, "2")
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
#  WEEKLY (one contractor)
# ---------------------------------------------------------------------------

def build_weekly_contractor_pdf(contractor_name, week_label, att_rows, work_rows,
                                totals) -> bytes:
    """One contractor's week. PAGE 1 = attendance & payments (bordered table +
    totals). PAGE 2 = work log (bordered table). att_rows/work_rows are already
    filtered to this contractor."""
    _ensure()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    ref = "Week · " + week_label
    foot = "Metfraa · Project Operations · Weekly Report · " + week_label
    title = "Weekly Contractor Report"

    # ---------- PAGE 1: attendance & payments ----------
    y = _header(c, "Metfraa / Project Operations · " + contractor_name, title, ref)

    def chip(x, label, val, col):
        c.setFillColor(_hx(SOFT)); c.roundRect(x, y - 38, 160, 34, 3, fill=1, stroke=0)
        c.setFont(_f(True), 7); c.setFillColor(_hx(MUTED)); c.drawString(x + 10, y - 16, label.upper())
        c.setFont(_f(True), 15); c.setFillColor(_hx(col)); c.drawString(x + 10, y - 33, str(val))
    chip(L, "Regular", "\u20b9 " + _fmt(totals.get("regular", 0), 0), INK)
    chip(L + 168, "OT", "\u20b9 " + _fmt(totals.get("ot", 0), 0), MUTED)
    chip(L + 336, "Total payable", "\u20b9 " + _fmt(totals.get("grand", 0), 0), BLUE)
    y -= 64

    y = _section(c, y, "Attendance & payments")
    cols = [("Site / Job", 150, "l"), ("Worker type", 110, "l"), ("Head", 45, "c"),
            ("OT", 70, "c"), ("Regular \u20b9", 80, "r"), ("OT \u20b9", 70, "r"),
            ("Amount \u20b9", 85, "r")]
    rows = [[r["site"], r["worker_type"], r["headcount"], r.get("ot_text", "") or "\u2014",
             _fmt(r.get("regular", 0), 0), _fmt(r.get("ot", 0), 0), _fmt(r["amount"], 0)]
            for r in att_rows]
    if rows:
        y = _grid_table(c, y, foot, title, cols, rows)
    else:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9); c.drawString(L + 8, y - 13, "No attendance this week."); y -= 18
    y -= 10
    c.setFillColor(_hx(BLUE)); c.rect(L, y - 32, R - L, 36, fill=1, stroke=0)
    c.setFont(_f(True), 9); c.setFillColor(_hx(WHITE))
    c.drawString(L + 12, y - 13, contractor_name.upper() + " \u2014 TOTAL PAYABLE")
    c.setFont(_f(True), 8)
    c.drawString(L + 12, y - 25, "Regular \u20b9" + _fmt(totals.get("regular", 0), 0)
                 + " \u00b7 OT \u20b9" + _fmt(totals.get("ot", 0), 0))
    c.setFont(_f(True), 18); c.drawRightString(R - 12, y - 20, "\u20b9 " + _fmt(totals.get("grand", 0), 0))
    _footer(c, foot, "1 of 2")
    c.showPage()

    # ---------- PAGE 2: work log ----------
    y = _header(c, "Metfraa / Project Operations · " + contractor_name, title + " \u2014 Work Log", ref)
    y = _section(c, y, "Work progress")
    wcols = [("Site", 62, "l"), ("Part", 48, "l"), ("Nature of work", 120, "l"),
             ("Workers", 92, "l"), ("Qty", 38, "r"), ("Wt (Kg)", 62, "r"),
             ("Time", 78, "l"), ("Equipment", 120, "l")]
    wrows = [[w["site"], w.get("part_mark", "") or "\u2014", w.get("nature_of_work", ""),
              w.get("workers", ""), "" if w.get("qty_nos") is None else _fmt(w["qty_nos"]),
              "" if w.get("weight_kg") is None else _fmt(w["weight_kg"]),
              w.get("time", ""), w.get("equipment", "")]
             for w in work_rows]
    if wrows:
        y = _grid_table(c, y, foot, title + " \u2014 Work Log", wcols, wrows)
        # weight total
        tw = sum((w.get("weight_kg") or 0) for w in work_rows)
        y -= 10
        c.setFillColor(_hx(BLUE)); c.rect(L, y - 24, R - L, 26, fill=1, stroke=0)
        c.setFont(_f(True), 9); c.setFillColor(_hx(WHITE))
        c.drawString(L + 12, y - 16, "TOTAL WEIGHT")
        c.drawRightString(R - 12, y - 16, _fmt(tw) + " Kg")
    else:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9); c.drawString(L + 8, y - 13, "No work lines this week.")
    _footer(c, foot, "2 of 2")
    c.showPage()
    c.save()
    return buf.getvalue()
