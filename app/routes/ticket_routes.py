from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from ..db import get_db
from ..models.user import User
from ..models.ticket import Ticket, TicketComment, TicketAttachment, TicketCategory, TicketPriority, TicketStatus
from ..utils.deps import get_current_user
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/tickets", tags=["Tickets"])


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    service_provider_id: Optional[str] = None
    due_date: Optional[date] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    status: Optional[TicketStatus] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    service_provider_id: Optional[str] = None
    due_date: Optional[date] = None
    estimated_cost: Optional[str] = None
    actual_cost: Optional[str] = None


class TicketCommentCreate(BaseModel):
    comment: str


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    client_id: str
    title: str
    description: Optional[str]
    category: str
    priority: str
    status: str
    property_id: Optional[str]
    unit_id: Optional[str]
    tenant_id: Optional[str]
    service_provider_id: Optional[str]
    due_date: Optional[date]
    resolved_at: Optional[date]
    estimated_cost: Optional[str]
    actual_cost: Optional[str]
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=List[TicketResponse])
def list_tickets(
    client_id: str = Query(..., description="Mandant ID"),
    status: Optional[TicketStatus] = Query(None),
    priority: Optional[TicketPriority] = Query(None),
    category: Optional[TicketCategory] = Query(None),
    property_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Tickets"""
    query = db.query(Ticket).filter(
        Ticket.owner_id == current_user.id,
        Ticket.client_id == client_id
    )
    
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category:
        query = query.filter(Ticket.category == category)
    if property_id:
        query = query.filter(Ticket.property_id == property_id)
    
    tickets = query.order_by(Ticket.created_at.desc()).all()
    return [TicketResponse.model_validate(ticket) for ticket in tickets]


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    ticket_data: TicketCreate,
    client_id: str = Query(..., description="Mandant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Neues Ticket erstellen"""
    ticket = Ticket(
        owner_id=current_user.id,
        client_id=client_id,
        **ticket_data.model_dump()
    )
    
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    
    return TicketResponse.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Einzelnes Ticket abrufen"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.owner_id == current_user.id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    
    return TicketResponse.model_validate(ticket)


@router.put("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: str,
    ticket_data: TicketUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ticket aktualisieren"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.owner_id == current_user.id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    
    update_data = ticket_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ticket, key, value)
    
    # Wenn Status auf "resolved" gesetzt wird, setze resolved_at
    if ticket.status == TicketStatus.RESOLVED and not ticket.resolved_at:
        ticket.resolved_at = date.today()
    
    db.commit()
    db.refresh(ticket)
    
    return TicketResponse.model_validate(ticket)


@router.post("/{ticket_id}/comments", status_code=201)
def add_comment(
    ticket_id: str,
    comment_data: TicketCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kommentar zu Ticket hinzufügen"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.owner_id == current_user.id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    
    comment = TicketComment(
        ticket_id=ticket_id,
        user_id=current_user.id,
        comment=comment_data.comment
    )
    
    db.add(comment)
    db.commit()
    db.refresh(comment)
    
    return {
        "id": comment.id,
        "comment": comment.comment,
        "created_at": comment.created_at.isoformat()
    }


@router.get("/{ticket_id}/comments")
def get_comments(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Kommentare eines Tickets abrufen"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.owner_id == current_user.id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    
    comments = db.query(TicketComment).filter(
        TicketComment.ticket_id == ticket_id
    ).order_by(TicketComment.created_at.asc()).all()
    
    return [
        {
            "id": c.id,
            "comment": c.comment,
            "user_id": c.user_id,
            "created_at": c.created_at.isoformat()
        }
        for c in comments
    ]


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ticket löschen"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.owner_id == current_user.id
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    
    db.delete(ticket)
    db.commit()
    
    return None

