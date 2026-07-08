"""YouTube adapter (AXKG-SPEC-012 §2 YouTube Adapter).

metadata(yt-dlp) + transcript(youtube-transcript-api, ko→en) 두 갈래. transcript가 없거나
짧으면 description fallback, 둘 다 부실하면 TRANSCRIPT_UNAVAILABLE. 기존 profile 코드
(`service/jobs/content_enrich.py`, `service/knowledge_capture/source.py`)를 포팅했다(직접 import 아님).
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection.base import (
    CONTENT_FETCH_FAILED,
    INVALID_URL,
    TRANSCRIPT_UNAVAILABLE,
    CollectionError,
    guard_public_url,
    utc_now_iso,
)

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")

MIN_TRANSCRIPT_LENGTH = 100
MIN_DESCRIPTION_LENGTH = 200

# 기본 fetcher는 sync(외부 lib) — to_thread로 감싼다. 테스트는 fake를 주입한다.
MetadataFetcher = Callable[[str], dict[str, Any]]
TranscriptFetcher = Callable[[str], "str | None"]


def is_youtube_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in _YOUTUBE_HOSTS


def extract_video_id(url: str) -> str:
    """host/path/query에서 video id 추출. 실패 시 INVALID_URL (§3)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        value = parsed.path.strip("/").split("/")[0]
    elif parsed.path.startswith("/shorts/"):
        parts = parsed.path.split("/")
        value = parts[2] if len(parts) > 2 else ""
    elif parsed.path.startswith("/embed/"):
        parts = parsed.path.split("/")
        value = parts[2] if len(parts) > 2 else ""
    else:
        value = parse_qs(parsed.query).get("v", [""])[0]
    if not value or not _VIDEO_ID_RE.fullmatch(value):
        raise CollectionError(INVALID_URL, "YouTube video id를 추출할 수 없음")
    return value


def canonical_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _default_metadata_fetcher(video_id: str) -> dict[str, Any]:
    import yt_dlp  # lazy — 실행 환경에만 필요

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(canonical_youtube_url(video_id), download=False)
    return {
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "duration_s": int(info.get("duration") or 0),
        "channel": info.get("uploader") or info.get("channel") or "",
        "tags": info.get("tags") or [],
        "thumbnail": info.get("thumbnail") or "",
        "upload_date": info.get("upload_date") or "",
    }


def _default_transcript_fetcher(video_id: str) -> str | None:
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = YouTubeTranscriptApi()
    fetched = ytt_api.fetch(video_id, languages=["ko", "en"])
    return " ".join(s.text.strip() for s in fetched.snippets if getattr(s, "text", None))


def _upload_date_to_iso(upload_date: str) -> str | None:
    if re.fullmatch(r"\d{8}", upload_date or ""):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return None


async def collect_youtube(
    source_url: str,
    *,
    metadata_fetcher: MetadataFetcher | None = None,
    transcript_fetcher: TranscriptFetcher | None = None,
) -> SourceMaterial:
    metadata_fetcher = metadata_fetcher or _default_metadata_fetcher
    transcript_fetcher = transcript_fetcher or _default_transcript_fetcher

    await guard_public_url(source_url)
    video_id = extract_video_id(source_url)
    canonical = canonical_youtube_url(video_id)

    try:
        metadata = await asyncio.to_thread(metadata_fetcher, video_id)
    except Exception as exc:  # noqa: BLE001 — 수집 실패는 실패 코드로 보존
        raise CollectionError(CONTENT_FETCH_FAILED, "YouTube metadata 수집 실패") from exc

    try:
        transcript = await asyncio.to_thread(transcript_fetcher, video_id)
    except Exception:  # noqa: BLE001 — 자막 없음은 실패가 아니다 (description fallback)
        transcript = None

    description = str(metadata.get("description") or "")
    if transcript and len(transcript.strip()) >= MIN_TRANSCRIPT_LENGTH:
        content_text = transcript.strip()
        content_format = "transcript"
        fetch_method = "youtube_transcript_api"
    elif len(description.strip()) >= MIN_DESCRIPTION_LENGTH:
        content_text = description.strip()
        content_format = "video_description"
        fetch_method = "youtube_metadata"
    else:
        raise CollectionError(
            TRANSCRIPT_UNAVAILABLE, "transcript 없음/미달 + description도 부실"
        )

    title = str(metadata.get("title") or "").strip() or None
    return SourceMaterial(
        source_url=source_url,
        canonical_url=canonical,
        adapter="youtube",
        title=title,
        author=str(metadata.get("channel") or "").strip() or None,
        published_at=_upload_date_to_iso(str(metadata.get("upload_date") or "")),
        duration_seconds=int(metadata.get("duration_s") or 0) or None,
        content_text=content_text,
        content_format=content_format,
        fetch_method=fetch_method,
        fetched_at=utc_now_iso(),
        external_id=video_id,
        metadata={
            "description": description,
            "thumbnail": metadata.get("thumbnail") or "",
            "tags": metadata.get("tags") or [],
            "headings": [],
            "links": [],
            "images": [],
            "page_kind": "unknown",
        },
    )
