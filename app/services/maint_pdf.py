"""Maintenance report PDFs — Machine History Card (per asset) and the
Breakdown Register. Branded identically to the Plant reports by reusing their
drawing helpers (same fonts, blue/ink palette, header/footer)."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as _canvas

from .plant_pdf import (_ensure, _f, _hx, _fmt, _clip, _header, _section,
                        _thead, _footer, L, R, INK, MUTED, SOFT, BLUE, GREEN, RED)


def build_history_card(asset: dict, events: list) -> bytes:
    _ensure()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    code = asset.get("asset_code", "")
    y = _header(c, "Metfraa / Maintenance", "Machine History Card", code)

    # --- equipment details (2-column key/value) ---
    y = _section(c, y, "Equipment details")
    cap = ""
    if asset.get("capacity") is not None:
        cap = f'{_fmt(asset["capacity"], 0)} {asset.get("capacity_unit") or ""}'.strip()
    pairs = [
        ("Code", asset.get("asset_code") or "—"),
        ("Type", asset.get("type_name") or "—"),
        ("Description", asset.get("description") or "—"),
        ("Category", asset.get("category") or "—"),
        ("Make / Vendor", asset.get("manufacturer") or "—"),
        ("Serial / Model", asset.get("serial_model_no") or "—"),
        ("Capacity", cap or "—"),
        ("Location", asset.get("location") or "—"),
        ("Acquired", asset.get("acquisition_date") or "—"),
        ("Mfg year", str(asset.get("mfg_year")) if asset.get("mfg_year") else "—"),
    ]
    col_w = (R - L) / 2
    row_h = 15
    for i, (k, v) in enumerate(pairs):
        col = i % 2
        row = i // 2
        x = L + col * col_w
        yy = y - row * row_h
        c.setFont(_f(True), 7.5); c.setFillColor(_hx(MUTED))
        c.drawString(x + 4, yy - 11, k.upper())
        c.setFont(_f(), 9); c.setFillColor(_hx(INK))
        c.drawString(x + 96, yy - 11, _clip(c, str(v), _f(), 9, col_w - 102))
    y = y - ((len(pairs) + 1) // 2) * row_h - 12

    # --- maintenance history ---
    y = _section(c, y, "Maintenance history")
    cols = [("Date", 0), ("Type", 56), ("Complaint / task", 118), ("Action", 248),
            ("Downtime", 356), ("Cost \u20b9", 412), ("Attended", 466)]
    y = _thead(c, y, cols)
    c.setFont(_f(), 8)
    for i, e in enumerate(events):
        rh = 15
        if y - rh < 60:
            _footer(c, code, "—"); c.showPage()
            y = _header(c, "Metfraa / Maintenance", "Machine History Card (cont.)", code)
            y = _thead(c, y, cols)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(), 8)
        c.drawString(L + 6, y - 11, e.get("event_date") or "")
        cat = e.get("category", "")
        c.setFillColor(_hx(RED) if cat == "Breakdown" else _hx(BLUE))
        c.drawString(L + 56, y - 11, _clip(c, cat, _f(), 8, 60))
        c.setFillColor(_hx(INK))
        c.drawString(L + 118, y - 11, _clip(c, e.get("complaint") or "", _f(), 8, 126))
        c.drawString(L + 248, y - 11, _clip(c, e.get("action") or "", _f(), 8, 104))
        c.drawString(L + 356, y - 11, f'{e["downtime_hrs"]}h' if e.get("downtime_hrs") is not None else "\u2014")
        c.drawString(L + 412, y - 11, "\u20b9" + _fmt(e["cost"], 0) if e.get("cost") is not None else "\u2014")
        c.drawString(L + 466, y - 11, _clip(c, e.get("attended_by_name") or "", _f(), 8, R - L - 472))
        y -= rh
    if not events:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9)
        c.drawString(L + 6, y - 14, "No maintenance events recorded yet."); y -= 20

    # --- summary ---
    y -= 6
    tot_dt = sum(e.get("downtime_hrs") or 0 for e in events if e.get("category") == "Breakdown")
    tot_cost = sum(e.get("cost") or 0 for e in events)
    c.setFont(_f(True), 9); c.setFillColor(_hx(INK))
    c.drawString(L + 6, y - 12, f"{len(events)} events   ·   total downtime {round(tot_dt, 1)}h   ·   total cost \u20b9{_fmt(tot_cost, 0)}")
    _footer(c, code, "1")
    c.showPage(); c.save()
    return buf.getvalue()


def build_breakdown_register(rows: list, range_label: str) -> bytes:
    _ensure()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    y = _header(c, "Metfraa / Maintenance", "Breakdown Register", range_label)
    cols = [("Date", 0), ("Asset", 52), ("Complaint", 108), ("Cause", 218),
            ("Downtime", 330), ("Cost \u20b9", 388), ("Status", 446)]
    y = _thead(c, y, cols)
    c.setFont(_f(), 8)
    tot_dt = 0.0
    tot_cost = 0.0
    for i, e in enumerate(rows):
        rh = 15
        if y - rh < 60:
            _footer(c, range_label, "—"); c.showPage()
            y = _header(c, "Metfraa / Maintenance", "Breakdown Register (cont.)", range_label)
            y = _thead(c, y, cols)
        if i % 2 == 0:
            c.setFillColor(_hx(SOFT)); c.rect(L, y - rh, R - L, rh, fill=1, stroke=0)
        c.setFillColor(_hx(INK)); c.setFont(_f(), 8)
        c.drawString(L + 6, y - 11, e.get("event_date") or "")
        c.drawString(L + 52, y - 11, _clip(c, e.get("asset_code") or "", _f(), 8, 54))
        c.drawString(L + 108, y - 11, _clip(c, e.get("complaint") or "", _f(), 8, 106))
        c.drawString(L + 218, y - 11, _clip(c, e.get("cause") or "", _f(), 8, 106))
        c.drawString(L + 330, y - 11, f'{e["downtime_hrs"]}h' if e.get("downtime_hrs") is not None else "\u2014")
        c.drawString(L + 388, y - 11, "\u20b9" + _fmt(e["cost"], 0) if e.get("cost") is not None else "\u2014")
        st = e.get("status") or "Open"
        c.setFillColor(_hx(GREEN) if st == "Closed" else _hx(RED))
        c.drawString(L + 446, y - 11, st)
        c.setFillColor(_hx(INK))
        tot_dt += e.get("downtime_hrs") or 0
        tot_cost += e.get("cost") or 0
        y -= rh
    if not rows:
        c.setFillColor(_hx(MUTED)); c.setFont(_f(), 9)
        c.drawString(L + 6, y - 14, "No breakdowns in this range."); y -= 20
    y -= 6
    c.setFont(_f(True), 9); c.setFillColor(_hx(INK))
    c.drawString(L + 6, y - 12, f"{len(rows)} breakdowns   ·   total downtime {round(tot_dt, 1)}h   ·   total cost \u20b9{_fmt(tot_cost, 0)}")
    _footer(c, range_label, "1")
    c.showPage(); c.save()
    return buf.getvalue()
