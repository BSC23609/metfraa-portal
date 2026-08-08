#!/usr/bin/env python3
"""Report EHS submissions whose form_id doesn't match the form registry.

Read-only — it changes nothing. Run it to find out WHY a submission showed
"Unknown form" on the review screen.

    set "DATABASE_URL=<your Neon connection string>"
    python scripts\\check_ehs_forms.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERROR: DATABASE_URL is not set. Copy it from Vercel > Settings > "
             "Environment Variables and `set` it first.")

from app.database import SessionLocal            # noqa: E402
from app.ehs.forms import ALL_FORMS, FORMS_BY_ID  # noqa: E402
from app.models import EHSSubmission              # noqa: E402

db = SessionLocal()
rows = db.query(EHSSubmission).all()
by_code = {(f.get("code") or "").upper(): f for f in ALL_FORMS}

known, by_code_only, orphans = Counter(), Counter(), Counter()
orphan_examples = {}
pending_orphans = []

for s in rows:
    fid = s.form_id or ""
    if fid in FORMS_BY_ID:
        known[fid] += 1
        continue
    slug = fid.strip().lower().replace("_", "-")
    code = (s.form_code or "").strip().upper()
    if slug in FORMS_BY_ID or code in by_code:
        by_code_only[fid] += 1
        orphan_examples.setdefault(fid, s.submission_id)
    else:
        orphans[fid] += 1
        orphan_examples.setdefault(fid, s.submission_id)
    if s.status == "pending":
        pending_orphans.append((fid, s.submission_id, s.form_title, s.submitted_at_ist))

print("=" * 74)
print(f"EHS FORM CHECK — {len(rows)} submissions, {len(FORMS_BY_ID)} forms in the registry")
print("=" * 74)

print(f"\n[1] form_id matches the registry ({sum(known.values())} rows)")
for k, n in known.most_common():
    print(f"    {k:28} {n}")

print(f"\n[2] form_id does NOT match, but resolves by slug/code ({sum(by_code_only.values())} rows)")
if by_code_only:
    print("    These used to show 'Unknown form'. They now resolve correctly.")
    for k, n in by_code_only.most_common():
        print(f"    {k:28} {n:5}  e.g. {orphan_examples.get(k)}")
else:
    print("    none")

print(f"\n[3] UNRECOGNISED — no registry match at all ({sum(orphans.values())} rows)")
if orphans:
    print("    These render from their stored fields, but cannot produce a PDF")
    print("    or a master-log row on approval. Tell Claude these form_ids.")
    for k, n in orphans.most_common():
        print(f"    {k:28} {n:5}  e.g. {orphan_examples.get(k)}")
else:
    print("    none")

if pending_orphans:
    print(f"\n[!] PENDING submissions affected ({len(pending_orphans)}) — these are the")
    print("    ones a reviewer is blocked on right now:")
    for fid, sid, title, when in pending_orphans[:25]:
        print(f"    {when or '':20} {fid:24} {sid:28} {title or ''}")
    if len(pending_orphans) > 25:
        print(f"    ... and {len(pending_orphans) - 25} more")
else:
    print("\n[ok] No pending submissions are affected.")

db.close()
