from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..db import get_db
from ..models.subscription import Subscription, SubscriptionStatus
from ..models.user import User
from .deps import get_current_user
from datetime import datetime


def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency that checks if the current user has an active subscription.
    Raises HTTPException if subscription is not active.
    
    Use this dependency in routes that require an active subscription.
    """
    subscription = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    
    # If no subscription exists, user is on trial
    if not subscription:
        # Allow trial users (you can change this behavior)
        return current_user
    
    # Check if subscription is active
    if subscription.status == SubscriptionStatus.ACTIVE:
        # Check if subscription period has expired
        if subscription.current_period_end and subscription.current_period_end < datetime.utcnow():
            # Period expired, but subscription might still be active (Stripe handles this)
            # For now, we'll allow access and let Stripe webhooks handle the status update
            return current_user
        return current_user
    
    # Check if subscription is cancelled but still in period
    if subscription.status == SubscriptionStatus.CANCELLED and subscription.cancel_at_period_end:
        if subscription.current_period_end and subscription.current_period_end >= datetime.utcnow():
            return current_user
    
    # Subscription is not active
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Active subscription required. Please subscribe to continue using the service."
    )

