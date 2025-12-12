from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from decimal import Decimal
from ..db import get_db
from ..models.user import User
from ..models.cashbook import CashBookEntry
from ..utils.deps import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/api/cashbook", tags=["CashBook"])


class CashBookEntryCreate(BaseModel):
    entry_date: date
    entry_type: str  # "income" or "expense"
    amount: float
    purpose: Optional[str] = None
    lease_id: Optional[str] = None
    tenant_id: Optional[str] = None
    charge_id: Optional[str] = None


class CashBookEntryResponse(BaseModel):
    id: str
    client_id: str
    fiscal_year_id: Optional[str]
    entry_date: date
    entry_type: str
    amount: float
    purpose: Optional[str]
    lease_id: Optional[str]
    tenant_id: Optional[str]
    charge_id: Optional[str]
    receipt_path: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CashBookBalance(BaseModel):
    opening_balance: float
    total_income: float
    total_expenses: float
    current_balance: float


@router.get("", response_model=List[CashBookEntryResponse])
def list_cashbook_entries(
    client_id: str = Query(..., description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    entry_type: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Kassenbuch-Einträge"""
    query = db.query(CashBookEntry).filter(
        CashBookEntry.owner_id == current_user.id,
        CashBookEntry.client_id == client_id
    )
    
    if fiscal_year_id:
        query = query.filter(CashBookEntry.fiscal_year_id == fiscal_year_id)
    if start_date:
        query = query.filter(CashBookEntry.entry_date >= start_date)
    if end_date:
        query = query.filter(CashBookEntry.entry_date <= end_date)
    if entry_type:
        query = query.filter(CashBookEntry.entry_type == entry_type)
    
    entries = query.order_by(CashBookEntry.entry_date.desc()).all()
    return entries


@router.post("", response_model=CashBookEntryResponse, status_code=201)
def create_cashbook_entry(
    entry_data: CashBookEntryCreate,
    client_id: str = Query(..., description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neuen Kassenbuch-Eintrag erstellen"""
    entry = CashBookEntry(
        owner_id=current_user.id,
        client_id=client_id,
        fiscal_year_id=fiscal_year_id,
        **entry_data.dict()
    )
    
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    return entry


@router.get("/balance", response_model=CashBookBalance)
def get_cashbook_balance(
    client_id: str = Query(..., description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kassenstand berechnen"""
    query = db.query(CashBookEntry).filter(
        CashBookEntry.owner_id == current_user.id,
        CashBookEntry.client_id == client_id
    )
    
    if fiscal_year_id:
        query = query.filter(CashBookEntry.fiscal_year_id == fiscal_year_id)
    
    entries = query.all()
    
    total_income = sum(float(e.amount) for e in entries if e.entry_type == "income")
    total_expenses = sum(float(e.amount) for e in entries if e.entry_type == "expense")
    
    # Öffnungssaldo (vereinfacht - könnte aus Vorjahr kommen)
    opening_balance = 0.0
    
    current_balance = opening_balance + total_income - total_expenses
    
    return {
        "opening_balance": opening_balance,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "current_balance": current_balance
    }


@router.delete("/{entry_id}", status_code=204)
def delete_cashbook_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kassenbuch-Eintrag löschen"""
    entry = db.query(CashBookEntry).filter(
        CashBookEntry.id == entry_id,
        CashBookEntry.owner_id == current_user.id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    
    db.delete(entry)
    db.commit()
    
    return None

