"""
PDF-Generator für Mahnungen und andere Dokumente
Verwendet HTML-Templates mit Jinja2 und konvertiert zu PDF mit WeasyPrint
"""
import os
from pathlib import Path
from typing import Dict, Optional
from datetime import date
from decimal import Decimal
import logging

# Setze Library-Pfade für macOS (Homebrew)
if os.name == 'posix' and os.uname().sysname == 'Darwin':
    homebrew_lib = '/opt/homebrew/lib'
    if os.path.exists(homebrew_lib):
        current_ld_path = os.environ.get('DYLD_LIBRARY_PATH', '')
        if homebrew_lib not in current_ld_path:
            os.environ['DYLD_LIBRARY_PATH'] = f"{homebrew_lib}:{current_ld_path}" if current_ld_path else homebrew_lib

try:
    from jinja2 import Environment, FileSystemLoader, Template
    from weasyprint import HTML, CSS
    PDF_AVAILABLE = True
except ImportError as e:
    PDF_AVAILABLE = False
    logging.warning(f"Jinja2 oder WeasyPrint nicht installiert. PDF-Generierung nicht verfügbar: {e}")
except OSError as e:
    PDF_AVAILABLE = False
    logging.error(f"WeasyPrint System-Bibliotheken fehlen. Bitte installieren Sie: brew install pango gdk-pixbuf libffi cairo. Fehler: {e}")

logger = logging.getLogger(__name__)

# Template-Verzeichnis
TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)

# Output-Verzeichnis für PDFs
PDF_OUTPUT_DIR = Path(__file__).parent.parent.parent / "documents" / "pdfs"
PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def format_currency(amount: float) -> str:
    """Formatiere Betrag als Währung"""
    return f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(d: date) -> str:
    """Formatiere Datum im deutschen Format"""
    if not d:
        return ""
    return d.strftime("%d.%m.%Y")


def get_reminder_type_label(reminder_type: str) -> str:
    """Konvertiere ReminderType zu deutschem Label"""
    labels = {
        "payment_reminder": "Zahlungserinnerung",
        "first_reminder": "1. Mahnung",
        "second_reminder": "2. Mahnung",
        "final_reminder": "Letzte Mahnung",
        "legal_action": "Rechtsweg"
    }
    return labels.get(reminder_type, reminder_type)


def generate_reminder_pdf(
    reminder_data: Dict,
    template_content: Optional[str] = None,
    output_filename: Optional[str] = None
) -> str:
    """
    Generiere PDF für Mahnung aus Template
    
    Args:
        reminder_data: Dict mit allen Daten für das Template
        template_content: HTML-Template als String (optional, sonst wird Standard-Template verwendet)
        output_filename: Name der Output-Datei (optional)
    
    Returns:
        Pfad zur generierten PDF-Datei
    """
    if not PDF_AVAILABLE:
        raise RuntimeError("PDF-Generierung nicht verfügbar. Bitte installieren Sie: pip install jinja2 weasyprint")
    
    # Standard-Template falls keines übergeben wurde
    if not template_content:
        template_content = get_default_reminder_template()
    
    # Erstelle Jinja2 Template
    template = Template(template_content)
    
    # Bereite Daten für Template vor
    template_vars = prepare_reminder_data(reminder_data)
    
    # Rendere HTML
    html_content = template.render(**template_vars)
    
    # Generiere PDF
    if not output_filename:
        output_filename = f"reminder_{reminder_data.get('reminder_id', 'unknown')}.pdf"
    
    output_path = PDF_OUTPUT_DIR / output_filename
    
    try:
        # Workaround für WeasyPrint-Kompatibilitätsprobleme
        try:
            HTML(string=html_content).write_pdf(output_path)
        except AttributeError as attr_error:
            if "'super' object has no attribute 'transform'" in str(attr_error):
                logger.warning("⚠️ WeasyPrint Kompatibilitätsproblem erkannt. Versuche mit optimierten Optionen...")
                HTML(string=html_content).write_pdf(
                    output_path,
                    optimize_images=False,
                    presentational_hints=True
                )
            else:
                raise
        logger.info(f"✅ PDF generiert: {output_path}")
        return str(output_path)
    except Exception as e:
        logger.error(f"❌ Fehler beim Generieren der PDF: {str(e)}")
        raise


