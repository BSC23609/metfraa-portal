"""Branded individual expense-claim PDF — a faithful port of the old Node app's
server/services/pdf.js (PDFKit) to reportlab.

The old app produced the polished report you see in the July consolidated PDF:
group + company logo header, an employee info card, a purpose/project strip,
per-form itemised tables, a blue total banner, a signature row, and one page
per bill. The migrated portal lost all of that and emitted a bare reportlab
table; this restores the original design pixel-close.

It mirrors PDFKit's absolute-positioning model with reportlab's low-level
canvas rather than flowables, so the layout matches the original rather than
merely resembling it. DejaVu Sans is bundled (as in the old app) because the
built-in Helvetica has no ₹ glyph.
"""
import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas

# --- design tokens (mirror the frontend theme, exactly as the old app) ---
BLUE = "#1F7CCB"
BLUE_D = "#155a96"
INK = "#0d1421"
MUTED = "#6b7689"
LINE = "#d6dde6"
SOFT = "#eef2f7"
SUCCESS = "#059669"
WARN = "#b45309"

PAGE_W, PAGE_H = A4          # 595.27 x 841.89 pt
L = 50                       # left margin
R = PAGE_W - 50              # right edge
FOOT_H = 30

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FONT_DIR = os.path.join(_ASSETS, "assets", "fonts")
_EXP_ASSETS = os.path.join(_ASSETS, "static", "expense", "assets")
GROUP_LOGO = os.path.join(_EXP_ASSETS, "group-logo.png")
COMPANY_LOGOS = {
    "bsc": os.path.join(_EXP_ASSETS, "bsc-logo.png"),
    "metfraa": os.path.join(_EXP_ASSETS, "metfraa-logo.png"),
}

# Register DejaVu under the Helvetica names the old code used, so the whole
# renderer reads the same. Done once, guarded.
_FONTS_READY = False


def _ensure_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    try:
        reg = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
        bold = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
        if os.path.exists(reg):
            pdfmetrics.registerFont(TTFont("Helv", reg))
            pdfmetrics.registerFont(TTFont("Helv-Obl", reg))
        if os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("Helv-Bold", bold))
        _FONTS_READY = True
    except Exception:
        _FONTS_READY = False


def _font(bold=False, obl=False):
    if _FONTS_READY:
        return "Helv-Bold" if bold else ("Helv-Obl" if obl else "Helv")
    return "Helvetica-Bold" if bold else ("Helvetica-Oblique" if obl else "Helvetica")


SUBTITLES = {
    "met_local": "Metfraa / LTA", "met_cab": "Metfraa / CAB",
    "met_accommodation": "Metfraa / ACC", "met_outstation": "Metfraa / OUT",
    "met_misc": "Metfraa / MISC", "met_advance": "Metfraa / ADV",
    "met_dtr": "Metfraa / DTR",
}
TITLES = {
    "met_local": "Local Travel Allowance", "met_cab": "Cab Reimbursement",
    "met_accommodation": "Monthly Accommodation Reimbursement",
    "met_outstation": "Outstation Travel Reimbursement",
    "met_misc": "Miscellaneous Reimbursement",
    "met_advance": "Travel Advance Request",
    "met_dtr": "Daily Travel Reimbursement",
}


def _fmt(n):
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.2f}"


def _date(s):
    if not s:
        return "—"
    for f in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:len(datetime.now().strftime(f))], f).strftime("%d %b %Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")).strftime("%d %b %Y")
    except Exception:
        return str(s)


def _period(s):
    if not s:
        return "—"
    if len(str(s)) == 7 and "-" in str(s):
        y, m = str(s).split("-")
        try:
            return datetime(int(y), int(m), 1).strftime("%B %Y")
        except ValueError:
            return s
    return s


# ---------------------------------------------------------------------------
# The renderer is a small stateful helper around a reportlab canvas that tracks
# a y-cursor from the top (PDFKit-style), auto-adds pages, and paints the
# header on each. Coordinates are converted (reportlab origin is bottom-left).
# ---------------------------------------------------------------------------

