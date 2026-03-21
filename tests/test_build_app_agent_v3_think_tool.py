from __future__ import annotations

from graphs.build_app_agent_v3.think_tool_middleware import ThinkToolMiddleware


def test_think_tool_truncates_lines_and_chars() -> None:
    middleware = ThinkToolMiddleware(max_summary_chars=20, max_lines=3)
    result = middleware._build_result(
        summary=" line1  \n\nline2 is here\nline3 ok\nline4 ignored",
        risk=None,
    )

    assert result["ok"] is True
    assert result["summary"] == "line1\nline2 is here\n"
    assert result["risk"] is None


def test_think_tool_truncates_risk_and_drops_empty_lines() -> None:
    middleware = ThinkToolMiddleware(max_risk_chars=8, max_lines=2)
    result = middleware._build_result(
        summary="\n\n",
        risk="  too  long  \n\nline2",
    )

    assert result["ok"] is True
    assert result["summary"] == ""
    assert result["risk"] == "too long"
