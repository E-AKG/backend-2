from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from ..db import get_db
from ..models.user import User
from ..models.owner import Owner
from ..models.client import Client
from ..utils.deps import get_current_user
from pydantic import BaseModel
from decimal import Decimal

router = APIRouter()


class OwnerCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    ownership_percentage: Optional[float] = None
    iban: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None


class OwnerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    ownership_percentage: Optional[float] = None
    iban: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None


class OwnerOut(BaseModel):
    id: str
    client_id: str
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    ownership_percentage: Optional[float]
    iban: Optional[str]
    bank_name: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/api/owners", response_model=List[OwnerOut])
def list_owners(
    client_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Eigentümer"""
    query = db.query(Owner).filter(Owner.owner_id == current_user.id)
    
    if client_id:
        # Prüfe ob Client existiert und User gehört
        client = db.query(Client).filter(
            Client.id == client_id,
            Client.owner_id == current_user.id
        ).first()
        if not client:
            raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
        query = query.filter(Owner.client_id == client_id)
    
    owners = query.order_by(Owner.last_name, Owner.first_name).all()
    return owners


@router.get("/api/owners/{owner_id}", response_model=OwnerOut)
def get_owner(
    owner_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnen Eigentümer abrufen"""
    owner = db.query(Owner).filter(
        Owner.id == owner_id,
        Owner.owner_id == current_user.id
    ).first()
    
    if not owner:
        raise HTTPException(status_code=404, detail="Eigentümer nicht gefunden")
    
    return owner


@router.post("/api/owners", response_model=OwnerOut, status_code=status.HTTP_201_CREATED)
def create_owner(
    owner_data: OwnerCreate,
    client_id: str = Query(..., description="Client ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Eigentümer erstellen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    owner = Owner(
        owner_id=current_user.id,
        client_id=client_id,
        **owner_data.dict(exclude={"ownership_percentage"})
    )
    
    if owner_data.ownership_percentage is not None:
        owner.ownership_percentage = Decimal(str(owner_data.ownership_percentage))
    
    db.add(owner)
    db.commit()
    db.refresh(owner)
    
    return owner


@router.put("/api/owners/{owner_id}", response_model=OwnerOut)
def update_owner(
    owner_id: str,
    owner_data: OwnerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eigentümer aktualisieren"""
    owner = db.query(Owner).filter(
        Owner.id == owner_id,
        Owner.owner_id == current_user.id
    ).first()
    
    if not owner:
        raise HTTPException(status_code=404, detail="Eigentümer nicht gefunden")
    
    update_data = owner_data.dict(exclude_unset=True, exclude={"ownership_percentage"})
    for key, value in update_data.items():
        setattr(owner, key, value)
    
    if owner_data.ownership_percentage is not None:
        owner.ownership_percentage = Decimal(str(owner_data.ownership_percentage))
    
    db.commit()
    db.refresh(owner)
    
    return owner


@router.delete("/api/owners/{owner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_owner(
    owner_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eigentümer löschen"""
    owner = db.query(Owner).filter(
        Owner.id == owner_id,
        Owner.owner_id == current_user.id
    ).first()
    
    if not owner:
        raise HTTPException(status_code=404, detail="Eigentümer nicht gefunden")
    
    db.delete(owner)
    db.commit()
    
    return None

