import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def credentials(user_factory):
    user = user_factory(username="alice")
    user.set_password("correct-horse")
    user.save()
    return user


def test_valid_credentials_return_a_token(api, credentials):
    response = api.post(
        "/api/v1/auth/token/", {"username": "alice", "password": "correct-horse"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["token"]
    assert response.json()["username"] == "alice"


def test_wrong_password_is_rejected(api, credentials):
    response = api.post(
        "/api/v1/auth/token/", {"username": "alice", "password": "wrong"}, format="json"
    )

    assert response.status_code == 400


def test_failures_do_not_reveal_whether_the_account_exists(api, credentials):
    """Distinguishing 'no such user' from 'wrong password' turns the endpoint
    into an account oracle."""
    missing = api.post(
        "/api/v1/auth/token/", {"username": "nobody", "password": "x"}, format="json"
    )
    wrong = api.post("/api/v1/auth/token/", {"username": "alice", "password": "x"}, format="json")

    assert missing.status_code == wrong.status_code
    assert missing.json() == wrong.json()


def test_an_inactive_user_cannot_obtain_a_token(api, credentials):
    credentials.is_active = False
    credentials.save()

    response = api.post(
        "/api/v1/auth/token/", {"username": "alice", "password": "correct-horse"}, format="json"
    )

    assert response.status_code == 400


def test_whoami_identifies_the_caller(api, credentials):
    token = Token.objects.create(user=credentials)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = api.get("/api/v1/auth/whoami/")

    assert response.status_code == 200
    assert response.json()["username"] == "alice"


def test_revoking_takes_effect_immediately(api, credentials):
    """The reason this is a token rather than a self-contained JWT: a JWT
    stays valid until it expires unless a denylist is added."""
    token = Token.objects.create(user=credentials)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    assert api.post("/api/v1/auth/token/revoke/").status_code == 204
    assert api.get("/api/v1/auth/whoami/").status_code == 401


def test_an_unknown_token_is_rejected(api):
    api.credentials(HTTP_AUTHORIZATION="Token deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")

    assert api.get("/api/v1/auth/whoami/").status_code == 401


def test_no_credentials_is_401_not_500(api):
    assert api.get("/api/v1/auth/whoami/").status_code == 401


def test_the_login_endpoint_is_rate_limited(api, credentials, monkeypatch):
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "3/minute"})
    cache.clear()

    codes = [
        api.post(
            "/api/v1/auth/token/", {"username": "alice", "password": "wrong"}, format="json"
        ).status_code
        for _ in range(5)
    ]

    assert codes.count(429) == 2
