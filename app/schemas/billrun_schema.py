from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, TYPE_CHECKING
from datetime import date, datetime
from decimal import Decimal
from ..models.billrun import BillRunStatus, ChargeStatus

if TYPE_CHECKING:
    pass


class TenantInfo(BaseModel):
    """Minimale Mieter-Informationen für Charge-Anzeige"""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    first_name: str
    last_name: str


class PropertyInfo(BaseModel):
    """Minimale Immobilien-Informationen für Charge-Anzeige"""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    name: str


class UnitInfo(BaseModel):
    """Minimale Einheiten-Informationen für Charge-Anzeige"""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    unit_label: str
    property: Optional[PropertyInfo] = None


class LeaseInfo(BaseModel):
    """Minimale Vertrags-Informationen für Charge-Anzeige"""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    tenant: Optional[TenantInfo] = None
    unit: Optional[UnitInfo] = None


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bill_run_id: str
    lease_id: str
    amount: Decimal
    due_date: date
    status: ChargeStatus
    paid_amount: Decimal
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Erweiterte Informationen für Frontend
    lease: Optional[LeaseInfo] = None


class BillRunCreate(BaseModel):
    period_month: int = Field(..., ge=1, le=12, description="Monat (1-12)")
    period_year: int = Field(..., ge=2020, le=2100, description="Jahr")
    description: Optional[str] = Field(None, max_length=500)


class BillRunUpdate(BaseModel):
    status: Optional[BillRunStatus] = None
    description: Optional[str] = Field(None, max_length=500)


class BillRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    period_month: int
    period_year: int
    status: BillRunStatus
    run_date: date
    description: Optional[str]
    total_amount: Optional[Decimal]
    paid_amount: Decimal
    created_at: datetime
    updated_at: datetime
    charges: List[ChargeOut] = []


class ChargeCreate(BaseModel):
    lease_id: str = Field(..., description="Vertrag ID")
    amount: Decimal = Field(..., gt=0, description="Sollbetrag")
    due_date: date = Field(..., description="Fälligkeitsdatum")
    description: Optional[str] = Field(None, max_length=500)


class ChargeUpdate(BaseModel):
    amount: Optional[Decimal] = Field(None, gt=0)
    due_date: Optional[date] = None
    status: Optional[ChargeStatus] = None
    description: Optional[str] = Field(None, max_length=500)


class BillRunGenerateRequest(BaseModel):
    """Request um BillRun automatisch zu generieren"""
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2020, le=2100)
    description: Optional[str] = Field(None, max_length=500)
    client_id: Optional[str] = Field(None, description="Mandant ID")
    fiscal_year_id: Optional[str] = Field(None, description="Geschäftsjahr ID")

