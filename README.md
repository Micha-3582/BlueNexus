# BlueNexus – ESS & Smart Home

### Smart-Home-Zentrale und Energiemanagement in einer selbst gehosteten Web-App

*Open Source (GPL-3.0) · läuft lokal · ohne Cloud-Zwang.* Der Name: **Blue** erinnert an die Herkunft als Steuerung für Victron-ESS-Anlagen, **Nexus** steht für die Verknüpfung mit dem ganzen Haus.

> 📖 **Bedienung und alle Einstellungen: siehe das [Handbuch](MANUAL.md).**

Diese Software ist **mehr als eine Victron-Steuerung**. Sie ist eine eigenständige, lokal laufende
**Smart-Home-Zentrale** – ohne ioBroker, Home Assistant, Node-RED oder Cloud-Zwang – und bringt dabei ein
vollwertiges **Energiemanagement für Victron-ESS-Anlagen mit dynamischem Strompreis** gleich mit.

Jede Installation trägt den Namen ihres Besitzers: Beim ersten Start fragt die App nach dem Vornamen und heißt
dann z. B. **„Michaels BlueNexus“** – in Kopfzeile, Browser-Tab, Handy-App und Nachrichten (später frei änderbar).

Sie läuft auf einem Raspberry Pi (oder jedem Linux-Rechner im Netz), wird im Browser oder als App auf dem
Handy bedient und verbindet alles, was im Haus Strom verbraucht, misst, schaltet oder filmt:

| | |
|---|---|
| ⚡ **Energie** | Victron Cerbo GX, Tibber-Strompreise, PV-Prognose, intelligente Ladeplanung, Überschuss-Automatik, Kosten und Ersparnis |
| 🏠 **Smart Home** | Shelly, Tasmota, WLED, Tuya, Homematic / HomematicIP, Zigbee (deCONZ), Klimaanlagen (Midea), Wake-on-LAN, Rollläden, Türschlösser, Soundmodule |
| 🏷️ **NFC-Tags** | Handy an einen Aufkleber halten – und die Zentrale schaltet, startet eine Regel, schickt ein Foto oder einen Gong. Nur registrierte Handys, auch unterwegs |
| 🧠 **Regeln** | Grafischer Regel-Editor: WENN … DANN … SONST, Zeitpläne, Sonnenstand, Abläufe mit Timern, Telegram- und Pushover-Meldungen |
| 📷 **Kameras** | Reolink und beliebige RTSP-Kameras: Standbild, Live-Bild, Bewegungs- und Klingel-Auslöser |
| 🗣️ **Alexa** | Sprachsteuerung ohne Amazon-Entwicklerkonto – die App gibt sich im Heimnetz als Hue-Bridge aus |
| 📈 **Verläufe** | Eigene Diagramme für alle Messwerte (Ersatz für InfluxDB + Grafana) |
| 🌍 **Fernzugriff** | Sicherer Zugriff von unterwegs per Cloudflare-Tunnel, direkt in den Einstellungen eingerichtet |

Jedes Modul lässt sich **einzeln ein- und ausschalten**. Wer keine PV-Anlage hat, nutzt die App als reine
Smart-Home-Zentrale mit Kameras – wer nur Energie will, blendet den Rest aus.

---

## Inhalt

