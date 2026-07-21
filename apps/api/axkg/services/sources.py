"""Source Inbox lifecycle (AXKG-SPEC-003). URL 검증·중복 처리·요약 재시도 큐잉. WP1 Phase 1.

경계:
- 이 Phase는 수신·목록·상세·중복·재시도 **큐잉**까지다. 실제 원문 수집 adapter는
  Phase 2(AXKG-SPEC-012), 요약 실행·`received` 자동 트리거는 Phase 3(AXKG-SPEC-011①).
- 요약 task 생성은 AI 실행 client 없이 queued row만 만든다(worker가 Phase 3에서 소비).
  provider/model/options 스냅샷은 AiExecutionService.create_task와 동일한 SPEC-007
  병합 순서를 쓴다.
"""
from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession

from axkg.dto.ai import AiTaskDTO
from axkg.dto.source import SourceDTO
from axkg.dto.source_material import SourceMaterial
from axkg.integrations.source_collection.docx_text import (
    DOCX_EXTENSION,
    DocxExtractError,
    extract_docx_text,
    is_docx_filename,
)
from axkg.models.base import utcnow
from axkg.services.ai.source_summary import INTAKE_NOTE_KEY
from axkg.services.project_scaffold import origin_staging_path
from axkg.storage.markdown_root import MarkdownRoot
from axkg.repositories.ai_task_definitions import AiTaskDefinitionRepository
from axkg.repositories.ai_tasks import AiTaskRepository
from axkg.repositories.settings import SettingRepository
from axkg.repositories.sources import SourceRepository
from axkg.services.ai.resolution import resolve_execution_config

SUMMARY_TASK_TYPE = "collect_source_summary"
AI_PROVIDER_SETTINGS_KEY = "ai_provider"
MAX_MANUAL_NOTE_LENGTH = 2000
# 업로드 v1 허용 확장자 (AXKG-SPEC-003 §4 Validation, WORK-010/011). md=본문 그대로,
# docx=본문 텍스트만 추출(표/이미지 파싱 계약 없음, AXKG-DEC-007 D5 · SPEC-012 docx_text).
UPLOAD_ALLOWED_EXTENSION = ".md"
UPLOAD_ALLOWED_EXTENSIONS = (".md", DOCX_EXTENSION)
# 업로드 파일 크기 상한 — 구현 기본값(AXKG-SPEC-003 §7 OQ). 1 MiB.
# md는 텍스트라 1 MiB면 장문 노트/아티클도 충분하고, 요약 입력·메모리·남용을 유계로 둔다.
MAX_UPLOAD_SIZE_BYTES = 1 * 1024 * 1024

# 중복 재수신 시 기존 source에 이벤트를 연결(누적)할 수 있는 상태 (documented 전).
_LINKABLE_STATUSES = ("received", "summarizing", "summarized", "collection_failed")
# 이미 처리가 끝나 새 입력을 duplicate candidate로만 표시하는 상태.
_CANDIDATE_STATUSES = ("documented", "archived", "ignored")


class InvalidUrlError(Exception):
    """source_url이 http/https 형식이 아니다 (Case Matrix: INVALID_URL)."""


class ManualNoteTooLongError(Exception):
    """수동 메모 길이 초과 (Case Matrix: MANUAL_NOTE_TOO_LONG)."""


class SourceNotFoundError(Exception):
    def __init__(self, source_id: uuid.UUID) -> None:
        super().__init__(f"source not found: {source_id}")
        self.source_id = source_id


class CollectionRetryNotAllowedError(Exception):
    """collection_failed가 아닌 source의 요약 재시도 (Case Matrix: COLLECTION_RETRY_NOT_ALLOWED)."""

    def __init__(self, source_id: uuid.UUID, status: str) -> None:
        super().__init__(f"collection retry not allowed: source {source_id} status={status}")
        self.source_id = source_id
        self.status = status


