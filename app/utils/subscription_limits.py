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
    Trial users: max 1 unit
    Paid users: unlimited
    
    Raises HTTPException if limit reached.
    """
    if has_active_subscription(current_user, db):
        return  # Paid users have no limits
    
    # Count existing units for trial user
    unit_count = db.query(func.count(Unit.id)).filter(
        Unit.owner_id == current_user.id
    ).scalar()
    
    if unit_count >= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "unit_limit_reached",
                "message": "Sie haben das Limit von 1 Einheit erreicht. Bitte upgraden Sie auf ein Abonnement, um weitere Einheiten anzulegen.",
                "current_count": unit_count,
                "limit": 1,
                "upgrade_required": True
            }
        )


def check_csv_upload_limit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """
    Check if user has reached the CSV upload limit.
    Trial users: max 1 CSV file
    Paid users: unlimited
    
    Raises HTTPException if limit reached.
    """
    if has_active_subscription(current_user, db):
        return  # Paid users have no limits
    
    # Count existing CSV files for trial user
    csv_count = db.query(func.count(CsvFile.id)).filter(
        CsvFile.owner_id == current_user.id
    ).scalar()
    
    if csv_count >= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "csv_limit_reached",
                "message": "Sie haben das Limit von 1 CSV-Datei erreicht. Bitte upgraden Sie auf ein Abonnement, um weitere CSV-Dateien hochzuladen.",
                "current_count": csv_count,
                "limit": 1,
                "upgrade_required": True
            }
        )


def check_match_limit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """
    Check if user has already performed a match operation.
    Trial users: max 1 match operation
    Paid users: unlimited
    
    Raises HTTPException if limit reached.
    """
    if has_active_subscription(current_user, db):
        return  # Paid users have no limits
    
    # Count existing payment matches for trial user
    # Check if user has any charges with matches
    # Charge has no owner_id, need to join through BillRun
    match_count = db.query(func.count(PaymentMatch.id)).join(
        Charge, PaymentMatch.charge_id == Charge.id
    ).join(
        BillRun, Charge.bill_run_id == BillRun.id
    ).filter(
        BillRun.owner_id == current_user.id
    ).scalar()
    
    if match_count >= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "match_limit_reached",
                "message": "Sie haben das Limit von 1 Abgleich erreicht. Bitte upgraden Sie auf ein Abonnement, um weitere Abgleiche durchzuführen.",
                "current_count": match_count,
                "limit": 1,
                "upgrade_required": True
            }
        )


def get_user_limits(user: User, db: Session) -> dict:
    """
    Get current usage and limits for a user.
    Returns dict with limits and current usage.
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
    
    if has_subscription:
        return {
            "has_subscription": True,
            "units": {"used": unit_count, "limit": None, "unlimited": True},
            "csv_files": {"used": csv_count, "limit": None, "unlimited": True},
            "matches": {"used": match_count, "limit": None, "unlimited": True},
        }
    else:
        return {
            "has_subscription": False,
            "units": {"used": unit_count, "limit": 1, "unlimited": False},
            "csv_files": {"used": csv_count, "limit": 1, "unlimited": False},
            "matches": {"used": match_count, "limit": 1, "unlimited": False},
        }

