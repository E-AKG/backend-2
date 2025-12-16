"""
Portal-Routes für Mieter
Mieter können hier ihre Betriebskostenabrechnungen und Belege einsehen
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from ..db import get_db
from ..models.portal_user import PortalUser
from ..models.document import Document, DocumentType, DocumentStatus
from ..models.document_link import DocumentLink
from ..models.lease import Lease
from ..models.tenant import Tenant
from ..models.unit import Unit
from ..models.property import Property
from ..utils.portal_auth import get_current_portal_user
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, Field, field_validator
import os
import logging

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/api/portal", tags=["Portal"])


class PortalUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    unit_label: str
    address: Optional[str] = None
    
    @classmethod
    def from_unit(cls, unit):
        """Erstelle PortalUnitResponse aus Unit mit Property-Adresse"""
        address = unit.property.address if unit.property else None
        return cls(
            id=unit.id,
            unit_label=unit.unit_label,
            address=address or ""
        )


class PortalLeaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    start_date: datetime
    end_date: Optional[datetime]
    status: str
    unit: PortalUnitResponse


class PortalTenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    first_name: str
    last_name: str
    email: Optional[str]
    leases: List[PortalLeaseResponse] = []


class PortalDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: Optional[str]
    filename: str
    document_type: str
    billing_year: Optional[int]
    document_date: Optional[datetime]
    description: Optional[str]
    published_at: Optional[datetime]
    file_size: Optional[int]
    mime_type: Optional[str]


class PortalBKStatementDetailResponse(PortalDocumentResponse):
    linked_receipts: List[PortalDocumentResponse] = []


@router.get("/me", response_model=PortalTenantResponse)
def get_portal_user_info(
    current_portal_user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db)
):
    """
    Hole Informationen zum aktuell eingeloggten Mieterportal-Benutzer
    (inkl. zugehöriger Mieter, Mietverträge und Einheiten)
    """
    tenant = db.query(Tenant).options(
        joinedload(Tenant.leases).joinedload(Lease.unit).joinedload(Unit.property)
    ).filter(Tenant.id == current_portal_user.tenant_id).first()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mieter nicht gefunden")

    # Konvertiere Tenant zu Response, mit angepassten Unit-Responses die Property-Adresse enthalten
    tenant_dict = {
        "id": tenant.id,
        "first_name": tenant.first_name,
        "last_name": tenant.last_name,
        "email": tenant.email,
        "leases": []
    }
    
    for lease in tenant.leases:
        unit_address = lease.unit.property.address if lease.unit and lease.unit.property else ""
        lease_dict = {
            "id": lease.id,
            "start_date": lease.start_date,
            "end_date": lease.end_date,
            "status": lease.status.value if hasattr(lease.status, 'value') else str(lease.status),
            "unit": {
                "id": lease.unit.id,
                "unit_label": lease.unit.unit_label,
                "address": unit_address
            }
        }
        tenant_dict["leases"].append(lease_dict)
    
    return PortalTenantResponse.model_validate(tenant_dict)


@router.get("/bk", response_model=List[PortalDocumentResponse])
def list_bk_statements(
    year: Optional[int] = Query(None, description="Filter nach Abrechnungsjahr"),
    current_portal_user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db)
):
    """
    Liste aller veröffentlichten Betriebskostenabrechnungen für den Mieter
    """
    query = db.query(Document).filter(
        Document.document_type == DocumentType.BK_STATEMENT.value,
        Document.status == DocumentStatus.PUBLISHED,
        Document.tenant_id == current_portal_user.tenant_id  # Nur eigene Dokumente
    )

    if year:
        query = query.filter(Document.billing_year == year)

    statements = query.order_by(Document.billing_year.desc(), Document.published_at.desc()).all()
    return [PortalDocumentResponse.model_validate(s) for s in statements]


@router.get("/bk/{statement_id}", response_model=PortalBKStatementDetailResponse)
def get_bk_statement_details(
    statement_id: str,
    current_portal_user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db)
):
    """
    Hole Details einer Betriebskostenabrechnung inkl. verknüpfter Belege
    """
    statement = db.query(Document).options(
        joinedload(Document.linked_receipts).joinedload(DocumentLink.receipt)
    ).filter(
        Document.id == statement_id,
        Document.document_type == DocumentType.BK_STATEMENT.value,
        Document.status == DocumentStatus.PUBLISHED,
        Document.tenant_id == current_portal_user.tenant_id  # Nur eigene Dokumente
    ).first()

    if not statement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Betriebskostenabrechnung nicht gefunden oder nicht veröffentlicht")

    # Lade verknüpfte Belege
    links = db.query(DocumentLink).filter(DocumentLink.statement_id == statement_id).all()
    receipt_ids = [link.receipt_id for link in links]
    receipts = db.query(Document).filter(
        Document.id.in_(receipt_ids),
        Document.status == DocumentStatus.PUBLISHED
    ).all() if receipt_ids else []

    result = PortalBKStatementDetailResponse.model_validate(statement)
    result.linked_receipts = [PortalDocumentResponse.model_validate(r) for r in receipts]
    
    return result


@router.get("/documents/{document_id}/download")
def download_portal_document(
    document_id: str,
    current_portal_user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db)
):
    """
    Lade ein Dokument herunter (mit Sicherheitsprüfung)
    """
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.status == DocumentStatus.PUBLISHED,
        Document.tenant_id == current_portal_user.tenant_id  # Nur eigene Dokumente
    ).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden oder nicht für Sie freigegeben")

    # Sicherstellen, dass der Pfad absolut ist
    absolute_file_path = os.path.abspath(document.file_path)

    if not os.path.exists(absolute_file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datei auf dem Server nicht gefunden")

    # TODO: Implementierung einer Signed URL für S3/Cloud Storage
    # Für lokale Dateien wird direkt FileResponse verwendet
    return FileResponse(
        absolute_file_path,
        media_type=document.mime_type or "application/octet-stream",
        filename=document.filename
    )


class PasswordChangeRequest(BaseModel):
    """Schema für Passwort-Änderung"""
    current_password: str = Field(..., min_length=1, description="Aktuelles Passwort")
    new_password: str = Field(..., min_length=8, description="Neues Passwort (mindestens 8 Zeichen)")
    
    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        """Validiere neues Passwort"""
        if len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        password_bytes = len(v.encode('utf-8'))
        if password_bytes > 72:
            raise ValueError(f"Passwort darf nicht länger als 72 Bytes sein (aktuell: {password_bytes} Bytes)")
        return v


class PasswordChangeResponse(BaseModel):
    """Response für Passwort-Änderung"""
    message: str
    success: bool


@router.put("/me/password", response_model=PasswordChangeResponse)
def change_password(
    password_data: PasswordChangeRequest,
    current_portal_user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db)
):
    """
    Ändere das Passwort des Portal-Users
    
    - **current_password**: Aktuelles Passwort (zur Verifizierung)
    - **new_password**: Neues Passwort (mindestens 8 Zeichen)
    """
    try:
        # Validiere aktuelles Passwort
        if not pwd_context.verify(password_data.current_password, current_portal_user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Aktuelles Passwort ist falsch"
            )
        
        # Validiere neues Passwort
        password_bytes = len(password_data.new_password.encode('utf-8'))
        if password_bytes > 72:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passwort darf nicht länger als 72 Bytes sein"
            )
        
        # Hash neues Passwort
        new_password_hash = pwd_context.hash(password_data.new_password)
        
        # Update Passwort
        current_portal_user.password_hash = new_password_hash
        db.commit()
        
        logger.info(f"Portal-User {current_portal_user.email} hat Passwort geändert")
        
        return PasswordChangeResponse(
            message="Passwort erfolgreich geändert",
            success=True
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Ändern des Passworts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Ändern des Passworts"
        )
