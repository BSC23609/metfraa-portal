"""Consolidated monthly report — cover + navigable table of contents + every
claim's branded PDF with its bills, merged into one document.

Faithful port of the old Node app's consolidated-report.js (pdf-lib) to
reportlab (cover/TOC) + pypdf (merge & links). Produces the document the old
"APPROVED FOR PAYMENT" email attached: a cover page, a clickable table of
contents, then each claim page followed by its bills, every content page
carrying a "HOME ^" link back to the contents.

The individual claim pages are rendered by expense_pdf.build_claim_pdf, so the
consolidated report and the standalone report share one renderer.
"""
import io
from datetime import datetime, timedelta

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, FloatObject, NameObject,
                           NumberObject, TextStringObject)
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as _canvas

from .expense_pdf import (_ensure_fonts, _font, BLUE, INK, LINE, MUTED, SOFT,
                          build_claim_pdf)

PAGE_W, PAGE_H = A4
MARGIN = 40

FORM_LABEL = {
    "met_local": "Local Travel", "met_cab": "Cab Reimbursement",
    "met_accommodation": "Accommodation", "met_outstation": "Outstation",
    "met_misc": "Miscellaneous", "met_advance": "Travel Advance",
    "met_dtr": "Daily Travel",
}


def _fmt_inr(n):
    try:
        return f"{float(n or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _fmt_date(iso):
    if not iso:
        return "—"
    s = str(iso)
    for f in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], f).strftime("%d %b %Y")
        except ValueError:
            continue
    return s


def _fmt_dt_ist(iso):
    if not iso:
        return "—"
    s = str(iso)
    try:
        base = s.replace(" ", "T") + "Z" if len(s) == 19 and s[10] == " " else s
        d = datetime.fromisoformat(base.replace("Z", ""))
        # timestamps are stored IST already in this portal; show as-is
        return d.strftime("%d %b %Y %I:%M %p") + " IST"
    except Exception:
        return s


def _month_label(period):
    try:
        y, m = period.split("-")
        return datetime(int(y), int(m), 1).strftime("%B %Y")
    except Exception:
        return period or ""


# ---------------------------------------------------------------------------
#  Cover + TOC drawn with reportlab (origin bottom-left, like pdf-lib)
# ---------------------------------------------------------------------------

def _hex(c):
    from reportlab.lib.colors import HexColor
    return HexColor(c)


def _draw_cover(c, employee, period, total, count, generated_at, signoffs):
    W, H = PAGE_W, PAGE_H
    c.setFillColor(_hex(BLUE))
    c.rect(0, H - 6, W, 6, fill=1, stroke=0)

    c.setFont(_font(bold=True), 9)
    c.setFillColor(_hex(MUTED))
    c.drawString(MARGIN, H - 90, "CONSOLIDATED REPORT")

    c.setFont(_font(bold=True), 32)
    c.setFillColor(_hex(INK))
    c.drawString(MARGIN, H - 130, _month_label(period))

    c.setStrokeColor(_hex(LINE))
    c.setLineWidth(0.5)
    c.line(MARGIN, H - 180, W - MARGIN, H - 180)

    c.setFont(_font(bold=True), 8)
    c.setFillColor(_hex(MUTED))
    c.drawString(MARGIN, H - 205, "EMPLOYEE")
    c.setFont(_font(bold=True), 15)
    c.setFillColor(_hex(INK))
    c.drawString(MARGIN, H - 226, employee.get("name") or "—")
    c.setFont(_font(), 9)
    c.setFillColor(_hex(MUTED))
    tail = employee.get("email") or ""
    if employee.get("code"):
        tail += "  ·  " + employee["code"]
    c.drawString(MARGIN, H - 243, tail)

    negative = float(total or 0) < 0
    disp = abs(float(total or 0))
    label = "PAYABLE TO COMPANY" if negative else "PAYABLE TO EMPLOYEE"
    col = "#b82929" if negative else INK
    tx = W - MARGIN - 240
    c.setFont(_font(bold=True), 8)
    c.setFillColor(_hex(MUTED))
    c.drawString(tx, H - 205, label)
    c.setFont(_font(bold=True), 22)
    c.setFillColor(_hex(col))
    c.drawString(tx, H - 235, f"INR {_fmt_inr(disp)}")
    c.setFont(_font(), 9)
    c.setFillColor(_hex(MUTED))
    c.drawString(tx, H - 253, f"{count} claim{'' if count == 1 else 's'}"
                 + ("  ·  net owed back" if negative else ""))

    c.setStrokeColor(_hex(LINE))
    c.line(MARGIN, H - 280, W - MARGIN, H - 280)

    so = signoffs or {}
    c.setFont(_font(bold=True), 8)
    c.setFillColor(_hex(MUTED))
    c.drawString(MARGIN, H - 310, "STATUS")
    if so.get("mgmt", {}).get("by"):
        st, sc = "APPROVED — READY FOR PAYMENT", "#059659"
    elif so.get("hr", {}).get("by"):
        st, sc = "HR VERIFIED — AWAITING MANAGEMENT", BLUE
    else:
        st, sc = "DRAFT — AWAITING REVIEW", "#b3660d"
    c.setFont(_font(bold=True), 12)
    c.setFillColor(_hex(sc))
    c.drawString(MARGIN, H - 328, st)

    sigY = H - 356

    def sig(lbl, meta):
        nonlocal sigY
        if not meta or not meta.get("by"):
            return
        c.setFont(_font(bold=True), 8)
        c.setFillColor(_hex(MUTED))
        c.drawString(MARGIN, sigY, lbl)
        c.setFont(_font(bold=True), 10)
        c.setFillColor(_hex(INK))
        who = str(meta["by"]).split("@")[0]
        c.drawString(MARGIN + 90, sigY, f"{who}  ·  {_fmt_dt_ist(meta.get('at'))}")
        sigY -= 18
    sig("HR VERIFIED", so.get("hr"))
    sig("MGMT APPROVED", so.get("mgmt"))

    c.setFont(_font(), 8)
    c.setFillColor(_hex(MUTED))
    c.drawString(MARGIN, 40, f"Generated {_fmt_date(generated_at)}")
    c.setFont(_font(bold=True), 7)
    c.drawString(MARGIN, 28, "METFRAA · EXPENSE PORTAL · CONSOLIDATED")


