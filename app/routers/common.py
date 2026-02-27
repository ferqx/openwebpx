from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "Hello from custom route!"}


@router.post("/webhook")
async def webhook(data: dict[str, Any]) -> dict[str, Any]:
    return {"received": data, "status": "processed"}


@router.get("/")
async def custom_root() -> dict[str, Any]:
    return {"message": "Custom Aegra Server", "custom": True}
