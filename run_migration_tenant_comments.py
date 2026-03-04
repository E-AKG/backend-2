#!/usr/bin/env python3
"""
Migration Script: Erstellt Tabelle tenant_comments für Gesprächsnotizen
"""
import os
from app.db import engine
from sqlalchemy import text

migration_sql = """
CREATE TABLE IF NOT EXISTS tenant_comments (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tenant_comments_tenant_id ON tenant_comments(tenant_id);
CREATE INDEX IF NOT EXISTS ix_tenant_comments_user_id ON tenant_comments(user_id) WHERE user_id IS NOT NULL;
"""

print("🔄 Führe Migration für tenant_comments (Gesprächsnotizen) aus...")

try:
    with engine.begin() as conn:
        conn.execute(text(migration_sql))
    print("✅ Migration erfolgreich abgeschlossen!")
    print("   - Tabelle tenant_comments erstellt")
except Exception as e:
    print(f"❌ Fehler bei Migration: {str(e)}")
