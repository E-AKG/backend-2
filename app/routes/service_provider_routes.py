from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from ..db import get_db
from ..models.user import User
from ..models.service_provider import ServiceProvider, ServiceProviderType
from ..models.client import Client
from ..utils.deps import get_current_user
from pydantic import BaseModel

router = APIRouter()


class ServiceProviderCreate(BaseModel):
    company_name: Optional[str] = None
    first_name: str
    last_name: str
    service_type: ServiceProviderType
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    iban: Optional[str] = None
    bank_name: Optional[str] = None
    rating: Optional[int] = None
    notes: Optional[str] = None


class ServiceProviderUpdate(BaseModel):
    company_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    service_type: Optional[ServiceProviderType] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    iban: Optional[str] = None
    bank_name: Optional[str] = None
    rating: Optional[int] = None
    notes: Optional[str] = None


class ServiceProviderOut(BaseModel):
    id: str
    client_id: str
    company_name: Optional[str]
    first_name: str
    last_name: str
    service_type: str
    email: Optional[str]
    phone: Optional[str]
    mobile: Optional[str]
    address: Optional[str]
    tax_id: Optional[str]
    iban: Optional[str]
    bank_name: Optional[str]
    rating: Optional[int]
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/api/service-providers", response_model=List[ServiceProviderOut])
def list_service_providers(
    client_id: Optional[str] = Query(None),
    service_type: Optional[ServiceProviderType] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Dienstleister"""
    query = db.query(ServiceProvider).filter(ServiceProvider.owner_id == current_user.id)
    
    if client_id:
        # Prüfe ob Client existiert und User gehört
        client = db.query(Client).filter(
            Client.id == client_id,
            Client.owner_id == current_user.id
        ).first()
        if not client:
            raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
        query = query.filter(ServiceProvider.client_id == client_id)
    
    if service_type:
        query = query.filter(ServiceProvider.service_type == service_type)
    
    providers = query.order_by(ServiceProvider.last_name, ServiceProvider.first_name).all()
    return providers


@router.get("/api/service-providers/{provider_id}", response_model=ServiceProviderOut)
def get_service_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnen Dienstleister abrufen"""
    provider = db.query(ServiceProvider).filter(
        ServiceProvider.id == provider_id,
        ServiceProvider.owner_id == current_user.id
    ).first()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Dienstleister nicht gefunden")
    
    return provider


@router.post("/api/service-providers", response_model=ServiceProviderOut, status_code=status.HTTP_201_CREATED)
def create_service_provider(
    provider_data: ServiceProviderCreate,
    client_id: str = Query(..., description="Client ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Dienstleister erstellen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    provider = ServiceProvider(
        owner_id=current_user.id,
        client_id=client_id,
        **provider_data.dict()
    )
    
    db.add(provider)
    db.commit()
    db.refresh(provider)
    
    return provider


@router.put("/api/service-providers/{provider_id}", response_model=ServiceProviderOut)
def update_service_provider(
    provider_id: str,
    provider_data: ServiceProviderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dienstleister aktualisieren"""
    provider = db.query(ServiceProvider).filter(
        ServiceProvider.id == provider_id,
        ServiceProvider.owner_id == current_user.id
    ).first()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Dienstleister nicht gefunden")
    
    update_data = provider_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(provider, key, value)
    
    db.commit()
    db.refresh(provider)
    
    return provider


@router.delete("/api/service-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dienstleister löschen"""
    provider = db.query(ServiceProvider).filter(
        ServiceProvider.id == provider_id,
        ServiceProvider.owner_id == current_user.id
    ).first()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Dienstleister nicht gefunden")
    
    db.delete(provider)
    db.commit()
    
    return None

