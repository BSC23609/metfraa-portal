"""Vercel entrypoint — exposes the FastAPI app as the serverless function handler.

Vercel's Python runtime auto-detects `app` in index.py at the repo root.
All routes (pages, APIs, /static, /cron) are served through this one function.
"""
from app.main import app  # noqa: F401