def _row_amount(s):
    is_settled_adv = s.get("status") == "settled" and s.get("form_type") == "met_advance"
    if is_settled_adv:
        amt = float(s.get("differential_amount") or 0)
        prefix = "-INR " if amt < 0 else ("+INR " if amt > 0 else "INR ")
        return prefix, amt
    if s.get("status") == "settled" and s.get("actuals"):
        try:
            return "INR ", float((s["actuals"] or {}).get("actual_amount") or 0)
        except Exception:
            return "INR ", 0.0
    return "INR ", float(s.get("total_amount") or 0)


def _draw_toc_pages(subs):
    """Render the TOC (possibly several pages) into its own PDF; return
    (pdf_bytes, page_count, row_targets) where row_targets[i] =
    (toc_page_index, rect, submission_index) so the merger can add links."""
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    W, H = PAGE_W, PAGE_H
    row_targets = []
    ROWS_PER_PAGE = 30
    toc_page = 0
    header_emp = subs[0]["_employee_name"] if subs else ""
    header_period = subs[0]["_period"] if subs else ""

    def header():
        c.setFillColor(_hex(BLUE)); c.rect(0, H - 6, W, 6, fill=1, stroke=0)
        c.setFont(_font(bold=True), 9); c.setFillColor(_hex(MUTED))
        c.drawString(MARGIN, H - 70, "TABLE OF CONTENTS")
        c.setFont(_font(bold=True), 14); c.setFillColor(_hex(INK))
        c.drawString(MARGIN, H - 92, f"{header_emp} · {header_period}")
        c.setStrokeColor(_hex(LINE)); c.setLineWidth(0.5)
        c.line(MARGIN, H - 108, W - MARGIN, H - 108)
        c.setFont(_font(bold=True), 7); c.setFillColor(_hex(MUTED))
        c.drawString(MARGIN, H - 128, "#")
        c.drawString(MARGIN + 25, H - 128, "REFERENCE")
        c.drawString(MARGIN + 155, H - 128, "FORM")
        c.drawString(MARGIN + 260, H - 128, "SUBMITTED")
        c.drawString(W - MARGIN - 130, H - 128, "AMOUNT")
        c.drawString(W - MARGIN - 30, H - 128, "OPEN")
        c.line(MARGIN, H - 138, W - MARGIN, H - 138)

    header()
    rowY = H - 158
    rowH = 22
    on_page = 0
    for i, s in enumerate(subs):
        if on_page >= ROWS_PER_PAGE:
            c.showPage(); toc_page += 1; header(); rowY = H - 158; on_page = 0
        idx = f"{i + 1:02d}"
        is_settled_adv = s.get("status") == "settled" and s.get("form_type") == "met_advance"
        base = FORM_LABEL.get(s["form_type"], s["form_type"])
        form_label = f"{base}  [advance settled]" if is_settled_adv else base
        prefix, amt = _row_amount(s)
        c.setFont(_font(), 9); c.setFillColor(_hex(MUTED)); c.drawString(MARGIN, rowY, idx)
        c.setFont(_font(bold=True), 9); c.setFillColor(_hex(INK))
        c.drawString(MARGIN + 25, rowY, s["reference"])
        c.setFont(_font(), 9); c.setFillColor(_hex(MUTED if is_settled_adv else INK))
        c.drawString(MARGIN + 155, rowY, form_label)
        c.setFillColor(_hex(MUTED)); c.drawString(MARGIN + 260, rowY, _fmt_date(s.get("submitted_at")))
        if s.get("late_settlement"):
            c.setFont(_font(bold=True), 7); c.setFillColor(_hex("#b82929"))
            c.drawString(W - MARGIN - 190, rowY, "LATE")
        c.setFont(_font(bold=True), 9)
        c.setFillColor(_hex("#b82929" if amt < 0 else INK))
        c.drawString(W - MARGIN - 130, rowY, f"{prefix}{_fmt_inr(abs(amt))}")
        c.setFont(_font(bold=True), 14); c.setFillColor(_hex(BLUE))
        c.drawString(W - MARGIN - 26, rowY, ">")
        c.setStrokeColor(_hex(LINE)); c.setLineWidth(0.25)
        c.line(MARGIN, rowY - 8, W - MARGIN, rowY - 8)
        row_targets.append((toc_page, [MARGIN, rowY - 8, W - MARGIN, rowY + 12], i))
        rowY -= rowH
        on_page += 1
    c.showPage()
    c.save()
    return buf.getvalue(), toc_page + 1, row_targets


