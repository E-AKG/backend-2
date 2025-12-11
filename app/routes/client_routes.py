from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from ..db import get_db
from ..models.client import Client, ClientType
from ..models.fiscal_year import FiscalYear
from ..utils.deps import get_current_user
from ..models.user import User
from pydantic import BaseModel
from datetime import date

router = APIRouter()


# ========= Schemas =========

class ClientCreate(BaseModel):
    name: str
    client_type: ClientType = ClientType.PRIVATE_LANDLORD
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    client_type: Optional[ClientType] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ClientResponse(BaseModel):
    id: str
    name: str
    client_type: str
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class FiscalYearCreate(BaseModel):
    year: int
    start_date: date
    end_date: date
    is_active: bool = False


class FiscalYearUpdate(BaseModel):
    year: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    is_closed: Optional[bool] = None


class FiscalYearResponse(BaseModel):
    id: str
    client_id: str
    year: int
    start_date: date
    end_date: date
    is_active: bool
    is_closed: bool
    opening_balance: Optional[float]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ========= Client Routes =========

@router.get("/api/clients", response_model=List[ClientResponse])
def list_clients(
    active_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Mandanten des aktuellen Users"""
    query = db.query(Client).filter(Client.owner_id == current_user.id)
    
    if active_only:
        query = query.filter(Client.is_active == True)
    
    clients = query.order_by(Client.name).all()
    return clients


@router.get("/api/clients/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnen Mandanten abrufen"""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    return client


@router.post("/api/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    client_data: ClientCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Mandanten erstellen"""
    client = Client(
        owner_id=current_user.id,
        **client_data.dict()
    )
    
    db.add(client)
    db.commit()
    db.refresh(client)
    
    # Erstelle automatisch ein Geschäftsjahr für das aktuelle Jahr
    current_year = date.today().year
    fiscal_year = FiscalYear(
        client_id=client.id,
        year=current_year,
        start_date=date(current_year, 1, 1),
        end_date=date(current_year, 12, 31),
        is_active=True
    )
    db.add(fiscal_year)
    db.commit()
    
    return client


@router.put("/api/clients/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: str,
    client_data: ClientUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mandanten aktualisieren"""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    update_data = client_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(client, key, value)
    
    db.commit()
    db.refresh(client)
    
    return client


@router.delete("/api/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mandanten löschen"""
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    db.delete(client)
    db.commit()
    
    return None


# ========= Fiscal Year Routes =========

@router.get("/api/clients/{client_id}/fiscal-years", response_model=List[FiscalYearResponse])
def list_fiscal_years(
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Geschäftsjahre eines Mandanten"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    fiscal_years = db.query(FiscalYear).filter(
        FiscalYear.client_id == client_id
    ).order_by(FiscalYear.year.desc()).all()
    
    return fiscal_years


@router.post("/api/clients/{client_id}/fiscal-years", response_model=FiscalYearResponse, status_code=status.HTTP_201_CREATED)
def create_fiscal_year(
    client_id: str,
    fiscal_year_data: FiscalYearCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neues Geschäftsjahr erstellen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    # Wenn is_active=True, setze alle anderen auf False
    if fiscal_year_data.is_active:
        db.query(FiscalYear).filter(
            FiscalYear.client_id == client_id,
            FiscalYear.is_active == True
        ).update({"is_active": False})
    
    fiscal_year = FiscalYear(
        client_id=client_id,
        **fiscal_year_data.dict()
    )
    
    db.add(fiscal_year)
    db.commit()
    db.refresh(fiscal_year)
    
    return fiscal_year


@router.put("/api/fiscal-years/{fiscal_year_id}", response_model=FiscalYearResponse)
def update_fiscal_year(
    fiscal_year_id: str,
    fiscal_year_data: FiscalYearUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Geschäftsjahr aktualisieren"""
    fiscal_year = db.query(FiscalYear).join(Client).filter(
        FiscalYear.id == fiscal_year_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not fiscal_year:
        raise HTTPException(status_code=404, detail="Geschäftsjahr nicht gefunden")
    
    # Wenn is_active=True gesetzt wird, setze alle anderen auf False
    if fiscal_year_data.is_active is True:
        db.query(FiscalYear).filter(
            FiscalYear.client_id == fiscal_year.client_id,
            FiscalYear.id != fiscal_year_id,
            FiscalYear.is_active == True
        ).update({"is_active": False})
    
    update_data = fiscal_year_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fiscal_year, key, value)
    
    db.commit()
    db.refresh(fiscal_year)
    
    return fiscal_year


@router.get("/api/fiscal-years/{fiscal_year_id}", response_model=FiscalYearResponse)
def get_fiscal_year(
    fiscal_year_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnes Geschäftsjahr abrufen"""
    fiscal_year = db.query(FiscalYear).join(Client).filter(
        FiscalYear.id == fiscal_year_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not fiscal_year:
        raise HTTPException(status_code=404, detail="Geschäftsjahr nicht gefunden")
    
    return fiscal_year

