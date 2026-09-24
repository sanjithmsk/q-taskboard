import pytest
from rest_framework.test import APIClient
from users.models import User
from projects.models import Project, Membership, Task


def auth(email):
    c = APIClient()
    r = c.post('/api/auth/login', {'email': email, 'password': 'password123'}, format='json')
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['token']}")
    return c


@pytest.fixture
def world(db):
    admin = User.objects.create_user(email='admin@x.dev', name='Admin', password='password123')
    member = User.objects.create_user(email='member@x.dev', name='Member', password='password123')
    viewer = User.objects.create_user(email='viewer@x.dev', name='Viewer', password='password123')
    outsider = User.objects.create_user(email='outsider@x.dev', name='Outsider', password='password123')
    p = Project.objects.create(name='P', owner=admin)
    Membership.objects.create(user=admin, project=p, role='admin')
    Membership.objects.create(user=member, project=p, role='member')
    Membership.objects.create(user=viewer, project=p, role='viewer')
    t = Task.objects.create(project=p, title='orig', status='todo', created_by=admin, position=0)
    return dict(p=p, t=t, admin=admin, member=member, viewer=viewer, outsider=outsider)


@pytest.mark.django_db
class TestTaskPatchAuthz:
    def test_outsider_cannot_edit(self, world):
        c = auth('outsider@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'title': 'pwned', 'status': 'done'}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 403
        assert world['t'].title == 'orig' and world['t'].status == 'todo'

    def test_viewer_cannot_edit(self, world):
        c = auth('viewer@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'title': 'viewer-edit'}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 403
        assert world['t'].title == 'orig'

    def test_member_can_edit(self, world):
        c = auth('member@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'title': 'updated', 'status': 'done'}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 200
        assert world['t'].title == 'updated' and world['t'].status == 'done'
        assert r.data['task']['title'] == 'updated'

    def test_admin_can_edit(self, world):
        c = auth('admin@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'title': 'admin-edit'}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 200 and world['t'].title == 'admin-edit'

    def test_unknown_task_is_404_not_403(self, world):
        c = auth('admin@x.dev')
        r = c.patch("/api/tasks/00000000-0000-0000-0000-000000000000", {'title': 'x'}, format='json')
        assert r.status_code == 404

    def test_authz_checked_before_input_validation(self, world):
        # An unauthorized user sending an invalid status should get 403, not 400.
        c = auth('outsider@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'status': 'nonsense'}, format='json')
        assert r.status_code == 403

    def test_valid_status_validation_still_works_for_member(self, world):
        c = auth('member@x.dev')
        r = c.patch(f"/api/tasks/{world['t'].id}", {'status': 'nonsense'}, format='json')
        assert r.status_code == 400
