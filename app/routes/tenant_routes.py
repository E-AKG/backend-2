from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from ..db import get_db
from ..models.user import User
from ..models.tenant import Tenant
from ..models.lease import Lease
from ..schemas.tenant_schema import TenantCreate, TenantUpdate, TenantOut
from ..utils.deps import get_current_user
from ..services.risk_score_service import update_tenant_risk_score, recalculate_all_tenant_risk_scores
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


@router.get("", response_model=dict)
def list_tenants(
    search: Optional[str] = Query(None, description="Search in name or email"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=10000, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all tenants for the current user with pagination and search.
    """
    try:
        query = db.query(Tenant).filter(Tenant.owner_id == current_user.id)
        
        # Apply search filter
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (Tenant.first_name.ilike(search_filter)) | 
                (Tenant.last_name.ilike(search_filter)) |
                (Tenant.email.ilike(search_filter))
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        tenants = query.order_by(Tenant.last_name, Tenant.first_name).offset(offset).limit(page_size).all()
        
        return {
            "items": [TenantOut.model_validate(tenant) for tenant in tenants],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Database error listing tenants: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant_data: TenantCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new tenant.
    """
    try:
        new_tenant = Tenant(
            owner_id=current_user.id,
            **tenant_data.model_dump()
        )
        db.add(new_tenant)
        db.commit()
        db.refresh(new_tenant)
        
        logger.info(f"Tenant created: {new_tenant.id} by user {current_user.id}")
        return TenantOut.model_validate(new_tenant)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create tenant"
        )


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific tenant by ID.
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    return TenantOut.model_validate(tenant)


@router.get("/{tenant_id}/crm")
def get_tenant_crm(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Erweiterte CRM-Ansicht für einen Mieter
    Inkludiert: Verträge, Zahlungen, Offene Posten, Timeline
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    from ..models.lease import Lease, LeaseStatus
    from ..models.unit import Unit
    from ..models.property import Property
    from ..models.billrun import Charge, ChargeStatus
    from ..models.bank import PaymentMatch
    
    # Aktive und historische Verträge
    leases = db.query(Lease).filter(
        Lease.tenant_id == tenant_id
    ).order_by(Lease.start_date.desc()).all()
    
    leases_data = []
    for lease in leases:
        unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
        property_obj = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
        
        leases_data.append({
            "id": lease.id,
            "start_date": lease.start_date.isoformat() if lease.start_date else None,
            "end_date": lease.end_date.isoformat() if lease.end_date else None,
            "status": lease.status.value,
            "unit": {
                "id": unit.id if unit else None,
                "label": unit.unit_label if unit else None,
                "property": {
                    "id": property_obj.id if property_obj else None,
                    "name": property_obj.name if property_obj else None,
                    "address": property_obj.address if property_obj else None,
                } if property_obj else None
            } if unit else None,
            "components": [
                {
                    "type": comp.type.value,
                    "amount": float(comp.amount),
                    "description": comp.description
                }
                for comp in lease.components
            ]
        })
    
    # Offene Posten
    open_charges = db.query(Charge).join(Lease).filter(
        Lease.tenant_id == tenant_id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE])
    ).order_by(Charge.due_date).all()
    
    charges_data = []
    total_open = 0
    for charge in open_charges:
        open_amount = float(charge.amount - charge.paid_amount)
        total_open += open_amount
        charges_data.append({
            "id": charge.id,
            "amount": float(charge.amount),
            "paid": float(charge.paid_amount),
            "open": open_amount,
            "due_date": charge.due_date.isoformat() if charge.due_date else None,
            "status": charge.status.value,
            "description": charge.description
        })
    
    # Zahlungshistorie (letzte 20)
    payment_matches = db.query(PaymentMatch).join(Charge).join(Lease).filter(
        Lease.tenant_id == tenant_id
    ).order_by(PaymentMatch.created_at.desc()).limit(20).all()
    
    payments_data = []
    for pm in payment_matches:
        payments_data.append({
            "id": pm.id,
            "amount": float(pm.matched_amount),
            "date": pm.created_at.isoformat() if pm.created_at else None,
            "is_automatic": pm.is_automatic,
            "charge_id": pm.charge_id
        })
    
    # Timeline (vereinfacht - später erweitern)
    timeline = []
    
    # Verträge zur Timeline hinzufügen
    for lease in leases:
        timeline.append({
            "id": f"lease_{lease.id}",
            "type": "lease",
            "title": f"Vertrag {'gestartet' if lease.status == LeaseStatus.ACTIVE else 'beendet'}",
            "date": lease.start_date.isoformat() if lease.start_date else None,
            "description": f"Vertrag für {lease.unit.unit_label if lease.unit else 'unbekannt'}"
        })
    
    # Zahlungen zur Timeline hinzufügen
    for payment in payments_data:
        timeline.append({
            "id": f"payment_{payment['id']}",
            "type": "payment",
            "title": f"Zahlung erhalten: {payment['amount']:.2f} €",
            "date": payment['date'],
            "description": "Zahlung zugeordnet"
        })
    
    # Sortiere Timeline nach Datum
    timeline.sort(key=lambda x: x['date'] or '', reverse=True)
    
    return {
        "tenant": TenantOut.model_validate(tenant),
        "leases": leases_data,
        "open_charges": {
            "items": charges_data,
            "total": total_open,
            "count": len(charges_data)
        },
        "payments": {
            "items": payments_data,
            "total": sum(float(p['amount']) for p in payments_data),
            "count": len(payments_data)
        },
        "timeline": timeline[:50]  # Limit auf 50 Einträge
    }


