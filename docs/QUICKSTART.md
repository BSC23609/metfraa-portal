# 🚀 First Run — Quick Cheat Sheet

The fastest path from zero to running. ~5 minutes.

## On your laptop (test it works)

```bash
# 1. Get into the project
cd metfraa-kpi

# 2. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Set up .env (just for local testing — leave most fields blank)
cp .env.example .env
# Open .env in any editor, set SECRET_KEY to something random.
# Leave MS_CLIENT_ID etc empty for now.

# 4. Initialize DB + seed all 8 employees
python scripts/init_db.py

# 5. Run!
uvicorn app.main:app --reload
```

Open <http://localhost:8000> → click **Dev login (no SSO)** at the bottom → pick any account → you're in.

Try it: submit a daily entry as Nirmal, log in as another employee, view the admin panel as info@metfraa.com.

---

## Then: real Microsoft login (when you're ready)

Follow `README.md` § *Microsoft 365 / Azure AD setup* — takes ~10 min in the Azure portal.

After that, set in `.env`:
```
MS_CLIENT_ID=<from Azure>
MS_CLIENT_SECRET=<from Azure>
MS_TENANT_ID=<from Azure>
```

Restart `uvicorn` and the "Sign in with Microsoft 365" button will work.

---

## Then: deploy to Render

1. Push to GitHub.
2. Go to <https://render.com> → New → Blueprint → paste repo URL.
3. Set the secret env vars (Microsoft IDs, SMTP password, etc.).
4. Apply. Done.

Update Azure with the production redirect URI: `https://your-app.onrender.com/auth/callback`.

---

## Daily routine for employees

- Sign in once a day (any time, but reminder goes out at 8:30 PM).
- Pick today's date (defaults to today).
- Pick day type: 🏗️ Work / 🏖️ Leave / 🚛 Site-Remote / ☀️ Sunday / 🎉 Holiday.
- If "Work": enter the count for each KPI.
- Optional: jot a comment.
- Hit **Submit & Lock**.

That's it. You can backfill yesterday/last week the same way — but once submitted, it's locked.

---

## When the month ends

- The last entry of the month auto-unlocks the **"Generate this month's PDF"** button on the Reports tab.
- Click it. Wait ~5 seconds. PDF is generated, uploaded to OneDrive, and available for download.
- File goes to OneDrive: `KPI_Tracker/Reports/2026-05/Nirmal_Kumar_AGM_May_2026.pdf`

Admins can also manually generate or re-generate any report from the admin panel.