class SummaryFeedbackNotAllowedError(Exception):
    """summarized가 아닌 source에 요약 피드백 (Case Matrix: SUMMARY_FEEDBACK_NOT_ALLOWED)."""

    def __init__(self, source_id: uuid.UUID, status: str) -> None:
        super().__init__(f"summary feedback not allowed: source {source_id} status={status}")
        self.source_id = source_id
        self.status = status


class EmptyFeedbackError(Exception):
    """빈/공백 피드백 (Case Matrix: EMPTY_FEEDBACK)."""

    def __init__(self, source_id: uuid.UUID) -> None:
        super().__init__(f"empty summary feedback: source {source_id}")
        self.source_id = source_id


class EmptyPushTextError(Exception):
    """빈/공백 chat push 대화 내용 (AXKG-SPEC-006 Case Matrix: EMPTY_PUSH_TEXT)."""


class UnsupportedUploadTypeError(Exception):
    """업로드 파일이 v1 허용(.md) 형식이 아님 (AXKG-SPEC-003 Case Matrix: UNSUPPORTED_UPLOAD_TYPE)."""


class UploadTooLargeError(Exception):
    """업로드 파일이 크기 상한 초과 (AXKG-SPEC-003 §7 OQ 구현 기본값)."""


class EmptyUploadTextError(Exception):
    """업로드 md 본문이 비어 있음 (AXKG-SPEC-003 §4 Validation: upload raw_text 필수)."""


class ManualSourceResult:
    """수동 입력 결과 — 신규 저장 또는 기존 source 연결/후보 표시.

    duplicate_kind: None(신규) / "linked"(기존에 이벤트 연결) / "candidate"(문서화 후 중복 후보).
    """

    def __init__(
        self,
        source: SourceDTO,
        *,
        duplicate_kind: str | None = None,
        existing_source_id: uuid.UUID | None = None,
    ) -> None:
        self.source = source
        self.duplicate_kind = duplicate_kind
        self.existing_source_id = existing_source_id


class QueueCollectionResult:
    def __init__(self, source: SourceDTO, ai_task: AiTaskDTO) -> None:
        self.source = source
        self.ai_task = ai_task


class CollectionApplyResult:
    """수집 성공 후 canonical 반영 결과.

    normalized_url_changed: canonical 정규화가 기존과 달라 갱신됐는지.
    merged_into: canonical이 기존의 다른 active source와 합류하면 그 source id (S-2).
    """

    def __init__(
        self,
        source: SourceDTO,
        *,
        normalized_url_changed: bool,
        merged_into: uuid.UUID | None,
    ) -> None:
        self.source = source
        self.normalized_url_changed = normalized_url_changed
        self.merged_into = merged_into


def normalize_url(raw: str) -> str:
    """중복 판정용 정규화: scheme/host 소문자, 기본 포트·fragment·말미 슬래시 제거.

    query는 의미를 바꿀 수 있어 보존한다. 검증(http/https)은 validate_url이 담당한다.
    """
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    netloc = host.lower()
    if parts.port is not None:
        default = {"http": 80, "https": 443}.get(scheme)
        if parts.port != default:
            netloc = f"{netloc}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def validate_url(raw: str) -> None:
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise InvalidUrlError


