from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..db import get_db
from ..models.subscription import Subscription, SubscriptionStatus
from ..models.user import User
from ..schemas.subscription_schema import (
    SubscriptionResponse,
    SubscriptionUpdate,
    CheckoutSessionCreate,
    CheckoutSessionResponse
)
from ..services.stripe_service import create_checkout_session
from ..utils.deps import get_current_user
from ..utils.subscription_limits import get_user_limits
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.get("/me", response_model=SubscriptionResponse)
def get_my_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's subscription"""
    subscription = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    
    if not subscription:
        # Return a default trial subscription
        return SubscriptionResponse(
            id=0,
            user_id=current_user.id,
            stripe_subscription_id=None,
            stripe_customer_id=None,
            status=SubscriptionStatus.TRIAL,
            plan_name="Trial",
            price_per_month=0,
            current_period_start=None,
            current_period_end=None,
            cancel_at_period_end=False,
            cancelled_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    return subscription


@router.get("/limits")
def get_limits(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current usage and limits for the user"""
    return get_user_limits(current_user, db)


@router.post("/checkout", response_model=CheckoutSessionResponse)
def create_checkout(
    checkout_data: CheckoutSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session for subscription payment"""
    try:
        result = create_checkout_session(
            user=current_user,
            plan_name=checkout_data.plan_name,
            price_per_month=checkout_data.price_per_month,
            success_url=checkout_data.success_url,
            cancel_url=checkout_data.cancel_url,
            db=db
        )
        
        return CheckoutSessionResponse(**result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )


@router.post("/cancel")
def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel subscription (at period end)"""
    subscription = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found"
        )
    
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is not active"
        )
    
    try:
        import stripe
        from ..config import settings
        
        if subscription.stripe_subscription_id and settings.STRIPE_SECRET_KEY:
            # Cancel at period end via Stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=True
            )
            subscription.cancel_at_period_end = True
        else:
            # Manual cancellation
            subscription.status = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = datetime.utcnow()
            subscription.cancel_at_period_end = False
        
        db.commit()
        logger.info(f"Subscription {subscription.id} cancelled for user {current_user.id}")
        
        return {"message": "Subscription will be cancelled at the end of the billing period"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )


@router.post("/reactivate")
def reactivate_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reactivate a cancelled subscription"""
    subscription = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found"
        )
    
    if subscription.status == SubscriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already active"
        )
    
    try:
        import stripe
        from ..config import settings
        
        if subscription.stripe_subscription_id and settings.STRIPE_SECRET_KEY:
            # Reactivate via Stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=False
            )
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.cancel_at_period_end = False
            subscription.cancelled_at = None
        else:
            # Manual reactivation
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.cancel_at_period_end = False
            subscription.cancelled_at = None
        
        db.commit()
        logger.info(f"Subscription {subscription.id} reactivated for user {current_user.id}")
        
        return {"message": "Subscription reactivated successfully"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error reactivating subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reactivate subscription"
        )

