from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aegra_api.api.runs import create_run
from aegra_api.models import RunCreate, User

from app.services.sandbox_git import resolve_thread_graph_id

if TYPE_CHECKING:
    from aegra_api.core.orm import Thread as ThreadORM
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.code_review import ReviewFixRequest

logger = logging.getLogger(__name__)


class CodeReviewFixRunner:
    """Dispatch approved fix work onto the bound task thread."""

    async def start_fix(
        self,
        *,
        session: AsyncSession,
        fix_request: ReviewFixRequest,
        thread: ThreadORM,
        instruction: str,
    ) -> dict[str, str]:
        """Create a new run on the existing thread for the fix instruction."""
        thread_id = str(thread.thread_id or "").strip()
        if not thread_id:
            raise ValueError("thread.thread_id is required")

        graph_id = await resolve_thread_graph_id(session, thread=thread)
        user = User(identity=str(thread.user_id or "").strip() or "unknown")
        run = await create_run(
            thread_id,
            RunCreate(
                assistant_id=graph_id,
                input={
                    "messages": [
                        {
                            "type": "human",
                            "content": instruction,
                        }
                    ]
                },
                config={},
                context={},
                stream_mode=None,
                on_completion="keep",
                multitask_strategy="enqueue",
            ),
            user=user,
            session=session,
        )
        runner_job_id = str(run.run_id or "").strip()
        if not runner_job_id:
            raise RuntimeError("Aegra create_run did not return run_id")

        logger.info(
            "Accepted auto-fix request %s as run %s on thread %s",
            fix_request.id,
            runner_job_id,
            thread_id,
        )
        return {
            "runner_job_id": runner_job_id,
            "thread_id": thread_id,
            "status": "running",
            "queue_scope": "thread",
        }


code_review_fix_runner = CodeReviewFixRunner()
