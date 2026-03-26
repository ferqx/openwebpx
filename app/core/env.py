from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_env() -> None:
    project_root = Path(__file__).resolve().parents[2]

    # 按照优先级加载环境文件
    env_files = [".env.test.local", ".env"]
    for f in env_files:
        env_path = project_root / f
        if env_path.exists():
            # 允许后面的文件不覆盖前面的 (如果需要 override=True 请根据需求调整)
            load_dotenv(env_path, override=False)


load_project_env()
