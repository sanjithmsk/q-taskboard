import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestRegister:
    def test_creates_user_and_returns_token(self, client):
        response = client.post('/api/auth/register', {
            'email': 'test@example.com',
            'password': 'password123',
            'name': 'Test User',
        }, format='json')
        assert response.status_code == 201
        assert 'token' in response.data
        assert response.data['user']['email'] == 'test@example.com'

    def test_rejects_short_password(self, client):
        response = client.post('/api/auth/register', {
            'email': 'test@example.com',
            'password': 'short',
            'name': 'Test User',
        }, format='json')
        assert response.status_code == 400

    def test_rejects_duplicate_email(self, client):
        User.objects.create_user(email='test@example.com', name='Existing', password='password123')
        response = client.post('/api/auth/register', {
            'email': 'test@example.com',
            'password': 'password123',
            'name': 'New User',
        }, format='json')
        assert response.status_code == 400

    def test_rejects_missing_name(self, client):
        response = client.post('/api/auth/register', {
            'email': 'test@example.com',
            'password': 'password123',
        }, format='json')
        assert response.status_code == 400


@pytest.mark.django_db
class TestLogin:
    def test_returns_token_on_valid_credentials(self, client):
        User.objects.create_user(email='test@example.com', name='Test', password='password123')
        response = client.post('/api/auth/login', {
            'email': 'test@example.com',
            'password': 'password123',
        }, format='json')
        assert response.status_code == 200
        assert 'token' in response.data
        assert response.data['user']['email'] == 'test@example.com'

    def test_rejects_wrong_password(self, client):
        User.objects.create_user(email='test@example.com', name='Test', password='password123')
        response = client.post('/api/auth/login', {
            'email': 'test@example.com',
            'password': 'wrongpassword',
        }, format='json')
        assert response.status_code == 401

    def test_rejects_missing_email(self, client):
        response = client.post('/api/auth/login', {'password': 'anything'}, format='json')
        assert response.status_code == 400

    def test_rejects_unknown_email(self, client):
        response = client.post('/api/auth/login', {
            'email': 'nobody@example.com',
            'password': 'password123',
        }, format='json')
        assert response.status_code == 401


@pytest.mark.django_db
class TestAuthEndpointsIgnoreStaleToken:
    """A browser can hold a token whose user no longer exists (e.g. after
    `manage.py seed` recreates every user with a new id). That must not block
    signing in or registering again."""

    def _stale_token(self):
        ghost = User.objects.create_user(email='ghost@example.com', name='Ghost', password='password123')
        token = str(RefreshToken.for_user(ghost).access_token)
        ghost.delete()
        return token

    @pytest.mark.parametrize('kind', ['stale', 'garbage'])
    def test_login_succeeds_with_bad_bearer_token(self, client, kind):
        User.objects.create_user(email='test@example.com', name='Test', password='password123')
        token = self._stale_token() if kind == 'stale' else 'not-a-jwt'
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.post('/api/auth/login', {
            'email': 'test@example.com',
            'password': 'password123',
        }, format='json')
        assert response.status_code == 200
        assert 'token' in response.data

    @pytest.mark.parametrize('kind', ['stale', 'garbage'])
    def test_register_succeeds_with_bad_bearer_token(self, client, kind):
        token = self._stale_token() if kind == 'stale' else 'not-a-jwt'
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.post('/api/auth/register', {
            'email': 'new@example.com',
            'password': 'password123',
            'name': 'New User',
        }, format='json')
        assert response.status_code == 201
        assert 'token' in response.data

    def test_wrong_password_still_rejected_with_stale_token(self, client):
        User.objects.create_user(email='test@example.com', name='Test', password='password123')
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self._stale_token()}')
        response = client.post('/api/auth/login', {
            'email': 'test@example.com',
            'password': 'wrongpassword',
        }, format='json')
        assert response.status_code == 401
        assert response.data == {'error': 'invalid credentials'}

    def test_protected_endpoints_still_reject_stale_token(self, client):
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self._stale_token()}')
        assert client.get('/api/users/me').status_code == 401
        assert client.get('/api/projects').status_code == 401


@pytest.mark.django_db
class TestAuthIgnoresStaleToken:
    """Register/login must not authenticate the request: a stale/expired Bearer
    header (e.g. for a user removed by `manage.py seed`) must not 401 the
    sign-in endpoints. Regression for the lockout after re-seeding."""
    STALE = 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxMDAwMDAwMDAwLCJ1c2VyX2lkIjoiZGVhZGJlZWYtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDAwIn0.x'

    def test_register_ignores_stale_token(self, client):
        r = client.post('/api/auth/register',
                        {'email': 'fresh@x.dev', 'name': 'Fresh', 'password': 'password123'},
                        format='json', HTTP_AUTHORIZATION=self.STALE)
        assert r.status_code == 201

    def test_login_ignores_stale_token(self, client):
        User.objects.create_user(email='who@x.dev', name='Who', password='password123')
        r = client.post('/api/auth/login', {'email': 'who@x.dev', 'password': 'password123'},
                        format='json', HTTP_AUTHORIZATION=self.STALE)
        assert r.status_code == 200
