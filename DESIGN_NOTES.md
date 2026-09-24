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
