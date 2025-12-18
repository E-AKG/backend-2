from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Dict, Any
from datetime import datetime, date


class PropertyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Property name")
    address: str = Field(..., min_length=1, max_length=500, description="Property address")
    year_built: Optional[int] = Field(None, ge=1800, le=2100, description="Year built")
    size_sqm: Optional[int] = Field(None, gt=0, description="Size in square meters")
    units_count: Optional[int] = Field(None, ge=0, le=1000, description="Anzahl der Einheiten (für automatische Erstellung)")
    features: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional features as JSON")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    # Erweiterte Stammdaten
    unit_value_file_number: Optional[str] = Field(None, max_length=100, description="Einheitswert-Aktenzeichen")
    cadastral_district: Optional[str] = Field(None, max_length=100, description="Flur")
    cadastral_parcel: Optional[str] = Field(None, max_length=100, description="Flurstück")
    
    # Technische Daten
    heating_type: Optional[str] = Field(None, description="Heizungsart")
    energy_certificate_valid_until: Optional[str] = Field(None, description="Gültigkeit Energieausweis (YYYY-MM-DD)")
    energy_rating_value: Optional[float] = Field(None, description="Energiekennwert (kWh/m²a)")
    energy_rating_class: Optional[str] = Field(None, max_length=10, description="Energieklasse (A+, A, B, etc.)")
    total_residential_area: Optional[int] = Field(None, gt=0, description="Wohnfläche in m²")
    total_commercial_area: Optional[int] = Field(None, gt=0, description="Gewerbefläche in m²")
    
    @field_validator('year_built', 'size_sqm', mode='before')
    @classmethod
    def convert_empty_to_none(cls, v):
        """Convert empty strings to None for optional integer fields"""
        if v == "" or v is None:
            return None
        return v
    
    @field_validator('notes', mode='before')
    @classmethod
    def convert_empty_notes_to_none(cls, v):
        """Convert empty strings to None for notes"""
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v


class PropertyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    address: Optional[str] = Field(None, min_length=1, max_length=500)
    year_built: Optional[int] = Field(None, ge=1800, le=2100)
    size_sqm: Optional[int] = Field(None, gt=0)
    features: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    
    # Erweiterte Stammdaten
    unit_value_file_number: Optional[str] = Field(None, max_length=100)
    cadastral_district: Optional[str] = Field(None, max_length=100)
    cadastral_parcel: Optional[str] = Field(None, max_length=100)
    
    # Technische Daten
    heating_type: Optional[str] = None
    energy_certificate_valid_until: Optional[str] = None
    energy_rating_value: Optional[float] = None
    energy_rating_class: Optional[str] = Field(None, max_length=10)
    total_residential_area: Optional[int] = Field(None, gt=0)
    total_commercial_area: Optional[int] = Field(None, gt=0)


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
    
    # Erweiterte Stammdaten
    unit_value_file_number: Optional[str] = None
    cadastral_district: Optional[str] = None
    cadastral_parcel: Optional[str] = None
    
    # Technische Daten
    heating_type: Optional[str] = None
    energy_certificate_valid_until: Optional[date] = None
    energy_rating_value: Optional[float] = None
    energy_rating_class: Optional[str] = None
    total_residential_area: Optional[int] = None
    total_commercial_area: Optional[int] = None
    
    created_at: datetime
    updated_at: datetime

