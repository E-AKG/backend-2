#!/usr/bin/env python3
"""
Test-Script für echte FinAPI Integration
"""
import requests
import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

FINAPI_BASE_URL = os.getenv('FINAPI_BASE_URL', 'https://sandbox.finapi.io')
CLIENT_ID = os.getenv('FINAPI_CLIENT_ID')
CLIENT_SECRET = os.getenv('FINAPI_CLIENT_SECRET')

print("=" * 60)
print("🧪 FinAPI Production Integration Test")
print("=" * 60)
print()

# 1. Check Configuration
print("1️⃣ Configuration Check")
print(f"   Base URL: {FINAPI_BASE_URL}")
print(f"   Client ID: {CLIENT_ID[:20]}..." if CLIENT_ID else "   Client ID: ❌ NOT SET")
print(f"   Client Secret: {'✅ SET' if CLIENT_SECRET else '❌ NOT SET'}")
print()

if not CLIENT_ID or not CLIENT_SECRET:
    print("❌ ERROR: FinAPI credentials not configured!")
    print("   Please set FINAPI_CLIENT_ID and FINAPI_CLIENT_SECRET in .env")
    exit(1)

# 2. Get Client Token
print("2️⃣ Getting Client Token...")
try:
    response = requests.post(
        f"{FINAPI_BASE_URL}/api/v2/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
    )
    
    if response.status_code == 200:
        token_data = response.json()
        client_token = token_data.get("access_token")
        print(f"   ✅ Client Token received (expires in {token_data.get('expires_in')}s)")
        print(f"   Token: {client_token[:30]}...")
    else:
        print(f"   ❌ Failed: {response.status_code}")
        print(f"   Response: {response.text}")
        exit(1)
        
except Exception as e:
    print(f"   ❌ Error: {str(e)}")
    exit(1)

print()

# 3. Create Test User
print("3️⃣ Creating Test User...")
test_email = f"test_{os.urandom(4).hex()}@immoassist.test"
test_password = "TestPassword123!"

try:
    response = requests.post(
        f"{FINAPI_BASE_URL}/api/v2/users",
        headers={
            "Authorization": f"Bearer {client_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        },
        json={
            "email": test_email,
            "password": test_password,
            "isAutoUpdateEnabled": True
        }
    )
    
    if response.status_code in [200, 201]:
        user_data = response.json()
        user_id = user_data.get("id")
        print(f"   ✅ User created: {user_id}")
        print(f"   Email: {test_email}")
    else:
        print(f"   ❌ Failed: {response.status_code}")
        print(f"   Response: {response.text}")
        exit(1)
        
except Exception as e:
    print(f"   ❌ Error: {str(e)}")
    exit(1)

print()

# 4. Get User Token
print("4️⃣ Getting User Token...")
try:
    response = requests.post(
        f"{FINAPI_BASE_URL}/api/v2/oauth/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": user_id,  # USER ID!
            "password": test_password,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
    )
    
    if response.status_code == 200:
        token_data = response.json()
        user_token = token_data.get("access_token")
        print(f"   ✅ User Token received (expires in {token_data.get('expires_in')}s)")
        print(f"   Token: {user_token[:30]}...")
    else:
        print(f"   ❌ Failed: {response.status_code}")
        print(f"   Response: {response.text}")
        exit(1)
        
except Exception as e:
    print(f"   ❌ Error: {str(e)}")
    exit(1)

print()

# 5. Check Available Banks
print("5️⃣ Checking Available Banks...")
try:
    response = requests.get(
        f"{FINAPI_BASE_URL}/api/v2/banks",
        headers={
            "Authorization": f"Bearer {client_token}",
            "Accept": "application/json"
        },
        params={
            "perPage": 5
        }
    )
    
    if response.status_code == 200:
        banks_data = response.json()
        banks = banks_data.get("banks", [])
        print(f"   ✅ Found {len(banks)} banks (showing first 5):")
        for bank in banks[:5]:
            print(f"      • {bank.get('name')} (ID: {bank.get('id')})")
    else:
        print(f"   ❌ Failed: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"   ⚠️ Warning: {str(e)}")

print()

# 6. Summary
print("=" * 60)
print("✅ SUCCESS: FinAPI Integration is working!")
print("=" * 60)
print()
print("📋 Next Steps:")
print("   1. Open your app: http://localhost:5173")
print("   2. Go to: Bank → 'Bankkonto hinzufügen'")
print("   3. Click: 'Mit FinAPI verbinden'")
print("   4. In Web Form: Search for 'FinAPI Test Bank'")
print("   5. Login with:")
print("      • User ID: username")
print("      • PIN: password")
print()
print("🎉 Your tool is ready for real bank connections!")
print()

