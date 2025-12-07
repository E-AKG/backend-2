import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import HTTPException, status
from ..config import settings
import logging

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str):
    """
    Send a professional verification email to the user.
    
    Args:
        to_email: User's email address
        token: JWT verification token
    
    Raises:
        HTTPException: If email sending fails
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "E-Mail-Verifizierung – IZENIC ImmoAssist"
        # Verwende SMTP_FROM_EMAIL falls gesetzt, sonst SMTP_USER
        from_email = settings.SMTP_FROM_EMAIL.strip() if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip() else settings.SMTP_USER
        msg["From"] = from_email
        msg["To"] = to_email
        
        logger.info(f"📧 Sending verification email from: {from_email} to: {to_email}")

        # Backend verification link (gibt direkt HTML zurück, funktioniert auch auf Handy)
        # Falls BACKEND_URL nicht gesetzt ist, versuche aus FRONTEND_URL abzuleiten
        if settings.BACKEND_URL:
            backend_url = settings.BACKEND_URL
        else:
            # Fallback: Versuche aus FRONTEND_URL abzuleiten
            if "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL:
                # Warnung: localhost funktioniert nicht auf Handy!
                logger.warning(f"⚠️ BACKEND_URL nicht gesetzt und FRONTEND_URL enthält localhost!")
                logger.warning(f"⚠️ Verifizierungs-Link wird wahrscheinlich auf Handy nicht funktionieren!")
                logger.warning(f"⚠️ Bitte setze BACKEND_URL in .env (z.B. BACKEND_URL=http://192.168.178.51:8000)")
                # Verwende trotzdem FRONTEND_URL als Fallback (wird wahrscheinlich nicht funktionieren)
                backend_url = settings.FRONTEND_URL.replace(":5173", ":8000").replace("localhost", "127.0.0.1")
            else:
                # FRONTEND_URL enthält bereits eine IP-Adresse
                backend_url = settings.FRONTEND_URL.replace(":5173", ":8000")
        
        verify_link = f"{backend_url}/auth/verify?token={token}"
        logger.info(f"🔗 Verifizierungs-Link: {verify_link}")

        # Professionelles HTML-Template
        html = f"""
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>E-Mail-Verifizierung</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f5f7fa;">
            <table role="presentation" style="width: 100%; border-collapse: collapse; background-color: #f5f7fa;">
                <tr>
                    <td style="padding: 40px 20px;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); overflow: hidden;">
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; text-align: center;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;">
                                        IZENIC ImmoAssist
                                    </h1>
                                    <p style="margin: 10px 0 0 0; color: rgba(255, 255, 255, 0.9); font-size: 16px;">
                                        Immobilienverwaltung leicht gemacht
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px 30px;">
                                    <h2 style="margin: 0 0 20px 0; color: #1a202c; font-size: 24px; font-weight: 600;">
                                        Willkommen bei IZENIC ImmoAssist!
                                    </h2>
                                    
                                    <p style="margin: 0 0 20px 0; color: #4a5568; font-size: 16px; line-height: 1.6;">
                                        Vielen Dank für Ihre Registrierung! Um Ihr Konto zu aktivieren, bestätigen Sie bitte Ihre E-Mail-Adresse.
                                    </p>
                                    
                                    <p style="margin: 0 0 30px 0; color: #4a5568; font-size: 16px; line-height: 1.6;">
                                        Klicken Sie einfach auf den Button unten, um Ihre E-Mail-Adresse zu verifizieren.
                                    </p>
                                    
                                    <!-- CTA Button -->
                                    <table role="presentation" style="width: 100%; border-collapse: collapse; margin: 30px 0;">
                                        <tr>
                                            <td style="text-align: center; padding: 20px 0;">
                                                <a href="{verify_link}" 
                                                   style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-size: 16px; font-weight: 600; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); transition: all 0.3s ease;">
                                                    E-Mail-Adresse bestätigen
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                    
                                    <!-- Alternative Link -->
                                    <div style="margin: 30px 0; padding: 20px; background-color: #f7fafc; border-radius: 8px; border-left: 4px solid #667eea;">
                                        <p style="margin: 0 0 10px 0; color: #718096; font-size: 14px; font-weight: 600;">
                                            Falls der Button nicht funktioniert:
                                        </p>
                                        <p style="margin: 0; color: #4a5568; font-size: 14px; line-height: 1.6; word-break: break-all;">
                                            Kopieren Sie diesen Link in Ihren Browser:<br>
                                            <a href="{verify_link}" style="color: #667eea; text-decoration: none;">{verify_link}</a>
                                        </p>
                                    </div>
                                    
                                    <!-- Info Box -->
                                    <div style="margin: 30px 0; padding: 15px; background-color: #fff5e6; border-radius: 8px; border-left: 4px solid #f6ad55;">
                                        <p style="margin: 0; color: #744210; font-size: 14px; line-height: 1.6;">
                                            <strong>⏰ Wichtig:</strong> Dieser Link ist 1 Stunde gültig. Falls der Link abgelaufen ist, registrieren Sie sich bitte erneut.
                                        </p>
                                    </div>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px; background-color: #f7fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                                    <p style="margin: 0 0 10px 0; color: #718096; font-size: 14px; line-height: 1.6;">
                                        Mit freundlichen Grüßen,<br>
                                        <strong style="color: #4a5568;">Das IZENIC Team</strong>
                                    </p>
                                    <p style="margin: 20px 0 0 0; color: #a0aec0; font-size: 12px; line-height: 1.6;">
                                        IZENIC GmbH<br>
                                        kontakt@izenic.com
                                    </p>
                                    <p style="margin: 20px 0 0 0; color: #cbd5e0; font-size: 12px;">
                                        Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht auf diese E-Mail.
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
        
        # Plain Text Version
        text = f"""
IZENIC ImmoAssist - E-Mail-Verifizierung

Willkommen bei IZENIC ImmoAssist!

Vielen Dank für Ihre Registrierung. Um Ihr Konto zu aktivieren, bestätigen Sie bitte Ihre E-Mail-Adresse, indem Sie auf den folgenden Link klicken:

{verify_link}

WICHTIG: Dieser Link ist 1 Stunde gültig. Falls der Link abgelaufen ist, registrieren Sie sich bitte erneut.

Mit freundlichen Grüßen,
Das IZENIC Team

IZENIC GmbH
kontakt@izenic.com

Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht auf diese E-Mail.
        """

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(from_email, to_email, msg.as_string())
        
        logger.info(f"✅ Verification email sent successfully to {to_email} from {from_email}")
        
    except smtplib.SMTPAuthenticationError:
        logger.error(f"SMTP authentication failed for {settings.SMTP_USER}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email configuration error. Please contact support."
        )
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email to {to_email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again later."
        )
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )