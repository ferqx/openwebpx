from __future__ import annotations

from graphs.build_app_agent_v3.system_info_middleware import (
    _parse_system_info_output,
    build_system_info_prompt,
)


def test_build_system_info_prompt_renders_fields() -> None:
    info = {
        "time": "2026-03-16T09:05:07+08:00",
        "timezone": "CST",
        "os": "Debian GNU/Linux 12 (bookworm)",
        "system": "Linux",
        "release": "6.10.9",
        "version": "#1 SMP",
        "machine": "arm64",
        "python": "Python 3.12.4",
        "node": "v20.15.0",
        "cwd": "/workspace",
    }

    prompt = build_system_info_prompt(info)

    assert "Time: 2026-03-16T09:05:07+08:00" in prompt
    assert "Timezone: CST" in prompt
    assert "OS: Debian GNU/Linux 12 (bookworm)" in prompt
    assert "Kernel: Linux 6.10.9 (#1 SMP)" in prompt
    assert "Machine: arm64" in prompt
    assert "Python: Python 3.12.4" in prompt
    assert "Node: v20.15.0" in prompt
    assert "CWD: /workspace" in prompt


def test_parse_system_info_output_extracts_values() -> None:
    raw = "\n".join(
        [
            "TIME=2026-03-16T09:05:07+08:00",
            "TZ=CST",
            "OS=Debian GNU/Linux 12 (bookworm)",
            "SYS=Linux",
            "REL=6.10.9",
            "VER=#1 SMP",
            "MACH=arm64",
            "PY=Python 3.12.4",
            "NODE=v20.15.0",
            "CWD=/workspace",
        ]
    )

    info = _parse_system_info_output(raw)

    assert info["time"] == "2026-03-16T09:05:07+08:00"
    assert info["timezone"] == "CST"
    assert info["os"] == "Debian GNU/Linux 12 (bookworm)"
    assert info["system"] == "Linux"
    assert info["release"] == "6.10.9"
    assert info["version"] == "#1 SMP"
    assert info["machine"] == "arm64"
    assert info["python"] == "Python 3.12.4"
    assert info["node"] == "v20.15.0"
    assert info["cwd"] == "/workspace"
