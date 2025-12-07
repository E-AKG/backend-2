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

