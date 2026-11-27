"""Code Books — reference standards (IS / ASCE / AISC …) for the design team.

The PDFs are large (10-30 MB), so they are hosted in external storage
(Vercel Blob) and referenced here by public URL. Any logged-in user can
view/download; only admins can add or remove entries.
"""
import os
import re
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

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


def _title_from_url(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"\.(pdf|PDF)$", "", name)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Document"


def _parse_lines(text: str):
    """Each line: 'Title | URL | Category', 'Title | URL', or just 'URL'."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        title = url = category = ""
        url_parts = [p for p in parts if p.lower().startswith(("http://", "https://"))]
        if not url_parts:
            continue
        url = url_parts[0]
        others = [p for p in parts if p is not url and not p.lower().startswith(("http://", "https://"))]
        if len(others) >= 1 and others[0]:
            title = others[0]
        if len(others) >= 2 and others[1]:
            category = others[1]
        out.append({
            "title": title or _title_from_url(url),
            "url": url,
            "category": category or "Code Books",
        })
    return out


# category display order preference
_ORDER = ["IS codes", "IS Codes", "American codes", "American Codes", "Code Books"]


@router.get("", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user)):
    _ensure()
    return templates.TemplateResponse(request, "code_books.html", {"user": user})


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
        groups.setdefault(r.category or "Code Books", []).append(
            {"id": r.id, "title": r.title, "url": r.url})
    ordered = sorted(groups.keys(),
                     key=lambda c: (_ORDER.index(c) if c in _ORDER else 99, c.lower()))
    return {"groups": [{"category": c, "items": groups[c]} for c in ordered],
            "can_edit": bool(user.is_admin), "total": len(rows)}


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
        raise HTTPException(400, "No valid URLs found. Paste one URL per line.")
    base = db.query(CodeBook).count()
    for i, it in enumerate(items):
        db.add(CodeBook(category=it["category"][:120], title=it["title"][:300],
                        url=it["url"], sort=base + i, created_by=user.name))
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
            f"code-books/{file.filename}", data, access="public",
            add_random_suffix=True, content_type=file.content_type or "application/pdf")
        url = res.url
    except Exception as e:
        raise HTTPException(500, f"Blob upload failed: {e}. Is the Blob store connected "
                                 "to this project (BLOB_READ_WRITE_TOKEN)?")
    _ensure()
    db.add(CodeBook(category=(category or "Code Books").strip()[:120],
                    title=(title or "").strip()[:300] or _title_from_url(file.filename),
                    url=url, sort=db.query(CodeBook).count(), created_by=user.name))
    db.commit()
    return {"ok": True, "url": url}


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
