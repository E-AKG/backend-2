from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from ..db import get_db
from ..models.user import User
from ..models.meter import Meter, MeterReading, MeterType
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/meters", tags=["Meters"])


class MeterCreate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    meter_type: MeterType
    meter_number: str
    location: Optional[str] = None
    calibration_date: Optional[date] = None
    calibration_due_date: Optional[date] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    notes: Optional[str] = None


class MeterUpdate(BaseModel):
    meter_type: Optional[MeterType] = None
    meter_number: Optional[str] = None
    location: Optional[str] = None
    calibration_date: Optional[date] = None
    calibration_due_date: Optional[date] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    notes: Optional[str] = None


class MeterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    property_id: Optional[str]
    unit_id: Optional[str]
    meter_type: str
    meter_number: str
    location: Optional[str]
    calibration_date: Optional[date]
    calibration_due_date: Optional[date]
    manufacturer: Optional[str]
    model: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class MeterReadingCreate(BaseModel):
    reading_value: int
    reading_date: date
    reading_type: Optional[str] = "manual"
    reader_name: Optional[str] = None
    billrun_id: Optional[str] = None


class MeterReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    meter_id: str
    reading_value: int
    reading_date: date
    reading_type: Optional[str]
    reader_name: Optional[str]
    billrun_id: Optional[str]
    created_at: datetime


@router.get("", response_model=List[MeterResponse])
def list_meters(
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Zähler"""
    query = db.query(Meter).filter(Meter.owner_id == current_user.id)
    
    if property_id:
        query = query.filter(Meter.property_id == property_id)
    if unit_id:
        query = query.filter(Meter.unit_id == unit_id)
    if client_id:
        query = query.filter(Meter.client_id == client_id)
    
    meters = query.order_by(Meter.meter_type, Meter.meter_number).all()
    return [MeterResponse.model_validate(m) for m in meters]


@router.get("/{meter_id}", response_model=MeterResponse)
def get_meter(
    meter_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnen Zähler abrufen"""
    meter = db.query(Meter).filter(
        Meter.id == meter_id,
        Meter.owner_id == current_user.id
    ).first()
    
    if not meter:
        raise HTTPException(status_code=404, detail="Zähler nicht gefunden")
    
    return MeterResponse.model_validate(meter)


@router.post("", response_model=MeterResponse, status_code=201)
def create_meter(
    meter_data: MeterCreate,
    client_id: str = Query(..., description="Mandant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Zähler erstellen"""
    from ..models.property import Property
    from ..models.unit import Unit
    
    # Prüfe Property/Unit gehören zum User
    if meter_data.property_id:
        property_obj = db.query(Property).filter(
            Property.id == meter_data.property_id,
            Property.owner_id == current_user.id
        ).first()
        if not property_obj:
            raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    
    if meter_data.unit_id:
        unit_obj = db.query(Unit).filter(
            Unit.id == meter_data.unit_id,
            Unit.owner_id == current_user.id
        ).first()
        if not unit_obj:
            raise HTTPException(status_code=404, detail="Einheit nicht gefunden")
    
    meter = Meter(
        owner_id=current_user.id,
        client_id=client_id,
        **meter_data.dict()
    )
    
    db.add(meter)
    db.commit()
    db.refresh(meter)
    
    return MeterResponse.model_validate(meter)


@router.put("/{meter_id}", response_model=MeterResponse)
def update_meter(
    meter_id: str,
    meter_data: MeterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Zähler aktualisieren"""
    meter = db.query(Meter).filter(
        Meter.id == meter_id,
        Meter.owner_id == current_user.id
    ).first()
    
    if not meter:
        raise HTTPException(status_code=404, detail="Zähler nicht gefunden")
    
    update_data = meter_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(meter, key, value)
    
    db.commit()
    db.refresh(meter)
    
    return MeterResponse.model_validate(meter)


@router.delete("/{meter_id}", status_code=204)
def delete_meter(
    meter_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Zähler löschen"""
    meter = db.query(Meter).filter(
        Meter.id == meter_id,
        Meter.owner_id == current_user.id
    ).first()
    
    if not meter:
        raise HTTPException(status_code=404, detail="Zähler nicht gefunden")
    
    db.delete(meter)
    db.commit()
    
    return None


@router.get("/{meter_id}/readings", response_model=List[MeterReadingResponse])
def list_meter_readings(
    meter_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Zählerstände eines Zählers"""
    meter = db.query(Meter).filter(
        Meter.id == meter_id,
        Meter.owner_id == current_user.id
    ).first()
    
    if not meter:
        raise HTTPException(status_code=404, detail="Zähler nicht gefunden")
    
    readings = db.query(MeterReading).filter(
        MeterReading.meter_id == meter_id
    ).order_by(MeterReading.reading_date.desc()).all()
    
    return [MeterReadingResponse.model_validate(r) for r in readings]


@router.post("/{meter_id}/readings", response_model=MeterReadingResponse, status_code=201)
def create_meter_reading(
    meter_id: str,
    reading_data: MeterReadingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Zählerstand erfassen"""
    meter = db.query(Meter).filter(
        Meter.id == meter_id,
        Meter.owner_id == current_user.id
    ).first()
    
    if not meter:
        raise HTTPException(status_code=404, detail="Zähler nicht gefunden")
    
    reading = MeterReading(
        meter_id=meter_id,
        owner_id=current_user.id,
        **reading_data.dict()
    )
    
    db.add(reading)
    db.commit()
    db.refresh(reading)
    
    return MeterReadingResponse.model_validate(reading)

