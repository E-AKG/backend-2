import stripe
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from dateutil.relativedelta import relativedelta
from ..config import settings
from ..models.subscription import Subscription, SubscriptionStatus
from ..models.payment import Payment, PaymentStatus, PaymentMethod
from ..models.user import User
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Initialize Stripe
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY not set - Stripe functionality will be disabled")


def create_checkout_session(
    user: User,
    plan_name: str,
    price_per_month: int,
    success_url: str,
    cancel_url: str,
    db: Session
) -> dict:
    """
    Create a Stripe Checkout Session for subscription payment.
    
    Returns:
        dict: Contains session_id and url
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured. Please add STRIPE_SECRET_KEY to your .env file. See STRIPE_SETUP.md for instructions."
        )
    
    try:
        # Create or get Stripe customer
        customer_id = None
        subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        
        if subscription and subscription.stripe_customer_id:
            customer_id = subscription.stripe_customer_id
        else:
            # Create new Stripe customer
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"user_id": str(user.id)}
            )
            customer_id = customer.id
            
            # Update or create subscription record
            if subscription:
                subscription.stripe_customer_id = customer_id
            else:
                subscription = Subscription(
                    user_id=user.id,
                    stripe_customer_id=customer_id,
                    plan_name=plan_name,
                    price_per_month=price_per_month,
                    status=SubscriptionStatus.TRIAL
                )
                db.add(subscription)
            db.commit()
        
        # Create Stripe Checkout Session
        # Use price_id if configured, otherwise create a one-time payment
        if settings.STRIPE_PRICE_ID:
            # Recurring subscription
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card', 'paypal'],
                mode='subscription',
                line_items=[{
                    'price': settings.STRIPE_PRICE_ID,
                    'quantity': 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "plan_name": plan_name
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id),
                        "plan_name": plan_name
                    }
                }
            )
        else:
            # Subscription mode (fallback - creates price on the fly)
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card', 'paypal'],
                mode='subscription',
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {
                            'name': f'{plan_name} Plan - Monthly',
                        },
                        'unit_amount': price_per_month,
                        'recurring': {
                            'interval': 'month',
                        },
                    },
                    'quantity': 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "plan_name": plan_name
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id),
                        "plan_name": plan_name
                    }
                }
            )
        
        logger.info(f"Created Stripe checkout session for user {user.id}: {session.id}")
        
        return {
            "session_id": session.id,
            "url": session.url
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment processing error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating checkout session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the checkout session."
        )


def handle_webhook_event(event: dict, db: Session) -> None:
    """
    Handle Stripe webhook events.
    
    Events handled:
    - checkout.session.completed: Payment successful, activate subscription
    - customer.subscription.created: Subscription created
    - customer.subscription.updated: Subscription updated
    - customer.subscription.deleted: Subscription cancelled
    - invoice.payment_succeeded: Monthly payment succeeded
    - invoice.payment_failed: Monthly payment failed
    """
    event_type = event.get('type')
    data = event.get('data', {}).get('object', {})
    
    try:
        if event_type == 'checkout.session.completed':
            # Payment successful, activate subscription
            session = data
            user_id = int(session.get('metadata', {}).get('user_id'))
            plan_name = session.get('metadata', {}).get('plan_name', 'Basic')
            
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found for checkout session {session.get('id')}")
                return
            
            subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
            
            if session.get('mode') == 'subscription':
                # Get subscription from Stripe
                stripe_subscription_id = session.get('subscription')
                if stripe_subscription_id:
                    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                    
                    if subscription:
                        subscription.stripe_subscription_id = stripe_subscription_id
                        subscription.status = SubscriptionStatus.ACTIVE
                        subscription.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start)
                        subscription.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end)
                    else:
                        subscription = Subscription(
                            user_id=user_id,
                            stripe_subscription_id=stripe_subscription_id,
                            stripe_customer_id=stripe_sub.customer,
                            plan_name=plan_name,
                            price_per_month=int(stripe_sub.items.data[0].price.unit_amount),
                            status=SubscriptionStatus.ACTIVE,
                            current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
                            current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end)
                        )
                        db.add(subscription)
            else:
                # One-time payment - create subscription manually
                if subscription:
                    subscription.status = SubscriptionStatus.ACTIVE
                    subscription.current_period_start = datetime.utcnow()
                    # Set period end to 1 month from now
                    subscription.current_period_end = datetime.utcnow() + relativedelta(months=1)
                else:
                    subscription = Subscription(
                        user_id=user_id,
                        stripe_customer_id=session.get('customer'),
                        plan_name=plan_name,
                        price_per_month=1000,  # Default 10 EUR
                        status=SubscriptionStatus.ACTIVE,
                        current_period_start=datetime.utcnow(),
                        current_period_end=datetime.utcnow() + relativedelta(months=1)
                    )
                    db.add(subscription)
            
            # Create payment record
            payment_intent_id = session.get('payment_intent')
            amount_total = session.get('amount_total', 0)
            
            payment = Payment(
                user_id=user_id,
                subscription_id=subscription.id if subscription else None,
                stripe_payment_intent_id=payment_intent_id,
                amount=amount_total,
                currency='eur',
                status=PaymentStatus.SUCCEEDED,
                description=f"Subscription payment for {plan_name} plan"
            )
            db.add(payment)
            db.commit()
            logger.info(f"Activated subscription for user {user_id}")
        
        elif event_type == 'customer.subscription.updated':
            # Subscription updated (e.g., plan changed, status changed)
            stripe_subscription_id = data.get('id')
            subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_subscription_id
            ).first()
            
            if subscription:
                status_map = {
                    'active': SubscriptionStatus.ACTIVE,
                    'canceled': SubscriptionStatus.CANCELLED,
                    'past_due': SubscriptionStatus.PAST_DUE,
                    'trialing': SubscriptionStatus.TRIAL,
                }
                subscription.status = status_map.get(data.get('status'), SubscriptionStatus.ACTIVE)
                subscription.current_period_start = datetime.fromtimestamp(data.get('current_period_start', 0))
                subscription.current_period_end = datetime.fromtimestamp(data.get('current_period_end', 0))
                subscription.cancel_at_period_end = data.get('cancel_at_period_end', False)
                
                if subscription.status == SubscriptionStatus.CANCELLED:
                    subscription.cancelled_at = datetime.utcnow()
                
                db.commit()
                logger.info(f"Updated subscription {subscription.id} from webhook")
        
        elif event_type == 'customer.subscription.deleted':
            # Subscription cancelled
            stripe_subscription_id = data.get('id')
            subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_subscription_id
            ).first()
            
            if subscription:
                subscription.status = SubscriptionStatus.CANCELLED
                subscription.cancelled_at = datetime.utcnow()
                subscription.cancel_at_period_end = False
                db.commit()
                logger.info(f"Cancelled subscription {subscription.id} from webhook")
        
        elif event_type == 'invoice.payment_succeeded':
            # Monthly payment succeeded
            invoice = data
            stripe_subscription_id = invoice.get('subscription')
            
            if stripe_subscription_id:
                subscription = db.query(Subscription).filter(
                    Subscription.stripe_subscription_id == stripe_subscription_id
                ).first()
                
                if subscription:
                    # Update period dates
                    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                    subscription.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start)
                    subscription.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end)
                    subscription.status = SubscriptionStatus.ACTIVE
                    
                    # Create payment record
                    payment = Payment(
                        user_id=subscription.user_id,
                        subscription_id=subscription.id,
                        stripe_payment_intent_id=invoice.get('payment_intent'),
                        amount=invoice.get('amount_paid', 0),
                        currency=invoice.get('currency', 'eur'),
                        status=PaymentStatus.SUCCEEDED,
                        description=f"Monthly subscription payment - {subscription.plan_name}"
                    )
                    db.add(payment)
                    db.commit()
                    logger.info(f"Recorded monthly payment for subscription {subscription.id}")
        
        elif event_type == 'invoice.payment_failed':
            # Monthly payment failed
            invoice = data
            stripe_subscription_id = invoice.get('subscription')
            
            if stripe_subscription_id:
                subscription = db.query(Subscription).filter(
                    Subscription.stripe_subscription_id == stripe_subscription_id
                ).first()
                
                if subscription:
                    subscription.status = SubscriptionStatus.PAST_DUE
                    db.commit()
                    logger.warning(f"Payment failed for subscription {subscription.id}")
    
    except Exception as e:
        logger.error(f"Error handling webhook event {event_type}: {str(e)}")
        db.rollback()
        raise

