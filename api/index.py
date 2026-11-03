"""Vercel entrypoint — all routes serve through this one function.

Lives in api/ because Vercel reliably builds Python functions here regardless
of framework detection. vercel.json rewrites every path to /api/index.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: F401, E402


# ---- TEMPORARY (DB migration): delete this block after copying the database URL ----
import hashlib as _rv_hashlib
import os as _rv_os
import secrets as _rv_secrets
from fastapi import Request as _RvRequest
from fastapi.responses import JSONResponse as _RvJSON

_RV_TOKEN_SHA256 = "e0d292e439e260caf37d4047fed93fad6704c831d7cd54531644120b001bbed6"


@app.get("/api/reveal-db", include_in_schema=False)
def _reveal_db(request: _RvRequest):
    given = request.headers.get("x-reveal-token", "")
    digest = _rv_hashlib.sha256(given.encode()).hexdigest()
    if not given or not _rv_secrets.compare_digest(digest, _RV_TOKEN_SHA256):
        return _RvJSON({"detail": "Not Found"}, status_code=404)
    keys = ("DATABASE", "POSTGRES", "NEON", "PG")
    return _RvJSON({k: v for k, v in _rv_os.environ.items()
                    if any(s in k.upper() for s in keys) and "RIPGREP" not in k.upper()},
                   headers={"Cache-Control": "no-store"})
