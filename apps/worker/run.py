"""open-kknaks worker — AXKG AI task 실행 (docker compose로 구동)."""

import asyncio
import os

from open_kknaks.broker.redis import RedisBroker
# 요약 작업 workspace — 이미지에 COPY된 프로젝트(진입 문서 CLAUDE.md/agent.md +
# context/source-summary-guide.md). claude를 이 디렉토리 "안에서" 실행하면 진입 문서를
# 스스로 읽는다. WORK_DIR env가 없을 때의 기본값을 run.py 옆 workspace로 고정한다
# (docker: /app/workspace, 로컬: apps/worker/workspace — 둘 다 이 경로로 해석됨).
DEFAULT_WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
from open_kknaks.config import ClaudeConfig
from open_kknaks.middleware.cost import CostMiddleware
from open_kknaks.middleware.logging import LoggingMiddleware
from open_kknaks.middleware.retries import RetriesMiddleware
from open_kknaks.middleware.timeout import TimeoutMiddleware
from open_kknaks.worker.worker import ClaudeWorker


async def main() -> None:
    broker = RedisBroker(
        url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        namespace=os.environ.get("NAMESPACE", "axkg"),
    )
    await broker.connect()

    config = ClaudeConfig(
        work_dir=os.environ.get("WORK_DIR", DEFAULT_WORK_DIR),
    )

    worker = ClaudeWorker(
        broker=broker,
        config=config,
        queues=os.environ.get("QUEUES", "default").split(","),
        concurrency=int(os.environ.get("CONCURRENCY", "2")),
        middleware=[
            LoggingMiddleware(),
            RetriesMiddleware(max_retries=2),
            TimeoutMiddleware(),
            CostMiddleware(
                worker_budget_usd=5.0,
                global_budget_usd=20.0,
            ),
        ],
    )

    print(f"Worker starting: queues={worker.queues}, concurrency={worker.concurrency}")

    try:
        await worker.run()
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
