from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, timedelta
from ..db import get_db
from ..models.user import User
from ..models.reminder import Reminder, ReminderType, ReminderStatus
from ..models.billrun import Charge, ChargeStatus
from ..models.tenant import Tenant
from ..utils.deps import get_current_user
from pydantic import BaseModel

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
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


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
    return reminders


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
    
    return reminder


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
    
    cutoff_date = date.today() - timedelta(days=days_overdue)
    
    # Finde alle überfälligen Charges
    overdue_charges = db.query(Charge).join(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        Property.client_id == client_id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]),
        Charge.due_date < cutoff_date
    ).all()
    
    created = []
    skipped = []
    
    for charge in overdue_charges:
        # Prüfe ob bereits eine Mahnung dieses Typs existiert
        existing = db.query(Reminder).filter(
            Reminder.charge_id == charge.id,
            Reminder.reminder_type == reminder_type,
            Reminder.status != ReminderStatus.CANCELLED
        ).first()
        
        if existing:
            skipped.append({
                "charge_id": charge.id,
                "reason": "Mahnung dieses Typs existiert bereits"
            })
            continue
        
        open_amount = float(charge.amount - charge.paid_amount)
        
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
    
    db.commit()
    
    return {
        "created": len(created),
        "skipped": len(skipped),
        "details": {
            "created": created,
            "skipped": skipped
        }
    }


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
    
    return reminder


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

