from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from ..db import get_db
from ..models.user import User
from ..models.document import Document, DocumentType, DocumentStatus
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict
import os
import uuid

router = APIRouter(prefix="/api/documents", tags=["Documents"])


class DocumentCreate(BaseModel):
    filename: str
    document_type: DocumentType = DocumentType.OTHER
    title: Optional[str] = None
    description: Optional[str] = None
    document_date: Optional[date] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    lease_id: Optional[str] = None
    ticket_id: Optional[str] = None
    accounting_id: Optional[str] = None
    charge_id: Optional[str] = None
    tags: Optional[str] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    document_date: Optional[date] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    lease_id: Optional[str] = None
    ticket_id: Optional[str] = None
    accounting_id: Optional[str] = None
    charge_id: Optional[str] = None
    tags: Optional[str] = None
    billing_year: Optional[int] = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    client_id: str
    filename: str
    file_path: str
    file_size: Optional[int]
    mime_type: Optional[str]
    document_type: str
    title: Optional[str]
    description: Optional[str]
    document_date: Optional[date]
    property_id: Optional[str]
    unit_id: Optional[str]
    tenant_id: Optional[str]
    lease_id: Optional[str]
    ticket_id: Optional[str]
    accounting_id: Optional[str]
    charge_id: Optional[str]
    tags: Optional[str]
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=List[DocumentResponse])
def list_documents(
    client_id: Optional[str] = Query(None, description="Mandant ID (optional, wird aus current_user.selected_client_id verwendet falls nicht angegeben)"),
    document_type: Optional[str] = Query(None, description="Dokumenttyp (z.B. 'bk_statement', 'bk_receipt')"),
    status: Optional[str] = Query(None, description="Status (z.B. 'draft', 'published')"),
    billing_year: Optional[int] = Query(None, description="Abrechnungsjahr"),
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    lease_id: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Dokumente"""
    # Hole client_id aus Query-Parameter oder aus current_user
    if not client_id:
        client_id = getattr(current_user, 'selected_client_id', None)
    
    # Falls immer noch kein client_id vorhanden, hole den ersten Client des Users
    if not client_id:
        from ..models.client import Client
        default_client = db.query(Client).filter(Client.owner_id == current_user.id).first()
        if default_client:
            client_id = default_client.id
    
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Kein Mandant gefunden. Bitte erstellen Sie zuerst einen Mandanten oder geben Sie client_id an."
        )
    
    query = db.query(Document).filter(
        Document.owner_id == current_user.id,
        Document.client_id == client_id
    )
    
    # Konvertiere document_type String zu Enum (unterstützt sowohl "BK_STATEMENT" als auch "bk_statement")
    if document_type:
        document_type_str = document_type.lower()
        try:
            # Validiere, dass der String ein gültiger Enum-Wert ist
            document_type_enum = DocumentType(document_type_str)
            # WICHTIG: Verwende den Enum-Wert (lowercase String) direkt als String für den Filter
            # SQLAlchemy serialisiert Enums manchmal mit dem Namen statt dem Wert bei PostgreSQL Enums
            # Daher verwenden wir cast() um sicherzustellen, dass der String-Wert verwendet wird
            from sqlalchemy import cast, String
            query = query.filter(cast(Document.document_type, String) == document_type_enum.value)
        except ValueError:
            # Falls der String kein gültiger Enum-Wert ist, wirf einen Fehler
            raise HTTPException(
                status_code=422,
                detail=f"Ungültiger document_type: {document_type}. Gültige Werte: {[e.value for e in DocumentType]}"
            )
    
    # Filter nach status (falls angegeben)
    if status:
        from ..models.document import DocumentStatus
        from sqlalchemy import cast, String
        status_str = status.lower()
        try:
            # Validiere, dass der String ein gültiger Enum-Wert ist
            status_enum = DocumentStatus(status_str)
            # WICHTIG: Verwende den Enum-Wert (lowercase String) direkt als String für den Filter
            query = query.filter(cast(Document.status, String) == status_enum.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Ungültiger status: {status}. Gültige Werte: {[e.value for e in DocumentStatus]}"
            )
    
    # Filter nach billing_year (falls angegeben)
    if billing_year:
        query = query.filter(Document.billing_year == billing_year)
    if property_id:
        query = query.filter(Document.property_id == property_id)
    if unit_id:
        query = query.filter(Document.unit_id == unit_id)
    if tenant_id:
        query = query.filter(Document.tenant_id == tenant_id)
    if lease_id:
        query = query.filter(Document.lease_id == lease_id)
    if ticket_id:
        query = query.filter(Document.ticket_id == ticket_id)
    if search:
        query = query.filter(
            (Document.title.contains(search)) |
            (Document.description.contains(search)) |
            (Document.filename.contains(search))
        )
    
    documents = query.order_by(Document.created_at.desc()).all()
    return [DocumentResponse.model_validate(doc) for doc in documents]


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    client_id: str = Query(..., description="Mandant ID"),
    document_type: str = Query("other", description="Dokumenttyp (z.B. 'other', 'bk_statement', 'bk_receipt')"),
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    document_date: Optional[date] = Query(None),
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    lease_id: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    accounting_id: Optional[str] = Query(None),
    charge_id: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dokument hochladen"""
    # Konvertiere String zu Enum (unterstützt sowohl "OTHER" als auch "other")
    document_type_str = document_type.lower() if document_type else "other"
    
    # Validiere document_type
    try:
        document_type_enum = DocumentType(document_type_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger document_type: {document_type}. Gültige Werte: {[e.value for e in DocumentType]}"
        )
    
    # Erstelle Upload-Verzeichnis falls nicht vorhanden
    upload_dir = "uploads/documents"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generiere eindeutigen Dateinamen
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    # Speichere Datei
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Erstelle Datenbankeintrag
    # WICHTIG: Verwende den Enum-Wert (lowercase String) direkt beim Erstellen des Objekts
    document = Document(
        owner_id=current_user.id,
        client_id=client_id,
        filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        document_type=document_type_enum.value,  # Verwende .value direkt (lowercase String)
        title=title or file.filename,
        description=description,
        document_date=document_date,
        property_id=property_id,
        unit_id=unit_id,
        tenant_id=tenant_id,
        lease_id=lease_id,
        ticket_id=ticket_id,
        accounting_id=accounting_id,
        charge_id=charge_id,
        tags=tags,
        status=DocumentStatus.DRAFT.value  # Setze Status auf DRAFT
    )
    
    db.add(document)
    db.commit()
    db.refresh(document)
    
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnes Dokument abrufen"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.owner_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dokument herunterladen"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.owner_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    
    # Konvertiere relativen Pfad zu absolutem Pfad
    file_path = document.file_path
    if not os.path.isabs(file_path):
        # Relativer Pfad: Konvertiere zu absolutem Pfad
        file_path = os.path.abspath(file_path)
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, 
            detail=f"Datei nicht gefunden: {file_path}"
        )
    
    return FileResponse(
        file_path,
        media_type=document.mime_type or "application/octet-stream",
        filename=document.filename
    )


@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: str,
    document_data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dokument bearbeiten"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.owner_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    
    # Aktualisiere Felder
    update_data = document_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(document, field, value)
    
    db.commit()
    db.refresh(document)
    
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Dokument löschen"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.owner_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    
    # Lösche Datei
    if os.path.exists(document.file_path):
        os.remove(document.file_path)
    
    db.delete(document)
    db.commit()
    
    return None

