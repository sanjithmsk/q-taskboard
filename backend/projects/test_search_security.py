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
    owner = User.objects.create_user(email='o@x.dev', name='Owner', password='password123')
    viewer = User.objects.create_user(email='v@x.dev', name='Viewer', password='password123')
    secret = User.objects.create_user(email='ceo@secret.dev', name='CEO', password='hunter2pass')
    p = Project.objects.create(name='P', owner=owner)
    Membership.objects.create(user=owner, project=p, role='admin')
    Membership.objects.create(user=viewer, project=p, role='viewer')
    Task.objects.create(project=p, title='Fix login bug', description='auth flow', status='todo', created_by=owner, assignee=owner, position=0)
    Task.objects.create(project=p, title='Write docs', description='50% done', status='todo', created_by=owner, position=1)
    Task.objects.create(project=p, title="O'Brien task", description="quote ' test", status='done', created_by=owner, position=0)
    return dict(p=p, owner=owner, viewer=viewer, secret=secret)


@pytest.mark.django_db
class TestSearchInjection:
    def test_union_injection_cannot_dump_users(self, world):
        c = auth('v@x.dev')
        payload = ("zzz%') UNION SELECT id, id, email, password, 'x', NULL::uuid, id, 0, "
                   "created_at, updated_at FROM users --")
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': payload})
        assert r.status_code == 200
        titles = [t['title'] for t in r.data['tasks']]
        # No user email/hash should ever appear as a "task"
        assert 'ceo@secret.dev' not in titles
        assert not any('pbkdf2' in (t.get('description') or '') for t in r.data['tasks'])
        assert r.data['tasks'] == []  # payload matches no real task

    def test_quote_in_query_is_literal_not_error(self, world):
        c = auth('o@x.dev')
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': "O'Brien"})
        assert r.status_code == 200
        assert [t['title'] for t in r.data['tasks']] == ["O'Brien task"]

    def test_like_wildcards_are_literal(self, world):
        c = auth('o@x.dev')
        # '%' must match the literal '50%' task, not act as a wildcard matching all
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': '50%'})
        assert r.status_code == 200
        assert [t['title'] for t in r.data['tasks']] == ['Write docs']

    def test_underscore_is_literal(self, world):
        c = auth('o@x.dev')
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'l_gin'})  # '_' would match 'login' if wildcard
        assert r.status_code == 200
        assert r.data['tasks'] == []

    def test_normal_search_matches_title_and_description(self, world):
        c = auth('o@x.dev')
        assert [t['title'] for t in c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'login'}).data['tasks']] == ['Fix login bug']
        assert [t['title'] for t in c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'auth'}).data['tasks']] == ['Fix login bug']

    def test_search_response_shape_matches_unfiltered(self, world):
        c = auth('o@x.dev')
        full = c.get(f"/api/projects/{world['p'].id}/tasks").data['tasks']
        searched = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'login'}).data['tasks']
        assert set(full[0].keys()) == set(searched[0].keys())
        assert 'assignee' in searched[0]  # nested object present, not just assignee_id
        assert searched[0]['assignee']['email'] == 'o@x.dev'

    def test_blank_query_returns_all(self, world):
        c = auth('o@x.dev')
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': '   '})
        assert r.status_code == 200
        assert len(r.data['tasks']) == 3

    def test_search_still_scoped_to_project(self, world):
        # a task in another project must never leak via search
        other = Project.objects.create(name='Other', owner=world['owner'])
        Task.objects.create(project=other, title='login secret elsewhere', created_by=world['owner'])
        c = auth('o@x.dev')
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'login'})
        assert [t['title'] for t in r.data['tasks']] == ['Fix login bug']

    def test_non_member_still_forbidden(self, world):
        outsider = User.objects.create_user(email='out@x.dev', name='Out', password='password123')
        c = auth('out@x.dev')
        r = c.get(f"/api/projects/{world['p'].id}/tasks", {'q': 'login'})
        assert r.status_code == 403
