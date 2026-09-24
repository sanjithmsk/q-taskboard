# Design Notes

## Activity feed: does the primary change roll back if the audit write fails?

**Yes — the change and its activity record commit or roll back together.** Each
mutation (task create, status/assignee change, comment add) wraps the domain
write and the `Activity` write in a single `transaction.atomic()` block, so a
failed audit insert aborts the whole request.

**Reasoning:** The brief frames activity as an audit trail where *every*
meaningful change leaves a record, and comments explicitly as part of the
engagement audit trail — a change that silently isn't recorded would corrupt the
trail's completeness, which for an audit/compliance use case is worse than
failing loudly and letting the client retry. Both writes hit the same Postgres
database in the same request, so atomicity is essentially free and gives a clean
all-or-nothing guarantee; the alternative (best-effort logging) trades audit
integrity for availability, which is the wrong trade here. If the feed were later
fed by a separate store (e.g. a queue or analytics DB), I'd revisit this and move
to best-effort writes with a durable outbox rather than coupling core writes to a
remote system's availability.

## Comments are append-only

There is intentionally no PATCH/DELETE route for comments and the model exposes
no edit path — enforced at the API surface (only GET/POST on
`/api/tasks/<id>/comments`). Authorization: any project member may read; only
admins/members may post; viewers are read-only.

## Airtable export

**Endpoint:** `POST /api/projects/<id>/export` — members only (admin/member; viewers
403). Implemented in Django with `pyairtable` (real API calls); orchestration in
`projects/airtable_client.py`, in-memory test double in `projects/airtable_mock.py`.

**Idempotent (safe to re-run):** the export reads existing rows once, keyed by a
`TaskId` field (the task UUID), and updates matches / creates the rest — re-running
never duplicates. If that initial read fails permanently the export aborts (we
can't upsert safely without knowing current state).

**Resilient:** each record is upserted independently. Transient errors
(429/5xx, connection/timeout) are retried with exponential backoff; permanent
errors (4xx like 401/422) are not retried; a single record's failure is recorded
in the response (`failed`, `errors[]`) without aborting the rest. Partial success
returns HTTP 207.

**Setup for a real run:**
1. In the target Airtable base, create a table (default name `Tasks`) with these
   fields: `TaskId` (single line text), `Title` (single line text), `Description`
   (long text), `Status` (single line text), `Assignee` (single line text),
   `Position` (number), `CreatedAt` (single line text). Unknown fields cause a
   permanent 422 per record.
2. Put credentials in a `.env` file next to `docker-compose.yml`:
   `AIRTABLE_API_KEY=pat...`, `AIRTABLE_BASE_ID=app...`, `AIRTABLE_TABLE_NAME=Tasks`.
3. `docker compose up -d backend` (compose auto-loads `.env`), then trigger the
   export from the project detail page or `POST /api/projects/<id>/export`.
