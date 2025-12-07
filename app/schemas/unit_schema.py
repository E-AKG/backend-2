from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from ..models.unit import UnitStatus


class UnitCreate(BaseModel):
    property_id: str = Field(..., description="Property ID")
    unit_label: str = Field(..., min_length=1, max_length=100, description="Unit label (e.g., 'Apartment 1A')")
    floor: Optional[int] = Field(None, description="Floor number")
    size_sqm: Optional[int] = Field(None, gt=0, description="Size in square meters")
    status: UnitStatus = Field(default=UnitStatus.VACANT, description="Unit status")


class UnitUpdate(BaseModel):
    unit_label: Optional[str] = Field(None, min_length=1, max_length=100)
    floor: Optional[int] = None
    size_sqm: Optional[int] = Field(None, gt=0)
    status: Optional[UnitStatus] = None


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    property_id: str
    unit_label: str
    floor: Optional[int]
    size_sqm: Optional[int]
    status: UnitStatus
    created_at: datetime
    updated_at: datetime

