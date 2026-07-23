"""Site Visit PDF generator — Metfraa brand palette (blue + black + white).

Design language matches dashboard.html: metfraa-blue accents, black masthead,
clean white cards, Helvetica-family, no industrial/amber elements.
"""
import base64
import io
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
)

# ---- Metfraa brand palette (matches tailwind config in HTML templates) ----
BLACK = colors.HexColor("#000000")
INK = colors.HexColor("#111827")          # metfraa-ink
BLUE = colors.HexColor("#1E3A8A")         # metfraa-blue
BLUE_DARK = colors.HexColor("#152A66")    # metfraa-blue-dark

GRAY_50 = colors.HexColor("#F9FAFB")
GRAY_100 = colors.HexColor("#F3F4F6")
GRAY_200 = colors.HexColor("#E5E7EB")
GRAY_300 = colors.HexColor("#D1D5DB")
GRAY_400 = colors.HexColor("#9CA3AF")
GRAY_500 = colors.HexColor("#6B7280")
GRAY_600 = colors.HexColor("#4B5563")
GRAY_700 = colors.HexColor("#374151")

# Priority palette (matches HTML badges)
SUCCESS = colors.HexColor("#059669")   # emerald-600
WARN = colors.HexColor("#D97706")      # amber-600
DANGER = colors.HexColor("#DC2626")    # red-600


CATEGORY_LABEL = {
    "newshed": "New Shed Requirement",
    "reroof": "Re-roofing & Shed Maintenance",
    "extension": "Extension / Modification",
    "other": "Other Requirement",
}


def _priority_color(p: str):
    return {"Low": SUCCESS, "Medium": WARN, "High": DANGER}.get(p or "", GRAY_500)


def _styles():
    return {
        "eyebrow": ParagraphStyle("Eyebrow",
            fontName="Helvetica-Bold", fontSize=8, textColor=BLUE,
            alignment=TA_LEFT, leading=10, spaceAfter=2),
        "section": ParagraphStyle("Section",
            fontName="Helvetica-Bold", fontSize=11, textColor=BLUE,
            alignment=TA_LEFT, leading=14, spaceBefore=14, spaceAfter=8),
        "section_sub": ParagraphStyle("SectionSub",
            fontName="Helvetica-Bold", fontSize=13, textColor=INK,
            alignment=TA_LEFT, leading=16, spaceAfter=6),
        "label": ParagraphStyle("Label",
            fontName="Helvetica-Bold", fontSize=7.5, textColor=GRAY_500,
            alignment=TA_LEFT, leading=9),
        "value": ParagraphStyle("Value",
            fontName="Helvetica", fontSize=10, textColor=INK,
            alignment=TA_LEFT, leading=13),
        "value_bold": ParagraphStyle("ValueBold",
            fontName="Helvetica-Bold", fontSize=10, textColor=INK,
            alignment=TA_LEFT, leading=13),
        "rid": ParagraphStyle("Rid",
            fontName="Courier-Bold", fontSize=10, textColor=BLUE,
            alignment=TA_LEFT, leading=12),
        "note": ParagraphStyle("Note",
            fontName="Helvetica", fontSize=10, textColor=INK,
            alignment=TA_LEFT, leading=14, backColor=GRAY_50,
            borderColor=GRAY_200, borderWidth=0.5, borderPadding=10,
            leftIndent=0, spaceBefore=2, spaceAfter=4),
        "small": ParagraphStyle("Small",
            fontName="Helvetica", fontSize=8, textColor=GRAY_500,
            alignment=TA_LEFT, leading=10),
        "caption": ParagraphStyle("Caption",
            fontName="Helvetica", fontSize=8, textColor=GRAY_600,
            alignment=TA_CENTER, leading=10, spaceBefore=2),
        "footer": ParagraphStyle("Footer",
            fontName="Helvetica", fontSize=8, textColor=GRAY_400,
            alignment=TA_CENTER, leading=10),
    }


