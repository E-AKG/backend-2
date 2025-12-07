from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime


class PropertyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Property name")
    address: str = Field(..., min_length=1, max_length=500, description="Property address")
    year_built: Optional[int] = Field(None, ge=1800, le=2100, description="Year built")
    size_sqm: Optional[int] = Field(None, gt=0, description="Size in square meters")
    features: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional features as JSON")
    notes: Optional[str] = Field(None, description="Additional notes")


class PropertyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    address: Optional[str] = Field(None, min_length=1, max_length=500)
    year_built: Optional[int] = Field(None, ge=1800, le=2100)
    size_sqm: Optional[int] = Field(None, gt=0)
    features: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    name: str
    address: str
    year_built: Optional[int]
    size_sqm: Optional[int]
    features: Dict[str, Any]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