# ---------------------------------------------------------------------------
#  "HOME ^" pill stamped on every content page, linking back to the TOC.
# ---------------------------------------------------------------------------

def _home_pill_pdf():
    """A one-page overlay with the HOME pill at top-right, to merge onto each
    content page. Returns (bytes, rect)."""
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    W, H = PAGE_W, PAGE_H
    label = "HOME ^"
    c.setFont(_font(bold=True), 8)
    pillW = pdfmetrics.stringWidth(label, _font(bold=True), 8) + 16
    pillH = 16
    x = W - MARGIN - pillW
    y = H - MARGIN + 4
    c.setFillColor(_hex(SOFT)); c.setStrokeColor(_hex(LINE)); c.setLineWidth(0.5)
    c.roundRect(x, y, pillW, pillH, 2, fill=1, stroke=1)
    c.setFillColor(_hex(BLUE))
    c.drawString(x + 8, y + 4.5, label)
    c.save()
    return buf.getvalue(), [x, y, x + pillW, y + pillH]


def _link_annot(rect, target_page_index):
    """A GoTo link annotation dict to add to a page."""
    x1, y1, x2, y2 = rect
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(x1), FloatObject(y1),
                                          FloatObject(x2), FloatObject(y2)]),
        NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
        NameObject("/Dest"): ArrayObject([
            NumberObject(target_page_index), NameObject("/Fit")]),
    })


def build_consolidated(claims: list, employee: dict, period: str, total,
                       generated_at, signoffs=None) -> tuple[bytes, int]:
    """claims: ordered list of dicts, each:
         { sub, emp, payload, attachments }  where sub/emp/payload/attachments
         are exactly what build_claim_pdf expects, PLUS on `sub`:
         _employee_name, _period, submitted_at, late_settlement, differential_amount.
    Returns (pdf_bytes, page_count)."""
    _ensure_fonts()

    # 1. render each claim to its own PDF (with bills embedded)
    claim_pdfs = []
    for cl in claims:
        pdf = build_claim_pdf(cl["sub"], cl["emp"], cl["payload"],
                              attachments=cl.get("attachments") or [],
                              suppress_attachments=False)
        claim_pdfs.append(PdfReader(io.BytesIO(pdf)))

    # 2. cover
    cover_buf = io.BytesIO()
    cc = _canvas.Canvas(cover_buf, pagesize=A4)
    _draw_cover(cc, employee, period, total, len(claims), generated_at, signoffs)
    cc.save()
    cover_reader = PdfReader(io.BytesIO(cover_buf.getvalue()))

    # 3. TOC skeleton (needs claim page offsets to add links)
    toc_subs = [dict(cl["sub"]) for cl in claims]
    for s in toc_subs:
        s.setdefault("_employee_name", employee.get("name", ""))
        s.setdefault("_period", period)
    toc_bytes, toc_pages, row_targets = _draw_toc_pages(toc_subs)
    toc_reader = PdfReader(io.BytesIO(toc_bytes))

    # 4. assemble
    writer = PdfWriter()
    # cover (page 0)
    for p in cover_reader.pages:
        writer.add_page(p)
    toc_start = len(writer.pages)          # first TOC page index
    for p in toc_reader.pages:
        writer.add_page(p)

    # where each claim's first page lands
    claim_start = []
    home_overlay, home_rect = _home_pill_pdf()
    home_reader = PdfReader(io.BytesIO(home_overlay))
    home_page = home_reader.pages[0]

    for reader in claim_pdfs:
        claim_start.append(len(writer.pages))
        for p in reader.pages:
            # stamp the HOME pill and add its link back to the first TOC page
            try:
                p.merge_page(home_page)
            except Exception:
                pass
            writer.add_page(p)

    # 5. TOC row links -> each claim's first page
    for (toc_pg, rect, claim_idx) in row_targets:
        page = writer.pages[toc_start + toc_pg]
        annot = _link_annot(rect, claim_start[claim_idx])
        _add_annot(writer, page, annot)

    # 6. HOME links on every content page -> first TOC page
    for start in claim_start:
        pass  # per-page handled below
    for pg_index in range(claim_start[0] if claim_start else len(writer.pages),
                          len(writer.pages)):
        page = writer.pages[pg_index]
        annot = _link_annot(home_rect, toc_start)
        _add_annot(writer, page, annot)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), len(writer.pages)


def _add_annot(writer, page, annot):
    ref = writer._add_object(annot)
    if "/Annots" in page:
        page["/Annots"].append(ref)
    else:
        page[NameObject("/Annots")] = ArrayObject([ref])
