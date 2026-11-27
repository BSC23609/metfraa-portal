"""Code Books — reference standards (IS / ASCE / AISC …) for the design team.

The PDFs are large (10-30 MB) and licensed, so they live in a PRIVATE Vercel
Blob store. Entries hold the blob pathname; the portal streams each file to the
viewer through a login-gated route, so only signed-in staff can open them.
Any logged-in user can view/download; only admins can add or remove entries.
"""
import re
from contextlib import AsyncExitStack
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..database import engine, get_db
from ..deps import get_current_user
from ..models import CodeBook, Employee

router = APIRouter(prefix="/code-books", tags=["code-books"])
templates = Jinja2Templates(directory="app/templates")


def _ensure():
    try:
        CodeBook.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


def _title_from_ref(ref: str) -> str:
    name = unquote(urlparse(ref).path.rsplit("/", 1)[-1] if "://" in ref else ref.rsplit("/", 1)[-1])
    name = re.sub(r"\.(pdf|PDF)$", "", name)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Document"


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def _links(ref: str):
    """View + download links for a stored reference. A blob pathname is streamed
    through our login-gated /file route; a legacy full URL is passed through."""
    if _is_url(ref):
        return ref, ref + ("&" if "?" in ref else "?") + "download=1"
    base = "/code-books/file?p=" + quote(ref, safe="")
    return base, base + "&download=1"


def _parse_lines(text: str):
    """Each line, positional: 'Title | ref | Category', 'Title | ref', or 'ref'.
    `ref` is a blob pathname (e.g. code-books/800.pdf) or a full URL."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]
        if not parts:
            continue
        if len(parts) == 1:
            title, ref, category = "", parts[0], ""
        elif len(parts) == 2:
            title, ref, category = parts[0], parts[1], ""
        else:
            title, ref, category = parts[0], parts[1], parts[2]
        if not ref:
            continue
        out.append({"title": title or _title_from_ref(ref), "ref": ref,
                    "category": category or "Code Books"})
    return out


# category display order preference
_ORDER = ["IS codes", "IS Codes", "American codes", "American Codes", "Code Books"]


@router.get("", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user)):
    _ensure()
    return templates.TemplateResponse(request, "downloads.html", {"user": user})


@router.get("/api/list")
def api_list(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure()
    try:
        rows = db.query(CodeBook).order_by(CodeBook.category, CodeBook.sort, CodeBook.id).all()
    except Exception:
        db.rollback()
        rows = []
    groups = {}
    for r in rows:
        view, download = _links(r.url or "")
        groups.setdefault(r.category or "Code Books", []).append(
            {"id": r.id, "title": r.title, "view": view, "download": download})
    ordered = sorted(groups.keys(),
                     key=lambda c: (_ORDER.index(c) if c in _ORDER else 99, c.lower()))
    return {"groups": [{"category": c, "items": groups[c]} for c in ordered],
            "can_edit": bool(user.is_admin), "total": len(rows)}


@router.get("/file")
async def stream_file(p: str, download: int = 0,
                      user: Employee = Depends(get_current_user)):
    """Stream a private blob to a signed-in user. `p` is the blob pathname."""
    if _is_url(p):
        raise HTTPException(400, "Not a blob pathname.")
    stack = AsyncExitStack()
    try:
        from vercel import blob as vblob
        dl = await stack.enter_async_context(vblob.stream_blob(p, access="private"))
    except Exception as e:
        await stack.aclose()
        raise HTTPException(404, f"File not available: {e}")
    fname = p.rsplit("/", 1)[-1] or "file.pdf"
    disp = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disp}; filename="{fname}"',
               "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=600"}
    return StreamingResponse(dl, media_type=(dl.metadata.content_type or "application/pdf"),
                             headers=headers, background=BackgroundTask(stack.aclose))


class AddIn(BaseModel):
    text: str = ""


@router.post("/api/add")
def api_add(p: AddIn, user: Employee = Depends(get_current_user),
            db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(403, "Only admins can add code books.")
    _ensure()
    items = _parse_lines(p.text)
    if not items:
        raise HTTPException(400, "Nothing to add. Paste one file path (or URL) per line.")
    base = db.query(CodeBook).count()
    for i, it in enumerate(items):
        db.add(CodeBook(category=it["category"][:120], title=it["title"][:300],
                        url=it["ref"], sort=base + i, created_by=user.name))
    db.commit()
    return {"ok": True, "added": len(items)}


# Vercel Hobby caps the request body at ~4.5MB, so the in-portal uploader is
# limited; larger code books are pushed to Blob with the bulk upload script.
MAX_UPLOAD = 4 * 1024 * 1024


@router.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     category: str = Form("Code Books"),
                     title: str = Form(""),
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(403, "Only admins can upload code books.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{file.filename} is {len(data) // 1048576} MB — the "
                                 "in-portal uploader is limited to 4 MB on this plan. "
                                 "Use the bulk upload script for large files.")
    try:
        from vercel import blob as vblob
        res = await vblob.put_blob(
            f"code-books/{file.filename}", data, access="private",
            add_random_suffix=True, content_type=file.content_type or "application/pdf")
        ref = res.pathname
    except Exception as e:
        raise HTTPException(500, f"Blob upload failed: {e}. Is the private Blob store "
                                 "connected to this project (BLOB_READ_WRITE_TOKEN)?")
    _ensure()
    db.add(CodeBook(category=(category or "Code Books").strip()[:120],
                    title=(title or "").strip()[:300] or _title_from_ref(file.filename),
                    url=ref, sort=db.query(CodeBook).count(), created_by=user.name))
    db.commit()
    return {"ok": True}


@router.post("/api/{cid}/delete")
def api_delete(cid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(403, "Only admins can remove code books.")
    _ensure()
    row = db.query(CodeBook).filter(CodeBook.id == cid).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}
