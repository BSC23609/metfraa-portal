"""Printable outpass / gatepass PDF.

Ported from BSC's lib/outpass_pdf.js (pdfkit) to reportlab. Same layout: a
header band, the detail fields in two columns, and a green APPROVED band across
the bottom carrying the approver's name and the timestamp — that band is what a
gatekeeper actually looks at, so it stays visually loud.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas

INK = colors.HexColor("#0d1421")
BLUE = colors.HexColor("#1F7CCB")
GREEN = colors.HexColor("#16a34a")
MUTED = colors.HexColor("#6b7689")
LINE = colors.HexColor("#d6dde6")


def build_outpass_pdf(d: dict) -> bytes:
    """d: type, on_duty, date, emp_code, name, designation, purpose,
    out_time, in_time, ref_no, approver, approved_at."""
    buf = io.BytesIO()
    W, H = landscape(A5)
    c = _canvas.Canvas(buf, pagesize=(W, H))
    M = 14 * mm
    full_w = W - 2 * M

    # ---- header ----
    c.setFillColor(INK)
    c.rect(0, H - 24 * mm, W, 24 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(M, H - 13 * mm, "METFRAA STEEL BUILDINGS PVT. LTD.")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#9fb3c8"))
    c.drawString(M, H - 18.5 * mm, "Steeling the Future")

    label = "GATE PASS" if d.get("type") == "gatepass" else "OUT PASS"
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(colors.white)
    c.drawRightString(W - M, H - 13 * mm, label)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#9fb3c8"))
    c.drawRightString(W - M, H - 18.5 * mm, str(d.get("ref_no") or ""))

    # On-duty is a materially different thing at the gate — make it obvious.
    if d.get("on_duty"):
        c.setFillColor(BLUE)
        c.roundRect(W - M - 30 * mm, H - 33 * mm, 30 * mm, 6.5 * mm, 2, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(W - M - 15 * mm, H - 31.2 * mm, "ON DUTY")

    def field(lbl, val, x, y, w):
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(x, y + 7 * mm, str(lbl).upper())
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10.5)
        text = str(val or "-")
        # Purpose can run long; clip rather than overflow into the next field.
        while c.stringWidth(text, "Helvetica-Bold", 10.5) > w - 3 * mm and len(text) > 4:
            text = text[:-2]
            if c.stringWidth(text + "…", "Helvetica-Bold", 10.5) <= w - 3 * mm:
                text += "…"
        c.drawString(x, y + 2 * mm, text)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(x, y, x + w, y)

    col_l, col_r = M, M + full_w / 2 + 4 * mm
    half_w = full_w / 2 - 4 * mm
    y = H - 46 * mm
    row = 15 * mm

    field("Date", d.get("date"), col_l, y, half_w)
    field("Employee code", d.get("emp_code"), col_r, y, half_w)
    y -= row
    field("Name", d.get("name"), col_l, y, half_w)
    field("Designation", d.get("designation"), col_r, y, half_w)
    y -= row
    field("Out-time", d.get("out_time"), col_l, y, half_w)
    if d.get("type") == "gatepass":
        field("In-time", d.get("in_time"), col_r, y, half_w)
    y -= row
    field("Purpose", d.get("purpose"), col_l, y, full_w)

    # ---- approval band ----
    bh = 13 * mm
    by = M
    c.setFillColor(GREEN)
    c.roundRect(M, by, full_w, bh, 3, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(M + 6 * mm, by + 4.6 * mm, "APPROVED")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#eafbf1"))
    c.drawRightString(W - M - 6 * mm, by + 4.8 * mm,
                      f"Approved by {d.get('approver') or '-'}    {d.get('approved_at') or ''}")

    c.showPage()
    c.save()
    return buf.getvalue()
