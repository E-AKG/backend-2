#!/usr/bin/env python3
"""
Script to empty all database tables (delete all rows, keep tables).
WARNING: This will delete all data from all tables!
"""

from app.db import engine, Base
from app.models import (
    user, property, unit, tenant, lease, billrun, bank, auto_match_log
)
from sqlalchemy import text

def empty_all_tables():
    """Empty all tables while preserving the table structure."""
    print("🔄 Emptying all database tables...")
    
    # Get all table names in dependency order (reverse of creation order)
    # We need to delete in reverse dependency order to respect foreign keys
    tables = [
        "auto_match_logs",      # Depends on bank_transactions and charges
        "payment_matches",      # Depends on bank_transactions and charges
        "charges",              # Depends on bill_runs and leases
        "bill_runs",            # Depends on users
        "lease_components",    # Depends on leases
        "leases",               # Depends on users, units, tenants
        "bank_transactions",    # Depends on bank_accounts
        "bank_accounts",       # Depends on users
        "units",                # Depends on users, properties
        "properties",           # Depends on users
        "tenants",              # Depends on users
        "users",                # Top level (but we keep it last to ensure all FKs are cleared)
    ]
    
    with engine.begin() as conn:
        # Disable foreign key checks temporarily to allow deletion in any order
        # This is PostgreSQL-specific
        conn.execute(text("SET session_replication_role = 'replica';"))
        
        try:
            # Delete from each table
            for table_name in tables:
                result = conn.execute(text(f"DELETE FROM {table_name}"))
                rowcount = result.rowcount
                if rowcount > 0:
                    print(f"   ✅ Emptied {table_name} ({rowcount} rows deleted)")
                else:
                    print(f"   ℹ️  {table_name} (already empty)")
            
            # Also reset sequences for tables with auto-increment IDs (users table)
            # This ensures the next ID starts from 1 again
            try:
                conn.execute(text("ALTER SEQUENCE users_id_seq RESTART WITH 1"))
                print("   ✅ Reset users_id sequence")
            except Exception as e:
                # Sequence might not exist or be named differently
                print(f"   ⚠️  Could not reset users_id sequence: {e}")
            
        finally:
            # Re-enable foreign key checks
            conn.execute(text("SET session_replication_role = 'origin';"))
    
    print("\n✅ All tables emptied successfully!")
    print("📋 Tables are now empty and ready to be filled with new data.\n")

if __name__ == "__main__":
    try:
        empty_all_tables()
    except Exception as e:
        print(f"\n❌ Error emptying tables: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

