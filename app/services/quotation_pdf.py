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
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=16 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"Quotation {q.quote_no or ''}")
    ss = getSampleStyleSheet()
    W = 180 * mm  # content width

    small = ParagraphStyle("sm", parent=ss["Normal"], fontSize=8, textColor=GRAY, leading=12)
    val = ParagraphStyle("val", parent=ss["Normal"], fontSize=9, textColor=INK, leading=13)
    valr = ParagraphStyle("valr", parent=val, alignment=TA_RIGHT)
    val_b = ParagraphStyle("valb", parent=val, fontName="Helvetica-Bold")
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, textColor=INK, leading=12)
    cellr = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)

    # white-on-navy title band styles
    qt = ParagraphStyle("qt", parent=ss["Normal"], fontName="Times-Bold", fontSize=27,
                        textColor=colors.white, leading=29)
    band_lbl = ParagraphStyle("bl", parent=ss["Normal"], fontName="Helvetica", fontSize=7,
                              textColor=colors.HexColor("#AFC0DC"), leading=11, alignment=TA_RIGHT)
    band_val = ParagraphStyle("bv", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9,
                              textColor=colors.white, leading=11, alignment=TA_RIGHT)
    # card label (gold eyebrow)
    card_lbl = ParagraphStyle("cl", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=7.5,
                              textColor=GOLD, leading=11)
    company_st = ParagraphStyle("co", parent=val, fontName="Times-Bold", fontSize=13, leading=16,
                                textColor=NAVY)
    # items header (white on navy)
    hcell = ParagraphStyle("hcell", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=8,
                           textColor=colors.white, leading=11)
    hcellr = ParagraphStyle("hcellr", parent=hcell, alignment=TA_RIGHT)

    def _tag(txt):
        return Paragraph(txt, card_lbl)

    el = []

    def _img(path, w, h):
        if path.exists():
            try:
                return Image(str(path), width=w, height=h, kind="proportional")
            except Exception:
                return ""
        return ""

    # ---- masthead: Metfraa (left) + Bharat Steel Group (right)
    metfraa_cell = _img(_METFRAA_LOGO, 52 * mm, 15 * mm)
    group_cell = _img(_LOGO, 42 * mm, 12 * mm)
    head = Table([[metfraa_cell, group_cell]], colWidths=[108 * mm, 72 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (0, 0), (0, 0), "LEFT"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(head)
    el.append(Spacer(1, 14))

    # ---- solid navy title band: "QUOTATION" left, meta grid right (no dead space)
    mini = Table([
        [Paragraph("QUOTATION NO.", band_lbl), Paragraph(q.quote_no or "-", band_val)],
        [Paragraph("DATE", band_lbl), Paragraph(_d(q.date), band_val)],
        [Paragraph("VALID UNTIL", band_lbl), Paragraph(_d(q.valid_until), band_val)],
    ], colWidths=[32 * mm, 35 * mm])
    mini.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    band = Table([[Paragraph("QUOTATION", qt), mini]], colWidths=[105 * mm, 75 * mm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 14),
                              ("RIGHTPADDING", (-1, 0), (-1, 0), 14),
                              ("TOPPADDING", (0, 0), (-1, -1), 10),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                              ("LINEBELOW", (0, 0), (-1, -1), 1.6, GOLD)]))
    el.append(band)
    el.append(Spacer(1, 14))

    # ---- paired cards: BILL TO (left) + details (right)
    bill = [_tag("BILL TO"),
            Paragraph(q.customer_company or q.customer_name or "-", company_st)]
    line2 = []
    if q.customer_name and q.customer_company:
        line2.append("Attn: " + q.customer_name)
    if q.customer_address:
        line2.append(q.customer_address.replace("\n", ", "))
    if q.customer_contact:
        line2.append("Contact: " + q.customer_contact)
    if line2:
        bill.append(Spacer(1, 1))
        bill.append(Paragraph("<br/>".join(line2), val))

    det = []
    if q.project:
        det += [_tag("PROJECT"), Paragraph(q.project, val_b), Spacer(1, 6)]
    det += [_tag("PREPARED BY"), Paragraph(q.created_by or "-", val)]
    if GSTIN:
        det += [Spacer(1, 6), _tag("GSTIN"), Paragraph(GSTIN, val)]

    cards = Table([[bill, "", det]], colWidths=[104 * mm, 4 * mm, 72 * mm])
    cards.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), PANEL), ("BACKGROUND", (2, 0), (2, 0), PANEL),
        ("BOX", (0, 0), (0, 0), 0.5, LINE), ("BOX", (2, 0), (2, 0), 0.5, LINE),
        ("LINEABOVE", (0, 0), (0, 0), 2, GOLD), ("LINEABOVE", (2, 0), (2, 0), 2, GOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (0, 0), 10), ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (2, 0), (2, 0), 10), ("RIGHTPADDING", (2, 0), (2, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
    ]))
    el.append(cards)
    el.append(Spacer(1, 16))

    # ---- items table (navy filled header, subtle zebra, boxed)
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
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 7), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROWALT]),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, GOLD),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, LINE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 14))

    # ---- amount in words (left) + totals card (right, shaded, navy TOTAL row)
    words_block = [_tag("AMOUNT IN WORDS"),
                   Paragraph(_amount_in_words(q.total),
                             ParagraphStyle("ww", parent=val, fontName="Times-BoldItalic",
                                            fontSize=10.5, leading=15, textColor=NAVY))]
    tot_rows = [[Paragraph("Subtotal", val), Paragraph(_inr(q.subtotal), valr)]]
    if (q.discount or 0):
        tot_rows.append([Paragraph("Discount", val), Paragraph("- " + _inr(q.discount), valr)])
    tot_rows.append([Paragraph(f"GST ({(q.gst_pct or 0):g}%)", val), Paragraph(_inr(q.gst_amount), valr)])
    tot_lbl = ParagraphStyle("tl", parent=val, fontName="Helvetica-Bold", fontSize=11,
                             textColor=colors.white)
    tot_val = ParagraphStyle("tv", parent=valr, fontName="Helvetica-Bold", fontSize=11,
                             textColor=colors.white)
    tot_rows.append([Paragraph("TOTAL", tot_lbl), Paragraph(_inr(q.total), tot_val)])
    totals = Table(tot_rows, colWidths=[40 * mm, 38 * mm])
    nrows = len(tot_rows)
    totals.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -2), 5), ("BOTTOMPADDING", (0, 0), (-1, -2), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
        ("BACKGROUND", (0, nrows - 1), (-1, nrows - 1), NAVY),
        ("TOPPADDING", (0, -1), (-1, -1), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, GOLD),
    ]))
    tot_card = Table([[totals]], colWidths=[78 * mm])
    tot_card.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), PANEL),
                                  ("BOX", (0, 0), (0, 0), 0.5, LINE),
                                  ("TOPPADDING", (0, 0), (-1, -1), 0),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(Table([[words_block, tot_card]], colWidths=[100 * mm, 80 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("LEFTPADDING", (0, 0), (0, 0), 0),
                                      ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                                      ("ALIGN", (1, 0), (1, 0), "RIGHT")])))
    el.append(Spacer(1, 18))

    # ---- terms + signature side by side
    terms_block = [_tag("TERMS & CONDITIONS")]
    if q.terms:
        for ln in str(q.terms).split("\n"):
            ln = ln.strip()
            if ln:
                terms_block.append(Paragraph('<font color="#B08D57">•</font>&nbsp; ' + ln, small))
    sign_block = [Paragraph("For", small),
                  Paragraph(GROUP, ParagraphStyle("g", parent=val, fontName="Times-Bold",
                            fontSize=11, textColor=NAVY, leading=14)),
                  Spacer(1, 28),
                  Table([[""]], colWidths=[50 * mm],
                        style=TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.6, LINE)])),
                  Paragraph("Authorised Signatory", small)]
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