class _Doc:
    def __init__(self, buf, subtitle, title, reference, company):
        _ensure_fonts()
        self.c = _canvas.Canvas(buf, pagesize=A4)
        self.c.setTitle(f"{title} — {reference}")
        self.subtitle = subtitle
        self.reference = reference
        self.company = company
        self.page = 1
        self._pages_drawn = []   # (footer drawn later)
        self._header()
        self.y = 80              # content starts below header band

    # y is measured from the TOP; convert for canvas draws
    def _ty(self, y_from_top):
        return PAGE_H - y_from_top

    def _header(self):
        top = 30
        try:
            g = ImageReader(GROUP_LOGO)
            gw, gh = g.getSize()
            h = 22
            self.c.drawImage(g, L, self._ty(top + h), width=h * gw / gh, height=h,
                             mask="auto")
        except Exception:
            pass
        co = COMPANY_LOGOS.get(self.company)
        if co:
            try:
                im = ImageReader(co)
                iw, ih = im.getSize()
                boxW, boxH = 110, 26
                scale = min(boxW / iw, boxH / ih)
                w, hh = iw * scale, ih * scale
                self.c.drawImage(im, R - w, self._ty(top + hh), width=w, height=hh,
                                 mask="auto")
            except Exception:
                pass
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(0.5)
        self.c.line(L, self._ty(top + 38), R, self._ty(top + 38))

    def add_page(self):
        self._footer(self.page)          # stamp the page we're leaving
        self.c.showPage()
        self.page += 1
        self._header()
        self.y = 80

    def need(self, space):
        if self.y + space > PAGE_H - FOOT_H - 30:
            self.add_page()

    def text(self, s, x, y_top, size, color, bold=False, obl=False, width=None,
             align="left", cspace=0.0):
        self.c.setFont(_font(bold, obl), size)
        self.c.setFillColor(color)
        if cspace:
            self.c._charSpace = cspace
        s = "—" if s is None else str(s)
        if width and align == "right":
            self.c.drawRightString(x + width, self._ty(y_top + size), s)
        elif width and align == "center":
            self.c.drawCentredString(x + width / 2, self._ty(y_top + size), s)
        else:
            if width:
                s = self._clip(s, _font(bold, obl), size, width)
            self.c.drawString(x, self._ty(y_top + size), s)
        if cspace:
            self.c._charSpace = 0

    def _clip(self, s, font, size, width):
        if pdfmetrics.stringWidth(s, font, size) <= width:
            return s
        while s and pdfmetrics.stringWidth(s + "…", font, size) > width:
            s = s[:-1]
        return s + "…"

    def wrapped(self, s, x, y_top, size, color, width, bold=False, obl=False,
                leading=None):
        """Draw multi-line wrapped text; returns the y-cursor after."""
        font = _font(bold, obl)
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        leading = leading or size * 1.35
        words = str(s).split()
        line = ""
        yy = y_top
        for w in words:
            trial = (line + " " + w).strip()
            if pdfmetrics.stringWidth(trial, font, size) > width and line:
                self.c.drawString(x, self._ty(yy + size), line)
                yy += leading
                line = w
            else:
                line = trial
        if line:
            self.c.drawString(x, self._ty(yy + size), line)
            yy += leading
        return yy

    def rect(self, x, y_top, w, h, fill=None, stroke=None, lw=0.5):
        if fill:
            self.c.setFillColor(fill)
        if stroke:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(lw)
        self.c.rect(x, self._ty(y_top + h), w, h, fill=1 if fill else 0,
                    stroke=1 if stroke else 0)

    def hline(self, x1, x2, y_top, color=LINE, lw=0.5):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(lw)
        self.c.line(x1, self._ty(y_top), x2, self._ty(y_top))

    # ---- shared components (sectionHeading / table / tripBanner) ----

    def section(self, text):
        self.need(60)
        self.y += 8
        self.text(text.upper(), L, self.y, 8, BLUE, bold=True, width=R - L,
                  cspace=0.4)
        self.hline(L, R, self.y + 12)
        self.y += 22

    def table(self, headers, rows, widths, numeric=None):
        numeric = numeric or []
        totalW = R - L
        s = sum(widths)
        if s > 0 and abs(s - totalW) > 0.5:
            widths = [w * totalW / s for w in widths]
        PAD = 6
        self.need(60)
        # header
        y = self.y
        self.rect(L, y, totalW, 22, fill=INK)
        x = L + PAD
        for i, h in enumerate(headers):
            self.text(h.upper(), x, y + 7, 8, "white", bold=True,
                      width=widths[i] - PAD * 2, cspace=0.8)
            x += widths[i]
        y += 22
        # body
        for idx, r in enumerate(rows):
            heights = []
            for i, cell in enumerate(r):
                txt = "—" if cell is None else str(cell)
                heights.append(self._measure(txt, widths[i] - PAD * 2, 9))
            rowH = max(18, max(heights) + PAD * 2)
            if y + rowH > PAGE_H - FOOT_H - 30:
                self.add_page()
                y = self.y
            if idx % 2 == 0:
                self.rect(L, y, totalW, rowH, fill=SOFT)
            x = L + PAD
            for i, cell in enumerate(r):
                txt = "—" if cell is None else str(cell)
                al = "right" if i in numeric else "left"
                self._cell(txt, x, y + PAD, widths[i] - PAD * 2, 9, al)
                x += widths[i]
            self.hline(L, R, y + rowH, color=LINE, lw=0.3)
            y += rowH
        self.y = y + 8

    def _measure(self, s, width, size):
        font = _font()
        words = str(s).split()
        if not words:
            return size * 1.2
        lines, line = 1, ""
        for w in words:
            trial = (line + " " + w).strip()
            if pdfmetrics.stringWidth(trial, font, size) > width and line:
                lines += 1
                line = w
            else:
                line = trial
        return lines * size * 1.2

    def _cell(self, s, x, y_top, width, size, align):
        font = _font()
        self.c.setFont(font, size)
        self.c.setFillColor(INK)
        words = str(s).split()
        line, yy = "", y_top
        drawn = []
        for w in words:
            trial = (line + " " + w).strip()
            if pdfmetrics.stringWidth(trial, font, size) > width and line:
                drawn.append(line)
                line = w
            else:
                line = trial
        if line:
            drawn.append(line)
        for ln in drawn or [""]:
            if align == "right":
                self.c.drawRightString(x + width, self._ty(yy + size), ln)
            else:
                self.c.drawString(x, self._ty(yy + size), ln)
            yy += size * 1.2

    def trip_banner(self, title, dates):
        self.need(60)
        y = self.y
        self.rect(L, y, R - L, 22, fill=INK)
        self.text(title.upper(), L + 10, y + 6, 10, "white", bold=True, cspace=1)
        if dates:
            self.text(dates, L, y + 6, 9, "#9bb6d4", width=R - L - 10, align="right")
        self.y = y + 28

    def finish(self):
        self._footer(self.page)          # last page
        self.c.save()

    def _footer(self, page_no):
        # Page count isn't known until the end, so the footer shows the page
        # number and total pages via the total captured at finish time. We
        # store the total on the instance; when unknown mid-render we show the
        # running number, then overwrite is impossible — so we render "Page N".
        y = PAGE_H - FOOT_H
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(0.5)
        self.c.line(L, self._ty(y), R, self._ty(y))
        gen = datetime.now().strftime("%d/%m/%Y, %I:%M:%S %p")
        self.text(f"Ref {self.reference}  ·  Generated {gen}", L, y + 8, 8, MUTED)
        total = getattr(self, "_total_pages", None)
        label = f"Page {page_no} of {total}" if total else f"Page {page_no}"
        self.text(label, L, y + 8, 8, MUTED, width=R - L, align="right")


