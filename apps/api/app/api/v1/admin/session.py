from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_active_user

router = APIRouter()


@router.get("/validate")
async def validate_admin_session(user=Depends(get_current_active_user)):
    """Validate the current authenticated dashboard session."""
    return {"authorized": True, "email": user.email, "role": user.role}
