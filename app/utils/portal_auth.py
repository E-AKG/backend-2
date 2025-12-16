"""
Portal Authentication Utilities
Dependencies für Portal-User-Authentifizierung
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from ..db import get_db
from ..models.portal_user import PortalUser
from ..utils.jwt_handler import decode_token
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer()


def get_current_portal_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> PortalUser:
    """
    Extract and validate JWT token for PortalUser, return the current authenticated portal user.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
        portal_user_id: str = payload.get("sub") or payload.get("portal_user_id")
        
        if portal_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Prüfe ob user_type portal ist
        user_type = payload.get("user_type")
        if user_type != "portal":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Portal token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error decoding portal user token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    portal_user = db.query(PortalUser).filter(PortalUser.id == portal_user_id).first()
    
    if portal_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not portal_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email address.",
        )
    
    if not portal_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your portal account is inactive. Please contact support.",
        )
            
    return portal_user

