from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, DateTime
from datetime import datetime
import uuid
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models"""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


def generate_uuid():
    """Generate a new UUID for primary keys"""
    return str(uuid.uuid4())

