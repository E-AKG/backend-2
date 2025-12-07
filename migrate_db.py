#!/usr/bin/env python3
"""
Database migration script - drops all tables and recreates them.
WARNING: This will delete all data!
"""

from app.db import engine, Base
from app.models import user, property, unit, tenant, lease, billrun, bank
from sqlalchemy import text

print("🔄 Dropping all existing tables with CASCADE...")

# Drop all tables with CASCADE to handle dependencies
with engine.begin() as conn:
    # Disable foreign key checks temporarily
    conn.execute(text("SET session_replication_role = 'replica';"))
    
    # Drop all tables
    Base.metadata.drop_all(bind=conn)
    
    # Re-enable foreign key checks
    conn.execute(text("SET session_replication_role = 'origin';"))

print("✅ All tables dropped")

print("\n🔄 Creating all tables with new schema...")
Base.metadata.create_all(bind=engine)
print("✅ All tables created successfully!")

print("\n📋 Created tables:")
for table in Base.metadata.sorted_tables:
    print(f"   - {table.name}")

print("\n✨ Database migration complete! You can now run the backend server.")

