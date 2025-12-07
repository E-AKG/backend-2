from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_HOURS: int = 24  # 24 Stunden für längere Sessions (kann über .env überschrieben werden)
    
    # SMTP
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_FROM_EMAIL: str = ""  # Absender-E-Mail-Adresse (optional, falls nicht gesetzt wird SMTP_USER verwendet)
    
    # Frontend
    FRONTEND_URL: str
    
    # Backend (für Verifizierungs-Links in E-Mails)
    BACKEND_URL: Optional[str] = None  # Falls nicht gesetzt, wird FRONTEND_URL verwendet
    
    # App
    APP_NAME: str = "IZENIC ImmoAssist API"
    DEBUG: bool = False
    
    # FinAPI (Optional - für echte Bankverbindung)
    FINAPI_BASE_URL: Optional[str] = "https://sandbox.finapi.io"
    FINAPI_CLIENT_ID: Optional[str] = None
    FINAPI_CLIENT_SECRET: Optional[str] = None
    
    # Stripe (für Zahlungen)
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_ID: Optional[str] = None  # Stripe Price ID für das Abo (10 EUR/Monat)

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra fields in .env without errors


settings = Settings()

