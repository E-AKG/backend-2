from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
from ..db import get_db
from ..models.user import User
from ..models.accounting import Accounting, AccountingItem, UnitSettlement, AccountingType, AccountingStatus
from ..models.lease import Lease, LeaseStatus
from ..models.unit import Unit
from ..models.tenant import Tenant
from ..models.property import Property
from ..models.billrun import Charge
from ..models.meter import Meter, MeterReading
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict
import logging

logger = logging.getLogger(__name__)
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
    model_config = ConfigDict(from_attributes=True)
    
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
    created_at: datetime
    updated_at: datetime


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
        **accounting_data.model_dump()
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


@router.delete("/{accounting_id}", status_code=204)
def delete_accounting(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Abrechnung löschen"""
    from sqlalchemy.exc import SQLAlchemyError
    import logging
    
    logger = logging.getLogger(__name__)
    
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    # Prüfe ob Abrechnung bereits generiert/versendet wurde
    if accounting.status in [AccountingStatus.GENERATED, AccountingStatus.SENT, AccountingStatus.CLOSED]:
        raise HTTPException(
            status_code=400,
            detail=f"Abrechnung mit Status '{accounting.status.value}' kann nicht gelöscht werden. Nur Entwürfe und berechnete Abrechnungen können gelöscht werden."
        )
    
    try:
        # Lösche zugehörige PDF-Datei falls vorhanden
        if accounting.document_path:
            from pathlib import Path
            pdf_path = Path(accounting.document_path)
            if pdf_path.exists():
                try:
                    pdf_path.unlink()
                    logger.info(f"✅ PDF-Datei gelöscht: {pdf_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Konnte PDF-Datei nicht löschen: {str(e)}")
        
        # Lösche Abrechnung (CASCADE löscht automatisch Items und Settlements)
        db.delete(accounting)
        db.commit()
        
        logger.info(f"✅ Abrechnung {accounting_id} gelöscht")
        return None
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Löschen der Abrechnung: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Löschen der Abrechnung")


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
        **item_data.model_dump()
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
    
    # Hole alle aktiven Verträge im Zeitraum - NUR für diesen Mandant
    active_leases_query = db.query(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        Lease.status == LeaseStatus.ACTIVE,
        Lease.start_date <= accounting.period_end,
        (Lease.end_date.is_(None) | (Lease.end_date >= accounting.period_start))
    )
    
    # Filter nach client_id der Abrechnung
    if accounting.client_id:
        try:
            # Filter über Lease.client_id ODER Property.client_id
            active_leases_query = active_leases_query.filter(
                (Lease.client_id == accounting.client_id) | (Property.client_id == accounting.client_id)
            )
        except Exception:
            logger.warning(f"client_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
    
    # Filter nach fiscal_year_id der Abrechnung
    if accounting.fiscal_year_id:
        try:
            active_leases_query = active_leases_query.filter(Lease.fiscal_year_id == accounting.fiscal_year_id)
        except Exception:
            logger.warning(f"fiscal_year_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
    
    active_leases = active_leases_query.all()
    
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
        
        # Berechne tatsächliche Anzahl Monate im Abrechnungszeitraum
        period_start = accounting.period_start
        period_end = accounting.period_end
        
        # Berechne Monate zwischen Start und Ende (inklusive)
        if period_start and period_end:
            # Berechne Differenz in Monaten
            year_diff = period_end.year - period_start.year
            month_diff = period_end.month - period_start.month
            months_in_period = year_diff * 12 + month_diff + 1  # +1 weil beide Monate inklusive sind
            
            # Prüfe ob Vertrag im Zeitraum aktiv war
            lease_start = max(lease.start_date, period_start)
            lease_end = min(lease.end_date if lease.end_date else period_end, period_end)
            
            # Berechne tatsächliche Monate, die der Vertrag im Abrechnungszeitraum aktiv war
            if lease_start <= lease_end:
                year_diff_actual = lease_end.year - lease_start.year
                month_diff_actual = lease_end.month - lease_start.month
                actual_months = year_diff_actual * 12 + month_diff_actual + 1
            else:
                actual_months = 0
        else:
            months_in_period = 12  # Fallback
            actual_months = 12
        
        for component in lease.components:
            if component.type.value in ["operating_costs", "heating_costs"]:
                # Berechne Vorauszahlungen für den tatsächlichen Zeitraum
                advance_payments += Decimal(str(component.amount)) * Decimal(actual_months)
        
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
    template_name: Optional[str] = Query(None, description="Name des benutzerdefinierten Templates (optional)"),
    generate_all_settlements: bool = Query(True, description="Generiere auch PDFs für alle Einzelabrechnungen"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generiere PDF-Dokumente für Abrechnung aus HTML-Template
    
    Generiert:
    - Gesamtabrechnung (Übersicht aller Kosten und Verteilung)
    - Optional: Einzelabrechnungen für jeden Mieter
    
    Template-Platzhalter (Gesamtabrechnung):
    - {{ accounting_type }}, {{ accounting_type_label }}, {{ period_start }}, {{ period_end }}
    - {{ total_costs }}, {{ total_costs_formatted }}, {{ total_advance_payments }}, {{ total_settlement }}
    - {{ items }} (Liste aller Kostenposten)
    - {{ settlements }} (Liste aller Einzelabrechnungen)
    - {{ client.name }}, {{ client.address }}, {{ client.email }}, {{ client.phone }}
    - {{ notes }}
    
    Template-Platzhalter (Einzelabrechnung):
    - {{ tenant.full_name }}, {{ tenant.address }}
    - {{ property.name }}, {{ unit.label }}, {{ unit.size_sqm }}
    - {{ advance_payments }}, {{ allocated_costs }}, {{ settlement_amount }}
    - {{ items }} (Kostenposten für diesen Mieter)
    - {{ client.name }}, {{ client.address }}
    """
    from sqlalchemy.orm import joinedload
    from ..utils.pdf_generator import generate_accounting_pdf, generate_settlement_pdf, load_custom_template
    import logging
    
    logger = logging.getLogger(__name__)
    
    accounting = db.query(Accounting).options(
        joinedload(Accounting.items),
        joinedload(Accounting.unit_settlements).joinedload(UnitSettlement.tenant),
        joinedload(Accounting.unit_settlements).joinedload(UnitSettlement.unit).joinedload(Unit.property)
    ).filter(
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
    
    # Lade Client-Daten (falls vorhanden, sonst verwende User-Daten)
    client_name = current_user.email  # Fallback auf User-Email
    client_address = ""
    client_email = current_user.email
    client_phone = ""
    
    if hasattr(accounting, 'client_id') and accounting.client_id:
        from ..models.client import Client
        client = db.query(Client).filter(Client.id == accounting.client_id).first()
        if client:
            client_name = client.name or current_user.email
            client_address = client.address or ""
            client_email = client.email or current_user.email
            client_phone = client.phone or ""
    
    # Bereite Daten für Gesamtabrechnung vor
    items_data = []
    for item in accounting.items:
        items_data.append({
            "cost_type": item.cost_type,
            "description": item.description,
            "amount": float(item.amount),
            "is_allocable": item.is_allocable,
        })
    
    settlements_data = []
    for settlement in accounting.unit_settlements:
        settlements_data.append({
            "id": settlement.id,
            "tenant_name": f"{settlement.tenant.first_name} {settlement.tenant.last_name}" if settlement.tenant else "",
            "unit_label": settlement.unit.unit_label if settlement.unit else "",
            "advance_payments": float(settlement.advance_payments),
            "allocated_costs": float(settlement.allocated_costs),
            "settlement_amount": float(settlement.settlement_amount),
        })
    
    accounting_data = {
        "accounting_id": accounting.id,
        "accounting_type": accounting.accounting_type.value,
        "period_start": accounting.period_start,
        "period_end": accounting.period_end,
        "total_costs": float(accounting.total_costs),
        "total_advance_payments": float(accounting.total_advance_payments),
        "total_settlement": float(accounting.total_settlement),
        "items": items_data,
        "settlements": settlements_data,
        "client": {
            "name": client_name,
            "address": client_address,
            "email": client_email,
            "phone": client_phone,
        },
        "notes": accounting.notes or "",
    }
    
    # Lade Template (benutzerdefiniert oder Standard)
    template_content = None
    if template_name:
        template_content = load_custom_template(template_name)
        if not template_content:
            raise HTTPException(
                status_code=404,
                detail=f"Template '{template_name}' nicht gefunden."
            )
    
    try:
        # Generiere Gesamtabrechnung-PDF
        output_filename = f"accounting_{accounting_id}.pdf"
        pdf_path = generate_accounting_pdf(
            accounting_data=accounting_data,
            template_content=template_content,
            output_filename=output_filename
        )
        
        # Speichere absoluten Pfad in der Datenbank
        from pathlib import Path
        pdf_path_absolute = str(Path(pdf_path).absolute())
        
        # Generiere Einzelabrechnungen (optional)
        settlement_paths = []
        if generate_all_settlements:
            for settlement in accounting.unit_settlements:
                # Bereite Daten für Einzelabrechnung vor
                settlement_items = items_data  # Alle Items für diese Abrechnung
                
                settlement_data = {
                    "settlement_id": settlement.id,
                    "accounting_id": accounting.id,
                    "period_start": accounting.period_start,
                    "period_end": accounting.period_end,
                    "advance_payments": float(settlement.advance_payments),
                    "allocated_costs": float(settlement.allocated_costs),
                    "settlement_amount": float(settlement.settlement_amount),
                    "tenant": {
                        "first_name": settlement.tenant.first_name if settlement.tenant else "",
                        "last_name": settlement.tenant.last_name if settlement.tenant else "",
                        "address": settlement.tenant.address or "" if settlement.tenant else "",
                    },
                    "property": {
                        "name": settlement.unit.property.name if settlement.unit and settlement.unit.property else "",
                        "address": settlement.unit.property.address or "" if settlement.unit and settlement.unit.property else "",
                    },
                    "unit": {
                        "label": settlement.unit.unit_label if settlement.unit else "",
                        "unit_number": settlement.unit.unit_number or "" if settlement.unit else "",
                        "size_sqm": float(settlement.unit.size_sqm) if settlement.unit and settlement.unit.size_sqm else 0,
                    },
                    "items": settlement_items,
                    "client": accounting_data["client"],
                }
                
                tenant_name = settlement.tenant.last_name if settlement.tenant else "unknown"
                settlement_filename = f"settlement_{settlement.id}_{tenant_name}.pdf"
                settlement_pdf_path = generate_settlement_pdf(
                    settlement_data=settlement_data,
                    template_content=None,  # Verwende Standard-Template für Einzelabrechnungen
                    output_filename=settlement_filename
                )
                settlement_paths.append(settlement_pdf_path)
                
                # Speichere Pfad in UnitSettlement
                settlement.document_path = settlement_pdf_path
        
        # Aktualisiere Abrechnung
        accounting.status = AccountingStatus.GENERATED
        accounting.generated_at = date.today()
        accounting.document_path = pdf_path_absolute  # Speichere absoluten Pfad
        
        db.commit()
        
        return {
            "status": "generated",
            "document_path": pdf_path,
            "settlement_paths": settlement_paths,
            "generated_at": accounting.generated_at.isoformat(),
            "message": f"PDF erfolgreich generiert. Gesamtabrechnung + {len(settlement_paths)} Einzelabrechnungen."
        }
    except Exception as e:
        logger.error(f"Fehler beim Generieren der Abrechnungs-PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Generieren der PDF: {str(e)}"
        )


@router.get("/{accounting_id}/download-pdf")
def download_accounting_pdf(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lade Abrechnungs-PDF herunter
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    from ..utils.pdf_generator import PDF_OUTPUT_DIR
    import logging
    
    logger = logging.getLogger(__name__)
    
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    if not accounting.document_path:
        raise HTTPException(
            status_code=400,
            detail="PDF wurde noch nicht generiert. Bitte generieren Sie zuerst die PDF."
        )
    
    # Pfad auflösen: Wenn relativ, dann relativ zu PDF_OUTPUT_DIR
    document_path = accounting.document_path
    if Path(document_path).is_absolute():
        pdf_path = Path(document_path)
    else:
        # Relativer Pfad: Versuche zuerst direkt, dann relativ zu PDF_OUTPUT_DIR
        pdf_path = Path(document_path)
        if not pdf_path.exists():
            pdf_path = PDF_OUTPUT_DIR / Path(document_path).name
    
    logger.info(f"Suche PDF unter: {pdf_path} (absolut: {pdf_path.is_absolute()})")
    logger.info(f"PDF_OUTPUT_DIR: {PDF_OUTPUT_DIR}")
    
    if not pdf_path.exists():
        # Versuche auch mit vollem Pfad aus PDF_OUTPUT_DIR
        pdf_path_alt = PDF_OUTPUT_DIR / Path(document_path).name
        logger.info(f"Alternativer Pfad: {pdf_path_alt}")
        if pdf_path_alt.exists():
            pdf_path = pdf_path_alt
        else:
            raise HTTPException(
                status_code=404,
                detail=f"PDF-Datei nicht gefunden. Gesucht unter: {pdf_path} und {pdf_path_alt}. Bitte generieren Sie die PDF erneut."
            )
    
    logger.info(f"✅ PDF gefunden: {pdf_path}")
    
    return FileResponse(
        path=str(pdf_path),
        filename=f"accounting_{accounting_id}.pdf",
        media_type="application/pdf"
    )


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


@router.delete("/{accounting_id}/items/{item_id}", status_code=204)
def delete_accounting_item(
    accounting_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kostenposten löschen"""
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    item = db.query(AccountingItem).filter(
        AccountingItem.id == item_id,
        AccountingItem.accounting_id == accounting_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Kostenposten nicht gefunden")
    
    # Aktualisiere Gesamtkosten
    accounting.total_costs -= Decimal(str(item.amount))
    
    db.delete(item)
    db.commit()
    
    return None


@router.get("/{accounting_id}/meter-check")
def check_meter_readings(
    accounting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Prüfe Zählerstände für Abrechnung
    Zeigt alle Zähler mit fehlenden oder veralteten Ablesungen
    """
    accounting = db.query(Accounting).filter(
        Accounting.id == accounting_id,
        Accounting.owner_id == current_user.id
    ).first()
    
    if not accounting:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    
    # Hole alle aktiven Verträge im Zeitraum
    active_leases = db.query(Lease).join(Unit).join(Property).filter(
        # TODO: Add Property.client_id filter after migration
        # Property.client_id == accounting.client_id,
        Lease.status == LeaseStatus.ACTIVE,
        Lease.start_date <= accounting.period_end,
        (Lease.end_date.is_(None) | (Lease.end_date >= accounting.period_start))
    ).all()
    
    # Hole alle Zähler für diese Einheiten/Objekte
    unit_ids = [lease.unit_id for lease in active_leases if lease.unit_id]
    property_ids = list(set([lease.unit.property_id for lease in active_leases if lease.unit and lease.unit.property_id]))
    
    meters = db.query(Meter).filter(
        Meter.client_id == accounting.client_id,
        (
            (Meter.unit_id.in_(unit_ids)) |
            (Meter.property_id.in_(property_ids))
        )
    ).all()
    
    meter_status = []
    for meter in meters:
        # Prüfe ob Ablesung für Abrechnungszeitraum existiert
        reading = db.query(MeterReading).filter(
            MeterReading.meter_id == meter.id,
            MeterReading.reading_date >= accounting.period_start,
            MeterReading.reading_date <= accounting.period_end
        ).order_by(MeterReading.reading_date.desc()).first()
        
        # Prüfe letzte Ablesung vor dem Zeitraum
        previous_reading = db.query(MeterReading).filter(
            MeterReading.meter_id == meter.id,
            MeterReading.reading_date < accounting.period_start
        ).order_by(MeterReading.reading_date.desc()).first()
        
        meter_status.append({
            "meter_id": meter.id,
            "meter_number": meter.meter_number,
            "meter_type": meter.meter_type.value,
            "location": meter.location,
            "unit_label": meter.unit.unit_label if meter.unit else None,
            "property_name": meter.property.name if meter.property else None,
            "has_reading": reading is not None,
            "reading_value": reading.reading_value if reading else None,
            "reading_date": reading.reading_date.isoformat() if reading else None,
            "previous_reading_value": previous_reading.reading_value if previous_reading else None,
            "previous_reading_date": previous_reading.reading_date.isoformat() if previous_reading else None,
            "needs_reading": reading is None,
        })
    
    return {
        "accounting_id": accounting_id,
        "period_start": accounting.period_start.isoformat(),
        "period_end": accounting.period_end.isoformat(),
        "meters": meter_status,
        "total_meters": len(meters),
        "meters_with_readings": len([m for m in meter_status if m["has_reading"]]),
        "meters_needing_readings": len([m for m in meter_status if m["needs_reading"]])
    }