def prepare_reminder_data(reminder_data: Dict) -> Dict:
    """
    Bereite Daten für Template vor - konvertiert alle Werte zu Template-freundlichen Formaten
    """
    # Helper-Funktionen für Template
    template_vars = {
        # Basis-Daten
        "reminder_id": reminder_data.get("reminder_id", ""),
        "reminder_type": reminder_data.get("reminder_type", ""),
        "reminder_type_label": get_reminder_type_label(reminder_data.get("reminder_type", "")),
        "reminder_date": format_date(reminder_data.get("reminder_date")),
        "reminder_date_raw": reminder_data.get("reminder_date"),
        
        # Beträge
        "amount": float(reminder_data.get("amount", 0)),
        "amount_formatted": format_currency(float(reminder_data.get("amount", 0))),
        "reminder_fee": float(reminder_data.get("reminder_fee", 0)),
        "reminder_fee_formatted": format_currency(float(reminder_data.get("reminder_fee", 0))),
        "total_amount": float(reminder_data.get("amount", 0)) + float(reminder_data.get("reminder_fee", 0)),
        "total_amount_formatted": format_currency(
            float(reminder_data.get("amount", 0)) + float(reminder_data.get("reminder_fee", 0))
        ),
        
        # Mieter-Daten
        "tenant": {
            "first_name": reminder_data.get("tenant", {}).get("first_name", ""),
            "last_name": reminder_data.get("tenant", {}).get("last_name", ""),
            "full_name": f"{reminder_data.get('tenant', {}).get('first_name', '')} {reminder_data.get('tenant', {}).get('last_name', '')}".strip(),
            "address": reminder_data.get("tenant", {}).get("address", ""),
            "email": reminder_data.get("tenant", {}).get("email", ""),
            "phone": reminder_data.get("tenant", {}).get("phone", ""),
        },
        
        # Objekt/Einheit-Daten
        "property": {
            "name": reminder_data.get("property", {}).get("name", ""),
            "address": reminder_data.get("property", {}).get("address", ""),
        },
        "unit": {
            "label": reminder_data.get("unit", {}).get("label", ""),
            "unit_number": reminder_data.get("unit", {}).get("unit_number", ""),
        },
        
        # Charge-Daten
        "charge": {
            "amount": float(reminder_data.get("charge", {}).get("amount", 0)),
            "amount_formatted": format_currency(float(reminder_data.get("charge", {}).get("amount", 0))),
            "paid_amount": float(reminder_data.get("charge", {}).get("paid_amount", 0)),
            "paid_amount_formatted": format_currency(float(reminder_data.get("charge", {}).get("paid_amount", 0))),
            "due_date": format_date(reminder_data.get("charge", {}).get("due_date")),
            "due_date_raw": reminder_data.get("charge", {}).get("due_date"),
            "description": reminder_data.get("charge", {}).get("description", ""),
        },
        
        # Mandant/Vermieter-Daten
        "client": {
            "name": reminder_data.get("client", {}).get("name", ""),
            "address": reminder_data.get("client", {}).get("address", ""),
            "email": reminder_data.get("client", {}).get("email", ""),
            "phone": reminder_data.get("client", {}).get("phone", ""),
        },
        "owner": {
            "name": reminder_data.get("owner", {}).get("name", ""),
            "email": reminder_data.get("owner", {}).get("email", ""),
        },
        
        # Notizen
        "notes": reminder_data.get("notes", ""),
        
        # Helper-Funktionen für Template
        "format_currency": format_currency,
        "format_date": format_date,
    }
    
    return template_vars