# ===========================================================================
#  Form-specific body renderers (ported 1:1 from pdf.js)
# ===========================================================================

MODE_LABEL = {"bus": "Bus", "bike_taxi": "Bike Taxi", "auto": "Auto",
              "share_auto": "Share Auto"}
DTR_PURPOSE = {"project_visit": "Project", "site_visit": "Site",
               "sales_visit": "Sales", "metfraa_office": "M. Office",
               "metfraa_factory": "M. Factory", "purchase_visit": "Purchase",
               "other": "Other"}
PURPOSE_NAMES = {
    "project_visit": "Project Visit", "site_visit": "Site Visit",
    "sales_visit": "Sales Visit", "metfraa_office": "Visit to Metfraa - Office",
    "metfraa_factory": "Visit to Metfraa - Factory",
    "purchase_visit": "Purchase Visit", "other": "Other",
}


def _render_local(d, p):
    d.section(f"Vehicle — {p.get('vehicle_label') or p.get('vehicle_type','')}  ·  "
              f"Rate ₹{_fmt(p.get('rate_per_km'))}/km")
    rows = [[_date(t.get("date")), t.get("from"), t.get("to"), t.get("purpose") or "—",
             f"{_fmt(t.get('km'))} KM", f"₹ {_fmt(t.get('amount'))}"]
            for t in (p.get("trips") or [])]
    d.table(["Date", "From", "To", "Purpose", "Distance", "Amount"], rows,
            [70, 95, 95, 130, 65, 70], numeric=[4, 5])


