"""AXKG-SPEC-005 documents/graph API 테스트 (WP2 Phase 3).

커버: 문서 조회·links·graph/documents(source 제외)·neighborhood·search·rebuild
+ link-preview Case Matrix(BROKEN_WIKILINK/UP_WITHOUT_BODY_LINK/DUPLICATE_STEM) + owner 인증.
문서 인덱스는 POST /graph/rebuild로 fixture markdown root에서 채운다.
"""
from pathlib import Path

import pytest
from httpx import AsyncClient

from axkg.config import settings

SEED_EMAIL = "kknaks@medisolveai.com"
SEED_PASSWORD = "1234"

CONCEPT = """---
type: concept
id: CONCEPT-GRAPH-RAG
title: Graph RAG
aliases: [grag]
tags: [ai]
---
Graph RAG combines retrieval with a knowledge graph.
"""
RETRIEVER = """---
type: reference
id: REF-RETRIEVER
title: Retriever design note
up: [graph-rag]
---
The retriever uses keyword score. See [[graph-rag]].
"""
INBOX = """---
type: reference
id: REF-INBOX
title: Source inbox note
---
Relates to [[retriever-note|the retriever]].
"""
SOURCE = """---
type: source
id: SRC-1
title: Raw source record
---
Raw text.
"""


@pytest.fixture
def seeded_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "c").mkdir()
    (tmp_path / "r").mkdir()
    (tmp_path / "s").mkdir()
    (tmp_path / "c" / "graph-rag.md").write_text(CONCEPT, "utf-8")
    (tmp_path / "r" / "retriever-note.md").write_text(RETRIEVER, "utf-8")
    (tmp_path / "r" / "inbox-note.md").write_text(INBOX, "utf-8")
    (tmp_path / "s" / "raw-source.md").write_text(SOURCE, "utf-8")
    monkeypatch.setattr(settings, "axkg_markdown_root", str(tmp_path))
    return tmp_path


