#!/usr/bin/env python3
"""
Test ECHTE FinAPI-Verbindung
Führt den kompletten Flow durch
"""
from dotenv import load_dotenv
load_dotenv()  # Lade .env BEVOR app importiert wird

from app.utils.finapi_service import finapi_service
import sys

print("\n" + "="*80)
print("🚀 ECHTER FINAPI-VERBINDUNGSTEST")
print("="*80 + "\n")

# 1. Prüfe Konfiguration
if not finapi_service.is_configured():
    print("❌ FinAPI nicht konfiguriert!")
    print("   Bitte CLIENT_ID und CLIENT_SECRET in .env eintragen\n")
    sys.exit(1)

print("✅ FinAPI ist konfiguriert!\n")

# 2. Hole Client Token
print("1️⃣ Client Token anfordern...")
client_token = finapi_service._get_client_token()

if not client_token:
    print("❌ Client Token konnte nicht abgerufen werden\n")
    sys.exit(1)

print(f"✅ Client Token: {client_token[:50]}...\n")

# 3. Erstelle Test-User
print("2️⃣ FinAPI Test-User erstellen...")
test_email = "test@izenic-immoassist.de"
test_password = "TestPassword123!"

user_result = finapi_service.create_user_in_finapi(test_email, test_password)

if not user_result:
    print("❌ User konnte nicht erstellt werden\n")
    sys.exit(1)

if user_result.get("exists"):
    print(f"ℹ️  User existiert bereits: {test_email}\n")
    # Verwende das gespeicherte Passwort
else:
    print(f"✅ User erstellt: {user_result.get('id')}")
    # FinAPI gibt das Passwort zurück
    if 'password' in user_result:
        test_password = user_result['password']
        print(f"   FinAPI-generiertes Passwort: {test_password}\n")
    else:
        print(f"   Verwende unser Passwort\n")

# 4. Hole User Token  
print("3️⃣ User Token anfordern...")

# FinAPI verwendet die USER-ID (nicht Email) als username!
user_id = user_result.get('id')
print(f"   User ID: {user_id}")
print(f"   Password: {test_password}\n")

# Manueller Test mit USER ID
import requests
try:
    token_response = requests.post(
        f"{finapi_service.base_url}/api/v2/oauth/token",
        data={
            "grant_type": "password",
            "client_id": finapi_service.client_id,
            "client_secret": finapi_service.client_secret,
            "username": user_id,  # USER ID statt Email!
            "password": test_password,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
    )
    
    print(f"   Response Status: {token_response.status_code}")
    
    if token_response.status_code == 200:
        token_data = token_response.json()
        user_token = token_data.get("access_token")
        print(f"✅ User Token: {user_token[:50]}...")
        print(f"   Gültig für: {token_data.get('expires_in')} Sekunden\n")
    else:
        print(f"   Response: {token_response.text}\n")
        print(f"❌ Fehler beim Token-Abruf\n")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Fehler: {e}\n")
    sys.exit(1)

print(f"✅ User Token: {user_token[:50]}...\n")

# 5. Starte Bank Connection Import
print("4️⃣ Bank Connection Import starten...")
web_form_data = finapi_service.start_bank_connection_import(user_token)

if not web_form_data:
    print("❌ Web Form konnte nicht gestartet werden\n")
    sys.exit(1)

print(f"✅ Web Form bereit!\n")
print(f"📍 Web Form URL:")
print(f"   {web_form_data['location']}\n")
print(f"📋 Web Form ID: {web_form_data.get('id')}\n")

# 6. Instructions
print("="*80)
print("✅ ✅ ✅ ALLES BEREIT! ✅ ✅ ✅")
print("="*80)
print("\n🎯 NÄCHSTE SCHRITTE:\n")
print("1. Öffnen Sie diese URL in Ihrem Browser:")
print(f"   {web_form_data['location']}\n")
print("2. FinAPI zeigt Ihnen die Bank-Auswahl")
print("3. Wählen Sie: 'finAPI Test Redirect Bank' (für Sandbox)")
print("4. Login-Daten (Sandbox):")
print("   Username: Demodaten")
print("   PIN: 12345 (beliebige 5-stellige Zahl)\n")
print("5. Nach erfolgreicher Authentifizierung:")
print("   → FinAPI importiert die Kontodaten")
print("   → Sie können Transaktionen synchronisieren\n")
print("="*80 + "\n")

