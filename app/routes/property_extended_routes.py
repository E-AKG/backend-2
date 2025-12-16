from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List
import logging

from ..utils.deps import get_current_user, get_db
from ..models.user import User
from ..models.property import Property
from ..models.property_insurance import PropertyInsurance, InsuranceType
from ..models.property_bank_account import PropertyBankAccount, PropertyAccountType
from ..models.allocation_key import AllocationKey, AllocationMethod
from ..schemas.property_extended_schema import (
    PropertyInsuranceCreate, PropertyInsuranceUpdate, PropertyInsuranceOut,
    PropertyBankAccountCreate, PropertyBankAccountUpdate, PropertyBankAccountOut,
    AllocationKeyCreate, AllocationKeyUpdate, AllocationKeyOut
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== Versicherungen ==========

@router.get("/api/properties/{property_id}/insurances", response_model=List[PropertyInsuranceOut])
def list_property_insurances(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Versicherungen für ein Objekt"""
    # Prüfe, ob Objekt existiert und dem Benutzer gehört
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    insurances = db.query(PropertyInsurance).filter(
        PropertyInsurance.property_id == property_id,
        PropertyInsurance.owner_id == current_user.id
    ).all()
    
    return insurances


@router.post("/api/properties/{property_id}/insurances", response_model=PropertyInsuranceOut, status_code=status.HTTP_201_CREATED)
def create_property_insurance(
    property_id: str,
    insurance_data: PropertyInsuranceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erstelle eine neue Versicherung für ein Objekt"""
    # Prüfe, ob Objekt existiert und dem Benutzer gehört
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    try:
        new_insurance = PropertyInsurance(
            property_id=property_id,
            owner_id=current_user.id,
            **insurance_data.model_dump()
        )
        db.add(new_insurance)
        db.commit()
        db.refresh(new_insurance)
        
        logger.info(f"Versicherung erstellt: {new_insurance.id} für Objekt {property_id}")
        return new_insurance
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating insurance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Erstellen der Versicherung"
        )


@router.put("/api/property-insurances/{insurance_id}", response_model=PropertyInsuranceOut)
def update_property_insurance(
    insurance_id: str,
    insurance_data: PropertyInsuranceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere eine Versicherung"""
    insurance = db.query(PropertyInsurance).filter(
        PropertyInsurance.id == insurance_id,
        PropertyInsurance.owner_id == current_user.id
    ).first()
    
    if not insurance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Versicherung nicht gefunden"
        )
    
    try:
        update_data = insurance_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(insurance, key, value)
        
        db.commit()
        db.refresh(insurance)
        
        logger.info(f"Versicherung aktualisiert: {insurance_id}")
        return insurance
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating insurance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Aktualisieren der Versicherung"
        )


@router.delete("/api/property-insurances/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property_insurance(
    insurance_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche eine Versicherung"""
    insurance = db.query(PropertyInsurance).filter(
        PropertyInsurance.id == insurance_id,
        PropertyInsurance.owner_id == current_user.id
    ).first()
    
    if not insurance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Versicherung nicht gefunden"
        )
    
    try:
        db.delete(insurance)
        db.commit()
        logger.info(f"Versicherung gelöscht: {insurance_id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting insurance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Löschen der Versicherung"
        )


# ========== Property Bank Accounts ==========

@router.get("/api/properties/{property_id}/bank-accounts", response_model=List[PropertyBankAccountOut])
def list_property_bank_accounts(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Bankkonten für ein Objekt"""
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    accounts = db.query(PropertyBankAccount).filter(
        PropertyBankAccount.property_id == property_id,
        PropertyBankAccount.owner_id == current_user.id
    ).all()
    
    return accounts


@router.post("/api/properties/{property_id}/bank-accounts", response_model=PropertyBankAccountOut, status_code=status.HTTP_201_CREATED)
def create_property_bank_account(
    property_id: str,
    account_data: PropertyBankAccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erstelle ein neues Bankkonto für ein Objekt"""
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    try:
        new_account = PropertyBankAccount(
            property_id=property_id,
            owner_id=current_user.id,
            **account_data.model_dump()
        )
        db.add(new_account)
        db.commit()
        db.refresh(new_account)
        
        logger.info(f"Bankkonto erstellt: {new_account.id} für Objekt {property_id}")
        return new_account
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating bank account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Erstellen des Bankkontos"
        )


@router.put("/api/property-bank-accounts/{account_id}", response_model=PropertyBankAccountOut)
def update_property_bank_account(
    account_id: str,
    account_data: PropertyBankAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere ein Bankkonto"""
    account = db.query(PropertyBankAccount).filter(
        PropertyBankAccount.id == account_id,
        PropertyBankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bankkonto nicht gefunden"
        )
    
    try:
        update_data = account_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(account, key, value)
        
        db.commit()
        db.refresh(account)
        
        logger.info(f"Bankkonto aktualisiert: {account_id}")
        return account
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating bank account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Aktualisieren des Bankkontos"
        )


@router.delete("/api/property-bank-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property_bank_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche ein Bankkonto"""
    account = db.query(PropertyBankAccount).filter(
        PropertyBankAccount.id == account_id,
        PropertyBankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bankkonto nicht gefunden"
        )
    
    try:
        db.delete(account)
        db.commit()
        logger.info(f"Bankkonto gelöscht: {account_id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting bank account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Löschen des Bankkontos"
        )


# ========== Verteilerschlüssel ==========

@router.get("/api/properties/{property_id}/allocation-keys", response_model=List[AllocationKeyOut])
def list_allocation_keys(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Verteilerschlüssel für ein Objekt"""
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    keys = db.query(AllocationKey).filter(
        AllocationKey.property_id == property_id,
        AllocationKey.owner_id == current_user.id
    ).all()
    
    return keys


@router.post("/api/properties/{property_id}/allocation-keys", response_model=AllocationKeyOut, status_code=status.HTTP_201_CREATED)
def create_allocation_key(
    property_id: str,
    key_data: AllocationKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erstelle einen neuen Verteilerschlüssel für ein Objekt"""
    property_obj = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    
    if not property_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objekt nicht gefunden"
        )
    
    try:
        new_key = AllocationKey(
            property_id=property_id,
            owner_id=current_user.id,
            **key_data.model_dump()
        )
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        
        logger.info(f"Verteilerschlüssel erstellt: {new_key.id} für Objekt {property_id}")
        return new_key
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating allocation key: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Erstellen des Verteilerschlüssels"
        )


@router.put("/api/allocation-keys/{key_id}", response_model=AllocationKeyOut)
def update_allocation_key(
    key_id: str,
    key_data: AllocationKeyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere einen Verteilerschlüssel"""
    key = db.query(AllocationKey).filter(
        AllocationKey.id == key_id,
        AllocationKey.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verteilerschlüssel nicht gefunden"
        )
    
    try:
        update_data = key_data.model_dump(exclude_unset=True)
        for key_attr, value in update_data.items():
            setattr(key, key_attr, value)
        
        db.commit()
        db.refresh(key)
        
        logger.info(f"Verteilerschlüssel aktualisiert: {key_id}")
        return key
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating allocation key: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Aktualisieren des Verteilerschlüssels"
        )


@router.delete("/api/allocation-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche einen Verteilerschlüssel"""
    key = db.query(AllocationKey).filter(
        AllocationKey.id == key_id,
        AllocationKey.owner_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verteilerschlüssel nicht gefunden"
        )
    
    try:
        db.delete(key)
        db.commit()
        logger.info(f"Verteilerschlüssel gelöscht: {key_id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting allocation key: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Löschen des Verteilerschlüssels"
        )

