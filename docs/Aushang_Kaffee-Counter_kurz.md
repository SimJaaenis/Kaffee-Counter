# Kaffee-Counter (Kurz-Aushang)

## Schnellbedienung
1. Produkt mit Drehencoder wählen.
2. Optional: `Grün` = direkt auf Standardprodukt springen.
3. Karte an den Leser halten -> Buchung wird durchgeführt.

## Kontostand
1. `Weiß` drücken.
2. Karte an den Leser halten.
3. Kontostand wird angezeigt.
4. `Rot` = zurück, `Grün` = Standardprodukt.

## Storno nach Buchung
- Nach einer Buchung gibt es ein 5s-Storno-Fenster.
- `Rot kurz` innerhalb der 5s -> Buchung wird storniert.

## Druckfunktionen am Gerät
- `Encoder > 5s` drücken: Einzel-Quittung pro Buchung EIN/AUS.
- In Kontostand-Ansicht: Zeitraum wählen (Woche/Monat), Vorschau sehen, mit `Grün` drucken.
- `Weiß + Grün > 5s`: Ranking-Druck (Woche/Monat/Jahr).

## Datensicherung
- `Rot >= 3s` im Betrieb: internes Backup auf SD (wenn SD steckt).

## Admin-Portal
- Beim Einschalten `Weiß` gedrückt halten -> Admin-WLAN startet.
- Browser: `http://192.168.4.1/`

## Wichtig
- Interne Daten sind die Hauptdatenquelle (Single Source of Truth).
- SD-Import beim Boot nur manuell: beim Einschalten `Rot` lange halten.