class SourceService:
    def __init__(self, session: AsyncSession) -> None:
        self._sources = SourceRepository(session)
        self._tasks = AiTaskRepository(session)
        self._definitions = AiTaskDefinitionRepository(session)
        self._settings = SettingRepository(session)

    # ------------------------------------------------------------------
    # 수신
    # ------------------------------------------------------------------

    async def create_manual(
        self,
        *,
        source_url: str,
        raw_text: str | None,
        submitted_by: uuid.UUID | None,
    ) -> ManualSourceResult:
        """페이지 직접 입력 (S-3) + 중복 처리 (S-2). received 상태로 저장."""
        validate_url(source_url)
        if raw_text is not None and len(raw_text) > MAX_MANUAL_NOTE_LENGTH:
            raise ManualNoteTooLongError

        normalized = normalize_url(source_url)
        existing = await self._sources.get_active_by_normalized_url(normalized)
        if existing is not None:
            return await self._handle_duplicate(
                existing,
                channel="manual",
                submitted_by=submitted_by,
                raw_text=raw_text,
                slack_message_ts=None,
            )

        created = await self._sources.create(
            source_url=source_url,
            normalized_url=normalized,
            source_channel="manual",
            submitted_by=submitted_by,
            submitted_at=utcnow(),
            raw_text=raw_text,
        )
        return ManualSourceResult(created)

    async def create_slack(
        self,
        *,
        source_url: str,
        raw_text: str | None,
        slack_user_id: str | None,
        channel_id: str | None,
        trigger_key: str,
    ) -> ManualSourceResult:
        """슬래시 커맨드 수신 (S-1) + 중복 처리 (S-2). received·source_channel=slack로 저장.

        Slack user는 제품 user UUID가 아니므로 `submitted_by=None`으로 두고 채널/유저/멱등키를
        metadata에 남긴다(DB README: Slack user는 MVP에서 metadata에 산다). 최초 수신 이벤트도
        `metadata.slack_events[]`에 기록한다.
        """
        validate_url(source_url)
        normalized = normalize_url(source_url)
        existing = await self._sources.get_active_by_normalized_url(normalized)
        if existing is not None:
            return await self._handle_duplicate(
                existing,
                channel="slack",
                submitted_by=None,
                raw_text=raw_text,
                slack_message_ts=None,
                slack_user_id=slack_user_id,
                channel_id=channel_id,
            )

        event: dict[str, Any] = {
            "ts": None,
            "channel": "slack",
            "channel_id": channel_id,
            "user": slack_user_id,
            "text": raw_text,
            "received_at": utcnow().isoformat(),
        }
        created = await self._sources.create(
            source_url=source_url,
            normalized_url=normalized,
            source_channel="slack",
            submitted_by=None,
            submitted_at=utcnow(),
            raw_text=raw_text,
            metadata={
                "slack_events": [event],
                "slack_channel": channel_id,
                "slack_user": slack_user_id,
                "slack_trigger_key": trigger_key,
            },
        )
        return ManualSourceResult(created)

    async def create_chat_push(
        self,
        *,
        raw_text: str,
        submitted_by: uuid.UUID | None,
        chat_id: uuid.UUID,
        run_id: uuid.UUID | None,
    ) -> SourceDTO:
        """채팅④ 방안 push 수신 (S-4) — `source_channel=chat` source를 received로 생성한다.

        push 시점까지의 대화 내용 전부(방안 포함)를 `raw_text`로 받는다. URL이 없으므로
        `source_url`·`normalized_url`은 null이고(중복 판정 대상 아님), 요약 파이프라인에서
        이 대화 내용이 곧 요약 입력이 된다(AXKG-SPEC-012 User Note Fallback 경로 재사용).
        push를 만든 chat/run을 provenance로 metadata에 남긴다. 대화 직렬화(형식·조립 위치)는
        호출부(chat 표면)가 소유한다 — 이 서비스는 이미 조립된 텍스트를 받는다.

        빈/공백 대화는 `EmptyPushTextError`로 거부한다(trim 후 non-empty, AXKG-SPEC-003 §4).
        중복 병합은 하지 않는다 — chat source는 URL이 없어 normalized_url 중복 판정에 들지 않는다.
        """
        text = (raw_text or "").strip()
        if not text:
            raise EmptyPushTextError
        provenance: dict[str, Any] = {"chat_id": str(chat_id)}
        if run_id is not None:
            provenance["run_id"] = str(run_id)
        return await self._sources.create(
            source_url=None,
            normalized_url=None,
            source_channel="chat",
            submitted_by=submitted_by,
            submitted_at=utcnow(),
            raw_text=text,
            metadata={"chat_push": provenance},
        )

    async def create_upload(
        self,
        *,
        filename: str | None,
        content: bytes,
        submitted_by: uuid.UUID | None,
        note: str | None = None,
        markdown_root: MarkdownRoot | None = None,
    ) -> SourceDTO:
        """파일 업로드 intake (S-5) — `source_channel=upload` source를 received로 생성한다.

        v1 허용 확장자: `.md`(본문 그대로)·`.docx`(본문 텍스트만 추출, WP11 Phase 2). 그 외
        확장자/디코딩 불가/손상 docx는 `UnsupportedUploadTypeError`로 거부하고 **source row를
        만들지 않는다**(intake validation, 수집 실패와 무관 — SPEC-012 adapter 경로를 타지 않는다).
        크기 상한 초과는 `UploadTooLargeError`, 본문이 비면 `EmptyUploadTextError`.

        - **md**: frontmatter는 strip하지 않고 본문 그대로 보존한다(무손실·무파서, BOM만 제거).
          요약①이 frontmatter 메타(제목/태그)도 함께 정제한다.
        - **docx**: `word/document.xml`의 문단 텍스트만 추출해 raw_text에 담는다(표/이미지 파싱
          계약 없음, AXKG-DEC-007 D5). 기능별 구조화는 요약①이 담당한다. 첨부 docx **원본 raw**는
          `markdown_root`가 있으면 origin staging에 best-effort 보관하고(그래프 노드 아님), corp
          매칭·게이트 승인 시 `projects/{corp}/origin/`으로 finalize된다(Phase 4).

        업로드 본문 자체가 원문이라 URL 수집 없이 raw_text가 곧 요약 입력이 된다(fallback 아님).
        `note`(intake 메모, 회사명 등)가 있으면 metadata에 저장돼 탭 무관 항상 요약 컨텍스트로
        동반된다(SPEC-003, WP11 Phase 2). Phase 4 corp 바인딩이 이 메모를 읽는다.
        """
        name = (filename or "").strip()
        if not name.lower().endswith(UPLOAD_ALLOWED_EXTENSIONS):
            raise UnsupportedUploadTypeError
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise UploadTooLargeError

        if is_docx_filename(name):
            try:
                text = extract_docx_text(content)
            except DocxExtractError as exc:
                # .docx 확장자여도 zip/document.xml이 아니면 유효한 docx가 아니다.
                raise UnsupportedUploadTypeError from exc
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                # 텍스트로 디코딩되지 않으면 .md 확장자여도 유효한 md가 아니다.
                raise UnsupportedUploadTypeError from exc
        if not text.strip():
            raise EmptyUploadTextError

        metadata: dict[str, Any] = {}
        clean_note = (note or "").strip()
        if clean_note:
            if len(clean_note) > MAX_MANUAL_NOTE_LENGTH:
                raise ManualNoteTooLongError
            metadata[INTAKE_NOTE_KEY] = clean_note

        # origin 첨부 원본 raw staging (docx만, best-effort). corp 미확정 단계라 임시 경로에 둔다.
        if is_docx_filename(name) and markdown_root is not None and content:
            staged = self._stage_origin(markdown_root, name, content)
            if staged is not None:
                metadata["origin"] = staged

        return await self._sources.create(
            source_url=None,
            normalized_url=None,
            source_channel="upload",
            submitted_by=submitted_by,
            submitted_at=utcnow(),
            raw_text=text,
            original_filename=name,
            metadata=metadata or None,
        )

    @staticmethod
    def _stage_origin(
        markdown_root: MarkdownRoot, filename: str, content: bytes
    ) -> dict[str, str] | None:
        """origin 첨부 원본을 임시 staging에 raw로 쓴다(best-effort). 실패/미마운트면 None.

        root가 아직 마운트되지 않았으면(테스트/오프라인) 조용히 건너뛴다 — origin은 감사용
        부가물이라 요약/문서화 흐름을 막지 않는다. staging 토큰은 충돌 없는 uuid다.
        """
        if not markdown_root.root.is_dir():
            return None
        token = str(uuid.uuid4())
        rel = origin_staging_path(token, filename)
        try:
            markdown_root.write_bytes(rel, content)
        except OSError:
            return None
        return {"filename": PurePosixPath(filename.strip()).name, "staged_rel": rel}

    async def _handle_duplicate(
        self,
        existing: SourceDTO,
        *,
        channel: str,
        submitted_by: uuid.UUID | None,
        raw_text: str | None,
        slack_message_ts: str | None,
        slack_user_id: str | None = None,
        channel_id: str | None = None,
    ) -> ManualSourceResult:
        if existing.status in _CANDIDATE_STATUSES:
            updated = await self._sources.mark_duplicate_candidate(existing.id)
            return ManualSourceResult(
                updated, duplicate_kind="candidate", existing_source_id=existing.id
            )
        event: dict[str, Any] = {
            "ts": slack_message_ts,
            "channel": channel,
            "user": slack_user_id
            if slack_user_id is not None
            else (str(submitted_by) if submitted_by is not None else None),
            "text": raw_text,
            "received_at": utcnow().isoformat(),
        }
        if channel_id is not None:
            event["channel_id"] = channel_id
        updated = await self._sources.append_intake_event(existing.id, event)
        return ManualSourceResult(
            updated, duplicate_kind="linked", existing_source_id=existing.id
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    async def get(self, source_id: uuid.UUID) -> SourceDTO:
        source = await self._sources.get(source_id)
        if source is None:
            raise SourceNotFoundError(source_id)
        return source

    async def get_detail(self, source_id: uuid.UUID) -> tuple[SourceDTO, str | None]:
        """상세(U-2)용. collection_failed면 최신 실패 task의 error_message를 함께 반환한다."""
        source = await self.get(source_id)
        error_message: str | None = None
        if source.status == "collection_failed":
            failed = await self._tasks.get_latest_failed_by_source(
                source_id, SUMMARY_TASK_TYPE
            )
            error_message = failed.error_message if failed else None
        return source, error_message

    async def list(self, *, status: str | None = None) -> list[SourceDTO]:
        return await self._sources.list(status=status)

    async def list_ai_tasks(self, source_id: uuid.UUID) -> list[AiTaskDTO]:
        await self.get(source_id)  # 404 보장
        return await self._tasks.list_by_source(source_id)

    # ------------------------------------------------------------------
    # 요약 재시도 큐잉 (실행은 Phase 3 worker)
    # ------------------------------------------------------------------

    async def start_summary(self, source_id: uuid.UUID) -> QueueCollectionResult:
        """received source의 요약을 최초 트리거한다: queued task 생성 + summarizing 전이.

        SPEC-011 S-1: source가 등록되면(received) 시스템이 collect_source_summary task를
        만든다. 실제 실행(수집·AI)은 비동기(background/worker) 소관이라 여기서 막지 않는다.
        재시도(collection_failed)는 `queue_collection`이 담당한다 — 이 경로는 최초 1회다.
        """
        source = await self.get(source_id)
        if source.status != "received":
            raise CollectionRetryNotAllowedError(source_id, source.status)
        task = await self._enqueue_summary_task(source_id, None)
        updated = await self._sources.set_status(source_id, "summarizing")
        return QueueCollectionResult(updated, task)

    async def queue_collection(
        self, source_id: uuid.UUID, *, note: str | None = None
    ) -> QueueCollectionResult:
        """collection_failed source의 요약을 재시도 큐에 넣고 summarizing으로 전이한다.

        새 queued collect_source_summary task를 만들고, 직전 failed task가 있으면
        retry_of_task_id로 연결한다(실패 task 불변, AXKG-SPEC-003/002).

        `note`가 주어지면(단건 호출) 메모(raw_text)를 갱신한 뒤 재큐한다 — 원문 수집이 다시
        실패해도 메모가 있으면 user_note fallback으로 요약된다(PLAN-005-T-013, FE T-014 소비).
        """
        source = await self.get(source_id)
        if source.status != "collection_failed":
            raise CollectionRetryNotAllowedError(source_id, source.status)

        # upload 채널은 URL 수집이 없고 raw_text(md 본문)가 곧 원문이다(AXKG-WORK-010 C-3,
        # SPEC-012 §5 경계). user_note는 URL 수집 실패 fallback 전용이므로 upload에는 의미가
        # 없다 — note가 와도 raw_text(원문)를 덮어쓰지 않도록 무시하고 원문 그대로 재큐한다.
        # (재시도 자체는 막지 않는다: 재큐 후 build_data_blocks의 upload 분기로 요약 성공.)
        if note is not None and source.source_channel != "upload":
            if len(note) > MAX_MANUAL_NOTE_LENGTH:
                raise ManualNoteTooLongError
            await self._sources.set_raw_text(source_id, note)

        previous_failed = await self._tasks.get_latest_failed_by_source(
            source_id, SUMMARY_TASK_TYPE
        )
        task = await self._enqueue_summary_task(source_id, previous_failed)
        updated = await self._sources.set_status(source_id, "summarizing")
        return QueueCollectionResult(updated, task)

    # ------------------------------------------------------------------
    # 요약 피드백 재요약 — 세션 resume 재실행 (PLAN-005-T-016 / SPEC-002)
    # ------------------------------------------------------------------

    async def submit_summary_feedback(
        self, source_id: uuid.UUID, *, feedback: str
    ) -> QueueCollectionResult:
        """summarized source에 피드백을 주면 직전 요약 세션을 resume해 재요약을 큐잉한다.

        흐름(사용자 확정): 직전 요약 task의 `open_kknaks_session_id`로 claude 세션을 이어붙여
        (`options.resume={mode:session, session_id}`) 피드백만 입력으로 재실행한다 → 원문·지침
        재전송 없이 v2를 만든다. 새 `collect_source_summary` ai_task를 만들고 직전 요약 task에
        `retry_of_task_id`로 링크(요약 lineage 한 체인)한 뒤 `summarizing`으로 전이한다. 직전
        요약 task는 불변 보존(SPEC-002). 실제 실행은 background(`execute_source_summary`) 소관.
        """
        source = await self.get(source_id)
        if source.status != "summarized":
            raise SummaryFeedbackNotAllowedError(source_id, source.status)
        text = (feedback or "").strip()
        if not text:
            raise EmptyFeedbackError(source_id)

        # resume 대상 = 현재 active 요약 버전(vN)의 세션 (SPEC-002 open-kknaks Session Rule을
        # 요약 버전에 적용: active revision session → 그 revision의 원 task session → 폴백).
        # 게이트 _resolve_resume_session의 요약판이다 — active 버전을 SoT로 읽는다(T-012).
        active = await self._sources.get_active_summary_revision(source_id)
        previous: AiTaskDTO | None = None
        resume_session: str | None = None
        if active is not None:
            resume_session = active.open_kknaks_session_id
            if active.ai_task_id is not None:
                previous = await self._tasks.get(active.ai_task_id)
        if previous is None:
            # active 버전이 없거나(백필 전 데이터) task 링크가 없으면 최신 succeeded task로 폴백.
            previous = await self._tasks.get_latest_succeeded_by_source(
                source_id, SUMMARY_TASK_TYPE
            )
        if resume_session is None and previous is not None:
            resume_session = previous.open_kknaks_session_id
        task = await self._enqueue_feedback_task(source_id, text, previous, resume_session)
        updated = await self._sources.set_status(source_id, "summarizing")
        return QueueCollectionResult(updated, task)

    async def _enqueue_feedback_task(
        self,
        source_id: uuid.UUID,
        feedback: str,
        previous: AiTaskDTO | None,
        resume_session: str | None,
    ) -> AiTaskDTO:
        definition = await self._definitions.get_by_key(SUMMARY_TASK_TYPE)
        if definition is None or not definition.enabled:
            raise LookupError(f"ai_task_definition missing: {SUMMARY_TASK_TYPE}")
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        options = dict(config.options)
        if resume_session:
            # open-kknaks 2.0.2 claude executor 계약: options.resume={mode:session, session_id}
            # → worker가 `claude --resume <session_id>`로 세션을 이어 실행한다. session이 없으면
            # (직전 succeeded task 부재) resume를 걸지 않고 최초 요약처럼 새 세션으로 돈다.
            options["resume"] = {"mode": "session", "session_id": resume_session}
        return await self._tasks.create(
            task_type=SUMMARY_TASK_TYPE,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=options,
            provider_options=config.provider_options,
            source_id=source_id,
            retry_of_task_id=previous.id if previous else None,
            retry_count=(previous.retry_count + 1) if previous else 0,
            payload={
                "kind": "summary_feedback",
                "feedback": feedback,
                "resume_of_task_id": str(previous.id) if previous else None,
            },
        )

    # ------------------------------------------------------------------
    # 수집 결과 반영 — canonical → normalized_url 갱신 + 중복 재검사 (SPEC-012)
    # ------------------------------------------------------------------

    async def apply_collection_result(
        self, source_id: uuid.UUID, material: SourceMaterial
    ) -> CollectionApplyResult:
        """수집 성공 시 canonical_url로 normalized_url을 갱신하고 중복을 재검사한다.

        canonical이 기존의 다른 active source와 합류하면 SPEC-003 S-2를 따라 그 source에
        재수신 이벤트를 연결한다(Phase 1 `append_intake_event` 재사용). 두 row의 병합
        lifecycle(어느 쪽을 남길지)은 요약 파이프라인/사용자 소관으로 남긴다.
        """
        source = await self.get(source_id)
        new_normalized = normalize_url(material.canonical_url)
        changed = new_normalized != source.normalized_url

        merged_into: uuid.UUID | None = None
        existing = await self._sources.get_active_duplicate(new_normalized, source_id)
        if existing is not None:
            await self._sources.append_intake_event(
                existing.id,
                {
                    "ts": None,
                    "channel": "collection_merge",
                    "user": None,
                    "text": material.canonical_url,
                    "received_at": utcnow().isoformat(),
                    "merged_source_id": str(source_id),
                },
            )
            merged_into = existing.id

        updated = source
        if changed:
            updated = await self._sources.set_normalized_url(source_id, new_normalized)
        return CollectionApplyResult(
            updated, normalized_url_changed=changed, merged_into=merged_into
        )

    async def _enqueue_summary_task(
        self, source_id: uuid.UUID, previous_failed: AiTaskDTO | None
    ) -> AiTaskDTO:
        definition = await self._definitions.get_by_key(SUMMARY_TASK_TYPE)
        if definition is None or not definition.enabled:
            raise LookupError(f"ai_task_definition missing: {SUMMARY_TASK_TYPE}")
        global_settings = await self._settings.get_value(AI_PROVIDER_SETTINGS_KEY)
        config = resolve_execution_config(global_settings, definition)
        return await self._tasks.create(
            task_type=SUMMARY_TASK_TYPE,
            task_definition_id=definition.id,
            provider=config.provider,
            model=config.model,
            options=config.options,
            provider_options=config.provider_options,
            source_id=source_id,
            retry_of_task_id=previous_failed.id if previous_failed else None,
            retry_count=(previous_failed.retry_count + 1) if previous_failed else 0,
        )
