"""
Admin-Routes für Mieterportal-Verwaltung
Admin kann BK-Statements und Belege hochladen, verknüpfen und veröffentlichen
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime, date
from ..db import get_db
from ..models.user import User
from ..models.document import Document, DocumentType, DocumentStatus
from ..models.document_link import DocumentLink
from ..models.portal_user import PortalUser
from ..models.lease import Lease
from ..models.tenant import Tenant
from ..utils.deps import get_current_user
from ..services.notification_service import NotificationService, NotificationType as NotifType
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr
import os
import uuid
import shutil
import secrets
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/portal", tags=["Admin Portal"])

# Password hashing für Portal-User
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def require_admin_or_staff(
    current_user: User = Depends(get_current_user)
) -> User:
    """Prüfe ob User Admin oder Staff ist"""
    # Fallback: Wenn role nicht gesetzt ist, behandle als ADMIN (für Migration-Kompatibilität)
    user_role = getattr(current_user, 'role', None) or 'admin'
    if user_role not in ['admin', 'staff']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Staff access required"
        )
    return current_user


# Storage-Verzeichnis für Dokumente
DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "documents", "portal")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)


# Schemas für Portal-User-Verwaltung
class PortalUserCreateRequest(BaseModel):
    tenant_id: str
    lease_id: Optional[str] = None
    email: EmailStr  # E-Mail-Adresse des Mieters
    send_invitation: bool = True  # Soll Einladungs-E-Mail gesendet werden?


class PortalUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    lease_id: Optional[str]
    email: str
    is_active: bool
    is_verified: bool


@router.post("/users/invite", response_model=PortalUserResponse, status_code=status.HTTP_201_CREATED)
def invite_portal_user(
    request: PortalUserCreateRequest,
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """
    Lade einen Mieter zum Portal ein (erstellt Portal-User und sendet Einladungs-E-Mail)
    
    - Erstellt Portal-User für Tenant
    - Generiert temporäres Passwort
    - Sendet Einladungs-E-Mail mit Login-Daten
    """
    # Prüfe ob Tenant existiert und dem User gehört
    tenant = db.query(Tenant).filter(
        Tenant.id == request.tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mieter nicht gefunden"
        )
    
    # Prüfe ob Portal-User bereits existiert
    existing_user = db.query(PortalUser).filter(
        PortalUser.email == request.email
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Portal-User mit E-Mail {request.email} existiert bereits"
        )
    
    # Generiere temporäres Passwort
    temp_password = secrets.token_urlsafe(12)  # 12 Zeichen, URL-safe
    password_hash = pwd_context.hash(temp_password)
    
    # Erstelle Portal-User
    portal_user = PortalUser(
        tenant_id=request.tenant_id,
        lease_id=request.lease_id,
        email=request.email,
        password_hash=password_hash,
        is_active=True,
        is_verified=True  # Beim Einladen bereits verifiziert (E-Mail wurde gesendet)
    )
    
    db.add(portal_user)
    db.flush()
    
    # Sende Einladungs-E-Mail (falls gewünscht)
    if request.send_invitation:
        notification_service = NotificationService()
        tenant_name = f"{tenant.first_name} {tenant.last_name}"
        portal_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        
        success = notification_service.send_email(
            db=db,
            to_email=request.email,
            subject="Einladung zum Mieterportal – Immpire",
            template="portal_invitation",
            data={
                "tenant_name": tenant_name,
                "email": request.email,
                "temp_password": temp_password,
                "portal_url": portal_url
            },
            recipient_id=portal_user.id,
            notification_type=NotifType.PORTAL_INVITATION,
            from_user_id=current_user.id  # Verwende Absender-E-Mail vom aktuellen User
        )
        
        if not success:
            logger.warning(f"⚠️ Einladungs-E-Mail konnte nicht gesendet werden an {request.email}")
    
    db.commit()
    db.refresh(portal_user)
    
    return PortalUserResponse.model_validate(portal_user)


@router.get("/users", response_model=List[PortalUserResponse])
def list_portal_users(
    tenant_id: Optional[str] = None,
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """
    Liste alle Portal-User (optional gefiltert nach tenant_id)
    """
    query = db.query(PortalUser).join(Tenant).filter(
        Tenant.owner_id == current_user.id
    )
    
    if tenant_id:
        query = query.filter(PortalUser.tenant_id == tenant_id)
    
    portal_users = query.all()
    return [PortalUserResponse.model_validate(pu) for pu in portal_users]


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    filename: str
    title: Optional[str]
    document_type: str
    status: str
    billing_year: Optional[int]


class LinkReceiptsRequest(BaseModel):
    statement_id: str
    receipt_ids: List[str]


@router.post("/documents/upload", response_model=List[DocumentUploadResponse], status_code=status.HTTP_201_CREATED)
def upload_document(
    files: List[UploadFile] = File(...),  # Unterstützt jetzt mehrere Dateien
    document_type: str = Form(...),  # Verwende String statt Enum für bessere Kompatibilität
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    billing_year: Optional[int] = Form(None),
    unit_id: Optional[str] = Form(None),
    tenant_ids: Optional[List[str]] = Form(None),  # Mehrere Mieter möglich
    lease_id: Optional[str] = Form(None),
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """
    Lade ein oder mehrere Dokumente hoch (BK_STATEMENT oder BK_RECEIPT)
    
    Unterstützt jetzt mehrere Dateien gleichzeitig.
    Dokumente werden als DRAFT gespeichert (nicht sichtbar für Mieter).
    
    Falls mehrere tenant_ids angegeben werden, wird für jeden tenant_id ein separates Document erstellt.
    """
    # Konvertiere String zu Enum (unterstützt sowohl "BK_STATEMENT" als auch "bk_statement")
    document_type_str = document_type.lower() if document_type else None
    
    # Mappe mögliche Eingaben zu Enum-Werten
    type_mapping = {
        "bk_statement": DocumentType.BK_STATEMENT,
        "bk_receipt": DocumentType.BK_RECEIPT,
    }
    
    if document_type_str not in type_mapping:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"document_type muss 'bk_statement' oder 'bk_receipt' sein. Erhalten: {document_type}"
        )
    
    document_type_enum = type_mapping[document_type_str]
    
    # Validiere document_type
    if document_type_enum not in [DocumentType.BK_STATEMENT, DocumentType.BK_RECEIPT]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type muss BK_STATEMENT oder BK_RECEIPT sein"
        )
    
    # Validiere billing_year für BK_STATEMENT
    if document_type_enum == DocumentType.BK_STATEMENT and not billing_year:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="billing_year ist für BK_STATEMENT erforderlich"
        )
    
    # Hole client_id aus current_user (wird vom Frontend gesetzt)
    client_id = getattr(current_user, 'selected_client_id', None)
    
    # Fallback: Hole ersten Client des Users
    if not client_id:
        from ..models.client import Client
        default_client = db.query(Client).filter(Client.owner_id == current_user.id).first()
        client_id = default_client.id if default_client else None
    
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein Mandant gefunden. Bitte erstellen Sie zuerst einen Mandanten."
        )
    
    # Konvertiere tenant_ids zu Liste (falls None oder einzelner String)
    if tenant_ids is None:
        tenant_ids = []
    elif isinstance(tenant_ids, str):
        tenant_ids = [tenant_ids]
    
    # Wenn keine tenant_ids angegeben, erstelle ein Document ohne tenant_id
    if not tenant_ids:
        tenant_ids = [None]
    
    # Erstelle für jede Datei und jeden tenant_id ein Document
    created_documents = []
    
    for file in files:
        # Speichere Datei
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(DOCUMENTS_DIR, unique_filename)
        
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Fehler beim Speichern der Datei: {str(e)}"
            )
        
        # Hole file_size
        file_size = os.path.getsize(file_path)
        
        # Erstelle für jeden tenant_id ein Document
        for tenant_id in tenant_ids:
            document = Document(
                owner_id=current_user.id,
                client_id=client_id,
                filename=file.filename,
                file_path=file_path,
                file_size=file_size,
                mime_type=file.content_type,
                document_type=document_type_enum.value,
                title=title or file.filename,
                description=description,
                billing_year=billing_year,
                unit_id=unit_id,
                tenant_id=tenant_id,
                lease_id=lease_id,
                status=DocumentStatus.DRAFT.value
            )
            
            db.add(document)
            created_documents.append(document)
    
    db.commit()
    
    # Refresh alle Documents
    for doc in created_documents:
        db.refresh(doc)
    
    return [DocumentUploadResponse.model_validate(doc) for doc in created_documents]


@router.post("/bk/{billing_year}/link-receipts", status_code=status.HTTP_200_OK)
def link_receipts_to_statement(
    billing_year: int,
    request: LinkReceiptsRequest,
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """
    Verknüpfe Belege (BK_RECEIPT) mit einem Statement (BK_STATEMENT)
    
    Args:
        billing_year: Abrechnungsjahr
        request: statement_id und receipt_ids
    """
    # Prüfe ob Statement existiert
    statement = db.query(Document).filter(
        Document.id == request.statement_id,
        Document.document_type == DocumentType.BK_STATEMENT.value,
        Document.billing_year == billing_year,
        Document.owner_id == current_user.id
    ).first()
    
    if not statement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Betriebskostenabrechnung nicht gefunden"
        )
    
    # Prüfe ob alle Receipts existieren und zu diesem User gehören
    receipts = db.query(Document).filter(
        Document.id.in_(request.receipt_ids),
        Document.document_type == DocumentType.BK_RECEIPT.value,
        Document.owner_id == current_user.id
    ).all()
    
    if len(receipts) != len(request.receipt_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Einige Belege wurden nicht gefunden"
        )
    
    # Erstelle Verknüpfungen
    created_links = []
    for receipt_id in request.receipt_ids:
        # Prüfe ob Link bereits existiert
        existing_link = db.query(DocumentLink).filter(
            DocumentLink.statement_id == request.statement_id,
            DocumentLink.receipt_id == receipt_id
        ).first()
        
        if not existing_link:
            link = DocumentLink(
                statement_id=request.statement_id,
                receipt_id=receipt_id
            )
            db.add(link)
            created_links.append(receipt_id)
    
    db.commit()
    
    return {
        "message": f"{len(created_links)} Belege erfolgreich verknüpft",
        "statement_id": request.statement_id,
        "linked_receipts": created_links
    }


@router.post("/bk/{billing_year}/publish", status_code=status.HTTP_200_OK)
def publish_bk_statement(
    billing_year: int,
    statement_id: str = Form(...),  # Akzeptiere statement_id als Form-Parameter
    receipt_ids: Optional[List[str]] = Form(None),  # FastAPI unterstützt Listen mit FormData
    tenant_ids: Optional[List[str]] = Form(None),  # Mehrere Mieter für Benachrichtigung
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """
    Veröffentliche eine Betriebskostenabrechnung (und optional verknüpfte Belege)
    
    - Setzt Status auf PUBLISHED
    - Setzt published_at
    - Sendet Benachrichtigungen an betroffene Mieter
    """
    # Prüfe ob Statement existiert
    statement = db.query(Document).filter(
        Document.id == statement_id,
        Document.document_type == DocumentType.BK_STATEMENT.value,
        Document.billing_year == billing_year,
        Document.owner_id == current_user.id
    ).first()
    
    if not statement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Betriebskostenabrechnung nicht gefunden"
        )
    
    # Veröffentliche Statement
    # WICHTIG: Verwende den Enum-Wert (lowercase String) für den Status
    statement.status = DocumentStatus.PUBLISHED.value
    statement.published_at = datetime.utcnow()
    
    # Veröffentliche verknüpfte Belege (falls receipt_ids angegeben)
    if receipt_ids:
        receipts = db.query(Document).filter(
            Document.id.in_(receipt_ids),
            Document.document_type == DocumentType.BK_RECEIPT.value,
            Document.owner_id == current_user.id
        ).all()
        
        for receipt in receipts:
            receipt.status = DocumentStatus.PUBLISHED.value
            receipt.published_at = datetime.utcnow()
    else:
        # Veröffentliche alle verknüpften Belege automatisch
        links = db.query(DocumentLink).filter(
            DocumentLink.statement_id == statement_id
        ).all()
        
        receipt_ids_from_links = [link.receipt_id for link in links]
        if receipt_ids_from_links:
            receipts = db.query(Document).filter(
                Document.id.in_(receipt_ids_from_links),
                Document.document_type == DocumentType.BK_RECEIPT.value
            ).all()
            
            for receipt in receipts:
                receipt.status = DocumentStatus.PUBLISHED.value
                receipt.published_at = datetime.utcnow()
    
    db.commit()
    
    # Sende Benachrichtigungen an betroffene Mieter
    # VERBESSERTE LOGIK: Prüfe lease_id, tenant_id, billing_year und client_id
    
    logger.info(f"🔍 DEBUG: Statement {statement_id} - lease_id={statement.lease_id}, tenant_id={statement.tenant_id}, unit_id={statement.unit_id}, client_id={statement.client_id}")
    
    # Starte mit automatisch gefundenen tenant_ids
    auto_tenant_ids = []
    
    # 1. Prüfe ob Statement spezifisch für einen Lease ist
    if statement.lease_id:
        logger.info(f"🔍 DEBUG: Prüfe Lease {statement.lease_id}")
        lease = db.query(Lease).filter(
            Lease.id == statement.lease_id,
            Lease.status == "active"
        ).first()
        if lease:
            # Prüfe ob Lease zum billing_year passt
            billing_start = date(billing_year, 1, 1)
            billing_end = date(billing_year, 12, 31)
            if lease.start_date <= billing_end and (lease.end_date is None or lease.end_date >= billing_start):
                auto_tenant_ids = [lease.tenant_id]
                logger.info(f"✅ DEBUG: Lease gefunden, Tenant-ID: {lease.tenant_id}")
            else:
                logger.warning(f"⚠️ DEBUG: Lease {statement.lease_id} passt nicht zum billing_year {billing_year}")
        else:
            logger.warning(f"⚠️ DEBUG: Lease {statement.lease_id} nicht gefunden oder nicht aktiv")
    
    # 2. Falls kein lease_id, prüfe ob Statement spezifisch für einen Tenant ist
    elif statement.tenant_id:
        logger.info(f"🔍 DEBUG: Prüfe Tenant {statement.tenant_id}")
        tenant = db.query(Tenant).filter(Tenant.id == statement.tenant_id).first()
        if tenant:
            auto_tenant_ids = [tenant.id]
            logger.info(f"✅ DEBUG: Tenant gefunden: {tenant.first_name} {tenant.last_name}, E-Mail: {tenant.email}")
        else:
            logger.warning(f"⚠️ DEBUG: Tenant {statement.tenant_id} nicht gefunden")
    
    # 3. Falls unit_id gesetzt ist, hole alle relevanten Tenants
    elif statement.unit_id:
        logger.info(f"🔍 DEBUG: Prüfe Unit {statement.unit_id}")
        # Prüfe billing_year: Nur Tenants, die zum Zeitpunkt des billing_year in der Unit gewohnt haben
        billing_start = date(billing_year, 1, 1)
        billing_end = date(billing_year, 12, 31)
        
        leases = db.query(Lease).filter(
            Lease.unit_id == statement.unit_id,
            Lease.status == "active",
            Lease.start_date <= billing_end,
            or_(
                Lease.end_date >= billing_start,
                Lease.end_date == None
            )
        ).all()
        
        auto_tenant_ids = [lease.tenant_id for lease in leases]
        logger.info(f"✅ DEBUG: {len(leases)} Lease(s) gefunden für Unit {statement.unit_id}, Tenant-IDs: {auto_tenant_ids}")
    
    else:
        logger.warning(f"⚠️ DEBUG: Statement hat weder lease_id, noch tenant_id, noch unit_id!")
    
    # 4. Prüfe client_id (Multi-Tenancy): Nur Tenants mit gleichem client_id
    if auto_tenant_ids and statement.client_id:
        logger.info(f"🔍 DEBUG: Filtere Tenants nach client_id={statement.client_id}")
        tenants = db.query(Tenant).filter(
            Tenant.id.in_(auto_tenant_ids),
            Tenant.client_id == statement.client_id
        ).all()
        auto_tenant_ids = [t.id for t in tenants]
        logger.info(f"✅ DEBUG: {len(tenants)} Tenant(s) nach client_id gefiltert: {auto_tenant_ids}")
    elif auto_tenant_ids and not statement.client_id:
        logger.warning(f"⚠️ DEBUG: Statement hat kein client_id, verwende alle gefundenen Tenants")
    
    # 4.5. Kombiniere automatisch gefundene und manuell ausgewählte tenant_ids
    # tenant_ids aus Form-Parameter (manuell ausgewählt beim Veröffentlichen)
    manual_tenant_ids = []
    if tenant_ids:
        if isinstance(tenant_ids, str):
            manual_tenant_ids = [tenant_ids]
        elif isinstance(tenant_ids, list):
            manual_tenant_ids = tenant_ids
    
    # Validiere manuell ausgewählte tenant_ids
    if manual_tenant_ids:
        valid_manual_tenants = db.query(Tenant).filter(
            Tenant.id.in_(manual_tenant_ids),
            Tenant.client_id == statement.client_id,
            Tenant.owner_id == current_user.id
        ).all()
        valid_manual_tenant_ids = [t.id for t in valid_manual_tenants]
        logger.info(f"✅ DEBUG: {len(valid_manual_tenant_ids)} manuell ausgewählte Tenant(s) validiert: {valid_manual_tenant_ids}")
    else:
        valid_manual_tenant_ids = []
    
    # Kombiniere beide Listen (ohne Duplikate)
    all_tenant_ids = list(set(auto_tenant_ids + valid_manual_tenant_ids))
    tenant_ids = all_tenant_ids
    logger.info(f"✅ DEBUG: Kombinierte tenant_ids (automatisch: {len(auto_tenant_ids)}, manuell: {len(valid_manual_tenant_ids)}, gesamt: {len(tenant_ids)}): {tenant_ids}")
    
    # 5. Sende Benachrichtigungen an betroffene Mieter
    notification_service = NotificationService()
    sent_count = 0
    failed_count = 0
    
    if not tenant_ids:
        logger.warning(f"⚠️ Keine Tenants gefunden für Statement {statement_id} (lease_id={statement.lease_id}, tenant_id={statement.tenant_id}, unit_id={statement.unit_id})")
        return {
            "message": "Betriebskostenabrechnung erfolgreich veröffentlicht",
            "statement_id": statement_id,
            "billing_year": billing_year,
            "notifications": {
                "sent": 0,
                "failed": 0,
                "total": 0,
                "note": "Keine betroffenen Mieter gefunden (kein Lease/Tenant/Unit zugeordnet)"
            }
        }
    
    # Hole alle betroffenen Tenants
    tenants = db.query(Tenant).filter(
        Tenant.id.in_(tenant_ids),
        Tenant.client_id == statement.client_id
    ).all()
    
    logger.info(f"📧 Gefundene Tenants für Statement {statement_id}: {len(tenants)}")
    
    # Für jeden Tenant: Versuche Portal-User zu finden, sonst verwende Tenant-E-Mail
    for tenant in tenants:
        tenant_name = f"{tenant.first_name} {tenant.last_name}"
        recipient_email = None
        portal_user_id = None
        
        # 1. Versuche Portal-User zu finden (priorisiert Portal-User-E-Mail)
        portal_user = db.query(PortalUser).filter(
            PortalUser.tenant_id == tenant.id,
            PortalUser.is_active == True,
            PortalUser.is_verified == True
        ).first()
        
        if portal_user and portal_user.email:
            recipient_email = portal_user.email
            portal_user_id = portal_user.id
            logger.info(f"✅ Portal-User gefunden für Tenant {tenant.id}: {recipient_email}")
        elif tenant.email:
            # 2. Fallback: Verwende Tenant-E-Mail direkt (auch ohne Portal-User)
            recipient_email = tenant.email
            logger.info(f"ℹ️ Kein Portal-User für Tenant {tenant.id}, verwende Tenant-E-Mail: {recipient_email}")
        else:
            logger.warning(f"⚠️ Keine E-Mail-Adresse für Tenant {tenant.id} ({tenant_name})")
            failed_count += 1
            continue
        
        # Sende E-Mail
        success = notification_service.send_email(
            db=db,
            to_email=recipient_email,
            subject=f"Neue Betriebskostenabrechnung {billing_year} verfügbar",
            template="bk_published",
            data={
                "year": billing_year,
                "tenant_name": tenant_name,
                "portal_url": os.getenv("FRONTEND_URL", "http://localhost:5173")
            },
            recipient_id=portal_user_id,  # Kann None sein, wenn kein Portal-User
            notification_type=NotifType.BK_PUBLISHED,
            document_id=statement.id,
            from_user_id=current_user.id
        )
        
        if success:
            sent_count += 1
            logger.info(f"✅ E-Mail gesendet an {recipient_email} für Tenant {tenant.id}")
        else:
            failed_count += 1
            logger.error(f"❌ Fehler beim Senden der E-Mail an {recipient_email} für Tenant {tenant.id}")
    
    return {
        "message": "Betriebskostenabrechnung erfolgreich veröffentlicht",
        "statement_id": statement_id,
        "billing_year": billing_year,
        "notifications": {
            "sent": sent_count,
            "failed": failed_count,
            "total": len(tenants),
            "note": f"{sent_count} von {len(tenants)} Mieter(n) benachrichtigt" if tenants else "Keine Mieter gefunden"
        }
    }


@router.get("/documents/{document_id}/download")
def download_document_admin(
    document_id: str,
    current_user: User = Depends(require_admin_or_staff),
    db: Session = Depends(get_db)
):
    """Lade ein Dokument herunter (Admin-Zugriff)"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.owner_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dokument nicht gefunden"
        )
    
    absolute_file_path = os.path.abspath(document.file_path)
    
    if not os.path.exists(absolute_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Datei nicht gefunden unter: {absolute_file_path}"
        )
    
    return FileResponse(
        absolute_file_path,
        media_type=document.mime_type or "application/octet-stream",
        filename=document.filename
    )

