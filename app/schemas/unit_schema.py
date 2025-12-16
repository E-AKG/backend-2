from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from decimal import Decimal
from ..models.unit import UnitStatus, UsageType, BathroomType


class UnitCreate(BaseModel):
    property_id: str = Field(..., description="Property ID")
    unit_label: str = Field(..., min_length=1, max_length=100, description="Unit label (e.g., 'Apartment 1A')")
    floor: Optional[int] = Field(None, description="Floor number")
    size_sqm: Optional[int] = Field(None, gt=0, description="Size in square meters (Legacy)")
    status: UnitStatus = Field(default=UnitStatus.VACANT, description="Unit status")
    
    # Basisdaten
    location: Optional[str] = Field(None, max_length=255, description="Lage (z.B. 'EG links', '1. OG')")
    unit_number: Optional[str] = Field(None, max_length=50, description="Einheitsnummer (z.B. '001')")
    
    # Flächen & Anteile
    living_area_sqm: Optional[Decimal] = Field(None, description="Wohnfläche in m² (DIN 277 oder WoFlV)")
    mea_numerator: Optional[int] = Field(None, ge=0, description="MEA Zähler (z.B. 125)")
    mea_denominator: Optional[int] = Field(None, gt=0, description="MEA Nenner (z.B. 1000)")
    
    # Nutzungsart
    usage_type: Optional[UsageType] = Field(None, description="Nutzungsart")
    
    # Ausstattung
    rooms: Optional[int] = Field(None, ge=0, description="Anzahl Zimmer")
    bathroom_type: Optional[BathroomType] = Field(None, description="Bad (Wanne/Dusche)")
    has_balcony: Optional[bool] = Field(False, description="Balkon vorhanden")
    floor_covering: Optional[str] = Field(None, max_length=100, description="Bodenbelag (z.B. 'Parkett', 'Laminat', 'Fliesen')")


class UnitUpdate(BaseModel):
    unit_label: Optional[str] = Field(None, min_length=1, max_length=100)
    floor: Optional[int] = None
    size_sqm: Optional[int] = Field(None, gt=0)
    status: Optional[UnitStatus] = None
    
    # Basisdaten
    location: Optional[str] = Field(None, max_length=255)
    unit_number: Optional[str] = Field(None, max_length=50)
    
    # Flächen & Anteile
    living_area_sqm: Optional[Decimal] = None
    mea_numerator: Optional[int] = Field(None, ge=0)
    mea_denominator: Optional[int] = Field(None, gt=0)
    
    # Nutzungsart
    usage_type: Optional[UsageType] = None
    
    # Ausstattung
    rooms: Optional[int] = Field(None, ge=0)
    bathroom_type: Optional[BathroomType] = None
    has_balcony: Optional[bool] = None
    floor_covering: Optional[str] = Field(None, max_length=100)


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    property_id: str
    unit_label: str
    floor: Optional[int]
    size_sqm: Optional[int]
    status: UnitStatus
    
    # Basisdaten
    location: Optional[str]
    unit_number: Optional[str]
    
    # Flächen & Anteile
    living_area_sqm: Optional[Decimal]
    mea_numerator: Optional[int]
    mea_denominator: Optional[int]
    
    # Nutzungsart
    usage_type: Optional[UsageType]
    
    # Ausstattung
    rooms: Optional[int]
    bathroom_type: Optional[BathroomType]
    has_balcony: bool
    floor_covering: Optional[str]
    
    created_at: datetime
    updated_at: datetime

