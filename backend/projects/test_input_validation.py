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
    nonmember = User.objects.create_user(email='non@x.dev', name='Non', password='password123')
    p = Project.objects.create(name='P', owner=admin)
    Membership.objects.create(user=admin, project=p, role='admin')
    Membership.objects.create(user=member, project=p, role='member')
    t = Task.objects.create(project=p, title='orig', status='todo', created_by=admin, position=0)
    return dict(p=p, t=t, admin=admin, member=member, nonmember=nonmember)


@pytest.mark.django_db
class TestTaskCreateValidation:
    def test_title_none_is_400_not_500(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': None}, format='json')
        assert r.status_code == 400

    def test_title_whitespace_is_400(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': '   '}, format='json')
        assert r.status_code == 400

    def test_title_missing_is_400(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {}, format='json')
        assert r.status_code == 400

    def test_title_too_long_is_400_not_500(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': 'a' * 501}, format='json')
        assert r.status_code == 400

    def test_invalid_status_is_400(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': 'x', 'status': 'nope'}, format='json')
        assert r.status_code == 400

    def test_garbage_assignee_is_400_not_500(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': 'x', 'assigneeId': 'nope'}, format='json')
        assert r.status_code == 400

    def test_nonmember_assignee_is_400(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks",
                                     {'title': 'x', 'assigneeId': str(world['nonmember'].id)}, format='json')
        assert r.status_code == 400

    def test_unknown_uuid_assignee_is_400_not_500(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks",
                                     {'title': 'x', 'assigneeId': '00000000-0000-0000-0000-000000000000'}, format='json')
        assert r.status_code == 400

    def test_valid_create_still_works(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks", {'title': 'Do a thing'}, format='json')
        assert r.status_code == 201 and r.data['task']['title'] == 'Do a thing'

    def test_member_assignee_ok(self, world):
        r = auth('admin@x.dev').post(f"/api/projects/{world['p'].id}/tasks",
                                     {'title': 'x', 'assigneeId': str(world['member'].id)}, format='json')
        assert r.status_code == 201 and r.data['task']['assignee']['email'] == 'member@x.dev'


@pytest.mark.django_db
class TestTaskPatchValidation:
    def test_title_none_is_400_not_500(self, world):
        r = auth('admin@x.dev').patch(f"/api/tasks/{world['t'].id}", {'title': None}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 400 and world['t'].title == 'orig'

    def test_title_whitespace_is_400_not_blank(self, world):
        r = auth('admin@x.dev').patch(f"/api/tasks/{world['t'].id}", {'title': '   '}, format='json')
        world['t'].refresh_from_db()
        assert r.status_code == 400 and world['t'].title == 'orig'

    def test_garbage_assignee_is_400_not_500(self, world):
        r = auth('admin@x.dev').patch(f"/api/tasks/{world['t'].id}", {'assigneeId': 'nope'}, format='json')
        assert r.status_code == 400

    def test_nonmember_assignee_is_400(self, world):
        r = auth('admin@x.dev').patch(f"/api/tasks/{world['t'].id}",
                                      {'assigneeId': str(world['nonmember'].id)}, format='json')
        assert r.status_code == 400

    def test_assign_member_then_unassign(self, world):
        c = auth('admin@x.dev')
        r1 = c.patch(f"/api/tasks/{world['t'].id}", {'assigneeId': str(world['member'].id)}, format='json')
        assert r1.status_code == 200 and r1.data['task']['assignee']['email'] == 'member@x.dev'
        r2 = c.patch(f"/api/tasks/{world['t'].id}", {'assigneeId': None}, format='json')
        assert r2.status_code == 200 and r2.data['task']['assignee'] is None

    def test_authz_still_checked_before_validation(self, world):
        # non-member sending invalid input should get 403, not 400
        r = auth('non@x.dev').patch(f"/api/tasks/{world['t'].id}", {'title': None}, format='json')
        assert r.status_code == 403


@pytest.mark.django_db
class TestProjectValidation:
    def test_create_name_too_long_is_400(self, world):
        r = auth('admin@x.dev').post('/api/projects', {'name': 'a' * 121}, format='json')
        assert r.status_code == 400

    def test_create_name_missing_is_400(self, world):
        r = auth('admin@x.dev').post('/api/projects', {}, format='json')
        assert r.status_code == 400

    def test_patch_name_too_long_is_400_not_500(self, world):
        r = auth('admin@x.dev').patch(f"/api/projects/{world['p'].id}", {'name': 'a' * 200}, format='json')
        assert r.status_code == 400

    def test_patch_name_empty_is_400(self, world):
        r = auth('admin@x.dev').patch(f"/api/projects/{world['p'].id}", {'name': '   '}, format='json')
        assert r.status_code == 400

    def test_valid_patch_still_works(self, world):
        r = auth('admin@x.dev').patch(f"/api/projects/{world['p'].id}", {'name': 'Renamed'}, format='json')
        assert r.status_code == 200 and r.data['project']['name'] == 'Renamed'
