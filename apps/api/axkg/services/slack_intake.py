"""Slack intake 아웃바운드 오케스트레이션 (AXKG-SPEC-003 S-1 / WP1 Phase 4).

라우트(얇게)와 요약 실행(summary_execution)이 쓰는 봇 아웃바운드 seam:

- `post_anchor_message`: 접수 직후 봇이 채널에 앵커 메시지를 post하고 그 `ts`를 source
  metadata(`slack_anchor` + `slack_message_ts`)에 저장한다. 슬래시 커맨드는 제출 메시지
  ts가 없으므로 앵커를 봇이 만든다(SPEC-003 S-1 5번).
- `SlackSummaryNotifier`: 요약 완료(`summarized`)/실패(`collection_failed`) 시 앵커
  스레드에 결과를 회신한다. **slack 유입 source에만** 반응하고 manual은 무회신
  (summary_execution이 source_channel로 게이트). 아웃바운드 실패는 요약 task 성패에
  영향을 주지 않도록 호출측(summary_execution)이 예외를 삼킨다.

원문/URL 전문은 로그에 남기지 않는다(Pre-deploy Check).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from axkg.dto.ai import AiTaskDTO
from axkg.dto.source import SourceDTO
from axkg.integrations.slack import SlackBotClient
from axkg.repositories.sources import SourceRepository

logger = logging.getLogger("axkg.slack_intake")


async def post_anchor_message(
    source_id: uuid.UUID,
    channel_id: str,
    bot: SlackBotClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """봇이 채널에 앵커 메시지를 post하고 그 ts를 source metadata에 저장한다.

    best-effort — Slack 아웃바운드 실패가 접수(이미 커밋된 source)를 무르지 않는다.
    """
    try:
        result = await bot.chat_post_message(
            channel_id, "🔖 접수했습니다. 요약을 진행합니다."
        )
    except Exception:
        logger.warning("slack anchor post failed source_id=%s", source_id, exc_info=True)
        return
    ts = result.get("ts")
    async with session_factory() as session:
        await SourceRepository(session).set_slack_anchor(source_id, channel_id, ts)
        await session.commit()


class SlackSummaryNotifier:
    """요약 종료 시 앵커 스레드로 결과를 회신하는 notifier (summary_execution 훅).

    `execute_source_summary(..., notifier=SlackSummaryNotifier(bot))`로 주입한다.
    source_channel != 'slack'이면 summary_execution이 호출 자체를 하지 않는다.
    """

    def __init__(self, bot: SlackBotClient) -> None:
        self._bot = bot

    async def __call__(self, source: SourceDTO, task: AiTaskDTO) -> None:
        anchor = source.metadata.get("slack_anchor") or {}
        channel = anchor.get("channel") or source.metadata.get("slack_channel")
        thread_ts = anchor.get("ts")
        if not channel:
            # 앵커가 아직 안 잡혔으면(post 실패 등) 회신 대상이 없다.
            return
        if source.status == "summarized":
            payload = source.summary_payload or {}
            title = payload.get("title", "") or "(제목 없음)"
            summary = payload.get("summary", "")
            text = f"✅ 요약 완료: {title}\n{summary}".rstrip()
        else:  # collection_failed
            reason = task.error_message or task.error_code or "알 수 없는 오류"
            text = f"⚠️ 요약 실패: {reason}\n`요약 재시도`로 다시 시도할 수 있어요."
        await self._bot.chat_post_message(channel, text, thread_ts=thread_ts)
