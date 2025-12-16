# PDF-Templates für Mahnungen

## Wie funktioniert es?

1. **Erstellen Sie ein HTML-Template** mit Platzhaltern (z.B. `{{ tenant.full_name }}`)
2. **Speichern Sie es hier** als `.html` Datei
3. **System füllt automatisch** alle Platzhalter mit Daten aus
4. **PDF wird generiert** und kann heruntergeladen werden

## Verfügbare Platzhalter

### Mieter-Daten
- `{{ tenant.first_name }}` - Vorname
- `{{ tenant.last_name }}` - Nachname
- `{{ tenant.full_name }}` - Vollständiger Name
- `{{ tenant.address }}` - Adresse
- `{{ tenant.email }}` - E-Mail
- `{{ tenant.phone }}` - Telefon

### Objekt/Einheit
- `{{ property.name }}` - Objektname
- `{{ property.address }}` - Objektadresse
- `{{ unit.label }}` - Einheitsbezeichnung (z.B. "Wohnung 1a")
- `{{ unit.unit_number }}` - Einheitsnummer

### Mahnungs-Daten
- `{{ amount }}` - Offener Betrag (Zahl)
- `{{ amount_formatted }}` - Offener Betrag formatiert (z.B. "700,00 €")
- `{{ reminder_fee }}` - Mahngebühr (Zahl)
- `{{ reminder_fee_formatted }}` - Mahngebühr formatiert
- `{{ total_amount }}` - Gesamtbetrag (Zahl)
- `{{ total_amount_formatted }}` - Gesamtbetrag formatiert
- `{{ reminder_type }}` - Mahnstufe (z.B. "payment_reminder")
- `{{ reminder_type_label }}` - Mahnstufe auf Deutsch (z.B. "Zahlungserinnerung")
- `{{ reminder_date }}` - Mahndatum (z.B. "14.12.2024")
- `{{ reminder_id }}` - Eindeutige ID der Mahnung

### Sollbuchung (Charge)
- `{{ charge.amount }}` - Ursprünglicher Betrag (Zahl)
- `{{ charge.amount_formatted }}` - Ursprünglicher Betrag formatiert
- `{{ charge.paid_amount }}` - Bereits bezahlter Betrag (Zahl)
- `{{ charge.paid_amount_formatted }}` - Bereits bezahlter Betrag formatiert
- `{{ charge.due_date }}` - Fälligkeitsdatum (z.B. "30.11.2024")
- `{{ charge.description }}` - Beschreibung

### Mandant/Vermieter
- `{{ client.name }}` - Mandantenname
- `{{ client.address }}` - Mandantenadresse
- `{{ client.email }}` - E-Mail
- `{{ client.phone }}` - Telefon
- `{{ owner.name }}` - Name des Vermieters
- `{{ owner.email }}` - E-Mail des Vermieters

### Sonstiges
- `{{ notes }}` - Notizen zur Mahnung

### Helper-Funktionen
- `{{ format_currency(123.45) }}` - Formatiert Zahl als Währung
- `{{ format_date(date_object) }}` - Formatiert Datum

## Beispiel-Template

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial; margin: 40px; }
        .header { text-align: right; }
        .amount { font-weight: bold; font-size: 16pt; }
    </style>
</head>
<body>
    <div class="header">
        <p><strong>{{ client.name }}</strong></p>
        <p>{{ client.address }}</p>
    </div>
    
    <p><strong>{{ tenant.full_name }}</strong></p>
    <p>{{ tenant.address }}</p>
    
    <h2>{{ reminder_type_label }}</h2>
    
    <p>Sehr geehrte/r {{ tenant.first_name }} {{ tenant.last_name }},</p>
    
    <p>hiermit erinnern wir Sie an die ausstehende Zahlung für:</p>
    <p><strong>{{ property.name }} - {{ unit.label }}</strong></p>
    
    <p class="amount">Offener Betrag: {{ amount_formatted }}</p>
    {% if reminder_fee > 0 %}
    <p>Mahngebühr: {{ reminder_fee_formatted }}</p>
    {% endif %}
    <p class="amount">Gesamtbetrag: {{ total_amount_formatted }}</p>
    
    <p>Fälligkeitsdatum: {{ charge.due_date }}</p>
    
    <p>Bitte überweisen Sie den Betrag umgehend.</p>
    
    <p>Mit freundlichen Grüßen<br>{{ client.name }}</p>
    <p>Datum: {{ reminder_date }}</p>
</body>
</html>
```

## Template hochladen

Templates können über die API hochgeladen werden (wird noch implementiert) oder direkt in diesem Verzeichnis gespeichert werden.

## Verwendung

Beim Generieren einer PDF können Sie optional einen Template-Namen angeben:
- Ohne Template: Standard-Template wird verwendet
- Mit Template: Ihr benutzerdefiniertes Template wird verwendet

