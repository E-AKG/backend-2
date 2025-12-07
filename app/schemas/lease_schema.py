from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from ..models.lease import LeaseStatus, LeaseComponentType


class LeaseComponentCreate(BaseModel):
    type: LeaseComponentType = Field(..., description="Component type")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Amount in EUR")
    description: Optional[str] = Field(None, max_length=255, description="Description")


class LeaseComponentUpdate(BaseModel):
    type: Optional[LeaseComponentType] = None
    amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    description: Optional[str] = Field(None, max_length=255)


class LeaseComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lease_id: str
    type: LeaseComponentType
    amount: Decimal
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class LeaseCreate(BaseModel):
    unit_id: str = Field(..., description="Unit ID")
    tenant_id: str = Field(..., description="Tenant ID")
    start_date: date = Field(..., description="Lease start date")
    end_date: Optional[date] = Field(None, description="Lease end date")
    status: LeaseStatus = Field(default=LeaseStatus.PENDING, description="Lease status")
    due_day: int = Field(..., ge=1, le=28, description="Monthly payment due day (1-28)")

    @field_validator('end_date')
    @classmethod
    def validate_end_date(cls, v, info):
        if v and 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('end_date must be after start_date')
        return v


class LeaseUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[LeaseStatus] = None
    due_day: Optional[int] = Field(None, ge=1, le=28)

    @field_validator('end_date')
    @classmethod
    def validate_end_date(cls, v, info):
        if v and 'start_date' in info.data and info.data['start_date'] and v < info.data['start_date']:
            raise ValueError('end_date must be after start_date')
        return v


class LeaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    unit_id: str
    tenant_id: str
    start_date: date
    end_date: Optional[date]
    status: LeaseStatus
    due_day: int
    created_at: datetime
    updated_at: datetime
    components: List[LeaseComponentOut] = []

