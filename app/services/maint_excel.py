"""Metfraa maintenance Excel log — generated from the app's data, styled like the
BSC maintenance workbook: a master LOG, a DASHBOARD of KPIs, and one History Card
sheet per machine *family* (fleet tools grouped — ARC WELDING, AG-7 GRINDER, …).
Only families that have at least one logged event get a card."""
import io
import re
from collections import OrderedDict, defaultdict
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "FF0D1421"
BLUE = "FF1F7CCB"
HDR = "FFEEF2F7"
LINE = "FFD6DDE6"
MUTE = "FF6B7689"
_thin = Side(style="thin", color=LINE)
BORD = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def family_of(desc: str) -> str:
    """Fleet tools are 'FAMILY- NN'; strip the trailing number to get the family.
    One-offs (CNC PLASMA, SCREW COMPRESSOR, …) keep their full name."""
    f = re.sub(r"\s*-\s*0*\d+\s*$", "", (desc or "").strip())
    f = re.sub(r"\s+", " ", f).strip().upper().replace("CUTT OFF", "CUT OFF")
    return f or (desc or "").strip().upper() or "UNSPECIFIED"


def _bar(ws, row, text, span, color):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    c = ws.cell(row, 1, text)
    c.font = Font(bold=True, color="FFFFFFFF", size=12 if color == NAVY else 10)
    c.alignment = Alignment(horizontal="left", vertical="center")
    for col in range(1, span + 1):
        ws.cell(row, col).fill = PatternFill("solid", fgColor=color)
    ws.row_dimensions[row].height = 24 if color == NAVY else 18


