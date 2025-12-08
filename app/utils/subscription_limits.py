from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db import get_db
from ..models.subscription import Subscription, SubscriptionStatus
from ..models.user import User
from ..models.unit import Unit
from ..models.bank import CsvFile
from ..models.bank import PaymentMatch
from ..models.billrun import Charge, BillRun
from .deps import get_current_user


def has_active_subscription(user: User, db: Session) -> bool:
    """
    Check if user has an active subscription.
    Returns True if subscription is active, False otherwise (trial/free user).
    """
    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    
    if not subscription:
        return False  # Trial/Free user
    
    if subscription.status == SubscriptionStatus.ACTIVE:
        return True
    
    return False


def check_unit_limit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """
    Check if user has reached the unit limit.
    Currently: No limits for all users
    
    Raises HTTPException if limit reached.
    """
    # No limits - all users can create unlimited units
    return


def check_csv_upload_limit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """
    Check if user has reached the CSV upload limit.
    Currently: No limits for all users
    
    Raises HTTPException if limit reached.
    """
    # No limits - all users can upload unlimited CSV files
    return


def check_match_limit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """
    Check if user has already performed a match operation.
    Currently: No limits for all users
    
    Raises HTTPException if limit reached.
    """
    # No limits - all users can perform unlimited matches
    return


def get_user_limits(user: User, db: Session) -> dict:
    """
    Get current usage and limits for a user.
    Returns dict with limits and current usage.
    Currently: All users have unlimited access.
    """
    has_subscription = has_active_subscription(user, db)
    
    unit_count = db.query(func.count(Unit.id)).filter(
        Unit.owner_id == user.id
    ).scalar()
    
    csv_count = db.query(func.count(CsvFile.id)).filter(
        CsvFile.owner_id == user.id
    ).scalar()
    
    match_count = db.query(func.count(PaymentMatch.id)).join(
        Charge, PaymentMatch.charge_id == Charge.id
    ).join(
        BillRun, Charge.bill_run_id == BillRun.id
    ).filter(
        BillRun.owner_id == user.id
    ).scalar()
    
    # All users have unlimited access
    return {
        "has_subscription": has_subscription,
        "units": {"used": unit_count, "limit": None, "unlimited": True},
        "csv_files": {"used": csv_count, "limit": None, "unlimited": True},
        "matches": {"used": match_count, "limit": None, "unlimited": True},
    }

