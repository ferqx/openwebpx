from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session_maker
from app.services.code_review.review_analyzer import (
    CodeReviewAnalyzerService,
    code_review_analyzer_service,
)
from app.services.code_review.run_service import (
    CodeReviewRunService,
    code_review_run_service,
)


class CodeReviewRunDispatcher:
    def __init__(
        self,
        *,
        run_service: CodeReviewRunService = code_review_run_service,
        analyzer_service: CodeReviewAnalyzerService = code_review_analyzer_service,
    ) -> None:
        self.run_service = run_service
        self.analyzer_service = analyzer_service

    async def enqueue_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
    ) -> dict[str, object]:
        enqueued = await self.run_service.enqueue_run(session=session, run_id=run_id)
        if enqueued.get("transitioned_to_analyzing") is True:
            self._schedule_background_analysis(run_id=run_id)
        return enqueued

    async def complete_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        result_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return await self.run_service.complete_run(
            session=session,
            run_id=run_id,
            result_payload=result_payload,
        )

    async def fail_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        error_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return await self.run_service.fail_run(
            session=session,
            run_id=run_id,
            error_payload=error_payload,
        )

    async def analyze_run(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        analysis_result: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return await self.analyzer_service.analyze_run(
            session=session,
            run_id=run_id,
            analysis_result=analysis_result,
        )

    def _schedule_background_analysis(self, *, run_id: int) -> None:
        session_maker = get_async_session_maker()
        if session_maker is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._run_background_analysis(run_id=run_id, session_maker=session_maker)
        )

    async def _run_background_analysis(
        self, *, run_id: int, session_maker: object
    ) -> None:
        if not callable(session_maker):
            return
        async with session_maker() as session:
            try:
                await self.analyzer_service.analyze_run(session=session, run_id=run_id)
            except Exception as exc:  # noqa: BLE001
                await self.run_service.fail_run(
                    session=session,
                    run_id=run_id,
                    error_payload={
                        "error": "background analysis failed",
                        "detail": str(exc),
                    },
                )


code_review_run_dispatcher = CodeReviewRunDispatcher()
