from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from ..db import get_db
from ..models.user import User
from ..models.property import Property
from ..models.unit import Unit
from ..schemas.property_schema import PropertyCreate, PropertyUpdate, PropertyOut
from ..utils.deps import get_current_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/properties", tags=["Properties"])


@router.get("", response_model=dict)
def list_properties(
    search: Optional[str] = Query(None, description="Search in name or address"),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=10000, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all properties for the current user with pagination and search.
    Filtert nach Mandant (client_id) falls angegeben.
    """
    try:
        query = db.query(Property).filter(Property.owner_id == current_user.id)
        
        # Filter nach Mandant (client_id) - falls Spalte existiert
        if client_id:
            try:
                # Zeige NUR Daten mit diesem client_id
                query = query.filter(Property.client_id == client_id)
            except Exception:
                logger.warning(f"client_id Filter für Properties nicht verfügbar (Spalte existiert noch nicht)")
        
        # Apply search filter
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (Property.name.ilike(search_filter)) | 
                (Property.address.ilike(search_filter))
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        properties = query.order_by(Property.created_at.desc()).offset(offset).limit(page_size).all()
        
        return {
            "items": [PropertyOut.model_validate(prop) for prop in properties],
            "page": page,
            "page_size": page_size,
            "total": total
        }
    except SQLAlchemyError as e:
        logger.error(f"Database error listing properties: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED)
def create_property(
    property_data: PropertyCreate,
    client_id: Optional[str] = Query(None, description="Mandant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new property.
    Setzt client_id falls angegeben und Spalte existiert.
    """
    try:
        property_dict = property_data.model_dump()
        
        # Setze client_id falls angegeben (und Spalte existiert)
        if client_id:
            try:
                # Prüfe ob Client existiert und dem User gehört
                from ..models.client import Client
                client = db.query(Client).filter(
                    Client.id == client_id,
                    Client.owner_id == current_user.id
                ).first()
                if not client:
                    raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
                property_dict["client_id"] = client_id
            except Exception as e:
                # Falls client_id Spalte noch nicht existiert, ignorieren
                logger.warning(f"client_id kann nicht gesetzt werden (Spalte existiert noch nicht): {str(e)}")
        
        # Entferne units_count aus property_dict (ist kein Property-Feld)
        units_count = property_dict.pop("units_count", None)
        
        new_property = Property(
            owner_id=current_user.id,
            **property_dict
        )
        db.add(new_property)
        db.flush()  # Flush um ID zu bekommen, aber noch nicht committen
        
        # Erstelle automatisch Einheiten, falls units_count angegeben wurde
        if units_count and units_count > 0:
            from ..models.unit import UnitStatus
            created_units = []
            
            # Berechne durchschnittliche m² pro Einheit (falls Gesamtfläche angegeben)
            avg_sqm_per_unit = None
            if new_property.size_sqm and new_property.size_sqm > 0:
                avg_sqm_per_unit = int(new_property.size_sqm / units_count)
            
            for i in range(1, units_count + 1):
                unit_label = f"Wohnung {i}"
                unit = Unit(
                    owner_id=current_user.id,
                    property_id=new_property.id,
                    unit_label=unit_label,
                    size_sqm=avg_sqm_per_unit,  # Optional: gleichmäßig aufteilen
                    status=UnitStatus.VACANT,
                    unit_number=str(i).zfill(3) if i < 1000 else str(i),  # "001", "002", etc.
                )
                
                # Setze client_id falls vorhanden
                if client_id:
                    try:
                        unit.client_id = client_id
                    except Exception:
                        pass  # Falls Spalte noch nicht existiert
                
                db.add(unit)
                created_units.append(unit)
            
            logger.info(f"Created {len(created_units)} units automatically for property {new_property.id}")
        
        db.commit()
        db.refresh(new_property)
        
        logger.info(f"Property created: {new_property.id} by user {current_user.id}, client_id: {client_id}, units_count: {units_count}")
        return PropertyOut.model_validate(new_property)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating property: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create property"
        )


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific property by ID.
    """
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found"
        )
    
    return PropertyOut.model_validate(property_obj)


@router.put("/{property_id}", response_model=PropertyOut)
def update_property(
    property_id: str,
    property_data: PropertyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a property.
    """
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found"
        )
    
    try:
        # Update only provided fields
        update_data = property_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(property_obj, field, value)
        
        db.commit()
        db.refresh(property_obj)
        
        logger.info(f"Property updated: {property_id} by user {current_user.id}")
        return PropertyOut.model_validate(property_obj)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating property: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update property"
        )


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a property (only if it has no units).
    """
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found"
        )
    
    # Check if property has units
    units_count = db.query(Unit).filter(Unit.property_id == property_id).count()
    if units_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Objekt kann nicht gelöscht werden, da {units_count} Einheit(en) vorhanden {'sind' if units_count > 1 else 'ist'}. Bitte löschen Sie zuerst die Einheiten."
        )
    
    try:
        db.delete(property_obj)
        db.commit()
        logger.info(f"Property deleted: {property_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting property: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete property"
        )

