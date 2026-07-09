"""AXKG-SPEC-009 Prompts 관리 API 테스트 (WP5 Phase 2).

커버:
- GET /prompts 목록(seed 4종 + 활성 버전), GET /prompts/{key} 활성 버전
- POST versions → 새 version(max+1) + 활성 전환, 기존 버전 불변(row 보존)
- POST rollback → active 포인터 이동, 새 row 안 생김(복사 없음)
- validation: PROMPT_NOT_FOUND / EMPTY_PROMPT_BODY / INVALID_OUTPUT_SCHEMA / PROMPT_VERSION_NOT_FOUND
- 버전 목록의 활성 표시 정확
- owner 스코프/미인증 401
"""
from httpx import AsyncClient

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"
SEED_KEYS = {"source_summary", "classification_gate", "documentation_gate", "graph_rag_chat"}
KEY = "graph_rag_chat"


async def _auth(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


async def test_list_prompts_returns_seeds_with_active_version(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get("/prompts", headers=headers)
    assert res.status_code == 200
    prompts = {p["key"]: p for p in res.json()["prompts"]}
    assert SEED_KEYS <= set(prompts)
    assert prompts[KEY]["active_version"] == 1


async def test_get_prompt_returns_active_version(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get(f"/prompts/{KEY}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["key"] == KEY
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["prompt_text"]
    assert body["output_schema"]["type"] == "object"


# ---------------------------------------------------------------------------
# 저장 (새 버전 + 활성) / 롤백 (포인터 이동)
# ---------------------------------------------------------------------------


async def test_save_creates_new_version_and_activates(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/prompts/{KEY}/versions",
        json={"prompt_text": "새 본문 v2", "output_schema": {"type": "object"}},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["version"] == 2
    assert body["is_active"] is True
    assert body["prompt_text"] == "새 본문 v2"

    # 기존 v1 row는 보존되고, v2가 활성이다.
    versions = (await client.get(f"/prompts/{KEY}/versions", headers=headers)).json()[
        "versions"
    ]
    by_ver = {v["version"]: v for v in versions}
    assert set(by_ver) == {1, 2}
    assert by_ver[2]["is_active"] is True
    assert by_ver[1]["is_active"] is False
    assert by_ver[1]["prompt_text"]  # v1 본문 불변 보존

    # GET active도 v2를 가리킨다.
    active = (await client.get(f"/prompts/{KEY}", headers=headers)).json()
    assert active["version"] == 2


async def test_rollback_moves_pointer_without_new_row(client: AsyncClient) -> None:
    headers = await _auth(client)
    # v2 저장으로 활성 이동
    await client.post(
        f"/prompts/{KEY}/versions",
        json={"prompt_text": "v2", "output_schema": {"type": "object"}},
        headers=headers,
    )
    # v1로 롤백
    res = await client.post(
        f"/prompts/{KEY}/rollback", json={"version": 1}, headers=headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 1
    assert res.json()["is_active"] is True

    versions = (await client.get(f"/prompts/{KEY}/versions", headers=headers)).json()[
        "versions"
    ]
    # 새 row 안 생김 — 여전히 2개.
    assert {v["version"] for v in versions} == {1, 2}
    by_ver = {v["version"]: v for v in versions}
    assert by_ver[1]["is_active"] is True
    assert by_ver[2]["is_active"] is False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


async def test_get_unknown_prompt_404(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.get("/prompts/not_a_prompt", headers=headers)
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "PROMPT_NOT_FOUND"


async def test_save_unknown_prompt_404(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        "/prompts/not_a_prompt/versions",
        json={"prompt_text": "본문", "output_schema": {"type": "object"}},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "PROMPT_NOT_FOUND"


async def test_save_empty_body_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/prompts/{KEY}/versions",
        json={"prompt_text": "   ", "output_schema": {"type": "object"}},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "EMPTY_PROMPT_BODY"


async def test_save_invalid_output_schema_rejected(client: AsyncClient) -> None:
    headers = await _auth(client)
    # type 값이 숫자 — 유효한 JSON Schema가 아니다(check_schema 실패).
    res = await client.post(
        f"/prompts/{KEY}/versions",
        json={"prompt_text": "본문", "output_schema": {"type": 123}},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "INVALID_OUTPUT_SCHEMA"


async def test_rollback_unknown_version_404(client: AsyncClient) -> None:
    headers = await _auth(client)
    res = await client.post(
        f"/prompts/{KEY}/rollback", json={"version": 99}, headers=headers
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "PROMPT_VERSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/prompts")).status_code == 401
    assert (
        await client.post(
            f"/prompts/{KEY}/versions",
            json={"prompt_text": "x", "output_schema": {"type": "object"}},
        )
    ).status_code == 401
