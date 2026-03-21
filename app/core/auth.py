from __future__ import annotations

import logging
from typing import Any

from aegra_api.core.auth_deps import require_auth as aegra_require_auth
from fastapi import Depends

logger = logging.getLogger(__name__)


async def get_current_user(auth_data: Any = Depends(aegra_require_auth)) -> Any:
    """
    抽象的身份验证依赖。
    目前直接代理 aegra_api 的身份验证。
    未来如果切换验证方式（如 JWT、OAuth、API Key），只需修改此处。
    """
    return auth_data


# 导出一个标准的依赖项，用于路由保护
authenticated_user = get_current_user
