# TERMINAL_LOG

Chronological evidence for the review, fixes, and features. All output is real,
captured from the running Docker stack (backend `:8000`, Postgres `:5432`,
frontend `:3000`). For the bug proof, the **initial vulnerable commit**
(`32caa63`) was run in a throwaway container on `:8001` against a fresh database,
so the exploit and the fix could be shown side by side.

---

## 1. Setup

```text
$ docker compose up -d --build
SERVICE    STATUS       PORTS
backend    Up           0.0.0.0:8000->8000/tcp
db         Up           0.0.0.0:5432->5432/tcp
frontend   Up           0.0.0.0:3000->3000/tcp

$ docker compose exec backend python manage.py migrate
Operations to perform:
  Apply all migrations: auth, contenttypes, projects, users
Running migrations:
  Applying projects.0002_activity_comment_and_more... OK

$ docker compose exec backend python manage.py seed
login with any of these (password: password123):
  meera@taskboard.dev   — admin on Q3 Launch, Internal Tools
  arjun@taskboard.dev   — admin on Onboarding, member on Q3 Launch
  kavya@example.com     — member on Q3 Launch
  dev@example.com       — viewer on Q3 Launch
  lina@example.com      — member on Onboarding
```

---

## 2. Initial test run (baseline — initial commit `32caa63`)

```text
$ docker compose exec backend python -m pytest
======================= 15 passed, 16 warnings in 2.94s ========================
```

The baseline suite is green but covers only happy paths — none of the security
bugs below are tested, which is why they shipped.

---

## 3. Bug proof (running app — vulnerable initial commit on :8001)

Exploit script logs in as real seeded users and calls the API over HTTP.

```text
### Target: http://localhost:8001

[Bug #1 SQLi] GET tasks?q=<UNION SELECT ... FROM users -->  as VIEWER
  HTTP 200; rows returned: 5; leaked user credential rows: 5
    -> email=meera@taskboard.dev  password_hash=pbkdf2_sha256$1000000$ymVFwi6Yqg...
    -> email=kavya@example.com  password_hash=pbkdf2_sha256$1000000$81QaUnGyUb...
    -> email=lina@example.com  password_hash=pbkdf2_sha256$1000000$mpzDEsHMOu...
  RESULT: VULNERABLE - password hashes exfiltrated

[Bug #2 AuthZ] non-member PATCH /api/tasks/<id> on another project's task
  HTTP 200; title 'Map current onboarding funnel' -> 'PWNED by outsider'
  RESULT: VULNERABLE - outsider edited the task
```

- **Bug #1** — `projects/views.py` task search built raw SQL with an f-string
  (`title ILIKE '%{q}%'`). A `viewer` on any one project dumped every user's
  email + password hash via `UNION SELECT`.
- **Bug #2** — `TaskDetailView.patch` had no authorization; a user who is not a
  member of the project edited its task by ID.

---

## 4. Fix proof (running app — current fixed code on :8000)

Same exploit script, same payloads, against the fixed app:

```text
### Target: http://localhost:8000

[Bug #1 SQLi] GET tasks?q=<UNION SELECT ... FROM users -->  as VIEWER
  HTTP 200; rows returned: 0; leaked user credential rows: 0
  RESULT: SAFE - no user data leaked

[Bug #2 AuthZ] non-member PATCH /api/tasks/<id> on another project's task
  HTTP 403; title 'Map current onboarding funnel' -> 'Map current onboarding funnel'
  RESULT: SAFE - edit blocked
```

- **Fix #1** — search now uses the ORM's parameterized
  `Q(title__icontains=q) | Q(description__icontains=q)` (also escapes LIKE
  wildcards). Regression tests: `projects/test_search_security.py`.
- **Fix #2** — `patch` resolves membership via `task.project_id` and enforces
  `_can_edit_tasks(role)`, matching `delete()`. Tests:
  `projects/test_task_patch_authz.py`.

Also fixed and tested: insecure config / forgeable JWTs (`test_settings_hardening.py`),
missing input validation → 500s (`test_input_validation.py`).

---

## 5. Part 3c — Airtable export (idempotency + resilience)

> The real base run needs an Airtable Personal Access Token (see README /
> DESIGN_NOTES). The export **mechanism, idempotency, and resilience** are shown
> here against the in-memory test double; the endpoint auth + wiring are covered
> by `projects/test_export.py`. Add a token and re-run to push to a live base.

```text
Exporting 7 tasks from project 'Q3 Launch'

First run : {'total': 7, 'created': 7, 'updated': 0, 'failed': 0} | rows in base: 7
Second run: {'total': 7, 'created': 0, 'updated': 7, 'failed': 0} | rows in base: 7
=> re-run is idempotent: second run updated in place, NO duplicates

Resilience run: {'total': 7, 'created': 6, 'updated': 0, 'failed': 1}
  - permanent failure isolated (not retried), transient retried and succeeded
  - errors: [('Record demo video', '422 UNKNOWN_FIELD')]
```

The **second run** creates 0 and updates 7 with the row count unchanged — proof
that re-running does not duplicate. The resilience run shows a permanent error on
one record isolated (export continues) while a transient error is retried.

*(Airtable screenshot / share link of the live base to be attached here after the
real run — see the recording.)*

---

## 6. Part 3a — Task comments  &  Part 3b — Activity feed

```text
== Part 3a: Task comments ==
member posts: 201
admin posts : 201
viewer posts (want 403): 403
viewer reads (want 200): 200; thread (chronological):
   [2026-09-24T05:18:24] Arjun Rao: Kicking this off.
   [2026-09-24T05:18:24] Meera Iyer: Reviewed, looks good.

== Part 3b: Activity feed (most-recent-first, member-only) ==
admin reads feed: 200
   [2026-09-24T05:18:24] Meera Iyer assigned "Finalize launch date with marketing" to Arjun Rao
   [2026-09-24T05:18:24] Meera Iyer moved "Finalize launch date with marketing" from done to review
   [2026-09-24T05:18:24] Meera Iyer commented on "Finalize launch date with marketing"
   [2026-09-24T05:18:24] Arjun Rao commented on "Finalize launch date with marketing"
non-member reads feed (want 403): 403
```

Comments are append-only (no edit/delete route; PATCH/DELETE → 405), chronological,
member-post / viewer-read. Activity is scoped per project, most-recent-first,
member-only. Tests: `projects/test_comments_activity.py` (incl. atomic rollback).

---

## 7. Final test run (current code)

```text
$ docker compose exec backend python -m pytest         # Django
====================== 91 passed, 142 warnings in 38.94s =======================

$ docker compose exec frontend npm test                # React
 Test Files  2 passed (2)
      Tests  9 passed (9)
```
