from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from typing import Optional
from ..db import get_db
from ..models.user import User
from ..models.unit import Unit, UnitStatus
from ..models.property import Property
from ..models.lease import Lease, LeaseStatus
from ..schemas.unit_schema import UnitCreate, UnitUpdate, UnitOut
from ..utils.deps import get_current_user
from ..utils.subscription_limits import check_unit_limit
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/units", tags=["Units"])


@router.get("", response_model=dict)
def list_units(
    property_id: Optional[str] = Query(None, description="Filter by property ID"),
    status: Optional[UnitStatus] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=10000, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all units for the current user with filters and pagination.
    """
    try:
        query = db.query(Unit).filter(Unit.owner_id == current_user.id)
        
        # Apply filters
        if property_id:
            query = query.filter(Unit.property_id == property_id)
        if status:
            query = query.filter(Unit.status == status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        units = query.order_by(Unit.created_at.desc()).offset(offset).limit(page_size).all()
        
        return {
            "items": [UnitOut.model_validate(unit) for unit in units],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Database error listing units: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )


@router.post("", response_model=UnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    unit_data: UnitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new unit.
    Trial users: max 1 unit
    Paid users: unlimited
    """
    # Check unit limit for trial users
    check_unit_limit(current_user, db)
    
    # Verify property exists and belongs to user
    property_obj = db.query(Property).filter(
        Property.id == unit_data.property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found"
        )
    
    try:
        new_unit = Unit(
            owner_id=current_user.id,
            **unit_data.model_dump()
        )
        db.add(new_unit)
        db.commit()
        db.refresh(new_unit)
        
        logger.info(f"Unit created: {new_unit.id} by user {current_user.id}")
        return UnitOut.model_validate(new_unit)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unit with label '{unit_data.unit_label}' already exists in this property"
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating unit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create unit"
        )


@router.get("/{unit_id}", response_model=UnitOut)
def get_unit(
    unit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific unit by ID.
    """
    unit = db.query(Unit).filter(
        Unit.id == unit_id,
        Unit.owner_id == current_user.id
    ).first()
    
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found"
        )
    
    return UnitOut.model_validate(unit)


@router.put("/{unit_id}", response_model=UnitOut)
def update_unit(
    unit_id: str,
    unit_data: UnitUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a unit.
    """
    unit = db.query(Unit).filter(
        Unit.id == unit_id,
        Unit.owner_id == current_user.id
    ).first()
    
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found"
        )
    
    try:
        # Update only provided fields
        update_data = unit_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(unit, field, value)
        
        db.commit()
        db.refresh(unit)
        
        logger.info(f"Unit updated: {unit_id} by user {current_user.id}")
        return UnitOut.model_validate(unit)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unit with this label already exists in the property"
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating unit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update unit"
        )


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(
    unit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a unit (only if it has no active leases).
    """
    unit = db.query(Unit).filter(
        Unit.id == unit_id,
        Unit.owner_id == current_user.id
    ).first()
    
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found"
        )
    
    # Check if unit has active leases
    active_leases = db.query(Lease).filter(
        Lease.unit_id == unit_id,
        Lease.status == LeaseStatus.ACTIVE
    ).count()
    
    if active_leases > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete unit with {active_leases} active lease(s). End leases first."
        )
    
    try:
        db.delete(unit)
        db.commit()
        logger.info(f"Unit deleted: {unit_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting unit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete unit"
        )

