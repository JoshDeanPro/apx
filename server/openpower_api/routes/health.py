from fastapi import APIRouter

from ..schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness probe for Caddy. No auth, no DB dependency — must stay cheap."""
    return HealthOut(status="ok")
