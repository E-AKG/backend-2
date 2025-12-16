from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, List
from decimal import Decimal
from datetime import date
from ..db import get_db
from ..models.user import User
from ..models.lease import Lease, LeaseComponent, LeaseStatus, RentAdjustment
from ..models.unit import Unit
from ..models.tenant import Tenant
from ..models.property import Property
from ..schemas.lease_schema import (
    LeaseCreate, LeaseUpdate, LeaseOut,
    LeaseComponentCreate, LeaseComponentUpdate, LeaseComponentOut,
    RentAdjustmentOut
)
from ..utils.deps import get_current_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Leases"])


@router.get("/api/leases", response_model=dict)
def list_leases(
    status: Optional[LeaseStatus] = Query(None, description="Filter by status"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    unit_id: Optional[str] = Query(None, description="Filter by unit ID"),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=10000, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all leases for the current user with filters and pagination.
    Filtert nach Mandant (client_id) und Geschäftsjahr (fiscal_year_id) falls angegeben.
    """
    try:
        query = db.query(Lease).filter(Lease.owner_id == current_user.id)
        
        # Filter nach Mandant (client_id) - falls Spalte existiert
        if client_id:
            try:
                # Zeige NUR Daten mit diesem client_id
                query = query.filter(Lease.client_id == client_id)
            except Exception:
                # Falls client_id Spalte noch nicht existiert, filtere über Unit -> Property
                try:
                    query = query.join(Unit).join(Property).filter(Property.client_id == client_id)
                except Exception:
                    logger.warning(f"client_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
        
        # Filter nach Geschäftsjahr (fiscal_year_id) - falls Spalte existiert
        if fiscal_year_id:
            try:
                # Zeige NUR Daten mit diesem fiscal_year_id
                query = query.filter(Lease.fiscal_year_id == fiscal_year_id)
            except Exception:
                logger.warning(f"fiscal_year_id Filter für Leases nicht verfügbar (Spalte existiert noch nicht)")
        
        # Apply filters
        if status:
            query = query.filter(Lease.status == status)
        if tenant_id:
            query = query.filter(Lease.tenant_id == tenant_id)
        if unit_id:
            query = query.filter(Lease.unit_id == unit_id)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        leases = query.order_by(Lease.created_at.desc()).offset(offset).limit(page_size).all()
        
        return {
            "items": [LeaseOut.model_validate(lease) for lease in leases],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Database error listing leases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )


@router.post("/api/leases", response_model=LeaseOut, status_code=status.HTTP_201_CREATED)
def create_lease(
    lease_data: LeaseCreate,
    client_id: Optional[str] = Query(None, description="Mandant ID"),
    fiscal_year_id: Optional[str] = Query(None, description="Geschäftsjahr ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new lease.
    Setzt client_id und fiscal_year_id falls angegeben und Spalten existieren.
    """
    # Verify unit exists and belongs to user
    unit = db.query(Unit).filter(
        Unit.id == lease_data.unit_id,
        Unit.owner_id == current_user.id
    ).first()
    
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found"
        )
    
    # Verify tenant exists and belongs to user
    tenant = db.query(Tenant).filter(
        Tenant.id == lease_data.tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    # Check if unit already has an active lease
    existing_active_lease = db.query(Lease).filter(
        Lease.unit_id == lease_data.unit_id,
        Lease.status == LeaseStatus.ACTIVE
    ).first()
    
    if existing_active_lease:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unit already has an active lease"
        )
    
    try:
        lease_dict = lease_data.model_dump()
        
        # Setze client_id falls angegeben (und Spalte existiert)
        # Falls nicht angegeben, verwende client_id von Unit oder Tenant
        if client_id:
            try:
                from ..models.client import Client
                client = db.query(Client).filter(
                    Client.id == client_id,
                    Client.owner_id == current_user.id
                ).first()
                if not client:
                    raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
                lease_dict["client_id"] = client_id
            except Exception as e:
                logger.warning(f"client_id kann nicht gesetzt werden (Spalte existiert noch nicht): {str(e)}")
        else:
            # Versuche client_id von Unit oder Tenant zu übernehmen
            try:
                if hasattr(unit, 'client_id') and unit.client_id:
                    lease_dict["client_id"] = unit.client_id
                elif hasattr(tenant, 'client_id') and tenant.client_id:
                    lease_dict["client_id"] = tenant.client_id
            except Exception:
                pass
        
        # Setze fiscal_year_id falls angegeben
        if fiscal_year_id:
            try:
                from ..models.fiscal_year import FiscalYear
                fiscal_year = db.query(FiscalYear).filter(
                    FiscalYear.id == fiscal_year_id,
                    FiscalYear.client_id == (lease_dict.get("client_id") or client_id)
                ).first()
                if fiscal_year:
                    lease_dict["fiscal_year_id"] = fiscal_year_id
            except Exception as e:
                logger.warning(f"fiscal_year_id kann nicht gesetzt werden (Spalte existiert noch nicht): {str(e)}")
        
        new_lease = Lease(
            owner_id=current_user.id,
            **lease_dict
        )
        db.add(new_lease)
        db.commit()
        db.refresh(new_lease)
        
        logger.info(f"Lease created: {new_lease.id} by user {current_user.id}")
        return LeaseOut.model_validate(new_lease)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating lease: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lease"
        )


