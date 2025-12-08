import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import HTTPException, status
from ..config import settings
import logging

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str):
    """
    Send a professional verification email to the user.
    Uses SendGrid API if SENDGRID_API_KEY is set, otherwise falls back to SMTP.
    
    Args:
        to_email: User's email address
        token: JWT verification token
    
    Raises:
        HTTPException: If email sending fails
    """
    # Use SendGrid API if available (better for Render)
    if settings.SENDGRID_API_KEY:
        return _send_via_sendgrid_api(to_email, token)
    else:
        return _send_via_smtp(to_email, token)


def _get_verification_link(token: str) -> str:
    """Get the verification link URL"""
    if settings.BACKEND_URL:
        backend_url = settings.BACKEND_URL
    else:
        if "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL:
            backend_url = settings.FRONTEND_URL.replace(":5173", ":8000").replace("localhost", "127.0.0.1")
        else:
            backend_url = settings.FRONTEND_URL.replace(":5173", ":8000")
    return f"{backend_url}/auth/verify?token={token}"


def _get_email_html(verify_link: str) -> str:
    """Get HTML email content"""
    return f"""
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
                                Immpire
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
                                Willkommen bei Immpire!
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
                                <strong style="color: #4a5568;">Das Immpire Team</strong>
                            </p>
                            <p style="margin: 20px 0 0 0; color: #a0aec0; font-size: 12px; line-height: 1.6;">
                                Immpire<br>
                                kontakt@immpire.com
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


def _get_email_text(verify_link: str) -> str:
    """Get plain text email content"""
    return f"""Immpire - E-Mail-Verifizierung

Willkommen bei Immpire!

Vielen Dank für Ihre Registrierung. Um Ihr Konto zu aktivieren, bestätigen Sie bitte Ihre E-Mail-Adresse, indem Sie auf den folgenden Link klicken:

{verify_link}

WICHTIG: Dieser Link ist 1 Stunde gültig. Falls der Link abgelaufen ist, registrieren Sie sich bitte erneut.

Mit freundlichen Grüßen,
Das Immpire Team

Immpire
kontakt@immpire.com

Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht auf diese E-Mail."""


def _send_via_sendgrid_api(to_email: str, token: str):
    """Send email using SendGrid API (preferred method)"""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        
        logger.info(f"📧 Sending verification email via SendGrid API to: {to_email}")
        
        verify_link = _get_verification_link(token)
        logger.info(f"🔗 Verifizierungs-Link: {verify_link}")
        
        from_email = settings.SMTP_FROM_EMAIL.strip() if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip() else "kontakt@izenic.com"
        
        # Get email content
        html_content = _get_email_html(verify_link)
        text_content = _get_email_text(verify_link)
        
        # Create Mail object
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject="E-Mail-Verifizierung – Immpire",
            html_content=html_content,
            plain_text_content=text_content
        )
        
        # Send via SendGrid API
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        
        logger.info(f"✅ Verification email sent successfully via SendGrid API to {to_email} (Status: {response.status_code})")
        
    except ImportError:
        logger.error("❌ SendGrid library not installed. Install with: pip install sendgrid")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SendGrid library not installed. Please install sendgrid package."
        )
    except Exception as e:
        logger.error(f"❌ SendGrid API error: {str(e)}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email via SendGrid API. Please try again later."
        )


def _send_via_smtp(to_email: str, token: str):
    """Send email using SMTP (fallback method)"""
    if not settings.SMTP_HOST or not settings.SMTP_PORT or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SMTP configuration incomplete. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD."
        )
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "E-Mail-Verifizierung – Immpire"
        # Verwende SMTP_FROM_EMAIL falls gesetzt, sonst SMTP_USER
        from_email = settings.SMTP_FROM_EMAIL.strip() if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip() else settings.SMTP_USER
        msg["From"] = from_email
        msg["To"] = to_email
        
        logger.info(f"📧 Sending verification email from: {from_email} to: {to_email}")

        verify_link = _get_verification_link(token)
        logger.info(f"🔗 Verifizierungs-Link: {verify_link}")

        # Get email content
        html = _get_email_html(verify_link)
        text = _get_email_text(verify_link)

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        logger.info(f"🔌 Connecting to SMTP server: {settings.SMTP_HOST}:{settings.SMTP_PORT}")
        # Set timeout to prevent hanging (10 seconds)
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        logger.info(f"✅ Connected to SMTP server")
        
        logger.info(f"🔐 Starting TLS...")
        server.starttls()
        logger.info(f"✅ TLS started")
        
        logger.info(f"🔑 Logging in as {settings.SMTP_USER}...")
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        logger.info(f"✅ Logged in successfully")
        
        logger.info(f"📤 Sending email to {to_email}...")
        result = server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        
        if result:
            logger.warning(f"⚠️ SMTP server returned errors: {result}")
        else:
            logger.info(f"✅ Verification email sent successfully to {to_email} from {from_email}")
        
    except smtplib.SMTPConnectError as e:
        logger.error(f"❌ SMTP connection error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not connect to email server. Please contact support."
        )
    except (socket.timeout, TimeoutError) as e:
        logger.error(f"❌ SMTP timeout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email server timeout. Please try again later."
        )
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP authentication failed for {settings.SMTP_USER}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email configuration error. Please contact support."
        )
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error sending email to {to_email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again later."
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error sending email to {to_email}: {str(e)}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )
