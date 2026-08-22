"""Printable outpass / gatepass PDF.

Ported from BSC's lib/outpass_pdf.js (pdfkit) to reportlab. Same layout: a
header band, the detail fields in two columns, and a green APPROVED band across
the bottom carrying the approver's name and the timestamp — that band is what a
gatekeeper actually looks at, so it stays visually loud.
"""
import io
import pathlib

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas

INK = colors.HexColor("#0d1421")
BLUE = colors.HexColor("#1F7CCB")
GREEN = colors.HexColor("#16a34a")
MUTED = colors.HexColor("#6b7689")
LINE = colors.HexColor("#d6dde6")

# Both logos ship as opaque white-background PNGs, so the header is a WHITE
# letterhead rather than the dark band used elsewhere — a dark band would show
# them as white boxes. This also matches the EHS portal's header.
_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "static" / "expense" / "assets"
METFRAA_LOGO = _ASSETS / "metfraa-logo.png"      # 500x138
GROUP_LOGO = _ASSETS / "group-logo.png"          # 375x133


def _draw_logo(c, path: pathlib.Path, x, y, max_h, right_align_at=None):
    """Draw a logo at its natural aspect ratio. Missing file is not fatal —
    a pass without a logo still works at the gate; a crash doesn't."""
    try:
        from reportlab.lib.utils import ImageReader
        img = ImageReader(str(path))
        iw, ih = img.getSize()
        h = max_h
        w = h * iw / ih
        if right_align_at is not None:
            x = right_align_at - w
        c.drawImage(img, x, y, width=w, height=h, mask="auto")
        return w
    except Exception:
        return 0


def build_outpass_pdf(d: dict) -> bytes:
    """d: type, on_duty, date, emp_code, name, designation, purpose,
    out_time, in_time, ref_no, approver, approved_at."""
    buf = io.BytesIO()
    W, H = landscape(A5)
    c = _canvas.Canvas(buf, pagesize=(W, H))
    M = 14 * mm
    full_w = W - 2 * M

    # ---- header (white letterhead) ----
    head_h = 22 * mm
    head_y = H - head_h
    c.setFillColor(colors.white)
    c.rect(0, head_y, W, head_h, stroke=0, fill=1)

    _draw_logo(c, METFRAA_LOGO, M, head_y + 6.5 * mm, 9 * mm)
    _draw_logo(c, GROUP_LOGO, 0, head_y + 6.5 * mm, 9 * mm, right_align_at=W - M)

    # Blue rule under the letterhead, then the pass title on a dark strip so
    # the document type is unmistakable at a glance.
    c.setFillColor(BLUE)
    c.rect(0, head_y - 1.2 * mm, W, 1.2 * mm, stroke=0, fill=1)

    strip_h = 11 * mm
    strip_y = head_y - 1.2 * mm - strip_h
    c.setFillColor(INK)
    c.rect(0, strip_y, W, strip_h, stroke=0, fill=1)

    label = "GATE PASS" if d.get("type") == "gatepass" else "OUT PASS"
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(M, strip_y + 3.6 * mm, label)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#9fb3c8"))
    c.drawRightString(W - M, strip_y + 3.8 * mm, str(d.get("ref_no") or ""))

    # On-duty is a materially different thing at the gate — make it obvious.
    # Sits inside the dark strip next to the title, so it can never collide
    # with the fields below.
    if d.get("on_duty"):
        bw = 22 * mm
        bx = M + c.stringWidth(label, "Helvetica-Bold", 13) + 5 * mm
        c.setFillColor(BLUE)
        c.roundRect(bx, strip_y + 2.9 * mm, bw, 5.4 * mm, 1.5, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(bx + bw / 2, strip_y + 4.5 * mm, "ON DUTY")

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
    y = strip_y - 16 * mm
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
