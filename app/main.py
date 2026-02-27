from fastapi import FastAPI

from app.routers.common import router as common_router
from app.routers.sandbox import router as sandbox_router
from app.routers.scm import router as scm_router

app = FastAPI()

app.include_router(common_router)
app.include_router(sandbox_router)
app.include_router(scm_router)
