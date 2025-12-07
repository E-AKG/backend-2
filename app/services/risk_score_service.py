"""
Risk Score Service für Mieter
Berechnet einen Zahlungsrisiko-Score (0-100) basierend auf dem Zahlungsverhalten.
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Tuple, Optional
from ..models.tenant import Tenant, RiskLevel
from ..models.lease import Lease, LeaseStatus
from ..models.billrun import Charge, ChargeStatus
from ..models.bank import PaymentMatch, BankTransaction
import logging

logger = logging.getLogger(__name__)


def calculate_risk_score_for_tenant(
    tenant_id: str,
    db: Session,
    months_to_analyze: int = 6
) -> Tuple[int, RiskLevel]:
    """
    Berechnet risk_score und risk_level für einen Mieter.
    
    Nutzt die letzten N Monate Soll- und Ist-Daten.
    
    Args:
        tenant_id: ID des Mieters
        db: Database Session
        months_to_analyze: Anzahl Monate für Analyse (default: 6)
    
    Returns:
        Tuple[int, RiskLevel]: (score 0-100, risk_level)
    """
    try:
        # Hole Mieter
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        # Berechne Datumsbereich (letzte N Monate)
        today = date.today()
        start_date = today - timedelta(days=months_to_analyze * 30)
        
        # Hole alle aktiven Verträge des Mieters
        active_leases = db.query(Lease).filter(
            and_(
                Lease.tenant_id == tenant_id,
                Lease.status == LeaseStatus.ACTIVE,
                or_(
                    Lease.end_date.is_(None),
                    Lease.end_date >= start_date
                )
            )
        ).all()
        
        if not active_leases:
            # Keine aktiven Verträge → neutraler Score
            return (50, RiskLevel.MEDIUM)
        
        # Hole alle relevanten Charges (Sollstellungen) der letzten N Monate
        lease_ids = [lease.id for lease in active_leases]
        
        charges = db.query(Charge).join(Lease).filter(
            and_(
                Charge.lease_id.in_(lease_ids),
                Charge.due_date >= start_date,
                Charge.due_date <= today
            )
        ).order_by(Charge.due_date).all()
        
        if not charges:
            # Keine Charges → neutraler Score
            return (50, RiskLevel.MEDIUM)
        
        # Berechne durchschnittliche Monatsmiete
        total_monthly_rent = sum(
            sum(comp.amount for comp in lease.components)
            for lease in active_leases
        )
        avg_monthly_rent = total_monthly_rent / len(active_leases) if active_leases else Decimal('0')
        
        # Initialisiere Score
        score = 100
        
        # Analysiere jeden Monat
        months_analyzed = {}
        late_months = 0
        overdue_months = 0
        underpayment_months = 0
        very_late_payments = 0  # > 10 Tage verspätet (nach 15.)
        
        for charge in charges:
            month_key = (charge.due_date.year, charge.due_date.month)
            
            if month_key not in months_analyzed:
                months_analyzed[month_key] = {
                    'charges': [],
                    'total_due': Decimal('0'),
                    'total_paid': Decimal('0'),
                    'paid_by_5th': False,
                    'paid_by_15th': False,
                    'has_overdue': False
                }
            
            month_data = months_analyzed[month_key]
            month_data['charges'].append(charge)
            month_data['total_due'] += charge.amount
            
            # Hole alle PaymentMatches für diese Charge
            payment_matches = db.query(PaymentMatch).filter(
                PaymentMatch.charge_id == charge.id
            ).all()
            
            # Berechne gezahlten Betrag
            paid_for_charge = sum(
                Decimal(str(match.matched_amount))
                for match in payment_matches
            )
            month_data['total_paid'] += paid_for_charge
            
            # Prüfe Zahlungseingang
            for match in payment_matches:
                transaction = db.query(BankTransaction).filter(
                    BankTransaction.id == match.transaction_id
                ).first()
                
                if transaction and transaction.booking_date:
                    # Prüfe ob Zahlung bis zum 5. des Monats kam
                    payment_deadline_5th = date(
                        charge.due_date.year,
                        charge.due_date.month,
                        5
                    )
                    
                    if transaction.booking_date <= payment_deadline_5th:
                        month_data['paid_by_5th'] = True
                    
                    # Prüfe ob Zahlung bis zum 15. des Monats kam
                    payment_deadline_15th = date(
                        charge.due_date.year,
                        charge.due_date.month,
                        15
                    )
                    
                    if transaction.booking_date <= payment_deadline_15th:
                        month_data['paid_by_15th'] = True
                    else:
                        # Zahlung kam nach dem 15. → sehr verspätet
                        very_late_payments += 1
            
            # Prüfe Rückstand am Monatsende
            month_end = date(
                charge.due_date.year,
                charge.due_date.month,
                28  # Verwende 28. als "Monatsende" für Konsistenz
            )
            
            if month_data['total_paid'] < month_data['total_due']:
                month_data['has_overdue'] = True
        
        # Analysiere jeden Monat
        for month_key, month_data in months_analyzed.items():
            # 1. Prüfe Pünktlichkeit (bis 5. des Monats)
            if not month_data['paid_by_5th']:
                score -= 8
                late_months += 1
            
            # 2. Prüfe Rückstand am Monatsende
            if month_data['has_overdue']:
                score -= 10
                overdue_months += 1
            
            # 3. Prüfe Unterzahlung (< 70% der Sollmiete)
            if month_data['total_due'] > 0:
                payment_ratio = (month_data['total_paid'] / month_data['total_due']) * 100
                if payment_ratio < 70:
                    score -= 5
                    underpayment_months += 1
        
        # 4. Prüfe aktuellen Rückstand (nur für offene Charges, die noch nicht in Monatsanalyse waren)
        current_overdue = Decimal('0')
        analyzed_charge_ids = set()
        for month_data in months_analyzed.values():
            for charge in month_data['charges']:
                analyzed_charge_ids.add(charge.id)
        
        # Zähle nur offene Charges, die nicht bereits in der Monatsanalyse waren
        for charge in charges:
            if charge.id not in analyzed_charge_ids:
                if charge.status in [ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]:
                    remaining = charge.amount - charge.paid_amount
                    if remaining > 0:
                        current_overdue += remaining
        
        # Zusätzlich: Prüfe ob es offene Beträge in bereits analysierten Monaten gibt
        for month_data in months_analyzed.values():
            if month_data['total_due'] > month_data['total_paid']:
                current_overdue += (month_data['total_due'] - month_data['total_paid'])
        
        if avg_monthly_rent > 0:
            months_overdue = current_overdue / avg_monthly_rent
            
            # Zusätzliche Abzüge für hohen aktuellen Rückstand
            if months_overdue > 2:
                score -= 40  # Sehr hoher Rückstand
            elif months_overdue > 1:
                score -= 25  # Hoher Rückstand
        
        # 5. Zusätzlicher Abzug für sehr verspätete Zahlungen (> 10 Tage = nach 15.)
        if very_late_payments > 0:
            score -= 5
        
        # Score clampen auf 0-100
        score = max(0, min(100, score))
        
        # Bestimme risk_level
        if score >= 80:
            risk_level = RiskLevel.LOW
        elif score >= 50:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.HIGH
        
        logger.info(
            f"✅ Risk Score berechnet für Tenant {tenant_id}: "
            f"Score={score}, Level={risk_level.value}, "
            f"Late={late_months}, Overdue={overdue_months}, "
            f"CurrentOverdue={current_overdue}"
        )
        
        return (score, risk_level)
        
    except Exception as e:
        logger.error(f"❌ Fehler bei Risk Score Berechnung für Tenant {tenant_id}: {str(e)}")
        raise


def update_tenant_risk_score(
    tenant_id: str,
    db: Session,
    months_to_analyze: int = 6
) -> Tuple[int, RiskLevel]:
    """
    Berechnet und speichert den Risk Score für einen Mieter.
    
    Returns:
        Tuple[int, RiskLevel]: (score, risk_level)
    """
    score, risk_level = calculate_risk_score_for_tenant(tenant_id, db, months_to_analyze)
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        tenant.risk_score = score
        tenant.risk_level = risk_level
        tenant.risk_updated_at = datetime.now()
        db.commit()
        db.refresh(tenant)
    
    return (score, risk_level)


def recalculate_all_tenant_risk_scores(
    db: Session,
    owner_id: Optional[int] = None,
    months_to_analyze: int = 6
) -> dict:
    """
    Berechnet Risk Scores für alle Mieter (oder nur für einen Owner).
    
    Returns:
        dict mit Statistiken: {total, updated, errors}
    """
    query = db.query(Tenant)
    if owner_id:
        query = query.filter(Tenant.owner_id == owner_id)
    
    tenants = query.all()
    total = len(tenants)
    updated = 0
    errors = 0
    
    for tenant in tenants:
        try:
            update_tenant_risk_score(tenant.id, db, months_to_analyze)
            updated += 1
        except Exception as e:
            logger.error(f"Fehler bei Tenant {tenant.id}: {str(e)}")
            errors += 1
    
    return {
        "total": total,
        "updated": updated,
        "errors": errors
    }