def _render_cab(d, p):
    d.section("Cab Reimbursement — Trips 80 km+")
    rows = [[_date(r.get("date")), r.get("pickup"), r.get("drop"),
             f"{r.get('km') or '—'} km", f"₹ {_fmt(r.get('fare'))}", r.get("purpose") or "—"]
            for r in (p.get("rides") or [])]
    d.table(["Date", "Pickup", "Drop", "Distance", "Fare", "Purpose"], rows,
            [70, 95, 95, 60, 70, 105], numeric=[4])


def _render_misc(d, p):
    items = p.get("items") or []
    d.section(f"Miscellaneous Reimbursement · {len(items)} item(s)")
    rows = [[_date(it.get("date")), it.get("purpose") or "—", f"₹ {_fmt(it.get('amount'))}"]
            for it in items]
    d.table(["Date", "Purpose", "Amount"], rows, [90, 290, 95], numeric=[2])


def _render_dtr(d, p, lookup):
    entries = p.get("entries") if isinstance(p.get("entries"), list) else []
    d.section(f"Daily Travel · {len(entries)} {'entry' if len(entries) == 1 else 'entries'}")
    rows = []
    for e in entries:
        ctx = "—"
        pc = e.get("purpose_category")
        pid = e.get("project_id")
        if pc == "project_visit" and pid is not None and lookup.get(pid):
            pr = lookup[pid]
            ctx = f"{pr['name']} ({pr['code']})" if pr.get("code") and pr["code"] != pr["name"] else pr["name"]
        elif pc == "site_visit" and e.get("client_name"):
            ctx = f"Site: {e['client_name']}"
        elif pc == "purchase_visit" and e.get("client_name"):
            ctx = f"Vendor: {e['client_name']}"
        elif pc == "sales_visit" and e.get("client_name"):
            ctx = f"Client: {e['client_name']}"
        elif pc == "metfraa_office":
            ctx = "Metfraa Office"
        elif pc == "metfraa_factory":
            ctx = "Metfraa Factory"
        elif pc == "other" and e.get("purpose_other_reason"):
            ctx = e["purpose_other_reason"]
        bill = "—" if e.get("mode") == "bus" else "Yes"
        rows.append([_date(e.get("date")), MODE_LABEL.get(e.get("mode"), e.get("mode")),
                     e.get("from") or "—", e.get("to") or "—",
                     DTR_PURPOSE.get(e.get("purpose_category"), "—"), ctx, bill,
                     f"₹ {_fmt(e.get('fare'))}"])
    d.table(["Date", "Mode", "From", "To", "Purpose", "Context", "Bill", "Fare"],
            rows, [54, 56, 80, 80, 50, 90, 30, 55], numeric=[7])

    remarks = [e for e in entries if e.get("remarks")]
    if remarks:
        d.y += 8
        d.text("REMARKS", L, d.y, 9, MUTED, bold=True, cspace=1.3)
        d.y += 14
        for e in remarks:
            d.y = d.wrapped(f"{_date(e.get('date'))} — {e['remarks']}", L, d.y, 9, INK, R - L)
    others = [e for e in entries if e.get("purpose_category") == "other" and e.get("purpose_other_reason")]
    if others:
        d.y += 8
        d.text("OTHER — REASONS", L, d.y, 9, MUTED, bold=True, cspace=1.3)
        d.y += 14
        for e in others:
            d.y = d.wrapped(f"{_date(e.get('date'))} — {e['purpose_other_reason']}", L, d.y, 9, INK, R - L)


def _render_advance(d, p):
    d.section("Travel Advance — Trip Details")
    d.table(["Field", "Detail"],
            [["Destination", p.get("destination") or "—"],
             ["Travel from", _date(p.get("travel_from"))],
             ["Travel to", _date(p.get("travel_to"))],
             ["Mode of travel", p.get("mode") or "Not specified"]],
            [140, 350])
    d.y += 8
    d.section("Purpose / Justification")
    d.y = d.wrapped(p.get("purpose") or "—", L, d.y, 11, INK, R - L)
    if p.get("notes"):
        d.y += 6
        d.y = d.wrapped("Additional notes: " + p["notes"], L, d.y, 9, MUTED, R - L, obl=True)
    d.y += 8
    d.y = d.wrapped(
        "Settlement: actual bills are to be submitted via the reimbursement forms "
        "after the trip. Any balance is returned by the employee, or reimbursed "
        "to them, as applicable.", L, d.y, 9, MUTED, R - L, obl=True)


