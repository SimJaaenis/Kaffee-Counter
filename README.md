# RFID Kaffee-Counter

Implementiert mit Micropython auf Raspberry Pi Pico W.

## Gehäuse

Die STL-Datei ist für ein "[TEKO Gehäuse, 115.5, ABS, Hellgrau, 161 x 95 x 60 mm, Europult](https://www.pollin.de/p/teko-gehaeuse-115-5-abs-hellgrau-161-x-95-x-60-mm-europult-460938)" erstellt worden.

## Initiales Setup

### Micropython Setup in VS Code

1. Go to <https://micropython.org/download/> and download the latest version for the Pico or Pico W. You can use this [direct link](https://micropython.org/download/RPI_PICO_W/).
2. Plugin the device into the computer while holding the `bootsel` button.
3. Drag the UF2 file onto your Pico once it is done downloading. *It should show up on your Desktop as RPI-RP2.
4. Once it is done, the RPI-RP2 will disappear.
5. Unplug and replug the Pico (without holding the `bootsel` ). You need to do this so VSCode can find the device.

Now install VS Code plugin:

1. Make sure you have Python 3.9 installed on your computer. It is one of the requirements for the extension.
2. Go to extensions in VSCode and install the extension. Search [MicroPico](https://marketplace.visualstudio.com/items?itemName=paulober.pico-w-go).

### Wenn der Raspberry Pi läuft

Vor der initalen Nutzung sollte mit dem ausführen der [SetTime Modul](SetTime.py) die aktuelle Uhrzeit und das Datum eingestellt werden, welche auf das RTC-Modul DS1307 gespeichert wird. Die Uhrzeit und das Datum wird im Leerlauf auf dem 16x2 LCD-Display angezeigt.

## Tag Typen

Es können die speziellen Tag-Typen *goldTag*, *silverTag* und *bronzeTag* jeweils einem RFID-Tag zugewiesen werden.
Die Funktion der speziellen Tag-Typen ist wie folgt:

| Tag | Beschreibung |
| --- | --- |
| goldTag | Der GoldTag ist in der Lage den Kaffee Counter eines Nutzers auf 0 zu reseten. Dazu muss der GoldTag ausgelesen werden und nach aufforderung der zu Nutzertag der zurückgesetzt werden soll. Der Counter wird anschließend auf 0 gesetzt und die Anzahl ein letztes mal im Display angezeigt. Im Anschluss kann nicht mehr nachvollzogen werden wie viele Kaffees getrunken wurden. |
| silverTag | Der Silver Tag funktioniert wie der GoldTag, nur dass die Anzahl der bezogenen Kaffees im Anschluss nicht gelöscht wird. Der Tag wurde auf nachfrage der Nutzer implementiert für Nutzer, die ihre aktuellen Bezüge selbst prüfen wollten. |
| bronzeTag | Der BronzeTag existiert aus Demonstrationsgründen um Nutzern bei der ersteinweisung zu zeigen was passiert, wenn ein unbekannter Tag erkannt wird. Es erscheint nach dem scannen des Tags die Meldung "Nutzer unbekannt" - "Neuer Nutzer hinzugefügt", allerding ohne einen neuen Nutzer anzulegen. Um den einzuweisenden Nutzern das korrekte scannen zu demonstrieren, empfiehlt es sich einen normalen Nutzer als Demo-Nutzer anzulegen |

## Datenhaltung

### Format der Datei Karte_NutzerID

Die Datei [Karte_NutzerID.log](Logs/Karte_NutzerID.log) speichert die Zuordnung der Karten zu den Nutzern und wird nur durch das einlesen eines unbekannten Tags oder manuell editiert. Beim einlesen eines unbekannten Tags wird der Tag neu angelegt. Nutzername ist hierbei die Tag-ID.
Jeder Tag erhält eine eigene Zeile. Ist ein Nutzername mehrfach vorhanden, werden die Kaffees beider Tags, auf ein Konto in der `NutzerID_Kaffee.log` gerechnet. Ist eine Tag-ID mehrfach vorhanden wird beim einlesen der letzte/unterste Eintrag genutzt, da die vorherigen Einträge durch das erneute zuweisen des Nutzernamens überschrieben werden.

Format der Datei:

```ini
'Tag-ID':'Nutzername'
'Tag-ID':'Nutzername'
```

### Format der Datei NutzerID_Kaffee

Die Datei [NutzerID_Kaffee.log](Logs/NutzerID_Kaffee.log) speichert die Anzahl der Kaffees zu den Nutzern. Jeder Nutzer erhält eine Zeile. Jeder Nutzername sollte in der `Karte_NutzerID.log` mindestens einem Tag zugewiesen sein.

Format der Datei:

```ini
'Nutzername':'Kaffeeanzahl'
'Nutzername':'Kaffeeanzahl'
```

Es ist darauf zu achten, dass die Nutzer in der `Karte_NutzerID.log` und der `NutzerID_Kaffee.log` **exakt gleich geschrieben** sind, so dass eine Zuordnung stattfinden kann. Fehler bei der Zuordnung werden derzeit nicht abgefangen und führen zum Absturz.

## Known bugs / quirks

Um derzeit Umlaute auf dem LCD Display darzustellen sind folgende Codes zu nutzen:
\xE1 // gibt ein ä aus
\xEF // gibt ein ö aus
\xF5 // gibt ein ü aus
\xE2 // gibt ein ß aus
\xDF // gibt ein ° aus
\xE4 // gibt ein µ aus
\xF4 // gibt ein Ω aus

ggf. Umstellung auf eine andere lib, behebt dieses Problem. Issue [#1](https://github.com/SimJaaenis/Kaffee-Counter/issues/1) erstellt.
<https://werner.rothschopf.net/202003_arduino_liquid_crystal_umlaute.htm>
