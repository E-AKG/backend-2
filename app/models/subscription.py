from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin
from datetime import datetime
import enum


class SubscriptionStatus(str, enum.Enum):
    """Subscription status enum"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"
    TRIAL = "trial"


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Stripe fields
    stripe_subscription_id = Column(String, unique=True, nullable=True, index=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_price_id = Column(String, nullable=True)
    
    # Subscription details
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.TRIAL, nullable=False)
    plan_name = Column(String, default="Basic", nullable=False)  # Basic, Pro, etc.
    price_per_month = Column(Integer, nullable=False)  # Price in cents (e.g., 1000 = 10.00 EUR)
    
    # Dates
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", backref="subscription")
    payments = relationship("Payment", back_populates="subscription", cascade="all, delete-orphan")

