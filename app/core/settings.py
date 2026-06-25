from __future__ import annotations

import os

from aegra_api.settings import settings as aegra_settings


# 代理 aegra_api 的设置，同时支持本地环境变量覆盖
# 这样即便没有 aegra_api，我们也可以通过定义本地的 Settings 类来无缝切换
class AppSettings:
    @property
    def database_url(self) -> str:
        return aegra_settings.db.database_url

    @property
    def debug(self) -> bool:
        return aegra_settings.db.DB_ECHO_LOG

    # sandbox-agent specific configuration
    @property
    def telemetry_enabled(self) -> bool:
        return os.getenv("SANDBOX_AGENT_TELEMETRY_ENABLED", "true").lower() == "true"


settings = AppSettings()
