"""
Echte FinAPI Integration mit direkten API-Calls
Basiert auf FinAPI Access V2 API
"""
import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from ..models.bank import BankAccount, BankTransaction
from ..config import settings

logger = logging.getLogger(__name__)


class RealFinAPIService:
    """
    Echte FinAPI Integration für Produktionsumgebung
    """
    
    def __init__(self):
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
        """Hole Client Access Token von FinAPI"""
        if not self.is_configured():
            return None
        
        try:
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
            self.token_expiry = datetime.now() + timedelta(seconds=token_data.get("expires_in", 3600))
            
            logger.info(f"✅ Client token received (expires in {token_data.get('expires_in')}s)")
            return self.client_token
            
        except requests.RequestException as e:
            logger.error(f"Failed to get client token: {str(e)}")
            return None
    
    def create_user_in_finapi(self, email: str, password: str) -> Optional[Dict]:
        """Erstelle User in FinAPI"""
        if not self.is_configured():
            return None
        
        client_token = self._get_client_token()
        if not client_token:
            return None
        
        try:
            response = requests.post(
                f"{self.base_url}/api/v2/users",
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                },
                json={
                    "email": email,
                    "password": password,
                    "isAutoUpdateEnabled": True
                }
            )
            
            response.raise_for_status()
            user_data = response.json()
            
            logger.info(f"✅ FinAPI User created: {user_data.get('id')}")
            return user_data
            
        except requests.RequestException as e:
            logger.error(f"Failed to create FinAPI user: {str(e)}")
            return None
    
    def get_user_token(self, user_id: str, password: str) -> Optional[str]:
        """Hole User Access Token"""
        if not self.is_configured():
            return None
        
        try:
            response = requests.post(
                f"{self.base_url}/api/v2/oauth/token",
                data={
                    "grant_type": "password",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": user_id,  # FinAPI User ID!
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
            return None
    
    def get_banks(self) -> List[Dict]:
        """Hole verfügbare Banken von FinAPI"""
        if not self.is_configured():
            return []
        
        client_token = self._get_client_token()
        if not client_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v2/banks",
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "Accept": "application/json"
                }
            )
            
            response.raise_for_status()
            banks_data = response.json()
            
            logger.info(f"✅ Retrieved {len(banks_data.get('banks', []))} banks")
            return banks_data.get('banks', [])
            
        except requests.RequestException as e:
            logger.error(f"Failed to get banks: {str(e)}")
            return []
    
    def get_accounts(self, user_token: str) -> List[Dict]:
        """Hole Accounts von FinAPI"""
        if not self.is_configured():
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
            accounts_data = response.json()
            
            logger.info(f"✅ Retrieved {len(accounts_data.get('accounts', []))} accounts")
            return accounts_data.get('accounts', [])
            
        except requests.RequestException as e:
            logger.error(f"Failed to get accounts: {str(e)}")
            return []
    
    def get_transactions(self, user_token: str, account_ids: List[int], days_back: int = 90, from_date: Optional[date] = None) -> List[Dict]:
        """Hole Transaktionen von FinAPI"""
        if not self.is_configured():
            return []
        
        try:
            # Verwende from_date wenn gegeben, sonst berechne basierend auf days_back
            if from_date:
                from_date_str = from_date.isoformat()
            else:
                from_date_str = (date.today() - timedelta(days=days_back)).isoformat()
            
            # Setze maxBankBookingDate auf heute, um sicherzustellen, dass alle neuesten Transaktionen geladen werden
            max_date_str = date.today().isoformat()
            
            logger.info(f"📥 Fetching transactions from {from_date_str} to {max_date_str}")
            
            params = {
                "accountIds": ",".join(map(str, account_ids)),
                "minBankBookingDate": from_date_str,
                "maxBankBookingDate": max_date_str,  # Explizit bis heute
                "perPage": 500
            }
            
            response = requests.get(
                f"{self.base_url}/api/v2/transactions",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/json"
                },
                params=params
            )
            
            response.raise_for_status()
            transactions_data = response.json()
            
            transactions = transactions_data.get('transactions', [])
            logger.info(f"✅ Retrieved {len(transactions)} transactions from FinAPI (from {from_date_str} to {max_date_str})")
            
            # Log Datumsbereich der geladenen Transaktionen
            if transactions:
                dates = []
                for txn in transactions:
                    booking_date = txn.get("bookingDate") or txn.get("valueDate")
                    if booking_date:
                        dates.append(booking_date)
                
                if dates:
                    dates.sort()
                    logger.info(f"   📅 Transaction date range: {dates[0]} to {dates[-1]}")
            
            return transactions
            
        except requests.RequestException as e:
            logger.error(f"Failed to get transactions: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"   Response: {e.response.text}")
            return []
    
    def sync_transactions(self, db: Session, bank_account: BankAccount, days_back: int = 90) -> int:
        """Synchronisiere Transaktionen von FinAPI"""
        if not self.is_configured():
            logger.warning("FinAPI not configured, using demo data")
            return 0
        
        if not bank_account.finapi_access_token:
            logger.warning("No FinAPI access token for account")
            return 0
        
        try:
            # Bestimme Startdatum: Verwende last_sync + 1 Tag oder days_back
            max_date = date.today()
            from_date = None
            
            if bank_account.last_sync:
                # Lade ab dem Tag nach dem letzten Sync (+1 Tag um Überschneidungen zu vermeiden)
                from_date = bank_account.last_sync + timedelta(days=1)
                
                # Stelle sicher, dass from_date nicht in der Zukunft liegt
                if from_date > max_date:
                    # Wenn last_sync heute oder in der Zukunft ist, lade die letzten 7 Tage
                    from_date = max_date - timedelta(days=7)
                    logger.warning(f"⚠️ last_sync ({bank_account.last_sync}) ist zu neu, lade letzte 7 Tage ab {from_date}")
                
                # Aber nicht älter als days_back
                min_date = date.today() - timedelta(days=days_back)
                if from_date < min_date:
                    from_date = min_date
                    
                logger.info(f"📅 Using last_sync date: {bank_account.last_sync}, loading from: {from_date} to {max_date}")
            else:
                from_date = date.today() - timedelta(days=days_back)
                logger.info(f"📅 No last_sync date, loading from: {from_date} to {max_date} (last {days_back} days)")
            
            # Hole Accounts
            accounts = self.get_accounts(bank_account.finapi_access_token)
            if not accounts:
                logger.warning("No accounts found")
                return 0
            
            # Verwende erstes Account
            account_id = accounts[0].get('id')
            if not account_id:
                logger.warning("No account ID found")
                return 0
            
            # Hole Transaktionen
            transactions = self.get_transactions(
                bank_account.finapi_access_token, 
                [account_id], 
                days_back,
                from_date=from_date
            )
            
            if not transactions:
                logger.warning(f"⚠️ No transactions returned from FinAPI")
                return 0
            
            imported_count = 0
            skipped_count = 0
            
            for trans_data in transactions:
                # Prüfe ob Transaktion bereits existiert
                txn_id = str(trans_data.get("id")) if trans_data.get("id") else None
                if not txn_id:
                    continue
                
                existing = db.query(BankTransaction).filter(
                    BankTransaction.finapi_transaction_id == txn_id
                ).first()
                
                if existing:
                    skipped_count += 1
                    continue  # Überspringe bereits importierte
                
                # Erstelle neue Transaktion
                booking_date_str = trans_data.get("bookingDate")
                if not booking_date_str:
                    logger.warning(f"No bookingDate for transaction {trans_data.get('id')}")
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
            
            # Aktualisiere last_sync auch wenn keine neuen Transaktionen (für zukünftige Syncs)
            bank_account.last_sync = date.today()
            
            if imported_count > 0:
                db.commit()
                logger.info(f"✅ Imported {imported_count} new transactions, skipped {skipped_count} existing ones for account {bank_account.id}")
            else:
                db.commit()
                if skipped_count > 0:
                    logger.info(f"ℹ️ No new transactions found ({skipped_count} already exist). Last sync updated to {bank_account.last_sync}")
                else:
                    logger.info(f"ℹ️ No transactions found in date range. Last sync updated to {bank_account.last_sync}")
            
            return imported_count
            
        except Exception as e:
            logger.error(f"Failed to sync transactions: {str(e)}")
            return 0


# Globale Instanz
real_finapi_service = RealFinAPIService()
