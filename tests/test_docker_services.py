from __future__ import annotations

from app.services.docker_bootstrap import (
    build_corepack_prepare_command,
    build_service_launch_command,
    build_tail_logs_command,
    install_command_for_manager,
    service_pid_check_command,
)
from app.services.docker_repo import (
    build_repo_binding,
    build_repo_remote_urls,
    build_repo_sync_signature,
    extract_error_message,
    normalize_repo_auth_mode,
    sanitize_repo_sync_error,
)
from app.services.docker_runtime import (
    build_diagnostic_message,
    build_preview_urls,
    build_start_command,
    collect_port_bindings_from_attrs,
    detect_framework,
    detect_package_manager_from_package_json,
    extract_error_lines,
    has_workspace_protocol,
    parse_package_json,
    resolve_package_manager_spec,
    resolve_start_script,
    strict_package_manager_reason,
)
from app.services.sandbox_bootstrap import (
    append_bootstrap_log,
    build_bootstrap_response,
    can_destroy_container_for_bootstrap_reset,
    normalize_bootstrap_state,
    normalize_bootstrap_steps,
    normalize_stream_mode,
)
from app.services.sandbox_git import (
    build_pending_git_changes_response,
    parse_git_porcelain,
    sanitize_commit_message,
    truncate_text,
)


def test_build_repo_binding_derives_git_identity_defaults() -> None:
    binding = build_repo_binding(
        thread_id="thread-1",
        user_id="user-1",
        metadata={
            "provider": "github",
            "repo": "owner/repo",
            "branch": "feat/test",
            "github_auth_mode": "github_app",
        },
        scm_user_login="alice",
        scm_user_name="",
        scm_user_email="",
    )

    assert binding is not None
    assert binding["git_name"] == "alice"
    assert binding["git_email"] == "alice@users.noreply.github.com"


def test_repo_helpers_build_urls_signature_and_sanitize_token() -> None:
    public_url, auth_url = build_repo_remote_urls(
        provider="gitlab",
        repo="group/repo",
        token="secret token",
        gitlab_base_url="https://gitlab.example.com",
    )

    assert public_url == "https://gitlab.example.com/group/repo.git"
    assert "secret%20token" in auth_url
    assert (
        build_repo_sync_signature(
            container_id="cid",
            binding={"provider": "gitlab", "repo": "group/repo", "branch": "main"},
        )
        == "cid|gitlab|group/repo|main||"
    )
    assert "***" in sanitize_repo_sync_error("token=secret token", "secret token")


def test_repo_auth_mode_and_error_message_helpers() -> None:
    gitlab_base_url, github_auth_mode = normalize_repo_auth_mode(
        {"provider": "github", "github_auth_mode": "", "gitlab_base_url": ""}
    )
    assert gitlab_base_url is None
    assert github_auth_mode is None

    class FakeExc(Exception):
        detail = "boom"

    assert extract_error_message(FakeExc()) == "boom"


def test_runtime_package_and_framework_helpers() -> None:
    package_json = {
        "packageManager": "pnpm@9.0.0",
        "scripts": {"dev": "vite"},
        "dependencies": {"vite": "^5.0.0", "foo": "workspace:*"},
    }

    assert parse_package_json('{"scripts":{"dev":"vite"}}') == {
        "scripts": {"dev": "vite"}
    }
    assert detect_package_manager_from_package_json(package_json) == "pnpm"
    assert has_workspace_protocol(package_json) is True
    assert resolve_start_script(package_json) == "dev"
    assert detect_framework(package_json) == "vite"
    assert (
        build_start_command(
            package_manager="pnpm",
            start_script="dev",
            framework="vite",
            port=3000,
        )
        == "pnpm run dev -- --host 0.0.0.0 --port 3000"
    )
    assert (
        resolve_package_manager_spec(
            package_manager="pnpm",
            package_json=package_json,
        )
        == "pnpm@9.0.0"
    )
    assert (
        strict_package_manager_reason(
            detected_manager="pnpm",
            package_json=package_json,
        )
        == "package.json#packageManager"
    )


def test_runtime_network_and_diagnostic_helpers() -> None:
    bindings = collect_port_bindings_from_attrs(
        {
            "NetworkSettings": {
                "Ports": {
                    "3000/tcp": [{"HostPort": "4010"}],
                    "9229/tcp": None,
                }
            }
        }
    )
    assert bindings == {"3000/tcp": [4010]}
    assert build_preview_urls(bindings, healthcheck_path="/") == [
        "http://127.0.0.1:4010/"
    ]

    logs = "ok\nError: failed build\nTraceback: boom\n"
    assert extract_error_lines(logs) == ["Error: failed build", "Traceback: boom"]

    diagnostic = build_diagnostic_message(
        {
            "app_detected": True,
            "framework": "vite",
            "package_manager": "pnpm",
            "start_script": "dev",
            "start_command": "pnpm run dev -- --host 0.0.0.0 --port 3000",
            "service_running": False,
            "service_pid": None,
            "startup_error": "install failed",
            "preview_probes": {"http://127.0.0.1:4010/": "error:ConnectError"},
            "error_lines": ["Error: failed build"],
            "log_tail": "",
        }
    )
    assert diagnostic is not None
    assert "startup_error" in diagnostic
    assert "preview_unreachable" in diagnostic


def test_docker_bootstrap_command_helpers() -> None:
    assert "corepack prepare pnpm@9.0.0" in build_corepack_prepare_command("pnpm@9.0.0")
    assert install_command_for_manager("yarn") == "yarn install"
    assert "agent-web.pid" in service_pid_check_command("/tmp/agent-web.pid")
    launch_cmd = build_service_launch_command(
        run_cmd="pnpm run dev -- --host 0.0.0.0 --port 3000",
        service_log_path="/tmp/agent-web.log",
        service_pid_path="/tmp/agent-web.pid",
    )
    assert "nohup pnpm run dev" in launch_cmd
    assert build_tail_logs_command("/tmp/agent-web.log", lines=50).startswith(
        "tail -n 50 "
    )


def test_sandbox_bootstrap_helpers_normalize_and_append_logs() -> None:
    state = normalize_bootstrap_state(None)
    assert state["status"] == "idle"
    assert normalize_stream_mode(None) == ["messages-tuple"]
    assert normalize_bootstrap_steps(
        [{"key": "repo", "title": "拉取代码", "status": "success"}]
    ) == [{"key": "repo", "title": "拉取代码", "status": "success"}]

    append_bootstrap_log(state, level="info", message="boot", step="repo")
    assert state["event_seq"] == 1
    assert state["logs"][-1]["step"] == "repo"
    assert can_destroy_container_for_bootstrap_reset(
        {"steps": [{"key": "repo", "status": "error"}]}
    )

    response = build_bootstrap_response(
        thread_id="thread-1",
        graph_id="build_app_agent_v3",
        state=state,
        accepted=True,
    )
    assert response["accepted"] is True


def test_sandbox_git_helpers_parse_status_and_commit_message() -> None:
    entries = parse_git_porcelain("M  a.txt\nR  old.txt -> new.txt\n?? untracked.txt\n")
    assert len(entries) == 3
    assert entries[1]["old_path"] == "old.txt"
    assert entries[2]["is_unstaged"] is True

    assert sanitize_commit_message("`feat: add thing`\n\nbody") == "feat: add thing"
    assert truncate_text("abcdef", max_chars=3) == ("abc", True)

    pending = build_pending_git_changes_response(
        thread_id="thread-1",
        graph_id="build_app_agent_v3",
        include_diff=True,
    )
    assert pending["pending_initialization"] is True
    assert pending["diff"] == ""
