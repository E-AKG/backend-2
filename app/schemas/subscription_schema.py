from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from ..models.subscription import SubscriptionStatus


class SubscriptionBase(BaseModel):
    plan_name: str
    price_per_month: int  # In cents


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionResponse(BaseModel):
    id: int
    user_id: int
    stripe_subscription_id: Optional[str]
    stripe_customer_id: Optional[str]
    status: SubscriptionStatus
    plan_name: str
    price_per_month: int
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    cancelled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    status: Optional[SubscriptionStatus] = None
    cancel_at_period_end: Optional[bool] = None


class CheckoutSessionCreate(BaseModel):
    plan_name: str = "Basic"
    price_per_month: int = 1000  # 10 EUR in cents
    success_url: str
    cancel_url: str


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str

