from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.code_review import ReviewFixRequest


class CodeReviewFixRunnerAdapter:
    def build_runner_job_id(self, *, fix_request: ReviewFixRequest) -> str:
        return f"fix-request-{fix_request.id}"

    async def start_fix(self, *, fix_request: ReviewFixRequest) -> str:
        return self.build_runner_job_id(fix_request=fix_request)


code_review_fix_runner = CodeReviewFixRunnerAdapter()
