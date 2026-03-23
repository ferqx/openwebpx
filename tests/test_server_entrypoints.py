from __future__ import annotations

from pathlib import Path


def test_project_server_entrypoints_target_app_main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    files = {
        "run_server.py": project_root / "run_server.py",
        "docker-compose.yml": project_root / "docker-compose.yml",
        "docker-compose.prod.yml": project_root / "docker-compose.prod.yml",
    }

    for label, path in files.items():
        content = path.read_text(encoding="utf-8")
        assert "app.main:app" in content, label
        assert "aegra_api.main:app" not in content, label
