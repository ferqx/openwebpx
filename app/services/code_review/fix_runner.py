from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from aegra_api.services.langgraph_service import (
    create_run_config,
    get_langgraph_service,
)
from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.code_review import ReviewFixRequest

logger = logging.getLogger(__name__)


class CodeReviewFixRunner:
    """负责协调 Agent 执行代码修复并提交到 SCM."""

    def __init__(self, graph_id: str = "build_app_agent_v3"):
        self.graph_id = graph_id

    async def start_fix(
        self, *, _session: AsyncSession, fix_request: ReviewFixRequest
    ) -> str:
        """启动修复流程."""
        finding = fix_request.review_finding
        run = fix_request.review_run
        integration = run.repository_integration

        # 1. 获取 Git 信息和令牌
        token = os.getenv("TEST_GITLAB_TOKEN")
        if not token:
            raise ValueError("No SCM token available for fix runner")

        repo_url = integration.gitlab_base_url or "https://gitlab.com"
        full_name = integration.full_name
        source_branch = run.head_branch

        # 构造带 Token 的克隆地址 (处理 gitlab.com 或私有部署)
        # 格式: https://oauth2:TOKEN@gitlab.com/group/repo.git
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(repo_url)
        auth_netloc = f"oauth2:{token}@{parts.netloc}"
        auth_url = urlunsplit((parts.scheme, auth_netloc, f"/{full_name}.git", "", ""))

        # 2. 构造指令
        prompt = f"""You are an automated code repair agent. Your task is to FIX a specific issue and PUSH the fix back to the repository.

CONTEXT:
- Repository: {full_name}
- Branch: {source_branch}
- File: {finding.file_path}
- Issue: {finding.title}
- Suggested Fix: {finding.metadata_.get("suggested_fix", "Not provided")}

CRITICAL INSTRUCTIONS:
1. CLONE the repository using this authenticated URL: `{auth_url}`
2. CHECKOUT the branch `{source_branch}`.
3. FIX the issue in `{finding.file_path}`.
4. CONFIGURE git user: `git config --global user.email "ai-fixer@openwebpx.io" && git config --global user.name "AI Fixer"`
5. COMMIT with message: "[AI Fix] {finding.title}"
6. PUSH to origin `{source_branch}`.

You MUST use your provided shell/git tools. Do NOT just talk, PERFORM the actions.
"""

        # 3. 启动 Aegra Run
        langgraph_service = get_langgraph_service()
        # 复用评审的 Thread ID 保持对话连续性
        thread_id = run.thread_id or f"fix-{fix_request.id}"

        class MockUser:
            def __init__(self, identity):
                self.identity = identity

            def to_dict(self):
                return {"identity": self.identity}

        user = MockUser("fix-runner-service")
        aegra_run_id = f"fix-{fix_request.id}"

        # 注入环境变量，确保 Agent 有权限 Push (GitLab Token)
        token = os.getenv("TEST_GITLAB_TOKEN")
        # 注意：在真实沙盒中，我们需要将 token 注入到 Git Config 或 URL 中
        # 这里简化处理，假设 Agent 已经配置好或能通过环境变量使用 token

        config = create_run_config(run_id=aegra_run_id, thread_id=thread_id, user=user)

        logger.info(
            f"Starting Auto-Fix Run {aegra_run_id} for finding in {finding.file_path}"
        )

        try:
            async with langgraph_service.get_graph(self.graph_id) as graph:
                # 触发修复任务
                # 我们这里不阻塞等待结果，因为修复可能很慢
                # 实际生产环境应由回调处理
                await graph.ainvoke(
                    {"messages": [HumanMessage(content=prompt)]}, config=config
                )

            return aegra_run_id

        except Exception as e:
            logger.error(f"Failed to start auto-fix: {e}")
            raise


code_review_fix_runner = CodeReviewFixRunner()
