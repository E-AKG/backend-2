from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from ..models.payment import PaymentStatus, PaymentMethod


class PaymentResponse(BaseModel):
    id: int
    user_id: int
    subscription_id: Optional[int]
    stripe_payment_intent_id: Optional[str]
    amount: int  # In cents
    currency: str
    status: PaymentStatus
    payment_method: Optional[PaymentMethod]
    description: Optional[str]
    receipt_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaymentHistoryResponse(BaseModel):
    payments: list[PaymentResponse]
    total: int

