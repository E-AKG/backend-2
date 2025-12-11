from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from decimal import Decimal
from ..db import get_db
from ..models.user import User
from ..models.accounting import Accounting, AccountingItem, UnitSettlement, AccountingType, AccountingStatus
from ..models.lease import Lease, LeaseStatus
from ..models.unit import Unit
from ..models.tenant import Tenant
from ..models.property import Property
from ..models.billrun import Charge
from ..utils.deps import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/api/accounting", tags=["Accounting"])


class AccountingCreate(BaseModel):
    accounting_type: AccountingType
    period_start: date
    period_end: date
    notes: Optional[str] = None


class AccountingItemCreate(BaseModel):
    cost_type: str
    description: str
    amount: float
    is_allocable: bool = True
    notes: Optional[str] = None


class AccountingResponse(BaseModel):
    id: str
    client_id: str
    fiscal_year_id: Optional[str]
    accounting_type: str
    status: str
    period_start: date
    period_end: date
    total_costs: float
    total_advance_payments: float
    total_settlement: float
    document_path: Optional[str]
    generated_at: Optional[date]
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[AccountingResponse])
def list_accountings(
    client_id: Optional[str] = Query(None),
    fiscal_year_id: Optional[str] = Query(None),
    accounting_type: Optional[AccountingType] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Abrechnungen"""
    query = db.query(Accounting).filter(Accounting.owner_id == current_user.id)
    
    if client_id:
        query = query.filter(Accounting.client_id == client_id)
    if fiscal_year_id:
        query = query.filter(Accounting.fiscal_year_id == fiscal_year_id)
    if accounting_type:
        query = query.filter(Accounting.accounting_type == accounting_type)
    
    accountings = query.order_by(Accounting.period_end.desc()).all()
    return accountings


@router.post("", response_model=AccountingResponse, status_code=201)
def create_accounting(
    accounting_data: AccountingCreate,
    client_id: str = Query(..., description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neue Abrechnung erstellen"""
    accounting = Accounting(
        owner_id=current_user.id,
        client_id=client_id,
        fiscal_year_id=fiscal_year_id,
        **accounting_data.dict()
    )
    
    db.add(accounting)
    db.commit()
    db.refresh(accounting)
    
    return accounting


@router.get("/{accounting_id}", response_model=AccountingResponse)
def get_accounting(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelne Abrechnung abrufen"""
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    return accounting


@router.post("/{accounting_id}/items", status_code=201)
def add_accounting_item(
    accounting_id: str,
    item_data: AccountingItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kostenposten zur Abrechnung hinzufügen"""
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    item = AccountingItem(
        accounting_id=accounting_id,
        **item_data.dict()
    )
    
    db.add(item)
    
    # Aktualisiere Gesamtkosten
    accounting.total_costs += Decimal(str(item_data.amount))
    
    db.commit()
    db.refresh(item)
    
    return item


@router.post("/{accounting_id}/calculate")
def calculate_accounting(
    accounting_id: str,
    allocation_method: str = Query("area", description="Umlageschlüssel: 'area', 'units', 'persons'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Abrechnung berechnen
    Verteilt Kosten auf alle Einheiten basierend auf Umlageschlüssel
    """
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    # Hole alle aktiven Verträge im Zeitraum
    active_leases = db.query(Lease).join(Unit).join(Property).filter(
        Property.client_id == accounting.client_id,
        Lease.status == LeaseStatus.ACTIVE,
        Lease.start_date <= accounting.period_end,
        (Lease.end_date.is_(None) | (Lease.end_date >= accounting.period_start))
    ).all()
    
    # Berechne Gesamtfläche/Gesamteinheiten für Umlage
    total_area = 0
    total_units = len(active_leases)
    
    for lease in active_leases:
        if lease.unit and lease.unit.size_sqm:
            total_area += lease.unit.size_sqm
    
    # Hole alle Kostenposten
    items = db.query(AccountingItem).filter(
        AccountingItem.accounting_id == accounting_id,
        AccountingItem.is_allocable == True
    ).all()
    
    total_allocable_costs = sum(float(item.amount) for item in items)
    
    # Lösche alte Einzelabrechnungen
    db.query(UnitSettlement).filter(
        UnitSettlement.accounting_id == accounting_id
    ).delete()
    
    # Berechne für jede Einheit
    total_advance = Decimal(0)
    total_settlement = Decimal(0)
    
    for lease in active_leases:
        unit = lease.unit
        tenant = lease.tenant
        
        # Berechne Anteil basierend auf Umlageschlüssel
        if allocation_method == "area" and unit.size_sqm and total_area > 0:
            allocation_factor = Decimal(unit.size_sqm) / Decimal(total_area)
        elif allocation_method == "units" and total_units > 0:
            allocation_factor = Decimal(1) / Decimal(total_units)
        else:
            allocation_factor = Decimal(1) / Decimal(total_units) if total_units > 0 else Decimal(0)
        
        allocated_costs = Decimal(str(total_allocable_costs)) * allocation_factor
        
        # Hole Vorauszahlungen aus Lease Components
        advance_payments = Decimal(0)
        for component in lease.components:
            if component.type.value in ["operating_costs", "heating_costs"]:
                # Berechne Vorauszahlungen für den Zeitraum
                months_in_period = 12  # Vereinfacht - könnte genauer berechnet werden
                advance_payments += Decimal(str(component.amount)) * Decimal(months_in_period)
        
        settlement_amount = allocated_costs - advance_payments
        
        settlement = UnitSettlement(
            accounting_id=accounting_id,
            unit_id=unit.id if unit else None,
            lease_id=lease.id,
            tenant_id=tenant.id if tenant else None,
            advance_payments=advance_payments,
            allocated_costs=allocated_costs,
            settlement_amount=settlement_amount
        )
        
        db.add(settlement)
        total_advance += advance_payments
        total_settlement += settlement_amount
    
    # Aktualisiere Abrechnung
    accounting.total_advance_payments = total_advance
    accounting.total_settlement = total_settlement
    accounting.status = AccountingStatus.CALCULATED
    
    db.commit()
    
    return {
        "status": "calculated",
        "total_costs": float(accounting.total_costs),
        "total_advance_payments": float(total_advance),
        "total_settlement": float(total_settlement),
        "units_count": len(active_leases)
    }


@router.get("/{accounting_id}/settlements")
def get_settlements(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelabrechnungen einer Abrechnung abrufen"""
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    settlements = db.query(UnitSettlement).filter(
        UnitSettlement.accounting_id == accounting_id
    ).all()
    
    settlements_data = []
    for settlement in settlements:
        settlements_data.append({
            "id": settlement.id,
            "unit_id": settlement.unit_id,
            "unit_label": settlement.unit.unit_label if settlement.unit else None,
            "tenant_id": settlement.tenant_id,
            "tenant_name": f"{settlement.tenant.first_name} {settlement.tenant.last_name}" if settlement.tenant else None,
            "advance_payments": float(settlement.advance_payments),
            "allocated_costs": float(settlement.allocated_costs),
            "settlement_amount": float(settlement.settlement_amount),
            "is_sent": settlement.is_sent,
        })
    
    return settlements_data


@router.post("/{accounting_id}/generate")
def generate_accounting_documents(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generiere PDF-Dokumente für Abrechnung
    (Vereinfacht - in Produktion würde hier PDF-Generierung stattfinden)
    """
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    if accounting.status != AccountingStatus.CALCULATED:
        raise HTTPException(
            status_code=400,
            detail="Abrechnung muss zuerst berechnet werden"
        )
    
    # In Produktion: PDF-Generierung hier
    # Für jetzt: Setze Status auf generiert
    accounting.status = AccountingStatus.GENERATED
    accounting.generated_at = date.today()
    accounting.document_path = f"/documents/accounting_{accounting_id}.pdf"
    
    db.commit()
    
    return {
        "status": "generated",
        "document_path": accounting.document_path,
        "generated_at": accounting.generated_at.isoformat()
    }


@router.get("/{accounting_id}/items")
def get_accounting_items(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kostenposten einer Abrechnung abrufen"""
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    items = db.query(AccountingItem).filter(
        AccountingItem.accounting_id == accounting_id
    ).all()
    
    return [
        {
            "id": item.id,
            "cost_type": item.cost_type,
            "description": item.description,
            "amount": float(item.amount),
            "is_allocable": item.is_allocable,
            "notes": item.notes
        }
        for item in items
    ]

