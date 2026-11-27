"""Metfraa-branded quotation PDF (reportlab / platypus).

build_quotation_pdf(q) -> bytes, where q is a CrmQuotation ORM object.
Header company details are overridable via env so finance can tune them
without a code change.
"""
import io
import os
import pathlib

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

NAVY = colors.HexColor("#0A2B66")
BLUE = colors.HexColor("#01578C")
INK = colors.HexColor("#1E1D1D")
GRAY = colors.HexColor("#64748B")
LIGHT = colors.HexColor("#F1F5F9")
LINE = colors.HexColor("#CBD5E1")

_IMG = pathlib.Path(__file__).resolve().parent.parent / "static" / "img"
_LOGO = _IMG / "bsg_group_logo.png"              # group logo (header left)
_METFRAA_LOGO = _IMG / "metfraa_logo.png"        # company logo (header right)

# Entity the quotation is signed by (header shows the group logo instead of
# the company name).
GROUP = os.getenv("QUOTE_GROUP_NAME", "The Bharat Steel Group")
COMPANY = os.getenv("METFRAA_QUOTE_COMPANY", "Metfraa Steel Buildings Pvt. Ltd.")
TAGLINE = os.getenv("METFRAA_QUOTE_TAGLINE", "Steeling the Future")
ADDRESS = os.getenv("METFRAA_QUOTE_ADDRESS", "")
PHONE = os.getenv("METFRAA_QUOTE_PHONE", "98840 42222")
EMAIL = os.getenv("METFRAA_QUOTE_EMAIL", "info@metfraa.com")
WEB = os.getenv("METFRAA_QUOTE_WEB", "www.metfraa.com")
GSTIN = os.getenv("METFRAA_QUOTE_GSTIN", "")


def _inr(v):
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        n = 0.0
    s = f"{abs(n):,.2f}"
    return ("-" if n < 0 else "") + "Rs. " + s


