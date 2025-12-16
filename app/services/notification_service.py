"""
Notification Service für E-Mail-Versand
Abstrahiert E-Mail-Versand über SendGrid API
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import HTTPException, status
from ..config import settings
from ..models.notification import Notification, NotificationStatus, NotificationType
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class NotificationService:
    """Service für E-Mail-Benachrichtigungen via SendGrid"""
    
    @staticmethod
    def send_email(
        db: Session,
        to_email: str,
        subject: str,
        template: str,
        data: Dict[str, Any],
        recipient_id: Optional[str] = None,
        notification_type: NotificationType = NotificationType.OTHER,
        document_id: Optional[str] = None,
        from_user_id: Optional[int] = None  # User-ID des Absenders (für Absender-E-Mail)
    ) -> bool:
        """
        Sende E-Mail via SendGrid API
        
        Args:
            db: Database session
            to_email: Empfänger-E-Mail
            subject: Betreff
            template: Template-Name (z.B. "bk_published")
            data: Template-Daten (z.B. {"year": 2025, "tenant_name": "Max Mustermann"})
            recipient_id: Optional: portal_user_id oder tenant_id
            notification_type: Typ der Benachrichtigung
            document_id: Optional: Verknüpfung zu Dokument
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        # Erstelle Notification-Log (PENDING)
        notification = Notification(
            recipient_email=to_email,
            recipient_id=recipient_id,
            notification_type=notification_type,
            status=NotificationStatus.PENDING,
            subject=subject,
            document_id=document_id
        )
        db.add(notification)
        db.flush()
        
        try:
            # Bestimme Absender-E-Mail
            from_email = NotificationService._get_from_email(db, from_user_id)
            logger.info(f"📧 Verwende Absender-E-Mail: {from_email}")
            
            # Prüfe ob SendGrid verfügbar ist
            sendgrid_available = False
            try:
                import sendgrid
                sendgrid_available = True
            except ImportError:
                logger.error("❌ SendGrid-Bibliothek nicht installiert!")
                logger.error("💡 Installiere SendGrid mit: pip install sendgrid==6.11.0")
                logger.error("💡 Oder verwende Python 3.11: python3.11 -m pip install sendgrid==6.11.0")
                raise Exception("SendGrid-Bibliothek nicht installiert. Bitte installieren Sie SendGrid: pip install sendgrid==6.11.0")
            
            # Hole SendGrid API Key
            sendgrid_key = None
            if settings.SENDGRID_API_KEY and settings.SENDGRID_API_KEY.strip():
                sendgrid_key = settings.SENDGRID_API_KEY.strip()
            elif settings.SMTP_PASSWORD and settings.SMTP_PASSWORD.strip().startswith('SG.'):
                sendgrid_key = settings.SMTP_PASSWORD.strip()
            
            if not sendgrid_key:
                logger.error("❌ SENDGRID_API_KEY nicht in .env konfiguriert!")
                logger.error("💡 Füge SENDGRID_API_KEY=SG.xxxxx... zu deiner .env Datei hinzu")
                raise Exception("SENDGRID_API_KEY nicht konfiguriert. Bitte füge SENDGRID_API_KEY zu deiner .env Datei hinzu.")
            
            # Verwende SendGrid API
            logger.info("📧 Verwende SendGrid für E-Mail-Versand")
            success = NotificationService._send_via_sendgrid(
                to_email, subject, template, data, sendgrid_key, from_email
            )
            
            # Update Notification-Status
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
                db.commit()
                logger.info(f"✅ E-Mail erfolgreich gesendet an {to_email}")
                return True
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "E-Mail-Versand fehlgeschlagen"
                db.commit()
                return False
                
        except Exception as e:
            error_msg = str(e)
            notification.status = NotificationStatus.FAILED
            notification.error_message = error_msg[:500]  # Max 500 Zeichen
            db.commit()
            logger.error(f"❌ Fehler beim Senden der E-Mail an {to_email}: {error_msg}")
            return False
    
    @staticmethod
    def _get_from_email(db: Session, user_id: Optional[int]) -> str:
        """
        Bestimme Absender-E-Mail:
        1. SMTP_FROM_EMAIL aus Config (Priorität - für SendGrid-Verifizierung)
        2. User.email (Login-E-Mail) - Fallback
        3. SMTP_USER aus Config (Fallback)
        4. kontakt@izenic.com (letzter Fallback)
        """
        # PRIORITÄT 1: SMTP_FROM_EMAIL (wird für SendGrid-Verifizierung benötigt)
        if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip():
            return settings.SMTP_FROM_EMAIL.strip()
        
        # Fallback: User-E-Mail
        if user_id:
            from ..models.user import User
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.email:
                return user.email.strip()
        
        # SMTP_USER als Fallback
        if settings.SMTP_USER and settings.SMTP_USER.strip():
            return settings.SMTP_USER.strip()
        
        # Letzter Fallback
        return "kontakt@izenic.com"
    
    @staticmethod
    def _send_via_sendgrid(
        to_email: str,
        subject: str,
        template: str,
        data: Dict[str, Any],
        api_key: str,
        from_email: str
    ) -> bool:
        """Sende E-Mail via SendGrid API"""
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            
            # Validiere API-Key
            api_key = api_key.strip()
            if not api_key.startswith('SG.') or len(api_key) < 50:
                logger.error("❌ SendGrid API-Key ungültig")
                return False
            
            # Generiere E-Mail-Inhalt basierend auf Template
            html_content = NotificationService._get_template_html(template, data)
            text_content = NotificationService._get_template_text(template, data)
            
            # Erstelle Mail-Objekt
            message = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content,
                plain_text_content=text_content
            )
            
            # Sende via SendGrid
            sg = SendGridAPIClient(api_key)
            response = sg.send(message)
            
            if response.status_code in [200, 202]:
                logger.info(f"✅ SendGrid E-Mail gesendet: Status {response.status_code}")
                return True
            else:
                # Detaillierte Fehlerbehandlung
                error_body = ""
                try:
                    error_body = response.body.decode('utf-8') if response.body else ""
                except:
                    pass
                
                logger.error(f"❌ SendGrid Fehler: Status {response.status_code}")
                logger.error(f"❌ SendGrid Response: {error_body}")
                
                if response.status_code == 403:
                    logger.error("💡 Mögliche Ursachen für 403 Forbidden:")
                    logger.error("   1. API-Key hat nicht die 'Mail Send' Berechtigung")
                    logger.error("   2. Absender-E-Mail-Adresse ist nicht verifiziert in SendGrid")
                    logger.error("   3. API-Key ist ungültig oder abgelaufen")
                    logger.error(f"   Absender-E-Mail: {from_email}")
                    logger.error("💡 Lösung:")
                    logger.error("   1. Gehe zu SendGrid → Settings → API Keys")
                    logger.error("   2. Prüfe, ob der API-Key 'Mail Send' Berechtigung hat")
                    logger.error("   3. Gehe zu SendGrid → Settings → Sender Authentication")
                    logger.error("   4. Verifiziere die Absender-E-Mail-Adresse")
                
                return False
                
        except ImportError:
            logger.warning("⚠️ SendGrid-Bibliothek nicht installiert, verwende SMTP-Fallback")
            # Fallback zu SMTP
            from_email = NotificationService._get_from_email(db, from_user_id) if 'db' in locals() and 'from_user_id' in locals() else "kontakt@izenic.com"
            return NotificationService._send_via_smtp(to_email, subject, template, data, from_email)
        except Exception as e:
            logger.error(f"❌ SendGrid-Fehler: {str(e)}")
            if "403" in str(e) or "Forbidden" in str(e):
                logger.error("💡 403 Forbidden bedeutet:")
                logger.error("   - API-Key hat nicht die richtigen Berechtigungen")
                logger.error("   - Oder Absender-E-Mail ist nicht verifiziert")
                logger.error(f"   Absender-E-Mail: {from_email}")
            return False
    
    @staticmethod
    def _send_via_smtp(
        to_email: str,
        subject: str,
        template: str,
        data: Dict[str, Any],
        from_email: str
    ) -> bool:
        """Sende E-Mail via SMTP (Fallback)"""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            if not all([settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER, settings.SMTP_PASSWORD]):
                logger.error("❌ SMTP-Konfiguration unvollständig")
                return False
            
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to_email
            
            html_content = NotificationService._get_template_html(template, data)
            text_content = NotificationService._get_template_text(template, data)
            
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(from_email, to_email, msg.as_string())
            server.quit()
            
            logger.info(f"✅ SMTP E-Mail gesendet an {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ SMTP-Fehler: {str(e)}")
            return False
    
    @staticmethod
    def _get_template_html(template: str, data: Dict[str, Any]) -> str:
        """Generiere HTML-Inhalt basierend auf Template"""
        if template == "portal_invitation":
            tenant_name = data.get("tenant_name", "")
            email = data.get("email", "")
            temp_password = data.get("temp_password", "")
            portal_url = data.get("portal_url", settings.FRONTEND_URL)
            
            return f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Einladung zum Mieterportal</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f5f5f5;">
    <table role="presentation" style="width: 100%; border-collapse: collapse; background-color: #f5f5f5;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="padding: 40px 30px; text-align: center; background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%);">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px;">Immpire</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px 30px;">
                            <h2 style="margin: 0 0 20px 0; color: #164e63;">Einladung zum Mieterportal</h2>
                            <p style="margin: 0 0 20px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Sehr geehrte/r {tenant_name},
                            </p>
                            <p style="margin: 0 0 20px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Sie wurden zum Mieterportal eingeladen. Hier können Sie Ihre Betriebskostenabrechnungen und zugehörige Belege einsehen und herunterladen.
                            </p>
                            <div style="background-color: #f8fafc; border-left: 4px solid #0e7490; padding: 20px; margin: 30px 0; border-radius: 4px;">
                                <p style="margin: 0 0 10px 0; color: #164e63; font-weight: 600; font-size: 14px;">Ihre Login-Daten:</p>
                                <p style="margin: 5px 0; color: #155e75; font-size: 16px;"><strong>E-Mail:</strong> {email}</p>
                                <p style="margin: 5px 0; color: #155e75; font-size: 16px;"><strong>Passwort:</strong> <code style="background-color: #e2e8f0; padding: 4px 8px; border-radius: 4px; font-family: monospace;">{temp_password}</code></p>
                            </div>
                            <p style="margin: 20px 0; color: #64748b; font-size: 14px;">
                                <strong>⚠️ Wichtig:</strong> Bitte ändern Sie Ihr Passwort nach dem ersten Login.
                            </p>
                            <table role="presentation" style="width: 100%; border-collapse: collapse; margin: 30px 0;">
                                <tr>
                                    <td style="text-align: center; padding: 20px 0;">
                                        <a href="{portal_url}/portal/login" 
                                           style="display: inline-block; background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%); color: #ffffff; text-decoration: none; padding: 15px 30px; border-radius: 6px; font-size: 16px; font-weight: 600;">
                                            Zum Mieterportal
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 30px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                            <p style="margin: 0; color: #64748b; font-size: 14px;">
                                Mit freundlichen Grüßen,<br>
                                <strong style="color: #0e7490;">Das Immpire Team</strong>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""
        elif template == "bk_published":
            year = data.get("year", "")
            tenant_name = data.get("tenant_name", "")
            portal_url = data.get("portal_url", settings.FRONTEND_URL)
            
            return f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neue Betriebskostenabrechnung</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f5f5f5;">
    <table role="presentation" style="width: 100%; border-collapse: collapse; background-color: #f5f5f5;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="padding: 40px 30px; text-align: center; background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%);">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px;">Immpire</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px 30px;">
                            <h2 style="margin: 0 0 20px 0; color: #164e63;">Neue Betriebskostenabrechnung verfügbar</h2>
                            <p style="margin: 0 0 20px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Sehr geehrte/r {tenant_name},
                            </p>
                            <p style="margin: 0 0 20px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Ihre Betriebskostenabrechnung für das Jahr {year} ist jetzt im Mieterportal verfügbar.
                            </p>
                            <p style="margin: 0 0 30px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Sie können die Abrechnung und zugehörige Belege im Portal einsehen und herunterladen.
                            </p>
                            <table role="presentation" style="width: 100%; border-collapse: collapse; margin: 30px 0;">
                                <tr>
                                    <td style="text-align: center; padding: 20px 0;">
                                        <a href="{portal_url}/portal/bk/{year}" 
                                           style="display: inline-block; background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%); color: #ffffff; text-decoration: none; padding: 15px 30px; border-radius: 6px; font-size: 16px; font-weight: 600;">
                                            Zum Mieterportal
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 30px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                            <p style="margin: 0; color: #64748b; font-size: 14px;">
                                Mit freundlichen Grüßen,<br>
                                <strong style="color: #0e7490;">Das Immpire Team</strong>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""
        else:
            # Fallback-Template
            return f"<html><body><p>{data.get('message', '')}</p></body></html>"
    
    @staticmethod
    def _get_template_text(template: str, data: Dict[str, Any]) -> str:
        """Generiere Plain-Text-Inhalt basierend auf Template"""
        if template == "portal_invitation":
            tenant_name = data.get("tenant_name", "")
            email = data.get("email", "")
            temp_password = data.get("temp_password", "")
            portal_url = data.get("portal_url", settings.FRONTEND_URL)
            
            return f"""Einladung zum Mieterportal

Sehr geehrte/r {tenant_name},

Sie wurden zum Mieterportal eingeladen. Hier können Sie Ihre Betriebskostenabrechnungen und zugehörige Belege einsehen und herunterladen.

Ihre Login-Daten:
E-Mail: {email}
Passwort: {temp_password}

⚠️ Wichtig: Bitte ändern Sie Ihr Passwort nach dem ersten Login.

Zum Mieterportal: {portal_url}/portal/login

Mit freundlichen Grüßen,
Das Immpire Team
"""
        elif template == "bk_published":
            year = data.get("year", "")
            tenant_name = data.get("tenant_name", "")
            portal_url = data.get("portal_url", settings.FRONTEND_URL)
            
            return f"""Neue Betriebskostenabrechnung verfügbar

Sehr geehrte/r {tenant_name},

Ihre Betriebskostenabrechnung für das Jahr {year} ist jetzt im Mieterportal verfügbar.

Sie können die Abrechnung und zugehörige Belege im Portal einsehen und herunterladen.

Zum Mieterportal: {portal_url}/portal/bk/{year}

Mit freundlichen Grüßen,
Das Immpire Team
"""
        else:
            return data.get('message', '')

