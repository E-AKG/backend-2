from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from ..db import get_db
from ..models.user import User
from ..models.key import Key, KeyHistory, KeyType, KeyStatus
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/keys", tags=["Keys"])


class KeyCreate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    key_type: KeyType
    key_number: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class KeyUpdate(BaseModel):
    key_type: Optional[KeyType] = None
    key_number: Optional[str] = None
    description: Optional[str] = None
    status: Optional[KeyStatus] = None
    assigned_to_type: Optional[str] = None
    assigned_to_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    notes: Optional[str] = None


class KeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    property_id: Optional[str]
    unit_id: Optional[str]
    key_type: str
    key_number: Optional[str]
    description: Optional[str]
    status: str
    assigned_to_type: Optional[str]
    assigned_to_id: Optional[str]
    assigned_to_name: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class KeyHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    key_id: str
    action: str
    action_date: date
    assigned_to_type: Optional[str]
    assigned_to_id: Optional[str]
    assigned_to_name: Optional[str]
    notes: Optional[str]
    created_at: datetime


class KeyActionRequest(BaseModel):
    action: str  # "out", "return", "lost", "replaced"
    assigned_to_type: Optional[str] = None
    assigned_to_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    notes: Optional[str] = None


@router.get("", response_model=List[KeyResponse])
def list_keys(
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[KeyStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Schlüssel"""
    query = db.query(Key).filter(Key.owner_id == current_user.id)
    
    if property_id:
        query = query.filter(Key.property_id == property_id)
    if unit_id:
        query = query.filter(Key.unit_id == unit_id)
    if client_id:
        query = query.filter(Key.client_id == client_id)
    if status:
        query = query.filter(Key.status == status)
    
    keys = query.order_by(Key.key_type, Key.key_number).all()
    return [KeyResponse.model_validate(k) for k in keys]


@router.get("/{key_id}", response_model=KeyResponse)
def get_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnen Schlüssel abrufen"""
    key = db.query(Key).filter(
        Key.id == key_id,
        Key.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Schlüssel nicht gefunden")
    
    return KeyResponse.model_validate(key)


@router.post("", response_model=KeyResponse, status_code=201)
def create_key(
    key_data: KeyCreate,
    client_id: str = Query(..., description="Mandant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Schlüssel erstellen"""
    from ..models.property import Property
    from ..models.unit import Unit
    
    # Prüfe Property/Unit gehören zum User
    if key_data.property_id:
        property_obj = db.query(Property).filter(
            Property.id == key_data.property_id,
            Property.owner_id == current_user.id
        ).first()
        if not property_obj:
            raise HTTPException(status_code=404, detail="Objekt nicht gefunden")
    
    if key_data.unit_id:
        unit_obj = db.query(Unit).filter(
            Unit.id == key_data.unit_id,
            Unit.owner_id == current_user.id
        ).first()
        if not unit_obj:
            raise HTTPException(status_code=404, detail="Einheit nicht gefunden")
    
    key = Key(
        owner_id=current_user.id,
        client_id=client_id,
        **key_data.dict()
    )
    
    db.add(key)
    db.commit()
    db.refresh(key)
    
    return KeyResponse.model_validate(key)


@router.put("/{key_id}", response_model=KeyResponse)
def update_key(
    key_id: str,
    key_data: KeyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Schlüssel aktualisieren"""
    key = db.query(Key).filter(
        Key.id == key_id,
        Key.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Schlüssel nicht gefunden")
    
    update_data = key_data.dict(exclude_unset=True)
    for key_attr, value in update_data.items():
        setattr(key, key_attr, value)
    
    db.commit()
    db.refresh(key)
    
    return KeyResponse.model_validate(key)


@router.post("/{key_id}/action", response_model=KeyResponse)
def key_action(
    key_id: str,
    action_data: KeyActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Schlüssel-Aktion (Ausgabe, Rückgabe, etc.)"""
    key = db.query(Key).filter(
        Key.id == key_id,
        Key.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Schlüssel nicht gefunden")
    
    # Update Key Status
    if action_data.action == "out":
        key.status = KeyStatus.OUT
        key.assigned_to_type = action_data.assigned_to_type
        key.assigned_to_id = action_data.assigned_to_id
        key.assigned_to_name = action_data.assigned_to_name
    elif action_data.action == "return":
        key.status = KeyStatus.AVAILABLE
        key.assigned_to_type = None
        key.assigned_to_id = None
        key.assigned_to_name = None
    elif action_data.action == "lost":
        key.status = KeyStatus.LOST
    elif action_data.action == "replaced":
        key.status = KeyStatus.REPLACED
    
    # Erstelle Historie-Eintrag
    history = KeyHistory(
        key_id=key_id,
        owner_id=current_user.id,
        action=action_data.action,
        action_date=date.today(),
        assigned_to_type=action_data.assigned_to_type,
        assigned_to_id=action_data.assigned_to_id,
        assigned_to_name=action_data.assigned_to_name,
        notes=action_data.notes
    )
    
    db.add(history)
    db.commit()
    db.refresh(key)
    
    return KeyResponse.model_validate(key)


@router.get("/{key_id}/history", response_model=List[KeyHistoryResponse])
def get_key_history(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Historie eines Schlüssels"""
    key = db.query(Key).filter(
        Key.id == key_id,
        Key.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Schlüssel nicht gefunden")
    
    history = db.query(KeyHistory).filter(
        KeyHistory.key_id == key_id
    ).order_by(KeyHistory.action_date.desc(), KeyHistory.created_at.desc()).all()
    
    return [KeyHistoryResponse.model_validate(h) for h in history]


@router.delete("/{key_id}", status_code=204)
def delete_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Schlüssel löschen"""
    key = db.query(Key).filter(
        Key.id == key_id,
        Key.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Schlüssel nicht gefunden")
    
    db.delete(key)
    db.commit()
    
    return None

