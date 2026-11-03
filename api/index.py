"""Vercel entrypoint — all routes serve through this one function.

Lives in api/ because Vercel reliably builds Python functions here regardless
of framework detection. vercel.json rewrites every path to /api/index.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: F401, E402
