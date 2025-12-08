from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_HOURS: int = 24  # 24 Stunden für längere Sessions (kann über .env überschrieben werden)
    
    # SMTP (Fallback, wenn SendGrid API nicht verwendet wird)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = ""  # Absender-E-Mail-Adresse (optional, falls nicht gesetzt wird SMTP_USER verwendet)
    
    # SendGrid API (bevorzugt, funktioniert besser mit Render)
    SENDGRID_API_KEY: Optional[str] = None  # Wenn gesetzt, wird SendGrid API statt SMTP verwendet
    
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

