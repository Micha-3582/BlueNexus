# Änderungsprotokoll

Hier steht, was sich in welcher Version geändert hat. Die Versionsnummer steht in der App unter *Einstellungen → System* („Installierte Version“), in `app/VERSION` und als Tag/Release auf GitHub (`v1.6.0` …).

**Zählweise:** `1.x.0` = neue Funktionen, `1.x.y` = Fehlerbehebungen und Kleinigkeiten. Die genauen Einzeländerungen stehen im Verlauf der Commits.

## 1.9.2 – 26.10.2026
- Fix: Auch die Freigabe direkt am Eintrag („Sichtbar für …“) blendet einen global vom Dashboard ausgeblendeten Eintrag wieder ein. Neu angelegte Geräte, Sensoren und Schalter sind anfangs vom Dashboard ausgeblendet (Augen-Symbol in den Listen); ohne dieses Auge blieb die Kachel für Konten leer.

## 1.9.1 – 26.10.2026
- Fix: Einträge, die vom Dashboard ausgeblendet waren, blieben trotz Freigabe für ein Konto unsichtbar. Beim Anhaken in „Sichtbare Geräte …“ werden sie jetzt auch auf dem Dashboard angezeigt; betroffene Einträge sind mit „(nicht auf dem Dashboard)“ markiert.

## 1.9.0 – 26.10.2026
- Neu: in der **Benutzerverwaltung** gibt es pro normalem Konto den Bereich **„Sichtbare Geräte, Sensoren, Schalter …“**. Dort lässt sich per Haken festlegen, was das Konto sehen darf (Geräte, Sensoren, eigene Schalter & Knöpfe, Wake-on-LAN, Thermostate, Rollläden, Soundmodule, Kameras) – gesammelt statt einzeln an jedem Ding. Neu angelegte Dinge sind zunächst nur für Administratoren sichtbar, bis sie hier freigegeben werden.
- Neu: **Profil kopieren** (Knopf ⧉ am Konto): legt ein neues Konto mit denselben Rechten, Kacheln, Reihenfolge und Sichtbarkeiten an – nur Name und Passwort neu.
- Fix: die Einstellungskarte **Diagramme** (Energie stündlich) erscheint nur noch, wenn das Energiemodul eingeschaltet ist.

## 1.8.2 – 27.10.2026
- Fix: die Kachel **Wetter** hat jetzt eine Überschrift wie die anderen Kacheln.

## 1.8.1 – 27.10.2026
- Fix: der Reiter **Logbuch** hat in der schmalen Ansicht (Handy, Symbolleiste) jetzt ein Symbol.

## 1.8.0 – 27.10.2026
- **UV-Index im Wetter:** aktuell (mit Einstufung nach WHO), pro Stunde in den nächsten 24 Stunden (ab UV 1) und als Tagesmaximum in der 7-Tage-Übersicht, farbig von niedrig bis extrem (Open-Meteo, ohne Zusatzschlüssel).

## 1.7.0 – 27.10.2026
- **Messwert eines Geräts als Sensor:** z. B. nur die Außen- oder Innentemperatur einer Klimaanlage oder die Leistung einer Steckdose als eigener Sensor – mit Verlauf, in Regeln nutzbar und **einzeln teilbar, ohne das Gerät zu teilen** (Thermometer-Symbol beim Gerät).

## 1.6.0 – 26.10.2026
- **Geräte-Logbuch** (*Smart Home → Logbuch*, nur Administratoren): wer hat wann welches Gerät bedient – von Hand, per Regel, Automatik, Alexa, Telegram oder Freigabe –, dazu Sensor-Wechsel, Regel-Ereignisse und fremde Zugriffsversuche (unbekanntes Handy, NFC-/QR-Tag, falsche PIN, fehlgeschlagene Anmeldung) mit Adresse. Das Regel-Logbuch ist darin aufgegangen; „zuletzt …“ steht in den Listen.
- **Schaltvorgänge von außen** (Lichtschranke, Taster am Gerät, eigener Timer) kommen ins Logbuch: Tasmota meldet per Regel im Gerät (Glocken-Symbol), Homematic über die CCU.
- **Zustand eines Geräts als Sensor** (z. B. Torstatus-Relais: AN = geschlossen), auch **aus der Leistung** mit einstellbarer Watt-Schwelle (z. B. Lampe hinter Messrelais). Änderbar und wieder entfernbar.
- **Schneller:** die Oberfläche wartet nicht mehr auf langsame oder ausgefallene Geräte (letzter Zustand sofort, Auffrischung im Hintergrund, wachsende Pause bei Offline-Geräten, geteilte Quellen ohne Warten). Neue Karte *Sonstiges → Geschwindigkeit (Fehlersuche)*.
- **Alle Symbole bei allem** (165 Symbole für Aktoren, Sensoren, Schalter, Rechner, Thermostate, Schlösser); das Logbuch zeigt das eingestellte Symbol.
- **Telegram:** Fehlermeldung nennt, was fehlt; „Test senden“ probiert eingetippte Werte; Auslöser von Befehlen stehen im Logbuch.
- Meldungen: Felder für Akku/Tageszusammenfassung nur mit Energie-Modul.
- Fehlerbehebungen: Regel-Logbuch ohne Energie-Modul (Laden/Leeren/Zähler), Zähler nach Uhrensprung, Logbuch-Worte bei umgekehrten Sensoren, Sensor-Anzeige „AN = geschlossen“.

