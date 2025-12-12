from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from ..db import get_db
from ..models.user import User
from ..models.document import Document, DocumentType
from ..utils.deps import get_current_user
from pydantic import BaseModel
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


class DocumentResponse(BaseModel):
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
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[DocumentResponse])
def list_documents(
    client_id: str = Query(..., description="Mandant ID"),
    document_type: Optional[DocumentType] = Query(None),
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
    query = db.query(Document).filter(
        Document.owner_id == current_user.id,
        Document.client_id == client_id
    )
    
    if document_type:
        query = query.filter(Document.document_type == document_type)
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
    return documents


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    client_id: str = Query(..., description="Mandant ID"),
    document_type: DocumentType = Query(DocumentType.OTHER),
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
    document = Document(
        owner_id=current_user.id,
        client_id=client_id,
        filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        document_type=document_type,
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
        tags=tags
    )
    
    db.add(document)
    db.commit()
    db.refresh(document)
    
    return document


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
    
    return document


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

