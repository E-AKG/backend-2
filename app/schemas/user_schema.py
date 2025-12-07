from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime


class UserCreate(BaseModel):
    """Schema for user registration"""
    email: EmailStr
    # Remove max_length from Field - we check bytes in validator, not characters
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long, max 72 bytes")
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        # Bcrypt has a maximum of 72 bytes. We check bytes, not characters, to handle Unicode correctly
        password_bytes = len(v.encode('utf-8'))
        if password_bytes > 72:
            raise ValueError(f'Password cannot be longer than 72 bytes (current: {password_bytes} bytes). Please use a shorter password.')
        if not any(char.isdigit() for char in v):
            raise ValueError('Password must contain at least one digit')
        if not any(char.isalpha() for char in v):
            raise ValueError('Password must contain at least one letter')
        return v


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Schema for user output"""
    id: int
    email: EmailStr
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2 replacement for orm_mode


class TokenResponse(BaseModel):
    """Schema for token response"""
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    """Schema for generic message response"""
    message: str