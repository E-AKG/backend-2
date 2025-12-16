from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
from datetime import date, datetime
from decimal import Decimal
import re


class BankAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=255, description="Kontoname")
    iban: Optional[str] = Field(None, max_length=34, description="IBAN")
    bank_name: Optional[str] = Field(None, max_length=255, description="Bankname")
    
    @field_validator('iban')
    @classmethod
    def validate_iban(cls, v):
        if v is None or v == "":
            return v
        
        # Entferne Leerzeichen
        iban = v.replace(" ", "").upper()
        
        # Basis-Validierung: 2 Buchstaben + 2 Ziffern + bis zu 30 alphanumerisch
        if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$', iban):
            raise ValueError('Ungültige IBAN. Format: DE89370400440532013000')
        
        # Längenprüfung für Deutschland
        if iban.startswith('DE') and len(iban) != 22:
            raise ValueError('Deutsche IBAN muss 22 Zeichen lang sein')
        
        return iban


class BankAccountUpdate(BaseModel):
    account_name: Optional[str] = Field(None, min_length=1, max_length=255)
    iban: Optional[str] = Field(None, max_length=34)
    bank_name: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class BankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: int
    account_name: str
    iban: Optional[str]
    bank_name: Optional[str]
    finapi_account_id: Optional[str]
    is_active: bool
    last_sync: Optional[date]
    balance: Optional[Decimal]
    created_at: datetime
    updated_at: datetime


class BankTransactionCreate(BaseModel):
    """Normalerweise wird das von FinAPI automatisch erstellt"""
    bank_account_id: Optional[str] = None  # Optional für manuelle Buchungen
    transaction_date: date
    amount: Decimal
    purpose: Optional[str] = None
    counterpart_name: Optional[str] = Field(None, max_length=255)
    counterpart_iban: Optional[str] = Field(None, max_length=34)
    description: Optional[str] = None  # Alias für purpose (wird zu purpose gemappt)


class BankTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bank_account_id: str
    transaction_date: date
    booking_date: Optional[date]
    amount: Decimal
    purpose: Optional[str]
    counterpart_name: Optional[str]
    counterpart_iban: Optional[str]
    finapi_transaction_id: Optional[str]
    is_matched: bool
    matched_amount: Decimal
    created_at: datetime
    updated_at: datetime


class PaymentMatchCreate(BaseModel):
    transaction_id: str = Field(..., description="Banktransaktion ID")
    charge_id: str = Field(..., description="Sollbuchung ID")
    matched_amount: Decimal = Field(..., gt=0, description="Zugeordneter Betrag")
    is_automatic: bool = Field(default=False, description="Automatisch zugeordnet?")
    note: Optional[str] = Field(None, max_length=500)


class PaymentMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    transaction_id: str
    charge_id: str
    matched_amount: Decimal
    is_automatic: bool
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class FinAPIConnectRequest(BaseModel):
    """Request um FinAPI-Verbindung herzustellen"""
    bank_account_id: str
    finapi_credentials: dict  # Wird später mit echten FinAPI-Parametern gefüllt