@router.get("/api/leases/{lease_id}", response_model=LeaseOut)
def get_lease(
    lease_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific lease by ID.
    """
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease not found"
        )
    
    return LeaseOut.model_validate(lease)


@router.put("/api/leases/{lease_id}", response_model=LeaseOut)
def update_lease(
    lease_id: str,
    lease_data: LeaseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a lease.
    """
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease not found"
        )
    
    try:
        # Update only provided fields
        update_data = lease_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(lease, field, value)
        
        db.commit()
        db.refresh(lease)
        
        logger.info(f"Lease updated: {lease_id} by user {current_user.id}")
        return LeaseOut.model_validate(lease)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating lease: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lease"
        )


@router.delete("/api/leases/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lease(
    lease_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a lease.
    """
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease not found"
        )
    
    try:
        db.delete(lease)
        db.commit()
        logger.info(f"Lease deleted: {lease_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting lease: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete lease"
        )


# ============= Lease Components =============

@router.get("/api/leases/{lease_id}/components", response_model=List[LeaseComponentOut])
def list_lease_components(
    lease_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all components for a specific lease.
    """
    # Verify lease exists and belongs to user
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease not found"
        )
    
    components = db.query(LeaseComponent).filter(
        LeaseComponent.lease_id == lease_id
    ).all()
    
    return [LeaseComponentOut.model_validate(comp) for comp in components]


@router.post("/api/leases/{lease_id}/components", response_model=LeaseComponentOut, status_code=status.HTTP_201_CREATED)
def create_lease_component(
    lease_id: str,
    component_data: LeaseComponentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Add a component to a lease.
    """
    # Verify lease exists and belongs to user
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease not found"
        )
    
    try:
        new_component = LeaseComponent(
            lease_id=lease_id,
            **component_data.model_dump()
        )
        db.add(new_component)
        db.commit()
        db.refresh(new_component)
        
        logger.info(f"Lease component created: {new_component.id} for lease {lease_id}")
        return LeaseComponentOut.model_validate(new_component)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating lease component: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lease component"
        )


@router.put("/api/lease-components/{component_id}", response_model=LeaseComponentOut)
def update_lease_component(
    component_id: str,
    component_data: LeaseComponentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a lease component.
    """
    # Get component and verify ownership through lease
    component = db.query(LeaseComponent).join(Lease).filter(
        LeaseComponent.id == component_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease component not found"
        )
    
    try:
        # Update only provided fields
        update_data = component_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(component, field, value)
        
        db.commit()
        db.refresh(component)
        
        logger.info(f"Lease component updated: {component_id}")
        return LeaseComponentOut.model_validate(component)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating lease component: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lease component"
        )


