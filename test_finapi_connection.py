#!/usr/bin/env python3
"""
Test FinAPI Connection
Testet die Verbindung zu FinAPI und zeigt verfügbare Features
"""
import os
from dotenv import load_dotenv
import requests

load_dotenv()

# FinAPI-Konfiguration
FINAPI_BASE_URL = os.getenv('FINAPI_BASE_URL', 'https://sandbox.finapi.io')
FINAPI_CLIENT_ID = os.getenv('FINAPI_CLIENT_ID')
FINAPI_CLIENT_SECRET = os.getenv('FINAPI_CLIENT_SECRET')

print("\n" + "="*80)
print("🔍 FINAPI CONNECTION TEST")
print("="*80 + "\n")

# 1. Prüfe Konfiguration
print("1️⃣ Konfiguration prüfen...")
print(f"   Base URL: {FINAPI_BASE_URL}")
print(f"   Client ID: {FINAPI_CLIENT_ID[:20] + '...' if FINAPI_CLIENT_ID and len(FINAPI_CLIENT_ID) > 20 else FINAPI_CLIENT_ID or 'NICHT GESETZT'}")
print(f"   Client Secret: {'***' + FINAPI_CLIENT_SECRET[-8:] if FINAPI_CLIENT_SECRET else 'NICHT GESETZT'}")
print()

if not FINAPI_CLIENT_ID or not FINAPI_CLIENT_SECRET:
    print("❌ FEHLER: FinAPI-Credentials nicht konfiguriert!")
    print("\n📝 Bitte in .env eintragen:")
    print("   FINAPI_BASE_URL=https://sandbox.finapi.io")
    print("   FINAPI_CLIENT_ID=ihr_client_id")
    print("   FINAPI_CLIENT_SECRET=ihr_client_secret")
    print("\n🔗 Credentials erhalten: https://www.finapi.io/jetzt-testen/\n")
    exit(1)

# 2. OAuth-Token holen
print("2️⃣ OAuth Client Token anfordern...")
try:
    response = requests.post(
        f"{FINAPI_BASE_URL}/api/v2/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": FINAPI_CLIENT_ID,
            "client_secret": FINAPI_CLIENT_SECRET,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
    )
    
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in")
        
        print(f"   ✅ Token erhalten!")
        print(f"   Token: {access_token[:50]}...")
        print(f"   Gültig für: {expires_in} Sekunden ({expires_in/3600:.1f} Stunden)")
        print(f"   Scope: {token_data.get('scope')}")
        print()
        
        # 3. Test API-Call: Get Client Configuration
        print("3️⃣ Client-Konfiguration abrufen...")
        config_response = requests.get(
            f"{FINAPI_BASE_URL}/api/v2/clientConfiguration",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        
        print(f"   Status: {config_response.status_code}")
        
        if config_response.status_code == 200:
            config = config_response.json()
            print(f"   ✅ Client-Konfiguration erfolgreich abgerufen!")
            print(f"   Client ID: {config.get('clientId')}")
            print(f"   Max Users: {config.get('maxUserCount')}")
            print(f"   User Auto-Verify: {config.get('isUserAutoVerificationEnabled')}")
            print()
            
            print("=" * 80)
            print("✅ ✅ ✅ FINAPI-VERBINDUNG ERFOLGREICH! ✅ ✅ ✅")
            print("=" * 80)
            print("\n🎉 Sie können jetzt echte Bankverbindungen herstellen!")
            print("   Die App wird automatisch echte Transaktionen verwenden.\n")
            
        else:
            print(f"   ⚠️ Konfiguration konnte nicht abgerufen werden")
            print(f"   Response: {config_response.text}")
            print()
    
    else:
        print(f"   ❌ Token-Anfrage fehlgeschlagen!")
        print(f"   Response: {response.text}")
        print("\n💡 Mögliche Ursachen:")
        print("   - Client ID oder Secret falsch")
        print("   - Sandbox-URL falsch")
        print("   - Keine Internetverbindung zu FinAPI")
        print()

except requests.RequestException as e:
    print(f"   ❌ Netzwerkfehler: {e}")
    print()

print("=" * 80 + "\n")

