import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from ..config import settings


def create_token(data: dict, expires_delta: timedelta = None):
    """
    Create a JWT token with the given data.
    
    Args:
        data: Dictionary containing the data to encode
        expires_delta: Optional timedelta for token expiration
    
    Returns:
        Encoded JWT token as string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS)
    
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str):
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please request a new verification email."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token. Please check your verification link."
        )