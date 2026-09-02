#!/usr/bin/env python3
"""Move every trace of one (duplicate) employee onto another, then deactivate it.

Use after check_duplicate_employees.py identifies a split. Moves expense
submissions, attachments-via-submission, monthly payments, meta, and gatepass
links from --from onto --into, so the person's history is unified under one id.

Dry run by default. Nothing is written without --apply. Never deletes the
duplicate — it is deactivated, so the record and any audit trail survive.

    set "DATABASE_URL=<your Neon connection string>"
    python scripts\\merge_employee.py --from 57 --into 40           # preview
    python scripts\\merge_employee.py --from 57 --into 40 --apply   # do it
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERROR: DATABASE_URL is not set. Copy it from Vercel and `set` it first.")

from app.database import SessionLocal  # noqa: E402
from app.models import (Employee, ExpenseEmployeeMeta, ExpenseMonthlyPayment,  # noqa: E402
                        ExpenseSubmission)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", type=int, required=True,
                    help="the duplicate id to empty out")
    ap.add_argument("--into", dest="dst", type=int, required=True,
                    help="the id to keep")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.src == args.dst:
        sys.exit("--from and --into must differ.")

    db = SessionLocal()
    src = db.query(Employee).filter(Employee.id == args.src).first()
    dst = db.query(Employee).filter(Employee.id == args.dst).first()
    if not src or not dst:
        sys.exit("One of those employee ids does not exist.")

    subs = db.query(ExpenseSubmission).filter(ExpenseSubmission.employee_id == args.src).all()
    pays = db.query(ExpenseMonthlyPayment).filter(
        ExpenseMonthlyPayment.employee_id == args.src).all()
    metas = db.query(ExpenseEmployeeMeta).filter(
        ExpenseEmployeeMeta.employee_id == args.src).all()

    # Optional models — present only if the gatepass module is installed.
    gate_rows = []
    try:
        from app.models import EmployeeApprover, OutpassRequest
        gate_rows = [
            ("outpass requester", db.query(OutpassRequest).filter(
                OutpassRequest.requester_id == args.src).all()),
            ("outpass approver", db.query(OutpassRequest).filter(
                OutpassRequest.approver_id == args.src).all()),
            ("approver-of override", db.query(EmployeeApprover).filter(
                EmployeeApprover.approver_emp_id == args.src).all()),
        ]
    except Exception:
        pass

    W = 74
    print("=" * W)
    print("MERGE  " + ("(APPLY)" if args.apply else "(DRY RUN — nothing written)"))
    print("=" * W)
    print(f"FROM  id={src.id}  {src.name!r}  {src.email}  code={src.employee_code}")
    print(f"INTO  id={dst.id}  {dst.name!r}  {dst.email}  code={dst.employee_code}")
    print(f"\n  expense submissions : {len(subs)}")
    print(f"  monthly payments    : {len(pays)}")
    print(f"  expense meta rows   : {len(metas)}")
    for label, rows in gate_rows:
        if rows:
            print(f"  {label:19} : {len(rows)}")

    # Payment collision: both ids already paid the same month.
    dst_pay_keys = {(p.year, p.month) for p in db.query(ExpenseMonthlyPayment)
                    .filter(ExpenseMonthlyPayment.employee_id == args.dst).all()}
    clashes = [(p.year, p.month) for p in pays if (p.year, p.month) in dst_pay_keys]
    if clashes:
        print(f"\n  [!] payment clash on {clashes} — the FROM record's payment for "
              "these months\n      will be dropped (the INTO record already has one).")

    if not args.apply:
        print("\nRe-run with --apply to perform the merge.")
        db.close()
        return

    moved_pay = 0
    for p in pays:
        if (p.year, p.month) in dst_pay_keys:
            db.delete(p)          # keep the destination's existing payment
        else:
            p.employee_id = args.dst
            moved_pay += 1
    for s in subs:
        s.employee_id = args.dst
        # keep the denormalised copies consistent with the kept record
        s.employee_name = dst.name
        s.employee_email = dst.email
    # meta: keep the destination's if it has one, else move
    dst_meta = db.query(ExpenseEmployeeMeta).filter(
        ExpenseEmployeeMeta.employee_id == args.dst).first()
    for m in metas:
        if dst_meta:
            db.delete(m)
        else:
            m.employee_id = args.dst
            dst_meta = m
    for label, rows in gate_rows:
        for r in rows:
            if hasattr(r, "requester_id") and r.requester_id == args.src:
                r.requester_id = args.dst
            if hasattr(r, "approver_id") and r.approver_id == args.src:
                r.approver_id = args.dst
            if hasattr(r, "approver_emp_id") and r.approver_emp_id == args.src:
                r.approver_emp_id = args.dst

    src.is_active = False          # never deleted, just retired
    db.commit()
    print(f"\nMerged: {len(subs)} submissions, {moved_pay} payments moved. "
          f"id={src.id} deactivated.")
    print("Re-run check_duplicate_employees.py to confirm the split is gone.")
    db.close()


if __name__ == "__main__":
    main()