def _render_accommodation(d, p):
    limit = p.get("daily_limit") or 0
    entries = p.get("entries") or []
    d.section(f"Daily Limit ({p.get('level','')}) · ₹{_fmt(limit)} / day  ·  "
              f"Days claimed: {len(entries)}")
    rows = []
    over_any = False
    for e in entries:
        amt = float(e.get("amount") or 0)
        over = amt > limit
        over_any = over_any or over
        rows.append([_date(e.get("date")), e.get("location") or "—",
                     e.get("hotel") or "—", e.get("bill_no") or "—",
                     f"₹ {_fmt(amt)}{' ⚠' if over else ''}"])
    d.table(["Date", "Location", "Hotel / Stay", "Bill #", "Amount"], rows,
            [75, 110, 175, 90, 75], numeric=[4])
    if over_any:
        d.y += 4
        d.y = d.wrapped(f"⚠ One or more entries exceed the daily limit of ₹{_fmt(limit)} "
                        "— management approval required.", L, d.y, 9, WARN, R - L, obl=True)


def _render_outstation(d, p):
    ent = p.get("entitlement") or {}
    d.section(f"Level {p.get('level','')} entitlement · Train {ent.get('train')} · "
              f"Bus {ent.get('bus')} · Food up to ₹{_fmt(ent.get('food_per_day'))}/day")
    CAT = {"travel": "Long-distance Travel", "accommodation": "Accommodation",
           "food": "Food", "local_conveyance": "Local Conv.", "others": "Other"}
    for idx, trip in enumerate(p.get("trips") or []):
        d.trip_banner(f"Trip {idx + 1:02d} · {trip.get('place','')}",
                      f"{_date(trip.get('from_date'))} — {_date(trip.get('to_date'))}")
        if trip.get("purpose"):
            d.y = d.wrapped(f"Purpose: {trip['purpose']}", L, d.y, 9, MUTED, R - L, obl=True)
            d.y += 4
        if trip.get("manager_approval"):
            d.text(f"✓ Approved by: {trip['manager_approval']}", L, d.y, 9, SUCCESS)
            d.y += 14
        rows = []
        cats = trip.get("categories") or {}
        for cat in ("travel", "accommodation", "food", "local_conveyance", "others"):
            for item in (cats.get(cat) or []):
                if not (float(item.get("amount") or 0) > 0) and not item.get("desc"):
                    continue
                rows.append([_date(item.get("date")), item.get("desc") or "—",
                             CAT[cat], f"₹ {_fmt(item.get('amount'))}"])
        if rows:
            d.table(["Date", "Description", "Category", "Amount"], rows,
                    [75, 230, 110, 75], numeric=[3])
        else:
            d.y = d.wrapped("No expenses logged for this trip.", L, d.y, 9, MUTED, R - L, obl=True)


_BODY = {
    "met_local": lambda d, s, p: _render_local(d, p),
    "met_cab": lambda d, s, p: _render_cab(d, p),
    "met_misc": lambda d, s, p: _render_misc(d, p),
    "met_dtr": lambda d, s, p: _render_dtr(d, p, s.get("project_lookup") or {}),
    "met_advance": lambda d, s, p: _render_advance(d, p),
    "met_accommodation": lambda d, s, p: _render_accommodation(d, p),
    "met_outstation": lambda d, s, p: _render_outstation(d, p),
}


# ===========================================================================
#  Main entry
# ===========================================================================

def _signoff(who, when):
    if not who:
        return ""
    line = str(who)
    if when:
        try:
            w = str(when)
            iso = w.replace(" ", "T") + "Z" if len(w) == 19 and w[10] == " " else w
            line += " · " + datetime.fromisoformat(iso.replace("Z", "")).strftime("%d %b %Y, %I:%M %p")
        except Exception:
            line += " · " + str(when)
    return line


