from __future__ import annotations

from graphs.build_app_agent_v3.prompts import build_system_prompt


def test_build_system_prompt_encourages_parallel_read_only_tool_calls() -> None:
    prompt = build_system_prompt()

    assert "同一轮" in prompt
    assert "多个彼此独立的只读检查" in prompt
    assert "只有当下一个工具调用**依赖**上一个结果时，才改为串行" in prompt


def test_build_system_prompt_prioritizes_environment_checks() -> None:
    prompt = build_system_prompt()

    assert "先确认环境与前提" in prompt
    assert "如果 `/workspace` 为空" in prompt
    assert "先明确诊断这些前提问题" in prompt


def test_build_system_prompt_requires_serial_writes_and_patch_recovery() -> None:
    prompt = build_system_prompt()

    assert "所有写操作" in prompt
    assert "都必须串行执行" in prompt
    assert "所有项目文件写入都必须通过 `apply_patch` 完成" in prompt
    assert "重新读取文件后用更小、更精确的 patch 重试" in prompt
