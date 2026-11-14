"""
Authentication, password policy and token handling (brief §21, §25).
"""

import pytest

from tests.helpers import register_user


def test_register_and_login_round_trip(client, clean_mongo):
    user, token = register_user(client)
    assert user["email"] == "test@example.com"
    assert token

    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "StudyHard2026"},
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["user"]["id"] == user["id"]
    assert payload["token"]


def test_duplicate_email_is_rejected(client, clean_mongo):
    register_user(client)
    response = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "full_name": "Someone Else", "password": "StudyHard2026"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize("password", ["short", "12345678", "password", ""])
def test_weak_passwords_rejected(client, clean_mongo, password):
    response = client.post(
        "/api/auth/register",
        json={"email": f"weak{password or 'empty'}@example.com", "full_name": "Weak", "password": password},
    )
    assert response.status_code in (400, 422)


def test_invalid_email_rejected(client, clean_mongo):
    response = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "full_name": "Nope", "password": "StudyHard2026"},
    )
    assert response.status_code in (400, 422)


def test_wrong_password_rejected(client, clean_mongo):
    register_user(client)
    response = client.post(
        "/api/auth/login", json={"email": "test@example.com", "password": "WrongPass999"}
    )
    assert response.status_code == 401


def test_me_requires_auth(client, clean_mongo):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_bad_token(client, clean_mongo):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] in ("invalid_token", "unauthorized")


def test_me_returns_profile(client, clean_mongo):
    user, token = register_user(client)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["email"] == "test@example.com"
    assert "password_hash" not in payload


def test_change_password_flow(client, clean_mongo):
    user, token = register_user(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "StudyHard2026", "new_password": "EvenHarder2027"},
        headers=headers,
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    # Old password must fail now, the new one must work.
    assert (
        client.post(
            "/api/auth/login", json={"email": "test@example.com", "password": "StudyHard2026"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "test@example.com", "password": "EvenHarder2027"}
        ).status_code
        == 200
    )


def test_expired_token_is_rejected(client, clean_mongo):
    from utils.security import create_access_token

    user, _ = register_user(client)
    from config.settings import get_settings

    expired = create_access_token(user["id"], secret=get_settings().secret_key,
                                  expires_in_hours=-1)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "token_expired"
