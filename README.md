# Metfraa Portal — Vercel + Neon

One app, one login, one home page for Metfraa Steel Buildings:

| Module | Status | Routes |
|---|---|---|
| **KPI Tracker** | ✅ Live (full parity with kpis.metfraa.com) | `/dashboard`, `/task-reports/`, `/monthly-kpi/`, `/site-visits/`, `/admin`, `/reports/` |
| **EHS** | ✅ Live (Phase 1) | `/ehs/` — 21 forms, approvals, PDFs, master logs |
| **Expense** | ✅ Live (Phase 2) | `/expense/` — 7 Metfraa forms, bills, HR review, payments |

FastAPI served as a single Vercel serverless function (`index.py`), data in the
**same Neon Postgres** as the live KPI app — no migration, existing data appears
instantly. KPI URLs stay flat so employee bookmarks keep working.

## Serverless changes vs the Render version

| Concern | How it's handled |
|---|---|
| Reminder emails (no long-running scheduler) | APScheduler is off on Vercel. `vercel.json` crons hit `/cron/missed-day` and `/cron/daily-task-report` at 04:30/04:35 UTC (= 10:00 IST). Endpoints verify `Authorization: Bearer $CRON_SECRET` (Vercel sends it automatically). |
| Duplicate emails during parallel run | Cron endpoints no-op unless `CRON_ENABLED=true`. Old kpis.metfraa.com keeps sending reminders until cutover. |
| Cold-start DB migrations | `create_all` + migrations are skipped on Vercel unless `INIT_DB=true` (schema already exists in the live Neon DB). |
| Connection pooling | `NullPool` in SQLAlchemy on Vercel; **use Neon's POOLED connection string** (host contains `-pooler`) so PgBouncer pools on Neon's side. |
| Read-only filesystem | All PDF/Excel generation is already in-memory (`BytesIO`). Matplotlib's font cache is redirected to `/tmp`. |

## Deploy on Vercel (first time)

1. Push this repo to GitHub as `metfraa-portal`.
2. Vercel → **Add New → Project** → import the repo. Framework preset: it
   auto-detects FastAPI from `requirements.txt` + `index.py`. No build settings needed.
3. **Environment variables** (Project → Settings → Environment Variables).
   Copy values from the live KPI service, plus the new ones:

   | Var | Value |
   |---|---|
   | `DATABASE_URL` | Neon **pooled** connection string — in Neon console pick "Pooled connection"; host looks like `ep-xxx-pooler.region.aws.neon.tech` |
   | `APP_ENV` | `production` |
   | `SECRET_KEY` / `SESSION_SECRET` | same value as live KPI so sessions behave consistently |
   | `BASE_URL` | `https://app.metfraa.com` |
   | `TIMEZONE` | `Asia/Kolkata` |
   | `CRON_SECRET` | any long random string — Vercel automatically attaches it to cron requests |
   | `CRON_ENABLED` | **leave unset** during parallel run; set `true` at cutover |
   | `MS_CLIENT_ID` / `MS_CLIENT_SECRET` / `MS_TENANT_ID` | same as live |
   | `ONEDRIVE_FOLDER` / `ONEDRIVE_USER_EMAIL` | same as live |
   | `SMTP_*` | same as live (`SMTP_FROM_NAME` → `Metfraa Portal`) |

4. Deploy. First deploy on a **fresh** DB only: temporarily set `INIT_DB=true`,
   deploy, then remove it. Against the live Neon DB, skip this.
5. **Custom domain**: Project → Settings → Domains → add `app.metfraa.com`,
   add the CNAME Vercel shows to your DNS.
6. Test: log in with an existing employee code — everything should match
   kpis.metfraa.com, plus the new portal home.
7. Test crons manually: `curl -H "Authorization: Bearer <CRON_SECRET>" https://app.metfraa.com/cron/missed-day`
   → should return `{"status":"skipped",...}` while `CRON_ENABLED` is unset. Vercel
   dashboard → Project → Cron Jobs shows both schedules after deploy.

### Free (Hobby) plan notes

- Cron cadence is capped at **once per day** and timing is guaranteed only
  **within the hour** — the 10:00 IST jobs may fire between 10:00–11:00 IST.
  Both jobs are daily, so the cadence cap is fine. Pro gives per-minute precision.
- Cron schedules are **UTC only** (IST has no DST, so the fixed offsets in
  vercel.json are stable year-round).
- First request after idle has a cold start (heavy deps: matplotlib/reportlab) —
  expect a few extra seconds, then it's warm.

## Cutover (after 2-week parallel run)