def _render_all(d, sub, emp, payload, attachments, suppress_attachments):
    ft = sub["form_type"]
    title = TITLES.get(ft, ft)
    subtitle = SUBTITLES.get(ft, "EXPENSE SUBMISSION")

    # -- title block --
    d.y += 20
    d.text(subtitle, L, d.y, 9, MUTED, cspace=1.2)
    d.y += 16
    d.text(title.upper(), L, d.y, 22, INK, bold=True, cspace=0.5, width=R - L)
    d.y += 26
    d.text(f"Reference · {sub['reference']}", L, d.y, 9, MUTED)
    d.y += 20

    # -- employee info card --
    infoY = d.y
    infoH = 80
    d.rect(L, infoY, R - L, infoH, fill=SOFT)
    colW = (R - L) / 4
    cells = [
        ("NAME", emp.get("name") or "—"), ("EMPLOYEE ID", emp.get("employee_code") or "—"),
        ("DESIGNATION", emp.get("designation") or "—"), ("LEVEL", emp.get("level") or "—"),
        ("DEPARTMENT", emp.get("department") or "—"), ("EMAIL", emp.get("email") or "—"),
        ("PERIOD", _period(sub.get("period"))),
        ("SUBMITTED", _date(sub.get("submitted_at") or datetime.now().isoformat())),
    ]
    for i, (lbl, val) in enumerate(cells):
        col, row = i % 4, i // 4
        x = L + col * colW + 10
        yy = infoY + 10 + row * 35
        d.text(lbl, x, yy, 7, MUTED, bold=True, cspace=1.3)
        d.text(val, x, yy + 12, 10, INK, width=colW - 20)
    d.y = infoY + infoH + 20

    # -- purpose / project strip --
    pc = sub.get("purpose_category")
    if pc or sub.get("project") or sub.get("client_name"):
        purpose_text = PURPOSE_NAMES.get(pc, "—")
        second_label, second_value = "PROJECT", "—"
        proj = sub.get("project")
        if pc == "project_visit" and proj:
            second_value = proj["name"] + (f" ({proj['code']})" if proj.get("code") and proj["code"] != proj["name"] else "")
        elif pc == "site_visit":
            second_label, second_value = "SITE", sub.get("client_name") or "—"
        elif pc == "purchase_visit":
            second_label, second_value = "VENDOR", sub.get("client_name") or "—"
        elif pc == "sales_visit":
            second_label, second_value = "CLIENT", sub.get("client_name") or "—"
        elif pc in ("metfraa_office", "metfraa_factory"):
            second_label = "DESTINATION"
            second_value = "Metfraa Office" if pc == "metfraa_office" else "Metfraa Factory"
        elif pc == "other":
            second_label, second_value = "REASON", (sub.get("purpose_other_reason") or "—")
        stripY = d.y
        stripH = 40
        d.rect(L, stripY, R - L, stripH, fill=SOFT)
        d.text("PURPOSE", L + 10, stripY + 8, 7, MUTED, bold=True, cspace=1.3)
        d.text(purpose_text, L + 10, stripY + 20, 12, INK, bold=True, width=(R - L) / 2 - 20)
        d.text(second_label, L + (R - L) / 2 + 10, stripY + 8, 7, MUTED, bold=True, cspace=1.3)
        d.text(second_value, L + (R - L) / 2 + 10, stripY + 20, 12, INK, bold=True, width=(R - L) / 2 - 20)
        d.y = stripY + stripH + 16
        if pc == "other" and sub.get("purpose_other_reason") and len(sub["purpose_other_reason"]) > 60:
            d.text("REASON (FULL)", L, d.y, 7, MUTED, bold=True, cspace=1.3)
            d.y += 12
            d.y = d.wrapped(sub["purpose_other_reason"], L, d.y, 10, INK, R - L)
            d.y += 6

    # -- body --
    _BODY.get(ft, lambda d, s, p: None)(d, sub, payload)

    # -- total banner --
    d.need(80)
    d.y += 12
    banY = d.y
    banH = 56
    total_label = "ADVANCE AMOUNT REQUESTED" if ft == "met_advance" else "TOTAL REIMBURSEMENT CLAIM"
    d.rect(L, banY, R - L, banH, fill=BLUE)
    d.text(total_label, L + 20, banY + 14, 10, "white", cspace=1.6)
    d.text(f"₹ {_fmt(sub.get('total_amount'))}", L, banY + 16, 22, "white", bold=True,
           width=R - L - 20, align="right")
    d.y = banY + banH + 24

    # -- signatures --
    d.need(120)
    sigY = d.y + 40
    gap = 24
    sigColW = (R - L - gap * 2) / 3
    status = sub.get("status")
    checked, approved = "", ""
    if status == "settled":
        checked = _signoff(sub.get("reviewed_by"), sub.get("reviewed_at"))
        approved = _signoff(sub.get("settlement_reviewed_by"), sub.get("settlement_reviewed_at"))
    elif status == "approved":
        checked = approved = _signoff(sub.get("reviewed_by"), sub.get("reviewed_at"))
    elif status in ("advance_approved", "settlement_pending"):
        checked = _signoff(sub.get("reviewed_by"), sub.get("reviewed_at"))

    if ft == "met_advance":
        advX = L + sigColW + gap
        advW = sigColW * 2 + gap
        d.hline(L, L + sigColW, sigY, color=INK, lw=0.7)
        if emp.get("name"):
            d.text(emp["name"], L, sigY + 4, 9, INK, width=sigColW)
        d.text("EMPLOYEE · DATE", L, sigY + 20, 7, MUTED, bold=True, cspace=1.1, width=sigColW)
        arows = [("HR VERIFIED", _signoff(sub.get("advance_hr_verified_by"), sub.get("advance_hr_verified_at"))),
                 ("MGMT APPROVED", _signoff(sub.get("advance_mgmt_approved_by"), sub.get("advance_mgmt_approved_at"))),
                 ("ACCOUNTS PAID", _signoff(sub.get("advance_paid_by"), sub.get("advance_paid_at")))]
        if status == "settled":
            arows.append(("SETTLEMENT APPROVED", _signoff(sub.get("settlement_reviewed_by"), sub.get("settlement_reviewed_at"))))
        rowH = 14
        for ri, (lbl, fill) in enumerate(arows):
            yy = sigY + 4 + ri * rowH
            d.text(lbl, advX, yy, 7, MUTED, bold=True, cspace=1.1, width=110)
            if fill:
                d.text(fill, advX + 115, yy, 8, INK, width=advW - 115)
            else:
                d.hline(advX + 115, advX + advW - 5, yy + 9, color=MUTED, lw=0.4)
        d.y = sigY + 4 + len(arows) * rowH + 12
    else:
        cols = [(L, emp.get("name") or "", "EMPLOYEE · DATE"),
                (L + sigColW + gap, checked, "CHECKED BY · DATE"),
                (L + (sigColW + gap) * 2, approved, "APPROVED BY · DATE")]
        for x, name, lbl in cols:
            d.hline(x, x + sigColW, sigY, color=INK, lw=0.7)
            if name:
                d.text(name, x, sigY + 4, 9, INK, width=sigColW)
            d.text(lbl, x, sigY + 20, 7, MUTED, bold=True, cspace=1.1, width=sigColW)
        d.y = sigY + 40

    # -- bills (only when NOT merging externally) --
    if attachments and not suppress_attachments:
        for idx, att in enumerate(attachments):
            _render_bill(d, att, idx + 1, len(attachments))