def get_default_reminder_template() -> str:
    """
    Standard-Template für Mahnungen
    Kann später durch benutzerdefinierte Templates ersetzt werden
    """
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: Arial, sans-serif;
            font-size: 12pt;
            line-height: 1.6;
            margin: 40px;
            color: #333;
        }
        .header {
            text-align: right;
            margin-bottom: 30px;
        }
        .address-block {
            margin-bottom: 30px;
        }
        .subject {
            font-weight: bold;
            margin: 20px 0;
        }
        .content {
            margin: 20px 0;
        }
        .amount-table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        .amount-table td {
            padding: 8px;
            border-bottom: 1px solid #ddd;
        }
        .amount-table .label {
            text-align: left;
        }
        .amount-table .value {
            text-align: right;
            font-weight: bold;
        }
        .footer {
            margin-top: 40px;
            font-size: 10pt;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <p><strong>{{ client.name }}</strong></p>
        <p>{{ client.address }}</p>
        <p>{{ client.email }}</p>
    </div>
    
    <div class="address-block">
        <p><strong>{{ tenant.full_name }}</strong></p>
        <p>{{ tenant.address }}</p>
    </div>
    
    <div class="subject">
        <p>{{ reminder_type_label }} - {{ property.name }} - {{ unit.label }}</p>
    </div>
    
    <div class="content">
        <p>Sehr geehrte/r {{ tenant.first_name }} {{ tenant.last_name }},</p>
        
        <p>hiermit erinnern wir Sie an die ausstehende Zahlung Ihrer Miete.</p>
        
        <table class="amount-table">
            <tr>
                <td class="label">Fälligkeitsdatum:</td>
                <td class="value">{{ charge.due_date }}</td>
            </tr>
            <tr>
                <td class="label">Offener Betrag:</td>
                <td class="value">{{ amount_formatted }}</td>
            </tr>
            {% if reminder_fee > 0 %}
            <tr>
                <td class="label">Mahngebühr:</td>
                <td class="value">{{ reminder_fee_formatted }}</td>
            </tr>
            {% endif %}
            <tr>
                <td class="label"><strong>Gesamtbetrag:</strong></td>
                <td class="value"><strong>{{ total_amount_formatted }}</strong></td>
            </tr>
        </table>
        
        <p>Bitte überweisen Sie den ausstehenden Betrag umgehend auf unser Konto.</p>
        
        {% if notes %}
        <p><em>{{ notes }}</em></p>
        {% endif %}
    </div>
    
    <div class="footer">
        <p>Mit freundlichen Grüßen</p>
        <p>{{ client.name }}</p>
        <p>Datum: {{ reminder_date }}</p>
    </div>
</body>
</html>
"""


def load_custom_template(template_name: str) -> Optional[str]:
    """
    Lade benutzerdefiniertes Template aus Datei
    
    Args:
        template_name: Name der Template-Datei (z.B. "reminder_template.html")
    
    Returns:
        Template-Inhalt als String oder None wenn nicht gefunden
    """
    template_path = TEMPLATE_DIR / template_name
    
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    
    return None


def generate_accounting_pdf(
    accounting_data: Dict,
    template_content: Optional[str] = None,
    output_filename: Optional[str] = None
) -> str:
    """
    Generiere PDF für Betriebskostenabrechnung aus Template
    
    Args:
        accounting_data: Dict mit allen Daten für das Template
        template_content: HTML-Template als String (optional, sonst wird Standard-Template verwendet)
        output_filename: Name der Output-Datei (optional)
    
    Returns:
        Pfad zur generierten PDF-Datei
    """
    if not PDF_AVAILABLE:
        raise RuntimeError("PDF-Generierung nicht verfügbar. Bitte installieren Sie: pip install jinja2 weasyprint")
    
    # Standard-Template falls keines übergeben wurde
    if not template_content:
        template_content = get_default_accounting_template()
    
    # Erstelle Jinja2 Template
    template = Template(template_content)
    
    # Bereite Daten für Template vor
    template_vars = prepare_accounting_data(accounting_data)
    
    # Rendere HTML
    html_content = template.render(**template_vars)
    
    # Generiere PDF
    if not output_filename:
        output_filename = f"accounting_{accounting_data.get('accounting_id', 'unknown')}.pdf"
    
    output_path = PDF_OUTPUT_DIR / output_filename
    
    try:
        # Versuche PDF-Generierung mit WeasyPrint
        # Workaround für bekannte WeasyPrint-Kompatibilitätsprobleme mit Python 3.13
        try:
            HTML(string=html_content).write_pdf(output_path)
        except AttributeError as attr_error:
            if "'super' object has no attribute 'transform'" in str(attr_error):
                logger.warning("⚠️ WeasyPrint Kompatibilitätsproblem erkannt. Versuche mit optimierten Optionen...")
                # Versuche mit optimierten Optionen als Workaround
                try:
                    HTML(string=html_content).write_pdf(
                        output_path,
                        optimize_images=False,
                        presentational_hints=True
                    )
                except Exception as e2:
                    logger.error(f"❌ Auch Workaround fehlgeschlagen: {str(e2)}")
                    raise attr_error  # Re-raise original error
            else:
                raise
        logger.info(f"✅ Abrechnungs-PDF generiert: {output_path}")
        return str(output_path)
    except Exception as e:
        logger.error(f"❌ Fehler beim Generieren der Abrechnungs-PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def generate_settlement_pdf(
    settlement_data: Dict,
    template_content: Optional[str] = None,
    output_filename: Optional[str] = None
) -> str:
    """
    Generiere PDF für Einzelabrechnung (pro Mieter) aus Template
    
    Args:
        settlement_data: Dict mit allen Daten für das Template
        template_content: HTML-Template als String (optional, sonst wird Standard-Template verwendet)
        output_filename: Name der Output-Datei (optional)
    
    Returns:
        Pfad zur generierten PDF-Datei
    """
    if not PDF_AVAILABLE:
        raise RuntimeError("PDF-Generierung nicht verfügbar. Bitte installieren Sie: pip install jinja2 weasyprint")
    
    # Standard-Template falls keines übergeben wurde
    if not template_content:
        template_content = get_default_settlement_template()
    
    # Erstelle Jinja2 Template
    template = Template(template_content)
    
    # Bereite Daten für Template vor
    template_vars = prepare_settlement_data(settlement_data)
    
    # Rendere HTML
    html_content = template.render(**template_vars)
    
    # Generiere PDF
    if not output_filename:
        tenant_name = settlement_data.get("tenant", {}).get("last_name", "unknown")
        output_filename = f"settlement_{settlement_data.get('settlement_id', 'unknown')}_{tenant_name}.pdf"
    
    output_path = PDF_OUTPUT_DIR / output_filename
    
    try:
        # Workaround für WeasyPrint-Kompatibilitätsprobleme
        try:
            HTML(string=html_content).write_pdf(output_path)
        except AttributeError as attr_error:
            if "'super' object has no attribute 'transform'" in str(attr_error):
                logger.warning("⚠️ WeasyPrint Kompatibilitätsproblem erkannt. Versuche mit optimierten Optionen...")
                HTML(string=html_content).write_pdf(
                    output_path,
                    optimize_images=False,
                    presentational_hints=True
                )
            else:
                raise
        logger.info(f"✅ Einzelabrechnungs-PDF generiert: {output_path}")
        return str(output_path)
    except Exception as e:
        logger.error(f"❌ Fehler beim Generieren der Einzelabrechnungs-PDF: {str(e)}")
        raise


def prepare_accounting_data(accounting_data: Dict) -> Dict:
    """
    Bereite Daten für Abrechnungs-Template vor
    """
    from datetime import date as date_class
    
    template_vars = {
        "accounting_id": accounting_data.get("accounting_id", ""),
        "accounting_type": accounting_data.get("accounting_type", ""),
        "accounting_type_label": "Betriebskostenabrechnung" if accounting_data.get("accounting_type") == "operating_costs" else "Hausgeldabrechnung",
        "period_start": format_date(accounting_data.get("period_start")),
        "period_end": format_date(accounting_data.get("period_end")),
        "period_start_raw": accounting_data.get("period_start"),
        "period_end_raw": accounting_data.get("period_end"),
        
        "total_costs": float(accounting_data.get("total_costs", 0)),
        "total_costs_formatted": format_currency(float(accounting_data.get("total_costs", 0))),
        "total_advance_payments": float(accounting_data.get("total_advance_payments", 0)),
        "total_advance_payments_formatted": format_currency(float(accounting_data.get("total_advance_payments", 0))),
        "total_settlement": float(accounting_data.get("total_settlement", 0)),
        "total_settlement_formatted": format_currency(float(accounting_data.get("total_settlement", 0))),
        
        "items": accounting_data.get("items", []),
        "settlements": accounting_data.get("settlements", []),
        
        "client": {
            "name": accounting_data.get("client", {}).get("name", ""),
            "address": accounting_data.get("client", {}).get("address", ""),
            "email": accounting_data.get("client", {}).get("email", ""),
            "phone": accounting_data.get("client", {}).get("phone", ""),
        },
        
        "notes": accounting_data.get("notes", ""),
        
        "date": date_class,  # Für date.today() im Template
        "format_currency": format_currency,
        "format_date": format_date,
    }
    
    return template_vars


def prepare_settlement_data(settlement_data: Dict) -> Dict:
    """
    Bereite Daten für Einzelabrechnungs-Template vor
    """
    from datetime import date as date_class
    
    template_vars = {
        "settlement_id": settlement_data.get("settlement_id", ""),
        "accounting_id": settlement_data.get("accounting_id", ""),
        
        "period_start": format_date(settlement_data.get("period_start")),
        "period_end": format_date(settlement_data.get("period_end")),
        
        "advance_payments": float(settlement_data.get("advance_payments", 0)),
        "advance_payments_formatted": format_currency(float(settlement_data.get("advance_payments", 0))),
        "allocated_costs": float(settlement_data.get("allocated_costs", 0)),
        "allocated_costs_formatted": format_currency(float(settlement_data.get("allocated_costs", 0))),
        "settlement_amount": float(settlement_data.get("settlement_amount", 0)),
        "settlement_amount_formatted": format_currency(float(settlement_data.get("settlement_amount", 0))),
        "is_credit": float(settlement_data.get("settlement_amount", 0)) < 0,
        
        "tenant": {
            "first_name": settlement_data.get("tenant", {}).get("first_name", ""),
            "last_name": settlement_data.get("tenant", {}).get("last_name", ""),
            "full_name": f"{settlement_data.get('tenant', {}).get('first_name', '')} {settlement_data.get('tenant', {}).get('last_name', '')}".strip(),
            "address": settlement_data.get("tenant", {}).get("address", ""),
        },
        
        "property": {
            "name": settlement_data.get("property", {}).get("name", ""),
            "address": settlement_data.get("property", {}).get("address", ""),
        },
        
        "unit": {
            "label": settlement_data.get("unit", {}).get("label", ""),
            "unit_number": settlement_data.get("unit", {}).get("unit_number", ""),
            "size_sqm": settlement_data.get("unit", {}).get("size_sqm", 0),
        },
        
        "items": settlement_data.get("items", []),
        "non_allocable_items": settlement_data.get("non_allocable_items", []),
        "allocation_key_label": settlement_data.get("allocation_key_label", "nach Fläche (m²)"),
        "tenant_period_start": settlement_data.get("tenant_period_start"),
        "tenant_period_end": settlement_data.get("tenant_period_end"),
        "occupied_days": settlement_data.get("occupied_days", 0),
        "period_days": settlement_data.get("period_days", 365),
        "advance_payments_breakdown": settlement_data.get("advance_payments_breakdown", {}),
        "is_vacancy": settlement_data.get("is_vacancy", False),
        
        "client": {
            "name": settlement_data.get("client", {}).get("name", ""),
            "address": settlement_data.get("client", {}).get("address", ""),
            "email": settlement_data.get("client", {}).get("email", ""),
            "phone": settlement_data.get("client", {}).get("phone", ""),
        },
        
        "date": date_class,  # Für date.today() im Template
        "format_currency": format_currency,
        "format_date": format_date,
    }
    
    return template_vars


def get_default_accounting_template() -> str:
    """
    Standard-Template für Gesamtabrechnung
    """
    return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Betriebskostenabrechnung</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; font-size: 11pt; }
        .header { text-align: right; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .title { font-size: 16pt; font-weight: bold; margin: 20px 0; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #f5f5f5; font-weight: bold; }
        .total-row { font-weight: bold; background-color: #f9f9f9; }
        .footer { margin-top: 40px; font-size: 10pt; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <p><strong>{{ client.name }}</strong></p>
        <p>{{ client.address }}</p>
    </div>
    
    <div class="title">{{ accounting_type_label }} {{ period_start }} - {{ period_end }}</div>
    
    <h3>Kostenübersicht</h3>
    <table>
        <thead>
            <tr>
                <th>Kostenart</th>
                <th>Beschreibung</th>
                <th>Betrag</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ item.cost_type }}</td>
                <td>{{ item.description }}</td>
                <td>{{ format_currency(item.amount) }}</td>
            </tr>
            {% endfor %}
            <tr class="total-row">
                <td colspan="2">Gesamtkosten</td>
                <td>{{ total_costs_formatted }}</td>
            </tr>
        </tbody>
    </table>
    
    <h3>Verteilung auf Einheiten</h3>
    <table>
        <thead>
            <tr>
                <th>Mieter</th>
                <th>Einheit</th>
                <th>Vorauszahlungen</th>
                <th>Anteilige Kosten</th>
                <th>Nachzahlung/Guthaben</th>
            </tr>
        </thead>
        <tbody>
            {% for settlement in settlements %}
            <tr>
                <td>{{ settlement.tenant_name }}</td>
                <td>{{ settlement.unit_label }}</td>
                <td>{{ format_currency(settlement.advance_payments) }}</td>
                <td>{{ format_currency(settlement.allocated_costs) }}</td>
                <td>{{ format_currency(settlement.settlement_amount) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <div class="footer">
        <p>Erstellt am: {{ format_date(date.today()) }}</p>
    </div>
</body>
</html>
"""


def get_default_settlement_template() -> str:
    """
    Standard-Template für Einzelabrechnung (pro Mieter)
    """
    return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Betriebskostenabrechnung - {{ tenant.full_name }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; font-size: 11pt; line-height: 1.6; }
        .header { text-align: right; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .recipient { margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #333; }
        .title { font-size: 16pt; font-weight: bold; margin: 20px 0; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #2c3e50; color: white; }
        .total-row { font-weight: bold; background-color: #f5f5f5; font-size: 13pt; }
        .settlement-amount { font-size: 18pt; font-weight: bold; padding: 20px; text-align: center; margin: 20px 0; }
        .settlement-amount.positive { background-color: #fff3cd; color: #856404; }
        .settlement-amount.negative { background-color: #d1ecf1; color: #0c5460; }
        .footer { margin-top: 40px; font-size: 10pt; color: #666; border-top: 1px solid #ddd; padding-top: 20px; }
    </style>
</head>
<body>
    <div class="header">
        <p><strong>{{ client.name }}</strong></p>
        <p>{{ client.address }}</p>
        {% if client.email %}<p>E-Mail: {{ client.email }}</p>{% endif %}
        {% if client.phone %}<p>Telefon: {{ client.phone }}</p>{% endif %}
    </div>
    
    <div class="recipient">
        <p><strong>{{ tenant.full_name }}</strong></p>
        <p>{{ tenant.address }}</p>
    </div>
    
    <div class="title">Betriebskostenabrechnung {{ period_start }} - {{ period_end }}</div>
    <p>Objekt: <strong>{{ property.name }}</strong> - {{ unit.label }}</p>
    
    <h3>Kostenaufstellung</h3>
    <table>
        <thead>
            <tr>
                <th>Kostenart</th>
                <th>Beschreibung</th>
                <th>Betrag</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ item.cost_type }}</td>
                <td>{{ item.description }}</td>
                <td>{{ format_currency(item.amount) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <h3>Abrechnung</h3>
    <table>
        <tr>
            <td>Anteilige Kosten:</td>
            <td style="text-align: right; font-weight: bold;">{{ allocated_costs_formatted }}</td>
        </tr>
        <tr>
            <td>Geleistete Vorauszahlungen:</td>
            <td style="text-align: right;">{{ advance_payments_formatted }}</td>
        </tr>
        <tr class="total-row">
            <td>{% if is_credit %}Guthaben{% else %}Nachzahlung{% endif %}:</td>
            <td style="text-align: right;">{{ settlement_amount_formatted }}</td>
        </tr>
    </table>
    
    <div class="settlement-amount {% if is_credit %}negative{% else %}positive{% endif %}">
        {% if is_credit %}
        Guthaben: {{ settlement_amount_formatted }}
        {% else %}
        Nachzahlung: {{ settlement_amount_formatted }}
        {% endif %}
    </div>
    
    <div class="footer">
        <p>Mit freundlichen Grüßen</p>
        <p><strong>{{ client.name }}</strong></p>
        <p>Datum: {{ format_date(date.today()) }}</p>
    </div>
</body>
</html>
"""