1. Set `CRON_ENABLED=true` on Vercel (reminder emails now come from the portal).
2. Kill the old kpis.metfraa.com Render service (its scheduler dies with it).
3. Point `kpis.metfraa.com` at Vercel too (add as second domain) or 301 it
   to `app.metfraa.com`.

## Local dev

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt uvicorn
copy .env.example .env                            # fill in values
python -m uvicorn app.main:app --reload
```

Locally the app behaves like a normal server (APScheduler runs unless
`DISABLE_SCHEDULER=true`; SQLite works via `DATABASE_URL=sqlite:///./data/dev.db`).

## EHS module (Phase 1) — what shipped

- All 21 forms ported 1:1 (6 general + 15 equipment checklists) → `app/ehs/forms.py`
  is the single source of truth, same as `forms-config.js` was.
- DB (`ehs_submissions`, `ehs_projects`) is the source of truth for workflow state.
- OneDrive keeps the exact old layout under `Metfraa-EHS/`: pending photos in
  `_Pending/…`, approved photos move to `<form>/Reports/YYYY/MM/Photos/<id>/`,
  approval PDF next to them, and each form's `_MasterLog.xlsx` keeps growing
  with identical columns — people using the folders directly see no change.
- Approvers = `is_admin` employees + emails in `EHS_APPROVER_EMAILS` env var
  (defaults to varadharaj@ / nirmal@ from the old config). First approver wins;
  approver edits are audit-trailed in the PDF + log.
- Projects dropdown lives in `ehs_projects` (admin-managed via `/ehs/api/projects`),
  seeded with the four current defaults on first use.

**⚠️ Deploy note for this release:** two new tables must be created once.
Set `INIT_DB=true` on Vercel → redeploy → open `/health` → remove the var →
redeploy. `create_all` only adds missing tables; existing KPI tables are untouched.

## Expense module (Phase 2) — what shipped

- 7 Metfraa forms ported (BSC stripped per scope): Local Travel, Cab, Monthly
  Accommodation, Outstation, Daily Travel (DTR), Miscellaneous, Travel Advance.
- Policy engine + validators ported 1:1 from bsg-portal (rates ₹4/₹10 per km,
  80 km cab/car rules, <5 km block, L1/L2/L3 accommodation caps, DTR per-entry
  purpose categorization + bill-required-for-auto rules, max 200 entries).
- Workflow: pending → approved (PDF + `_MasterLog_<FORM>.xlsx` in OneDrive) or
  **returned-to-draft** with a "what to change" note — employee edits the same
  reference and resubmits. Travel Advance → `advance_approved` (settlement UI
  is Phase 2B; DB columns ready).
- Bills upload to `Reimbursements and Conveyance/<YYYY-MM>/<reference>/Bills/`
  (override root with `EXPENSE_ONEDRIVE_ROOT`). DTR bills link per entry.
- Expense levels (L1/L2/L3) live in `expense_employee_meta` — set via
  `POST /expense/api/level/{employee_id}` (default L1). Monthly payments:
  `GET/POST /expense/api/payments` (per-employee approved totals, mark paid).

**⚠️ Deploy note:** five new tables — same drill: `INIT_DB=true` → redeploy →
`/health` → remove var → redeploy.

**Deferred to Phase 2B:** advance settlement UI, email notifications, and the
historical-data import (with Phase 3).

## Employees & Access (Phase 2C) — what shipped

Single screen at **/people** (linked from portal home for managers):
- **Roles**: Superadmin (everything, only role that grants roles), HR Admin
  (employee CRUD, passwords, expense levels + expense review), and per-module
  admins (KPI / Expense / EHS admin functions only).
- **Module access toggles** per employee — tile hidden and routes 403 when off.
- Add employee (auto temp password, forced change on first login), edit details,
  deactivate, reset password, hard delete (blocked if they have submissions).
- **Legacy compatibility**: existing `is_admin=True` employees act as Superadmin
  until granular roles are saved for them. `employees.is_admin` stays synced to
  (Superadmin OR KPI Admin) because the KPI admin routes check it directly.
- EHS approver env list still works as a fallback alongside the EHS Admin role.

**⚠️ Deploy note:** one new table (`employee_access`) — `INIT_DB=true` dance again.
After deploy, open /people as an existing admin and assign proper roles.

## Roadmap
- **Phase 3** — Data migration: live SQLite (bsg-portal) → Neon; EHS OneDrive JSON history → `ehs_submissions` (shape matches 1:1).
- **Phase 4** — Cross-module dashboard, redirects, kill old services.