- [Was die Software kann – der Überblick](#was-die-software-kann--der-überblick)
- [Module](#module)
- [Smart Home: unterstützte Geräte und Systeme](#smart-home-unterstützte-geräte-und-systeme)
- [Regeln und Abläufe](#regeln-und-abläufe)
- [NFC-Tags](#nfc-tags)
- [Kameras](#kameras)
- [Sprachsteuerung mit Alexa](#sprachsteuerung-mit-alexa)
- [Benachrichtigungen](#benachrichtigungen)
- [Verläufe und Auswertungen](#verläufe-und-auswertungen)
- [Das Dashboard](#das-dashboard)
- [Benutzer, Rechte und Sichtbarkeit](#benutzer-rechte-und-sichtbarkeit)
- [Energiemanagement mit Victron und Tibber](#energiemanagement-mit-victron-und-tibber)
  - [Wie es funktioniert](#wie-es-funktioniert)
  - [Die Lade-Strategie im Detail](#die-lade-strategie-im-detail)
  - [Überschuss-Automatik](#überschuss-automatik)
- [Sicherheit](#sicherheit)
- [Fernzugriff von unterwegs](#fernzugriff-von-unterwegs)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Konfigurierbare Parameter](#konfigurierbare-parameter)
- [Datenquellen und Register](#datenquellen-und-register)
- [Architektur](#architektur)
- [Aktualisieren, Sicherung, Datenhaltung](#aktualisieren-sicherung-datenhaltung)
- [Lizenz / Haftung](#lizenz--haftung)

---

## Was die Software kann – der Überblick

**Eine Oberfläche für das ganze Haus.** Ein Dashboard zeigt Energiefluss, Strompreis, Schalter, Sensoren,
Thermostate, Klimaanlagen und Kameras. Alles läuft **lokal im Heimnetz**; Geräte werden direkt angesprochen,
nicht über die Hersteller-Cloud (Ausnahmen sind unten genannt).

**Geräte verbinden.** Shelly, Tasmota, WLED, Tuya/Smart Life, Homematic und HomematicIP (über OpenCCU),
Zigbee (über Phoscon/deCONZ, auch mehrere Gateways), Midea-Klimaanlagen (NetHome Plus), Wake-on-LAN-Rechner
sowie Reolink- und RTSP-Kameras. Die App sucht Geräte im Netz selbst; gefundene Treffer werden erst angesehen
und benannt, dann hinzugefügt.

**Alles miteinander verknüpfen.** Der Regel-Editor verbindet Auslöser (Uhrzeit, Sonnenauf-/untergang, Sensor,
Strompreis, Akkustand, Tastendruck, Türklingel, Kamerabewegung …) mit Aktionen (schalten, warten, Thermostat
setzen, Klimaanlage einstellen, Rollladen fahren, Gong spielen, Tür öffnen, Rechner wecken, Nachricht mit
Kamerabild aufs Handy schicken …).

**Den Strom intelligent einsetzen.** Mit Tibber lädt die Steuerung den Akku in den günstigsten
Viertelstunden, vermeidet Preisspitzen, nutzt die PV-Prognose und schaltet bei Überschuss Verbraucher zu.

**Für die ganze Familie.** Mehrere Benutzer mit fein einstellbaren Rechten, Sichtbarkeit pro Gerät,
PIN-Schutz für heikle Schalter, persönliche Dashboards, Vorschau „so sieht das Konto die App“.

**Ohne Cloud-Zwang, ohne Abo.** Daten bleiben auf dem eigenen Server. Cloud wird nur dort gebraucht, wo es
nicht anders geht: Tibber-Preise, VRM-Prognose, Wetter (Open-Meteo), Telegram/Pushover und – wahlweise –
die Midea-Cloud für Klimaanlagen.

---

## Module

Die App besteht aus Modulen, die du einzeln an- und ausschalten kannst (Erststart-Auswahl oder später unter
*Einstellungen → System → Module*). Ausgeschaltete Module verschwinden aus Menü, Einstellungen, Dashboard,
Rechtevergabe und Regel-Editor – gelöscht wird dabei nichts.

| Modul | Enthält |
|---|---|
| **⚡ Energie** | Victron/Cerbo, Tibber oder fester Tarif, VRM, Ladeplan, Überschuss-Automatik, Energie-Verlauf, Ersparnis |
| **🏠 Smart Home** | Geräte, Sensoren, Thermostate, Türschlösser, Regeln und Abläufe, Wake-on-LAN, Soundmodule, Rollläden, Klimaanlagen |
| **📈 Verläufe** | Messwerte aufzeichnen und als Diagramme zeigen (braucht Energie oder Smart Home) |
| **📷 Kameras** | Reolink und RTSP-Kameras |
| **🗣️ Alexa** | Sprachsteuerung für freigegebene Geräte und eigene Schalter (standardmäßig aus) |

Die Module sind unabhängig voneinander kombinierbar; nur die Überschuss-Automatik braucht Energie **und**
Smart Home. Die App läuft auch **ganz ohne Victron** als reines Smart-Home-System.

---

## Smart Home: unterstützte Geräte und Systeme

| System | Was geht | Wie |
|---|---|---|
| **Shelly** (Gen1–Gen3) | Schalten, Leistungsmessung | Suche im Heimnetz oder IP eintragen, lokal |
| **Tasmota** | Schalten, Leistungsmessung | Suche oder IP eintragen, lokal |
| **WLED** | Ein/Aus, Helligkeit per Regler | Gemeinsame Suche mit Tasmota, lokal |
| **Tuya / Smart Life** (z. B. Gosund) | Schalten | Die Cloud liefert nur einmalig die Geräteschlüssel, geschaltet wird **lokal** |
| **Homematic / HomematicIP** (OpenCCU) | Aktoren, Sensoren, Thermostate, Türschlösser, Rollläden, Soundmodule (Gong), Wandtaster | CCU-Anbindung; optional **Push von der CCU**: Reaktion in unter einer Sekunde, ohne ständiges Abfragen |
| **Zigbee** (Phoscon / deCONZ) | Aktoren, Sensoren, Thermostate | **Mehrere Gateways** (z. B. eins pro Haus) möglich |
| **Klimaanlagen** (Midea, NetHome Plus; auch Comfee, Inventor, Pioneer u. a.) | Ein/Aus, Modus, Solltemperatur, Lüfter, Schwenken, Temperaturen | Lokal über die Gerätebibliothek, alternativ über die NetHome-Plus-Cloud (eigenes Konto) |
| **Wake-on-LAN** | PC, NAS, Server aufwecken | Magic Packet, mit Erreichbarkeitsanzeige |
| **Eigene Schalter und Knöpfe** | Merker, Auslöser, **Nachlauf-Timer** | Software-Schalter ohne Gerät dahinter, zum Verketten von Regeln |
| **Kameras** | Standbild, Live-Bild, Bewegung, Klingel | Reolink und RTSP (siehe unten) |

Weitere Netze und VLANs lassen sich für die Suche zusätzlich eintragen.

**Besonderheiten**

- **Dimmen:** WLED-Lampen per Helligkeits-Regler.
- **Rollläden:** auf Position fahren, anhalten, nach Sonnenstand automatisch abends zu und morgens auf.
- **Türschlösser (HomematicIP):** öffnen, entriegeln, verriegeln – mit PIN und eigener Freigabe, ob Regeln öffnen dürfen.
- **Homematic-Funk-Diagnose:** Duty Cycle der Funkmodule, gesprächigste Geräte, Befehle der App – plus ein Test „Homematic pausieren“, um den Verursacher von Funklast zu finden.
- **Kurzer und langer Tastendruck** an Wandtastern als getrennte Auslöser.
- **NFC-Tags:** Handy an einen Tag halten löst einen Knopf (und damit jede Regel) aus – nur registrierte Handys, einzeln sperrbar, auch unterwegs über den Tunnel.
- **Klingel:** Reolink-Türklingel als Auslöser („Klingel gedrückt“) – zum Beispiel für einen Gong im Haus.
- **Sicherheits-Timer:** Geräte schalten sich nach einer einstellbaren Zeit selbst wieder ab, falls eine Regel hängt.

---

## Regeln und Abläufe

Der Regel-Editor (*Smart Home → Regeln*) arbeitet nach dem Schema **WENN → DANN → SONST** – ähnlich wie Blockly
in ioBroker, aber als übersichtliches Formular, das auch am Handy funktioniert.

**Zwei Arten von Regeln**

- **Zustand halten:** Das Gerät folgt der Bedingung. *Licht an, solange die Tür offen ist.*
- **Ablauf:** Startet einmal, wenn die Bedingung eintritt, und arbeitet Schritte nacheinander ab – mit
  Warten dazwischen. *Warmwasser-Timer, morgens den PC wecken, Thermostate für zwei Stunden anheben.*

**Bedingungen (WENN)**

Uhrzeit von–bis · Uhrzeit (einmal täglich) · Wochentag · **Sonnenaufgang / Sonnenuntergang** (mit Versatz, aus dem
Standort berechnet, ohne Internet) · **Nacht / Tag** (Sonnenstand) · **Strompreis** · **Laufzeit pro Tag zu den
günstigsten Zeiten** · **Akkustand** · **Sonnenprognose für morgen** · Sensorwerte (Fenster, Tür, Bewegung,
Temperatur …) · Zustand oder Leistung eines anderen Geräts · eigener Schalter / Knopf · Wandtaster kurz/lang ·
Kamera-Bewegung · Türklingel. Mehrere Bedingungen lassen sich mit UND / ODER verknüpfen.

**Aktionen (DANN / SONST)**

Gerät schalten oder umschalten · Warten · Thermostat-Solltemperatur setzen · **Klimaanlage einstellen** (Modus,
Temperatur, Lüfter) · Rollladen fahren · Gong / Sound abspielen · Türschloss öffnen · Rechner aufwecken ·
eigenen Schalter setzen oder Knopf drücken (Abläufe verketten) · **Telegram-Nachricht** · **Telegram mit
Kamera-Standbild** · **Telegram mit Video zum Ereignis** (aus der SD-Karten-Aufnahme, filterbar auf Tier/Person/Fahrzeug) · **Pushover-Nachricht**.

**Gut gelöst**

- **Trockenlauf:** Regeln werden nur protokolliert, nichts wird geschaltet – ideal zum Ausprobieren.
- **Logbuch** zeigt, was wann und warum geschaltet wurde.
- **Gruppen:** Regeln lassen sich in frei benennbare Gruppen sortieren (auf- und zuklappbar, per Ziehen sortierbar).
- **Laufende Abläufe überstehen einen Neustart** der App.
- **Restzeit** laufender Timer auf der Dashboard-Kachel; Antippen bricht ab.
- **Sperrzeit** gegen mehrfaches Auslösen (z. B. Lichtschranke).
- **Löschschutz:** Was von einer aktiven Regel benutzt wird, lässt sich nicht versehentlich löschen.
- **Der Editor bietet nur an, was es bei dir gibt:** Systeme, die nicht eingerichtet oder abgewählt sind (z. B.
  keine Klimaanlage, kein Energie-Modul, keine Kamera), erscheinen nicht als Bedingung oder Schritt.
- **Reaktionszeit** unter einer Sekunde mit Homematic-Push.

---

## NFC-Tags

Ein günstiger **NFC-Aufkleber oder Schlüsselanhänger** wird zum physischen Knopf für dein Smart Home: Handy kurz
daranhalten, und BlueNexus löst aus, was du in den Regeln festgelegt hast – Licht an, Garagentor, Gong im Haus,
Foto der Kamera aufs Handy, Szene „Gute Nacht“. Das funktioniert zu Hause und **unterwegs** über den Fernzugriff.

- **Nur registrierte Handys.** Ein Tag trägt nur eine Internet-Adresse; ausgelöst wird erst, wenn das Handy der
  Zentrale bekannt ist. Ein kopierter oder fotografierter Tag nützt niemandem.
- **Registrieren** in Sekunden: direkt am Handy oder per Einmal-Link (15 Minuten gültig) für ein anderes Handy.
  Verlorenes Handy? Mit einem Klick in der Liste löschen – sofort gesperrt.
- **Pro NFC-Tag einstellbar**, welche Handys ihn nutzen dürfen (nicht zeitlich begrenzt – ein registriertes Handy darf, bis du es löschst). Jeder neue NFC-Tag legt automatisch einen eigenen Knopf (🏷️) an,
  den du in Regeln als „WENN Knopf gedrückt“ verwendest.
- **App installierbar:** Die Einrichtungsseite `/nfc` führt Handy-Nutzer ohne Anmeldung durch die Installation – danach öffnet
  und schließt sich die App beim Scannen von selbst.
- **Rechte:** eigener Bereich „Smart Home: NFC-Tags“. Ein Lese-Konto (z. B. Demo) sieht Tags, Handys und Freigaben, aber
  **keine Adressen**; verwalten darf nur, wer Schreibrecht hat.
- Registrierungen gehören zur **Sicherung** und werden mit wiederhergestellt. Abgelehnte Versuche stehen im Logbuch.
- Erprobt mit **Android**; geeignet sind NFC-Tags nach NTAG/MIFARE-Standard (13,56 MHz). Einrichtung unter *Smart Home → NFC-Tags*,
  ausführlich im [Handbuch](MANUAL.md#13c-nfc-tags-handy-scannen-knopf-auslösen).

---

## Kameras

- **Reolink** (lokale Schnittstelle, Standbild in voller Auflösung) und **jede Kamera mit RTSP**
  (z. B. Wansview und viele weitere).
- **Standbild** automatisch aktualisiert (1 / 5 / 10 / 30 Sekunden), **Live-Bild** per Klick (Klar oder Flüssig),
  **Vollbild** auch auf dem iPhone. Ein Live-Strom endet nach 15 Minuten von selbst, damit nie einer vergessen läuft.
- Die Bilder laufen **durch die App** – also nur mit Anmeldung, Recht „Kameras“ und Freigabe der jeweiligen
  Kamera. Zugangsdaten und Kamera-IP bleiben auf dem Server.
- **Bewegung und Klingel als Auslöser** in Regeln, z. B. „Bewegung im Hof → Foto aufs Handy“.
- Funktioniert auch über den Fernzugriff.

---

## Sprachsteuerung mit Alexa

Die App gibt sich im Heimnetz als **Philips-Hue-Bridge** aus. Echo-Geräte finden sie **ohne Cloud, ohne
Skill und ohne Amazon-Entwicklerkonto**. Jedes freigegebene Gerät oder jeder eigene Schalter erscheint in der
Alexa-App als Lampe oder Steckdose: *„Alexa, schalte den Warmwasser-Timer ein.“*

Sicherheit zuerst: Geräte mit PIN und Türschlösser sind für Alexa **nie** freigebbar – Sprache umgeht die PIN nie.

---

## Benachrichtigungen

- **Telegram:** Mehrere Empfänger an einem Bot, pro Meldung wählbar, wer sie bekommt. Mit Kamera-Standbild in
  Regeln – dasselbe Foto geht an alle gewählten Empfänger. Dazu Tagesbilanz, Monatsübersicht und Störungsmeldungen.
- **Pushover:** Zweiter Meldeweg mit eigenem Regelbaustein, Auswahl einzelner Geräte als Ziel, Prioritäten
  und Bildanhang.
- **Zugangsdaten sind jederzeit löschbar:** Für jedes Passwort, jeden Token und jeden Schlüssel gibt es einen
  Löschen-Knopf – nichts bleibt ungewollt gespeichert.

---

## Verläufe und Auswertungen

- **Verläufe (Diagramme):** Beliebige Messwerte fein aufzeichnen (Netz, Verbrauch, Solar, Batterie, Strompreis,
  Sensorwerte, Leistung von Shelly/Tasmota, Klimaanlagen-Temperaturen …) und als **Linie, Fläche, Balken oder
  Stufen** darstellen. Zoom, Min/Max-Band, freie Farben, bis zu 12 Reihen pro Diagramm, **Export als PNG**
  (dunkel oder weiß), Diagramme wahlweise auf dem Dashboard. Aufbewahrung: Rohwerte 7 Tage, Zusammenfassung 400 Tage.
- **Energie-Charts:** Verbrauch/Solar mit SOC-Band und Energieflüsse (7 Pfade wie im VRM), 35 Tage Historie.
- **Wochenrückblick und Monatsüberblick:** Solar, Verbrauch, Netz, Autarkie, Kosten.
- **Ersparnis:** was PV, Akku und Steuerung gegenüber „alles aus dem Netz“ sparen.
- **Solarlogbuch:** PV-Prognose gegen realen Ertrag, mit Korrekturfaktor.
- **Betriebsbericht:** Läuft alles? Sind Prognose, Preise und Daten vollständig?
- **Batterie-Watchdog:** erkennt hängende Ladevorgänge, zeigt Vollzyklen und Lebensdauer-Hochrechnung.
- **Logbücher** für Regeln und Automatik.

---

## Das Dashboard

Ein Dashboard für alles – installierbar als App auf dem Handy (PWA). Live-Kacheln aktualisieren sich alle
2 Sekunden.

Energie-Live-Werte · Strompreis-Kurve mit Ladefenstern · Energie-Charts · Wochen-/Monatsrückblick · Geräte ·
eigene Schalter und Knöpfe · Sensoren · Thermostate und Klimaanlagen · Wake-on-LAN · Verlaufs-Diagramme ·
Ersparnis · Wetter.

- Welche Kacheln erscheinen, entscheidet der Admin global – jeder Benutzer stellt unter **„Meine Ansicht“**
  seine eigene Auswahl und Reihenfolge zusammen.
- **Jede Liste ist per langem Druck und Ziehen sortierbar** (Geräte, Sensoren, Schalter, Kameras, Regeln …).
- Schalten per Antippen, bei Bedarf mit **PIN**.
- Dunkles, mobil optimiertes Design.

---

## Benutzer, Rechte und Sichtbarkeit

- **Mehrere Benutzer** mit Rechten pro Bereich: *Kein / Lesen / Schreiben* – getrennt für Dashboard, Verläufe,
  Kameras, Aktoren, Sensoren, Thermostate, Sicherheit, Regeln, Einstellungen und mehr.
- **Vorlagen** (Admin, Benutzer, Smart-Home-Nutzer, Demo) und Ablaufdatum für Gastzugänge.
- **Sichtbarkeit pro Gerät:** Der Türöffner für alle, der Warmwasser-Timer nur für bestimmte Konten.
  Neue Geräte sind zunächst nur für Admins sichtbar.
- **Bedienen ja, verwalten nein:** Nutzer mit Schreibrecht können Geräte schalten, aber nur Admins
  anlegen, umbenennen oder löschen.
- **Vorschau als Benutzer:** Der Admin sieht die App genau so, wie ein bestimmtes Konto sie sieht.
- **PIN-Schutz** für einzelne Geräte oder Schalter.

---

## Energiemanagement mit Victron und Tibber

Das Herzstück für alle mit PV-Anlage und Speicher: eine intelligente, webbasierte **Ladesteuerung für
Victron-ESS-Anlagen** (MultiPlus-II / Cerbo GX) auf Basis dynamischer **Tibber**-Strompreise und
**PV-Prognose**. Sie redet direkt per **Modbus TCP** mit dem Cerbo GX.

Ziel: **PV maximal nutzen, Netzstrom nur in den günstigsten Viertelstunden ziehen** und die Morgen- und
Abend-Preisspitzen niemals aus dem Netz decken – vollautomatisch, aber jederzeit manuell übersteuerbar.

### Wie es funktioniert

Ein Hintergrund-Regler läuft in einer Schleife und macht bei jedem Takt (Standard alle 5 Min, auf das
Viertelstunden-Raster ausgerichtet) Folgendes:

1. **Liest den Ist-Zustand** vom Cerbo per Modbus TCP: Batterie-SOC (aus dem BMS), aktuellen ESS-Mode und die
   kompletten System-Leistungen (Netz, Verbrauch, PV-AC, PV-DC, Batterie).
2. **Holt die Strompreise** von der Tibber-API – viertelstundengenau für heute und (sobald verfügbar) morgen.
3. **Holt die PV-Prognose** aus dem Victron-VRM-Portal (ohne VRM: Durchschnitt der echten Erträge der letzten Tage).
4. **Entscheidet** anhand der Strategie unten, ob jetzt aus dem Netz geladen werden soll.
5. **Schreibt den ESS-Mode** zurück auf den Cerbo (`9` = Netzladen erlaubt, `10` = nicht laden) – sofern kein
   Dry-Run aktiv ist und sich der Wert geändert hat.

Ein **zweiter, feiner Takt** (Standard alle 10 s) tastet unabhängig davon die Momentanleistungen ab und
integriert sie zu kWh – deutlich genauer als der Regeltakt und sehr nah an den VRM-Werten. Daraus entstehen
Verlaufs-Charts und das Ladeprotokoll mit Menge und Kosten.

Weitere Energie-Funktionen:

- **Intelligente Planung** (Standard bei dynamischem Tarif): rechnet bei jedem Durchlauf frisch über den ganzen
  bekannten Zeitraum, wann Netzladen am günstigsten ist.
- **Fester Tarif** wird ebenfalls unterstützt (dann ohne Preisplanung, PV-Vorrang und Ladelimit wirken weiter).
- **Manuelle Ladetermine** per Klick/Ziehen in der Preiskurve (z. B. für das E-Auto) und **Sofort-Laden**.
- **Periodische Vollladung** zum Zellbalancing des BMS.
- **Minimaler Akkustand und Netz-Sollwert** werden direkt am Cerbo gesetzt.
- **Kosten und Tarifwechsel:** Vertragskosten, MwSt, Tarifwechsel mit Stichtag, rückwirkend korrekte Tageskosten.
- **Verlauf nachholen** aus dem VRM nach Ausfällen.

### Die Lade-Strategie im Detail

Die Logik ist eine 1:1-Portierung des über viele Iterationen erprobten ioBroker-Skripts (V39.4) nach Python.
Sie arbeitet in drei Schritten und einem klaren Prioritätsbaum.

#### Schritt 1 – Bedarf ermitteln (Prioritätsbaum)

Es wird die **erste zutreffende** Strategie gewählt:

1. **Peak-Schutz** (harte Bedingung, höchste Priorität)
   Rechnet aus, ob der Akku den nächsten Preis-Peak (morgens 7–9, abends 19–21 Uhr) mit einem Mindest-SOC von
   **40 %** übersteht. Die bis dahin erwartete PV-Erzeugung wird abgezogen, der Verbrauch bis zum Peak addiert.
   Reicht es nicht, wird sofort nachgeladen – bis zu einem Preislimit von **37 ct/kWh**.

2. **Nacht-Puffer** (22:00–06:00, mit Hysterese)
   Fällt der SOC nachts unter die Sicherheitsschwelle (30 %) *und* ist die Gesamtbilanz negativ, wird bis knapp
   über die Schwelle nachgeladen. Eine Hysterese (±1,5 %) verhindert Schaltflattern an der Grenze.

3. **Morgen-Brücke** (00:00–09:00)
   Sorgt dafür, dass am Morgen ein Ziel-SOC von **35 %** vorhanden ist, um bis zur Mittags-PV zu überbrücken.

4. **Tiefpreis-Sicherung** (jederzeit)
   Ist die **Gesamtbilanz bis morgen Mittag** negativ (aktueller Speicher + erwartete Rest-PV − Verbrauch), wird
   die Differenz in den günstigsten Viertelstunden nachgeladen.

#### Schritt 2 – Planung

Der ermittelte Bedarf (kWh) wird auf die nötige Anzahl 15-Min-Slots umgerechnet (anhand der Ladeleistung). Aus
den erlaubten Slots im jeweiligen Zeitfenster werden die **preisgünstigsten** ausgewählt. Der Ladebedarf wird
zusätzlich durch die freie Restkapazität begrenzt (abzüglich einer PV-Reserve für die Mittagssonne).

#### Schritt 3 – Ausführung

- Geladen wird nur, wenn die **aktuelle Viertelstunde im Plan** liegt.
- **Preislimit** für die Standard-Strategien: nur in der günstigen Hälfte des Fensters laden (Nacht-Puffer: bis
  Ø-Preis ×1,1; sonst: unteres Viertel der Preisspanne).
- **Commitment:** Eine einmal begonnene Viertelstunde wird zu Ende geladen (kein Sekunden-Flattern beim Schalten).
- **Notbremse (mit Hysterese):** Fällt der SOC unter 30 % *und* liegt der Preis ≤ 37 ct, wird unabhängig von der
  Strategie geladen, bis 40 % wieder erreicht sind.

#### PV-Berücksichtigung

Die Prognose wird mit einem **Korrekturfaktor** (Erfahrungswert real vs. Prognose) skaliert und je nach
Tageszeit anteilig auf die verbleibende Erzeugung umgerechnet. Viel Sonne ⇒ weniger geplante Netzladung. Der
passende Faktor lässt sich über das **Solarlogbuch** datenbasiert ermitteln – oder die App passt ihn
automatisch an.

### Überschuss-Automatik

Ist der Akku voll und wird eingespeist, schaltet die App die Geräte einer Liste **nacheinander zu** (oberstes
zuerst) – Heizstab, Wärmepumpe, Klimaanlage, Waschmaschine. Bei Netzbezug oder Akku-Entladung werden sie in
umgekehrter Reihenfolge wieder abgeschaltet. Mit Trockenlauf, Pause nach Handschaltung und Sicherheits-Timer.

---

## Sicherheit

Die App ist dafür gebaut, auch erreichbar zu sein, wenn man will – deshalb ist Sicherheit eingebaut:

- **Anmeldung** mit gesalzenen Passwort-Hashes, Zugriffssperre nach Fehlversuchen, gleiche Rechenzeit bei
  unbekannten Konten (kein Erraten gültiger Benutzernamen).
- **Rechte nach dem Prinzip „standardmäßig verboten“:** Jede Funktion ist einem Bereich zugeordnet; was keinem
  Recht zugeordnet ist, darf niemand.
- **Schutz vor fremden Webseiten (CSRF)**, sichere Weiterleitungen, Schutz-Header, Größenlimit für Anfragen.
- **Cookies werden über HTTPS automatisch als „Secure“ markiert**, sobald die App über einen Tunnel oder
  Proxy erreicht wird; HSTS nur über HTTPS.
- **Zugangsdaten:** Dateien mit Passwörtern und Tokens sind nur für den Dienst-Benutzer lesbar, werden nie
  wieder angezeigt und sind jederzeit löschbar.
- **Dienst-Benutzer ohne Anmeldung** bei der Installation per Skript; die App läuft nicht als root.
- **Dry-Run-Modus** (Standard beim ersten Start): Die Ladesteuerung rechnet und protokolliert alles, schreibt
  aber **nichts** auf den Cerbo.
- **Harte Ladesperre:** Es wird **nie über das Ladelimit (Standard 90 %)** aus dem Netz geladen – auch nicht bei
  manuellem Override oder aktivem Ladetermin.
- **Preislimits** verhindern Netzladung zu teuren Zeiten außerhalb echter Peak-Not.
- **Fehlerabfang:** Fällt eine Datenquelle aus (Tibber, PV, Cerbo), läuft der Regler weiter und rechnet
  defensiv. Fehlt ein Messwert, schaltet eine Regel nicht „ins Blaue“.
- **PIN-Schutz**, Sichtbarkeit pro Gerät und die Regel, dass Sprachsteuerung nie an der PIN vorbeikommt.
- **Hinweis:** Wer die App ins Internet stellt, sollte zusätzlich **Cloudflare Access** (Anmeldung vor der App)
  einschalten – die Einstellungen weisen darauf hin.

---

## Fernzugriff von unterwegs

Unter *Einstellungen → System → Fernzugriff* richtest du einen **Cloudflare-Tunnel** direkt in der App ein:
Token eintragen, fertig. Keine Portfreigabe im Router, keine feste IP, kein eigener Server im Internet nötig. Die
App installiert und überwacht den Tunnel-Dienst selbst (inklusive Neustart bei Verbindungsabbruch). Läuft auch
auf dem Raspberry Pi.

---

## Installation

### Raspberry Pi / Debian / Ubuntu – ein Befehl

Auf dem Gerät (Raspberry Pi OS, Debian oder Ubuntu, am besten Pi 3/4/5) per SSH oder im Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/Micha-3582/BlueNexus/main/app/deploy/install.sh | bash
```

Das Skript erledigt alles selbst: nötige Pakete (git, Python, ffmpeg für Kameras) installieren, den Code holen, die
Python-Umgebung einrichten und die App als **Dienst** starten (startet nach jedem Neustart von selbst). Du musst
nichts von Hand anlegen. Dauer auf dem Pi: einige Minuten. Danach im Browser
`http://<IP-des-Geräts>:5005` öffnen – dort legst du dein Konto an, wählst deine Module und gehst den
Einrichtungsassistenten durch. Dem Gerät im Router am besten eine feste IP geben.

- **Privates Repo / Fork:** `curl -fsSL <raw-URL>/install.sh | GIT_TOKEN=<Token mit Leserecht> BLUENEXUS_REPO=<Git-Adresse> bash`
- **Aktualisieren:** Knopf in der App (*Einstellungen → System*) oder `sudo /opt/bluenexus/app/deploy/update.sh`.
  Der Befehl oben kann auch einfach wiederholt werden.
- **Entfernen:** `sudo /opt/bluenexus/app/deploy/uninstall.sh` (löscht auch alle Daten!).
- Weitere Wahlmöglichkeiten (Port, Ordner, ohne ffmpeg …): siehe Kopf von [`app/deploy/install.sh`](app/deploy/install.sh).

**Voraussetzung am Cerbo (nur Energie-Modul):** Einstellungen → Dienste → **Modbus TCP aktivieren**.

**Manuell / eigene Umgebung:**

```bash
pip install -r app/requirements.txt
python app/webapp.py     # http://<host>:5005
```

Läuft mit Python 3.9+. Alternativ per **pm2** oder **systemd** als Dienst.

---

## Einrichtung

1. **Konto anlegen** – Vorname angeben (daraus entsteht der Name der App, z. B. „Michaels BlueNexus“); das erste Konto wird zum Administrator.
2. **Module wählen** – Energie, Smart Home, Kameras, Alexa. Ohne PV-Anlage „Energie“ einfach abwählen.
3. **Einrichtungsassistent** (nur mit Energie): Cerbo-IP, Tibber-Token oder Festpreis, VRM-Zugang. Ein
   Verbindungstest prüft Cerbo und Tibber, bevor es losgeht.
4. **Geräte suchen** (*Smart Home → Geräte suchen*): Systeme ankreuzen, suchen, Treffer benennen, hinzufügen.
5. **Regeln bauen** – erst im **Trockenlauf** beobachten, dann scharf schalten.

Die Ladesteuerung startet im **Dry-Run**. Erst wenn die Entscheidungen plausibel sind, in den Einstellungen
scharf schalten.

---

## Konfigurierbare Parameter

Alle Strategie-Werte lassen sich pro Anlage im Admin-Bereich anpassen. Defaults:

| Parameter | Standard | Bedeutung |
|---|---|---|
| `battery_usable_kwh` | 24,0 | nutzbare Akkukapazität |
| `daily_usage_kwh` | 30,0 | angenommener Tagesverbrauch |
| `charge_power_w` | 3500 | Netz-Ladeleistung |
| `pv_reserve_kwh` | 5,0 | Kapazitätspuffer für Mittags-PV |
| `pv_korrektur_faktor` | 0,68 | Dämpfung Prognose → real |
| `pv_tom_morning_factor` | 0,15 | Anteil morgiger PV vor dem Morgen-Peak (Winter 0,05 / Sommer 0,25) |
| `min_peak_soc` | 40 % | Mindest-SOC vor jedem Peak |
| `peak_avoid_price` | 37 ct | Preislimit für Peak-Schutz / Notbremse |
| `night_safety_soc` | 30 % | Sicherheits-SOC nachts |
| `target_safe_soc` | 35 % | Ziel-SOC der Morgen-Brücke |
| `max_charge_soc` | 90 % | harte Obergrenze für Netzladung |
| `hysterese_soc` | 1,5 % | Schalthysterese |
| `poll_seconds` | 300 | Regeltakt (aufs 15-Min-Raster ausgerichtet) |
| `energy_sample_seconds` | 10 | Takt des Energie-Samplers |

Peak-Zeitfenster (morgens 7–9, abends 19–21 Uhr) sind ebenfalls einstellbar.

---

## Datenquellen und Register

| Quelle | Was | Wie |
|---|---|---|
| Cerbo GX | SOC, ESS-Mode, System-Leistungen, Netz-Energiezähler | Modbus TCP (Unit 100 System, Unit 225 BMS) |
| Tibber | Strompreise heute/morgen (viertelstundengenau) | Tibber-API (Token) |
| Victron VRM | PV-Prognose, Verlauf nachholen, Tagesertrag | HTTP (API-Token, 30-Min-Cache) |
| Open-Meteo | Wetter, Standort | HTTP |
| Smart-Home-Geräte | Schalten, Messwerte | lokal im Heimnetz (Shelly, Tasmota, WLED, Tuya, Zigbee, Homematic, Midea) |

**Genutzte Cerbo-Register** (verifiziert gegen die Victron-App):
SOC BMS `225/266` (×10), ESS-Mode `100/2900` (Holding, 9/10), System-Block ab `100/811`
(PV-WR, Last, Netz), Batterie `100/840–846`, PV-Ladegerät `100/850–851`,
Netz-Energiezähler `100/2622ff` (uint32, Wh).

> **Hinweis:** Die kumulierten Netz-Zählerregister (2622ff) sind bei manchen Anlagen unzuverlässig. Die
> Tages-Netzbilanz wird deshalb standardmäßig aus der **integrierten Netzleistung** berechnet und ist manuell
> korrigierbar (Abgleich mit der Victron-App).

---

## Architektur

```
webapp.py        Flask-Web-App (waitress) + Hintergrund-Threads (Regler, Energie-Sampler, Regeln, Aufzeichnung)
logic.py         reine, testbare Entscheidungslogik (decide()) – keine Hardware/IO
victron.py       Cerbo-Anbindung über Modbus TCP (Lesen/Schreiben)
datasources.py   Tibber-Preise;  vrm.py: PV-Prognose, Nachholen
rules.py         Regel-Editor und Regelmaschine;  flows.py: Abläufe mit Warten;  virtual.py: eigene Schalter, Knöpfe, Timer
surplus.py       Überschuss-Automatik
shelly.py tasmota.py wled.py tuya.py homematic.py zigbee.py midea.py wol.py   Geräteanbindungen
camera.py        Reolink / RTSP, Standbild, Live (ffmpeg), Bewegung, Klingel
alexa.py         Hue-Bridge-Emulation für Sprachsteuerung
notify.py pushover.py   Telegram und Pushover
tunnel.py        Cloudflare-Tunnel (cloudflared) mit Überwachung
auth.py pins.py visibility.py   Benutzer, Rechte, PIN, Sichtbarkeit
verlauf.py       Aufzeichnung und Diagramme (SQLite)
store.py         Persistenz: Config, State, Register, Ladeprotokoll, Historie
updater.py       In-App-Update über GitHub
templates/       Oberfläche (Dashboard, Smart Home, Regeln, Kameras, Verläufe, Einstellungen, Assistent)
deploy/          install.sh / update.sh / uninstall.sh
```

Die Trennung von **Logik** (rein, deterministisch, testbar) und **I/O** (Modbus, HTTP, Speicherung) macht die
Steuerung ohne Hardware testbar – die V39.4-Portierung ist durch Tests abgesichert. Daten liegen als JSON-Dateien
und einer SQLite-Datenbank im Ordner `app/` und sind **nicht in Git**.

---

## Aktualisieren, Sicherung, Datenhaltung

- **Sicherung und Umzug ohne Terminal:** *Einstellungen → System → Sicherung & Wiederherstellung* speichert **alle Einstellungen in einer verschlüsselten Datei** (Konten, Zugangsdaten, Geräte, Regeln, Kameras, Dashboard – wahlweise mit Verläufen und Historie). Bei einer neuen Installation spielst du sie auf der Startseite wieder ein („Schon eine Sicherung?“) – danach ist die neue App genau wie die alte. Kein SSH nötig.

- **Einfach:** in der App unter *Einstellungen → System → App-Version & Update* auf „Nach Updates suchen“ →
  „Jetzt aktualisieren“. Neue Abhängigkeiten werden dabei automatisch installiert.
- **Am Terminal:** `sudo /opt/bluenexus/app/deploy/update.sh` (oder `git pull` und Dienst neu starten).
- Persönliche Daten (Konfiguration, Geräte, Regeln, Termine, Zählerstände, Historie) bleiben bei Updates erhalten.
- Vor riskanten Vorgängen legt die App selbst Sicherungen in `app/backups/` an. Komplettsicherung: Ordner `app/` kopieren.

---

## Lizenz / Haftung

BlueNexus ist **freie Software** unter der **GNU General Public License, Version 3** (siehe [LICENSE](LICENSE)): Du darfst sie nutzen, ändern und weitergeben; Weitergaben und Weiterentwicklungen müssen wieder unter derselben Lizenz offen stehen. Es ist ein **privates, nicht-kommerzielles Hobbyprojekt** und steht in keiner Verbindung zu anderen Firmen oder Produkten gleichen oder ähnlichen Namens.

Nutzung auf **eigene Verantwortung**. Die Software steuert die Netzladung einer Batterieanlage und schaltet
Verbraucher im Haus – vor dem Scharfschalten (Dry-Run bzw. Trockenlauf aus) unbedingt im Parallelbetrieb
prüfen. Türschlösser, Heizgeräte und andere sicherheitsrelevante Geräte nur mit bedachten Regeln und PIN
einbinden. Keine Gewähr für Preis-, Prognose- oder Messdaten Dritter (Tibber, Victron VRM, Open-Meteo,
Victron-Register).

Alle genannten Produkt- und Markennamen (Victron Energy, Tibber, Shelly, Tasmota, Homematic, Philips Hue,
Amazon Alexa, Reolink, Midea, Telegram, Pushover, Cloudflare u. a.) gehören ihren jeweiligen Inhabern. Die
Software steht in keiner Verbindung zu diesen Unternehmen und nennt die Namen nur, um die Kompatibilität zu
beschreiben.
