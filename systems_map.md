# BetterUp Onboarding — Systems Map

## Where the data lives today

| System | What it owns | Update mechanism |
|---|---|---|
| **Ashby** | Source of truth for candidate: name, email, start date, location, offer details | Webhook on record change |
| **Workday** | HRIS: legal name, hire date, job title, department, home address, work location | SOAP/REST API (`Change_Job`, `Hire_Employee`) |
| **Okta / Lumos** | Identity: email, display name, group membership (department-based) | Okta REST API PATCH `/users/{id}` |
| **ExpoIT** | Equipment orders: recipient name, shipping address, delivery date | REST API order update |
| **Cohort Tracker** | Google Sheet / internal DB tracking start-date cohorts, office, title | Internal API or Sheets API |
| **Slack** | Communication: display name, profile photo | Only updated on Okta SCIM sync — indirect |

---

## Where it breaks today

```
Ashby (recruiter edits a field)
       │
       │   ← NO WEBHOOK HANDLER TODAY →
       │
  Recruiter manually:
  ├── Opens Workday → updates hire date
  ├── Emails IT → they update ExpoIT order
  ├── Pings someone in Slack → Okta gets updated (maybe)
  └── Updates the cohort tracker spreadsheet (if they remember)
```

**Three failure modes:**

1. **Change propagation failure** — A recruiter changes a start date in Ashby.
   Unless someone catches it, Workday stays on the old date, ExpoIT ships
   equipment to the wrong address window, and the cohort report is wrong.

2. **Bad data cascade** — A botched import puts "J0hn Sm1th" in Ashby.
   It flows into Workday (legal name on payroll), Okta (email prefix), and
   ExpoIT (shipping label) before anyone notices.

3. **Deadline monitoring gap** — IT hardware form, background check, and
   Okta provisioning all have ~7-day windows. No system watches them.
   A recruiter manually follows up, if at all.

---

## The slice I chose: **Change Propagation**

### Why this slice over the others

| Slice | Leverage | Why not first |
|---|---|---|
| **Change propagation** ← chose this | Highest | Root cause of the other two problems |
| Exception monitoring | Medium | Valuable but reactive — doesn't fix bad data |
| Cross-system validation | Medium | Needs propagation to be useful |

Change propagation is the load-bearing problem. If a change made in Ashby
reliably flows to all downstream systems, bad-data cascades become detectable
(you can diff the propagation result against expected values) and deadline
monitoring becomes tractable (you know the hire date is correct before you
start the clock). The other two slices are built on top of a working
propagation layer.

---

## Data flow with the prototype

```
Ashby webhook (POST /webhooks/ashby)
        │
        ▼
  Idempotency check  ──── duplicate? ──→  skip (200 OK, logged)
        │ new
        ▼
  Claude assessment
  ├── auto_propagate  ──────────────────────────────────────────┐
  ├── hold_for_review  ──→  logged, no downstream writes        │
  └── reject           ──→  logged, no downstream writes        │
                                                                 │
                              parallel dispatch ◄────────────────┘
                              ├── Workday  (hire_date / legal_name / …)
                              ├── Okta     (startDate / displayName / …)
                              ├── ExpoIT   (delivery_date / shipping_address)
                              └── CohortTracker (start_date / office / …)
                                       │
                                       ▼  retry up to 3× on failure
                              Audit log (SQLite)
                              Mark event processed (idempotency store)
```

---

## Change routing table

| Change type | Workday | Okta | ExpoIT | Cohort Tracker |
|---|:---:|:---:|:---:|:---:|
| start_date | ✓ | ✓ | ✓ | ✓ |
| name | ✓ | ✓ | ✓ | ✓ |
| address | ✓ | — | ✓ | — |
| location | ✓ | ✓ | ✓ | ✓ |
| title | ✓ | — | — | ✓ |
| department | ✓ | ✓ | — | ✓ |
