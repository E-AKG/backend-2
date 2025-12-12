from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from datetime import date
from decimal import Decimal
from ..db import get_db
from ..models.user import User
from ..models.billrun import BillRun, Charge, BillRunStatus, ChargeStatus
from ..models.lease import Lease, LeaseStatus, LeaseComponent
from ..schemas.billrun_schema import (
    BillRunCreate, BillRunUpdate, BillRunOut,
    BillRunGenerateRequest, ChargeOut, ChargeUpdate
)
from ..utils.deps import get_current_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Sollstellungen"])


@router.get("/api/bill-runs", response_model=dict)
def list_bill_runs(
    period_year: Optional[int] = Query(None),
    status: Optional[BillRunStatus] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Sollstellungen"""
    try:
        query = db.query(BillRun).filter(BillRun.owner_id == current_user.id)
        
        if period_year:
            query = query.filter(BillRun.period_year == period_year)
        if status:
            query = query.filter(BillRun.status == status)
        
        total = query.count()
        offset = (page - 1) * page_size
        bill_runs = query.options(
            joinedload(BillRun.charges)
        ).order_by(
            BillRun.period_year.desc(),
            BillRun.period_month.desc()
        ).offset(offset).limit(page_size).all()
        
        # Berechne paid_amount dynamisch aus den Charges
        for bill_run in bill_runs:
            if bill_run.charges:
                bill_run.paid_amount = sum(
                    Decimal(str(charge.paid_amount)) for charge in bill_run.charges
                )
            else:
                bill_run.paid_amount = Decimal(0)
        
        return {
            "items": [BillRunOut.model_validate(br) for br in bill_runs],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Fehler beim Laden der Sollstellungen: {str(e)}")
        raise HTTPException(status_code=500, detail="Datenbankfehler")


@router.post("/api/bill-runs/generate", response_model=BillRunOut, status_code=201)
def generate_bill_run(
    request: BillRunGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generiert automatisch eine Sollstellung für den angegebenen Monat.
    Erstellt Charges für alle aktiven Verträge.
    """
    try:
        # Prüfe ob bereits eine Sollstellung für diesen Monat existiert
        existing = db.query(BillRun).filter(
            BillRun.owner_id == current_user.id,
            BillRun.period_month == request.period_month,
            BillRun.period_year == request.period_year
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Sollstellung für {request.period_month}/{request.period_year} existiert bereits"
            )
        
        # Erstelle BillRun
        bill_run = BillRun(
            owner_id=current_user.id,
            client_id=request.client_id if hasattr(request, 'client_id') and request.client_id else None,
            fiscal_year_id=request.fiscal_year_id if hasattr(request, 'fiscal_year_id') and request.fiscal_year_id else None,
            period_month=request.period_month,
            period_year=request.period_year,
            description=request.description,
            status=BillRunStatus.DRAFT
        )
        db.add(bill_run)
        db.flush()  # Um ID zu bekommen
        
        # Hole alle aktiven Verträge des Benutzers
        active_leases_query = db.query(Lease).filter(
            Lease.owner_id == current_user.id,
            Lease.status == LeaseStatus.ACTIVE
        )
        
        # Filter nach client_id falls vorhanden
        if hasattr(request, 'client_id') and request.client_id:
            active_leases_query = active_leases_query.filter(Lease.client_id == request.client_id)
        
        active_leases = active_leases_query.all()
        
        logger.info(f"🔍 Found {len(active_leases)} active leases for user {current_user.id}")
        
        total_amount = Decimal(0)
        
        # Erstelle Charges für jeden Vertrag
        for lease in active_leases:
            logger.info(f"🔍 Processing lease {lease.id}: {len(lease.components)} components")
            
            # Berechne Gesamtmiete aus Komponenten
            lease_amount = sum(
                Decimal(str(component.amount))
                for component in lease.components
            )
            
            logger.info(f"🔍 Lease {lease.id} total amount: {lease_amount}")
            
            if lease_amount <= 0:
                logger.warning(f"⚠️ Lease {lease.id} has no components or 0 amount, skipping")
                continue  # Überspringe Verträge ohne Komponenten
            
            # Fälligkeitsdatum: due_day im angegebenen Monat
            try:
                due_date = date(request.period_year, request.period_month, lease.due_day)
            except ValueError:
                # Falls due_day ungültig (z.B. 31. Feb), nimm letzten Tag des Monats
                if request.period_month == 12:
                    due_date = date(request.period_year, 12, 31)
                else:
                    due_date = date(request.period_year, request.period_month + 1, 1)
                    due_date = due_date.replace(day=due_date.day - 1)
            
            charge = Charge(
                bill_run_id=bill_run.id,
                lease_id=lease.id,
                amount=lease_amount,
                due_date=due_date,
                status=ChargeStatus.OPEN,
                description=f"Miete {request.period_month:02d}/{request.period_year}"
            )
            db.add(charge)
            total_amount += lease_amount
        
        # Aktualisiere total_amount
        bill_run.total_amount = total_amount
        
        logger.info(f"💰 Final total_amount: {total_amount} €")
        
        db.commit()
        db.refresh(bill_run)
        
        logger.info(f"Sollstellung generiert: {bill_run.id} ({len(active_leases)} Verträge, {total_amount} €)")
        return BillRunOut.model_validate(bill_run)
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Generieren der Sollstellung: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Erstellen")


@router.get("/api/bill-runs/{bill_run_id}", response_model=BillRunOut)
def get_bill_run(
    bill_run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Hole eine spezifische Sollstellung"""
    bill_run = db.query(BillRun).options(
        joinedload(BillRun.charges)
    ).filter(
        BillRun.id == bill_run_id,
        BillRun.owner_id == current_user.id
    ).first()
    
    if not bill_run:
        raise HTTPException(status_code=404, detail="Sollstellung nicht gefunden")
    
    # Berechne paid_amount dynamisch aus den Charges
    if bill_run.charges:
        bill_run.paid_amount = sum(
            Decimal(str(charge.paid_amount)) for charge in bill_run.charges
        )
    else:
        bill_run.paid_amount = Decimal(0)
    
    return BillRunOut.model_validate(bill_run)


@router.put("/api/bill-runs/{bill_run_id}", response_model=BillRunOut)
def update_bill_run(
    bill_run_id: str,
    data: BillRunUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere Sollstellung (z.B. Status ändern)"""
    bill_run = db.query(BillRun).filter(
        BillRun.id == bill_run_id,
        BillRun.owner_id == current_user.id
    ).first()
    
    if not bill_run:
        raise HTTPException(status_code=404, detail="Sollstellung nicht gefunden")
    
    try:
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(bill_run, field, value)
        
        db.commit()
        db.refresh(bill_run)
        return BillRunOut.model_validate(bill_run)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Aktualisieren: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Aktualisieren")


@router.delete("/api/bill-runs/{bill_run_id}", status_code=204)
def delete_bill_run(
    bill_run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche Sollstellung (nur im Draft-Status)"""
    bill_run = db.query(BillRun).filter(
        BillRun.id == bill_run_id,
        BillRun.owner_id == current_user.id
    ).first()
    
    if not bill_run:
        raise HTTPException(status_code=404, detail="Sollstellung nicht gefunden")
    
    if bill_run.status != BillRunStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Nur Entwürfe können gelöscht werden"
        )
    
    try:
        db.delete(bill_run)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Löschen: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Löschen")


# ========= Charges (Sollbuchungen) =========

@router.get("/api/charges", response_model=dict)
def list_charges(
    bill_run_id: Optional[str] = Query(None),
    status: Optional[ChargeStatus] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Sollbuchungen mit Mieter/Objekt-Informationen"""
    try:
        logger.info(f"🔍 Charges API called - status: {status}, page: {page}, page_size: {page_size}")
        # Import hier um zirkuläre Imports zu vermeiden
        from sqlalchemy.orm import joinedload
        from ..models.lease import Lease
        from ..models.tenant import Tenant
        from ..models.unit import Unit
        from ..models.property import Property
        
        # Join mit BillRun für owner_id check und lade alle Relationships
        query = db.query(Charge).join(BillRun).filter(
            BillRun.owner_id == current_user.id
        ).options(
            joinedload(Charge.lease).joinedload(Lease.tenant),
            joinedload(Charge.lease).joinedload(Lease.unit).joinedload(Unit.property)
        )
        
        if bill_run_id:
            query = query.filter(Charge.bill_run_id == bill_run_id)
        if status:
            query = query.filter(Charge.status == status)
        
        total = query.count()
        offset = (page - 1) * page_size
        charges = query.order_by(Charge.due_date.desc()).offset(offset).limit(page_size).all()
        
        return {
            "items": [ChargeOut.model_validate(c) for c in charges],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Fehler beim Laden der Sollbuchungen: {str(e)}")
        raise HTTPException(status_code=500, detail="Datenbankfehler")


@router.put("/api/charges/{charge_id}", response_model=ChargeOut)
def update_charge(
    charge_id: str,
    data: ChargeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere Sollbuchung"""
    # Import hier um zirkuläre Imports zu vermeiden
    from sqlalchemy.orm import joinedload
    from ..models.lease import Lease
    from ..models.tenant import Tenant
    from ..models.unit import Unit
    from ..models.property import Property
    
    charge = db.query(Charge).join(BillRun).filter(
        Charge.id == charge_id,
        BillRun.owner_id == current_user.id
    ).options(
        joinedload(Charge.lease).joinedload(Lease.tenant),
        joinedload(Charge.lease).joinedload(Lease.unit).joinedload(Unit.property)
    ).first()
    
    if not charge:
        raise HTTPException(status_code=404, detail="Sollbuchung nicht gefunden")
    
    try:
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(charge, field, value)
        
        db.commit()
        db.refresh(charge)
        return ChargeOut.model_validate(charge)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Aktualisieren: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Aktualisieren")



# ========= Automatisches Matching =========

@router.post("/api/charges/match")
def match_charges_with_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Führt automatisches Matching von offenen Charges mit Banktransaktionen durch
    """
    try:
        from ..services.matching_service import auto_match_transactions
        
        logger.info(f"🔄 Manuelles Matching gestartet für User {current_user.id}")
        
        stats = auto_match_transactions(db, current_user.id)
        
        return {
            "success": True,
            "message": f"{stats['matched']} Zahlungen zugeordnet",
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Matching: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Matching: {str(e)}")


@router.post("/api/charges/{charge_id}/unmatch")
def unmatch_charge(
    charge_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Entfernt alle Zahlungszuordnungen von einer Charge
    """
    # Prüfe Zugriff
    charge = db.query(Charge).join(BillRun).filter(
        Charge.id == charge_id,
        BillRun.owner_id == current_user.id
    ).first()
    
    if not charge:
        raise HTTPException(status_code=404, detail="Sollbuchung nicht gefunden")
    
    try:
        from ..services.matching_service import MatchingService
        
        service = MatchingService(db)
        success = service.unmatch_charge(charge_id)
        
        if success:
            return {"success": True, "message": "Zuordnung entfernt"}
        else:
            raise HTTPException(status_code=500, detail="Fehler beim Entfernen")
            
    except Exception as e:
        logger.error(f"❌ Fehler beim Unmatch: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