async def _auth(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


async def _rebuild(client: AsyncClient, headers: dict[str, str]) -> dict:
    res = await client.post("/graph/rebuild", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def _doc_id(client: AsyncClient, headers: dict[str, str], stem: str) -> str:
    res = await client.get("/documents", headers=headers)
    assert res.status_code == 200
    for doc in res.json()["documents"]:
        if doc["stem"] == stem:
            return doc["id"]
    raise AssertionError(f"document {stem} not found")


# ---------------------------------------------------------------------------
# rebuild + 조회
# ---------------------------------------------------------------------------


async def test_rebuild_then_list_documents(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    stats = await _rebuild(client, headers)
    assert stats["indexed"] == 4
    res = await client.get("/documents", headers=headers)
    stems = {d["stem"] for d in res.json()["documents"]}
    assert stems == {"graph-rag", "retriever-note", "inbox-note", "raw-source"}


async def test_document_links_wikilink_up_backlink(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    retriever_id = await _doc_id(client, headers, "retriever-note")
    res = await client.get(f"/documents/{retriever_id}/links", headers=headers)
    assert res.status_code == 200
    body = res.json()
    # 본문+up → lineage는 up에, 백링크는 inbox-note(assoc).
    assert [l["target"] for l in body["up"]] == ["graph-rag"]
    assert body["wikilinks"] == []
    assert [b["stem"] for b in body["backlinks"]] == ["inbox-note"]


async def test_graph_documents_excludes_source(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    res = await client.get("/graph/documents", headers=headers)
    assert res.status_code == 200
    data = res.json()
    node_stems = {n["stem"] for n in data["nodes"]}
    assert node_stems == {"graph-rag", "retriever-note", "inbox-note"}
    assert "raw-source" not in node_stems
    # resolve된 엣지만: retriever→graph-rag(lineage), inbox→retriever(assoc).
    edge_types = sorted(e["edge_type"] for e in data["edges"])
    assert edge_types == ["assoc", "lineage"]


async def test_graph_neighborhood(client: AsyncClient, seeded_root: Path) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    graph_rag_id = await _doc_id(client, headers, "graph-rag")
    res = await client.get(
        f"/graph/documents/{graph_rag_id}/neighborhood?depth=1", headers=headers
    )
    assert res.status_code == 200
    stems = {n["stem"] for n in res.json()["nodes"]}
    assert "graph-rag" in stems and "retriever-note" in stems


async def test_graph_search_ranks_and_returns_snapshot(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    res = await client.post(
        "/graph/search", json={"query": "retriever keyword"}, headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["results"][0]["stem"] == "retriever-note"
    snapshot_stems = {e["stem"] for e in data["index_snapshot"]}
    assert "raw-source" not in snapshot_stems
    assert "graph-rag" in snapshot_stems


# ---------------------------------------------------------------------------
# 단건 상세 markdown_full read-through (PLAN-009-T-034)
# ---------------------------------------------------------------------------


async def test_document_detail_includes_markdown_full(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    retriever_id = await _doc_id(client, headers, "retriever-note")
    res = await client.get(f"/documents/{retriever_id}", headers=headers)
    assert res.status_code == 200
    # frontmatter+본문 전문 그대로(파일 read-through).
    assert res.json()["markdown_full"] == RETRIEVER


async def test_document_detail_markdown_full_null_when_file_missing(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    retriever_id = await _doc_id(client, headers, "retriever-note")
    # 인덱싱 이후 디스크 파일 삭제 → read-through 대상 없음 → null (인덱스 필드는 유지).
    (seeded_root / "r" / "retriever-note.md").unlink()
    res = await client.get(f"/documents/{retriever_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["markdown_full"] is None
    assert body["stem"] == "retriever-note"


async def test_document_list_omits_markdown_full(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    res = await client.get("/documents", headers=headers)
    assert res.status_code == 200
    # 목록은 본문을 싣지 않는다(payload 비대 방지) — 단건 상세만 read-through.
    assert all(d["markdown_full"] is None for d in res.json()["documents"])


# ---------------------------------------------------------------------------
# link-preview Case Matrix
# ---------------------------------------------------------------------------


async def test_link_preview_broken_wikilink(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    doc_id = await _doc_id(client, headers, "inbox-note")
    res = await client.post(
        f"/documents/{doc_id}/link-preview",
        json={"markdown": "body links [[nowhere-doc]]"},
        headers=headers,
    )
    assert res.status_code == 200
    codes = {e["error_code"] for e in res.json()["errors"]}
    assert "BROKEN_WIKILINK" in codes


async def test_link_preview_up_without_body(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    doc_id = await _doc_id(client, headers, "inbox-note")
    md = "---\ntype: reference\nid: X\ntitle: X\nup: [graph-rag]\n---\nNo body link.\n"
    res = await client.post(
        f"/documents/{doc_id}/link-preview", json={"markdown": md}, headers=headers
    )
    assert res.status_code == 200
    codes = {e["error_code"] for e in res.json()["errors"]}
    assert "UP_WITHOUT_BODY_LINK" in codes


async def test_link_preview_duplicate_stem(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    doc_id = await _doc_id(client, headers, "inbox-note")
    # 다른 문서(inbox-note)에서 이미 존재하는 stem(graph-rag)로 저장 시도.
    res = await client.post(
        f"/documents/{doc_id}/link-preview",
        json={"markdown": "new draft [[retriever-note]]", "stem": "graph-rag"},
        headers=headers,
    )
    assert res.status_code == 200
    codes = {e["error_code"] for e in res.json()["errors"]}
    assert "DUPLICATE_STEM" in codes


async def test_link_preview_resolves_existing_target(
    client: AsyncClient, seeded_root: Path
) -> None:
    headers = await _auth(client)
    await _rebuild(client, headers)
    doc_id = await _doc_id(client, headers, "inbox-note")
    res = await client.post(
        f"/documents/{doc_id}/link-preview",
        json={"markdown": "see [[graph-rag]]"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["errors"] == []
    assert body["links"][0]["target"] == "graph-rag"
    assert body["links"][0]["resolved"] is True


# ---------------------------------------------------------------------------
# 인증 / 404
# ---------------------------------------------------------------------------


async def test_documents_requires_auth(client: AsyncClient, seeded_root: Path) -> None:
    res = await client.get("/documents")
    assert res.status_code == 401


async def test_document_not_found(client: AsyncClient, seeded_root: Path) -> None:
    headers = await _auth(client)
    res = await client.get(
        "/documents/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "DOCUMENT_NOT_FOUND"