@router.put("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: str,
    tenant_data: TenantUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a tenant.
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    try:
        # Update only provided fields
        update_data = tenant_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(tenant, field, value)
        
        db.commit()
        db.refresh(tenant)
        
        logger.info(f"Tenant updated: {tenant_id} by user {current_user.id}")
        return TenantOut.model_validate(tenant)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update tenant"
        )


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a tenant (only if they have no leases).
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    # Check if tenant has leases
    leases_count = db.query(Lease).filter(Lease.tenant_id == tenant_id).count()
    if leases_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete tenant with {leases_count} lease(s). Delete leases first."
        )
    
    try:
        db.delete(tenant)
        db.commit()
        logger.info(f"Tenant deleted: {tenant_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete tenant"
        )


@router.post("/{tenant_id}/recalculate-risk-score", response_model=TenantOut)
def recalculate_tenant_risk_score(
    tenant_id: str,
    months_to_analyze: int = Query(6, ge=1, le=24, description="Number of months to analyze"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Berechnet und aktualisiert den Risk Score für einen spezifischen Mieter.
    """
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    try:
        score, risk_level = update_tenant_risk_score(tenant_id, db, months_to_analyze)
        db.refresh(tenant)
        
        logger.info(f"Risk score recalculated for tenant {tenant_id}: {score} ({risk_level.value})")
        return TenantOut.model_validate(tenant)
    except Exception as e:
        db.rollback()
        logger.error(f"Error recalculating risk score: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recalculate risk score: {str(e)}"
        )


@router.post("/recalculate-all-risk-scores")
def recalculate_all_risk_scores(
    months_to_analyze: int = Query(6, ge=1, le=24, description="Number of months to analyze"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Berechnet Risk Scores für alle Mieter des aktuellen Benutzers.
    """
    try:
        result = recalculate_all_tenant_risk_scores(
            db,
            owner_id=current_user.id,
            months_to_analyze=months_to_analyze
        )
        
        logger.info(f"Recalculated risk scores for {result['updated']} tenants")
        return result
    except Exception as e:
        logger.error(f"Error recalculating all risk scores: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recalculate risk scores: {str(e)}"
        )

