#!/usr/bin/env python3
"""Find employees that appear more than once, which splits their monthly wrap-up.

Read-only. The monthly summary groups submissions by employee_id, so two rows
for one person means two employee records. This lists them and shows how each
duplicate's submissions are spread, so you can decide which record to keep.

    set "DATABASE_URL=<your Neon connection string>"
    python scripts\\check_duplicate_employees.py
    python scripts\\check_duplicate_employees.py --name vivek     # focus on one
"""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERROR: DATABASE_URL is not set. Copy it from Vercel and `set` it first.")

from app.database import SessionLocal            # noqa: E402
from app.models import Employee, ExpenseSubmission  # noqa: E402


def _norm_email(e):
    return (e or "").strip().lower()


def _norm_name(n):
    return re.sub(r"\s+", " ", (n or "").strip().lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="", help="only show employees matching this")
    args = ap.parse_args()

    db = SessionLocal()
    emps = db.query(Employee).all()

    # submission counts per employee_id
    sub_by_emp = defaultdict(lambda: {"total": 0, "periods": defaultdict(int)})
    for s in db.query(ExpenseSubmission).all():
        b = sub_by_emp[s.employee_id]
        b["total"] += 1
        b["periods"][s.period] += 1

    # group employees by email, then by name, to catch both kinds of duplicate
    by_email = defaultdict(list)
    by_name = defaultdict(list)
    for e in emps:
        if _norm_email(e.email):
            by_email[_norm_email(e.email)].append(e)
        by_name[_norm_name(e.name)].append(e)

    flt = args.name.strip().lower()
    dupes = []
    seen = set()
    for key, group in list(by_email.items()) + list(by_name.items()):
        if len(group) < 2:
            continue
        ids = tuple(sorted(e.id for e in group))
        if ids in seen:
            continue
        seen.add(ids)
        if flt and not any(flt in _norm_name(e.name) or flt in _norm_email(e.email)
                           for e in group):
            continue
        dupes.append(group)

    W = 78
    print("=" * W)
    print(f"DUPLICATE EMPLOYEES  ({len(emps)} employees total)")
    print("=" * W)

    if not dupes:
        print("\nNo duplicates found" + (f" matching {args.name!r}." if flt else "."))
        db.close()
        return

    for group in sorted(dupes, key=lambda g: _norm_name(g[0].name)):
        print(f"\n{'-' * W}\n{group[0].name!r} — {len(group)} records:")
        # the record with the most submissions is the natural "keep"
        ranked = sorted(group, key=lambda e: sub_by_emp[e.id]["total"], reverse=True)
        for i, e in enumerate(ranked):
            b = sub_by_emp[e.id]
            tag = "  <- KEEP (most submissions)" if i == 0 and b["total"] else ""
            per = ", ".join(f"{p}:{n}" for p, n in sorted(b["periods"].items()))
            print(f"    id={e.id:<5} code={e.employee_code or '—':<10} "
                  f"{e.email or '(no email)':<28} active={int(bool(e.is_active))} "
                  f"subs={b['total']}{tag}")
            if per:
                print(f"          submissions: {per}")

    print(f"\n{'=' * W}")
    print("To merge (move the stray submissions onto the KEEP record, then\n"
          "deactivate the empty duplicate), run:\n"
          "    python scripts/merge_employee.py --from <stray_id> --into <keep_id>\n"
          "It shows a dry-run first and writes nothing without --apply.")
    print("=" * W)
    db.close()


if __name__ == "__main__":
    main()
