RFID Kaffee-Counter mit Micropython auf Raspberry Pi Pico W

Die Datei Log/Karte_NutzerID.log speichert die Zuordnung der Karten zu den Nutzern und wird nur durch das einlesen eines unbekannten Tags oder manuell editiert. Beim einlesen eines unbekannten Tags wird der Tag neu angelegt. Nutzername ist hierbei die Tag-ID.
Jeder Tag erhält eine eigene Zeile. Ist ein Nutzername mehrfach vorhanden, werden die Kaffees beider Tags, auf ein Konto in der NutzerID_Kaffee.log gerechnet.
Format der Datei:
'Tag-ID':'Nutzername'
'Tag-ID':'Nutzername'

Die Datei Log/NutzerID_Kaffee.log speichert die Anzahl der Kaffees zu den Nutzern. Jeder Nutzer erhält eine Zeile. Jeder Nutzername sollte in der Karte_NutzerID.log  mindestens einem Tag zugewiesen sein.
Format der Datei:
'Nutzername':'Kaffeeanzahl'
'Nutzername':'Kaffeeanzahl'

Es ist darauf zu achten dass die Nutzer in der Karte_NutzerID.log und der NutzerID_Kaffee.log exakt gleich geschrieben sind, so dass eine Zuordnung stattfinden kann. Fehler bei der Zuordnung werden derzeit nicht abgefangen und führen zum Absturz.

Hinweise zum LCD Display:
\xE1 // gibt ein ä aus
\xEF // gibt ein ö aus
\xF5 // gibt ein ü aus
\xE2 // gibt ein ß aus
\xDF // gibt ein ° aus
\xE4 // gibt ein µ aus
\xF4 // gibt ein Ω aus