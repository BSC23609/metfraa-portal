"""EHS approval PDF — generated when a submission is approved.

Reportlab port of metfraa-ehs pdf-report.js: brand header, submission meta,
field values, photo thumbnails, checklist table, approval block, footer.
"""
import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

log = logging.getLogger(__name__)

BRAND = colors.HexColor("#005B96")
INK = colors.HexColor("#1a2332")
GRAY = colors.HexColor("#6b7480")
LIGHT = colors.HexColor("#eef2f6")
GREEN = colors.HexColor("#1F8B4C")

S_TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, textColor=colors.white)
S_SUB = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#cfe3f2"))
S_SECTION = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=11, textColor=BRAND, spaceBefore=8, spaceAfter=4)
S_LABEL = ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=8.5, textColor=GRAY)
S_VALUE = ParagraphStyle("v", fontName="Helvetica", fontSize=9.5, textColor=INK)
S_SMALL = ParagraphStyle("sm", fontName="Helvetica", fontSize=8, textColor=GRAY)
S_CL = ParagraphStyle("cl", fontName="Helvetica", fontSize=8.5, textColor=INK)


def _photo_img(data: bytes, w_mm: float = 50, h_mm: float = 38) -> Image | None:
    try:
        return Image(io.BytesIO(data), width=w_mm * mm, height=h_mm * mm, kind="proportional")
    except Exception:
        return None


def generate_ehs_pdf(form: dict, sub, photo_buffers: dict) -> bytes:
    """photo_buffers: {"fields": {key: [bytes]}, "checklist": {int_idx: [bytes]}}."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"{form['title']} — {sub.submission_id}",
    )
    E: list = []

    # ---- Header band
    E.append(Table(
        [[Paragraph("METFRAA — EHS", S_TITLE)],
         [Paragraph(f"{form['title']}  ({form['code']})", S_SUB)]],
        colWidths=[doc.width],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (0, 0), 8),
            ("BOTTOMPADDING", (0, 1), (0, 1), 8),
        ]),
    ))
    E.append(Spacer(1, 6))

    # ---- Meta
    meta_rows = [
        [Paragraph("Submission ID", S_LABEL), Paragraph(sub.submission_id, S_VALUE),
         Paragraph("Submitted At (IST)", S_LABEL), Paragraph(sub.submitted_at_ist, S_VALUE)],
        [Paragraph("Submitted By", S_LABEL), Paragraph(sub.submitted_by_name, S_VALUE),
         Paragraph("Email", S_LABEL), Paragraph(sub.submitted_by_email or "—", S_VALUE)],
    ]
    E.append(Table(meta_rows, colWidths=[doc.width * f for f in (0.18, 0.32, 0.18, 0.32)],
                   style=TableStyle([
                       ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("TOPPADDING", (0, 0), (-1, -1), 5),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                       ("LEFTPADDING", (0, 0), (-1, -1), 8),
                   ])))
    E.append(Spacer(1, 4))

    # ---- Fields
    E.append(Paragraph("Form Details", S_SECTION))
    fields = sub.fields or {}
    pb_fields = (photo_buffers or {}).get("fields", {})
    for f in form["fields"]:
        if f["type"] == "photo":
            bufs = pb_fields.get(f["key"], [])
            E.append(Paragraph(f["label"], S_LABEL))
            if bufs:
                imgs = [i for i in (_photo_img(b) for b in bufs[:6]) if i]
                if imgs:
                    per_row = 3
                    rows = [imgs[i:i + per_row] for i in range(0, len(imgs), per_row)]
                    rows = [r + [""] * (per_row - len(r)) for r in rows]
                    E.append(Table(rows, colWidths=[doc.width / per_row] * per_row,
                                   style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 3),
                                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])))
                else:
                    E.append(Paragraph("(photos could not be embedded)", S_SMALL))
            else:
                E.append(Paragraph("(no photo)", S_SMALL))
            E.append(Spacer(1, 3))
        else:
            v = fields.get(f["key"], "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            E.append(Table([[Paragraph(f["label"], S_LABEL), Paragraph(str(v) if v not in (None, "") else "—", S_VALUE)]],
                           colWidths=[doc.width * 0.32, doc.width * 0.68],
                           style=TableStyle([
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde3ea")),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ])))

    # ---- Checklist
    cl_def = form.get("checklist") or []
    if cl_def:
        E.append(Paragraph("Inspection Checklist", S_SECTION))
        cl = sub.checklist or []
        pb_cl = (photo_buffers or {}).get("checklist", {})
        head = [Paragraph("<b>#</b>", S_CL), Paragraph("<b>Parameter</b>", S_CL),
                Paragraph("<b>Result</b>", S_CL), Paragraph("<b>Remarks</b>", S_CL)]
        rows = [head]
        for i, param in enumerate(cl_def):
            item = cl[i] if i < len(cl) else {}
            result = (item or {}).get("result", "")
            remarks = (item or {}).get("remarks", "")
            has_photo = bool(pb_cl.get(i) or pb_cl.get(str(i)))
            rows.append([
                Paragraph(str(i + 1), S_CL),
                Paragraph(param, S_CL),
                Paragraph(result or "—", S_CL),
                Paragraph((remarks + (" 📷" if has_photo else "")) or "—", S_CL),
            ])
        E.append(Table(rows, colWidths=[doc.width * f for f in (0.06, 0.54, 0.14, 0.26)],
                       repeatRows=1,
                       style=TableStyle([
                           ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3dd")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                       ])))
        # checklist photos appendix
        appendix = []
        for i in range(len(cl_def)):
            for b in (pb_cl.get(i) or pb_cl.get(str(i)) or []):
                img = _photo_img(b, 50, 38)
                if img:
                    appendix.append((i + 1, img))
        if appendix:
            E.append(Paragraph("Checklist Photo Evidence", S_SECTION))
            per_row = 3
            cells, labels = [], []
            for num, img in appendix:
                cells.append(img)
                labels.append(Paragraph(f"Item #{num}", S_SMALL))
            for i in range(0, len(cells), per_row):
                crow = cells[i:i + per_row]
                lrow = labels[i:i + per_row]
                crow += [""] * (per_row - len(crow))
                lrow += [""] * (per_row - len(lrow))
                E.append(Table([crow, lrow], colWidths=[doc.width / per_row] * per_row,
                               style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2),
                                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])))

    # ---- Approval block
    E.append(Spacer(1, 8))
    approval_rows = [
        [Paragraph("APPROVED", ParagraphStyle("ap", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white)),
         Paragraph(f"Reviewed by <b>{sub.reviewed_by_name or ''}</b> ({sub.reviewed_by_email or ''}) at {sub.reviewed_at_ist or ''} IST", S_VALUE)],
    ]
    if sub.edits_made:
        approval_rows.append([Paragraph("Edits", S_LABEL), Paragraph(sub.edits_made, S_SMALL)])
    E.append(Table(approval_rows, colWidths=[doc.width * 0.2, doc.width * 0.8],
                   style=TableStyle([
                       ("BACKGROUND", (0, 0), (0, 0), GREEN),
                       ("BACKGROUND", (1, 0), (1, -1), LIGHT),
                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("TOPPADDING", (0, 0), (-1, -1), 6),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                       ("LEFTPADDING", (0, 0), (-1, -1), 8),
                   ])))

    E.append(Spacer(1, 6))
    E.append(Paragraph(f"Generated by Metfraa Portal · {sub.submission_id}", S_SMALL))

    doc.build(E)
    return buf.getvalue()
