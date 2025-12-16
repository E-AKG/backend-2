from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
from ..db import get_db
from ..models.user import User
from ..models.cashbook import CashBookEntry
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict
import logging

logger = logging.getLogger(__name__)

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
    model_config = ConfigDict(from_attributes=True)
    
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
    created_at: datetime
    updated_at: datetime


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
    from ..models.billrun import Charge, ChargeStatus
    from decimal import Decimal
    
    # Konvertiere leere Strings zu None für optionale Foreign Keys
    entry_dict = entry_data.model_dump()
    for key in ['tenant_id', 'lease_id', 'charge_id']:
        if key in entry_dict and entry_dict[key] == '':
            entry_dict[key] = None
    
    entry = CashBookEntry(
        owner_id=current_user.id,
        client_id=client_id,
        fiscal_year_id=fiscal_year_id,
        **entry_dict
    )
    
    db.add(entry)
    db.flush()  # Flush um ID zu bekommen
    
    # Wenn charge_id angegeben ist UND es eine Einnahme ist, aktualisiere die Charge
    if entry_data.charge_id and entry_data.entry_type == "income":
        try:
            charge = db.query(Charge).filter(Charge.id == entry_data.charge_id).first()
            if charge:
                # Aktualisiere Charge
                matched_amount = Decimal(str(entry_data.amount))
                charge.paid_amount += matched_amount
                
                if charge.paid_amount >= charge.amount:
                    charge.status = ChargeStatus.PAID
                elif charge.paid_amount > 0:
                    charge.status = ChargeStatus.PARTIALLY_PAID
                
                db.flush()
                
                # Aktualisiere BillRun (Sollstellung) automatisch
                try:
                    from ..routes.billrun_routes import update_bill_run_totals
                    update_bill_run_totals(db, charge.bill_run_id)
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Fehler beim Aktualisieren der BillRun: {str(e)}")
                    # Nicht kritisch - Charge wurde bereits aktualisiert
                
                logger.info(f"✅ Kassenbuch-Eintrag {entry.id} aktualisiert Charge {charge.id} um {matched_amount}€")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Fehler beim Aktualisieren der Charge durch Kassenbuch: {str(e)}")
            # Nicht kritisch - Eintrag wurde bereits erstellt
    
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


@router.post("/auto-reconcile", response_model=dict)
def auto_reconcile_cashbook(
    client_id: str = Query(..., description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    min_confidence: float = Query(0.6, ge=0.0, le=1.0, description="Mindest-Confidence für automatisches Matching"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Automatischer Abgleich von Kassenbuch-Einträgen mit offenen Sollbuchungen
    """
    try:
        from ..utils.universal_matcher import universal_reconcile
        
        logger.info(f"🔄 Starte Kassenbuch-Abgleich für User {current_user.id}")
        
        stats = universal_reconcile(
            db,
            current_user.id,
            client_id=client_id,
            fiscal_year_id=fiscal_year_id,
            min_confidence=min_confidence
        )
        
        logger.info(f"✅ Kassenbuch-Abgleich abgeschlossen: {stats['matched']} von {stats['processed']} Einträgen zugeordnet")
        
        return {
            "status": "success",
            "message": f"Abgleich abgeschlossen: {stats['matched']} von {stats['processed']} Zahlungen zugeordnet",
            "processed": stats.get("processed", 0),
            "matched": stats.get("matched", 0),
            "no_match": stats.get("no_match", 0),
            "errors": stats.get("errors", 0),
            "sources": stats.get("sources", {}),
            "details": stats.get("details", [])
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Fehler beim Kassenbuch-Abgleich: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Fehler beim Kassenbuch-Abgleich: {str(e)}")


@router.delete("/{entry_id}", status_code=204)
def delete_cashbook_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kassenbuch-Eintrag löschen"""
    from ..models.billrun import Charge, ChargeStatus
    from decimal import Decimal
    import logging
    
    logger = logging.getLogger(__name__)
    
    entry = db.query(CashBookEntry).filter(
        CashBookEntry.id == entry_id,
        CashBookEntry.owner_id == current_user.id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    
    # Wenn Eintrag mit Charge verknüpft ist UND es eine Einnahme war, mache Charge-Update rückgängig
    if entry.charge_id and entry.entry_type == "income":
        try:
            charge = db.query(Charge).filter(Charge.id == entry.charge_id).first()
            if charge:
                # Mache Charge-Update rückgängig
                matched_amount = Decimal(str(entry.amount))
                charge.paid_amount -= matched_amount
                
                # Status aktualisieren
                if charge.paid_amount <= 0:
                    charge.status = ChargeStatus.OPEN
                    charge.paid_amount = Decimal(0)  # Stelle sicher, dass es nicht negativ wird
                elif charge.paid_amount < charge.amount:
                    charge.status = ChargeStatus.PARTIALLY_PAID
                else:
                    charge.status = ChargeStatus.PAID
                
                db.flush()
                
                # Aktualisiere BillRun (Sollstellung) automatisch
                try:
                    from ..routes.billrun_routes import update_bill_run_totals
                    update_bill_run_totals(db, charge.bill_run_id)
                except Exception as e:
                    logger.error(f"Fehler beim Aktualisieren der BillRun beim Löschen: {str(e)}")
                    # Nicht kritisch - Charge wurde bereits aktualisiert
                
                logger.info(f"✅ Kassenbuch-Eintrag {entry_id} gelöscht, Charge {charge.id} um {matched_amount}€ reduziert")
        except Exception as e:
            logger.error(f"Fehler beim Rückgängigmachen der Charge beim Löschen: {str(e)}")
            # Nicht kritisch - Eintrag wird trotzdem gelöscht
    
    db.delete(entry)
    db.commit()
    
    return None