def _head(ws, row, headers):
    for i, h in enumerate(headers, 1):
        c = ws.cell(row, i, h)
        c.font = Font(bold=True, size=9)
        c.fill = PatternFill("solid", fgColor=HDR)
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        c.border = BORD


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def build_maintenance_log_xlsx(db) -> bytes:
    from ..models import MaintAsset, MaintEvent
    assets = {a.id: a for a in db.query(MaintAsset).all()}
    events = db.query(MaintEvent).all()
    events.sort(key=lambda e: (e.event_date or date.min, e.id))

    def fam(e):
        a = assets.get(e.asset_id)
        return family_of(a.description if a else "")

    def code(e):
        a = assets.get(e.asset_id)
        return a.asset_code if a else "?"

    def mname(e):
        a = assets.get(e.asset_id)
        return a.description if a else ""

    # per-family stats
    stats = defaultdict(lambda: dict(jobs=0, bd=0, bdhrs=0.0, pm=0, dt=0.0, cost=0.0, last=None))
    for e in events:
        s = stats[fam(e)]
        s["jobs"] += 1
        if e.category == "Breakdown":
            s["bd"] += 1
            s["bdhrs"] += e.downtime_hrs or 0
        else:
            s["pm"] += 1
        s["dt"] += e.downtime_hrs or 0
        s["cost"] += e.cost or 0
        if e.event_date and (s["last"] is None or e.event_date > s["last"]):
            s["last"] = e.event_date

    bd = [e for e in events if e.category == "Breakdown"]
    pm = [e for e in events if e.category in ("Scheduled PM", "Unscheduled PM")]
    total_dt = round(sum(e.downtime_hrs or 0 for e in bd), 2)
    total_cost = round(sum(e.cost or 0 for e in events), 0)
    worst = max(stats.items(), key=lambda kv: kv[1]["dt"], default=(None, None))[0]

    wb = openpyxl.Workbook()

    # ---------------- DASHBOARD ----------------
    ws = wb.active
    ws.title = "DASHBOARD"
    _bar(ws, 1, "METFRAA  —  MAINTENANCE DASHBOARD", 7, NAVY)
    ws.cell(2, 1, "Generated from the Metfraa portal  ·  " + date.today().isoformat()).font = Font(italic=True, color=MUTE, size=9)
    kpis = [("TOTAL JOBS", len(events)), ("BREAKDOWNS", len(bd)), ("B/D HOURS", total_dt),
            ("PM JOBS", len(pm)), ("DOWNTIME HRS", total_dt), ("TOTAL COST", total_cost),
            ("WORST (downtime)", worst or "-")]
    for i, (k, v) in enumerate(kpis, 1):
        ws.cell(4, i, k).font = Font(bold=True, size=8, color=MUTE)
        ws.cell(5, i, v).font = Font(bold=True, size=12)
    _bar(ws, 7, "BY MACHINE FAMILY", 7, BLUE)
    _head(ws, 8, ["FAMILY", "JOBS", "BREAKDOWNS", "B/D HRS", "PM JOBS", "DOWNTIME HRS", "COST"])
    rr = 9
    for fn, s in sorted(stats.items(), key=lambda kv: -kv[1]["dt"]):
        vals = [fn, s["jobs"], s["bd"], round(s["bdhrs"], 2), s["pm"], round(s["dt"], 2), round(s["cost"], 0)]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(rr, ci, v)
            c.border = BORD
        ws.cell(rr, 7).number_format = "#,##0"
        rr += 1
    rr += 1
    mon = OrderedDict()
    for e in events:
        if not e.event_date:
            continue
        m = mon.setdefault(e.event_date.strftime("%b-%y"), dict(jobs=0, bd=0, bdhrs=0.0, dt=0.0))
        m["jobs"] += 1
        if e.category == "Breakdown":
            m["bd"] += 1
            m["bdhrs"] += e.downtime_hrs or 0
        m["dt"] += e.downtime_hrs or 0
    _bar(ws, rr, "BY MONTH", 5, BLUE)
    _head(ws, rr + 1, ["MONTH", "JOBS", "BREAKDOWNS", "B/D HRS", "DOWNTIME HRS"])
    rr += 2
    for k, m in mon.items():
        for ci, v in enumerate([k, m["jobs"], m["bd"], round(m["bdhrs"], 2), round(m["dt"], 2)], 1):
            ws.cell(rr, ci, v).border = BORD
        rr += 1
    _widths(ws, [26, 10, 14, 10, 10, 14, 12])
    ws.freeze_panes = "A4"

    # ---------------- LOG ----------------
    ws = wb.create_sheet("LOG")
    _bar(ws, 1, "MASTER MAINTENANCE LOG  —  one row per job", 13, NAVY)
    heads = ["SI", "DATE", "MAC NO", "MACHINE", "FAMILY", "CATEGORY", "STATUS",
             "PROBLEM / TASK", "CAUSE", "ACTION TAKEN", "ATTENDED BY", "DOWNTIME HRS", "COST"]
    _head(ws, 2, heads)
    for i, e in enumerate(events, 1):
        row = i + 2
        vals = [i, e.event_date.isoformat() if e.event_date else "", code(e), mname(e), fam(e),
                e.category, e.status or "", e.complaint or "", e.cause or "", e.action or "",
                (e.attended_by.name if e.attended_by else ""),
                e.downtime_hrs if e.downtime_hrs is not None else "",
                e.cost if e.cost is not None else ""]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(row, ci, v)
            c.border = BORD
            c.alignment = Alignment(vertical="top", wrap_text=ci in (8, 9, 10))
        ws.cell(row, 12).number_format = "0.00"
        ws.cell(row, 13).number_format = "#,##0"
    _widths(ws, [5, 12, 10, 22, 20, 16, 11, 34, 26, 30, 16, 12, 10])
    ws.freeze_panes = "A3"

    # ---------------- family history cards ----------------
    used = set()
    for fn in sorted(stats.keys()):
        fevents = [e for e in events if fam(e) == fn]
        nm = re.sub(r"[\\/*?:\[\]]", "-", fn)[:31] or "CARD"
        base, k = nm, 1
        while nm.lower() in used:
            k += 1
            nm = (base[:28] + f"-{k}")
        used.add(nm.lower())
        ws = wb.create_sheet(nm)
        _bar(ws, 1, "MACHINE HISTORY CARD  —  " + fn, 9, NAVY)
        codes = ", ".join(sorted({code(e) for e in fevents}))
        ws.cell(2, 1, "Machines in this family: " + codes).font = Font(size=9, color=MUTE)
        s = stats[fn]
        _head(ws, 4, ["TOTAL JOBS", "BREAKDOWNS", "B/D HRS", "PM JOBS", "DOWNTIME HRS", "COST", "LAST JOB"])
        for ci, v in enumerate([s["jobs"], s["bd"], round(s["bdhrs"], 2), s["pm"], round(s["dt"], 2),
                                round(s["cost"], 0), s["last"].isoformat() if s["last"] else "-"], 1):
            ws.cell(5, ci, v).border = BORD
        _head(ws, 7, ["SI", "DATE", "MACHINE", "DETAILS", "CAUSE", "ACTION TAKEN", "DOWNTIME", "STATUS", "CATEGORY"])
        rr = 8
        for i, e in enumerate(fevents, 1):
            vals = [i, e.event_date.isoformat() if e.event_date else "", code(e), e.complaint or "",
                    e.cause or "", e.action or "", e.downtime_hrs if e.downtime_hrs is not None else "",
                    e.status or "", e.category]
            for ci, v in enumerate(vals, 1):
                c = ws.cell(rr, ci, v)
                c.border = BORD
                c.alignment = Alignment(vertical="top", wrap_text=ci in (4, 5, 6))
            ws.cell(rr, 7).number_format = "0.00"
            rr += 1
        _widths(ws, [5, 12, 14, 34, 24, 30, 10, 12, 16])
        ws.freeze_panes = "A8"

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