def _qty(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    return str(int(n)) if n == int(n) else f"{n:g}"


def _d(v):
    return v.strftime("%d-%m-%Y") if v else "-"


def build_quotation_pdf(q) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=16 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"Quotation {q.quote_no or ''}")
    ss = getSampleStyleSheet()
    h_name = ParagraphStyle("hn", parent=ss["Normal"], fontName="Helvetica-Bold",
                            fontSize=15, textColor=NAVY, leading=18)
    h_tag = ParagraphStyle("ht", parent=ss["Normal"], fontName="Helvetica-Oblique",
                           fontSize=8.5, textColor=BLUE, leading=11)
    small = ParagraphStyle("sm", parent=ss["Normal"], fontSize=8, textColor=GRAY, leading=11)
    smallr = ParagraphStyle("smr", parent=small, alignment=TA_RIGHT)
    body = ParagraphStyle("bd", parent=ss["Normal"], fontSize=9, textColor=INK, leading=13)
    body_b = ParagraphStyle("bdb", parent=body, fontName="Helvetica-Bold")
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, textColor=INK, leading=12)
    cellr = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)
    title = ParagraphStyle("title", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=13, textColor=colors.white, alignment=TA_CENTER, leading=16)

    el = []

    # ---- header: group logo (left) | Metfraa logo (right), no words
    def _img(path, w, h):
        if path.exists():
            try:
                return Image(str(path), width=w, height=h, kind="proportional")
            except Exception:
                return ""
        return ""

    # Same box height for both so the two logos render at an equal size.
    group_cell = _img(_LOGO, 66 * mm, 18 * mm)
    metfraa_cell = _img(_METFRAA_LOGO, 66 * mm, 18 * mm)
    head_title = ParagraphStyle("htitle", parent=ss["Normal"], fontName="Helvetica-Bold",
                                fontSize=22, textColor=NAVY, alignment=TA_CENTER, leading=26)

    head = Table([[group_cell, Paragraph("QUOTATION", head_title), metfraa_cell]],
                 colWidths=[66 * mm, 48 * mm, 66 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (0, 0), (0, 0), "LEFT"),
                              ("ALIGN", (1, 0), (1, 0), "CENTER"),
                              ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(head)
    el.append(Spacer(1, 6))
    el.append(Table([[""]], colWidths=[180 * mm],
                    style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.3, NAVY)])))
    el.append(Spacer(1, 10))

    # ---- customer + meta two columns
    cust = [Paragraph("TO", small),
            Paragraph(q.customer_company or q.customer_name or "-", body_b)]
    if q.customer_name and q.customer_company:
        cust.append(Paragraph("Attn: " + q.customer_name, body))
    if q.customer_address:
        cust.append(Paragraph(q.customer_address.replace("\n", "<br/>"), body))
    if q.customer_contact:
        cust.append(Paragraph(q.customer_contact, body))
    if q.project:
        cust.append(Spacer(1, 3))
        cust.append(Paragraph("<b>Project:</b> " + q.project, body))

    metatbl = Table([
        [Paragraph("Quotation No.", small), Paragraph(q.quote_no or "-", body_b)],
        [Paragraph("Date", small), Paragraph(_d(q.date), body)],
        [Paragraph("Valid until", small), Paragraph(_d(q.valid_until), body)],
        [Paragraph("Prepared by", small), Paragraph(q.created_by or "-", body)],
    ], colWidths=[26 * mm, 42 * mm])
    metatbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 1),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    top = Table([[cust, metatbl]], colWidths=[112 * mm, 68 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el.append(top)
    el.append(Spacer(1, 10))

    # ---- items table
    header = ["#", "Description", "Qty", "Unit", "Rate", "Amount"]
    data = [[Paragraph(f"<font color='white'><b>{h}</b></font>",
                       ParagraphStyle("h", parent=cell,
                                      alignment=TA_RIGHT if h in ("Qty", "Rate", "Amount") else TA_LEFT))]
            for h in header]
    data = [data[i][0] for i in range(len(header))]
    rows = [data]
    for n, it in enumerate(q.items or [], 1):
        rows.append([
            Paragraph(str(it.get("sn") or n), cell),
            Paragraph(str(it.get("description") or ""), cell),
            Paragraph(_qty(it.get("qty")), cellr),
            Paragraph(str(it.get("unit") or ""), cell),
            Paragraph(_inr(it.get("rate")) if it.get("rate") not in (None, "") else "", cellr),
            Paragraph(_inr(it.get("amount")) if it.get("amount") not in (None, "") else "", cellr),
        ])
    if not (q.items or []):
        rows.append([Paragraph("-", cell)] + [Paragraph("", cell) for _ in range(5)])

    tbl = Table(rows, colWidths=[8 * mm, 78 * mm, 14 * mm, 14 * mm, 30 * mm, 36 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 6))

    # ---- totals
    tot_rows = [["Subtotal", _inr(q.subtotal)]]
    if (q.discount or 0):
        tot_rows.append(["Discount", "- " + _inr(q.discount)])
    tot_rows.append([f"GST ({(q.gst_pct or 0):g}%)", _inr(q.gst_amount)])
    tot_rows.append(["Total", _inr(q.total)])
    totals = Table([[Paragraph(a, body if a != "Total" else body_b),
                     Paragraph(b, cellr if a != "Total" else ParagraphStyle("tb", parent=cellr, fontName="Helvetica-Bold"))]
                    for a, b in tot_rows], colWidths=[30 * mm, 38 * mm])
    totals.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1, NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
    ]))
    el.append(Table([["", totals]], colWidths=[112 * mm, 68 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    el.append(Spacer(1, 12))

    # ---- terms
    if q.terms:
        el.append(Paragraph("Terms &amp; Conditions", body_b))
        el.append(Spacer(1, 2))
        for line in str(q.terms).split("\n"):
            line = line.strip()
            if line:
                el.append(Paragraph("• " + line, small))
    el.append(Spacer(1, 16))

    # ---- signature
    sign = Table([[Paragraph("For <b>" + GROUP + "</b>", body)],
                  [Spacer(1, 22)],
                  [Paragraph("Authorised Signatory", small)]], colWidths=[70 * mm])
    el.append(Table([["", sign]], colWidths=[110 * mm, 70 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 0)])))

    def _footer(canvas, docu):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(15 * mm, 12 * mm, 195 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRAY)
        canvas.drawString(15 * mm, 8 * mm, f"{EMAIL}  ·  {WEB}")
        canvas.drawRightString(195 * mm, 8 * mm, f"Page {docu.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