def _render_bill(d, att, idx, total):
    d.add_page()
    d.text(f"BILL {idx} OF {total}", L, d.y, 8, MUTED, bold=True, cspace=1.4)
    d.y += 14
    d.text(att.get("label") or att.get("filename") or "Bill", L, d.y, 13, INK, bold=True, width=R - L)
    d.y += 18
    d.text(f"Category: {att.get('category') or 'general'} · {att.get('mime_type')} · "
           f"{round((att.get('size_bytes') or 0) / 1024)} KB", L, d.y, 9, MUTED)
    d.y += 20
    mime = att.get("mime_type") or ""
    data = att.get("_bytes")
    if mime.startswith("image/") and data:
        try:
            img = ImageReader(io.BytesIO(data))
            iw, ih = img.getSize()
            maxW, maxH = R - L, PAGE_H - 200 - d.y
            scale = min(maxW / iw, maxH / ih)
            w, hh = iw * scale, ih * scale
            d.c.drawImage(img, L + (maxW - w) / 2, d._ty(d.y + hh), width=w, height=hh, mask="auto")
        except Exception:
            d.y = d.wrapped("Could not render this bill image.", L, d.y, 10, WARN, R - L, obl=True)
    elif mime == "application/pdf":
        d.rect(L, d.y, R - L, 80, fill=SOFT)
        d.text("PDF Attachment", L + 20, d.y + 12, 11, INK, bold=True)
        d.text(att.get("filename") or "", L + 20, d.y + 32, 10, MUTED)
        d.text("The original PDF is included with the consolidated report.",
               L + 20, d.y + 50, 9, MUTED, obl=True)
        d.y += 96
    else:
        d.y = d.wrapped(f"Unsupported preview type: {mime}.", L, d.y, 10, MUTED, R - L, obl=True)


