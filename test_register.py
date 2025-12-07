#!/usr/bin/env python3
"""
Test script to diagnose registration issues.
Shows what validation errors occur during registration.
"""

import requests
import json
import sys

API_URL = "http://localhost:8000"

def test_registration(email: str, password: str):
    """Test user registration and show detailed error messages."""
    print(f"🧪 Testing registration...")
    print(f"   Email: {email}")
    print(f"   Password: {'*' * len(password)} (length: {len(password)})")
    print()
    
    # Check password requirements
    print("🔍 Checking password requirements...")
    issues = []
    if len(password) < 8:
        issues.append("❌ Password must be at least 8 characters")
    else:
        print("   ✅ Password length: OK")
    
    if not any(char.isdigit() for char in password):
        issues.append("❌ Password must contain at least one digit")
    else:
        print("   ✅ Contains digit: OK")
    
    if not any(char.isalpha() for char in password):
        issues.append("❌ Password must contain at least one letter")
    else:
        print("   ✅ Contains letter: OK")
    
    if issues:
        print("\n⚠️  Password validation issues found:")
        for issue in issues:
            print(f"   {issue}")
        print("\n💡 Password requirements:")
        print("   - At least 8 characters")
        print("   - At least one digit (0-9)")
        print("   - At least one letter (a-z, A-Z)")
        return False
    
    print("   ✅ Password meets all requirements\n")
    
    # Try registration
    print("📡 Sending registration request...")
    try:
        response = requests.post(
            f"{API_URL}/auth/register",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 201:
            print("\n✅ Registration successful!")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"\n❌ Registration failed!")
            print(f"   Status: {response.status_code}")
            
            try:
                error_data = response.json()
                print(f"   Error details:")
                print(json.dumps(error_data, indent=2))
                
                # Handle validation errors (422)
                if response.status_code == 422:
                    if "detail" in error_data:
                        if isinstance(error_data["detail"], list):
                            print("\n📋 Validation errors:")
                            for error in error_data["detail"]:
                                loc = " → ".join(str(x) for x in error.get("loc", []))
                                msg = error.get("msg", "Unknown error")
                                print(f"   • {loc}: {msg}")
                        else:
                            print(f"   Detail: {error_data['detail']}")
                
                # Handle other errors (400, 500, etc.)
                elif "detail" in error_data:
                    print(f"   Message: {error_data['detail']}")
                    
            except json.JSONDecodeError:
                print(f"   Raw response: {response.text}")
            
            return False
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Connection Error!")
        print("   Is the backend server running?")
        print(f"   Try: uvicorn app.main:app --reload")
        return False
    except requests.exceptions.Timeout:
        print("\n❌ Request Timeout!")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected Error: {str(e)}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_register.py <email> <password>")
        print("\nExample:")
        print("  python test_register.py test@example.com TestPass123")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    
    success = test_registration(email, password)
    sys.exit(0 if success else 1)