@router.delete("/api/lease-components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lease_component(
    component_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a lease component.
    """
    # Get component and verify ownership through lease
    component = db.query(LeaseComponent).join(Lease).filter(
        LeaseComponent.id == component_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lease component not found"
        )
    
    try:
        db.delete(component)
        db.commit()
        logger.info(f"Lease component deleted: {component_id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting lease component: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete lease component"
        )


@router.get("/api/lease-components/{component_id}/adjustments", response_model=List[RentAdjustmentOut])
def list_rent_adjustments(
    component_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Mietanpassungen für eine Komponente"""
    component = db.query(LeaseComponent).join(Lease).filter(
        LeaseComponent.id == component_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not component:
        raise HTTPException(status_code=404, detail="Komponente nicht gefunden")
    
    adjustments = db.query(RentAdjustment).filter(
        RentAdjustment.component_id == component_id
    ).order_by(RentAdjustment.adjustment_date.desc()).all()
    
    return [RentAdjustmentOut.model_validate(adj) for adj in adjustments]


@router.post("/api/lease-components/{component_id}/adjust-rent")
def adjust_rent(
    component_id: str,
    new_amount: Decimal = Query(..., description="Neuer Mietbetrag"),
    adjustment_date: Optional[date] = Query(None, description="Anpassungsdatum (default: heute)"),
    reason: Optional[str] = Query(None, description="Grund der Anpassung"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Führe Mietanpassung durch (für Staffel- oder Indexmiete)
    """
    from datetime import date as date_class
    from decimal import Decimal
    
    component = db.query(LeaseComponent).join(Lease).filter(
        LeaseComponent.id == component_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not component:
        raise HTTPException(status_code=404, detail="Komponente nicht gefunden")
    
    if not adjustment_date:
        adjustment_date = date_class.today()
    
    old_amount = component.amount
    
    # Erstelle Adjustment-Eintrag
    # TODO: Uncomment after database migration adds adjustment_type column
    # adjustment_reason_text = reason or f"{component.adjustment_type.value} Anpassung" if hasattr(component, 'adjustment_type') and component.adjustment_type else "Anpassung"
    adjustment_reason_text = reason or "Anpassung"
    
    adjustment = RentAdjustment(
        component_id=component_id,
        adjustment_date=adjustment_date,
        old_amount=old_amount,
        new_amount=new_amount,
        adjustment_reason=adjustment_reason_text
    )
    
    # Aktualisiere Komponente
    component.amount = new_amount
    
    db.add(adjustment)
    db.commit()
    db.refresh(adjustment)
    
    return RentAdjustmentOut.model_validate(adjustment)


@router.get("/api/leases/{lease_id}/upcoming-adjustments")
def get_upcoming_adjustments(
    lease_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole alle bevorstehenden Mietanpassungen für einen Vertrag
    """
    from datetime import date as date_class
    
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    
    if not lease:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden")
    
    upcoming = []
    today = date_class.today()
    
    # TODO: Uncomment after database migration adds adjustment_type, staggered_schedule, index_adjustment_date columns
    # Temporarily disabled - columns don't exist yet
    # for component in lease.components:
    #     if hasattr(component, 'adjustment_type') and component.adjustment_type == "staggered" and hasattr(component, 'staggered_schedule') and component.staggered_schedule:
    #         # Prüfe Staffelmiete
    #         for schedule_item in component.staggered_schedule:
    #             schedule_date = date_class.fromisoformat(schedule_item.get("date"))
    #             if schedule_date > today:
    #                 upcoming.append({
    #                     "component_id": component.id,
    #                     "component_type": component.type.value,
    #                     "adjustment_date": schedule_date.isoformat(),
    #                     "new_amount": float(schedule_item.get("amount", 0)),
    #                     "current_amount": float(component.amount),
    #                     "type": "staggered"
    #                 })
    #     elif hasattr(component, 'adjustment_type') and component.adjustment_type == "index_linked" and hasattr(component, 'index_adjustment_date') and component.index_adjustment_date:
    #         # Prüfe Indexmiete
    #         if component.index_adjustment_date > today:
    #             upcoming.append({
    #                 "component_id": component.id,
    #                 "component_type": component.type.value,
    #                 "adjustment_date": component.index_adjustment_date.isoformat(),
    #                 "current_amount": float(component.amount),
    #                 "index_type": component.index_type,
    #                 "type": "index_linked"
    #             })
    
    return {
        "lease_id": lease_id,
        "upcoming_adjustments": sorted(upcoming, key=lambda x: x["adjustment_date"]),
        "count": len(upcoming)
    }

