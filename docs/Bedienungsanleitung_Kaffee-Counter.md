# Bedienungsanleitung Kaffee-Counter

## 1. Zweck
Der Kaffee-Counter ist eine RFID/NFC-basierte Team-Kaffeekasse auf Raspberry Pi Pico W.  
Nutzer buchen Produkte mit Karte, sehen ihren Kontostand, und Administratoren verwalten das System über ein lokales Admin-Portal.

## 2. Bedienung am Gerät (Nutzer)

### 2.1 Anzeige im Leerlauf (Idle)
- Im Idle zeigt das Display zentriert:
  - `Kaffee-Counter`
  - aktuelle Uhrzeit (minutengenau)
- Bei Inaktivität wird nur das Backlight gedimmt (Bildschirmschoner).  
  Der Text bleibt sichtbar.
- Bei Eingaben (Karte, Encoder, grüne Taste) wird das Backlight wieder aktiv.

### 2.2 Tasten und Encoder
- `Grün`:
  - Springt auf das Standardprodukt.
  - In bestimmten Untermenüs: Bestätigen/Drucken.
- `Weiß`:
  - Startet Kontostand-Abfrage (`Bitte Karte halten`).
- `Rot kurz`:
  - Zurück/Abbrechen.
  - Im 5s-Storno-Fenster: Storno ausführen.
- `Rot lang (>= 3s)`:
  - Backup interner Daten auf SD (wenn SD vorhanden).
- `Drehencoder links/rechts`:
  - Produktwahl oder Wertauswahl in Menüs.
- `Encoder drücken`:
  - Menü-Wechsel/Bestätigung (kontextabhängig).
- `Encoder lang (>5s)`:
  - Einzel-Quittung pro Buchung EIN/AUS.

### 2.3 Produkt buchen
1. Produkt mit Encoder wählen (oder `Grün` für Standardprodukt).
2. Karte an den NFC-Leser halten.
3. Buchung wird durchgeführt.
4. Anzeige zeigt Betrag und aktuellen Saldo.
5. RGB/Buzzer geben Feedback (Erfolg/Fehler).

### 2.4 Kontostand anzeigen
1. `Weiß` drücken.
2. Karte an den Leser halten.
3. Kontostand wird angezeigt.
4. `Rot` -> zurück zum Hauptmodus, `Grün` -> Standardprodukt.

### 2.5 Storno direkt nach Buchung
- Nach erfolgreicher Buchung startet ein 5s-Storno-Fenster.
- Anzeige: Countdown.
- `Rot kurz` innerhalb des Fensters:
  - Gegenbuchung (`undo`) wird geschrieben.
  - Display/Buzzer bestätigen Storno.

## 3. Druckfunktionen (serieller Drucker via MAX3232)

### 3.1 Einzelbelege pro Buchung
- Mit `Encoder >5s` im Kioskmodus ein-/ausschalten.

### 3.2 Druck aus Kontostand-Ansicht (eigene Buchungen)
- Nach Kontostand-Anzeige:
  - `Encoder drücken`: Zeitraum Woche/Monat wechseln.
  - `Encoder drehen`: Zeitraum-Offset wählen (z. B. letzte Woche, vorletzter Monat).
- Display zeigt Vorschau (Anzahl Buchungen + Summe).
- `Grün` druckt, `Rot` bricht ab.

### 3.3 Ranking-Druck
- `Weiß + Grün` gleichzeitig >5s halten.
- Ablauf:
  1. Zeitraumtyp wählen (Woche/Monat/Jahr).
  2. Zeitraumwert wählen (KW/Monat/Jahr).
  3. Vorschau sehen.
  4. `Grün` druckt, `Rot` zurück.

## 4. Datenhaltung und SD-Karte

### 4.1 Single Source of Truth
- Laufzeitdaten liegen intern auf dem Pico (`/data`).
- Dazu gehören:
  - Konfiguration
  - Nutzer/Balances
  - Buchungslogs

### 4.2 SD-Import beim Boot (nur manuell)
- SD wird **nicht automatisch** als Quelle verwendet.
- SD -> intern Import nur bei Boot mit lang gehaltenem roten Taster.

### 4.3 SD-Backup
- Backup intern -> SD:
  - im Betrieb: `Rot >= 3s`
  - oder im Admin-Portal per Button
- Funktioniert auch mit frisch eingesteckter, leerer FAT32-SD (Verzeichnisse werden angelegt).

## 5. Admin-Modus / Admin-Portal

### 5.1 Start
1. Gerät neu starten.
2. Während Boot `Weiß` gedrückt halten.
3. Pico startet Admin-AP.
4. Browser: `http://192.168.4.1/`

### 5.2 Login
- Login mit Admin-Zugangsdaten aus Konfiguration.
- Optional ist RFID-Login für Admins möglich (wenn Karte einem Admin zugeordnet ist).

### 5.3 Wichtige Bereiche
- `Dashboard`: Systemstatus, SD-Sicherung.
- `Nutzer`: Umbenennen, Karte hinzufügen/entfernen, Nutzer löschen (mit Bestätigung via `user_id`).
- `Nutzer anlegen`: Nutzer direkt per Kartenscan erstellen.
- `Einzahlung`: Guthaben buchen.
- `Logs`: paginierte Logansicht mit Filtern.
- `Products`: Produkte anlegen/ändern/löschen, Default setzen, Farbe setzen.
- `Admins`: mehrere Adminkonten verwalten.
- `Passwort`: Admin-Passwort ändern.
- `Zeit`: RTC-Zeit anzeigen, manuell setzen, Browserzeit synchronisieren.
- `Jingles`: Boot-Jingle konfigurieren.
- `Änderungslog`: Admin-Aktionen nachvollziehen.

## 6. Signale (RGB/Buzzer)
- Erfolg: grünes Feedback + kurzer Erfolgston.
- Fehler/Storno: rotes Feedback + Fehler-/Stornoton.
- Produktauswahl: kurzer Klickton (konfigurierbar).
- Admin-AP: blaues Statusfeedback möglich.

## 7. Typische Abläufe

### 7.1 Neue Konfiguration von SD übernehmen
1. SD vorbereiten (`/sd/config/...`).
2. Gerät neu starten.
3. Beim Boot roten Taster lange halten.
4. Boot-Status zeigt `SD-Import: EIN`.

### 7.2 Sicherung erstellen
1. SD einstecken.
2. `Rot >= 3s` drücken.
3. Backup wird auf SD geschrieben.

## 8. Fehlerbehebung
- `NFC nicht erreichbar`:
  - I2C prüfen (`0x24`), Versorgung, Bus.
- `RTC nicht erreichbar`:
  - DS1307 auf `0x68` prüfen, Versorgung/Batterie.
- `Logs im Portal langsam`:
  - Filter setzen (Nutzer/Typ/Zeitraum), kleinere Seitenzahl nutzen.
- `Druck nur kryptische Zeichen`:
  - Baudrate/8N1 am Drucker prüfen (z. B. 38400 laut Drucker-Setup),
  - RS232-Pegelwandler/Pinout/Kabellänge prüfen.

## 9. Betriebsempfehlungen
- Regelmäßig SD-Backups erstellen.
- Nach Admin-Änderungen zeitnah auf SD sichern.
- RTC-Zeit regelmäßig im Admin-Tab `Zeit` prüfen/synchronisieren.
