"""Expense OneDrive artifacts — approval PDF + per-form master log.

Root folder defaults to "Reimbursements and Conveyance" (the existing expense
folder in info@metfraa.com's drive); override with EXPENSE_ONEDRIVE_ROOT.

Layout:
  <root>/<YYYY-MM>/<reference>/Bills/…           (bills, uploaded at submit)
  <root>/<YYYY-MM>/<reference>/<reference>.pdf   (approval report)
  <root>/_MasterLog_<FORM>.xlsx                  (one log per form type)
"""
import io
import logging
import os

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import onedrive

log = logging.getLogger(__name__)

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BRAND = colors.HexColor("#005B96")
LIGHT = colors.HexColor("#eef2f6")

S_TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, textColor=colors.white)
S_SUB = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#cfe3f2"))
S_SEC = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=11, textColor=BRAND, spaceBefore=8, spaceAfter=4)
S_L = ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.HexColor("#6b7480"))
S_V = ParagraphStyle("v", fontName="Helvetica", fontSize=9.5, textColor=colors.HexColor("#1a2332"))
S_C = ParagraphStyle("c", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#1a2332"))
S_SM = ParagraphStyle("sm", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#6b7480"))


def expense_root() -> str:
    return os.getenv("EXPENSE_ONEDRIVE_ROOT", "Reimbursements and Conveyance").strip("/")


def submission_folder(sub) -> str:
    return f"{expense_root()}/{sub.period or 'no-period'}/{sub.reference}"


# ------------------------------------------------------------------ PDF

def _kv(label, value, width):
    return Table([[Paragraph(label, S_L), Paragraph(str(value) if value not in (None, "") else "—", S_V)]],
                 colWidths=[width * 0.32, width * 0.68],
                 style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde3ea")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))


def _rows_table(headers, rows, width, weights):
    data = [[Paragraph(f"<b>{h}</b>", S_C) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c) if c not in (None, "") else "—", S_C) for c in r])
    return Table(data, colWidths=[width * w for w in weights], repeatRows=1,
                 style=TableStyle([
                     ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                     ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                     ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3dd")),
                     ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                     ("TOPPADDING", (0, 0), (-1, -1), 3),
                     ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                 ]))


def _payload_elements(form_type: str, p: dict, width) -> list:
    E = []
    inr = "₹{:,.2f}".format
    if form_type == "met_local":
        E.append(_kv("Vehicle", f"{p.get('vehicle_label')} @ ₹{p.get('rate_per_km')}/km  {p.get('vehicle_reg', '')}", width))
        E.append(Spacer(1, 4))
        E.append(_rows_table(["Date", "From", "To", "Purpose", "KM", "Amount"],
                             [[t["date"], t["from"], t["to"], t.get("purpose", ""), f"{t['km']:g}", inr(t["amount"])] for t in p.get("trips", [])],
                             width, (0.13, 0.2, 0.2, 0.25, 0.08, 0.14)))
    elif form_type == "met_cab":
        E.append(_rows_table(["Date", "Pickup", "Drop", "KM", "Fare", "Purpose"],
                             [[r["date"], r["pickup"], r["drop"], f"{r['km']:g}", inr(r["fare"]), r.get("purpose", "")] for r in p.get("rides", [])],
                             width, (0.12, 0.2, 0.2, 0.08, 0.14, 0.26)))
    elif form_type == "met_accommodation":
        E.append(_kv("Level / Daily limit", f"{p.get('level')} — ₹{p.get('daily_limit')}/day", width))
        E.append(Spacer(1, 4))
        E.append(_rows_table(["Date", "Location", "Hotel", "Bill No.", "Amount"],
                             [[e["date"], e["location"], e.get("hotel", ""), e.get("bill_no", ""), inr(e["amount"])] for e in p.get("entries", [])],
                             width, (0.14, 0.24, 0.26, 0.16, 0.2)))
    elif form_type == "met_outstation":
        for t in p.get("trips", []):
            E.append(_kv("Trip", f"{t['place']}  ({t['from_date']} → {t['to_date']}) — {t['purpose']}", width))
            rows = []
            for cat, items in (t.get("categories") or {}).items():
                for it in items:
                    rows.append([it["date"], cat.replace("_", " ").title(), it.get("desc", ""), inr(it["amount"])])
            if rows:
                E.append(Spacer(1, 3))
                E.append(_rows_table(["Date", "Category", "Description", "Amount"], rows,
                                     width, (0.14, 0.2, 0.44, 0.22)))
            E.append(Spacer(1, 5))
    elif form_type == "met_misc":
        E.append(_rows_table(["Date", "Purpose", "Amount"],
                             [[i["date"], i["purpose"], inr(i["amount"])] for i in p.get("items", [])],
                             width, (0.16, 0.6, 0.24)))
    elif form_type == "met_advance":
        for k, label in [("destination", "Destination"), ("travel_from", "Travel From"),
                         ("travel_to", "Travel To"), ("purpose", "Purpose"),
                         ("mode", "Mode"), ("notes", "Notes"), ("amount", "Advance Amount (₹)")]:
            E.append(_kv(label, p.get(k), width))
    elif form_type == "met_dtr":
        E.append(_rows_table(["Date", "Mode", "From", "To", "Purpose", "Fare"],
                             [[e["date"], e["mode"].replace("_", " ").title(), e["from"], e["to"],
                               (e.get("client_name") or e.get("purpose_other_reason") or e["purpose_category"].replace("_", " ").title()),
                               inr(e["fare"])] for e in p.get("entries", [])],
                             width, (0.12, 0.12, 0.18, 0.18, 0.26, 0.14)))
    return E


def generate_expense_pdf(sub, form_title: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=sub.reference)
    W = doc.width
    E = [Table([[Paragraph("METFRAA — Expense Report", S_TITLE)],
                [Paragraph(f"{form_title} · {sub.reference}", S_SUB)]],
               colWidths=[W],
               style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                 ("TOPPADDING", (0, 0), (0, 0), 8),
                                 ("BOTTOMPADDING", (0, 1), (0, 1), 8)])),
         Spacer(1, 6),
         _kv("Employee", f"{sub.employee_name}  ({sub.employee_email or ''})", W),
         _kv("Period", sub.period or "—", W),
         _kv("Submitted (IST)", sub.submitted_at_ist, W),
         _kv("Total Claimed", "₹{:,.2f}".format(sub.total_amount), W),
         Spacer(1, 4),
         Paragraph("Details", S_SEC)]
    E += _payload_elements(sub.form_type, sub.payload or {}, W)
    E.append(Spacer(1, 8))
    status_label = "APPROVED" if sub.status in ("approved", "advance_approved", "settled") else sub.status.upper()
    E.append(Table([[Paragraph(status_label, ParagraphStyle("ap", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white)),
                     Paragraph(f"Reviewed by <b>{sub.reviewed_by or ''}</b> at {sub.reviewed_at_ist or ''} IST"
                               + (f"<br/>Note: {sub.review_note}" if sub.review_note else ""), S_V)]],
                   colWidths=[W * 0.2, W * 0.8],
                   style=TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#1F8B4C")),
                                     ("BACKGROUND", (1, 0), (1, -1), LIGHT),
                                     ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                     ("TOPPADDING", (0, 0), (-1, -1), 6),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8)])))
    E.append(Spacer(1, 6))
    E.append(Paragraph(f"Generated by Metfraa Portal · {sub.reference}", S_SM))
    doc.build(E)
    return buf.getvalue()


