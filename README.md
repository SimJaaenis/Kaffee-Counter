# Kaffee-Counter (MicroPython, Raspberry Pi Pico W/WH)

Team-Kaffeekasse mit NFC/RFID, LCD, RGB-Backlight, Buzzer, Buttons, Encoder, RTC, SD-Backup, Admin-Portal und optionalem seriellen Drucker.

## Wichtig: Projekt auf den Pico kopieren
- Der **gesamte Ordner `RasPiPico`** wird auf den Raspberry Pi Pico kopiert.
- Die Dateien liegen danach direkt auf dem Pico-Dateisystem (z. B. `main.py`, `kiosk.py`, `store.py`, `drivers/...`).
- Startdatei ist `main.py` (wird bei Boot ausgeführt).

## Wichtig: Verkabelung
- Bitte die Verkabelung exakt nach `docs/Kaffee-Counter-Anschlussplan.jpg` aufbauen.
- Der Anschlussplan ist die verbindliche Referenz für den realen Aufbau.

## Projektstruktur (Repository)
```text
/RasPiPico
  main.py
  kiosk.py
  store.py
  ledger.py
  logger.py
  admin_portal.py
  printer_service.py
  config_pins.py
  /drivers
    ...
  /data
    /config
    /logs
    /backup
/docs
  Kaffee-Counter-Anschlussplan.jpg
  Bedienungsanleitung_Kaffee-Counter.md
  Aushang_Kaffee-Counter_kurz.md
```

## Setup
1. MicroPython auf den Pico W/WH flashen.
2. Optional SD-Karte als FAT32 formatieren und einstecken.
3. Inhalt von `RasPiPico` auf den Pico kopieren.
4. Pico neu starten.

## Boot-Modi
- Normalbetrieb:
  - Kiosk startet.
- Admin-Modus:
  - Beim Boot weißen Taster gedrückt halten.
  - AP startet, Portal unter `http://192.168.4.1/`.
- SD-Import beim Boot:
  - Beim Boot roten Taster lange halten.
  - Nur dann wird Konfiguration von SD nach intern importiert.

## Datenhaltung (aktuell)
- Interne Daten auf dem Pico sind die **Single Source of Truth**.
- Laufzeit (Config, Nutzer, Balances, Logs) arbeitet intern unter `data/`.
- SD ist für manuelle Importe/Backups.
- Backup intern -> SD:
  - roter Taster `>= 3s` im Betrieb
  - oder über Admin-Dashboard

## Kernfunktionen
- Produkt buchen per Karte.
- Kontostand anzeigen.
- Storno innerhalb 5s nach Buchung.
- Druckfunktionen:
  - Einzelbeleg pro Buchung EIN/AUS (Encoder lang).
  - Zeitraum-Druck pro Nutzer.
  - Ranking-Druck (Woche/Monat/Jahr).
- Admin-Portal:
  - Nutzer, Karten, Produkte, Einzahlungen, Logs, Zeit, Admins, Jingles.

## Pinout und Details
- Alle konkreten Pins/Verbindungen bitte dem Anschlussplan entnehmen:
  - `docs/Kaffee-Counter-Anschlussplan.jpg`

## Troubleshooting (kurz)
- NFC nicht erreichbar:
  - I2C, Adresse, Versorgung prüfen.
- SD nicht verfügbar:
  - FAT32, Kartenkontakt, SPI-Verkabelung prüfen.
- Drucker druckt kryptisch:
  - Baudrate/8N1 am Drucker prüfen und mit Konfiguration abgleichen.

