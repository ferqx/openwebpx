from aegra_api.core.auth_deps import require_auth
from fastapi import Depends, FastAPI

from app.routers.auth import router as auth_router
from app.routers.common import router as common_router
from app.routers.sandbox import router as sandbox_router
from app.routers.scm import router as scm_router

app = FastAPI()

# Public routes
app.include_router(common_router)
app.include_router(auth_router)

# Protected custom routes
app.include_router(sandbox_router, dependencies=[Depends(require_auth)])
app.include_router(scm_router, dependencies=[Depends(require_auth)])
