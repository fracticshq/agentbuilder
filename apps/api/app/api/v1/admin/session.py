from fastapi import APIRouter, Depends

from app.auth.admin_key import require_admin_key

router = APIRouter()


@router.get("/validate", dependencies=[Depends(require_admin_key)])
async def validate_admin_session():
    """Validate the current X-Admin-Key header."""
    return {"authorized": True}