# ------------------------------------------------------------------ master log

LOG_HEADERS = ["Reference", "Employee", "Email", "Level", "Period", "Submitted At",
               "Total (₹)", "Status", "Reviewed By", "Reviewed At", "Note / Changes Required",
               "Bills", "PDF Report (link)"]


def append_expense_log(sub, form_code: str, bill_links: list[str], pdf_link: str | None) -> None:
    path = f"{expense_root()}/_MasterLog_{form_code}.xlsx"
    existing = onedrive.download_from_path(path)
    if existing:
        wb = load_workbook(io.BytesIO(existing))
        ws = wb["Submissions"] if "Submissions" in wb.sheetnames else wb.create_sheet("Submissions")
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Submissions"
        ws.append(LOG_HEADERS)
        fill = PatternFill("solid", fgColor="005B96")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF", size=11)
            c.fill = fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        for idx, h in enumerate(LOG_HEADERS, start=1):
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(max(len(h) + 4, 14), 50)
    ws.append([sub.reference, sub.employee_name, sub.employee_email or "", sub.employee_level or "",
               sub.period or "", sub.submitted_at_ist, sub.total_amount,
               sub.status, sub.reviewed_by or "", sub.reviewed_at_ist or "",
               sub.review_note or sub.changes_required or "",
               ", ".join(bill_links) if bill_links else "", pdf_link or ""])
    status_cell = ws.cell(row=ws.max_row, column=8)
    approvedish = sub.status in ("approved", "advance_approved", "settled")
    status_cell.font = Font(bold=True, color="FFFFFF")
    status_cell.fill = PatternFill("solid", fgColor="1F8B4C" if approvedish else ("C0392B" if sub.status == "rejected" else "B7791F"))
    buf = io.BytesIO()
    wb.save(buf)
    onedrive.upload_to_path(buf.getvalue(), path, XLSX_CT)
    log.info(f"[expense-log] appended {sub.reference} to {path}")
