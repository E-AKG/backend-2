from sqlalchemy import Column, Integer, String, Boolean, Enum
from .base import Base, TimestampMixin
import enum


class UserRole(str, enum.Enum):
    """Rolle des Benutzers"""
    ADMIN = "admin"  # Vollzugriff
    STAFF = "staff"  # Mitarbeiter (eingeschränkter Zugriff)
    PORTAL_USER = "portal_user"  # Mieter (nur Portal-Zugriff)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False)
    # role ist nullable=True für Migration-Kompatibilität, wird in main.py migriert
    role = Column(String(50), default='admin', nullable=True)  # Standard: 'admin'
    
    # E-Mail-Einstellungen für Benachrichtigungen
    notification_from_email = Column(String(255), nullable=True)  # Absender-E-Mail für Benachrichtigungen (optional, falls nicht gesetzt wird User.email verwendet)