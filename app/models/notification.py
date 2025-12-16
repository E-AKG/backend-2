from sqlalchemy import Column, String, Integer, ForeignKey, Index, Enum, Text, DateTime
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class NotificationStatus(str, enum.Enum):
    """Status der Benachrichtigung"""
    PENDING = "pending"  # Ausstehend
    SENT = "sent"  # Erfolgreich gesendet
    FAILED = "failed"  # Fehlgeschlagen


class NotificationType(str, enum.Enum):
    """Typ der Benachrichtigung"""
    BK_PUBLISHED = "bk_published"  # Betriebskostenabrechnung veröffentlicht
    EMAIL_VERIFICATION = "email_verification"  # E-Mail-Verifizierung
    PORTAL_INVITATION = "portal_invitation"  # Portal-Einladung
    OTHER = "other"  # Sonstiges


class Notification(Base, TimestampMixin):
    """
    Log für gesendete Benachrichtigungen (E-Mails)
    """
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=generate_uuid)
    
    # Empfänger
    recipient_email = Column(String(255), nullable=False, index=True)
    recipient_id = Column(String, nullable=True)  # portal_user_id oder tenant_id
    
    # Benachrichtigungs-Details
    notification_type = Column(Enum(NotificationType), nullable=False)
    status = Column(Enum(NotificationStatus), default=NotificationStatus.PENDING, nullable=False)
    
    # Inhalt
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)  # E-Mail-Body (optional, für Logging)
    
    # Fehler-Info
    error_message = Column(Text, nullable=True)  # Fehlermeldung bei failed
    
    # Verknüpfung zu Dokument/Entity
    document_id = Column(String, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Zeitstempel
    sent_at = Column(DateTime(timezone=True), nullable=True)  # Wann gesendet
    
    # Relationships
    document = relationship("Document", foreign_keys=[document_id])
    
    __table_args__ = (
        Index('ix_notifications_recipient', 'recipient_email'),
        Index('ix_notifications_status', 'status'),
        Index('ix_notifications_type', 'notification_type'),
    )

