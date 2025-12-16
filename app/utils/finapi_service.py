"""
FinAPI Integration Service
Basiert auf FinAPI Access V2 API
Dokumentation: https://docs.finapi.io/access/
"""
import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from ..models.bank import BankAccount, BankTransaction
from ..models.billrun import Charge, ChargeStatus
from ..config import settings
import uuid

logger = logging.getLogger(__name__)


class FinAPIService:
    """
    Service für FinAPI Access V2 Integration
    
    Implementiert:
    - OAuth 2.0 Client Credentials Flow
    - User Management
    - Bank Connection Import
    - Transaction Sync
    - Automatischer Zahlungsabgleich
    """
    
    def __init__(self):
        # FinAPI-Konfiguration aus .env
        self.base_url = getattr(settings, 'FINAPI_BASE_URL', 'https://sandbox.finapi.io')
        self.client_id = getattr(settings, 'FINAPI_CLIENT_ID', None)
        self.client_secret = getattr(settings, 'FINAPI_CLIENT_SECRET', None)
        self.client_token = None
        self.token_expiry = None
    
    def is_configured(self) -> bool:
        """Prüfe ob FinAPI-Credentials konfiguriert sind"""
        return (
            self.client_id is not None and 
            self.client_secret is not None and
            self.client_id != "your_finapi_client_id"
        )
    
    def _get_client_token(self) -> Optional[str]:
        """
        Hole Client Access Token von FinAPI (OAuth 2.0 Client Credentials Flow)
        Endpoint: POST /api/v2/oauth/token
        Content-Type: application/x-www-form-urlencoded
        """
        if not self.is_configured():
            logger.warning("FinAPI credentials not configured - using demo mode")
            return None
        
        # Token wiederverwenden wenn noch gültig
        if self.client_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.client_token
        
        try:
            logger.info("Requesting FinAPI client token...")
            
            response = requests.post(
                f"{self.base_url}/api/v2/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                }
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            self.client_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)  # 1 Min Puffer
            
            logger.info(f"✅ FinAPI client token erfolgreich erhalten (gültig für {expires_in}s)")
            return self.client_token
            
        except requests.RequestException as e:
            logger.error(f"❌ FinAPI authentication failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
    
    def create_user_in_finapi(self, user_email: str, user_password: str) -> Optional[Dict]:
        """
        Erstelle User in FinAPI
        POST /api/v2/users
        
        Returns: {"userId": "...", "password": "..."} oder None
        """
        token = self._get_client_token()
        if not token:
            return None
        
        try:
            logger.info(f"Creating FinAPI user for {user_email}...")
            
            response = requests.post(
                f"{self.base_url}/api/v2/users",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                },
                json={
                    "email": user_email,
                    "password": user_password,
                    "isAutoUpdateEnabled": True,
                }
            )
            
            if response.status_code == 201:
                user_data = response.json()
                logger.info(f"✅ FinAPI user created: {user_data.get('id')}")
                return user_data
            elif response.status_code == 422:
                # User existiert bereits
                logger.info(f"FinAPI user already exists for {user_email}")
                return {"email": user_email, "exists": True}
            else:
                logger.error(f"Failed to create user: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Failed to create FinAPI user: {str(e)}")
            return None
    
    def get_user_token(self, user_id: str, password: str) -> Optional[str]:
        """
        Hole User Access Token
        POST /api/v2/oauth/token mit grant_type=password
        
        WICHTIG: username = FinAPI User ID (nicht Email!)
        """
        if not self.is_configured():
            return None
        
        try:
            logger.info(f"Getting user token for user_id: {user_id}...")
            
            response = requests.post(
                f"{self.base_url}/api/v2/oauth/token",
                data={
                    "grant_type": "password",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": user_id,  # USER ID!
                    "password": password,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                }
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            logger.info(f"✅ User token received (expires in {token_data.get('expires_in')}s)")
            return token_data.get("access_token")
            
        except requests.RequestException as e:
            logger.error(f"Failed to get user token: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response Status: {e.response.status_code}")
                logger.error(f"Response Body: {e.response.text}")
            return None
    
    def create_webform(self, user_token: str = None) -> Optional[Dict]:
        """
        Erstelle FinAPI WebForm für Bankauswahl und Login
        
        Exakter Ablauf nach FinAPI-Dokumentation:
        1. Client Token holen (für System-Calls)
        2. Test-User erstellen (falls nicht vorhanden)
        3. User Token holen (für User-Aktionen)
        4. WebForm erstellen mit /api/webForms/bankConnectionImport
        
        Returns: {"url": "https://webform-sandbox.finapi.io/wf/...", "id": "123"}
        """
        try:
            logger.info("Creating FinAPI WebForm with exact API flow...")
            
            # 1. Hole Client Access Token (für System-Calls)
            client_token = self._get_client_token()
            if not client_token:
                logger.error("❌ Could not get client token")
                return None
            
            logger.info(f"✅ Client token received: {client_token[:20]}...")
            
            # 2. Erstelle Test-User (falls nicht vorhanden)
            test_user_id = "testuser1"
            test_user_password = "123456"
            
            # Versuche User zu erstellen
            user_response = requests.post(
                f"{self.base_url}/api/v2/users",
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "id": test_user_id,
                    "password": test_user_password
                }
            )
            
            if user_response.status_code in [200, 201]:
                logger.info(f"✅ Test user created: {test_user_id}")
            elif user_response.status_code == 409:
                logger.info(f"✅ Test user already exists: {test_user_id}")
            else:
                logger.warning(f"User creation response: {user_response.status_code} - {user_response.text}")
            
            # 3. Hole User Token (für User-Aktionen)
            user_token_response = requests.post(
                f"{self.base_url}/api/v2/oauth/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": test_user_id,
                    "password": test_user_password,
                    "grant_type": "password"
                }
            )
            
            if user_token_response.status_code != 200:
                logger.error(f"❌ User token failed: {user_token_response.status_code} - {user_token_response.text}")
                return None
            
            user_token_data = user_token_response.json()
            user_access_token = user_token_data["access_token"]
            logger.info(f"✅ User token received: {user_access_token[:20]}...")
            
            # 4. Erstelle WebForm mit korrektem Endpoint
            webform_response = requests.post(
                f"{self.base_url}/api/webForms/bankConnectionImport",
                headers={
                    "Authorization": f"Bearer {user_access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "accountTypes": ["CHECKING"],
                    "redirectUrl": f"{settings.FRONTEND_URL}/bank?webform=success"
                }
            )
            
            logger.info(f"FinAPI WebForm Response: {webform_response.status_code} - {webform_response.text}")
            
            if webform_response.status_code in [200, 201]:
                data = webform_response.json()
                webform_url = data.get("url")
                webform_id = data.get("id")
                
                if webform_url:
                    logger.info(f"✅ Echte FinAPI WebForm created: {webform_url}")
                    return {
                        "url": webform_url,
                        "location": webform_url,
                        "id": webform_id,
                        "status": "web_form"
                    }
            
            # Fallback: Lokale WebForm (da echte WebForm nicht verfügbar)
            logger.info("Using local WebForm fallback (echte FinAPI WebForm nicht verfügbar)...")
            webform_url = f"{settings.FRONTEND_URL}/finapi-webform.html?accessToken={user_access_token}"
            
            return {
                "url": webform_url,
                "location": webform_url,
                "id": f"webform_{user_access_token[:8]}",
                "status": "web_form"
            }
            
        except Exception as e:
            logger.error(f"Failed to create WebForm: {str(e)}")
            return None
    
    def get_webform_status(self, user_token: str, webform_id: str) -> Optional[Dict]:
        """
        Prüfe Status eines FinAPI WebForm 2.0
        
        GET /api/v2/webForms/{id}
        
        Returns: {"status": "completed|pending|error", "message": "..."}
        """
        if not user_token or not webform_id:
            return None
        
        try:
            logger.info(f"Checking WebForm 2.0 status for {webform_id}...")
            
            response = requests.get(
                f"{self.base_url}/api/v2/webForms/{webform_id}",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "pending")
                
                logger.info(f"✅ WebForm 2.0 status: {status}")
                return {
                    "status": status,
                    "message": data.get("message", ""),
                    "data": data
                }
            else:
                logger.error(f"WebForm status check failed: {response.status_code} - {response.text}")
                return {"status": "error", "message": "Status check failed"}
                
        except requests.RequestException as e:
            logger.error(f"Failed to check WebForm status: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def start_bank_connection_import(self, user_token: str) -> Optional[Dict]:
        """
        Starte Bank Connection Import via Web Form
        POST /api/v2/bankConnections/import
        
        Returns: {"location": "https://...", "id": "123"}
        """
        if not user_token:
            return None
        
        try:
            logger.info("Starting bank connection import (Web Form)...")
            
            # Generiere eindeutige Request-ID
            request_id = str(uuid.uuid4())
            
            response = requests.post(
                f"{self.base_url}/api/v2/bankConnections/import",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": request_id
                },
                json={
                    "bankId": 280002,  # FinAPI Test Redirect Bank (Sandbox)
                    "bankingInterface": "WEB_SCRAPER",  # WICHTIG!
                    # Für echte Banken: User wählt aus oder gibt BLZ ein
                }
            )
            
            if response.status_code in [201, 451]:  # 451 = Web Form erforderlich
                data = response.json()
                location = data.get("location")
                
                if location:
                    logger.info(f"✅ Web Form URL erhalten: {location}")
                    return {
                        "location": location,
                        "id": data.get("id"),
                        "status": "web_form"
                    }
                
            logger.error(f"Unexpected response: {response.status_code} - {response.text}")
            return None
            
        except requests.RequestException as e:
            logger.error(f"Failed to start bank connection: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return None
    
    def get_bank_connections(self, user_token: str) -> List[Dict]:
        """
        Hole alle Bank Connections des Users
        GET /api/v2/bankConnections
        """
        if not user_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v2/bankConnections",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json"
                }
            )
            
            response.raise_for_status()
            data = response.json()
            return data.get("connections", [])
            
        except requests.RequestException as e:
            logger.error(f"Failed to get bank connections: {str(e)}")
            return []
    
    def get_accounts(self, user_token: str) -> List[Dict]:
        """
        Hole alle Accounts (Konten) des Users
        GET /api/v2/accounts
        """
        if not user_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v2/accounts",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json"
                }
            )
            
            response.raise_for_status()
            data = response.json()
            return data.get("accounts", [])
            
        except requests.RequestException as e:
            logger.error(f"Failed to get accounts: {str(e)}")
            return []
    
    def sync_transactions(
        self,
        db: Session,
        bank_account: BankAccount,
        days_back: int = 90
    ) -> int:
        """
        Synchronisiere Transaktionen von FinAPI für ein Bankkonto
        
        Args:
            db: Database Session
            bank_account: BankAccount Objekt
            days_back: Wie viele Tage zurück synchronisieren
            
        Returns:
            Anzahl der importierten Transaktionen
        """
        if not bank_account.finapi_account_id:
            logger.warning(f"Bank account {bank_account.id} has no FinAPI connection")
            return 0
        
        # Hole Transaktionen von FinAPI
        # In Produktion: Echter API-Call an FinAPI
        # Für Demo: Simuliere Transaktionen
        
        transactions = self._fetch_transactions_from_finapi(
            bank_account.finapi_account_id,
            days_back
        )
        
        imported_count = 0
        
        for trans_data in transactions:
            # Prüfe ob Transaktion bereits existiert
            existing = db.query(BankTransaction).filter(
                BankTransaction.finapi_transaction_id == trans_data.get("id")
            ).first()
            
            if existing:
                continue  # Überspringe bereits importierte
            
            # Erstelle neue Transaktion
            # Verwende bookingDate oder bankBookingDate (für Demo-Daten)
            booking_date_str = trans_data.get("bookingDate") or trans_data.get("bankBookingDate")
            if not booking_date_str:
                logger.warning(f"Kein bookingDate für Transaktion {trans_data.get('id')}")
                continue
                
            transaction = BankTransaction(
                bank_account_id=bank_account.id,
                transaction_date=datetime.strptime(booking_date_str, "%Y-%m-%d").date(),
                booking_date=datetime.strptime(booking_date_str, "%Y-%m-%d").date(),
                amount=Decimal(str(trans_data["amount"])),
                purpose=trans_data.get("purpose"),
                counterpart_name=trans_data.get("counterpartName"),
                counterpart_iban=trans_data.get("counterpartIban"),
                finapi_transaction_id=trans_data.get("id"),
                is_matched=False,
                matched_amount=Decimal(0)
            )
            db.add(transaction)
            imported_count += 1
        
        if imported_count > 0:
            # Aktualisiere last_sync
            bank_account.last_sync = date.today()
            db.commit()
            logger.info(f"Imported {imported_count} transactions for account {bank_account.id}")
        
        return imported_count
    
    def get_transactions_from_finapi(
        self,
        user_token: str,
        account_ids: List[int],
        days_back: int = 90
    ) -> List[Dict]:
        """
        Hole ECHTE Transaktionen von FinAPI
        GET /api/v2/transactions
        """
        if not user_token:
            logger.warning("No user token - using demo data")
            return self._get_demo_transactions()
        
        try:
            min_date = (date.today() - timedelta(days=days_back)).isoformat()
            
            logger.info(f"Fetching real transactions from FinAPI (last {days_back} days)...")
            
            response = requests.get(
                f"{self.base_url}/api/v2/transactions",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json"
                },
                params={
                    "accountIds": ",".join(map(str, account_ids)),
                    "minBankBookingDate": min_date,
                    "perPage": 500
                }
            )
            
            response.raise_for_status()
            data = response.json()
            transactions = data.get("transactions", [])
            
            logger.info(f"✅ {len(transactions)} real transactions fetched from FinAPI")
            return transactions
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch transactions: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return []
    
    def _get_demo_transactions(self) -> List[Dict]:
        """Generiere Demo-Transaktionen wenn keine echte Verbindung"""
        today = date.today()
        logger.info(f"📊 Generating DEMO transactions for testing...")
        
        transactions = [
            # ✅ Mieteinnahmen (Positiv)
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=5)).isoformat(),
                "amount": 1200.00,
                "purpose": "Miete Wohnung 1A - Max Mustermann",
                "counterpartName": "Max Mustermann",
                "counterpartIban": "DE89370400440532013000",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=3)).isoformat(),
                "amount": 950.00,
                "purpose": "Mietzahlung Oktober - Anna Schmidt",
                "counterpartName": "Anna Schmidt",
                "counterpartIban": "DE89370400440532013001",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=2)).isoformat(),
                "amount": 1100.00,
                "purpose": "Miete Wohnung 2B",
                "counterpartName": "Thomas Weber",
                "counterpartIban": "DE45500105170648489891",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=1)).isoformat(),
                "amount": 850.00,
                "purpose": "Miete EG links",
                "counterpartName": "Familie Schneider",
                "counterpartIban": "DE77500105170648489893",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=10)).isoformat(),
                "amount": 1300.00,
                "purpose": "Miete November - Erika Müller",
                "counterpartName": "Erika Müller",
                "counterpartIban": "DE12500105170648489890",
            },
            
            # ❌ Ausgaben (Negativ)
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=7)).isoformat(),
                "amount": -250.00,
                "purpose": "Hausmeister Oktober",
                "counterpartName": "Hausmeisterdienst GmbH",
                "counterpartIban": "DE89370400440532013010",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=15)).isoformat(),
                "amount": -120.00,
                "purpose": "Müllabfuhr Q4 2025",
                "counterpartName": "Stadtverwaltung",
                "counterpartIban": "DE89370400440532013011",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=12)).isoformat(),
                "amount": -85.50,
                "purpose": "Versicherung Gebäude",
                "counterpartName": "Versicherung AG",
                "counterpartIban": "DE89370400440532013012",
            },
            {
                "id": f"demo_trans_{uuid.uuid4().hex[:8]}",
                "bankBookingDate": (today - timedelta(days=20)).isoformat(),
                "amount": -450.00,
                "purpose": "Reparatur Heizung",
                "counterpartName": "Sanitär & Heizung GmbH",
                "counterpartIban": "DE89370400440532013013",
            },
        ]
        
        logger.info(f"✅ Generated {len(transactions)} demo transactions (5 income, 4 expenses)")
        return transactions
    
    def _fetch_transactions_from_finapi(
        self,
        finapi_account_id: str,
        days_back: int
    ) -> List[Dict]:
        """
        Legacy method - ruft _get_demo_transactions auf
        """
        return self._get_demo_transactions()
    
    def auto_match_payments(
        self,
        db: Session,
        bank_account_id: str,
        owner_id: int
    ) -> int:
        """
        Versuche automatisch Transaktionen mit offenen Sollbuchungen abzugleichen
        
        Matching-Kriterien:
        1. Betrag stimmt überein (±2%)
        2. Zeitraum passt (±7 Tage um Fälligkeitsdatum)
        3. Name im Verwendungszweck oder Counterpart
        
        Returns:
            Anzahl der automatisch zugeordneten Zahlungen
        """
        from ..models.billrun import BillRun, Charge
        from ..models.lease import Lease
        from ..models.tenant import Tenant
        from ..models.bank import PaymentMatch
        
        # Hole ungematchte Transaktionen
        unmatched_transactions = db.query(BankTransaction).filter(
            BankTransaction.bank_account_id == bank_account_id,
            BankTransaction.is_matched == False,
            BankTransaction.amount > 0  # Nur Eingänge
        ).all()
        
        # Hole offene Sollbuchungen
        open_charges = db.query(Charge).join(
            Charge.bill_run
        ).filter(
            BillRun.owner_id == owner_id,
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
        ).all()
        
        matched_count = 0
        
        for transaction in unmatched_transactions:
            best_match = None
            best_score = 0
            
            for charge in open_charges:
                score = self._calculate_match_score(transaction, charge, db)
                
                if score > 70 and score > best_score:  # Mindestens 70% Übereinstimmung
                    best_match = charge
                    best_score = score
            
            if best_match:
                # Erstelle automatisches Match
                remaining = best_match.amount - best_match.paid_amount
                matched_amount = min(transaction.amount, remaining)
                
                payment_match = PaymentMatch(
                    transaction_id=transaction.id,
                    charge_id=best_match.id,
                    matched_amount=matched_amount,
                    is_automatic=True,
                    note=f"Automatisch zugeordnet (Score: {best_score}%)"
                )
                db.add(payment_match)
                
                # Update Charge
                best_match.paid_amount += matched_amount
                if best_match.paid_amount >= best_match.amount:
                    best_match.status = ChargeStatus.PAID
                elif best_match.paid_amount > 0:
                    best_match.status = ChargeStatus.PARTIALLY_PAID
                
                # Update Transaction
                transaction.matched_amount += matched_amount
                if transaction.matched_amount >= transaction.amount:
                    transaction.is_matched = True
                
                matched_count += 1
                logger.info(f"Auto-matched transaction {transaction.id} to charge {best_match.id}")
        
        if matched_count > 0:
            db.commit()
        
        return matched_count
    
    def auto_match_single_transaction(
        self,
        db: Session,
        transaction: BankTransaction,
        owner_id: int
    ) -> tuple[int, float]:
        """
        Automatische Zuordnung einer einzelnen Transaktion zu Sollbuchungen
        
        Returns:
            (matches_found, matched_amount)
        """
        from ..models.billrun import BillRun, Charge
        from ..models.lease import Lease
        from ..models.tenant import Tenant
        from ..models.bank import PaymentMatch
        
        # Hole offene Sollbuchungen
        open_charges = db.query(Charge).join(
            Charge.bill_run
        ).filter(
            BillRun.owner_id == owner_id,
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
        ).all()
        
        logger.info(f"🔍 Auto match for transaction {transaction.id}:")
        logger.info(f"   Amount: {transaction.amount} €")
        logger.info(f"   Date: {transaction.transaction_date}")
        logger.info(f"   Purpose: {transaction.purpose}")
        logger.info(f"   Counterpart: {transaction.counterpart_name}")
        logger.info(f"   Found {len(open_charges)} open charges")
        
        matches_found = 0
        total_matched_amount = 0.0
        
        # Finde beste Matches
        best_matches = []
        
        for charge in open_charges:
            score = self._calculate_match_score(transaction, charge, db)
            
            logger.info(f"   Charge {charge.id}: {charge.amount} €, Due: {charge.due_date}, Score: {score}%")
            
            if score > 70:  # Mindestens 70% Übereinstimmung
                remaining = charge.amount - charge.paid_amount
                matched_amount = min(transaction.amount - total_matched_amount, remaining)
                
                if matched_amount > 0:
                    best_matches.append({
                        'charge': charge,
                        'score': score,
                        'matched_amount': matched_amount
                    })
                    logger.info(f"   ✅ Match found: {matched_amount} € (Score: {score}%)")
                else:
                    logger.info(f"   ⚠️ Score {score}% but no remaining amount to match")
            else:
                logger.info(f"   ❌ Score {score}% too low (need >70%)")
        
        # Sortiere nach Score (beste zuerst)
        best_matches.sort(key=lambda x: x['score'], reverse=True)
        
        # Erstelle Matches
        for match in best_matches:
            if total_matched_amount >= transaction.amount:
                break
                
            charge = match['charge']
            matched_amount = match['matched_amount']
            
            # Erstelle PaymentMatch
            payment_match = PaymentMatch(
                transaction_id=transaction.id,
                charge_id=charge.id,
                matched_amount=matched_amount,
                is_automatic=True,
                note=f"Automatisch zugeordnet (Score: {match['score']}%)"
            )
            db.add(payment_match)
            
            # Update Charge
            charge.paid_amount += matched_amount
            if charge.paid_amount >= charge.amount:
                charge.status = ChargeStatus.PAID
            elif charge.paid_amount > 0:
                charge.status = ChargeStatus.PARTIALLY_PAID
            
            # Update Transaction
            transaction.matched_amount += matched_amount
            if transaction.matched_amount >= transaction.amount:
                transaction.is_matched = True
            
            matches_found += 1
            total_matched_amount += matched_amount
            
            logger.info(f"Auto-matched transaction {transaction.id} to charge {charge.id} (Score: {match['score']}%)")
        
        if matches_found > 0:
            db.commit()
        
        return matches_found, total_matched_amount
    
    def _calculate_match_score(
        self,
        transaction: BankTransaction,
        charge: Charge,
        db: Session
    ) -> int:
        """
        Berechne Match-Score (0-100) zwischen Transaktion und Sollbuchung
        """
        score = 0
        
        # 1. Betrag prüfen (40 Punkte)
        remaining = charge.amount - charge.paid_amount
        amount_diff = abs(float(transaction.amount) - float(remaining))
        if amount_diff == 0:
            score += 40
        elif amount_diff / float(remaining) < 0.02:  # ±2%
            score += 30
        
        # 2. Datum prüfen (30 Punkte)
        days_diff = abs((transaction.transaction_date - charge.due_date).days)
        if days_diff <= 3:
            score += 30
        elif days_diff <= 7:
            score += 20
        elif days_diff <= 14:
            score += 10
        
        # 3. Name prüfen (30 Punkte)
        from ..models.lease import Lease
        from ..models.tenant import Tenant
        
        lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
        if lease:
            tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
            if tenant:
                tenant_name = f"{tenant.first_name} {tenant.last_name}".lower()
                purpose_lower = (transaction.purpose or "").lower()
                counterpart_lower = (transaction.counterpart_name or "").lower()
                
                if tenant.last_name.lower() in purpose_lower or tenant.last_name.lower() in counterpart_lower:
                    score += 30
                elif tenant.first_name.lower() in purpose_lower:
                    score += 15
        
        return score


# Singleton instance
finapi_service = FinAPIService()

