from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import ReviewRun, ReviewTimelineEvent

INITIAL_REVIEW_EVENT_TYPES = ("review_requested", "queued")


class CodeReviewTimelineService:
    async def append_event(
        self,
        *,
        session: AsyncSession,
        review_run: ReviewRun,
        event_type: str,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        created_at: datetime | None = None,
    ) -> ReviewTimelineEvent:
        existing = await self._find_event(
            session=session,
            review_run_id=review_run.id,
            event_type=event_type,
            dedupe_key=dedupe_key,
        )
        if existing is not None:
            return existing

        event = ReviewTimelineEvent(
            review_run=review_run,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload=payload,
            created_at=created_at or datetime.now(UTC),
        )
        session.add(event)
        return event

    async def record_initial_run_events(
        self,
        *,
        session: AsyncSession,
        review_run: ReviewRun,
        normalized_event: dict[str, Any],
    ) -> list[ReviewTimelineEvent]:
        payload_base = {
            "normalized_event": normalized_event,
            "raw_payload": normalized_event.get("raw_payload"),
        }
        review_requested = await self.append_event(
            session=session,
            review_run=review_run,
            event_type="review_requested",
            dedupe_key=review_run.idempotency_key,
            payload=payload_base,
        )
        queued = await self.append_event(
            session=session,
            review_run=review_run,
            event_type="queued",
            dedupe_key=review_run.idempotency_key,
            payload={**payload_base, "queued": True},
        )
        return [review_requested, queued]

    async def list_events(
        self,
        *,
        session: AsyncSession,
        review_run_id: int,
    ) -> list[ReviewTimelineEvent]:
        result = await session.scalars(select(ReviewTimelineEvent))
        events = [
            event for event in result.all() if event.review_run_id == review_run_id
        ]
        events.sort(
            key=lambda event: (
                event.created_at or datetime.min.replace(tzinfo=UTC),
                event.id or 0,
            )
        )
        return events

    async def _find_event(
        self,
        *,
        session: AsyncSession,
        review_run_id: int | None,
        event_type: str,
        dedupe_key: str | None,
    ) -> ReviewTimelineEvent | None:
        if review_run_id is None:
            return None
        result = await session.scalars(select(ReviewTimelineEvent))
        for event in result.all():
            if (
                event.review_run_id == review_run_id
                and event.event_type == event_type
                and event.dedupe_key == dedupe_key
            ):
                return event
        return None


code_review_timeline_service = CodeReviewTimelineService()
