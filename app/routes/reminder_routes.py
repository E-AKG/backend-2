from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import date, timedelta, datetime
from ..db import get_db
from ..models.user import User
from ..models.reminder import Reminder, ReminderType, ReminderStatus
from ..models.billrun import Charge, ChargeStatus
from ..models.tenant import Tenant
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reminders", tags=["Reminders"])


class ReminderCreate(BaseModel):
    charge_id: str
    reminder_type: ReminderType
    reminder_fee: Optional[float] = 0.0
    due_date: Optional[date] = None
    notes: Optional[str] = None


class ReminderUpdate(BaseModel):
    status: Optional[ReminderStatus] = None
    document_path: Optional[str] = None
    document_sent_at: Optional[date] = None
    notes: Optional[str] = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    charge_id: str
    tenant_id: str
    reminder_type: str
    status: str
    amount: float
    reminder_fee: float
    reminder_date: date
    due_date: Optional[date]
    document_path: Optional[str]
    document_sent_at: Optional[date]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=List[ReminderResponse])
def list_reminders(
    tenant_id: Optional[str] = Query(None),
    charge_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[ReminderStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Mahnungen"""
    query = db.query(Reminder).filter(Reminder.owner_id == current_user.id)
    
    if tenant_id:
        query = query.filter(Reminder.tenant_id == tenant_id)
    if charge_id:
        query = query.filter(Reminder.charge_id == charge_id)
    if client_id:
        query = query.filter(Reminder.client_id == client_id)
    if status:
        query = query.filter(Reminder.status == status)
    
    reminders = query.order_by(Reminder.reminder_date.desc()).all()
    return [ReminderResponse.model_validate(r) for r in reminders]


@router.post("", response_model=ReminderResponse, status_code=201)
def create_reminder(
    reminder_data: ReminderCreate,
    client_id: str = Query(..., description="Mandant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neue Mahnung erstellen"""
    # Prüfe Charge existiert und gehört zum User
    charge = db.query(Charge).join(Tenant).filter(
        Charge.id == reminder_data.charge_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not charge:
        raise HTTPException(status_code=404, detail="Sollbuchung nicht gefunden")
    
    # Prüfe ob bereits eine Mahnung dieses Typs existiert
    existing = db.query(Reminder).filter(
        Reminder.charge_id == reminder_data.charge_id,
        Reminder.reminder_type == reminder_data.reminder_type,
        Reminder.status != ReminderStatus.CANCELLED
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Eine Mahnung vom Typ {reminder_data.reminder_type.value} existiert bereits für diese Sollbuchung"
        )
    
    # Berechne offenen Betrag
    open_amount = float(charge.amount - charge.paid_amount)
    
    reminder = Reminder(
        owner_id=current_user.id,
        client_id=client_id,
        charge_id=reminder_data.charge_id,
        tenant_id=charge.lease.tenant_id,
        reminder_type=reminder_data.reminder_type,
        amount=open_amount,
        reminder_fee=reminder_data.reminder_fee or 0.0,
        reminder_date=date.today(),
        due_date=reminder_data.due_date,
        notes=reminder_data.notes
    )
    
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    
    return ReminderResponse.model_validate(reminder)


@router.post("/bulk-create")
def bulk_create_reminders(
    reminder_type: ReminderType,
    client_id: str = Query(..., description="Mandant ID"),
    days_overdue: int = Query(14, description="Mindestanzahl Tage überfällig"),
    reminder_fee: float = Query(0.0, description="Mahngebühr"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mahnlauf starten: Erstellt Mahnungen für alle säumigen Mieter
    """
    from ..models.lease import Lease
    from ..models.unit import Unit
    from ..models.property import Property
    
    from datetime import timedelta
    import logging
    
    logger = logging.getLogger(__name__)
    
    cutoff_date = date.today() - timedelta(days=days_overdue)
    
    logger.info(f"🔍 Mahnlauf gestartet: Suche nach überfälligen Charges (mindestens {days_overdue} Tage überfällig, Fälligkeitsdatum vor {cutoff_date})")
    
    # Finde alle überfälligen Charges
    overdue_charges = db.query(Charge).join(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        # TODO: Add Property.client_id filter after migration
        # Property.client_id == client_id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]),
        Charge.due_date < cutoff_date
    ).all()
    
    logger.info(f"📋 Gefunden: {len(overdue_charges)} überfällige Charges")
    
    # Debug: Zeige Details der gefundenen Charges
    for charge in overdue_charges:
        days_overdue_count = (date.today() - charge.due_date).days
        logger.info(f"   - Charge {charge.id}: {days_overdue_count} Tage überfällig, Status: {charge.status}, Betrag: {charge.amount}€, Bezahlt: {charge.paid_amount}€")
    
    created = []
    skipped = []
    reasons_skipped = {}
    
    for charge in overdue_charges:
        # Prüfe ob bereits eine Mahnung dieses Typs existiert
        existing = db.query(Reminder).filter(
            Reminder.charge_id == charge.id,
            Reminder.reminder_type == reminder_type,
            Reminder.status != ReminderStatus.CANCELLED
        ).first()
        
        if existing:
            reason = "Mahnung dieses Typs existiert bereits"
            skipped.append({
                "charge_id": charge.id,
                "reason": reason
            })
            if reason not in reasons_skipped:
                reasons_skipped[reason] = 0
            reasons_skipped[reason] += 1
            logger.info(f"   ⏭️ Charge {charge.id}: Übersprungen - {reason}")
            continue
        
        open_amount = float(charge.amount - charge.paid_amount)
        
        # Prüfe ob noch offener Betrag vorhanden ist
        if open_amount <= 0:
            reason = "Charge bereits vollständig bezahlt"
            skipped.append({
                "charge_id": charge.id,
                "reason": reason
            })
            if reason not in reasons_skipped:
                reasons_skipped[reason] = 0
            reasons_skipped[reason] += 1
            logger.info(f"   ⏭️ Charge {charge.id}: Übersprungen - {reason}")
            continue
        
        reminder = Reminder(
            owner_id=current_user.id,
            client_id=client_id,
            charge_id=charge.id,
            tenant_id=charge.lease.tenant_id,
            reminder_type=reminder_type,
            amount=open_amount,
            reminder_fee=reminder_fee,
            reminder_date=date.today(),
            notes=f"Automatisch erstellt für säumigen Mieter"
        )
        
        db.add(reminder)
        created.append({
            "charge_id": charge.id,
            "tenant_id": charge.lease.tenant_id,
            "amount": open_amount
        })
        logger.info(f"   ✅ Mahnung erstellt für Charge {charge.id}: {open_amount}€")
    
    db.commit()
    
    logger.info(f"✅ Mahnlauf abgeschlossen: {len(created)} erstellt, {len(skipped)} übersprungen")
    
    # Erstelle detaillierte Antwort mit Gründen
    response = {
        "created": len(created),
        "skipped": len(skipped),
        "total_found": len(overdue_charges),
        "details": {
            "created": created,
            "skipped": skipped,
            "reasons_skipped": reasons_skipped
        }
    }
    
    # Wenn keine Mahnungen erstellt wurden, füge hilfreiche Info hinzu
    if len(created) == 0:
        if len(overdue_charges) == 0:
            response["message"] = f"Keine überfälligen Zahlungen gefunden (Filter: mindestens {days_overdue} Tage überfällig, Fälligkeitsdatum vor {cutoff_date})"
        else:
            response["message"] = f"{len(overdue_charges)} überfällige Zahlungen gefunden, aber alle wurden übersprungen. Gründe: {', '.join(reasons_skipped.keys())}"
    
    return response


@router.put("/{reminder_id}", response_model=ReminderResponse)
def update_reminder(
    reminder_id: str,
    reminder_data: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mahnung aktualisieren"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.owner_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Mahnung nicht gefunden")
    
    update_data = reminder_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(reminder, key, value)
    
    db.commit()
    db.refresh(reminder)
    
    return ReminderResponse.model_validate(reminder)


@router.get("/{reminder_id}", response_model=ReminderResponse)
def get_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelne Mahnung abrufen"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.owner_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Mahnung nicht gefunden")
    
    return reminder


@router.delete("/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mahnung löschen"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.owner_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Mahnung nicht gefunden")
    
    db.delete(reminder)
    db.commit()
    
    return None


@router.post("/{reminder_id}/generate-pdf")
def generate_reminder_pdf(
    reminder_id: str,
    template_name: Optional[str] = Query(None, description="Name des benutzerdefinierten Templates (optional)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generiere PDF für Mahnung aus HTML-Template
    
    Template-Platzhalter:
    - {{ tenant.first_name }}, {{ tenant.last_name }}, {{ tenant.full_name }}, {{ tenant.address }}, {{ tenant.email }}, {{ tenant.phone }}
    - {{ property.name }}, {{ property.address }}
    - {{ unit.label }}, {{ unit.unit_number }}
    - {{ charge.amount }}, {{ charge.amount_formatted }}, {{ charge.paid_amount }}, {{ charge.paid_amount_formatted }}, {{ charge.due_date }}, {{ charge.description }}
    - {{ amount }}, {{ amount_formatted }}, {{ reminder_fee }}, {{ reminder_fee_formatted }}, {{ total_amount }}, {{ total_amount_formatted }}
    - {{ reminder_type }}, {{ reminder_type_label }}, {{ reminder_date }}, {{ reminder_id }}
    - {{ client.name }}, {{ client.address }}, {{ client.email }}, {{ client.phone }}
    - {{ owner.name }}, {{ owner.email }}
    - {{ notes }}
    - Helper: {{ format_currency(123.45) }}, {{ format_date(date_object) }}
    """
    from ..models.lease import Lease
    from ..models.unit import Unit
    from ..models.property import Property
    from ..models.client import Client
    
    reminder = db.query(Reminder).options(
        joinedload(Reminder.charge).joinedload(Charge.lease).joinedload(Lease.tenant),
        joinedload(Reminder.charge).joinedload(Charge.lease).joinedload(Lease.unit).joinedload(Unit.property),
        joinedload(Reminder.client),
        joinedload(Reminder.owner)
    ).filter(
        Reminder.id == reminder_id,
        Reminder.owner_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Mahnung nicht gefunden")
    
    # Lade alle benötigten Daten
    charge = reminder.charge
    lease = charge.lease if charge else None
    tenant = reminder.tenant
    unit = lease.unit if lease else None
    property_obj = unit.property if unit else None
    client = reminder.client
    owner = reminder.owner
    
    # Bereite Daten für Template vor
    reminder_data = {
        "reminder_id": reminder.id,
        "reminder_type": reminder.reminder_type.value,
        "reminder_date": reminder.reminder_date,
        "amount": float(reminder.amount),
        "reminder_fee": float(reminder.reminder_fee),
        "notes": reminder.notes,
        "tenant": {
            "first_name": tenant.first_name if tenant else "",
            "last_name": tenant.last_name if tenant else "",
            "address": tenant.address if tenant else "",
            "email": tenant.email if tenant else "",
            "phone": tenant.phone if tenant else "",
        },
        "property": {
            "name": property_obj.name if property_obj else "",
            "address": property_obj.address if property_obj else "",
        },
        "unit": {
            "label": unit.unit_label if unit else "",
            "unit_number": unit.unit_number if unit else "",
        },
        "charge": {
            "amount": float(charge.amount) if charge else 0,
            "paid_amount": float(charge.paid_amount) if charge else 0,
            "due_date": charge.due_date if charge else None,
            "description": f"Miete {charge.due_date.strftime('%m/%Y')}" if charge and charge.due_date else "",
        },
        "client": {
            "name": client.name if client else "",
            "address": client.address if client else "",
            "email": client.email if client else "",
            "phone": client.phone if client else "",
        },
        "owner": {
            "name": f"{owner.first_name} {owner.last_name}".strip() if owner else "",
            "email": owner.email if owner else "",
        },
    }
    
    # Lade Template (benutzerdefiniert oder Standard)
    from ..utils.pdf_generator import generate_reminder_pdf, load_custom_template
    
    template_content = None
    if template_name:
        template_content = load_custom_template(template_name)
        if not template_content:
            raise HTTPException(
                status_code=404,
                detail=f"Template '{template_name}' nicht gefunden. Bitte laden Sie es zuerst hoch."
            )
    
    # Generiere PDF
    try:
        output_filename = f"reminder_{reminder_id}.pdf"
        pdf_path = generate_reminder_pdf(
            reminder_data=reminder_data,
            template_content=template_content,
            output_filename=output_filename
        )
        
        # Speichere Pfad in Datenbank
        reminder.document_path = pdf_path
        reminder.status = ReminderStatus.DRAFT  # Bleibt Entwurf bis versendet
        
        db.commit()
        
        return {
            "status": "generated",
            "document_path": pdf_path,
            "reminder_id": reminder_id,
            "message": "PDF erfolgreich generiert"
        }
    except Exception as e:
        logger.error(f"Fehler beim Generieren der PDF: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Generieren der PDF: {str(e)}"
        )


@router.post("/{reminder_id}/mark-sent")
def mark_reminder_sent(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mahnung als versendet markieren"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.owner_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Mahnung nicht gefunden")
    
    reminder.status = ReminderStatus.SENT
    reminder.document_sent_at = date.today()
    
    db.commit()
    db.refresh(reminder)
    
    return ReminderResponse.model_validate(reminder)


@router.post("/upload-template")
def upload_reminder_template(
    template_name: str = Query(..., description="Name der Template-Datei (z.B. 'mein_template.html')"),
    template_content: str = Query(..., description="HTML-Template-Inhalt"),
    current_user: User = Depends(get_current_user),
):
    """
    Lade ein benutzerdefiniertes HTML-Template hoch
    
    Das Template wird in backend-2/templates/ gespeichert und kann dann
    beim Generieren von PDFs verwendet werden.
    """
    from pathlib import Path
    from ..utils.pdf_generator import TEMPLATE_DIR
    
    # Validiere Template-Name
    if not template_name.endswith('.html'):
        template_name += '.html'
    
    # Speichere Template
    template_path = TEMPLATE_DIR / template_name
    
    try:
        with open(template_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        logger.info(f"✅ Template gespeichert: {template_path}")
        
        return {
            "status": "success",
            "message": f"Template '{template_name}' erfolgreich hochgeladen",
            "template_name": template_name,
            "template_path": str(template_path)
        }
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern des Templates: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Speichern des Templates: {str(e)}"
        )


@router.get("/templates")
def list_reminder_templates(
    current_user: User = Depends(get_current_user),
):
    """
    Liste alle verfügbaren Templates auf
    """
    from pathlib import Path
    from ..utils.pdf_generator import TEMPLATE_DIR
    
    templates = []
    
    if TEMPLATE_DIR.exists():
        for template_file in TEMPLATE_DIR.glob("*.html"):
            templates.append({
                "name": template_file.name,
                "path": str(template_file),
                "size": template_file.stat().st_size,
                "modified": template_file.stat().st_mtime
            })
    
    return {
        "templates": templates,
        "count": len(templates)
    }


@router.post("/test-pdf")
def test_generate_pdf(
    template_name: Optional[str] = Query(None, description="Name des Templates (optional, Standard wird verwendet)"),
    client_id: Optional[str] = Query(None, description="Mandant ID (optional, verwendet ersten verfügbaren)"),
    charge_id: Optional[str] = Query(None, description="Charge ID (optional, verwendet erste offene Charge)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generiere eine Test-PDF mit echten Daten aus dem Tool zum Testen des Templates
    
    Verwendet 100% echte Daten aus der Datenbank:
    - Echte offene Charge (Sollbuchung) mit echten Beträgen
    - Echter Mandant (Client)
    - Echter Mieter (Tenant) aus der Charge
    - Echtes Objekt (Property) und Einheit (Unit) aus dem Vertrag
    - Echte Fälligkeitsdaten, Beträge, etc.
    """
    from datetime import date
    from sqlalchemy.orm import joinedload
    from ..utils.pdf_generator import generate_reminder_pdf, load_custom_template
    from ..models.client import Client
    from ..models.billrun import Charge, ChargeStatus
    from ..models.lease import Lease, LeaseStatus
    from ..models.tenant import Tenant
    from ..models.property import Property
    from ..models.unit import Unit
    
    # Hole Client (Mandant)
    if client_id:
        client = db.query(Client).filter(
            Client.id == client_id,
            Client.owner_id == current_user.id
        ).first()
    else:
        # Nimm ersten verfügbaren Client
        client = db.query(Client).filter(
            Client.owner_id == current_user.id
        ).first()
    
    if not client:
        raise HTTPException(
            status_code=404,
            detail="Kein Mandant gefunden. Bitte erstellen Sie zuerst einen Mandanten."
        )
    
    # Hole echte offene Charge (Sollbuchung)
    if charge_id:
        charge = db.query(Charge).options(
            joinedload(Charge.lease).joinedload(Lease.tenant),
            joinedload(Charge.lease).joinedload(Lease.unit).joinedload(Unit.property)
        ).filter(
            Charge.id == charge_id,
            Charge.bill_run.has(owner_id=current_user.id)
        ).first()
    else:
        # Nimm erste offene Charge mit allen Relationships
        charge = db.query(Charge).options(
            joinedload(Charge.lease).joinedload(Lease.tenant),
            joinedload(Charge.lease).joinedload(Lease.unit).joinedload(Unit.property)
        ).join(Lease).filter(
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]),
            Lease.owner_id == current_user.id
        ).order_by(Charge.due_date.desc()).first()
    
    if not charge:
        raise HTTPException(
            status_code=404,
            detail="Keine offene Sollbuchung gefunden. Bitte erstellen Sie zuerst eine Sollstellung mit offenen Posten."
        )
    
    # Hole alle benötigten Daten aus der Charge
    lease = charge.lease
    tenant = lease.tenant if lease else None
    unit = lease.unit if lease else None
    property_obj = unit.property if unit else None
    
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Kein Mieter zur Charge gefunden."
        )
    
    if not property_obj or not unit:
        raise HTTPException(
            status_code=404,
            detail="Kein Objekt oder Einheit zur Charge gefunden."
        )
    
    # Berechne offenen Betrag (echt!)
    open_amount = float(charge.amount - charge.paid_amount)
    
    # Erstelle Test-Daten mit 100% echten Werten
    test_reminder_data = {
        "reminder_id": "test-reminder-" + str(date.today().strftime('%Y%m%d')),
        "reminder_type": "first_reminder",
        "reminder_date": date.today(),  # Heutiges Datum
        "amount": open_amount,  # ECHTER offener Betrag
        "reminder_fee": 0.00,  # Keine Gebühr für Test
        "notes": "Dies ist eine Test-Mahnung zum Prüfen des Template-Designs. Bitte überweisen Sie den Betrag umgehend.",
        "tenant": {
            "first_name": tenant.first_name,
            "last_name": tenant.last_name,
            "address": tenant.address or "",
            "email": tenant.email or "",
            "phone": tenant.phone or "",
        },
        "property": {
            "name": property_obj.name,
            "address": property_obj.address or "",
        },
        "unit": {
            "label": unit.unit_label,
            "unit_number": unit.unit_number or "",
        },
        "charge": {
            "amount": float(charge.amount),  # ECHTER ursprünglicher Betrag
            "paid_amount": float(charge.paid_amount),  # ECHTER bereits bezahlter Betrag
            "due_date": charge.due_date,  # ECHTES Fälligkeitsdatum
            "description": charge.description or f"Miete {charge.due_date.strftime('%m/%Y') if charge.due_date else ''}",
        },
        "client": {
            "name": client.name,
            "address": client.address or "",
            "email": client.email or "",
            "phone": client.phone or "",
        },
        "owner": {
            "name": client.name,  # Verwende Client-Name als Owner-Name
            "email": current_user.email,
        },
    }
    
    # Lade Template (benutzerdefiniert oder Standard)
    template_content = None
    if template_name:
        template_content = load_custom_template(template_name)
        if not template_content:
            raise HTTPException(
                status_code=404,
                detail=f"Template '{template_name}' nicht gefunden. Verfügbare Templates: {', '.join([f.name for f in (Path(__file__).parent.parent.parent / 'templates').glob('*.html')])}"
            )
    
    try:
        # Generiere PDF
        output_filename = f"test_reminder_{date.today().strftime('%Y%m%d')}.pdf"
        pdf_path = generate_reminder_pdf(
            reminder_data=test_reminder_data,
            template_content=template_content,
            output_filename=output_filename
        )
        
        logger.info(f"✅ Test-PDF generiert: {pdf_path}")
        
        return {
            "status": "success",
            "message": "Test-PDF erfolgreich generiert",
            "document_path": pdf_path,
            "filename": output_filename,
            "note": "Dies ist eine Test-PDF mit Dummy-Daten. Öffnen Sie die Datei, um das Template-Design zu prüfen."
        }
    except Exception as e:
        logger.error(f"❌ Fehler beim Generieren der Test-PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Generieren der Test-PDF: {str(e)}"
        )

