"""Airtable export: a thin real gateway around pyairtable plus the orchestration
(idempotent upsert, retry on transient errors, per-record failure isolation).

The orchestration in `run_export` talks only to a small gateway interface
(`existing_task_ids`, `create`, `update`), so it can be unit-tested against the
in-memory double in `airtable_mock.py` without any network access.
"""
import time

DEFAULT_TABLE = 'Tasks'
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BASE_DELAY = 0.5  # seconds; exponential backoff


class AirtableConfigError(Exception):
    """Raised when Airtable credentials/config are missing."""


def task_to_fields(task):
    """Map a Task model instance to an Airtable record's fields.

    `TaskId` is the stable key used for idempotent upserts across runs.
    """
    return {
        'TaskId': str(task.id),
        'Title': task.title,
        'Description': task.description or '',
        'Status': task.status,
        'Assignee': task.assignee.name if task.assignee else '',
        'Position': task.position,
        'CreatedAt': task.created_at.isoformat(),
    }


def airtable_is_transient(exc):
    """Classify a pyairtable/requests exception as transient (retry) or not."""
    import requests
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    resp = getattr(exc, 'response', None)
    return getattr(resp, 'status_code', None) in TRANSIENT_HTTP_STATUS


class AirtableGateway:
    """Real gateway backed by the official pyairtable client. One Airtable
    operation per method so retries can be applied around each call."""

    def __init__(self, api_key, base_id, table_name):
        from pyairtable import Api
        self._table = Api(api_key).table(base_id, table_name)

    def existing_task_ids(self):
        """Return {TaskId: airtable_record_id} for rows already in the table."""
        mapping = {}
        for rec in self._table.all(fields=['TaskId']):
            tid = rec.get('fields', {}).get('TaskId')
            if tid:
                mapping[str(tid)] = rec['id']
        return mapping

    def create(self, fields):
        return self._table.create(fields, typecast=True)

    def update(self, record_id, fields):
        return self._table.update(record_id, fields, typecast=True)


def build_gateway_from_settings():
    from django.conf import settings
    key = getattr(settings, 'AIRTABLE_API_KEY', '')
    base = getattr(settings, 'AIRTABLE_BASE_ID', '')
    table = getattr(settings, 'AIRTABLE_TABLE_NAME', '') or DEFAULT_TABLE
    if not (key and base):
        raise AirtableConfigError(
            'Airtable is not configured. Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID '
            '(and optionally AIRTABLE_TABLE_NAME) in the backend environment.'
        )
    return AirtableGateway(key, base, table)


def _retry(fn, *, is_transient, sleep, max_attempts=MAX_ATTEMPTS, base_delay=BASE_DELAY):
    """Call fn(); retry with exponential backoff only for transient errors."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised unless transient
            if attempt < max_attempts and is_transient(exc):
                sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise


def run_export(tasks, gateway, *, is_transient=airtable_is_transient, sleep=time.sleep,
               max_attempts=MAX_ATTEMPTS):
    """Push tasks to Airtable idempotently and return a summary.

    - Idempotent: one read of existing rows keyed by TaskId decides create vs
      update, so re-running never duplicates. A permanent failure on that read
      aborts the export (we can't safely upsert without knowing current state).
    - Resilient: each record is upserted independently; transient errors are
      retried, permanent errors are not, and a single record's failure is
      recorded without aborting the rest.
    """
    existing = _retry(
        lambda: gateway.existing_task_ids(),
        is_transient=is_transient, sleep=sleep, max_attempts=max_attempts,
    )

    summary = {'total': len(tasks), 'created': 0, 'updated': 0, 'failed': 0, 'errors': []}
    for task in tasks:
        fields = task_to_fields(task)
        task_id = fields['TaskId']
        record_id = existing.get(task_id)
        try:
            if record_id:
                _retry(lambda: gateway.update(record_id, fields),
                       is_transient=is_transient, sleep=sleep, max_attempts=max_attempts)
                summary['updated'] += 1
            else:
                _retry(lambda: gateway.create(fields),
                       is_transient=is_transient, sleep=sleep, max_attempts=max_attempts)
                summary['created'] += 1
        except Exception as exc:  # noqa: BLE001 - single-record isolation
            summary['failed'] += 1
            summary['errors'].append(
                {'taskId': task_id, 'title': fields['Title'], 'error': str(exc)}
            )
    return summary
