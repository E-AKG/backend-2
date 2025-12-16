from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from decimal import Decimal
from datetime import date, datetime, timedelta
from ..db import get_db
from ..models.user import User
from ..models.billrun import BillRun, Charge, ChargeStatus
from ..models.bank import BankTransaction, PaymentMatch
from ..models.auto_match_log import AutoMatchLog
from ..utils.deps import get_current_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stats", tags=["Statistics"])


@router.get("/dashboard")
def get_dashboard_stats(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole Dashboard-Statistiken mit echten Daten
    
    Inkludiert:
    - Mieteinnahmen für den gewählten Monat (Soll/Ist/Offen)
    - Anzahl Objekte, Einheiten, Mieter, Verträge
    - Offene Posten
    """
    # Falls kein Monat angegeben, nimm aktuellen
    if not month or not year:
        today = date.today()
        month = today.month
        year = today.year
    
    # Hole BillRun für diesen Monat
    bill_run_query = db.query(BillRun).filter(
        BillRun.owner_id == current_user.id,
        BillRun.period_month == month,
        BillRun.period_year == year
    )
    
    if client_id:
        try:
            # Zeige NUR Daten mit diesem client_id
            bill_run_query = bill_run_query.filter(BillRun.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für BillRuns nicht verfügbar (Spalte existiert noch nicht)")
    
    if fiscal_year_id:
        try:
            # Zeige NUR Daten mit diesem fiscal_year_id
            bill_run_query = bill_run_query.filter(BillRun.fiscal_year_id == fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für BillRuns nicht verfügbar (Spalte existiert noch nicht)")
    
    bill_run = bill_run_query.first()
    
    rent_data = {
        "erwartet": 0,
        "bezahlt": 0,
        "offen": 0,
        "prozent": 0,
    }
    
    if bill_run and bill_run.charges:
        total_expected = sum(Decimal(str(c.amount)) for c in bill_run.charges)
        total_paid = sum(Decimal(str(c.paid_amount)) for c in bill_run.charges)
        total_open = total_expected - total_paid
        
        rent_data = {
            "erwartet": float(total_expected),
            "bezahlt": float(total_paid),
            "offen": float(total_open),
            "prozent": int((total_paid / total_expected * 100) if total_expected > 0 else 0),
        }
    
    # Offene Posten (alle Monate)
    from ..models.lease import Lease
    from ..models.unit import Unit
    from ..models.tenant import Tenant
    from ..models.property import Property
    
    open_charges_query = db.query(
        Charge, Lease, Tenant, Unit, Property, BillRun
    ).join(
        BillRun, Charge.bill_run_id == BillRun.id
    ).join(
        Lease, Charge.lease_id == Lease.id
    ).join(
        Tenant, Lease.tenant_id == Tenant.id
    ).join(
        Unit, Lease.unit_id == Unit.id
    ).join(
        Property, Unit.property_id == Property.id
    ).filter(
        BillRun.owner_id == current_user.id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE])
    )
    
    # Filter nach client_id über BillRun
    if client_id:
        try:
            # Zeige NUR Daten mit diesem client_id
            open_charges_query = open_charges_query.filter(BillRun.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für offene Charges nicht verfügbar (Spalte existiert noch nicht)")
    
    # Filter nach fiscal_year_id über BillRun
    if fiscal_year_id:
        try:
            # Zeige NUR Daten mit diesem fiscal_year_id
            open_charges_query = open_charges_query.filter(BillRun.fiscal_year_id == fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für offene Charges nicht verfügbar (Spalte existiert noch nicht)")
    
    open_charges = open_charges_query.order_by(
        Charge.due_date
    ).all()  # Alle offenen Posten, nicht nur 10
    
    offene_posten = []
    for charge, lease, tenant, unit, prop, bill_run in open_charges:
        # Prüfe ob überfällig
        is_overdue = charge.due_date < date.today() and charge.status in [ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID]
        status_value = "overdue" if is_overdue else charge.status.value
        
        offene_posten.append({
            "charge_id": charge.id,
            "tenant_id": tenant.id,
            "lease_id": lease.id,
            "unit_id": unit.id,
            "property_id": prop.id,
            "mieter": f"{tenant.first_name} {tenant.last_name}",
            "einheit": unit.unit_label,
            "objekt": prop.name,
            "betrag": float(charge.amount),
            "bezahlt": float(charge.paid_amount),
            "offen": float(charge.amount - charge.paid_amount),
            "faellig": charge.due_date.isoformat(),
            "status": status_value,
        })
    
    # Zusätzliche Statistiken für Action-Center
    from ..models.unit import UnitStatus
    from ..models.lease import LeaseStatus
    
    # Leerstand
    units_query = db.query(Unit).filter(Unit.owner_id == current_user.id)
    if client_id:
        try:
            units_query = units_query.filter(Unit.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für Units nicht verfügbar (Spalte existiert noch nicht)")
    total_units = units_query.count()
    
    vacant_units_query = db.query(Unit).filter(
        Unit.owner_id == current_user.id,
        Unit.status == UnitStatus.VACANT
    )
    if client_id:
        try:
            vacant_units_query = vacant_units_query.filter(Unit.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für Units nicht verfügbar (Spalte existiert noch nicht)")
    vacant_units = vacant_units_query.count()
    vacancy_rate = int((vacant_units / total_units * 100) if total_units > 0 else 0)
    
    # Aktive Verträge
    active_leases_query = db.query(Lease).filter(
        Lease.owner_id == current_user.id,
        Lease.status == LeaseStatus.ACTIVE
    )
    if client_id:
        try:
            # Zeige NUR Daten mit diesem client_id
            active_leases_query = active_leases_query.filter(Lease.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
    if fiscal_year_id:
        try:
            # Zeige NUR Daten mit diesem fiscal_year_id
            active_leases_query = active_leases_query.filter(Lease.fiscal_year_id == fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
    active_leases = active_leases_query.count()
    
    # Überfällige Posten
    today = date.today()
    overdue_charges_query = db.query(Charge).join(BillRun).join(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]),
        Charge.due_date < today
    )
    
    # Filter nach client_id über BillRun
    if client_id:
        try:
            # Zeige NUR Daten mit diesem client_id
            overdue_charges_query = overdue_charges_query.filter(BillRun.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für überfällige Charges nicht verfügbar (Spalte existiert noch nicht)")
    
    # Filter nach fiscal_year_id über BillRun
    if fiscal_year_id:
        try:
            # Zeige NUR Daten mit diesem fiscal_year_id
            overdue_charges_query = overdue_charges_query.filter(BillRun.fiscal_year_id == fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für überfällige Charges nicht verfügbar (Spalte existiert noch nicht)")
    
    overdue_charges = overdue_charges_query.count()
    
    # Tickets-Statistik
    from ..models.ticket import Ticket, TicketStatus, TicketPriority
    tickets_query = db.query(Ticket).filter(Ticket.owner_id == current_user.id)
    if client_id:
        tickets_query = tickets_query.filter(Ticket.client_id == client_id)
    
    urgent_tickets = tickets_query.filter(
        Ticket.status != TicketStatus.RESOLVED,
        Ticket.status != TicketStatus.CLOSED,
        Ticket.priority == TicketPriority.URGENT
    ).count()
    
    open_tickets = tickets_query.filter(
        Ticket.status.in_([TicketStatus.NEW, TicketStatus.IN_PROGRESS, TicketStatus.ASSIGNED])
    ).count()
    
    # To-Dos (erweitert)
    todos = []
    
    # To-Do: Überfällige Posten
    if overdue_charges > 0:
        todos.append({
            "id": "overdue_charges",
            "type": "urgent",
            "title": f"{overdue_charges} überfällige Posten",
            "description": "Es gibt Zahlungen, die bereits überfällig sind",
            "action_url": "/finanzen?filter=overdue",
            "priority": "high"
        })
    
    # To-Do: Dringende Tickets
    if urgent_tickets > 0:
        todos.append({
            "id": "urgent_tickets",
            "type": "urgent",
            "title": f"{urgent_tickets} dringende Tickets",
            "description": "Es gibt dringende Vorgänge, die Aufmerksamkeit benötigen",
            "action_url": "/vorgaenge?filter=urgent",
            "priority": "high"
        })
    
    # To-Do: Offene Tickets
    if open_tickets > 0:
        todos.append({
            "id": "open_tickets",
            "type": "info",
            "title": f"{open_tickets} offene Tickets",
            "description": "Es gibt Vorgänge, die noch bearbeitet werden müssen",
            "action_url": "/vorgaenge",
            "priority": "medium"
        })
    
    # To-Do: Leerstand
    if vacancy_rate > 10:
        todos.append({
            "id": "high_vacancy",
            "type": "warning",
            "title": f"Leerstand: {vacancy_rate}%",
            "description": f"{vacant_units} von {total_units} Einheiten sind leer",
            "action_url": "/verwaltung?filter=vacant",
            "priority": "medium"
        })
    
    # Aktivitäts-Feed (erweitert - letzte 10 Aktivitäten)
    activities = []
    
    # Letzte Zahlungen (aus PaymentMatches)
    recent_payments_query = db.query(PaymentMatch).join(Charge).join(BillRun).join(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id
    )
    
    # Filter nach client_id über BillRun
    if client_id:
        try:
            # Zeige NUR Daten mit diesem client_id
            recent_payments_query = recent_payments_query.filter(BillRun.client_id == client_id)
        except Exception:
            logger.warning(f"client_id Filter für recent payments nicht verfügbar (Spalte existiert noch nicht)")
    
    # Filter nach fiscal_year_id über BillRun
    if fiscal_year_id:
        try:
            # Zeige NUR Daten mit diesem fiscal_year_id
            recent_payments_query = recent_payments_query.filter(BillRun.fiscal_year_id == fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für recent payments nicht verfügbar (Spalte existiert noch nicht)")
    
    recent_payments = recent_payments_query.order_by(PaymentMatch.created_at.desc()).limit(3).all()
    
    for payment in recent_payments:
        activities.append({
            "id": f"payment_{payment.id}",
            "type": "payment",
            "title": f"Zahlung erhalten: {float(payment.matched_amount):.2f} €",
            "description": f"Zuordnung zu {payment.charge.lease.tenant.first_name} {payment.charge.lease.tenant.last_name}",
            "timestamp": payment.created_at.isoformat() if payment.created_at else None,
            "icon": "payment"
        })
    
    # Letzte Tickets
    recent_tickets = tickets_query.order_by(Ticket.created_at.desc()).limit(3).all()
    for ticket in recent_tickets:
        activities.append({
            "id": f"ticket_{ticket.id}",
            "type": "ticket",
            "title": f"Neues Ticket: {ticket.title}",
            "description": f"Status: {ticket.status.value}, Priorität: {ticket.priority.value}",
            "timestamp": ticket.created_at.isoformat() if ticket.created_at else None,
            "icon": "ticket"
        })
    
    return {
        "rent_overview": rent_data,
        "period": {"month": month, "year": year},
        "open_charges": offene_posten,
        # Zusätzliche Felder für das Frontend
        "total_expected": rent_data["erwartet"],
        "total_paid": rent_data["bezahlt"],
        "total_outstanding": rent_data["offen"],
        "payment_rate": rent_data["prozent"],
        # Action-Center KPIs
        "kpis": {
            "open_charges": {
                "count": len(offene_posten),
                "amount": rent_data["offen"],
                "overdue": overdue_charges,
                "status": "warning" if overdue_charges > 0 else "ok"
            },
            "vacancy": {
                "rate": vacancy_rate,
                "count": vacant_units,
                "total": total_units,
                "status": "warning" if vacancy_rate > 10 else "ok"
            },
            "urgent_tickets": {
                "count": urgent_tickets,
                "status": "error" if urgent_tickets > 0 else "ok"
            },
            "open_tickets": {
                "count": open_tickets,
                "status": "warning" if open_tickets > 5 else "ok"
            },
            "active_leases": active_leases
        },
        "todos": todos,
        "activities": activities
    }


@router.get("/auto-match")
def get_auto_match_stats(
    days: int = Query(30, ge=1, le=365, description="Zeitraum in Tagen"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole Auto-Match-Statistiken für das Dashboard
    
    Inkludiert:
    - Anzahl automatisch zugeordneter Zahlungen
    - Erfolgsrate (matched / total)
    - Durchschnittlicher Confidence-Score
    - Breakdown nach Ergebnis
    """
    from ..models.bank import BankAccount
    
    # Zeitraum berechnen
    since_date = datetime.now() - timedelta(days=days)
    
    # Hole alle Logs im Zeitraum
    logs_query = db.query(AutoMatchLog).join(
        BankTransaction,
        AutoMatchLog.transaction_id == BankTransaction.id
    ).join(
        BankAccount,
        BankTransaction.bank_account_id == BankAccount.id
    ).filter(
        BankAccount.owner_id == current_user.id,
        AutoMatchLog.created_at >= since_date
    )
    
    all_logs = logs_query.all()
    
    # Statistiken berechnen
    total_attempts = len(all_logs)
    matched = len([log for log in all_logs if log.result == "matched"])
    no_match = len([log for log in all_logs if log.result == "no_match"])
    multiple_candidates = len([log for log in all_logs if log.result == "multiple_candidates"])
    skipped = len([log for log in all_logs if log.result == "skipped"])
    
    # Erfolgsrate
    success_rate = int((matched / total_attempts * 100) if total_attempts > 0 else 0)
    
    # Durchschnittlicher Confidence Score (nur für matched)
    matched_logs = [log for log in all_logs if log.result == "matched" and log.confidence_score]
    avg_confidence = float(
        sum(log.confidence_score for log in matched_logs) / len(matched_logs)
    ) if matched_logs else 0
    
    # Anzahl automatischer Matches im aktuellen Monat
    this_month_start = datetime(datetime.now().year, datetime.now().month, 1)
    monthly_matches = logs_query.filter(
        AutoMatchLog.created_at >= this_month_start,
        AutoMatchLog.result == "matched"
    ).count()
    
    # Gesamtanzahl Charges im aktuellen Monat
    today = date.today()
    monthly_bill_run = db.query(BillRun).filter(
        BillRun.owner_id == current_user.id,
        BillRun.period_month == today.month,
        BillRun.period_year == today.year
    ).first()
    
    monthly_total_charges = 0
    if monthly_bill_run:
        monthly_total_charges = db.query(Charge).filter(
            Charge.bill_run_id == monthly_bill_run.id
        ).count()
    
    return {
        "period_days": days,
        "total_attempts": total_attempts,
        "matched": matched,
        "no_match": no_match,
        "multiple_candidates": multiple_candidates,
        "skipped": skipped,
        "success_rate": success_rate,
        "avg_confidence_score": round(avg_confidence, 1),
        "this_month": {
            "auto_matched": monthly_matches,
            "total_charges": monthly_total_charges,
            "coverage_rate": int((monthly_matches / monthly_total_charges * 100) if monthly_total_charges > 0 else 0)
        }
    }


@router.get("/reports")
def get_reports_data(
    start_date: Optional[str] = Query(None, description="Startdatum (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Enddatum (YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole Berichtsdaten für einen Datumsbereich
    
    Inkludiert:
    - Einnahmen (Mieteinnahmen, Nebenkosten) für den Zeitraum
    - Ausgaben (Betriebskosten, Instandhaltung) für den Zeitraum
    - Überschuss
    """
    from ..models.lease import Lease, LeaseComponent, LeaseStatus
    from ..models.accounting import Accounting, AccountingItem
    
    # Parse Datumsbereich
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            start = date.today().replace(month=1, day=1)
    else:
        start = date.today().replace(month=1, day=1)
    
    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            end = date.today()
    else:
        end = date.today()
    
    # ===== EINNAHMEN =====
    # Berechne alle Monate im Zeitraum
    start_year = start.year
    start_month = start.month
    end_year = end.year
    end_month = end.month
    
    # Summiere Kaltmiete (cold_rent) aus LeaseComponents
    total_rent = Decimal(0)
    leases_query = db.query(Lease).filter(
        Lease.owner_id == current_user.id,
        Lease.status == LeaseStatus.ACTIVE,
        Lease.start_date <= end,
        (Lease.end_date >= start) | (Lease.end_date.is_(None))
    )
    
    if client_id:
        try:
            leases_query = leases_query.filter(Lease.client_id == client_id)
        except Exception:
            pass
    
    if fiscal_year_id:
        try:
            leases_query = leases_query.filter(Lease.fiscal_year_id == fiscal_year_id)
        except Exception:
            pass
    
    active_leases = leases_query.all()
    
    for lease in active_leases:
        # Berechne Anzahl Monate im Zeitraum
        lease_start = max(lease.start_date, start)
        lease_end = min(lease.end_date if lease.end_date else end, end)
        
        if lease_start <= lease_end:
            # Berechne Monate
            year_diff = lease_end.year - lease_start.year
            month_diff = lease_end.month - lease_start.month
            months = year_diff * 12 + month_diff + 1
            
            # Summiere Kaltmiete
            for component in lease.components:
                if component.type.value == "cold_rent":
                    total_rent += Decimal(str(component.amount)) * Decimal(months)
    
    # Nebenkosten: Summe aller Betriebskosten-Vorauszahlungen
    total_prepayments = Decimal(0)
    for lease in active_leases:
        lease_start = max(lease.start_date, start)
        lease_end = min(lease.end_date if lease.end_date else end, end)
        
        if lease_start <= lease_end:
            year_diff = lease_end.year - lease_start.year
            month_diff = lease_end.month - lease_start.month
            months = year_diff * 12 + month_diff + 1
            
            for component in lease.components:
                if component.type.value in ["operating_costs", "heating_costs"]:
                    total_prepayments += Decimal(str(component.amount)) * Decimal(months)
    
    # ===== AUSGABEN =====
    # Betriebskosten: Summe aller AccountingItems im Zeitraum
    accounting_query = db.query(Accounting).filter(
        Accounting.owner_id == current_user.id,
        Accounting.period_start <= end,
        Accounting.period_end >= start
    )
    
    if client_id:
        try:
            accounting_query = accounting_query.filter(Accounting.client_id == client_id)
        except Exception:
            pass
    
    if fiscal_year_id:
        try:
            accounting_query = accounting_query.filter(Accounting.fiscal_year_id == fiscal_year_id)
        except Exception:
            pass
    
    accountings = accounting_query.all()
    
    total_operating_costs = Decimal(0)
    total_maintenance = Decimal(0)
    
    for accounting in accountings:
        # Hole alle AccountingItems
        items = db.query(AccountingItem).filter(
            AccountingItem.accounting_id == accounting.id
        ).all()
        
        for item in items:
            if item.is_allocable:
                # Betriebskosten (umlagefähig)
                if "heizung" in item.cost_type.lower() or "heating" in item.cost_type.lower():
                    total_operating_costs += Decimal(str(item.amount))
                elif "instandhaltung" in item.cost_type.lower() or "maintenance" in item.cost_type.lower():
                    total_maintenance += Decimal(str(item.amount))
                else:
                    # Andere Betriebskosten
                    total_operating_costs += Decimal(str(item.amount))
    
    # Gesamtausgaben
    total_expenses = total_operating_costs + total_maintenance
    
    # Überschuss
    total_income = total_rent + total_prepayments
    surplus = total_income - total_expenses
    
    return {
        "income": {
            "rent": float(total_rent),
            "prepayments": float(total_prepayments),
            "total": float(total_income)
        },
        "expenses": {
            "operating_costs": float(total_operating_costs),
            "maintenance": float(total_maintenance),
            "total": float(total_expenses)
        },
        "surplus": float(surplus),
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        # Für Kompatibilität mit Frontend
        "total_rent": float(total_rent),
        "total_prepayments": float(total_prepayments)
    }

