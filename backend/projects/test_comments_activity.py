import pytest
from rest_framework.test import APIClient
from users.models import User
from projects.models import Project, Membership, Task, Comment, Activity


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
    outsider = User.objects.create_user(email='out@x.dev', name='Out', password='password123')
    p = Project.objects.create(name='P', owner=admin)
    Membership.objects.create(user=admin, project=p, role='admin')
    Membership.objects.create(user=member, project=p, role='member')
    Membership.objects.create(user=viewer, project=p, role='viewer')
    t = Task.objects.create(project=p, title='Task 1', status='todo', created_by=admin)
    return dict(p=p, t=t, admin=admin, member=member, viewer=viewer, outsider=outsider)


@pytest.mark.django_db
class TestComments:
    def test_member_can_post_and_it_appears_chronologically(self, world):
        c = auth('member@x.dev')
        c.post(f"/api/tasks/{world['t'].id}/comments", {'body': 'first'}, format='json')
        auth('admin@x.dev').post(f"/api/tasks/{world['t'].id}/comments", {'body': 'second'}, format='json')
        r = c.get(f"/api/tasks/{world['t'].id}/comments")
        assert r.status_code == 200
        bodies = [x['body'] for x in r.data['comments']]
        assert bodies == ['first', 'second']  # oldest first
        first = r.data['comments'][0]
        assert first['author']['email'] == 'member@x.dev'
        assert 'created_at' in first and first['created_at']

    def test_viewer_can_read_but_not_post(self, world):
        Comment.objects.create(task=world['t'], author=world['admin'], body='hi')
        c = auth('viewer@x.dev')
        assert c.get(f"/api/tasks/{world['t'].id}/comments").status_code == 200
        r = c.post(f"/api/tasks/{world['t'].id}/comments", {'body': 'nope'}, format='json')
        assert r.status_code == 403
        assert Comment.objects.filter(task=world['t']).count() == 1

    def test_non_member_cannot_read_or_post(self, world):
        c = auth('out@x.dev')
        assert c.get(f"/api/tasks/{world['t'].id}/comments").status_code == 403
        assert c.post(f"/api/tasks/{world['t'].id}/comments", {'body': 'x'}, format='json').status_code == 403

    def test_comments_are_append_only_no_edit_or_delete(self, world):
        cm = Comment.objects.create(task=world['t'], author=world['admin'], body='orig')
        c = auth('admin@x.dev')
        # collection has no PATCH/DELETE handlers -> 405; there is no item route at all
        assert c.patch(f"/api/tasks/{world['t'].id}/comments", {'body': 'edited'}, format='json').status_code == 405
        assert c.delete(f"/api/tasks/{world['t'].id}/comments").status_code == 405
        cm.refresh_from_db()
        assert cm.body == 'orig'

    def test_empty_body_is_400(self, world):
        c = auth('admin@x.dev')
        assert c.post(f"/api/tasks/{world['t'].id}/comments", {'body': '   '}, format='json').status_code == 400

    def test_unknown_task_is_404(self, world):
        c = auth('admin@x.dev')
        assert c.get("/api/tasks/00000000-0000-0000-0000-000000000000/comments").status_code == 404

    def test_posting_comment_records_activity(self, world):
        auth('member@x.dev').post(f"/api/tasks/{world['t'].id}/comments", {'body': 'hey'}, format='json')
        act = Activity.objects.filter(project=world['p'], action='comment_added').first()
        assert act is not None and act.actor == world['member']


@pytest.mark.django_db
class TestActivityFeed:
    def test_task_create_status_and_assignee_generate_activities(self, world):
        c = auth('admin@x.dev')
        created = c.post(f"/api/projects/{world['p'].id}/tasks", {'title': 'New'}, format='json').data['task']
        c.patch(f"/api/tasks/{created['id']}", {'status': 'in_progress'}, format='json')
        c.patch(f"/api/tasks/{created['id']}", {'assigneeId': str(world['member'].id)}, format='json')
        actions = list(Activity.objects.filter(task_id=created['id']).values_list('action', flat=True))
        assert 'task_created' in actions and 'status_changed' in actions and 'assignee_changed' in actions

    def test_feed_most_recent_first_and_summaries(self, world):
        c = auth('admin@x.dev')
        t = c.post(f"/api/projects/{world['p'].id}/tasks", {'title': 'Alpha'}, format='json').data['task']
        c.patch(f"/api/tasks/{t['id']}", {'status': 'done'}, format='json')
        r = c.get(f"/api/projects/{world['p'].id}/activities")
        assert r.status_code == 200
        acts = r.data['activities']
        assert acts[0]['action'] == 'status_changed'  # most recent first
        assert 'from' in acts[0]['metadata'] and acts[0]['metadata']['to'] == 'done'
        assert 'Alpha' in acts[0]['summary'] and world['admin'].name in acts[0]['summary']

    def test_feed_scoped_to_project(self, world):
        other = Project.objects.create(name='Other', owner=world['admin'])
        Membership.objects.create(user=world['admin'], project=other, role='admin')
        c = auth('admin@x.dev')
        c.post(f"/api/projects/{other.id}/tasks", {'title': 'Elsewhere'}, format='json')
        c.post(f"/api/projects/{world['p'].id}/tasks", {'title': 'Here'}, format='json')
        r = c.get(f"/api/projects/{world['p'].id}/activities")
        titles = [a['metadata'].get('title') for a in r.data['activities']]
        assert 'Here' in titles and 'Elsewhere' not in titles

    def test_non_member_cannot_read_feed(self, world):
        assert auth('out@x.dev').get(f"/api/projects/{world['p'].id}/activities").status_code == 403

    def test_member_can_read_feed(self, world):
        assert auth('viewer@x.dev').get(f"/api/projects/{world['p'].id}/activities").status_code == 200

    def test_noop_patch_records_no_activity(self, world):
        c = auth('admin@x.dev')
        before = Activity.objects.filter(project=world['p']).count()
        # title-only edit and setting status to its current value -> no new activity
        c.patch(f"/api/tasks/{world['t'].id}", {'title': 'renamed'}, format='json')
        c.patch(f"/api/tasks/{world['t'].id}", {'status': 'todo'}, format='json')
        assert Activity.objects.filter(project=world['p']).count() == before


@pytest.mark.django_db
class TestAtomicity:
    def test_task_create_rolls_back_if_activity_write_fails(self, world, monkeypatch):
        import projects.views as v
        monkeypatch.setattr(v, '_record_activity', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('audit down')))
        c = auth('admin@x.dev')
        before = Task.objects.filter(project=world['p']).count()
        with pytest.raises(Exception):
            c.post(f"/api/projects/{world['p'].id}/tasks", {'title': 'ghost'}, format='json')
        assert Task.objects.filter(project=world['p']).count() == before  # rolled back
        assert not Task.objects.filter(title='ghost').exists()

    def test_comment_rolls_back_if_activity_write_fails(self, world, monkeypatch):
        import projects.views as v
        monkeypatch.setattr(v, '_record_activity', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('audit down')))
        c = auth('member@x.dev')
        before = Comment.objects.filter(task=world['t']).count()
        with pytest.raises(Exception):
            c.post(f"/api/tasks/{world['t'].id}/comments", {'body': 'ghost'}, format='json')
        assert Comment.objects.filter(task=world['t']).count() == before  # rolled back
