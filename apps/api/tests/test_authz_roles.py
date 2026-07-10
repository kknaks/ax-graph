"""AXKG-SPEC-008 WP6 — role authz / 유저 관리 / 본인 비밀번호 변경 / is_active / 시드.

계약 SSOT: SPEC-008 §4 Access Boundary Matrix · §6 Acceptance Criteria · Case Matrix.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from axkg.models import Base, User
from axkg.seeds import seed_all, seed_users

ADMIN_EMAIL = "kknaks@medisolveai.com"
STAFF_EMAIL = "dr.jinlee@kakao.com"
SEED_PASSWORD = "1234"


async def _login(client: AsyncClient, email: str, password: str = SEED_PASSWORD) -> dict:
    res = await client.post("/auth/login", json={"email": email, "password": password})
    return res


async def _token(client: AsyncClient, email: str) -> str:
    res = await _login(client, email)
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- BE-1: role/is_active 시드 -------------------------------------------------


async def test_login_returns_role(client: AsyncClient) -> None:
    admin = (await _login(client, ADMIN_EMAIL)).json()
    staff = (await _login(client, STAFF_EMAIL)).json()
    assert admin["user"]["role"] == "admin"
    assert staff["user"]["role"] == "staff"


async def test_me_returns_role(client: AsyncClient) -> None:
    token = await _token(client, STAFF_EMAIL)
    res = await client.get("/auth/me", headers=_headers(token))
    assert res.status_code == 200
    assert res.json()["user"]["email"] == STAFF_EMAIL
    assert res.json()["user"]["role"] == "staff"


async def test_seed_roster_is_idempotent() -> None:
    """시드를 두 번 실행해도 email 기준으로 중복 계정이 생기지 않는다 (SPEC-008 AC)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(seed_all)
        await conn.run_sync(seed_users)  # 2회차
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        total = await session.scalar(select(func.count()).select_from(User))
        admins = await session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        staffs = await session.scalar(
            select(func.count()).select_from(User).where(User.role == "staff")
        )
    await engine.dispose()
    assert total == 22
    assert admins == 3
    assert staffs == 19


# --- BE-2: 접근 경계 매트릭스 --------------------------------------------------

ADMIN_GET_ROUTES = ["/sources", "/settings/ai-provider", "/prompts", "/templates", "/users"]


@pytest.mark.parametrize("route", ADMIN_GET_ROUTES)
async def test_staff_forbidden_on_admin_routes(client: AsyncClient, route: str) -> None:
    token = await _token(client, STAFF_EMAIL)
    res = await client.get(route, headers=_headers(token))
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "FORBIDDEN"


@pytest.mark.parametrize("route", ADMIN_GET_ROUTES)
async def test_admin_allowed_on_admin_routes(client: AsyncClient, route: str) -> None:
    token = await _token(client, ADMIN_EMAIL)
    res = await client.get(route, headers=_headers(token))
    assert res.status_code == 200


async def test_staff_can_access_graph_chat(client: AsyncClient) -> None:
    """그래프 + 채팅④는 staff+admin 모두 접근 (SPEC-008 Matrix)."""
    for email in (STAFF_EMAIL, ADMIN_EMAIL):
        token = await _token(client, email)
        res = await client.get("/graph/chats", headers=_headers(token))
        assert res.status_code == 200, f"{email}: {res.text}"


async def test_admin_route_still_requires_token(client: AsyncClient) -> None:
    res = await client.get("/users")
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "MISSING_TOKEN"


# --- BE-3: 유저 관리 (admin 전용) --------------------------------------------


async def test_admin_creates_user_login_with_default_password(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    res = await client.post(
        "/users",
        json={"email": "newbie@medisolveai.com", "display_name": "신입", "role": "staff"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == "newbie@medisolveai.com"
    assert body["role"] == "staff"
    assert body["is_active"] is True

    login = await _login(client, "newbie@medisolveai.com", SEED_PASSWORD)
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "staff"


async def test_staff_cannot_create_user(client: AsyncClient) -> None:
    staff_token = await _token(client, STAFF_EMAIL)
    res = await client.post(
        "/users",
        json={"email": "x@medisolveai.com", "role": "staff"},
        headers=_headers(staff_token),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "FORBIDDEN"


async def test_create_duplicate_email_rejected(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    res = await client.post(
        "/users",
        json={"email": ADMIN_EMAIL, "role": "staff"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "EMAIL_EXISTS"


async def test_create_invalid_role_rejected(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    res = await client.post(
        "/users",
        json={"email": "z@medisolveai.com", "role": "superuser"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 422


async def test_admin_changes_role(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    created = (
        await client.post(
            "/users",
            json={"email": "promote@medisolveai.com", "role": "staff"},
            headers=_headers(admin_token),
        )
    ).json()
    res = await client.patch(
        f"/users/{created['id']}/role",
        json={"role": "admin"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


async def test_deactivated_account_cannot_login(client: AsyncClient) -> None:
    """is_active=false 계정은 로그인할 수 없다 — INACTIVE_ACCOUNT (SPEC-008 AC)."""
    admin_token = await _token(client, ADMIN_EMAIL)
    created = (
        await client.post(
            "/users",
            json={"email": "toggle@medisolveai.com", "role": "staff"},
            headers=_headers(admin_token),
        )
    ).json()
    # 비활성화
    off = await client.patch(
        f"/users/{created['id']}/active",
        json={"is_active": False},
        headers=_headers(admin_token),
    )
    assert off.status_code == 200 and off.json()["is_active"] is False

    login = await _login(client, "toggle@medisolveai.com", SEED_PASSWORD)
    assert login.status_code == 401
    assert login.json()["detail"]["error_code"] == "INACTIVE_ACCOUNT"

    # 재활성화하면 다시 로그인 가능
    on = await client.patch(
        f"/users/{created['id']}/active",
        json={"is_active": True},
        headers=_headers(admin_token),
    )
    assert on.status_code == 200
    assert (await _login(client, "toggle@medisolveai.com")).status_code == 200


async def test_change_role_unknown_user_404(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    res = await client.patch(
        "/users/00000000-0000-0000-0000-000000000000/role",
        json={"role": "admin"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "USER_NOT_FOUND"


# --- BE-4: 본인 비밀번호 변경 ------------------------------------------------


async def test_self_password_change(client: AsyncClient) -> None:
    admin_token = await _token(client, ADMIN_EMAIL)
    created = (
        await client.post(
            "/users",
            json={"email": "pw@medisolveai.com", "role": "staff"},
            headers=_headers(admin_token),
        )
    ).json()
    user_token = await _token(client, "pw@medisolveai.com")

    res = await client.post(
        "/auth/password",
        json={"current_password": SEED_PASSWORD, "new_password": "newsecret"},
        headers=_headers(user_token),
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # 새 비번으로 로그인 가능, 옛 비번은 실패
    assert (await _login(client, "pw@medisolveai.com", "newsecret")).status_code == 200
    old = await _login(client, "pw@medisolveai.com", SEED_PASSWORD)
    assert old.status_code == 401
    assert old.json()["detail"]["error_code"] == "INVALID_CREDENTIALS"


async def test_password_change_wrong_current_rejected(client: AsyncClient) -> None:
    token = await _token(client, STAFF_EMAIL)
    res = await client.post(
        "/auth/password",
        json={"current_password": "wrong", "new_password": "whatever"},
        headers=_headers(token),
    )
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "INVALID_CREDENTIALS"


async def test_password_change_requires_auth(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/password",
        json={"current_password": "a", "new_password": "b"},
    )
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "MISSING_TOKEN"
