#!/usr/bin/env python3
"""
Simple test script for IZENIC ImmoAssist API
Tests the authentication endpoints
"""

import requests
import json
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"
TEST_EMAIL = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}@example.com"
TEST_PASSWORD = "TestPass123"

def print_section(title):
    """Print a formatted section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_health_check():
    """Test the health check endpoint"""
    print_section("Testing Health Check")
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("✅ Health check passed!")
            return True
        else:
            print("❌ Health check failed!")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API. Is the server running?")
        print(f"   Make sure the API is running at {BASE_URL}")
        return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_register():
    """Test user registration"""
    print_section("Testing User Registration")
    
    print(f"Registering user: {TEST_EMAIL}")
    print(f"Password: {TEST_PASSWORD}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/json"}
        )
        
        print(f"\nStatus Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 201:
            print("\n✅ Registration successful!")
            print("📧 Check your email for verification link")
            return True
        else:
            print(f"\n❌ Registration failed!")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_register_duplicate():
    """Test registering with duplicate email"""
    print_section("Testing Duplicate Registration")
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 400:
            print("\n✅ Correctly rejected duplicate registration!")
            return True
        else:
            print("\n❌ Should have rejected duplicate registration!")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_login_unverified():
    """Test login with unverified email"""
    print_section("Testing Login (Unverified Account)")
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 403:
            print("\n✅ Correctly rejected unverified account!")
            return True
        else:
            print("\n❌ Should have rejected unverified account!")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_login_invalid():
    """Test login with invalid credentials"""
    print_section("Testing Login (Invalid Credentials)")
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": TEST_EMAIL, "password": "WrongPassword123"},
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 401:
            print("\n✅ Correctly rejected invalid credentials!")
            return True
        else:
            print("\n❌ Should have rejected invalid credentials!")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_invalid_password():
    """Test registration with invalid password"""
    print_section("Testing Password Validation")
    
    invalid_passwords = [
        ("short", "Too short"),
        ("nodigits", "No digits"),
        ("12345678", "No letters")
    ]
    
    all_passed = True
    
    for password, reason in invalid_passwords:
        print(f"\nTesting password: '{password}' ({reason})")
        test_email = f"invalid_{datetime.now().strftime('%Y%m%d%H%M%S')}@example.com"
        
        try:
            response = requests.post(
                f"{BASE_URL}/auth/register",
                json={"email": test_email, "password": password},
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 422:
                print(f"✅ Correctly rejected: {reason}")
            else:
                print(f"❌ Should have rejected: {reason}")
                all_passed = False
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            all_passed = False
    
    return all_passed

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("  IZENIC ImmoAssist API Test Suite")
    print("="*60)
    print(f"\nAPI URL: {BASE_URL}")
    print(f"Test Email: {TEST_EMAIL}")
    print(f"Test Password: {TEST_PASSWORD}")
    
    # Track test results
    results = {
        "Health Check": False,
        "User Registration": False,
        "Duplicate Registration": False,
        "Login (Unverified)": False,
        "Login (Invalid)": False,
        "Password Validation": False
    }
    
    # Run tests
    results["Health Check"] = test_health_check()
    
    if not results["Health Check"]:
        print("\n❌ Cannot proceed without API connection!")
        sys.exit(1)
    
    results["User Registration"] = test_register()
    results["Duplicate Registration"] = test_register_duplicate()
    results["Login (Unverified)"] = test_login_unverified()
    results["Login (Invalid)"] = test_login_invalid()
    results["Password Validation"] = test_invalid_password()
    
    # Summary
    print_section("Test Summary")
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\n{'='*60}")
    print(f"Total: {passed}/{total} tests passed ({(passed/total)*100:.1f}%)")
    print(f"{'='*60}\n")
    
    if passed == total:
        print("🎉 All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please check the API.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {str(e)}")
        sys.exit(1)

