"""In-memory Airtable test double for unit tests.

This is NOT a substitute for the real integration (see `AirtableGateway` in
`airtable_client.py`); it only lets `run_export` be tested deterministically,
including retry and per-record failure behaviour, without any network access.
"""


class TransientError(Exception):
    """Simulated retryable Airtable failure (e.g. 429/5xx)."""


class PermanentError(Exception):
    """Simulated non-retryable Airtable failure (e.g. 401/422)."""


def is_transient(exc):
    """Classifier matching the test double's error types."""
    return isinstance(exc, TransientError)


class FakeAirtableGateway:
    """Implements the gateway interface used by run_export, backed by dicts.

    Failure injection: assign lists of exceptions to `existing_failures`,
    `create_failures[task_id]`, or `update_failures[task_id]`; one is raised
    (popped) per call, so `[TransientError(), TransientError()]` fails twice
    then succeeds on the third attempt.
    """

    def __init__(self, existing_task_ids=None):
        self._records = {}          # record_id -> fields
        self._by_task = {}          # TaskId -> record_id
        self._seq = 0
        self.calls = {'existing': 0, 'create': 0, 'update': 0}
        self.create_failures = {}
        self.update_failures = {}
        self.existing_failures = []
        for tid in (existing_task_ids or []):
            self._insert(str(tid), {'TaskId': str(tid)})

    def _insert(self, task_id, fields):
        record_id = f'rec{self._seq:05d}'
        self._seq += 1
        self._records[record_id] = dict(fields)
        self._by_task[task_id] = record_id
        return record_id

    def existing_task_ids(self):
        self.calls['existing'] += 1
        if self.existing_failures:
            raise self.existing_failures.pop(0)
        return dict(self._by_task)

    def create(self, fields):
        self.calls['create'] += 1
        task_id = str(fields.get('TaskId'))
        queue = self.create_failures.get(task_id)
        if queue:
            raise queue.pop(0)
        return {'id': self._insert(task_id, fields), 'fields': fields}

    def update(self, record_id, fields):
        self.calls['update'] += 1
        task_id = str(fields.get('TaskId'))
        queue = self.update_failures.get(task_id)
        if queue:
            raise queue.pop(0)
        self._records[record_id] = dict(fields)
        return {'id': record_id, 'fields': fields}

    # --- test helpers -----------------------------------------------------
    def all_records(self):
        return list(self._records.values())

    def record_count(self):
        return len(self._records)
