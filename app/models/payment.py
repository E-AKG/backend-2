from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Numeric
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin
import enum


class PaymentStatus(str, enum.Enum):
    """Payment status enum"""
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentMethod(str, enum.Enum):
    """Payment method enum"""
    CARD = "card"
    PAYPAL = "paypal"
    BANK_TRANSFER = "bank_transfer"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    
    # Stripe fields
    stripe_payment_intent_id = Column(String, unique=True, nullable=True, index=True)
    stripe_charge_id = Column(String, nullable=True)
    
    # Payment details
    amount = Column(Integer, nullable=False)  # Amount in cents (e.g., 1000 = 10.00 EUR)
    currency = Column(String, default="eur", nullable=False)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    payment_method = Column(SQLEnum(PaymentMethod), nullable=True)
    
    # Metadata
    description = Column(String, nullable=True)
    receipt_url = Column(String, nullable=True)  # Stripe receipt URL
    
    # Relationships
    user = relationship("User", backref="payments")
    subscription = relationship("Subscription", back_populates="payments")

