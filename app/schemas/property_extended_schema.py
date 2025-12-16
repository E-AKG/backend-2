from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from decimal import Decimal
from ..models.property_insurance import InsuranceType
from ..models.property_bank_account import PropertyAccountType
from ..models.allocation_key import AllocationMethod


# ========== Property Extended Schema ==========
class PropertyExtendedUpdate(BaseModel):
    """Erweiterte Property-Felder"""
    # Stammdaten
    unit_value_file_number: Optional[str] = Field(None, max_length=100, description="Einheitswert-Aktenzeichen")
    cadastral_district: Optional[str] = Field(None, max_length=100, description="Flur")
    cadastral_parcel: Optional[str] = Field(None, max_length=100, description="Flurstück")
    
    # Technische Daten
    heating_type: Optional[str] = Field(None, description="Heizungsart")
    energy_certificate_valid_until: Optional[date] = Field(None, description="Gültigkeit Energieausweis")
    energy_rating_value: Optional[Decimal] = Field(None, description="Energiekennwert (kWh/m²a)")
    energy_rating_class: Optional[str] = Field(None, max_length=10, description="Energieklasse (A+, A, B, etc.)")
    total_residential_area: Optional[int] = Field(None, gt=0, description="Wohnfläche in m²")
    total_commercial_area: Optional[int] = Field(None, gt=0, description="Gewerbefläche in m²")


# ========== Insurance Schemas ==========
def empty_str_to_none(v):
    """Convert empty strings to None"""
    if v == "" or v is None:
        return None
    return v


class PropertyInsuranceCreate(BaseModel):
    insurance_type: InsuranceType = Field(..., description="Versicherungstyp")
    insurer_name: str = Field(..., min_length=1, max_length=255, description="Versicherer")
    policy_number: Optional[str] = Field(None, max_length=100, description="Police-Nr.")
    coverage_description: Optional[str] = Field(None, description="Was ist abgedeckt?")
    start_date: Optional[date] = Field(None, description="Startdatum")
    end_date: Optional[date] = Field(None, description="Enddatum")
    annual_premium: Optional[str] = Field(None, max_length=50, description="Jahresprämie")
    notes: Optional[str] = Field(None, description="Notizen")
    
    @field_validator('policy_number', 'coverage_description', 'annual_premium', 'notes', mode='before')
    @classmethod
    def convert_empty_to_none(cls, v):
        return empty_str_to_none(v)


class PropertyInsuranceUpdate(BaseModel):
    insurance_type: Optional[InsuranceType] = None
    insurer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    policy_number: Optional[str] = Field(None, max_length=100)
    coverage_description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    annual_premium: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class PropertyInsuranceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    property_id: str
    owner_id: int
    insurance_type: InsuranceType
    insurer_name: str
    policy_number: Optional[str]
    coverage_description: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    annual_premium: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ========== Property Bank Account Schemas ==========
class PropertyBankAccountCreate(BaseModel):
    account_type: PropertyAccountType = Field(..., description="Kontotyp")
    account_name: str = Field(..., min_length=1, max_length=255, description="Name des Kontos")
    iban: Optional[str] = Field(None, max_length=34, description="IBAN")
    bank_name: Optional[str] = Field(None, max_length=255, description="Bankname")
    account_holder: Optional[str] = Field(None, max_length=255, description="Kontoinhaber")
    notes: Optional[str] = Field(None, description="Notizen")


class PropertyBankAccountUpdate(BaseModel):
    account_type: Optional[PropertyAccountType] = None
    account_name: Optional[str] = Field(None, min_length=1, max_length=255)
    iban: Optional[str] = Field(None, max_length=34)
    bank_name: Optional[str] = Field(None, max_length=255)
    account_holder: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class PropertyBankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    property_id: str
    owner_id: int
    account_type: PropertyAccountType
    account_name: str
    iban: Optional[str]
    bank_name: Optional[str]
    account_holder: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ========== Allocation Key Schemas ==========
class AllocationKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Name des Verteilerschlüssels")
    allocation_method: AllocationMethod = Field(..., description="Verteilungsmethode")
    custom_factors: Optional[Dict[str, float]] = Field(None, description="Individuelle Faktoren pro Einheit (für CUSTOM)")
    default_factor: Optional[Decimal] = Field(None, description="Standard-Faktor")
    is_active: bool = Field(True, description="Ist dieser Schlüssel aktiv?")
    notes: Optional[str] = Field(None, description="Notizen")


class AllocationKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    allocation_method: Optional[AllocationMethod] = None
    custom_factors: Optional[Dict[str, float]] = None
    default_factor: Optional[Decimal] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class AllocationKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    property_id: str
    owner_id: int
    name: str
    allocation_method: AllocationMethod
    custom_factors: Optional[Dict[str, float]]
    default_factor: Optional[Decimal]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

