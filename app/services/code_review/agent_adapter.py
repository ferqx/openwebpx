from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from aegra_api.services.langgraph_service import (
    create_run_config,
    get_langgraph_service,
)
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CodeReviewAgentAdapter(ABC):
    @abstractmethod
    async def run_analysis(
        self,
        *,
        _session: AsyncSession,
        diff: str,
        user_id: str,
        run_id: int,
        thread_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """运行代码评审分析."""
        pass


class AegraAgentAdapter(CodeReviewAgentAdapter):
    """基于 Aegra (v3 Agent) 的评审适配器."""

    def __init__(self, graph_id: str = "build_app_agent_v3"):
        self.graph_id = graph_id

    async def run_analysis(
        self,
        *,
        _session: AsyncSession,
        diff: str,
        user_id: str,
        run_id: int,
        thread_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        langgraph_service = get_langgraph_service()

        if not thread_id:
            from uuid import uuid4

            thread_id = str(uuid4())

        # 优化 Prompt，加入自动修复引导
        prompt = f"""You are an elite software architect and security researcher. Perform an intensive code review on the following Git Diff.

Evaluation Criteria:
- Security: SQL injection, XSS, insecure dependencies, credential leaks.
- Logic & Bugs: Edge cases, race conditions, type safety.
- Performance: N+1 queries, unnecessary re-renders, expensive loops.
- Style: Consistency, readability, BEM (for CSS/SCSS).

Constraint:
- Identify if a finding can be automatically fixed by an AI coding agent.
- Especially encourage auto-fixes for styling (SCSS), consistency, and simple logic refactoring.
- Provide clear, actionable advice.

Output Format:
You MUST return a JSON array of objects. No preamble or postamble.
Each object:
{{
  "severity": "high" | "medium" | "low",
  "category": "security" | "bug" | "performance" | "maintainability",
  "file_path": "relative/path/to/file",
  "line_start": number,
  "line_end": number,
  "title": "Short descriptive title",
  "body": "Detailed explanation and implementation guidance",
  "metadata": {{
    "auto_fixable": boolean,
    "suggested_fix": "A brief technical description of how to fix it"
  }}
}}

Git Diff:
```diff
{diff}
```
"""

        class MockUser:
            def __init__(self, identity):
                self.identity = identity

            def to_dict(self):
                return {"identity": self.identity}

        user = MockUser(user_id)
        aegra_run_id = f"cr-{run_id}"
        config = create_run_config(run_id=aegra_run_id, thread_id=thread_id, user=user)

        logger.info(f"Invoking Aegra Graph {self.graph_id} for ReviewRun {run_id}")

        try:
            async with langgraph_service.get_graph(self.graph_id) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content=prompt)]}, config=config
                )

            messages = result.get("messages", [])
            if not messages:
                return [], thread_id

            content = messages[-1].content
            logger.info(f"AI Agent Raw Response:\n{content[:500]}...")

            findings = self._extract_json(content)
            return findings, thread_id

        except Exception as e:
            logger.error(f"Aegra Agent Analysis failed: {e}", exc_info=True)
            raise

    def _extract_json(self, text: str) -> list[dict[str, Any]]:
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            start = text.find("[")
            end = text.rfind("]") + 1
            if start != -1 and end != 0:
                return json.loads(text[start:end])
            return []
        except Exception as e:
            logger.warning(f"Failed to parse JSON: {e}")
            return []


code_review_agent_adapter = AegraAgentAdapter()
