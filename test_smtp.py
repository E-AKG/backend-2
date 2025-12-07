#!/usr/bin/env python3
"""
SMTP Configuration Test Script
Tests your SMTP settings from .env file.
"""

import smtplib
from email.mime.text import MIMEText
from app.config import settings
import sys

def test_smtp_configuration():
    """Test SMTP configuration and connection."""
    print("🔍 Testing SMTP Configuration...\n")
    
    # Check if settings are loaded
    print("📋 Current SMTP Settings:")
    print(f"   Host: {settings.SMTP_HOST}")
    print(f"   Port: {settings.SMTP_PORT}")
    print(f"   User: {settings.SMTP_USER}")
    
    # Check for placeholder values
    if "your-email" in settings.SMTP_USER.lower() or "example.com" in settings.SMTP_USER.lower():
        print("\n❌ ERROR: SMTP_USER contains placeholder value!")
        print("   Please update your .env file with your real email address.")
        return False
    
    if settings.SMTP_PASSWORD == "your-gmail-app-password" or len(settings.SMTP_PASSWORD) < 10:
        print("\n❌ ERROR: SMTP_PASSWORD appears to be a placeholder or too short!")
        print("   Please update your .env file with your real Gmail App Password.")
        return False
    
    # Test connection
    print("\n🔌 Testing SMTP Connection...")
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            print("   ✅ Connected to SMTP server")
            
            print("   🔐 Starting TLS...")
            server.starttls()
            print("   ✅ TLS started")
            
            print("   🔑 Authenticating...")
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            print("   ✅ Authentication successful!")
            
            print("\n✅ SMTP configuration is correct!")
            print("   Your email settings are working properly.\n")
            return True
            
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ SMTP Authentication Failed!")
        print(f"   Error: {str(e)}")
        print("\n💡 Common causes:")
        print("   1. Using regular Gmail password instead of App Password")
        print("   2. App Password not generated correctly")
        print("   3. 2-Step Verification not enabled")
        print("   4. Wrong email address in SMTP_USER")
        print("\n📝 Solution for Gmail:")
        print("   1. Enable 2-Step Verification:")
        print("      https://myaccount.google.com/security")
        print("   2. Generate App Password:")
        print("      https://myaccount.google.com/apppasswords")
        print("   3. Select 'Mail' and 'Other (Custom name)'")
        print("   4. Enter 'IZENIC ImmoAssist' as name")
        print("   5. Copy the 16-character password")
        print("   6. Use it as SMTP_PASSWORD in .env")
        return False
        
    except smtplib.SMTPException as e:
        print(f"\n❌ SMTP Error: {str(e)}")
        return False
        
    except ConnectionRefusedError:
        print("\n❌ Connection Refused!")
        print("   Check if SMTP_HOST and SMTP_PORT are correct.")
        return False
        
    except Exception as e:
        print(f"\n❌ Unexpected Error: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        success = test_smtp_configuration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

