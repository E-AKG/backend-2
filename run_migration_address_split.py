#!/usr/bin/env python3
"""
Migration: Adresse aufteilen in Adresse (Straße), PLZ, Ort
"""
from app.db import engine
from sqlalchemy import text

tables = [
    ("tenants", "address"),
    ("service_providers", "address"),
    ("owners", "address"),
    ("clients", "address"),
    ("properties", "address"),
]

migration_parts = []
for table, col in tables:
    migration_parts.append(f"""
-- {table}
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS address_street VARCHAR(255);
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20);
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS city VARCHAR(100);
-- Bestehende Adresse nach address_street kopieren
UPDATE {table} SET address_street = {col} WHERE {col} IS NOT NULL;
""")

migration_sql = "\n".join(migration_parts)

print("🔄 Migration: Adresse → Adresse, PLZ, Ort...")
try:
    with engine.begin() as conn:
        conn.execute(text(migration_sql))
    print("✅ Migration erfolgreich! (address_street, postal_code, city hinzugefügt)")
except Exception as e:
    print(f"❌ Fehler: {str(e)}")
    raise
