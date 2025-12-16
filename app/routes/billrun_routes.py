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


def update_bill_run_totals(db: Session, bill_run_id: str):
    """
    Aktualisiere total_amount und paid_amount einer Sollstellung basierend auf allen Charges.
    Diese Funktion sollte aufgerufen werden, wenn eine Charge aktualisiert wird.
    """
    try:
        bill_run = db.query(BillRun).options(
            joinedload(BillRun.charges)
        ).filter(BillRun.id == bill_run_id).first()
        
        if not bill_run:
            logger.warning(f"BillRun {bill_run_id} nicht gefunden für Update")
            return
        
        # Berechne total_amount aus allen Charges
        if bill_run.charges:
            bill_run.total_amount = sum(
                Decimal(str(charge.amount)) for charge in bill_run.charges
            )
            bill_run.paid_amount = sum(
                Decimal(str(charge.paid_amount)) for charge in bill_run.charges
            )
        else:
            bill_run.total_amount = Decimal(0)
            bill_run.paid_amount = Decimal(0)
        
        db.commit()
        logger.info(f"✅ BillRun {bill_run_id} aktualisiert: total={bill_run.total_amount}, paid={bill_run.paid_amount}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Aktualisieren der BillRun-Totals: {str(e)}")
        raise


@router.get("/api/bill-runs", response_model=dict)
def list_bill_runs(
    period_year: Optional[int] = Query(None),
    status: Optional[BillRunStatus] = Query(None),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
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
        if client_id:
            try:
                # Zeige NUR Daten mit diesem client_id
                query = query.filter(BillRun.client_id == client_id)
            except Exception:
                logger.warning(f"client_id Filter für BillRuns nicht verfügbar (Spalte existiert noch nicht)")
        if fiscal_year_id:
            try:
                # Zeige NUR Daten mit diesem fiscal_year_id
                query = query.filter(BillRun.fiscal_year_id == fiscal_year_id)
            except Exception:
                logger.warning(f"fiscal_year_id Filter für BillRuns nicht verfügbar (Spalte existiert noch nicht)")
        
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
        # Prüfe ob bereits eine Sollstellung für diesen Monat existiert (mit client_id und fiscal_year_id)
        existing_query = db.query(BillRun).filter(
            BillRun.owner_id == current_user.id,
            BillRun.period_month == request.period_month,
            BillRun.period_year == request.period_year
        )
        
        if request.client_id:
            try:
                existing_query = existing_query.filter(BillRun.client_id == request.client_id)
            except Exception:
                pass
        
        if request.fiscal_year_id:
            try:
                existing_query = existing_query.filter(BillRun.fiscal_year_id == request.fiscal_year_id)
            except Exception:
                pass
        
        existing = existing_query.first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Sollstellung für {request.period_month}/{request.period_year} existiert bereits"
            )
        
        # Erstelle BillRun
        bill_run = BillRun(
            owner_id=current_user.id,
            client_id=request.client_id if request.client_id else None,
            fiscal_year_id=request.fiscal_year_id if request.fiscal_year_id else None,
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
        if request.client_id:
            try:
                active_leases_query = active_leases_query.filter(Lease.client_id == request.client_id)
            except Exception:
                logger.warning(f"client_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
        
        # Filter nach fiscal_year_id falls vorhanden
        if request.fiscal_year_id:
            try:
                active_leases_query = active_leases_query.filter(Lease.fiscal_year_id == request.fiscal_year_id)
            except Exception:
                logger.warning(f"fiscal_year_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
        
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
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
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
        
        # Filter nach client_id über BillRun
        if client_id:
            try:
                # Zeige NUR Daten mit diesem client_id
                query = query.filter(BillRun.client_id == client_id)
            except Exception:
                logger.warning(f"client_id Filter für Charges nicht verfügbar (Spalte existiert noch nicht)")
        
        # Filter nach fiscal_year_id über BillRun
        if fiscal_year_id:
            try:
                # Zeige NUR Daten mit diesem fiscal_year_id
                query = query.filter(BillRun.fiscal_year_id == fiscal_year_id)
            except Exception:
                logger.warning(f"fiscal_year_id Filter für Charges nicht verfügbar (Spalte existiert noch nicht)")
        
        total = query.count()
        offset = (page - 1) * page_size
        charges = query.order_by(Charge.due_date.desc()).offset(offset).limit(page_size).all()
        
        # Hole PaymentMatches mit Warnungen für jede Charge
        from ..models.bank import PaymentMatch
        from ..models.cashbook import CashBookEntry
        charge_items = []
        for charge in charges:
            charge_dict = ChargeOut.model_validate(charge).model_dump()
            
            # Hole PaymentMatches für diese Charge
            payment_matches = db.query(PaymentMatch).filter(
                PaymentMatch.charge_id == charge.id
            ).order_by(PaymentMatch.created_at.desc()).all()
            
            # Hole auch Kassenbuch-Einträge für diese Charge
            cashbook_entries = db.query(CashBookEntry).filter(
                CashBookEntry.charge_id == charge.id
            ).order_by(CashBookEntry.created_at.desc()).all()
            
            # Berechne aktuellen Status der Charge
            total_due = Decimal(str(charge.amount))
            total_paid_final = Decimal(str(charge.paid_amount))
            remaining_amount = total_due - total_paid_final
            
            # WICHTIG: Warnungen nur basierend auf dem aktuellen Status berechnen
            # Nicht aus alten PaymentMatch-Notizen, da diese veraltet sein können
            warnings = []
            total_transaction_amount = Decimal(0)  # Summe aller Transaktionsbeträge
            total_matched_amount = Decimal(0)  # Summe aller zugeordneten Beträge
            
            # Summiere alle Transaktionsbeträge für Warnungsberechnung
            for pm in payment_matches:
                # Hole die Transaktion, um den ursprünglichen Betrag zu erhalten
                from ..models.bank import BankTransaction
                transaction = db.query(BankTransaction).filter(BankTransaction.id == pm.transaction_id).first()
                if transaction:
                    transaction_amount = Decimal(str(transaction.amount))
                    matched_amount = Decimal(str(pm.matched_amount))
                    total_transaction_amount += transaction_amount
                    total_matched_amount += matched_amount
            
            # Summiere auch Kassenbuch-Einträge
            for entry in cashbook_entries:
                if entry.entry_type == "income":
                    entry_amount = Decimal(str(entry.amount))
                    total_transaction_amount += entry_amount
            
            # Berechne Warnungen basierend auf dem aktuellen Status (NACH allen Zahlungen)
            # Nur wenn noch etwas offen ist (remaining_amount > 0)
            if remaining_amount > 0:
                # Charge ist noch nicht vollständig bezahlt
                if total_transaction_amount > 0:
                    # Verwende total_transaction_amount (tatsächlich bezahlt)
                    if total_transaction_amount < total_due:
                        # Unterzahlung: Bezahlt < Sollbetrag
                        diff = total_due - total_transaction_amount
                        diff_rounded = float(diff.quantize(Decimal('0.01')))
                        paid_rounded = float(total_transaction_amount.quantize(Decimal('0.01')))
                        due_rounded = float(total_due.quantize(Decimal('0.01')))
                        warnings.append(f"⚠️ Unterzahlung: {paid_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {due_rounded:.2f}€)")
                    elif total_transaction_amount > total_due:
                        # Überzahlung: Bezahlt > Sollbetrag
                        diff = total_transaction_amount - total_due
                        diff_rounded = float(diff.quantize(Decimal('0.01')))
                        paid_rounded = float(total_transaction_amount.quantize(Decimal('0.01')))
                        due_rounded = float(total_due.quantize(Decimal('0.01')))
                        warnings.append(f"⚠️ Überzahlung: {paid_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ zu viel (Sollbetrag: {due_rounded:.2f}€)")
                else:
                    # Keine Transaktionen, aber noch offen
                    diff = remaining_amount
                    diff_rounded = float(diff.quantize(Decimal('0.01')))
                    paid_rounded = float(total_paid_final.quantize(Decimal('0.01')))
                    due_rounded = float(total_due.quantize(Decimal('0.01')))
                    warnings.append(f"⚠️ Unterzahlung: {paid_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {due_rounded:.2f}€)")
            elif remaining_amount < 0:
                # Überzahlung: Bezahlt > Sollbetrag (auch wenn vollständig bezahlt)
                diff = abs(remaining_amount)
                diff_rounded = float(diff.quantize(Decimal('0.01')))
                paid_rounded = float(total_paid_final.quantize(Decimal('0.01')))
                due_rounded = float(total_due.quantize(Decimal('0.01')))
                warnings.append(f"⚠️ Überzahlung: {paid_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ zu viel (Sollbetrag: {due_rounded:.2f}€)")
            # Wenn remaining_amount == 0, dann keine Warnungen (alles passt genau)
            
            # Berechne Über-/Unterzahlung basierend auf tatsächlich bezahlten Beträgen
            # Verwende total_transaction_amount (tatsächlich bezahlt) statt charge.paid_amount (zugeordnet)
            total_due = Decimal(str(charge.amount))
            total_paid_final = Decimal(str(charge.paid_amount))
            
            # WICHTIG: Nur Warnungen anzeigen, wenn die Charge noch nicht vollständig bezahlt ist
            # Wenn charge.paid_amount >= charge.amount, dann ist alles bezahlt und keine Warnung nötig
            if total_paid_final < total_due:
                # Charge ist noch nicht vollständig bezahlt - zeige Warnungen
                if warnings:
                    charge_dict["warnings"] = list(set(warnings))  # Entferne Duplikate
                
                # Berechne Unterzahlung basierend auf tatsächlich bezahlten Beträgen
                # Wenn Transaktionen vorhanden, verwende deren Summe
                if total_transaction_amount > 0:
                    if total_transaction_amount > total_due:
                        charge_dict["overpayment"] = float((total_transaction_amount - total_due).quantize(Decimal('0.01')))
                    elif total_transaction_amount < total_due:
                        charge_dict["underpayment"] = float((total_due - total_transaction_amount).quantize(Decimal('0.01')))
                else:
                    # Fallback: Verwende charge.paid_amount (für Kassenbuch-Einträge)
                    if total_paid_final > total_due:
                        charge_dict["overpayment"] = float((total_paid_final - total_due).quantize(Decimal('0.01')))
                    elif total_paid_final < total_due:
                        charge_dict["underpayment"] = float((total_due - total_paid_final).quantize(Decimal('0.01')))
            elif total_paid_final > total_due:
                # Überzahlung - auch wenn vollständig bezahlt, zeige Warnung bei Überzahlung
                if warnings:
                    # Filtere nur Überzahlungs-Warnungen
                    overpayment_warnings = [w for w in warnings if "Überzahlung" in w]
                    if overpayment_warnings:
                        charge_dict["warnings"] = list(set(overpayment_warnings))
                
                if total_transaction_amount > 0:
                    if total_transaction_amount > total_due:
                        charge_dict["overpayment"] = float((total_transaction_amount - total_due).quantize(Decimal('0.01')))
                else:
                    charge_dict["overpayment"] = float((total_paid_final - total_due).quantize(Decimal('0.01')))
            # Wenn total_paid_final == total_due, dann keine Warnungen (alles passt)
            
            charge_items.append(charge_dict)
        
        return {
            "items": charge_items,
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
