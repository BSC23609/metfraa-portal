# WATI templates — Metfraa Outpass / Gatepass

Create these five in the **Metfraa** WATI account. The BSC ones can't be reused:
they carry BSC branding and live in a different account.

## Rules that matter

**Category must be UTILITY, not Marketing.** Utility templates are exempt from
Meta's per-user frequency cap. If these get classified as Marketing, alerts will
be silently throttled — which is exactly the failure that's hardest to notice.
Keep the wording purely transactional: no greetings-as-marketing, no promotion,
no company slogan. A sign-off line like "Metfraa Steel Buildings" is fine.

**Variable names must match exactly.** The app sends parameters *by name*, not
by position. A template with `{{employee_name}}` where the app sends `employee`
will be declined by WATI with a parameter mismatch — and the send returns
HTTP 200, so nothing looks wrong until someone asks why they got no message.
Check the delivery log at **/gatepass → Admin → WhatsApp delivery** after the
first real send.

**No newlines inside a variable.** The app already strips them, but don't build
templates that expect multi-line values.

---

## 1. `met_outpass_request` → the approver

Sent when an employee raises a pass. Goes to the department head.

**Variables:** `name`, `ref`, `requester`, `type`, `purpose`, `date`, `out_time`

```
Hi {{name}}, a pass request needs your approval.

Employee: {{requester}}
Type: {{type}}
Date: {{date}}
Out time: {{out_time}}
Purpose: {{purpose}}
Ref: {{ref}}

Please review it in the Metfraa Portal.
```

---

## 2. `met_outpass_approved` → the requester

**Variables:** `name`, `ref`, `type`, `approver`

```
Hi {{name}}, your {{type}} has been approved by {{approver}}.

Ref: {{ref}}

If this is a gatepass, please record your return in the Metfraa Portal when you
are back.
```

---

## 3. `met_outpass_rejected` → the requester

**Variables:** `name`, `ref`, `type`, `approver`, `reason`

```
Hi {{name}}, your {{type}} was not approved by {{approver}}.

Reason: {{reason}}
Ref: {{ref}}

Please speak to your manager if you need to raise it again.
```

---

## 4. `met_outpass_overdue` → approver and HR

Sent when a gatepass passes its declared in-time with no return recorded.

**Variables:** `name`, `employee`, `ref`, `out_time`, `expected`, `overdue_min`,
`purpose`, `duty`

```
Hi {{name}}, a gatepass has not been returned.

Employee: {{employee}}
Out time: {{out_time}}
Expected back: {{expected}}
Overdue by: {{overdue_min}} minutes
Purpose: {{purpose}}
Category: {{duty}}
Ref: {{ref}}

No return has been recorded in the Metfraa Portal.
```

---

## 5. `met_gatepass_return_reminder` → the requester

**Variables:** `name`, `ref`, `out_time`, `expected`, `overdue_min`

```
Hi {{name}}, your gatepass is still showing as open.

Out time: {{out_time}}
Expected back: {{expected}}
Overdue by: {{overdue_min}} minutes
Ref: {{ref}}

If you are back, please record your return in the Metfraa Portal so it does not
show as overdue.
```

---

## Environment variables

Set in Vercel → Settings → Environment Variables:

| Variable | Value |
|---|---|
| `WATI_BASE_URL` | Metfraa's WATI API endpoint, e.g. `https://live-server-XXXX.wati.io` |
| `WATI_TOKEN` | the Metfraa WATI access token |
| `GATEPASS_HR_PHONE` | HR's WhatsApp number for overdue alerts |
| `GATEPASS_HR_NAME` | the name used in the greeting, e.g. `Rajasekar` |

The template names above are the defaults, so no further variables are needed if
you register them with these exact names. If Meta approves one under a different
name, override just that one:

`WATI_OUTPASS_REQUEST_TPL`, `WATI_OUTPASS_APPROVED_TPL`,
`WATI_OUTPASS_REJECTED_TPL`, `WATI_OVERDUE_TPL`, `WATI_RETURN_REMINDER_TPL`

---

## Before staff use it

1. Register all five, wait for Meta approval (usually minutes, occasionally a day).
2. Set the environment variables and redeploy.
3. Raise one test gatepass end to end — request, approve, record return.
4. Open **/gatepass → Admin → WhatsApp delivery**. Every row should say `sent`.
   - `declined` → the template name or a variable name doesn't match
   - `no_phone` → that employee has no phone number in `/people`
   - `skipped` → `WATI_BASE_URL` / `WATI_TOKEN` aren't set

Until WATI is configured the module still works — email notifications go out and
sends are logged as `skipped` rather than failing.

---

## Scheduling the overdue check

`/cron/gatepass-overdue` is **not** in `vercel.json`. Vercel Hobby allows only
one cron run per day, and a daily check is useless for a pass due back at 3pm.
BSC also found Vercel's scheduler fired unreliably, so an external pinger is the
better answer regardless of plan.

**Set it up on [cron-job.org](https://cron-job.org):**

| Field | Value |
|---|---|
| URL | `https://app.metfraa.com/cron/gatepass-overdue` |
| Schedule | every 15 minutes |
| Request method | GET |
| Header | `Authorization: Bearer <your CRON_SECRET>` |

Add the header under **Advanced → Headers**. The value must match the
`CRON_SECRET` environment variable in Vercel exactly, or the endpoint returns
401.

Calling it often is safe. Each recipient has its own stamp, and a stamp is only
set once a channel actually delivered — so extra runs do nothing, and a send
that failed is retried on the next run rather than being lost.

**To check it's working:** open the cron-job.org execution history. A healthy
run returns 200 with a body like
`{"ok":true,"checked":3,"approver":1,"hr":1,"requester":1,"whatsapp":true}`.
A 401 means the header doesn't match; a 503 means `CRON_SECRET` isn't set in
Vercel.
