"""AXKG-SPEC-008 auth 흐름 테스트: login 성공/실패, me, logout 후 401."""
from httpx import AsyncClient

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"


async def _login(client: AsyncClient) -> str:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200
    return res.json()["token"]


async def test_login_success(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["user"]["email"] == SEED_EMAIL


async def test_login_wrong_password(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": "wrong"}
    )
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": SEED_PASSWORD}
    )
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_CREDENTIALS"


async def test_login_empty_fields_rejected(client: AsyncClient) -> None:
    res = await client.post("/auth/login", json={"email": "", "password": ""})
    assert res.status_code == 422


async def test_me_with_token(client: AsyncClient) -> None:
    token = await _login(client)
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["user"]["email"] == SEED_EMAIL


async def test_me_without_token(client: AsyncClient) -> None:
    res = await client.get("/auth/me")
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "MISSING_TOKEN"


async def test_me_with_invalid_token(client: AsyncClient) -> None:
    res = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_TOKEN"


async def test_logout_then_me_401(client: AsyncClient) -> None:
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post("/auth/logout", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    res = await client.get("/auth/me", headers=headers)
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_TOKEN"


async def test_expired_token_rejected(client: AsyncClient, monkeypatch) -> None:
    from axkg.config import settings

    monkeypatch.setattr(settings, "axkg_auth_token_ttl_days", -1)
    token = await _login(client)
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_TOKEN"
