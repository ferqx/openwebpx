"""Optional think tool middleware for build_app_agent_v3."""

from __future__ import annotations

from typing import Annotated, Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime


class ThinkToolMiddleware(AgentMiddleware[Any, Any, Any]):
    """Provide a constrained no-op think tool for brief summaries."""

    def __init__(
        self,
        *,
        max_summary_chars: int = 400,
        max_risk_chars: int = 200,
        max_lines: int = 3,
        custom_tool_description: str | None = None,
    ) -> None:
        if max_summary_chars <= 0:
            raise ValueError("max_summary_chars must be positive")
        if max_risk_chars <= 0:
            raise ValueError("max_risk_chars must be positive")
        if max_lines <= 0:
            raise ValueError("max_lines must be positive")
        self._max_summary_chars = max_summary_chars
        self._max_risk_chars = max_risk_chars
        self._max_lines = max_lines
        self._custom_tool_description = custom_tool_description
        self.tools = [self._create_think_tool()]

    def _create_think_tool(self) -> BaseTool:
        description = self._custom_tool_description
        if description is None:
            description = (
                "Use to record a brief 1-3 line summary or a short risk note. "
                "Do not include chain-of-thought or long explanations."
            )

        def sync_think(
            summary: Annotated[str, "Short summary (1-3 lines)."],
            runtime: ToolRuntime[None, Any],
            risk: Annotated[str | None, "Optional risk note."] = None,
        ) -> dict[str, str | bool | None]:
            _ = runtime
            return self._build_result(summary=summary, risk=risk)

        async def async_think(
            summary: Annotated[str, "Short summary (1-3 lines)."],
            runtime: ToolRuntime[None, Any],
            risk: Annotated[str | None, "Optional risk note."] = None,
        ) -> dict[str, str | bool | None]:
            _ = runtime
            return self._build_result(summary=summary, risk=risk)

        return StructuredTool.from_function(
            name="think",
            description=description,
            func=sync_think,
            coroutine=async_think,
        )

    def _build_result(
        self,
        *,
        summary: str,
        risk: str | None,
    ) -> dict[str, str | bool | None]:
        normalized_summary = self._normalize_text(
            summary, max_chars=self._max_summary_chars
        )
        normalized_risk = None
        if risk is not None:
            normalized_risk = self._normalize_text(risk, max_chars=self._max_risk_chars)
        return {
            "ok": True,
            "summary": normalized_summary,
            "risk": normalized_risk,
        }

    def _normalize_text(self, text: str, *, max_chars: int) -> str:
        lines = [" ".join(line.strip().split()) for line in text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return ""
        if len(lines) > self._max_lines:
            lines = lines[: self._max_lines]
        normalized = "\n".join(lines)
        if len(normalized) > max_chars:
            return normalized[:max_chars]
        return normalized