def build_claim_pdf(sub: dict, emp: dict, payload: dict, attachments=None,
                    suppress_attachments=False) -> bytes:
    """Render one claim's branded PDF.

    sub: dict with form_type, reference, period, total_amount, status, the
         review/advance timestamps, purpose_category, project, client_name,
         purpose_other_reason, project_lookup.
    emp: name, employee_code, designation, level, department, email.
    attachments: list of {label, filename, category, mime_type, size_bytes,
                 _bytes}. Pass suppress_attachments=True when the bills will be
                 merged in afterwards.

    Two-pass so the footer can show "Page N of M".
    """
    attachments = attachments or []

    # pass 1: count pages
    tmp = io.BytesIO()
    d1 = _Doc(tmp, SUBTITLES.get(sub["form_type"], ""), TITLES.get(sub["form_type"], sub["form_type"]),
              sub["reference"], "metfraa")
    _render_all(d1, sub, emp, payload, attachments, suppress_attachments)
    total_pages = d1.page

    # pass 2: real render with the count known
    buf = io.BytesIO()
    d2 = _Doc(buf, SUBTITLES.get(sub["form_type"], ""), TITLES.get(sub["form_type"], sub["form_type"]),
              sub["reference"], "metfraa")
    d2._total_pages = total_pages
    _render_all(d2, sub, emp, payload, attachments, suppress_attachments)
    d2.finish()
    return buf.getvalue()


# ===========================================================================
#  Adapter: portal ORM -> the dicts build_claim_pdf expects.
# ===========================================================================

def build_from_submission(db, sub, attachments=None, suppress_attachments=False) -> bytes:
    """Render a portal ExpenseSubmission with the branded renderer.

    db: SQLAlchemy session (to resolve the employee + DTR project lookup).
    sub: ExpenseSubmission ORM object.
    attachments: optional list of dicts each with the keys build_claim_pdf
                 needs plus _bytes; if None and not suppressed, the caller is
                 expected to have merged bills separately.
    """
    from ..models import Employee, ExpenseEmployeeMeta, ExpenseProject

    emp_row = db.query(Employee).filter(Employee.id == sub.employee_id).first()
    meta = (db.query(ExpenseEmployeeMeta)
            .filter(ExpenseEmployeeMeta.employee_id == sub.employee_id).first())
    emp = {
        "name": (emp_row.name if emp_row else None) or sub.employee_name,
        "employee_code": emp_row.employee_code if emp_row else None,
        "designation": (emp_row.designation if emp_row else None) or "",
        "level": sub.employee_level or (meta.level if meta else "") or "",
        "department": (emp_row.department if emp_row else None) or "",
        "email": (emp_row.email if emp_row else None) or sub.employee_email or "",
    }

    payload = sub.payload or {}

    # DTR needs project id -> {name, code}
    project_lookup = {}
    if sub.form_type == "met_dtr":
        ids = {e.get("project_id") for e in (payload.get("entries") or [])
               if e.get("project_id") is not None}
        if ids:
            for pr in db.query(ExpenseProject).filter(ExpenseProject.id.in_(list(ids))).all():
                project_lookup[pr.id] = {"name": pr.name, "code": pr.code}

    # purpose/project strip context
    project = None
    pid = payload.get("project_id")
    if pid is not None:
        pr = db.query(ExpenseProject).filter(ExpenseProject.id == pid).first()
        if pr:
            project = {"name": pr.name, "code": pr.code}

    s = {
        "form_type": sub.form_type, "reference": sub.reference, "period": sub.period,
        "total_amount": sub.total_amount, "status": sub.status,
        "submitted_at": sub.submitted_at_ist,
        "reviewed_by": sub.reviewed_by, "reviewed_at": sub.reviewed_at_ist,
        "settlement_reviewed_by": sub.settlement_reviewed_by,
        "settlement_reviewed_at": sub.settled_at_ist,
        "advance_hr_verified_by": sub.advance_hr_verified_by,
        "advance_hr_verified_at": sub.advance_hr_verified_at,
        "advance_mgmt_approved_by": sub.advance_mgmt_approved_by,
        "advance_mgmt_approved_at": sub.advance_mgmt_approved_at,
        "advance_paid_by": sub.advance_paid_by, "advance_paid_at": sub.advance_paid_at,
        "purpose_category": payload.get("purpose_category"),
        "purpose_other_reason": payload.get("purpose_other_reason"),
        "client_name": payload.get("client_name"),
        "project": project, "project_lookup": project_lookup,
    }
    return build_claim_pdf(s, emp, payload, attachments=attachments,
                           suppress_attachments=suppress_attachments)