## 1.5.0 – 25.10.2026
- **Tasmota-Messwerte als Sensoren** (Temperatur, Luftfeuchte, Luftdruck, Leistung; auch Geräte ohne Relais, einzelne IP abfragbar).
- **Thermostate von Hand einstellen** (Homematic/Zigbee, Regler 5–30 °C) mit Sichtbarkeit pro Benutzer.
- **Alles teilbar:** Thermostate, Türschlösser, Rollläden, Soundmodule und Wake-on-LAN neben Geräten, Sensoren und Schaltern; geteilte Einträge erscheinen auch ohne eigene CCU.
- **Türschlösser von Hand bedienen** (Verriegeln, Entriegeln, Öffnen mit Bestätigung), auch geteilte.
- **Persönliches Auge:** Benutzer ohne Stift blenden freigegebene Einträge auf ihrem eigenen Dashboard aus.
- **IP-Adresse nachträglich änderbar** (Geräte im Heimnetz und Wake-on-LAN).
- Tasmota schneller (PulseTime nur bei Bedarf, Zustand aus der Antwort); Favoriten fragen nur noch die Favoriten ab.
- Diagramme: Legende linksbündig mit quadratischen Kästchen, Infokasten blendet sich am Handy nach 3 Sekunden aus.
- Fix: Python 3.9 (Annotation in `_shelly_payload`).

## 1.4.0 – 18.10.2026
- **Favoriten:** Stern an Geräten, Sensoren, Schaltern und Wake-on-LAN, Dashboard-Kachel, pro Konto.
- **Offene Lese-Schnittstelle** `/api/v1` (nur lesend, nur Heimnetz, Schlüssel pro Programm).
- **cloudflared** aktualisieren: neue Version anzeigen und per Klick installieren.
- **Etikettendruck** (NFC + QR) auf Niimbot D110/D110_M per Web Bluetooth am Android-Handy; Zusatz-App *QR Direkt* in Handbuch und App.
- PIN-geschützte Schalter springen erst nach der PIN um und behalten den gelben Rahmen.

## 1.3.0 – 13.10.2026
- **Klimaanlagen (Midea) lokal steuern:** Schlüssel über das MSmartHome-Konto, ⇄ Lokal, automatische Wiederholung, Schutz vor Kontosperre.
- Diagramme mit normalem Mauspfeil.

## 1.2.0 – 10.10.2026
- **Geräte teilen** zwischen BlueNexus-Anlagen (Freigaben und fremde Quellen per Einladungscode).
- **Telegram-Befehle:** Triggerwörter in Regeln, nur freigegebene Chats, Antworttexte einstellbar.
- **NFC-Tags direkt mit dem Handy beschreiben** (Web NFC, Android/Chrome).
- Regeln steuern Regeln; Benutzer mit Haken „Administrator“, Hauptkonto; Rückfragen als App-Fenster statt Browser-Popup.
- Meldungen: Telegram, Pushover und „Was soll gemeldet werden“ als getrennte Karten.
- Intelligente Planung: Preisschwelle „Immer laden unter“, PV-Reserve als Ladestand, neue Karte „Laden aus dem Netz“.

## 1.1.0 – 9.10.2026
- **Demo-Modus** (`BLUENEXUS_DEMO=1`) mit simulierten Geräten, CCU, Klimaanlagen, Kameras und Wetter.
- NFC: PIN-Abfrage nach dem Scannen, Registrierung ohne Seitenwechsel, Link-Vorschau; Knöpfe mit Web-Aufruf und Regel-Schritt „Adresse aufrufen“.
- Hell/Dunkel pro Gerät, Hintergrund wie die Homepage, Uhrzeit und Zeitzone in den Systemeinstellungen, Testmodus umschaltbar.
- Kameras: Chime der Reolink-Türklingel; Passwort vergessen per Telegram/Pushover oder Wiederherstellungsschlüssel.
- Homematic: klassisches Keymatic als Türschloss; Batterie-Watchdog ohne Alarm bei leerem Akku.

## 1.0.0 – 8.10.2026
- Erste veröffentlichte Version: Energie-Steuerung für Victron (ESS, Tibber, PV-Prognose), Smart Home (Shelly, Tasmota, WLED, Tuya, Homematic, Zigbee, Klimaanlagen, Wake-on-LAN), Regeln, Kameras, NFC-Tags und Fernzugriff.
