from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    """/health는 Bearer 검증 제외 — token 없이 200 (AXKG-SPEC-008)."""
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
