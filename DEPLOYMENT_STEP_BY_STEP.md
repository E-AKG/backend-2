# 🚀 Schritt-für-Schritt: Deployment auf Render mit immpire.com

## ✅ Voraussetzungen erfüllt
- ✅ Domain `immpire.com` gekauft
- ⏳ Render Account (falls noch nicht vorhanden)

---

## 📝 Schritt 1: Render Account erstellen

1. Gehe zu [render.com](https://render.com)
2. Klicke auf **"Get Started for Free"**
3. Melde dich mit GitHub an (empfohlen) oder mit E-Mail
4. Bestätige deine E-Mail-Adresse

---

## 📝 Schritt 2: PostgreSQL Database erstellen

1. Im Render Dashboard: **"New +"** → **"PostgreSQL"**
2. Fülle aus:
   - **Name:** `immpire-db`
   - **Database:** `immpire`
   - **User:** `immpire_user`
   - **Region:** Wähle **Frankfurt** (oder nächstgelegene)
   - **PostgreSQL Version:** 15
   - **Plan:** Free (für Start) oder Starter ($7/Monat für Produktion)
3. Klicke **"Create Database"**
4. ⚠️ **WICHTIG:** Notiere dir die **Internal Database URL** (sieht so aus: `postgresql://immpire_user:xxx@dpg-xxx-a.frankfurt-postgres.render.com/immpire`)

---

## 📝 Schritt 3: Backend Service erstellen

### 3.1 Service erstellen

1. **"New +"** → **"Web Service"**
2. **"Connect GitHub"** → Wähle dein Repository aus
3. Fülle aus:
   - **Name:** `immpire-backend`
   - **Region:** Gleiche Region wie Database (z.B. Frankfurt)
   - **Branch:** `main` (oder dein Haupt-Branch)
   - **Root Directory:** `backend` ⚠️ WICHTIG!
   - **Environment:** `Python 3`
   - **Build Command:** 
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command:**
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port $PORT
     ```
4. Klicke **"Create Web Service"**

### 3.2 Environment Variables setzen

Gehe zu **"Environment"** Tab und füge hinzu:

#### Database
```
DATABASE_URL=<INTERNAL_DATABASE_URL_VON_SCHRITT_2>
```
⚠️ Verwende die **Internal Database URL** (nicht External!)

#### JWT
```
JWT_SECRET_KEY=<GENERIERE_EINEN_SICHEREN_SCHLÜSSEL>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_HOURS=24
```

**JWT_SECRET_KEY generieren:**
```bash
# Auf deinem Mac im Terminal:
openssl rand -hex 32
```
Kopiere den generierten String und setze ihn als `JWT_SECRET_KEY`

#### SMTP (E-Mail)
```
SMTP_HOST=host285.checkdomain.de
SMTP_PORT=587
SMTP_USER=kontakt@immpire.com
SMTP_PASSWORD=<DEIN_SMTP_PASSWORT>
SMTP_FROM_EMAIL=kontakt@immpire.com
```

#### URLs
```
FRONTEND_URL=https://immpire.com
BACKEND_URL=https://api.immpire.com
```

#### App
```
APP_NAME=Immpire API
DEBUG=False
```

#### Stripe (wenn bereits konfiguriert)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
```

⚠️ **WICHTIG:** Klicke nach jeder Variable auf **"Save Changes"**

### 3.3 Domain konfigurieren (Backend)

1. Gehe zu **"Settings"** → Scroll runter zu **"Custom Domains"**
2. Klicke **"Add Custom Domain"**
3. Gib ein: `api.immpire.com`
4. Render zeigt dir DNS-Einträge an:
   - **Type:** CNAME
   - **Name:** `api`
   - **Value:** `<render-provided-value>` (z.B. `immpire-backend.onrender.com`)

⚠️ **Noch nicht in DNS eintragen!** Wir machen das später alle zusammen.

---

## 📝 Schritt 4: Frontend Service erstellen

### 4.1 Static Site erstellen

1. **"New +"** → **"Static Site"**
2. **"Connect GitHub"** → Wähle dein Repository aus
3. Fülle aus:
   - **Name:** `immpire-frontend`
   - **Branch:** `main`
   - **Root Directory:** `frontend` ⚠️ WICHTIG!
   - **Build Command:**
     ```bash
     npm install && npm run build
     ```
   - **Publish Directory:** `dist`
4. Klicke **"Create Static Site"**

### 4.2 Environment Variables setzen

Gehe zu **"Environment"** Tab:

```
VITE_API_URL=https://api.immpire.com
```

⚠️ **WICHTIG:** Klicke **"Save Changes"**

### 4.3 Domain konfigurieren (Frontend)

1. Gehe zu **"Settings"** → **"Custom Domains"**
2. Klicke **"Add Custom Domain"**
3. Gib ein: `immpire.com`
4. Optional: `www.immpire.com` (kannst du später hinzufügen)
5. Render zeigt dir DNS-Einträge an

⚠️ **Noch nicht in DNS eintragen!** Wir machen das später alle zusammen.

---

## 📝 Schritt 5: DNS-Einträge in Domain-Verwaltung

Gehe zu deinem Domain-Provider (z.B. Namecheap, GoDaddy, Cloudflare, etc.)

### 5.1 API-Subdomain (api.immpire.com)

Füge hinzu:
- **Type:** CNAME
- **Name/Host:** `api`
- **Value/Target:** `<render-provided-value-für-backend>` (z.B. `immpire-backend.onrender.com`)
- **TTL:** 3600 (oder Auto)

### 5.2 Root-Domain (immpire.com)

**Option A: CNAME (empfohlen)**
- **Type:** CNAME
- **Name/Host:** `@` (oder leer lassen)
- **Value/Target:** `<render-provided-value-für-frontend>` (z.B. `immpire-frontend.onrender.com`)
- **TTL:** 3600

**Option B: A-Record (falls CNAME nicht unterstützt)**
- Render gibt dir eine IP-Adresse
- **Type:** A
- **Name/Host:** `@`
- **Value:** `<render-ip-adresse>`
- **TTL:** 3600

### 5.3 Optional: www-Subdomain

- **Type:** CNAME
- **Name/Host:** `www`
- **Value/Target:** `<render-provided-value-für-frontend>`
- **TTL:** 3600

⚠️ **WICHTIG:** 
- Speichere alle Änderungen
- DNS-Propagierung kann **24-48 Stunden** dauern (meist aber schneller)
- Prüfe mit: `dig immpire.com` oder [whatsmydns.net](https://www.whatsmydns.net)

---

## 📝 Schritt 6: Warten auf DNS-Propagierung

1. Warte 10-30 Minuten
2. Prüfe DNS-Propagierung:
   ```bash
   # Im Terminal:
   dig immpire.com
   dig api.immpire.com
   ```
   Oder online: [whatsmydns.net](https://www.whatsmydns.net)

3. Wenn DNS-Einträge sichtbar sind:
   - Render erkennt automatisch die Domains
   - SSL-Zertifikate werden automatisch erstellt (kann 5-10 Minuten dauern)

---

## 📝 Schritt 7: Database Migration ausführen

Sobald Backend läuft:

1. Gehe zu Backend Service → **"Shell"** Tab
2. Führe aus:
   ```bash
   cd backend
   python run_migration_risk_score.py
   ```
3. Du solltest sehen: `✅ Migration erfolgreich abgeschlossen!`

---

## 📝 Schritt 8: Testen

### 8.1 Backend testen

1. Öffne: `https://api.immpire.com/health`
2. Sollte zurückgeben: `{"status": "healthy", "database": "connected"}`

### 8.2 Frontend testen

1. Öffne: `https://immpire.com`
2. Sollte die Landing Page zeigen
3. Versuche dich zu registrieren

### 8.3 E-Mail testen

1. Registriere einen Test-Account
2. Prüfe ob Verifizierungs-E-Mail ankommt
3. Klicke auf Verifizierungs-Link

---

## ✅ Checkliste

- [ ] Render Account erstellt
- [ ] PostgreSQL Database erstellt (Internal URL notiert)
- [ ] Backend Service erstellt
- [ ] Backend Environment Variables gesetzt
- [ ] Frontend Service erstellt
- [ ] Frontend Environment Variable gesetzt
- [ ] DNS-Einträge in Domain-Provider konfiguriert
- [ ] DNS-Propagierung abgewartet (10-30 Min)
- [ ] SSL-Zertifikate aktiv (automatisch von Render)
- [ ] Database Migration ausgeführt
- [ ] Backend Health-Check erfolgreich
- [ ] Frontend lädt korrekt
- [ ] Test-Registrierung funktioniert

---

## 🐛 Häufige Probleme

### Problem: Backend startet nicht
**Lösung:**
- Prüfe Logs in Render Dashboard
- Prüfe ob alle Environment Variables gesetzt sind
- Prüfe ob `DATABASE_URL` korrekt ist (Internal URL!)

### Problem: Frontend kann Backend nicht erreichen
**Lösung:**
- Prüfe ob `VITE_API_URL=https://api.immpire.com` gesetzt ist
- Prüfe Browser Console (F12) für Fehler
- Prüfe CORS-Einstellungen

### Problem: Domain zeigt nicht auf Service
**Lösung:**
- Warte auf DNS-Propagierung (kann 24-48h dauern)
- Prüfe DNS mit `dig immpire.com`
- Prüfe ob Domain in Render korrekt konfiguriert ist

### Problem: SSL-Zertifikat fehlt
**Lösung:**
- Warte 5-10 Minuten nach DNS-Propagierung
- Render erstellt SSL automatisch
- Prüfe in Render Dashboard → Settings → Custom Domains

---

## 📞 Nächste Schritte

Nach erfolgreichem Deployment:

1. **Stripe konfigurieren:**
   - Webhook erstellen: `https://api.immpire.com/api/payments/webhook`
   - Webhook Secret in Environment Variables setzen

2. **Monitoring einrichten:**
   - Render bietet integriertes Monitoring
   - Optional: Externe Monitoring-Tools

3. **Backup-Strategie:**
   - Render macht automatische Backups (bei Paid Plans)
   - Optional: Manuelle Backups einrichten

---

## 💡 Tipps

- **Free Plan Limits:** 
  - Services schlafen nach 15 Min Inaktivität
  - Erste Request kann 30-60 Sekunden dauern
  - Für Produktion: Starter Plan ($7/Monat) empfohlen

- **Performance:**
  - Statische Assets werden über CDN ausgeliefert
  - Database ist in gleicher Region wie Services

- **Updates:**
  - Push zu GitHub → Automatisches Deployment
  - Oder manuell: Service → "Manual Deploy"

---

**Viel Erfolg! 🚀**

Bei Fragen oder Problemen: Prüfe die Logs in Render Dashboard oder die Troubleshooting-Sektion oben.