def _header_footer(canvas, doc):
    """Black masthead with metfraa-blue accent line + footer."""
    canvas.saveState()
    width, height = A4

    # Black masthead (h=22mm)
    canvas.setFillColor(BLACK)
    canvas.rect(0, height - 22 * mm, width, 22 * mm, stroke=0, fill=1)

    # Metfraa-blue accent line (2mm)
    canvas.setFillColor(BLUE)
    canvas.rect(0, height - 24 * mm, width, 2 * mm, stroke=0, fill=1)

    # Eyebrow (blue text on black)
    canvas.setFillColor(BLUE)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(15 * mm, height - 10 * mm, "BUSINESS DEVELOPMENT — FIELD CAPTURE")

    # Title (white)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 17)
    canvas.drawString(15 * mm, height - 18 * mm, "METFRAA")

    canvas.setFillColor(GRAY_300)
    canvas.setFont("Helvetica", 13)
    canvas.drawString(45 * mm, height - 18 * mm, "|  Site Visit Report")

    # Report ID on right
    if hasattr(doc, "_report_id") and doc._report_id:
        canvas.setFillColor(GRAY_400)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(width - 15 * mm, height - 10 * mm, "REPORT ID")
        canvas.setFillColor(BLUE)
        canvas.setFont("Courier-Bold", 10)
        canvas.drawRightString(width - 15 * mm, height - 17 * mm, doc._report_id)

    # ---- Footer ----
    canvas.setStrokeColor(GRAY_200)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, 14 * mm, width - 15 * mm, 14 * mm)

    canvas.setFillColor(GRAY_500)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(15 * mm, 9 * mm,
        f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')}  ·  Metfraa Steel Buildings Pvt. Ltd.")

    canvas.setFillColor(GRAY_400)
    canvas.drawRightString(width - 15 * mm, 9 * mm, f"Page {doc.page}")

    canvas.restoreState()


def _grid_two_col(pairs: list, col_widths=(88 * mm, 88 * mm)) -> Table:
    """2-column grid of label/value pairs."""
    rows = []
    for i in range(0, len(pairs), 2):
        left = pairs[i]
        right = pairs[i + 1] if i + 1 < len(pairs) else ("", "")
        rows.append([
            _kv_cell(left[0], left[1]),
            _kv_cell(right[0], right[1]),
        ])
    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _kv_cell(label: str, value) -> Table:
    """Single label-over-value cell."""
    styles = _styles()
    if not label:
        return Paragraph("", styles["value"])

    if isinstance(value, Paragraph):
        val_flowable = value
    else:
        val_flowable = Paragraph(str(value) if value not in (None, "") else "—", styles["value"])

    data = [
        [Paragraph(label.upper(), styles["label"])],
        [val_flowable],
    ]
    inner = Table(data, colWidths=[80 * mm])
    inner.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return inner


# ============================================================
# Category detail pair builders
# ============================================================

def _newshed_pairs(d: dict) -> list:
    return [
        ("Purpose / Usage", d.get("purpose", "")),
        ("Length", (str(d["length"]) + " m") if d.get("length") else ""),
        ("Width", (str(d["width"]) + " m") if d.get("width") else ""),
        ("Eave / Clear height", (str(d["height"]) + " m") if d.get("height") else ""),
        ("Covered area", d.get("area", "")),
        ("Foundation", d.get("foundation", "")),
        ("Structure type", d.get("structure_type", "")),
        ("Roof sheeting", d.get("roof_sheet", "")),
        ("Wall cladding", d.get("cladding", "")),
        ("Ventilation / skylights", d.get("ventilation", "")),
        ("Openings", d.get("openings", "")),
        ("Utilities", d.get("utilities", "")),
        ("Timeline", d.get("timeline", "")),
        ("Budget", d.get("budget", "")),
    ]


def _reroof_pairs(d: dict) -> list:
    return [
        ("Existing structure", d.get("structure_type", "")),
        ("Existing material", d.get("material", "")),
        ("Age (yrs)", d.get("age", "")),
        ("Area affected", d.get("area_affected", "")),
        ("Scope of work", d.get("scope", "")),
        ("Timeline", d.get("timeline", "")),
        ("Budget", d.get("budget", "")),
        ("Access constraints", d.get("access", "")),
    ]


def _extension_pairs(d: dict) -> list:
    return [
        ("Existing structure", d.get("existing", "")),
        ("Extension area", (str(d["area"]) + " sqm") if d.get("area") else ""),
        ("Purpose", d.get("purpose", "")),
        ("Connection type", d.get("connection", "")),
        ("Structural notes", d.get("structural", "")),
        ("Timeline", d.get("timeline", "")),
        ("Budget", d.get("budget", "")),
    ]


# ============================================================
# Main generator
# ============================================================

def generate_site_visit_pdf(visit, employee=None) -> bytes:
    """Return PDF bytes for a SiteVisit record — Metfraa branded."""
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=32 * mm, bottomMargin=20 * mm,
        title=f"Site Visit — {visit.report_id}",
        author="Metfraa Steel Buildings",
    )
    doc._report_id = visit.report_id  # so header can render it

    elements = []

    # ---- Meta stripe (report id, visit date, status) ----
    visit_date_str = visit.visit_date.strftime("%A, %d %B %Y") if visit.visit_date else "—"
    emp_line = f"{employee.name} ({employee.employee_code})" if employee else (visit.visited_by or "—")

    status_color = SUCCESS if visit.status == "submitted" else WARN
    status_text = (visit.status or "").upper()

    meta_data = [
        [
            _kv_cell("Report ID", Paragraph(visit.report_id, styles["rid"])),
            _kv_cell("Visit date", visit_date_str),
            _kv_cell("Status", Paragraph(
                f'<font color="{status_color.hexval()}"><b>{status_text}</b></font>',
                styles["value"]
            )),
        ]
    ]
    mt = Table(meta_data, colWidths=[55 * mm, 65 * mm, 60 * mm])
    mt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, GRAY_200),
        ("BACKGROUND", (0, 0), (-1, -1), GRAY_50),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(mt)
    elements.append(Spacer(1, 8 * mm))

    # ---- Section 1: Visit & Contact Details ----
    elements.append(_section_header("1", "Visit & Contact Details"))
    contact_pairs = [
        ("Customer / Company", visit.company_name or ""),
        ("Visited by", emp_line),
        ("Contact person", visit.contact_person or ""),
        ("Phone", visit.contact_phone or ""),
        ("Email", visit.contact_email or ""),
        ("Site address", visit.site_address or ""),
    ]
    elements.append(_grid_two_col(contact_pairs))
    elements.append(Spacer(1, 6 * mm))

    # ---- Section 2: Requirement ----
    cat_label = CATEGORY_LABEL.get(visit.category or "", visit.category or "Not selected")
    elements.append(_section_header("2", f"Requirement — {cat_label}"))

    d = visit.details_json or {}
    if visit.category == "newshed":
        elements.append(_grid_two_col(_newshed_pairs(d)))
        if d.get("site_conditions"):
            elements.append(Spacer(1, 4 * mm))
            elements.append(Paragraph("SITE CONDITION NOTES", styles["label"]))
            elements.append(Spacer(1, 2 * mm))
            elements.append(Paragraph(d.get("site_conditions", "").replace("\n", "<br/>"), styles["note"]))
    elif visit.category == "reroof":
        elements.append(_grid_two_col(_reroof_pairs(d)))
        issues = d.get("issues") or []
        if issues:
            elements.append(Spacer(1, 4 * mm))
            elements.append(Paragraph("ISSUES OBSERVED", styles["label"]))
            elements.append(Spacer(1, 2 * mm))
            elements.append(Paragraph(" · ".join(issues), styles["value"]))
        maint = d.get("maintenance") or []
        if maint:
            elements.append(Spacer(1, 4 * mm))
            elements.append(Paragraph("ADDITIONAL MAINTENANCE", styles["label"]))
            elements.append(Spacer(1, 2 * mm))
            elements.append(Paragraph(" · ".join(maint), styles["value"]))
    elif visit.category == "extension":
        elements.append(_grid_two_col(_extension_pairs(d)))
    elif visit.category == "other":
        desc = d.get("description", "")
        if desc:
            elements.append(Paragraph(desc.replace("\n", "<br/>"), styles["note"]))
        else:
            elements.append(Paragraph("(no description entered)", styles["small"]))
    else:
        elements.append(Paragraph("(No category selected)", styles["small"]))

    elements.append(Spacer(1, 6 * mm))

    # ---- Section 3: Photos ----
    photos = sorted(visit.photos, key=lambda p: p.sequence)
    section_num = 3
    if photos:
        elements.append(_section_header(str(section_num), f"Site Photos ({len(photos)})"))
        section_num += 1

        photo_rows = []
        row_buf = []
        for i, p in enumerate(photos, start=1):
            img_flowable = _photo_flowable(p)
            cap = Paragraph(p.caption or f"Photo {i}", styles["caption"])
            cell = [img_flowable, Spacer(1, 2 * mm), cap]
            row_buf.append(cell)
            if len(row_buf) == 3:
                photo_rows.append(row_buf)
                row_buf = []
        if row_buf:
            while len(row_buf) < 3:
                row_buf.append("")
            photo_rows.append(row_buf)

        pt = Table(photo_rows, colWidths=[58 * mm, 58 * mm, 58 * mm])
        pt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(pt)
        elements.append(Spacer(1, 4 * mm))

    # ---- Discussion & Next Steps ----
    elements.append(_section_header(str(section_num), "Discussion Summary & Next Steps"))

    if visit.discussion_notes:
        elements.append(Paragraph("KEY DISCUSSION POINTS", styles["label"]))
        elements.append(Spacer(1, 2 * mm))
        elements.append(Paragraph(visit.discussion_notes.replace("\n", "<br/>"), styles["note"]))
        elements.append(Spacer(1, 4 * mm))
    if visit.next_steps:
        elements.append(Paragraph("NEXT STEPS / ACTION ITEMS", styles["label"]))
        elements.append(Spacer(1, 2 * mm))
        elements.append(Paragraph(visit.next_steps.replace("\n", "<br/>"), styles["note"]))
        elements.append(Spacer(1, 4 * mm))

    # Followup + priority side-by-side
    followup = visit.followup_date.strftime("%d %b %Y") if visit.followup_date else "—"
    priority = visit.priority or "—"
    p_color = _priority_color(visit.priority or "")
    prio_para = Paragraph(f'<font color="{p_color.hexval()}"><b>{priority}</b></font>', styles["value_bold"])

    fl_tbl = Table(
        [[
            _kv_cell("Follow-up date", followup),
            _kv_cell("Priority", prio_para),
        ]],
        colWidths=[88 * mm, 88 * mm],
    )
    fl_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(fl_tbl)

    # Build
    doc.build(elements, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buf.seek(0)
    return buf.read()


def _section_header(num: str, title: str) -> Table:
    """Blue circle number + heading, styled like the HTML section headers."""
    styles = _styles()

    # Numbered blue circle
    num_cell = Table(
        [[Paragraph(f'<font color="white"><b>{num}</b></font>', ParagraphStyle(
            "num", fontName="Helvetica-Bold", fontSize=11,
            alignment=TA_CENTER, textColor=colors.white))]],
        colWidths=[7 * mm], rowHeights=[7 * mm],
    )
    num_cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROUNDEDCORNERS", [3.5, 3.5, 3.5, 3.5]),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    header_row = Table(
        [[
            num_cell,
            [
                Paragraph(f"SECTION {num}", styles["eyebrow"]),
                Paragraph(title, styles["section_sub"]),
            ],
        ]],
        colWidths=[10 * mm, 170 * mm],
    )
    header_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRAY_200),
    ]))
    return header_row


def _photo_flowable(photo):
    """Render a photo thumbnail. Fallback to placeholder if unavailable."""
    if photo.thumbnail_b64:
        try:
            img_bytes = base64.b64decode(photo.thumbnail_b64)
            return Image(io.BytesIO(img_bytes), width=54 * mm, height=40 * mm, kind="proportional")
        except Exception:
            pass
    # Placeholder
    styles = _styles()
    ph = Table([[Paragraph("(photo unavailable)", styles["small"])]],
               colWidths=[54 * mm], rowHeights=[40 * mm])
    ph.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, GRAY_200),
        ("BACKGROUND", (0, 0), (-1, -1), GRAY_50),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return ph
