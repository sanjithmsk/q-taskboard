# Code Review — q-taskboard backend

Senior-engineer review of the Django REST backend, ranked by business impact and
focused on authorization, data integrity, and query performance. Every finding
was verified against the running app; the two Critical bugs have before/after
HTTP proof (full transcript in [TERMINAL_LOG.md](TERMINAL_LOG.md)). All four
issues below have been **fixed** with regression tests (91 backend tests pass).

## Bug proof (from the running app)

The vulnerable initial commit was run on `:8001`; the fixed code runs on `:8000`.
Same exploit, both targets:

```text
VULNERABLE (:8001)                          FIXED (:8000)
[SQLi]  viewer dumps 5 password hashes  ->  0 rows, no data leaked
        HTTP 200                            HTTP 200
[AuthZ] outsider PATCH -> "PWNED"       ->  HTTP 403, task unchanged
        HTTP 200
```

---

## 1. SQL injection in task search — Critical (Security)

**`backend/projects/views.py`** (task search). The `q` param was interpolated
into raw SQL via an f-string (`title ILIKE '%{q}%'`). **Proven:** a `viewer` on
one project exfiltrated every user's email + password hash with a `UNION SELECT`
(5/5 users leaked). Any authenticated user of any role could read the entire DB.

**Fix:** replaced raw SQL with the ORM's parameterized
`Q(title__icontains=q) | Q(description__icontains=q)` (also escapes LIKE
wildcards). Tests: `projects/test_search_security.py`.

## 2. No authorization on task edit — Critical (Security / AuthZ)

**`backend/projects/views.py`** `TaskDetailView.patch` looked up the task by ID
and mutated it with **no** membership/role check. **Proven:** a non-member of the
project renamed another project's task to "PWNED" and got HTTP 200; viewers could
also edit.

**Fix:** resolve membership via `task.project_id` and enforce
`_can_edit_tasks(role)` (the guard `delete()` already had), placed after the
404 lookup and before input processing. Tests: `projects/test_task_patch_authz.py`.

## 3. Insecure default configuration — High (Security)

**`backend/taskboard/settings.py`** `SECRET_KEY` fell back to a hardcoded value
and signs 30-day JWTs → forgeable tokens; `DEBUG` defaulted on; `ALLOWED_HOSTS`
`['*']` and `CORS_ALLOW_ALL_ORIGINS=True`.

**Fix:** fail fast in production if `SECRET_KEY` is unset/default; `DEBUG` off by
default; hosts/CORS from env; added password validators and login rate-limiting
(all gated on `DEBUG` so dev/tests are unaffected). Tests: `test_settings_hardening.py`.

## 4. No input validation on writes — High (Data integrity)

**`backend/projects/views.py`** task/project writes bypassed serializers, so bad
input hit the DB as unhandled `500`s. **Proven earlier:** `title: null` → 500;
invalid `assigneeId` → 500; over-length fields → 500; `title:"   "` saved a blank
title; `assigneeId` accepted non-members (cross-project assignment + email leak).

**Fix:** DRF write serializers on all create/update paths (`400` on bad input),
including validating `assigneeId` is a project member. Tests: `projects/test_input_validation.py`.

---

## Also noted (lower impact)

- **Performance:** the project list endpoint prefetched every task row just to
  `.count()` — the endpoints are *not* N+1 (constant query counts measured), but
  this over-fetches; use a `Count()` annotation.
- **Data integrity:** email case-sensitivity allows duplicate accounts; task
  `position` can collide when status changes; admin can demote the last admin
  (orphaned project). Left as documented follow-ups.
- **Auth robustness (fixed):** register/login ran `JWTAuthentication` on any
  Bearer header, so a stale token 401'd the sign-in endpoints. Now
  `authentication_classes = []` on those views. Test in `users/tests.py`.
