from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Optional
from datetime import datetime
import re


class TenantCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100, description="First name")
    last_name: str = Field(..., min_length=1, max_length=100, description="Last name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, max_length=50, description="Phone number")
    iban: Optional[str] = Field(None, max_length=34, description="IBAN")
    address: Optional[str] = Field(None, max_length=500, description="Address")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    @field_validator('iban')
    @classmethod
    def validate_iban(cls, v):
        if v is None or v == "":
            return v
        
        # Entferne Leerzeichen
        iban = v.replace(" ", "").upper()
        
        # Basis-Validierung: 2 Buchstaben + 2 Ziffern + bis zu 30 alphanumerisch
        if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$', iban):
            raise ValueError('Ungültige IBAN. Format: DE89370400440532013000')
        
        # Längenprüfung für Deutschland
        if iban.startswith('DE') and len(iban) != 22:
            raise ValueError('Deutsche IBAN muss 22 Zeichen lang sein')
        
        return iban


class TenantUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    iban: Optional[str] = Field(None, max_length=34)
    address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    
    @field_validator('iban')
    @classmethod
    def validate_iban(cls, v):
        if v is None or v == "":
            return v
        
        iban = v.replace(" ", "").upper()
        
        if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$', iban):
            raise ValueError('Ungültige IBAN')
        
        if iban.startswith('DE') and len(iban) != 22:
            raise ValueError('Deutsche IBAN muss 22 Zeichen lang sein')
        
        return iban


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    iban: Optional[str]
    address: Optional[str]
    notes: Optional[str]
    risk_score: Optional[int] = None  # 0-100
    risk_level: Optional[str] = None  # "low", "medium", "high"
    risk_updated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

