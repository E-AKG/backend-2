from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Index, Enum
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class PortalUser(Base, TimestampMixin):
    """
    Mieterportal-Benutzer
    Separate Tabelle für Mieter-Login (nicht User-Tabelle)
    """
    __tablename__ = "portal_users"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="CASCADE"), nullable=True, index=True)  # Optional: spezifischer Vertrag
    
    # Login-Daten
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # Gehashtes Passwort
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # E-Mail verifiziert
    
    # Verifikation
    verification_token = Column(String(255), nullable=True)
    verification_token_expires_at = Column(String, nullable=True)  # ISO datetime string
    
    # Relationships
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    lease = relationship("Lease", foreign_keys=[lease_id])
    
    __table_args__ = (
        Index('ix_portal_users_tenant', 'tenant_id'),
        # Index für email wird automatisch durch unique=True erstellt
    )

