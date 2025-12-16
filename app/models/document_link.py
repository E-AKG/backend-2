from sqlalchemy import Column, String, ForeignKey, Index
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


class DocumentLink(Base, TimestampMixin):
    """
    Verknüpfung zwischen Betriebskostenabrechnung (BK_STATEMENT) und Belegen (BK_RECEIPT)
    1:n Beziehung: Ein Statement kann mehrere Belege haben
    """
    __tablename__ = "document_links"

    id = Column(String, primary_key=True, default=generate_uuid)
    
    # Statement (Hauptdokument)
    statement_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Receipt (Beleg)
    receipt_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Relationships
    statement = relationship("Document", foreign_keys=[statement_id])
    receipt = relationship("Document", foreign_keys=[receipt_id])
    
    __table_args__ = (
        Index('ix_document_links_statement', 'statement_id'),
        Index('ix_document_links_receipt', 'receipt_id'),
        # Unique constraint: Ein Beleg kann nur einmal mit einem Statement verknüpft sein
        Index('ix_document_links_unique', 'statement_id', 'receipt_id', unique=True),
    )

