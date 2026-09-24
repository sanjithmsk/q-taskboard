import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from users.models import User
from projects.models import Project, Membership, Task
from projects.airtable_client import run_export, task_to_fields, airtable_is_transient
from projects.airtable_mock import FakeAirtableGateway, TransientError, PermanentError, is_transient

NO_SLEEP = lambda _s: None


def auth(email):
    c = APIClient()
    r = c.post('/api/auth/login', {'email': email, 'password': 'password123'}, format='json')
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['token']}")
    return c


@pytest.fixture
def project_with_tasks(db):
    admin = User.objects.create_user(email='admin@x.dev', name='Admin', password='password123')
    member = User.objects.create_user(email='member@x.dev', name='Member', password='password123')
    viewer = User.objects.create_user(email='viewer@x.dev', name='Viewer', password='password123')
    outsider = User.objects.create_user(email='out@x.dev', name='Out', password='password123')
    p = Project.objects.create(name='P', owner=admin)
    Membership.objects.create(user=admin, project=p, role='admin')
    Membership.objects.create(user=member, project=p, role='member')
    Membership.objects.create(user=viewer, project=p, role='viewer')
    tasks = [
        Task.objects.create(project=p, title=f'Task {i}', status='todo', created_by=admin,
                            assignee=(member if i == 0 else None), position=i)
        for i in range(3)
    ]
    return dict(p=p, tasks=tasks, admin=admin, member=member, viewer=viewer, outsider=outsider)


# ---- orchestration (unit, via the test double) --------------------------------

@pytest.mark.django_db
class TestRunExport:
    def test_creates_all_on_first_run(self, project_with_tasks):
        gw = FakeAirtableGateway()
        s = run_export(project_with_tasks['tasks'], gw, is_transient=is_transient, sleep=NO_SLEEP)
        assert (s['created'], s['updated'], s['failed']) == (3, 0, 0)
        assert gw.record_count() == 3

    def test_second_run_is_idempotent(self, project_with_tasks):
        gw = FakeAirtableGateway()
        run_export(project_with_tasks['tasks'], gw, is_transient=is_transient, sleep=NO_SLEEP)
        s2 = run_export(project_with_tasks['tasks'], gw, is_transient=is_transient, sleep=NO_SLEEP)
        assert (s2['created'], s2['updated'], s2['failed']) == (0, 3, 0)
        assert gw.record_count() == 3  # no duplicates

    def test_transient_error_is_retried_then_succeeds(self, project_with_tasks):
        gw = FakeAirtableGateway()
        tid = str(project_with_tasks['tasks'][0].id)
        gw.create_failures[tid] = [TransientError(), TransientError()]  # fail twice, then ok
        s = run_export(project_with_tasks['tasks'][:1], gw, is_transient=is_transient, sleep=NO_SLEEP)
        assert s['created'] == 1 and s['failed'] == 0
        assert gw.calls['create'] == 3

    def test_permanent_error_not_retried_and_isolated(self, project_with_tasks):
        gw = FakeAirtableGateway()
        t0, t1, t2 = project_with_tasks['tasks']
        # t0 fails permanently (queue has extras that must NOT be consumed by retry)
        gw.create_failures[str(t0.id)] = [PermanentError('422'), PermanentError('422')]
        s = run_export([t0, t1, t2], gw, is_transient=is_transient, sleep=NO_SLEEP)
        assert s['failed'] == 1 and s['created'] == 2   # others still exported
        assert gw.calls['create'] == 3                  # t0 tried once (no retry) + t1 + t2
        assert s['errors'][0]['taskId'] == str(t0.id)

    def test_permanent_error_reading_existing_aborts(self, project_with_tasks):
        gw = FakeAirtableGateway()
        gw.existing_failures = [PermanentError('401 unauthorized')]
        with pytest.raises(PermanentError):
            run_export(project_with_tasks['tasks'], gw, is_transient=is_transient, sleep=NO_SLEEP)

    def test_transient_error_reading_existing_is_retried(self, project_with_tasks):
        gw = FakeAirtableGateway()
        gw.existing_failures = [TransientError()]
        s = run_export(project_with_tasks['tasks'], gw, is_transient=is_transient, sleep=NO_SLEEP)
        assert s['created'] == 3 and gw.calls['existing'] == 2

    def test_field_mapping(self, project_with_tasks):
        f = task_to_fields(project_with_tasks['tasks'][0])
        assert f['Title'] == 'Task 0' and f['Status'] == 'todo'
        assert f['Assignee'] == 'Member' and f['TaskId'] == str(project_with_tasks['tasks'][0].id)


def test_real_classifier_distinguishes_transient():
    import requests
    err = requests.exceptions.HTTPError()
    err.response = type('R', (), {'status_code': 429})()
    assert airtable_is_transient(err) is True
    err.response = type('R', (), {'status_code': 422})()
    assert airtable_is_transient(err) is False
    assert airtable_is_transient(requests.exceptions.ConnectionError()) is True


# ---- endpoint (authorization + wiring) ---------------------------------------

@pytest.mark.django_db
class TestExportEndpoint:
    def test_viewer_cannot_export(self, project_with_tasks):
        r = auth('viewer@x.dev').post(f"/api/projects/{project_with_tasks['p'].id}/export")
        assert r.status_code == 403

    def test_non_member_cannot_export(self, project_with_tasks):
        r = auth('out@x.dev').post(f"/api/projects/{project_with_tasks['p'].id}/export")
        assert r.status_code == 403

    @override_settings(AIRTABLE_API_KEY='', AIRTABLE_BASE_ID='')
    def test_unconfigured_returns_503(self, project_with_tasks):
        r = auth('admin@x.dev').post(f"/api/projects/{project_with_tasks['p'].id}/export")
        assert r.status_code == 503

    def test_member_export_succeeds_with_double(self, project_with_tasks, monkeypatch):
        import projects.views as v
        fake = FakeAirtableGateway()
        monkeypatch.setattr(v, 'build_gateway_from_settings', lambda: fake)
        r = auth('member@x.dev').post(f"/api/projects/{project_with_tasks['p'].id}/export")
        assert r.status_code == 200
        assert r.data['export']['created'] == 3
        assert fake.record_count() == 3
