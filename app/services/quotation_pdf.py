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
PANEL = colors.HexColor("#EEF3F9")
ROWALT = colors.HexColor("#F7F9FC")
GOLD = colors.HexColor("#B08D57")   # slim premium accent

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


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three(n):
    h = n // 100
    r = n % 100
    out = (_ONES[h] + " Hundred" if h else "")
    if r:
        out = (out + " " + _two(r)).strip()
    return out


def _amount_in_words(amount):
    """Indian-system rupees in words, e.g. 6,499,440 -> 'Rupees Sixty Four
    Lakh Ninety Nine Thousand Four Hundred Forty Only'."""
    try:
        n = int(round(float(amount or 0)))
    except (TypeError, ValueError):
        return ""
    if n == 0:
        return "Rupees Zero Only"
    crore = n // 10000000
    n %= 10000000
    lakh = n // 100000
    n %= 100000
    thousand = n // 1000
    n %= 1000
    parts = []
    if crore:
        parts.append(_two(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return "Rupees " + " ".join(p for p in parts if p).strip() + " Only"


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

    W = 180 * mm  # content width (same layout, elegant/premium styling)

    lbl = ParagraphStyle("lbl", parent=ss["Normal"], fontName="Helvetica", fontSize=7.5,
                         textColor=GRAY, leading=10)
    lblr = ParagraphStyle("lblr", parent=lbl, alignment=TA_RIGHT)
    val = ParagraphStyle("val", parent=ss["Normal"], fontSize=9, textColor=INK, leading=13)
    valr = ParagraphStyle("valr", parent=val, alignment=TA_RIGHT)
    valr_b = ParagraphStyle("valrb", parent=valr, fontName="Helvetica-Bold")
    # serif title + refined small accent tags
    qt = ParagraphStyle("qt", parent=ss["Normal"], fontName="Times-Bold", fontSize=30,
                        textColor=NAVY, leading=32)

    def _tag(txt):
        return Paragraph(txt, ParagraphStyle("tag", parent=ss["Normal"], fontName="Helvetica-Bold",
                                             fontSize=7.5, textColor=GOLD, leading=11))
    hcell = ParagraphStyle("hcell", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=8,
                           textColor=NAVY, leading=11)
    hcellr = ParagraphStyle("hcellr", parent=hcell, alignment=TA_RIGHT)

    el = []

    def _img(path, w, h):
        if path.exists():
            try:
                return Image(str(path), width=w, height=h, kind="proportional")
            except Exception:
                return ""
        return ""

    # ---- masthead: Metfraa (primary, left) + Bharat Steel Group (right)
    metfraa_cell = _img(_METFRAA_LOGO, 54 * mm, 15 * mm)
    group_cell = _img(_LOGO, 44 * mm, 13 * mm)
    head = Table([[metfraa_cell, group_cell]], colWidths=[108 * mm, 72 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (0, 0), (0, 0), "LEFT"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(head)
    el.append(Spacer(1, 16))

    # ---- title + meta, framed by hairlines (no fill), slim gold left accent
    meta = Table([
        [Paragraph("QUOTATION NO.", lblr), Paragraph(q.quote_no or "-", valr_b)],
        [Paragraph("DATE", lblr), Paragraph(_d(q.date), valr)],
        [Paragraph("VALID UNTIL", lblr), Paragraph(_d(q.valid_until), valr)],
        [Paragraph("PREPARED BY", lblr), Paragraph(q.created_by or "-", valr)],
    ], colWidths=[30 * mm, 38 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    panel = Table([[Paragraph("Quotation", qt), meta]], colWidths=[92 * mm, 88 * mm])
    panel.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (0, 0), 10),
                               ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 9),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                               ("LINEBEFORE", (0, 0), (0, 0), 2.2, GOLD),
                               ("LINEABOVE", (0, 0), (-1, 0), 0.6, NAVY),
                               ("LINEBELOW", (0, -1), (-1, -1), 1.2, GOLD)]))
    el.append(panel)
    el.append(Spacer(1, 16))

    # ---- bill to
    bt = [_tag("BILL TO"),
          Paragraph(q.customer_company or q.customer_name or "-",
                    ParagraphStyle("c", parent=val, fontName="Times-Bold", fontSize=13, leading=16,
                                   textColor=NAVY))]
    line2 = []
    if q.customer_name and q.customer_company:
        line2.append("Attn: " + q.customer_name)
    if q.customer_address:
        line2.append(q.customer_address.replace("\n", ", "))
    if q.customer_contact:
        line2.append(q.customer_contact)
    if line2:
        bt.append(Paragraph("<br/>".join(line2), val))
    if q.project:
        bt.append(Spacer(1, 2))
        bt.append(Paragraph('<font color="#64748B">Project:</font> <b>' + q.project + "</b>", val))
    el.append(Table([[bt]], colWidths=[W], style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)])))
    el.append(Spacer(1, 14))

    # ---- items table (white header, hairline separators, no zebra)
    cw = [9 * mm, 85 * mm, 14 * mm, 15 * mm, 27 * mm, 30 * mm]
    rows = [[Paragraph("#", hcell), Paragraph("DESCRIPTION", hcell), Paragraph("QTY", hcellr),
             Paragraph("UNIT", hcell), Paragraph("RATE", hcellr), Paragraph("AMOUNT", hcellr)]]
    items = q.items or []
    for n, it in enumerate(items, 1):
        rows.append([
            Paragraph(str(it.get("sn") or n), cell),
            Paragraph(str(it.get("description") or ""), cell),
            Paragraph(_qty(it.get("qty")), cellr),
            Paragraph(str(it.get("unit") or ""), cell),
            Paragraph(_inr(it.get("rate")) if it.get("rate") not in (None, "") else "", cellr),
            Paragraph(_inr(it.get("amount")) if it.get("amount") not in (None, "") else "", cellr),
        ])
    if not items:
        rows.append([Paragraph("", cell) for _ in range(6)])
    tbl = Table(rows, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, GOLD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, NAVY),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 12))

    # ---- amount in words (left) + totals (right, no fill, gold-ruled total)
    words_block = [_tag("AMOUNT IN WORDS"),
                   Paragraph(_amount_in_words(q.total),
                             ParagraphStyle("ww", parent=val, fontName="Times-Bold",
                                            fontSize=10, leading=14, textColor=NAVY))]
    tot_rows = [[Paragraph("Subtotal", val), Paragraph(_inr(q.subtotal), valr)]]
    if (q.discount or 0):
        tot_rows.append([Paragraph("Discount", val), Paragraph("- " + _inr(q.discount), valr)])
    tot_rows.append([Paragraph(f"GST ({(q.gst_pct or 0):g}%)", val), Paragraph(_inr(q.gst_amount), valr)])
    tot_lbl = ParagraphStyle("tl", parent=val, fontName="Times-Bold", fontSize=11, textColor=NAVY)
    tot_val = ParagraphStyle("tv", parent=valr, fontName="Times-Bold", fontSize=11, textColor=NAVY)
    tot_rows.append([Paragraph("TOTAL", tot_lbl), Paragraph(_inr(q.total), tot_val)])
    totals = Table(tot_rows, colWidths=[36 * mm, 42 * mm])
    totals.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, LINE),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 1.6, GOLD),
        ("TOPPADDING", (0, -1), (-1, -1), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    el.append(Table([[words_block, totals]], colWidths=[102 * mm, 78 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (0, 0), "TOP"),
                                      ("VALIGN", (1, 0), (1, 0), "TOP"),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    el.append(Spacer(1, 18))

    # ---- terms + signature side by side
    terms_block = [_tag("TERMS & CONDITIONS")]
    if q.terms:
        for ln in str(q.terms).split("\n"):
            ln = ln.strip()
            if ln:
                terms_block.append(Paragraph("•&nbsp; " + ln, small))
    sign_block = [Paragraph("For", small),
                  Paragraph(GROUP, ParagraphStyle("g", parent=val, fontName="Times-Bold",
                            fontSize=11, textColor=NAVY, leading=14)),
                  Spacer(1, 26), Paragraph("Authorised Signatory", small)]
    el.append(Table([[terms_block, sign_block]], colWidths=[108 * mm, 72 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (0, 0), "TOP"),
                                      ("VALIGN", (1, 0), (1, 0), "TOP"),
                                      ("ALIGN", (1, 0), (1, 0), "LEFT"),
                                      ("LEFTPADDING", (0, 0), (0, 0), 0),
                                      ("LEFTPADDING", (1, 0), (1, 0), 20)])))

    def _page(canvas, docu):
        canvas.saveState()
        # slim premium top rule: thin navy + gold hairline
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 3 * mm, A4[0], 3 * mm, stroke=0, fill=1)
        canvas.setFillColor(GOLD)
        canvas.rect(0, A4[1] - 3.7 * mm, A4[0], 0.7 * mm, stroke=0, fill=1)
        # footer
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0.6)
        canvas.line(15 * mm, 12 * mm, 195 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRAY)
        canvas.drawString(15 * mm, 8 * mm,
                          "Metfraa Steel Buildings Pvt. Ltd.  ·  A Bharat Steel Group company  ·  " + EMAIL)
        canvas.drawRightString(195 * mm, 8 * mm, f"Page {docu.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=_page, onLaterPages=_page)
    return buf.getvalue()
