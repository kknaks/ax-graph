"""AXKG-SPEC-010 Templates 관리 API 테스트 (WP5 Phase 3).

커버:
- GET /templates 목록(seed 3종 + 활성 버전), GET /templates/{key} 활성 버전
- POST versions → 새 version(max+1) + 활성 전환, 기존 버전 불변(row 보존)
- POST rollback → active 포인터 이동, 새 row 안 생김(복사 없음)
- validation: TEMPLATE_NOT_FOUND / EMPTY_TEMPLATE_BODY / TEMPLATE_VERSION_NOT_FOUND
- key 3종만 유효, 임의 key 거부
- WP3 연동(관찰): 저장/롤백 후 get_active_version(실행측 로드 경로)이 활성 body를 따라감
- owner 스코프/미인증 401
"""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.repositories.document_templates import DocumentTemplateRepository

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"
# concept은 파생지식 전용 뼈대 — destination 매핑이 아니라 문서화③ 조립에 고정 동봉되지만
# document_templates 시드로 관리된다(PLAN-009-T-027, SPEC-011 §4 Layer Taxonomy).
SEED_KEYS = {"reference", "permanent", "project_baseline", "concept"}
KEY = "project_baseline"


async def _auth(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


async def test_list_templates_returns_seeds_with_active_version(
    client: AsyncClient,
) -> None:
    headers = await _auth(client)
    res = await client.get("/templates", headers=headers)
    assert res.status_code == 200
    templates = {t["key"]: t for t in res.json()["templates"]}
    assert SEED_KEYS <= set(templates)
    assert templates[KEY]["active_version"] == 1
    assert templates[KEY]["name"]


async def test_get_template_returns_active_version(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get(f"/templates/{KEY}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["key"] == KEY
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["body"]


# ---------------------------------------------------------------------------
# 저장 (새 버전 + 활성) / 롤백 (포인터 이동)
# ---------------------------------------------------------------------------


async def test_save_creates_new_version_and_activates(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/templates/{KEY}/versions",
        json={"body": "새 템플릿 본문 v2"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["version"] == 2
    assert body["is_active"] is True
    assert body["body"] == "새 템플릿 본문 v2"

    # 기존 v1 row는 보존되고, v2가 활성이다.
    versions = (
        await client.get(f"/templates/{KEY}/versions", headers=headers)
    ).json()["versions"]
    by_ver = {v["version"]: v for v in versions}
    assert set(by_ver) == {1, 2}
    assert by_ver[2]["is_active"] is True
    assert by_ver[1]["is_active"] is False
    assert by_ver[1]["body"]  # v1 본문 불변 보존

    # GET active도 v2를 가리킨다.
    active = (await client.get(f"/templates/{KEY}", headers=headers)).json()
    assert active["version"] == 2


async def test_rollback_moves_pointer_without_new_row(client: AsyncClient) -> None:
    headers = await _auth(client)
    await client.post(
        f"/templates/{KEY}/versions", json={"body": "v2"}, headers=headers
    )
    res = await client.post(
        f"/templates/{KEY}/rollback", json={"version": 1}, headers=headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 1
    assert res.json()["is_active"] is True

    versions = (
        await client.get(f"/templates/{KEY}/versions", headers=headers)
    ).json()["versions"]
    # 새 row 안 생김 — 여전히 2개.
    assert {v["version"] for v in versions} == {1, 2}
    by_ver = {v["version"]: v for v in versions}
    assert by_ver[1]["is_active"] is True
    assert by_ver[2]["is_active"] is False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


async def test_get_unknown_template_404(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get("/templates/not_a_template", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


async def test_save_unknown_template_404_rejects_arbitrary_key(
    client: AsyncClient,
) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/templates/arbitrary_key/versions",
        json={"body": "본문"},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


async def test_save_empty_body_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/templates/{KEY}/versions", json={"body": "   "}, headers=headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "EMPTY_TEMPLATE_BODY"


async def test_rollback_unknown_version_404(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/templates/{KEY}/rollback", json={"version": 99}, headers=headers
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "TEMPLATE_VERSION_NOT_FOUND"


async def test_only_seed_keys_valid(client: AsyncClient) -> None:
    headers = await _auth(client)
    listed = (await client.get("/templates", headers=headers)).json()["templates"]
    assert {t["key"] for t in listed} == SEED_KEYS


# ---------------------------------------------------------------------------
# WP3 연동 (변경 없이 관찰) — 실행측 활성 로드 경로가 저장/롤백을 따라간다
# ---------------------------------------------------------------------------


async def test_active_load_path_follows_save_and_rollback(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await _auth(client)

    async def _active_body() -> str:
        async with session_factory() as session:
            dto = await DocumentTemplateRepository(session).get_active_version(KEY)
            assert dto is not None
            return dto.body

    base = await _active_body()
    assert base  # seed v1 body

    await client.post(
        f"/templates/{KEY}/versions", json={"body": "실행측 로드 v2"}, headers=headers
    )
    # 저장 후 실행측(_load_active_template가 쓰는 get_active_version)이 새 body를 로드.
    assert await _active_body() == "실행측 로드 v2"

    await client.post(
        f"/templates/{KEY}/rollback", json={"version": 1}, headers=headers
    )
    # 롤백 후 다시 v1 body로.
    assert await _active_body() == base


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/templates")).status_code == 401
    assert (
        await client.post(f"/templates/{KEY}/versions", json={"body": "x"})
    ).status_code == 401
