from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Boolean, Text
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class DocumentType(str, enum.Enum):
    """Typ des Dokuments"""
    CONTRACT = "contract"  # Mietvertrag
    INVOICE = "invoice"  # Rechnung
    RECEIPT = "receipt"  # Quittung
    STATEMENT = "statement"  # Abrechnung
    CERTIFICATE = "certificate"  # Energieausweis, etc.
    PROTOCOL = "protocol"  # Protokoll (Eigentümerversammlung)
    OTHER = "other"  # Sonstiges


class Document(Base, TimestampMixin):
    """
    Dokument (DMS)
    Zentrale Dokumentenverwaltung
    """
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Datei-Informationen
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # Pfad zur Datei
    file_size = Column(Integer, nullable=True)  # Größe in Bytes
    mime_type = Column(String(100), nullable=True)  # MIME-Type
    
    # Metadaten
    document_type = Column(Enum(DocumentType), default=DocumentType.OTHER, nullable=False)
    title = Column(String(255), nullable=True)  # Anzeigename
    description = Column(Text, nullable=True)
    
    # Datum (falls relevant)
    document_date = Column(Date, nullable=True)  # Datum des Dokuments (z.B. Rechnungsdatum)
    
    # Verknüpfungen (optional, mehrere möglich)
    property_id = Column(String, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    accounting_id = Column(String, ForeignKey("accountings.id", ondelete="SET NULL"), nullable=True, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Tags (für Suche)
    tags = Column(Text, nullable=True)  # Komma-getrennte Tags
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    property = relationship("Property", foreign_keys=[property_id])
    unit = relationship("Unit", foreign_keys=[unit_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    lease = relationship("Lease", foreign_keys=[lease_id])
    ticket = relationship("Ticket", foreign_keys=[ticket_id])
    accounting = relationship("Accounting", foreign_keys=[accounting_id])
    charge = relationship("Charge", foreign_keys=[charge_id])
    
    __table_args__ = (
        Index('ix_documents_type', 'document_type'),
        Index('ix_documents_property', 'property_id'),
        Index('ix_documents_tenant', 'tenant_id'),
    )

