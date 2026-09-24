"""Regression tests for the production security hardening in settings.py.

Throttling is exercised by patching SimpleRateThrottle.THROTTLE_RATES directly
and restoring it, rather than override_settings — DRF binds THROTTLE_RATES as a
class attribute at import time, so override_settings would leak the rate into
other tests. In production nothing overrides settings, so this concern is
test-only.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from users.models import User


class _throttle_rate:
    """Temporarily set the 'auth' throttle rate and restore it afterwards."""
    def __init__(self, rate):
        self.rate = rate

    def __enter__(self):
        self._orig = SimpleRateThrottle.THROTTLE_RATES
        SimpleRateThrottle.THROTTLE_RATES = {**self._orig, 'auth': self.rate}
        cache.clear()
        return self

    def __exit__(self, *exc):
        SimpleRateThrottle.THROTTLE_RATES = self._orig
        cache.clear()
        return False


@pytest.mark.django_db
def test_login_is_throttled_when_enabled():
    User.objects.create_user(email='t@x.dev', name='T', password='password123')
    c = APIClient()
    with _throttle_rate('1/min'):
        r1 = c.post('/api/auth/login', {'email': 't@x.dev', 'password': 'password123'}, format='json')
        r2 = c.post('/api/auth/login', {'email': 't@x.dev', 'password': 'password123'}, format='json')
    assert r1.status_code == 200
    assert r2.status_code == 429  # second attempt in the window is blocked


@pytest.mark.django_db
def test_register_is_throttled_when_enabled():
    c = APIClient()
    with _throttle_rate('1/min'):
        r1 = c.post('/api/auth/register', {'email': 'a@x.dev', 'name': 'A', 'password': 'password123'}, format='json')
        r2 = c.post('/api/auth/register', {'email': 'b@x.dev', 'name': 'B', 'password': 'password123'}, format='json')
    assert r1.status_code == 201
    assert r2.status_code == 429


@pytest.mark.django_db
def test_scopeless_endpoints_are_never_throttled():
    # Views without throttle_scope must not be limited even when a rate is set.
    User.objects.create_user(email='u@x.dev', name='U', password='password123')
    c = APIClient()
    with _throttle_rate('1/min'):
        tok = c.post('/api/auth/login', {'email': 'u@x.dev', 'password': 'password123'}, format='json').data['token']
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        codes = [c.get('/api/projects').status_code for _ in range(5)]
    assert codes == [200] * 5


@pytest.mark.django_db
def test_throttling_off_by_default_in_tests():
    # With DEBUG-derived config, the baked 'auth' rate is None, so repeated
    # logins are not throttled during the normal suite.
    User.objects.create_user(email='n@x.dev', name='N', password='password123')
    c = APIClient()
    codes = [c.post('/api/auth/login', {'email': 'n@x.dev', 'password': 'password123'}, format='json').status_code
             for _ in range(6)]
    assert codes == [200] * 6
