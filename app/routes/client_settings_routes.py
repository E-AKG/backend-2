from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from ..db import get_db
from ..models.client_settings import ClientSettings
from ..models.client import Client
from ..utils.deps import get_current_user
from ..models.user import User
from pydantic import BaseModel
import os
import uuid
from pathlib import Path

router = APIRouter()

# Logo upload directory
LOGO_UPLOAD_DIR = Path("uploads/logos")
LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ========= Schemas =========

class ClientSettingsUpdate(BaseModel):
    default_bank_account_id: Optional[str] = None
    reminder_fees: Optional[Dict[str, float]] = None
    reminder_days: Optional[Dict[str, int]] = None
    reminder_enabled: Optional[Dict[str, bool]] = None
    text_templates: Optional[Dict[str, str]] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    company_tax_id: Optional[str] = None
    company_iban: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class ClientSettingsResponse(BaseModel):
    id: str
    client_id: str
    default_bank_account_id: Optional[str]
    reminder_fees: Dict[str, float]
    reminder_days: Dict[str, int]
    reminder_enabled: Dict[str, bool]
    text_templates: Dict[str, str]
    logo_path: Optional[str]
    company_name: Optional[str]
    company_address: Optional[str]
    company_tax_id: Optional[str]
    company_iban: Optional[str]
    settings: Dict[str, Any]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ========= Helper Functions =========

def get_or_create_settings(client_id: str, owner_id: int, db: Session) -> ClientSettings:
    """Hole oder erstelle ClientSettings"""
    settings = db.query(ClientSettings).filter(
        ClientSettings.client_id == client_id
    ).first()
    
    if not settings:
        # Erstelle Default-Settings
        default_fees = {
            "payment_reminder": 0.0,
            "first_reminder": 5.0,
            "second_reminder": 10.0,
            "final_reminder": 15.0
        }
        default_days = {
            "payment_reminder": 14,
            "first_reminder": 30,
            "second_reminder": 60,
            "final_reminder": 90
        }
        default_enabled = {
            "payment_reminder": True,
            "first_reminder": True,
            "second_reminder": True,
            "final_reminder": True
        }
        default_templates = {
            "reminder_1": "Sehr geehrte/r {tenant_name},\n\nwir möchten Sie daran erinnern, dass die Miete für {unit_label} noch aussteht.\n\nBitte überweisen Sie den Betrag von {amount} € bis zum {due_date}.\n\nMit freundlichen Grüßen",
            "reminder_2": "Sehr geehrte/r {tenant_name},\n\nleider ist die Miete für {unit_label} weiterhin nicht eingegangen.\n\nBitte überweisen Sie den Betrag von {amount} € umgehend.\n\nMit freundlichen Grüßen"
        }
        
        settings = ClientSettings(
            client_id=client_id,
            owner_id=owner_id,
            reminder_fees=default_fees,
            reminder_days=default_days,
            reminder_enabled=default_enabled,
            text_templates=default_templates,
            settings={}
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return settings


# ========= Routes =========

@router.get("/api/clients/{client_id}/settings", response_model=ClientSettingsResponse)
def get_client_settings(
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Client-Einstellungen abrufen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    settings = get_or_create_settings(client_id, current_user.id, db)
    return settings


@router.put("/api/clients/{client_id}/settings", response_model=ClientSettingsResponse)
def update_client_settings(
    client_id: str,
    settings_data: ClientSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Client-Einstellungen aktualisieren"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    settings = get_or_create_settings(client_id, current_user.id, db)
    
    update_data = settings_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            if key in ["reminder_fees", "reminder_days", "reminder_enabled", "text_templates", "settings"]:
                # Merge dictionaries
                current_value = getattr(settings, key) or {}
                if isinstance(current_value, dict) and isinstance(value, dict):
                    current_value.update(value)
                    setattr(settings, key, current_value)
                else:
                    setattr(settings, key, value)
            else:
                setattr(settings, key, value)
    
    db.commit()
    db.refresh(settings)
    
    return settings


@router.post("/api/clients/{client_id}/settings/logo", response_model=ClientSettingsResponse)
async def upload_logo(
    client_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Logo hochladen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    # Validiere Dateityp
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/svg+xml"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger Dateityp. Erlaubt: {', '.join(allowed_types)}"
        )
    
    # Generiere eindeutigen Dateinamen
    file_extension = Path(file.filename).suffix
    unique_filename = f"{client_id}_{uuid.uuid4()}{file_extension}"
    file_path = LOGO_UPLOAD_DIR / unique_filename
    
    # Speichere Datei
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {str(e)}")
    
    # Aktualisiere Settings
    settings = get_or_create_settings(client_id, current_user.id, db)
    
    # Lösche altes Logo falls vorhanden
    if settings.logo_path and os.path.exists(settings.logo_path):
        try:
            os.remove(settings.logo_path)
        except:
            pass
    
    settings.logo_path = str(file_path)
    db.commit()
    db.refresh(settings)
    
    return settings


@router.delete("/api/clients/{client_id}/settings/logo", response_model=ClientSettingsResponse)
def delete_logo(
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Logo löschen"""
    # Prüfe ob Client existiert und User gehört
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_id == current_user.id
    ).first()
    
    if not client:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    
    settings = get_or_create_settings(client_id, current_user.id, db)
    
    # Lösche Datei
    if settings.logo_path and os.path.exists(settings.logo_path):
        try:
            os.remove(settings.logo_path)
        except:
            pass
    
    settings.logo_path = None
    db.commit()
    db.refresh(settings)
    
    return settings

