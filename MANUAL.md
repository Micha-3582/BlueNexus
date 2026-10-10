# Handbuch – BlueNexus

Dieses Handbuch erklärt die komplette Software: was sie kann, wo man was einstellt und wie man Geräte, Regeln und Abläufe baut.
Die technische Beschreibung der Lade-Strategie, Installation und Architektur steht in der [README](README.md).

> **Hinweis zum Stand:** Das Handbuch beschreibt den Funktionsumfang der aktuellen Version. Die Oberfläche ist deutsch und für das Handy optimiert.
> Fast jedes Eingabefeld hat ein kleines **?** – darauf tippen zeigt eine kurze Erklärung.

## Inhalt

1. [Überblick](#1-überblick)
2. [Anmelden, Benutzer und Rechte](#2-anmelden-benutzer-und-rechte)
3. [Das Dashboard](#3-das-dashboard)
   - [Kameras (Reolink)](#3a-kameras-reolink-und-andere-mit-rtsp)
4. [Einstellungen (Energiesteuerung)](#4-einstellungen)
5. [Smart Home: Geräte einrichten](#5-smart-home-geräte-einrichten)
6. [Eigene Schalter & Knöpfe (Software)](#6-eigene-schalter--knöpfe-software)
7. [Sensoren, Thermostate und Türschlösser](#7-sensoren-thermostate-und-türschlösser)
8. [PIN-Schutz](#8-pin-schutz)
9. [Automatik (Überschuss)](#9-automatik-überschuss)
10. [Regeln und Abläufe (Regel-Editor)](#10-regeln-und-abläufe-regel-editor)
11. [Wake-on-LAN](#11-wake-on-lan)
11a. [Alexa (Sprachsteuerung)](#11a-alexa-sprachsteuerung)
11b. [Klimaanlage (Midea / NetHome Plus)](#11b-klimaanlage-midea--nethome-plus)
12. [Logbuch, Betriebsbericht, Solarlogbuch, Watchdog](#12-logbuch-betriebsbericht-solarlogbuch-watchdog)
13. [Benachrichtigungen (Telegram)](#13-benachrichtigungen-telegram)
13b. [Fernzugriff von unterwegs (Cloudflare Tunnel)](#13b-fernzugriff-von-unterwegs-cloudflare-tunnel)
13c. [NFC-Tags (Handy scannen, Knopf auslösen)](#13c-nfc-tags-handy-scannen-knopf-auslösen)
13d. [Geräte teilen (zwischen BlueNexus-Anlagen)](#13d-geräte-teilen-zwischen-bluenexus-anlagen)
14. [Kosten, Tarife und Tarifwechsel](#14-kosten-tarife-und-tarifwechsel)
15. [Update, Sicherung, Datenhaltung](#15-update-sicherung-datenhaltung)
16. [Beispiele](#16-beispiele)
17. [Fehlersuche (FAQ)](#17-fehlersuche-faq)

---

## 1. Überblick

Die Software besteht aus drei Teilen, die zusammenarbeiten:

| Teil | Aufgabe |
|---|---|
| **Ladesteuerung** | Liest Akku, Netz, PV und Verbrauch vom Victron Cerbo GX (Modbus TCP), holt Strompreise und PV-Prognose und entscheidet, wann aus dem Netz geladen wird. |
| **Smart Home** | Schaltet Steckdosen, Lichter usw. (Shelly, Tasmota, Tuya, Homematic, Zigbee), liest Sensoren, setzt Thermostate, steuert Türschlösser und weckt Rechner. |
| **Regeln & Automatik** | Regeln verknüpfen alles: „WENN … DANN … SONST …“, Zeitpläne, Abläufe mit Warten und Telegram-Nachricht. Die Überschuss-Automatik (PV-Überschuss schaltet Geräte zu) liegt bei den Einstellungen. |

**Das Menü oben** hat bis zu fünf Punkte. Welche davon du siehst, hängt von deinen Rechten ab:

| Menü | Inhalt |
|---|---|
| **Dashboard** | Ein Dashboard für alles: Energie, Preise, Geräte, Schalter und Sensoren. |
| **Verläufe** | Diagramme aufgezeichneter Messwerte (siehe [Kapitel 3b](#3b-verläufe-diagramme-der-messwerte)); nur mit dem Recht „Verläufe“. |
| **Kameras** | Standbilder und Live-Ansicht der Reolink-Kameras (nur sichtbar, wenn das Konto das Recht „Kameras“ hat). |
| **Smart Home** | Alles rund ums Haus. Unter-Reiter: **Aktoren · Sensoren · Thermostate · Sicherheit · Regeln · Geräte suchen · NFC-Tags · Wake-on-LAN · Sonstiges**. Es öffnet immer bei „Aktoren“. |
| **Einstellungen** | Die Energiesteuerung und die App selbst: Anlage, Tarif & Laden, VRM, **Automatik** (Überschuss-Schaltung), Wetter, Meldungen, Dashboard, System, **Konto & Benutzer**. |

So bleiben Energiesteuerung (Einstellungen) und Smart Home (eigener Bereich) getrennt, und trotzdem siehst du alles zusammen auf **einem** Dashboard.

**Module – nur nutzen, was du brauchst**

Die App besteht aus Modulen, die du einzeln an- und ausschalten kannst:

| Modul | Enthält |
|---|---|
| **⚡ Energie** | Victron/Cerbo, Tibber oder fester Tarif, VRM, Ladeplan, Überschuss-Automatik, Energie-Verlauf, Ersparnis und die zugehörigen Dashboard-Kacheln. |
| **🏠 Smart Home** | Geräte, Sensoren, Thermostate, Türschlösser, Regeln und Abläufe, Wake-on-LAN, Soundmodule, Rollläden. |
| **📈 Verläufe** | Menüpunkt Verläufe: Messwerte fein aufzeichnen und als Diagramme zeigen, Dashboard-Kachel „Verlauf“. Braucht **Energie oder Smart Home** (nur mit Kameras gibt es nichts aufzuzeichnen – das Modul ist dann automatisch aus). Beim Ausschalten pausiert die Aufzeichnung, gespeicherte Werte bleiben. |
| **📷 Kameras** | Reolink und RTSP-Kameras. |
| **🗣️ Alexa** | Sprachsteuerung für freigegebene Geräte und eigene Schalter (Kapitel 11a). Standardmäßig **aus**. |

- **Erster Start:** Nach dem Anlegen des ersten Zugangs fragt die App, welche Module du nutzt. Ohne PV-Anlage einfach „Energie“ abwählen – dann entfällt auch die Einrichtung von Cerbo und Tarif. Die App läuft dann als reines Smart-Home- und Kamera-System.
- **Später ändern:** *Einstellungen → System → Module*. Ausgeschaltete Module verschwinden aus Menü, Einstellungen, Dashboard und der Rechtevergabe. Gespeicherte Rechte bleiben erhalten und gelten wieder, sobald das Modul wieder an ist.
- **Daten bleiben erhalten:** Beim Ausschalten wird nichts gelöscht – weder Verlauf, Preise und Kosten noch Geräte, Regeln oder Kameras. Ist „Energie“ aus, **pausiert** die Ladesteuerung und es werden keine neuen Energiewerte aufgezeichnet; im Verlauf fehlt dann die Zeit dazwischen.
- **Begrüßung ohne Energie:** Wer das Modul Energie nicht gewählt hat, bekommt keinen Einrichtungsassistenten. Stattdessen erscheint beim ersten Öffnen des Dashboards (nur für den Administrator, nur einmal) eine kurze Begrüßung mit Hinweisen zu den gewählten Modulen und dazu, wo man Energie nachrüsten kann.
- **Regeln:** Was ein ausgeschaltetes Modul braucht, bietet der Regel-Editor nicht mehr an – ohne **Energie**: Strompreis, Laufzeit pro Tag, Akkustand, Sonne morgen; ohne **Kameras**: „Kamera-Standbild senden“. Schon vorhandene Regeln bleiben sichtbar. Eine Bedingung ohne Energiewerte gilt als „keine Daten“ (nie erfüllt), ein Standbild-Schritt ohne Kamera-Modul meldet im Logbuch „Modul Kameras ist ausgeschaltet“.
- **Abhängigkeiten zwischen den Modulen:** Die Module sind unabhängig und lassen sich beliebig kombinieren (mindestens eines aus Energie, Smart Home, Kameras bleibt an). Wo ein Teil zwei Module braucht, steht es hier:
  - **Überschuss-Automatik** (*Einstellungen → Automatik*): braucht **Energie und Smart Home** (sie schaltet Geräte nach dem PV-Überschuss). Ist eines der beiden aus, ist der Bereich ausgeblendet und die Automatik pausiert.
  - **Alexa:** braucht **Smart Home** (sie schaltet Geräte und eigene Schalter). Ohne Smart Home ist die Bridge aus.
  - **Regeln mit Kamera-Standbild:** brauchen **Smart Home und Kameras**.
  - **Regeln mit Strompreis, Akkustand oder Prognose:** brauchen **Energie**.
  - **Unabhängig von allen Modulen:** Wetter, Sonnenaufgang/-untergang (Standort aus den Wetter-Einstellungen), Telegram, Konto & Benutzer, System.
- **Bestehende Installationen** haben automatisch alle Module an – es ändert sich nichts, bis du selbst etwas abschaltest.

**Grundprinzipien**

- **Alles läuft lokal** im Heimnetz. Cloud wird nur für Tibber-Preise, die VRM-Prognose, Wetter (Open-Meteo) und Telegram gebraucht.
- **Dry-Run / Trockenlauf:** Die Ladesteuerung und die Regeln haben je einen Trockenlauf-Schalter. Dabei wird alles berechnet und protokolliert, aber nichts wirklich geschaltet. Ideal zum Ausprobieren.
- **Sicherheitsgrenzen:** Es wird nie über das Ladelimit aus dem Netz geladen (Standard 90 %), egal ob Automatik, Ladetermin oder Sofort-Override.
- **Die App ist installierbar** (PWA): Im Handy-Browser „Zum Startbildschirm hinzufügen“.

---

## 2. Anmelden, Benutzer und Rechte

Beim ersten Start legt man einen Zugang an (`/create-account`) bzw. meldet sich mit dem Admin-Konto an. Danach werden weitere Benutzer unter **Einstellungen → Konto & Benutzer → Weitere Benutzer** angelegt.

**Passwort vergessen.** Auf der Anmeldeseite führt **„Passwort vergessen?“** zu drei Wegen:

1. **Code per Telegram oder Pushover:** Dieser Weg erscheint **nur**, wenn Telegram bzw. Pushover eingerichtet ist (mit mindestens einem Empfänger, der als *System*-Empfänger markiert ist). Benutzernamen eingeben, **Code senden**: ein 6-stelliger Code geht an die System-Empfänger. Er gilt 10 Minuten, nur einmal, und nach 5 falschen Eingaben ist er ungültig; höchstens 3 Codes je 15 Minuten. Mit dem Code vergibst du ein neues Passwort. Dieser Weg gilt nur für **Konten mit vollen Administratorrechten**, weil der Code an die Empfänger des Admins geht.
2. **Wiederherstellungsschlüssel:** Beim **Konto anlegen** zeigt die App einmal einen Schlüssel der Form `XXXXX-XXXXX-XXXXX-XXXXX`. Aufschreiben und sicher aufbewahren (nicht auf demselben Gerät wie die App)! Mit Benutzername und Schlüssel vergibst du ein neues Passwort, ganz ohne Telegram oder Internet. Der benutzte Schlüssel ist danach verbraucht, die App zeigt gleich einen neuen. Wer schon vor dieser Funktion ein Konto hatte, erzeugt den Schlüssel unter *Einstellungen → Konto & Benutzer → Konto & Zugang → Wiederherstellungsschlüssel* (mit dem aktuellen Passwort; ein alter Schlüssel wird dabei ungültig).
3. **Letzte Rettung auf dem Gerät:** `python reset_password.py` im App-Ordner (per SSH oder am Rechner). Auf dem Pi z. B. `sudo -u bluenexus /opt/bluenexus/app/.venv/bin/python /opt/bluenexus/app/reset_password.py`.

Nach jedem Zurücksetzen kommt eine Nachricht an Telegram und Pushover („Passwort wurde zurückgesetzt“), und das Logbuch hält es fest. Die Antworten der Seite verraten nie, ob ein Benutzername existiert. Bei anderen Konten (Familie, Gäste) vergibt der Administrator ein neues Passwort unter *Weitere Benutzer*. In der Demo ist die Funktion abgeschaltet.

**Rechte pro Bereich.** Die Rechte sind nach den Menüpunkten der App geordnet. Pro Zeile stellst du mit drei Knöpfen **Kein**, **Lesen** oder **Schreiben** ein. Über „alle:“ in der Gruppenüberschrift setzt du eine ganze Gruppe auf einmal.

| Gruppe | Bereich | Bedeutung |
|---|---|---|
| **Dashboard** | Dashboard | Live-Werte, Verlauf, Preis/Ladeplan. Schreiben = Geräte schalten, eigene Schalter bedienen, Rechner aufwecken, Sofort-Laden, Ladetermine. |
| **Verläufe** | Verläufe | Der Menüpunkt Verläufe: Diagramme ansehen. Auswählen, was aufgezeichnet wird, und Diagramme zusammenstellen darf nur ein Administrator. Standard: nur Administratoren. |
| **Kameras** | Kameras | Der Menüpunkt Kameras: Standbild und Live-Ansicht der Kameras ansehen, die dem Konto freigegeben sind. Anlegen, Zugangsdaten ändern und entfernen nur Admin. Wird **nie** automatisch vergeben (auch nicht an Demo-Konten). |
| **Smart Home** | Aktoren, Soundmodule, Rollläden, Sensoren, Thermostate & Wake-on-LAN | Die gleichnamigen Reiter. Schreiben = **bedienen** (schalten, drücken, aufwecken). Verwalten – anlegen, umbenennen, Symbol, „schaltbar“, Umkehren, Sichtbarkeit, PIN, entfernen – darf **immer nur ein Administrator**. |
| | Sicherheit (Türschlösser) | Der Reiter Sicherheit – bewusst ein eigener Bereich, weil es um die Haustür geht. Türschlösser anlegen/ändern und „Regeln dürfen öffnen“ festlegen darf nur ein Administrator. |
| | Regeln | Der Reiter Regeln. **Achtung:** Regeln schalten auch PIN-geschützte Geräte ohne PIN – „Schreiben“ nur an vertrauenswürdige Konten. |
| | Geräte suchen & einrichten | Die Reiter Geräte suchen, Alexa (wenn das Modul an ist) und Sonstiges: Systeme wählen, suchen, Zugangsdaten (CCU, Tuya, Zigbee), Homematic-Push, Alexa-Status. Alexa-Freigaben legt nur ein Administrator an. |
| **Einstellungen** | Anlage · Tarif & Laden · VRM · Automatik (Überschuss) · Wetter · Meldungen · Dashboard · System | Je ein Bereich pro Einstellungs-Reiter. |
| **Konto & Verwaltung** | Eigenes Konto | Eigenen Namen/Passwort ändern. |
| | NFC-Tags | Der Reiter NFC-Tags. **Lesen** zeigt Tags, Handys und Freigaben (gut für Demo-Konten), aber **keine Adressen** – weder die der Tags noch die der Zentrale. **Schreiben** = Tags anlegen/umbenennen/löschen, Handys registrieren, Freigaben ändern; nur dann sind die Adressen sichtbar. Bei „Kein“ fehlt der Reiter. |
| | Benutzerverwaltung | Nur für Admins. Mindestens ein Zugang muss „Schreiben“ behalten. |

- **Vorlagen:** Über „Vorlage anwenden“ füllst du alles auf einmal vor – **Admin** (alles), **Benutzer** (nur Dashboard), **Smart-Home-Nutzer** (Dashboard + Geräte schreiben, Regeln/Automatik ansehen) und **Demo** (alles ansehen). Danach ist jede Zeile einzeln änderbar.
- **Übersicht in der Benutzerliste:** Statt Zahlen steht pro Gruppe, was das Konto darf, z. B. „Dashboard: Schreiben · Smart Home: teils · Einstellungen: –“. Passt ein Konto genau zu einer Vorlage, steht deren Name da.
- **Lesen** zeigt Seite und Werte; Zugangsdaten (Tokens, Passwörter, Geräte-IPs) sind nur bei **Schreiben** im Klartext sichtbar.
- **Ablauf:** Ein Benutzer kann mit Ablaufdatum angelegt werden (z. B. Gastzugang).
- **Darstellung** (Einstellungen → Dashboard): **Dunkel**, **Hell** oder **Automatisch** (folgt dem Gerät). Die Wahl gilt nur für das jeweilige Gerät und den Browser und braucht kein Recht – jeder stellt sie für sich ein, auch auf der Anmeldeseite und der NFC-Seite.
- **Meine Ansicht** (Einstellungen → Dashboard): Jeder wählt für sich, welche freigegebenen Dashboard-Kacheln er sieht und in welcher Reihenfolge – wirkt sich auf niemand sonst aus. Sie gehört zum Bereich „Einstellungen: Dashboard“: Steht der bei einem Konto auf **Kein**, verschwindet „Meine Ansicht“ für dieses Konto.
- **Dashboard-Kacheln pro Konto (Liste mit Reihenfolge):** Unter den Rechten steht für jedes Konto die Liste aller Dashboard-Kacheln. Der **Haken** legt fest, ob das Konto die Kachel überhaupt sehen darf; mit den **Pfeilen ▲▼** gibst du als Admin die **Reihenfolge** auf dem Dashboard dieses Kontos vor (sonst gilt die globale Reihenfolge aus Einstellungen → Dashboard). Wer „Meine Ansicht“ nutzen darf, kann Auswahl und Reihenfolge für sich selbst weiter ändern – die eigene Wahl hat Vorrang vor deiner Vorgabe; setzt er sie zurück, gilt wieder deine Vorgabe. **Entziehst du einem Konto „Einstellungen: Dashboard“ (Kein), gilt nur noch deine Vorgabe** – seine früher gespeicherte eigene Auswahl und Reihenfolge wirken dann nicht mehr (sie bleiben gespeichert und gelten wieder, wenn du ihm das Recht zurückgibst).
- **Speichern:** Die Rechte eines Kontos werden **automatisch gespeichert**, sobald du etwas änderst (Meldung „Gespeichert ✓“). Nur beim Anlegen eines neuen Benutzers drückst du „Benutzer anlegen“. Der Reiter „Konto & Benutzer“ hat keine globale Speichern-Leiste.
- **Nach einem Update:** Die neuen Smart-Home-Bereiche „Sicherheit“ und „Geräte suchen & einrichten“ übernehmen zunächst das bisherige Recht „Smart Home“, so verliert kein Konto etwas. Danach kannst du sie einzeln anpassen.

**Bedienen ja, verwalten nein.** Auch ein Konto mit „Schreiben“ im Smart Home kann Geräte nur **bedienen**: einen Schalter umlegen, einen Knopf drücken, einen Rechner aufwecken. Der Stift ✎ (Name, Symbol, Dashboard, Schaltbar, Umkehren, Sichtbarkeit, Entfernen), das Anlegen neuer Schalter/WOL-Ziele und das Ändern von Thermostaten und Türschlössern stehen **nur Administratoren** zur Verfügung – in der Oberfläche sind diese Bedienelemente für andere Konten ausgeblendet, und der Server lehnt entsprechende Anfragen ab.

### Sichtbarkeit einzelner Geräte pro Benutzer

**Eigenes Passwort ändern:** nur unter *Einstellungen → Konto & Benutzer → Konto & Zugang* – dort muss das **aktuelle Passwort** eingegeben werden. Das 🔑 in der Benutzerliste setzt dagegen nur das Passwort **anderer** Konten zurück (ohne altes Passwort); bei dem eigenen Konto führt es zu „Konto & Zugang“ und fehlt ganz, wenn dem Konto das Recht „Eigenes Konto: Schreiben“ fehlt. Wer sein Passwort ändern können soll, braucht also dieses Recht.

**Vorschau als Benutzer:** In der Benutzerliste (*Einstellungen → Konto & Benutzer*) gibt es pro Konto den Knopf **👁**. Er zeigt die App in diesem Fenster so, wie dieses Konto sie sieht – mit seinen Rechten, Menüs, Reitern und sichtbaren Geräten. Oben steht eine orangefarbene Leiste „Vorschau als …“ mit **„Vorschau beenden“** – das bringt dich zurück zu *Konto & Benutzer*. Die Vorschau ist **nur zum Ansehen**: Schalten, Speichern und Ändern sind gesperrt, damit nichts versehentlich passiert. Sie gilt für die ganze Browser-Sitzung – auch andere Fenster der App zeigen nach dem Neuladen die Vorschau, bis du sie beendest. Für volle Administratoren gibt es keine Vorschau.

Zusätzlich zu den Bereichsrechten legt ein **Administrator** für jeden Aktor, Sensor, eigenen Schalter/Knopf, jedes Soundmodul und jedes Wake-on-LAN-Ziel fest, **wer es sehen und bedienen darf** – zum Beispiel soll jeder den **Türöffner** sehen, aber nur bestimmte Konten den **Warmwasser-Timer**.

- **Neu angelegte Geräte, Sensoren, Schalter/Knöpfe und WOL-Ziele sind zunächst nur für Administratoren sichtbar.** Erst wenn du sie für Konten freigibst (siehe unten), sehen diese sie. Bereits vorhandene Einträge bleiben unverändert (für alle sichtbar).
- Hinter dem **Stift ✎** des Eintrags gibt es das Symbol mit den **zwei Personen** (nur für Admins sichtbar). **Grau** = alle Benutzer sehen es, **blau** = eingeschränkt (der Hover-Text nennt die Namen).
- Antippen öffnet **„Wer darf das sehen?“**: **Alle Benutzer** oder **Nur ausgewählte Benutzer** mit Häkchen je Konto.
- **Administratoren** (Benutzerverwaltung = Schreiben) sehen immer alles.
- Wer ein Gerät nicht sehen darf, bekommt es **weder im Dashboard noch in den Listen** angezeigt und kann es auch nicht schalten (die Anfrage wird abgelehnt, als gäbe es das Gerät nicht). **Regeln und Abläufe** nutzen das Gerät trotzdem ganz normal.
- Ändert ein Benutzer seinen Namen, wird er in den Listen mitgezogen; wird ein Konto gelöscht, wird es aus den Listen entfernt (das Gerät bleibt eingeschränkt).
- Auf diesem Weg lässt sich auch **„niemand außer Admins“** einstellen: „Nur ausgewählte Benutzer“ ohne Häkchen.

---

## 3. Das Dashboard

Das Dashboard zeigt den Zustand der Anlage und erlaubt Eingriffe. Die Live-Kacheln aktualisieren sich alle 2 Sekunden. Welche Kacheln erscheinen, legen Admin (global) und jeder Benutzer (**Meine Ansicht**) fest.

| Kachel | Inhalt |
|---|---|
| **Live-Werte (Victron)** | Momentanwerte: Netz, Verbrauch, Solar, Batterie, Ladestand (SOC). |
| **Energie (Verlauf)** | Balkendiagramm Verbrauch/Solar mit SOC-Band, 35 Tage Historie mit Tagesnavigation. Auflösung 15 Min oder stündlich (Einstellungen → Diagramme). |
| **Energieflüsse** | Woher der Strom kam und wohin er ging (7 Pfade wie im VRM). |
| **Wochenrückblick** | Solar, Verbrauch, Netz, Autarkie und Kosten der letzten 7 Tage. |
| **Monatsüberblick** | Dieselben Werte je Kalendermonat, dauerhaft archiviert. |
| **Tibber-Kachel** | Aktueller Preis, ESS-Modus, Tagesbilanz (nur bei dynamischem Tarif). |
| **Sofort laden (Override)** | Erzwingt Netzladen unabhängig vom Preis (bis zum Ladelimit). |
| **Strompreis & Ladeplan** | Preiskurve heute/morgen mit eingezeichneten Ladefenstern. Manuelle Termine lassen sich per Klick/Ziehen markieren. |
| **Ladevorgänge (heute)** | Protokoll: geplant / läuft / geladen, mit kWh, Kosten und Ø-Preis. |
| **Manuelle Ladetermine** | Formular für einen festen Ladezeitraum (z. B. E-Auto), überschreibt die Automatik für diesen Zeitraum. |
| **Geräte (Smart Home)** | Schalter für Steckdosen, Lichter und andere Aktoren. |
| **Eigene Schalter & Aktionen (Software)** | Selbst angelegte Schalter und Knöpfe sowie „Rechner aufwecken“. |
| **Sensoren (Smart Home)** | Fenster/Tür, Bewegung, Temperatur usw. – grün/rot bzw. Messwert. |
| **Ersparnis** | Was PV, Akku und Steuerung gegenüber „alles aus dem Netz“ sparen. |
| **Ladeplan-Simulation (Test)** | Vorschlag des EMS-Planers im Vergleich – steuert nichts. |
| **Wetter** | Vorhersage für den Standort (nur Anzeige). |

**Kacheln bedienen**

- **Schalten:** Auf die Gerätekachel tippen. Ist ein **PIN** gesetzt, erscheint zuerst ein Ziffernblock (siehe [PIN-Schutz](#8-pin-schutz)).
- **Reihenfolge ändern:** Kachel **lang drücken** und verschieben (Geräte, Sensoren, Schalter & Aktionen).
- **Eigene Schalter/Knöpfe:** Tippen schaltet bzw. drückt. Läuft ein Ablauf mit Timer, zeigt die Kachel die **Restzeit**; nochmal tippen bricht ab (bei Schaltern).
- **Sensoren** sind nur Anzeige. Rot/Grün hängt davon ab, wie der Sensor eingestellt ist (siehe [Sensoren](#7-sensoren-thermostate-und-türschlösser)).

### 3a. Kameras (Reolink und andere mit RTSP)

Menüpunkt **Kameras**: Alle freigegebenen Kameras als Kacheln mit Standbild.

- **Standbild:** Aktualisiert sich automatisch (oben einstellbar: jede Sekunde, alle 5, 10 oder 30 Sekunden – Standard 5 Sekunden; die Wahl merkt sich der Browser). Nur sichtbare Kacheln werden aufgefrischt, im Hintergrund-Tab ruht alles.
- **▶ Live:** Startet für diese eine Kamera das Live-Bild (mit ■ wieder beenden). Es endet nach 15 Minuten von selbst und stoppt, wenn du den Tab verlässt – so läuft nie ein vergessener Dauerstrom. Pro Browser läuft immer nur **ein** Live-Bild: Startest du ▶ bei einer anderen Kamera, endet das bisherige automatisch (so bleibt Datenrate und Serverlast klein). Serverweit sind maximal 6 Live-Ansichten gleichzeitig möglich (mehrere Konten/Geräte).
- **Live-Bild: Klar oder Flüssig** (Auswahl oben, wird im Browser gemerkt): **Klar** nimmt den Hauptstrom der Kamera (hohe Auflösung, bis 1920 Pixel Breite, 10 Bilder/s), **Flüssig** den kleinen Teilstrom (960 Pixel, 8 Bilder/s). „Klar“ braucht mehr Datenrate (grob 5–15 MBit/s je Betrachter) und Serverleistung, weil der Server das Kamerabild umrechnet – bei 4K/H.265-Kameras kann das einen kleinen Server spürbar auslasten. Reicht dir das nicht oder ruckelt es, wähle „Flüssig“. Das Standbild ist immer in voller Auflösung.
- **Reihenfolge ändern:** Eine Kamerakachel (nicht auf einem Knopf) **lange drücken** (ca. eine halbe Sekunde, am Handy kurzes Vibrieren) und an die gewünschte Stelle **verschieben**, dann loslassen. Die Reihenfolge ist **persönlich** (jedes Konto hat seine eigene, auch Konten mit nur Leserecht) und gilt auf all deinen Geräten. Neue Kameras erscheinen hinten.
- **Verbindungsaufbau:** Das Live-Bild braucht ein, zwei Sekunden (Meldung „Verbinde …“). Kommt kein Bild, versucht die App es automatisch bis zu dreimal neu, bevor sie ersatzweise Standbilder im Sekundentakt zeigt. Viele Kameras erlauben nur wenige gleichzeitige Video-Verbindungen und halten beendete Verbindungen noch kurz fest – die App meldet sich deshalb beim Beenden sauber ab.
- **⤢ Vollbild:** Das Bild füllt den ganzen Bildschirm (auch auf dem Handy/iPhone), Live-Bild läuft weiter. Beenden mit **✕** oben rechts (oder Esc am PC). Am Handy das Gerät **quer** halten, dann füllt das 16:9-Bild die ganze Breite. Wer die Adressleiste ausblenden und das Querformat sperren möchte, tippt im Vollbild auf **„Adressleiste ausblenden“** (nur Android/PC im Browser; Android blendet dabei einen eigenen Hinweis „Vollbildmodus beenden“ ein, den eine Webseite nicht unterdrücken kann). Ist die App als **App installiert** (Zum Startbildschirm hinzugefügt), gibt es ohnehin keine Adressleiste.
- **Technik:** Die App spricht die Kamera **lokal** an (Standbild über die HTTP-Schnittstelle der Kamera, Live über RTSP, das der Server mit **ffmpeg** in einen Strom umwandelt, den jeder Browser – auch iPhone – anzeigen kann). Zugangsdaten und die Kamera-IP bleiben auf dem Server; die Bilder laufen durch die App, also nur mit Anmeldung, Recht „Kameras“ und Freigabe der jeweiligen Kamera. Die Kamera selbst wird nicht ins Internet geöffnet.
- **ffmpeg auf dem Server:** Für das Live-Bild einmalig `apt install -y ffmpeg`. Ohne ffmpeg zeigt ▶ ersatzweise Standbilder im Sekundentakt, und die Seite weist darauf hin.
- **Kameratypen:** **Reolink** (lokale Schnittstelle der Kamera, Standbild in voller Auflösung) und **„Andere Kamera mit RTSP“**, z. B. **Wansview** und viele weitere IP-Kameras. Bei RTSP-Kameras kommt das Standbild aus dem Videostrom (ffmpeg; etwa 1–2 Sekunden Verzögerung pro Bild, daher ist „jede Sekunde“ dort eher alle 2 Sekunden) und das Live-Bild wie bei Reolink. Voraussetzung: **ffmpeg** auf dem Server und ein **RTSP-Stream an der Kamera**.
  - **Wansview:** In der Wansview-App bei der Kamera RTSP bzw. ONVIF aktivieren (nicht jedes Modell und jede Firmware kann das) und ein Gerätepasswort vergeben. Benutzer meist `admin`, Passwort = **Gerätepasswort** (nicht das App-Konto).
  - **RTSP-Pfad:** Leer lassen – die App probiert die gängigen Pfade (`/live/ch0`, `/stream1`, `/Streaming/Channels/101` u. a.) und merkt sich den passenden. Kennst du den Pfad aus der Anleitung, trägst du ihn unter „Erweitert“ ein; optional einen zweiten Pfad für das kleine Teilbild („Flüssig“).
- **Chime (Türgong) der Video-Türklingel (nur Admin):** Am Kamera-Symbol ✎ (Bearbeiten) → **🔔 Chime (Türgong)**. Dort erscheinen die mit der Türklingel gekoppelten Chimes: einen **Klingelton wählen** (10 Töne) und mit **Läuten** ausprobieren, die **Lautstärke** (Stumm bis Laut) einstellen und speichern. Voraussetzung: Der Chime ist in der Reolink-App mit der Türklingel gekoppelt und der Web-Zugang der Kamera (HTTP/HTTPS) ist eingeschaltet. Den Ton, mit dem der Chime beim Klingeln läutet, stellst du weiterhin in der Reolink-App ein. Aus einer Regel heraus lässt sich der Chime mit dem Schritt **Chime läuten** auslösen.
- **Kamera hinzufügen (nur Admin):** „＋ Kamera hinzufügen“ → IP-Adresse, Benutzer (meist `admin`), Passwort (und optional Name, Port, Kanal). Die App prüft die Verbindung (erst http, dann https) und übernimmt Modell und Namen. Neue Kameras sind **zunächst nur für Administratoren sichtbar**.
- **Stift ✎ (nur Admin):** Name ändern, **Sichtbarkeit** pro Konto (Symbol mit den zwei Personen, wie bei den Geräten), **Zugang ändern** (IP, Benutzer, neues Passwort, Port, Kanal) und Entfernen.
- **Fernzugriff** (Cloudflare-Tunnel) funktioniert; der Live-Strom braucht je Betrachter etwa 1–3 MBit/s Upload.

> **Ring-Klingeln/-Kameras** sind bewusst **nicht** eingebunden: Ring bietet keine lokale Schnittstelle, eine Anbindung bräuchte ein Zwischenprogramm (z. B. ring-mqtt mit MQTT-Server) oder die inoffizielle Ring-Cloud und wäre wartungsanfällig. Dafür bleibt die Ring-App.

### 3b. Verläufe (Diagramme der Messwerte)

Menüpunkt **Verläufe** (Ersatz für InfluxDB + Grafik-Adapter): ausgewählte Messwerte werden **fein aufgezeichnet** und als Diagramme angezeigt – z. B. der genaue Stromverlauf in Watt über den ganzen Tag, bei dem auch kurze Spitzen sichtbar bleiben.

- **Aufzeichnen (Administrator):** *⚙ Datenreihen* → Quelle wählen, Abtastzeit (5 s, 10 s, 30 s, 1 min, 5 min), optional ein Name → **Aufzeichnen**. Verfügbar sind: **Energie** (Netz, Verbrauch Haus, Solar gesamt, Batterie, Akkustand; Modul Energie) und der **Strompreis** (ct/kWh: bei dynamischem Tarif der aktuelle Tibber-Viertelstundenpreis, sonst der Festpreis; als Stufenlinie, Abtastzeit 1 min). Beim Anlegen der Preis-Reihe trägt die App die **schon bekannten Tibber-Preise der letzten 14 Tage nachträglich** ein, damit die Preiskurve sofort sichtbar ist. Preis und Netzleistung lassen sich in einem Diagramm übereinanderlegen (zwei Achsen). Die Reihe **„Kosten Netzbezug“** (ct/h) rechnet **Netzbezug × aktueller Preis**: 3 kW bei 30 ct/kWh ergeben 90 ct/h; bei Einspeisung ist der Wert 0. Sie zeigt, was der Strombezug gerade pro Stunde kostet (die Fläche darunter ist über die Zeit die Summe der Kosten), **Geräte** (Leistung in W bei Shelly, Tasmota und Homematic mit Leistungsmessung; an/aus-Zustand jedes Geräts) und **Sensoren** (alle angelegten, auch Fenster/Tür und Kamera-Erkennung als an/aus). Aufgezeichnet wird nur, was dort steht. Pro Reihe kann Name und Abtastzeit später geändert werden.
- **Diagramme (Administrator):** *＋ Diagramm* → Titel und bis zu 12 Reihen wählen (verschiedene Einheiten bekommen eine zweite Achse; an/aus-Reihen laufen als Stufen am unteren/oberen Rand mit). Neben jeder Reihe wählst du **die Farbe frei** (Farbfeld; sie gilt nur in diesem Diagramm). *✎* bearbeitet, *✕* löscht ein Diagramm (die Werte bleiben). Die Diagramme lassen sich per **langem Druck und Ziehen** umsortieren.
- **Darstellung:** Pro Diagramm wählst du im Dialog die Art: **Linie** (mit Min/Max-Band bei langen Zeiträumen), **Fläche** (Linie mit gefüllter Fläche, z. B. für Akkustand), **Balken** (Mittelwert je Zeitabschnitt – gut für Verbrauch oder Kosten über viele Stunden/Tage; die Balkenbreite passt sich dem Zeitraum an, kurze Spitzen werden dabei gemittelt), **Stufen** (Wert bleibt bis zur nächsten Änderung, z. B. Preise oder Zustände) **Punkte** (nur die einzelnen Messpunkte), **Fläche gestapelt** oder **Balken gestapelt**: Die Reihen **mit gleicher Einheit** werden aufeinandergelegt, sodass die Gesamthöhe die **Summe** zeigt (z. B. Verbrauch Wohnzimmer + Küche + Heizung = Gesamtverbrauch, oder Netz + Solar + Batterie). Im Hinweisfenster steht dann zusätzlich die **Summe**. Reihen mit anderer Einheit laufen auf der zweiten Achse mit, an/aus-Reihen bleiben als Stufen unabgestapelt. Der Strompreis und an/aus-Reihen laufen immer als Stufen. Die Wahl gilt auch in der Dashboard-Kachel.
- **Als Bild speichern (PNG):** Jedes Diagramm hat oben rechts **⬇ PNG** (für alle, die Verläufe sehen dürfen). Du wählst den **Hintergrund** – *dunkel* (wie am Bildschirm) oder *weiß* (zum Drucken oder für Dokumente) – und die App speichert das Diagramm genau so, wie es gerade angezeigt wird (Zeitraum, Zoom, Darstellungsart, Farben), mit **Titel, Zeitraum, Legende und Fußzeile**. Der Dateiname enthält Titel und Datum (z. B. `Verlauf-Stromverbrauch-2026-10-06.png`). Das Bild entsteht im Browser, es wird nichts hochgeladen.
- **Auf dem Dashboard:** Im Diagramm-Dialog den Haken **„Auf dem Dashboard zeigen“** setzen. Alle so markierten Diagramme erscheinen auf dem Dashboard in der Kachel **„Verlauf“** (mit Zeitraum-Knöpfen 1 h / 6 h / 24 h / 7 T; die Wahl merkt sich der Browser) und einem Link **„Alle Verläufe →“**. Die Kachel sehen nur Konten mit dem Recht „Verläufe“; sie lässt sich wie jede Kachel unter *Einstellungen → Anzeige* ausschalten und pro Konto freigeben. Ohne markiertes Diagramm bleibt sie unsichtbar. Sie aktualisiert sich alle 30 Sekunden.
- **Ansehen:** Oben den Zeitraum wählen: **1 h, 6 h, 12 h, 24 h, 7 T, 30 T, 1 J** oder über das Datumsfeld **einen bestimmten Tag**. Bewegst du die Maus/den Finger über das Diagramm, zeigt das Fenster Zeit und Wert. Bei langen Zeiträumen wird zusammengefasst; ein **blasses Band** zeigt dann Minimum und Maximum, damit Spitzen nicht verschwinden. Lücken (Gerät oder App war weg) bleiben als Lücke sichtbar. **Zoomen:** Mit gedrückter Maustaste im Diagramm einen Bereich aufziehen – alle Diagramme zeigen dann genau diesen Ausschnitt (mit den feinen Rohwerten, solange sie noch da sind). **↩ Zoom zurück** (steht oben; sobald du gezoomt hast, zeigt jedes Diagramm neben „PNG“ ein **−**) oder ein **Doppelklick** ins Diagramm geht einen Schritt zurück; die Zeitraum-Knöpfe setzen alles zurück. Am Handy zuerst etwa eine halbe Sekunde lang drücken, dann ziehen (sonst scrollt die Seite). Live-Zeiträume aktualisieren sich alle 15 Sekunden. **Zeit verschieben:** Im Diagramm einfach **seitlich wischen** (Maus: gedrückt halten und ziehen, Handy: mit dem Finger wischen) – so geht es in der Zeit zurück und wieder vor, nie in die Zukunft. **Jetzt** springt zurück zur aktuellen Zeit. **Zoom:** Mit dem Knopf **🔍 Zoom** wird die Lupe aktiv; dann einen Bereich im Diagramm aufziehen und vergrößern. Danach springt die Lupe von selbst zurück, und Wischen gilt wieder (Esc oder ein weiterer Klick auf die Lupe bricht ab). **Zoom zurück** bzw. Doppelklick ins Diagramm geht einen Schritt zurück. Den Tag wählst du über **📅 Tag wählen** (eigener Kalender).
- **Aufbewahrung:** Rohwerte in der gewählten Abtastzeit **7 Tage**, dazu eine **Minuten-Zusammenfassung** (Mittel, Min, Max) **400 Tage**. Lange Zeiträume und alte Tage kommen aus der Zusammenfassung. Die Datenbank (`app/verlauf.db`) liegt nur auf dem Server, ist nicht in Git und wird beim Update nicht angefasst; Größe und Anzahl der Werte stehen unter *⚙ Datenreihen*.
- **Reihe entfernen:** beendet nur die Aufzeichnung; die bisherigen Werte bleiben und schließen wieder an, wenn du dieselbe Quelle neu anlegst. Auf Wunsch (Haken) werden die Werte endgültig gelöscht.
- **Last:** Energiewerte kommen aus der ohnehin laufenden Messung (kein zusätzlicher Zugriff auf den Cerbo). Sensoren und Homematic-Werte nutzen den normalen Zwischenspeicher (mit Push kein Funk). Shelly/Tasmota werden je Abtastzeit einmal abgefragt – 10 s sind für Leistungsverläufe üblich, selten Wechselndes reicht mit 1–5 min.

---

## 4. Einstellungen

Die Einstellungen sind in Reiter gegliedert (Anlage, Tarif & Laden, VRM, Wetter, Meldungen, Dashboard, System, Konto & Benutzer). Alles zum Smart Home steht im eigenen Menü **Smart Home** (Kapitel 5). Geänderte Werte gelten erst nach **Speichern**. Einige Werte (Mindest-SOC, Sollwert Netz) werden dagegen **direkt am Cerbo** gesetzt.

### 4.1 Betrieb und System

- **Anzeigename:** Steht in der Kopfzeile und im Browser-Tab (praktisch bei mehreren Anlagen).
- *(Reihenfolge im Reiter **System**: App-Version & Update, Uhrzeit & Zeitzone, Betrieb, Module, Fernzugriff, Betriebsbericht, Sicherung & Wiederherstellung, Testmodus. Dry-Run, Regel-Intervall und Energie-Messtakt stehen in der Karte **Ladesteuerung** im Reiter **Anlage**, direkt unter den Cerbo-Angaben.)*
- **Dry-Run:** An = die Ladesteuerung rechnet und protokolliert nur, am Cerbo wird nichts geschaltet. Für den echten Betrieb ausschalten. Läuft parallel noch eine andere Steuerung (z. B. ioBroker), die den ESS-Modus setzt, diese vorher stoppen.
- **Regel-Intervall:** Wie oft die Ladesteuerung neu rechnet (Standard 300 s, ausgerichtet aufs Viertelstunden-Raster). Strompreise ändern sich nur viertelstündlich, daher reicht das.
- **Energie-Messtakt:** Wie oft Solar/Verbrauch/Netz/Akku für Verlauf und Tagesbilanz gemessen werden (Standard 10 s).
- **Diagramme:** „Energie (Verlauf) stündlich“ und „Energieflüsse stündlich“ fassen vier Viertelstunden wie im VRM zusammen.

### 4.2 Anlage (Cerbo GX)

- **Cerbo-IP und Port** (Standard 502). Am Cerbo muss **Modbus TCP** aktiviert sein: *Einstellungen → Dienste → Modbus TCP*.
- Der Button **Verbindung testen** prüft den Zugang.

### 4.3 Anlage & Speicher

| Feld | Bedeutung |
|---|---|
| Nutzbare Akkukapazität (kWh) | Real nutzbare Größe, nicht Nennkapazität (ca. 95 % davon). |
| Akku in Betrieb seit | Für die Vollzyklen-Berechnung im Watchdog. |
| Erwartete Zyklenzahl | Herstellerangabe (z. B. 6000), für die Lebensdauer-Hochrechnung. |
| Tagesverbrauch (kWh) | Durchschnitt pro Tag – Basis für die Planung. |
| Ladestrom (A) / Systemspannung (V) | Daraus errechnet sich die Ladeleistung beim Netzladen. |
| **Minimaler Akkustand am Cerbo (%)** | Wie „Minimaler SOC“ im VRM; darunter entlädt der Akku nicht. Wird **direkt am Cerbo** gesetzt. |
| **Sollwert Netz am Cerbo (W)** | ESS-Netz-Sollwert (−1000 … 1000 W in 10er-Schritten). 0 = möglichst kein Bezug/Einspeisung. Wird **direkt am Cerbo** gesetzt. |

> **PV-Reserve, Ladelimit und Preisschwelle** stehen im Reiter **Tarif & Laden** in der Karte **„Laden aus dem Netz“** (siehe 4.4).

**Periodische Vollladung:** Alle X Tage wird das Ladelimit auf ein Ziel (meist 100 %) angehoben, damit das BMS die Zellen balancieren kann. *Wann* geladen wird, entscheidet weiterhin die Planung – nur bei günstigem Preis bzw. genug Sonne. 0 = aus.

### 4.4 Stromtarif und Ladestrategie

#### Karte „Laden aus dem Netz“ (Reiter Tarif & Laden)

Hier legst du fest, **bis wohin** und **ab welchem Preis** die App aus dem Netz lädt:

| Feld | Bedeutung |
|---|---|
| **PV-Reserve: Netzladen bis (%)** | Bis zu diesem **Ladestand** lädt die Steuerung aus dem Netz (Intelligente Planung und klassische Strategien); der Rest bis 100 % bleibt für die Mittagssonne frei. Beispiel: 80 % bei 22,8 kWh = rund 4,6 kWh Platz (das Feld zeigt den Platz in kWh darunter an). 100 = kein Puffer. Früher stand hier „PV-Reserve (kWh)“; ein alter Wert wird beim Öffnen automatisch in Prozent umgerechnet. |
| Ladelimit / max. SOC (%) | Harte Obergrenze für **alles**, was aus dem Netz lädt, auch Sofort-Override, Ladetermine und die Preisschwelle „Immer laden unter“. Diese Wege kennen die PV-Reserve nicht, sie stoppen erst am Ladelimit. Es sollte gleich hoch oder höher als die PV-Reserve sein. |
| **Immer laden unter (ct/kWh)** („Preisschwelle“) | Fällt der Preis auf oder unter diesen Wert, wird geladen, unabhängig von der Strategie (0 = aus). Das gilt **auch bei eingeschalteter Intelligenter Planung**: Liegt der Preis unter der Schwelle, lädt die App sofort, statt auf noch billigere Viertelstunden zu warten (nur das Ladelimit bremst weiterhin). Im Preisdiagramm des Dashboards zeigt „Preisschwelle greift“ diese Stunden an. Die „Geplanten Ladefenster“ führen diese Viertelstunden mit auf (soweit sie bis zum Ladelimit noch in den Akku passen). |
| **Sicherheitspuffer beim Nachtladen (%-Punkte)** | Nur für die **Intelligente Planung**: Sie rechnet nachts mit einem entsprechend höheren Mindest-Akkustand und plant vorsichtiger. |

**Bis wohin wird aus dem Netz geladen?** Zwei Grenzen wirken zusammen: die **PV-Reserve** (Ladestand, bis zu dem die „klugen“ Wege laden) und das **Ladelimit** (harte Obergrenze für alles). Beispiel mit PV-Reserve 80 % und Ladelimit 95 %:

| Was lädt gerade | Stoppt bei |
|---|---|
| **Intelligente Planung** und **klassische Strategien** (Peak-Schutz, SOC-Strategie …) | **80 %** (PV-Reserve) – der Rest bleibt für die Mittagssonne frei |
| **Preisschwelle** („Immer laden unter“, Anzeige „Supergünstig“) | **95 %** (Ladelimit) |
| **Sofort-Override** (Knopf auf dem Dashboard) | **95 %** (Ladelimit) |
| **Manueller Ladetermin** | **95 %** (Ladelimit) |

Merksatz: Die PV-Reserve gilt nur für die automatische Planung. Alles, was du selbst auslöst (Override, Ladetermin) oder was als „immer laden“ eingestellt ist (Preisschwelle), geht bis zum Ladelimit. Das Ladelimit verhindert in allen Fällen, dass der Akku auf 100 % lädt. Liegt die PV-Reserve über dem Ladelimit, gilt das Ladelimit. Wer nachts bei sehr niedrigen Preisen nicht über die PV-Reserve hinaus laden will, senkt die Preisschwelle (dann entscheidet die Planung) oder setzt das Ladelimit niedriger.


- **Dynamischer Tarif (Tibber):** Access-Token von developer.tibber.com eintragen. Die Steuerung lädt in den günstigsten Viertelstunden.
- **Fester Preis:** Preis pro kWh (brutto) eintragen. Es gibt dann **keine Preisplanung**, die App lädt nie aktiv aus dem Netz. PV-Vorrang, Ladelimit und Sofort-Override wirken weiter.
- **Intelligente Planung** (Standard bei dynamischem Tarif): rechnet bei jedem Durchlauf frisch über den ganzen bekannten Zeitraum, wann Netzladen am günstigsten ist. Sie ersetzt Peak-Schutz, SOC-Strategie und Günstig-Vorkauf. *Sicherheitspuffer beim Nachtladen* lässt sie vorsichtiger planen.
- **Klassische Strategien** (nur wenn die Intelligente Planung aus ist): Peak-Schutz (Morgen-/Abend-Peak, Mindest-SOC, Notbrems-Preislimit, optional Günstig-Vorkauf) und SOC-Strategie (Nacht-Sicherheits-SOC, Ziel-SOC Morgen-Brücke, Hysterese). Details siehe README.
- **PV-Prognose:** Kommt vom VRM; Morgen-Faktor (Winter ≈ 0,05, Sommer ≈ 0,25) und optional **automatische Anpassung** an die Wirklichkeit (benötigt ≥ 5 Tage Solarlogbuch, Faktor 0,6–1,1). Ohne VRM rechnet die App mit dem Durchschnitt der letzten Tageserträge.
- **Netz-Zähler heute korrigieren:** Nur nötig, wenn die App über Mitternacht aus war – dann die Tageswerte aus der Victron-App eintragen.

### 4.5 VRM

- **Installations-ID** und **Zugriffstoken** aus dem VRM-Portal (*Präferenzen → Integrationen → Zugangs-Token*). Der Token wird nur einmal angezeigt.
- **Verlauf nachholen:** Fehlen Zeiträume (nach Ausfall), holt die App bis zu 35 Tage (oder länger, in 7-Tage-Häppchen) aus dem VRM. Erst Vorschau, dann übernehmen; vorhandene Messwerte bleiben, vorher wird gesichert. Kosten der nachgeholten Zeiten bleiben 0, bei festem Tarif werden sie automatisch nachgerechnet.

### 4.6 Wetter

Standort per Suche, GPS oder Google-Maps-Koordinaten einstellen. Das Wetter ist nur Anzeige und beeinflusst die Steuerung nicht.

### 4.7 Dashboard-Kacheln

Admin legt fest, welche Kacheln global sichtbar sind und in welcher Reihenfolge. Jeder Benutzer kann es unter **Meine Ansicht** weiter einschränken.

---

## 5. Smart Home: Geräte einrichten

**Menü Smart Home.** Die Unter-Reiter im Überblick:

| Reiter | Inhalt |
|---|---|
| **Aktoren** (Startseite) | Alle schaltbaren Geräte (Steckdosen, Lichter, Dimmer) und die eigenen Schalter & Knöpfe. |
| **Sensoren** | Sensoren von Homematic und Zigbee. |
| **Thermostate** | Thermostate von Homematic und Zigbee. |
| **Sicherheit** | Türschlösser (sicherheitsrelevante Geräte). |
| **Regeln** | Regel-Editor (Kapitel 10). |
| **Geräte suchen** | „Welche Systeme hast du?“ (Häkchen) und je System ein Fenster zum Suchen und Einrichten. |
| **Wake-on-LAN** | Rechner zum Aufwecken (Kapitel 11). |
| **Sonstiges** | Homematic-Push sowie Verweise auf Dashboard-Kacheln, Telegram und Logbücher. |

Die Reiter passen sich der Bildschirmbreite an: Am **PC** (breites Fenster) stehen die **Namen** als Text, am **Handy** (schmal) nur **Symbole**, deren Name beim Darüberfahren erscheint und in der Überschrift der Karte steht. Trennstriche gruppieren die Leiste vor und nach „Regeln“.

Zum Einrichten: Unter **Geräte suchen** per Häkchen wählen, **welche Systeme du hast**. Für jedes angekreuzte System erscheint ein eigenes Fenster zum Suchen und Einrichten. Bereits eingerichtete Geräte bleiben immer sichtbar. Wer keine Rechte für „Smart Home“ hat, sieht nur die Reiter, die ihm freigegeben sind (z. B. nur „Regeln“).

**Treffer erst ansehen, dann hinzufügen (alle Systeme):** Ob Shelly, Tasmota (auch per eingetippter IP-Adresse), Tuya, Homematic oder Zigbee – gefundene Geräte landen **nicht sofort** in der Geräteliste, sondern erscheinen unter dem jeweiligen System. Dort kannst du den **Namen** (bei Geräten und Sensoren auch das **Symbol**) schon anpassen und erst dann auf **Hinzufügen** klicken; „Alle hinzufügen“ übernimmt alle Zeilen mit ihren Namen. Passwortgeschützte Shelly/Tasmota fragen vorher nach dem Passwort.

**Reihenfolge ändern (überall gleich):** In allen Listen – Aktoren, Sensoren, Thermostate, Türschlösser, Soundmodule, Rollläden, eigene Schalter, Wake-on-LAN-Ziele, Kameras, **Alexa-Freigaben**, **Zigbee-Gateways** und **Regeln** – hältst du eine Zeile auf freier Fläche (nicht auf einem Knopf, Feld oder Regler) etwa **eine halbe Sekunde gedrückt** und ziehst sie dann an die neue Stelle (am Rand scrollt die Seite mit). Beim Loslassen ist die Reihenfolge gespeichert („Reihenfolge gespeichert ✓“). Kurz tippen oder scrollen bleibt unverändert. Das Umsortieren in den Listen darf nur ein Administrator; auf dem Dashboard ordnet jedes Konto seine Kacheln wie bisher selbst. **Bei Regeln** gibt es die Bearbeitung nur über den **Stift ✎** (ein Klick auf die Zeile öffnet sie nicht mehr, damit man sie ziehen kann). Das Ziehen ändert den Entwurf: unten auf **Speichern** tippen, dann gilt die neue Reihenfolge (sie entscheidet auch, welche Regel zuerst geprüft wird).

Jedes Gerät hat eine Zeile mit Symbol (antippen = anderes Symbol wählen), Name und Status. Alles Weitere steckt hinter dem **Stift ✎**: **Name** ändern (Häkchen speichert), dann Symbole, die **grün** leuchten, wenn sie an sind: **Auge** = auf dem Dashboard anzeigen, **Ein/Aus** = schaltbar (aus = nur Überwachung), und rechts der **Papierkorb** zum Entfernen. Bei Sensoren gibt es statt „schaltbar“ das Symbol **Pfeile** (= „TRUE/FALSE umkehren“, z. B. „TRUE = geschlossen“). Der Hover-Text nennt die Bedeutung, nach dem Antippen erscheint sie kurz als Meldung.

| System | Einrichtung |
|---|---|
| **Shelly** (Gen1–Gen3) | „Shellys suchen“ durchsucht das Heimnetz, oder IP einzeln eintragen. |
| **Tasmota / WLED** | „Tasmota / WLED suchen“ (eine Suche für beide) oder IP einzeln eintragen. **WLED**-Lampen/-Streifen werden an der JSON-Schnittstelle erkannt, lassen sich ein-/ausschalten (auch in Regeln, per Alexa, auf dem Dashboard) und in der Geräteliste mit einem **Helligkeits-Regler** dimmen (ganz links 0 % = aus, ganz rechts 100 %; beim Loslassen übernommen). Über den Knopf **🎨** unter einer WLED-Lampe (Geräteliste, Reiter Aktoren) stellst du **Farbe**, **Effekt**, **Farbpalette** und eine **Voreinstellung** (Preset aus WLED) direkt ein; jede Änderung schaltet die Lampe ein. Beim Einschalten durch Regeln/Dashboard/Alexa behält WLED seine zuletzt eingestellte Helligkeit, Farbe und den Effekt. Mit **„💾 Aktuelle Einstellung speichern …“** speicherst du, wie die Lampe gerade leuchtet (Farbe, Effekt, Palette, Helligkeit), unter einem Namen als **Voreinstellung in WLED** (gleicher Name überschreibt; es werden die kleinsten freien Plätze 1–250 belegt). **In Regeln** (Art „Ablauf“) gibt es den Schritt **„WLED: Voreinstellung / Farbe setzen“**: entweder eine Voreinstellung der Lampe aufrufen (die Liste wird aus der Lampe geladen) oder eine Farbe (mit optionaler Helligkeit in %) setzen. Ein- und Ausschalten geht wie bei jedem Gerät über „Gerät ein-/ausschalten“. Tipp: Lampe in der Geräteliste einstellen, als Voreinstellung speichern und diese in der Regel aufrufen (z. B. „bei Sonnenuntergang Voreinstellung Warmweiß“). Die Lampe lässt sich nicht entfernen, solange eine eingeschaltete Regel sie benutzt. Einen eingebauten Rückschalt-Timer gibt es bei WLED hier nicht. |
| **Tuya / Smart Life** (z. B. Gosund) | Einmalig Zugang (Region, Access ID, Access Secret) von iot.tuya.com eintragen; die Cloud wird nur zum Abholen der Geräteschlüssel gebraucht, geschaltet wird lokal. |
| **Homematic / HomematicIP (OpenCCU)** | CCU-Adresse, Benutzer, Passwort eintragen (Benutzer mit Schreibrechten). Dann Geräte, Sensoren, Thermostate und Türschlösser suchen. Das Passwort bleibt auf dem Server und wird nie wieder angezeigt. |
| **Zigbee (Phoscon / deCONZ)** | In Phoscon *Einstellungen → Gateway → Erweitert → „App autorisieren“* drücken, dann hier innerhalb einer Minute „Mit Gateway verbinden“. Danach Geräte, Sensoren und Thermostate suchen. **Mehrere Gateways** (z. B. eins pro Haus) sind möglich: Name und Adresse eintragen, verbinden, dann „Weiteres Gateway hinzufügen“. Die Treffer aller Gateways erscheinen gemeinsam (mit dem Gateway-Namen dahinter). |
| **Wake-on-LAN** | Siehe [Kapitel 11](#11-wake-on-lan). |

**Weitere Netze / VLANs:** Standardmäßig durchsucht die App nur das Netz des Servers. Weitere Netze (z. B. `192.168.178.0/24`, mehrere mit Komma) kann man für Shelly, Tasmota und Tuya zusätzlich eintragen. Der Server muss dorthin routen dürfen.

**Homematic-Push:** Mit dem Schalter „Push von der CCU“ meldet die CCU Änderungen (Tür geht auf, Schalter betätigt) selbst an die App. Regeln mit Sensoren reagieren dann in unter einer Sekunde, und es wird nichts ständig abgefragt. Die CCU muss den Server unter dem eingestellten Port erreichen können (Standard 8703). Fällt der Push aus, fragt die App wie gewohnt ab.

**Homematic-Funk-Diagnose (Duty Cycle):** Unter *Smart Home → Sonstiges → Homematic: Push von der CCU* gibt es **„Funk-Diagnose (Duty Cycle)“** (Aktualisieren drücken). Sie zeigt:

- den **Duty Cycle** der BidCos-Funkmodule in Prozent (Anteil der erlaubten Sendezeit von 1 % pro Stunde im 868-MHz-Band; bei 100 % sendet die CCU nicht mehr, Befehle gehen verloren oder verspäten sich). HomematicIP-Geräte melden diesen Wert nicht;
- die **gesprächigsten Geräte** der letzten 10 Minuten (Meldungen der CCU pro Minute, häufigster Datenpunkt) – nur mit aktivem Push;
- wie viele **Befehle diese App** in der letzten Stunde an die CCU gesendet hat, davon wie viele für den **Sicherheits-Timer** (Regeln → Einstellungen), und an welche Geräte.

Daraus ergeben sich kurze Hinweise (z. B. Sicherheits-Timer verlängern, auffälliges Gerät). **Test „Homematic pausieren“:** Der Knopf sperrt den Zugriff der App auf die CCU für 30 Minuten (endet von selbst, vorzeitig mit „Pause beenden“; die Victron-Steuerung läuft normal weiter). Sinkt der Duty Cycle in dieser Zeit, kam der Funkverkehr von der App; bleibt er hoch, liegt es an Geräten oder der CCU. Während der Pause erscheinen Homematic-Geräte als nicht erreichbar, Regeln schalten sie nicht. Die Zähler laufen nur im Speicher und beginnen beim Start der App von vorn. Beim Lesen gilt: **Mit aktivem Push** liest die App einen Homematic-Wert nur einmal (nach dem Start) von der CCU und vertraut danach den Meldungen der CCU; erst nach 15 Minuten ohne Meldung fragt sie einmal nach (Erreichbar-Status ebenso). **Ohne Push** werden gelesene Werte 10 Sekunden wiederverwendet. Hintergrund: Ein Lese-Aufruf kann bei Netz-Aktoren (Burst) einen Funkbefehl auslösen und so den Duty Cycle der CCU füllen – deshalb wird so wenig wie möglich gelesen. Darum sollte der **Push immer an** sein.

---

## 6. Eigene Schalter & Knöpfe (Software)

Das sind Schalter und Knöpfe, hinter denen **kein Gerät** steckt. Sie erscheinen auf dem Dashboard in der Kachel „Schalter & Aktionen“ und dienen als **Auslöser oder Merker für Regeln**.

- **Schalter:** bleibt an/aus, wie ein Lichtschalter.
- **Knopf:** wird gedrückt (löst einmal aus).
- **Knopf mit Web-Aufruf:** Ein Knopf, der beim Drücken eine **hinterlegte Adresse aufruft** (GET oder POST), z. B. einen Webhook (IFTTT, Home Assistant, ioBroker) oder ein Gerät mit HTTP-Schnittstelle. Beim Anlegen die Adresse eintragen (du siehst, was du eingibst); später hinter dem Stift ✎ **Adresse ansehen/ändern/entfernen** und GET/POST wählen. Die **Adresse ist nur für Administratoren sichtbar**: Wer den Knopf nur bedient, sieht sie nie, sie steht nicht im Logbuch und nicht in Fehlermeldungen. Nach dem Drücken meldet das Dashboard kurz, ob der Aufruf geklappt hat („Ausgelöst ✓“ oder „Aufruf fehlgeschlagen – …“). Der Aufruf geschieht auch, wenn eine **Regel** oder ein **NFC-Tag** den Knopf drückt, im **Trockenlauf** nie. Geschützt: nur `http`/`https`, keine Ziele wie 169.254.x.x (Cloud-Metadaten), Umleitungen werden nicht verfolgt, 8 Sekunden Zeitgrenze. Die Adresse gehört zur Sicherung.
- **Nachlauf-Timer:** läuft die eingestellte Zeit (Minuten) und geht dann **von selbst aus**. Jedes erneute Starten beginnt die Zeit **von vorn** (nachtriggerbar). Gedacht als **gemeinsamer Nachlauf für mehrere Auslöser**, siehe unten.

Anlegen unter *Smart Home → Aktoren → Eigene Schalter & Knöpfe*: Name eingeben, Art wählen, **Anlegen**. Jeder Schalter/Knopf lässt sich mit Symbol versehen, sortieren und mit **PIN** schützen. Hinter dem **Stift ✎** liegen **Name**, **Auge** (Dashboard anzeigen) und **Papierkorb** (entfernen). Direkt in der Liste kannst du einen Schalter **ein-/ausschalten** bzw. einen Knopf **drücken** (▶), ohne zum Dashboard zu wechseln – mit PIN-Abfrage, falls gesetzt.

Was bei Druck passieren soll, baust du unter **Smart Home → Regeln** (Art „Ablauf“), z. B. der **Warmwasser-Timer**: Knopf drücken → Pumpe an → 60 Minuten warten → Pumpe aus.

**Beispiel Außenbeleuchtung mit mehreren Auslösern und gemeinsamer Nachlaufzeit** (Haustür, Kamera, Bewegungsmelder … schalten dieselben Lampen, die Zeit gilt für alle):
1. Einen **Nachlauf-Timer** „Hof-Licht“ anlegen (z. B. 3 Minuten).
2. Für **jeden Auslöser** eine Regel (Art „Ablauf“): WENN *Nacht* UND *Haustür offen* (bzw. *Kamera Person*, *Bewegungsmelder* …) → DANN **nur ein Schritt**: *Eigener Schalter: „Hof-Licht“ einschalten (Timer: starten / verlängern)*.
3. **Eine** Regel der Art **„Zustand halten“**: WENN *Eigener Schalter „Hof-Licht“ läuft* → DANN alle Lampen **einschalten**, **SONST** (= der Timer läuft nicht mehr) dieselben Lampen **ausschalten**. Ohne den SONST-Teil bleiben die Lampen an – „nur DANN an“ heißt „bleibt an“.
Jeder Auslöser startet die Zeit neu; die Lampen gehen erst aus, wenn **3 Minuten nach dem letzten Auslöser** vergangen sind. Auf dem Dashboard zeigt die Kachel die Restzeit; ein Tipp startet bzw. beendet den Timer von Hand.

---

## 7. Sensoren, Thermostate und Türschlösser

*Smart Home → Sensoren / Thermostate / Sicherheit.*

### Sensoren (nur lesen)

Von Homematic und Zigbee: Temperatur, Luftfeuchte, Fenster/Tür, Bewegung, Anwesenheit, Helligkeit, Leistung. Dazu die **Erkennung der Reolink-Kameras** (siehe unten). Pro Sensor einstellbar:

- **Name** und **Symbol**
- **Auf dem Dashboard zeigen** (eigener Schalter pro Sensor)
- **Invertieren:** Dreht Wahr/Falsch um. Beispiel: „geschlossen = wahr = grün“ statt „offen = wahr“.
- Reihenfolge per Ziehen.

Sensoren sind in Regeln als Bedingung nutzbar („WENN Sensor wahr/falsch“ bzw. „unter/über“ bei Messwerten). Ist ein Sensor nicht erreichbar, **passiert in der Regel nichts** (kein Fehlschalten).

**Eingänge und Tasten (Homematic):**

- **Eingang:** Funk-Sendemodule wie das HM-MOD-EM-8 (z. B. mit Lichtschranke oder Kontakt) erscheinen als Ja/Nein-Sensor **„Eingang“** (TRUE = aktiv).
- **Wandtaster / Fernbedienung:** Jede Taste liefert die Sensoren **„Taste kurz gedrückt“**, **„Taste lang gedrückt“** und – wenn der Taster es meldet – **„Taste lang losgelassen“**. Ein Tastendruck ist etwa **5 Sekunden lang TRUE** und löst so genau einen Ablauf aus. „Lang gedrückt“ gilt auch, wenn die CCU nur das Halten der Taste meldet (manche Taster senden kein eigenes „lang“).
- **Klingelsignalsensor (z. B. HmIP-DSD-PCB) und ähnliche Eingangsmodule:** Stellst du den Kanal in der CCU auf **Taster**, kommen nur Tastendrücke (siehe unten, nur mit Push). Stellst du ihn auf **Schalter/Kontakt**, bietet die Suche zusätzlich den Sensor **„Eingang“** an: er zeigt dauerhaft WAHR/FALSCH, braucht **keinen** Push und lässt sich auch in der Anzeige ablesen. Für „Klingel gedrückt → Gong“ ist der Kontakt-Modus der einfachere Weg.
- Tasten funktionieren **nur mit aktivem Homematic-Push**, denn ein Tastendruck ist ein Ereignis und lässt sich nicht abfragen. Ohne Push steht der Sensor auf „nicht lesbar“. Eine Umkehr-Option gibt es bei Tasten nicht.
- **Fehlersuche:** Unter *Smart Home → Sonstiges → Homematic: Push von der CCU* zeigt „Letzte Meldungen der CCU (zur Fehlersuche)“, was die CCU zuletzt gemeldet hat (Kanaladresse, Meldung, Wert). Taste drücken, **Aktualisieren** – so sieht man, ob und wie der Druck ankommt.

### Thermostate

Homematic und Zigbee. In Abläufen kann man die **Solltemperatur setzen**, z. B. „alle Thermostate auf 25 °C“. Der Einstellbereich ist **5 bis 30 °C** (kleinere oder größere Werte werden darauf begrenzt, auch in älteren Regeln); zusätzlich gilt der Bereich des Geräts.

### Türschlösser (Homematic IP und klassisches Keymatic)

Der Zustand (verriegelt/entriegelt) erscheint als Sensor. Zum **Verriegeln, Entriegeln und Öffnen** per Ablauf wird das Schloss unter „Türschlösser“ angelegt.

**Klassisches Keymatic (Funk, z. B. HM-Sec-Key-S):** Wird bei der Schlosssuche (*Smart Home → Sicherheit*) ebenfalls gefunden und genauso angelegt. Der Zustand erscheint in der Schlossliste; *Verriegeln* und *Entriegeln* schalten den Riegel, *Öffnen* löst den Türöffner aus (Falle zurückziehen). Die Freigaben und Schutzregeln sind dieselben wie bei Homematic IP.

> **Sicherheit:** *Entriegeln* und *Öffnen* sind erst erlaubt, wenn du das beim jeweiligen Schloss **ausdrücklich freigibst**. Sie funktionieren **nur in Abläufen** (nie in „Zustand halten“) und werden im **Trockenlauf nie ausgeführt**. *Verriegeln* ist immer erlaubt.

### Rollläden (Homematic)

*Smart Home → Aktoren (Karte „Rollläden“).* Homematic-Rollladenaktoren (z. B. HM-LC-Bl1PBU-FM, HmIP-BROLL), die eine **Position** kennen: **0 % = ganz zu, 100 % = ganz auf**.

- **Anlegen:** *Geräte suchen → Homematic → „Homematic-Rollläden suchen“*. Name und Symbol lassen sich schon in der Trefferliste ändern. Neu angelegte Rollläden sind zunächst nur für Administratoren sichtbar.
- **Bedienen:** **▲ Auf**, **■ Stopp**, **▼ Zu** oder der Regler (Position in 5-%-Schritten; beim Loslassen fährt der Rollladen dorthin). Die aktuelle Position steht daneben („ganz auf“, „ganz zu“, „45 % auf“; „Position unbekannt“, wenn der Aktor nicht erreichbar ist). Die Anzeige aktualisiert sich alle 15 Sekunden.
- **In Regeln:** Schritt **„Rollladen fahren / anhalten (Homematic)“** in Abläufen: Rollladen wählen, dann *fahren auf* **x %** oder *anhalten*. Im Trockenlauf wird nur „würde fahren“ protokolliert.
- **Verwalten:** Symbol, Umbenennen, Entfernen und die **Sichtbarkeit pro Benutzer** wie bei den Soundmodulen. Ein Rollladen lässt sich nicht entfernen, solange eine eingeschaltete Regel ihn braucht.

### Soundmodule (Homematic Gong, Signalaktor)

*Smart Home → Aktoren (Karte „Soundmodule“).* Homematic-Funk-Gongs und Signalgeber (z. B. HM-OU-CM-PCB, HM-OU-CFM-TW) spielen auf Befehl einen **Titel von ihrer Karte** ab.

- **Anlegen:** *Geräte suchen → Homematic → „Homematic-Soundmodule suchen“*. Name und Symbol lassen sich schon in der Trefferliste ändern, dann **Hinzufügen**.
- **Ausprobieren:** In der Karte Titelnummer und Lautstärke (in Prozent) eintragen und **▶** drücken. Die Eingaben bleiben beim Auffrischen der Seite erhalten.
- **In Regeln:** Schritt **„Sound abspielen (Homematic Gong)“** in Abläufen: Modul, Titel (1–255), Lautstärke, Wiederholungen. Gesendet wird intern `Lautstärke,Wiederholungen,108000,Titel` an den Tonkanal – der Titel wird vollständig abgespielt. Im Trockenlauf wird nichts abgespielt.
- **Verwalten:** Symbol, Umbenennen, Entfernen und die **Sichtbarkeit pro Benutzer** (neu angelegte Module sind zunächst nur für Administratoren sichtbar) gibt es nur für Administratoren. Wer kein Soundmodul sehen darf, sieht auch die Karte nicht.

---

## 8. PIN-Schutz

Jedes schaltbare Ding kann mit einer **4-stelligen PIN** geschützt werden: Geräte (Shelly, Tasmota, Tuya, Homematic, Zigbee), eigene Schalter/Knöpfe und Wake-on-LAN-Ziele.

- **Setzen/Ändern/Entfernen:** nur durch **Admins** (Recht „Benutzerverwaltung“ = Schreiben), in der Aktorenliste unter Smart Home (🔑). Das Auge-Symbol zeigt die Eingabe.
- **Benutzen:** Beim Tippen auf die Kachel erscheint ein Ziffernblock. Auch Admins geben die PIN ein.
- **Schutz gegen Raten:** Nach 5 falschen PIN-Eingaben ist das Gerät 5 Minuten gesperrt. Bei der **Anmeldung** gilt: nach 10 falschen Versuchen von derselben Adresse innerhalb von 5 Minuten ist diese Adresse 5 Minuten gesperrt.
- Die PIN wird nur als Hash gespeichert, nie im Klartext.
- **Regeln und Abläufe sind von der PIN nicht betroffen** – die PIN schützt nur das Schalten von Hand am Dashboard.

---

## 9. Automatik (Überschuss)

Menü **Einstellungen → Automatik** (rechts neben „VRM“; gehört zur Energiesteuerung, nicht zum Smart Home). Ist der Akku voll und wird eingespeist, schaltet die Steuerung die Geräte der Liste **nacheinander zu** (oberstes zuerst). Bei Netzbezug oder Akku-Entladung werden sie in **umgekehrter Reihenfolge** wieder abgeschaltet.

- **Überschuss-Automatik aktiv:** Hauptschalter.
- **Trockenlauf:** Nur protokollieren/melden, nichts schalten.
- **Geräte im Überschuss:** Geräte aus der Liste hinzufügen und per Ziehen sortieren.
- **Akku mindestens (%):** Ab diesem Ladestand gilt Überschuss als vorhanden (bei Ladelimit 90 % z. B. 88).
- **Feineinstellungen** (aufklappbar): Zeiten, Pause nach Handschaltung, Sicherheits-Timer. Beide stehen ab Werk auf **0** (Regeln laufen sofort, kein Eigentimer am Gerät); wer nach Handschaltung eine Pause oder einen Rückschalt-Timer will, trägt hier Minuten ein. „Alle auf Standard“ stellt die Voreinstellung wieder her.
- Änderungen gelten erst mit **Speichern** (Leiste unten).
- **Logbuch:** Zeigt, was die Automatik wann und warum geschaltet hat.

> **Wichtig:** Ein Gerät gehört **entweder** zur Überschuss-Automatik **oder** zu einer Regel, nicht zu beidem.

---

## 10. Regeln und Abläufe (Regel-Editor)

Menü **Smart Home → Regeln**. Hier verknüpfst du alles nach dem Schema

> **WENN** (Bedingung) → **DANN** (Aktionen) → **SONST** (Aktionen, optional)

Ähnlich wie Blockly in ioBroker, aber als Formular. Eine neue Regel braucht zuerst nur einen **Namen** und öffnet dann den Regel-Editor. Regeln lassen sich **benennen, kopieren** (als „Kopie <Name>“), ein-/ausschalten und löschen. Die Liste zeigt je Regel eine Zusammenfassung und den Status.

**Speichern:** In der Regelliste gilt alles sofort und ohne Speichern-Knopf – Gruppen anlegen/umbenennen/löschen, Umsortieren, Verschieben, Ein-/Ausschalten und Löschen. Wenn du dagegen eine Regel im **Regel-Editor** bearbeitest oder neu anlegst, übernimmst du die Änderungen am Ende bewusst mit **Speichern** (oder verwirfst sie).

Oben auf der Seite gibt es zwei Hauptschalter:

- **Regeln aktiv:** Hauptschalter für alle Regeln. Beim Ausschalten werden laufende Abläufe beendet.
- **Trockenlauf:** Nur protokollieren (und melden), was geschaltet würde.

### 10.1 Zwei Arten von Regeln

| Art | Verhalten | Typisches Beispiel |
|---|---|---|
| **Zustand halten** | Das Gerät **folgt der Bedingung**: Bedingung wahr → DANN, unwahr → SONST. | „Licht an, solange die Tür offen ist.“ |
| **Ablauf** | Startet **einmal**, wenn die Bedingung eintritt (steigende Flanke). Die Schritte laufen nacheinander, mit Warten. SONST läuft, wenn die Bedingung wieder wegfällt. | „Warmwasser-Timer“, „Morgens PC wecken“, „Thermostate auf 25 °C, nach 2 h zurück“. |

Der Editor stellt die Art automatisch auf „Ablauf“, sobald du einen Schritt wählst, den es nur im Ablauf gibt (Warten, Nachricht, Thermostat usw.).

**Zustands-Regeln:** Laufende Geräte werden übernommen. Von Hand ausgeschaltete bleiben aus, bis die Bedingung einmal nicht mehr stimmt. Bei Konflikten gewinnt **Ausschalten**.

### 10.2 Bedingungen (WENN)

Mehrere Bedingungen lassen sich mit **alle (UND)** oder **eine davon (ODER)** verknüpfen.

| Bedingung | Bedeutung |
|---|---|
| **Uhrzeit von–bis** | Zeitfenster, optional nur an bestimmten Wochentagen. |
| **Uhrzeit (einmal pro Tag)** | Löst zu einer festen Uhrzeit aus. |
| **Wochentag** | Wahr an den gewählten Wochentagen, jeweils für den **ganzen Kalendertag (0–24 Uhr)**. Zum Kombinieren mit anderen Bedingungen („alle müssen zutreffen“), z. B. *Tag* **und** *Mo–Fr*. Mindestens ein Tag muss gewählt sein. |
| **Sonnenaufgang / Sonnenuntergang** | Löst einmal pro Tag zum Sonnenaufgang bzw. -untergang aus, optional mit **Versatz** (z. B. 30 Min vor Sonnenuntergang) und nur an bestimmten Wochentagen. Die Zeiten werden aus dem **Standort** berechnet (Einstellungen → Wetter), ohne Internet; im Regel-Editor steht die Zeit von heute. Ohne Standort wartet die Regel. |
| **Nacht / Tag (Sonnenstand)** | Ein **Zustand** wie „Uhrzeit von–bis“, aber nach der Sonne: *Nacht* = ab Sonnenuntergang bis Sonnenaufgang, *Tag* = umgekehrt. Beginn und Ende lassen sich um Minuten verschieben. Damit geht „abends an, morgens aus“ in **einer** Regel (DANN einschalten, SONST ausschalten). |
| **Strompreis** | Preis über/unter einem Wert (nur bei dynamischem Tarif). |
| **Laufzeit pro Tag** | Das Gerät soll pro Tag x Minuten laufen, und zwar **zu den günstigsten Zeiten** innerhalb eines Zeitfensters (von–bis). Nur bei „Zustand halten“ und dynamischem Tarif. |
| **Akkustand** | SOC über/unter einem Wert. |
| **Sonne morgen (Prognose)** | PV-Prognose für morgen über/unter einem Wert. |
| **Sensor** | Homematic-/Zigbee-Sensor wahr/falsch bzw. Messwert unter/über. |
| **Meine Aktoren** | Einer deiner Aktoren (Geräte aus der Liste „Meine Aktoren“) ist an/aus, oder seine Leistung liegt über/unter einem Wert. |
| **Eigener Schalter / Knopf** | Schalter ist an/aus, oder Knopf wurde gedrückt. |
| **Regel (an/aus)** | Eine andere Regel ist ein- oder ausgeschaltet. Damit kann eine Regel auf den Zustand einer anderen reagieren, z. B. „Regel ‚Nachtruhe‘ ist aus → …“. Nur gespeicherte Regeln lassen sich wählen. |

Fehlt ein Messwert (Sensor/Gerät nicht erreichbar), **passiert nichts** – die Regel schaltet nicht „ins Blaue“.

### 10.3 Aktionen (DANN / SONST)

| Schritt | Wirkung | Nur im Ablauf? |
|---|---|---|
| **Gerät ein-/ausschalten** | Schaltet ein Gerät. | nein |
| **Gerät umschalten (an ↔ aus)** | Dreht den aktuellen Zustand um. | ja |
| **Warten** | Wartet x Sekunden/Minuten/Stunden (blockiert nichts anderes). | ja |
| **Thermostate: Solltemperatur setzen** (5 bis 30 °C) | Setzt ein oder mehrere Thermostate auf einen Wert. | ja |
| **Telegram-Nachricht senden** | Schickt einen freien Text aufs Handy (auch für Fehlersuche in Abläufen). | ja |
| **Telegram: Kamera-Standbild senden** | Holt ein aktuelles Standbild der gewählten Kamera und schickt es mit einem optionalen Text aufs Handy (ohne Text steht der Kameraname dabei). Im Trockenlauf wird nichts gesendet. Wird die Kamera gelöscht, verschwindet der Schritt aus den Regeln. | ja |
| **Telegram: Video zum Ereignis senden** | Schickt ein kurzes Video (10 Sekunden, 720p, ab 3 Sekunden vor dem Auslösen) aus der **Aufnahme auf der SD-Karte** der Kamera. Optional mit **Filter auf die Ereignisart** (Tier, Person, Fahrzeug, Bewegung): Nur wenn die Aufnahme eine gewählte Art enthält, wird das Video gesendet. Das Video kommt erst, wenn die Aufnahme fertig ist (meist 1 bis 2 Minuten, höchstens 4); dieselbe Aufnahme wird nie doppelt gesendet. Nur Telegram (Pushover kann kein Video). **Nur für Reolink-Kameras** (andere Kameras bieten diese Schnittstelle nicht; sie erscheinen im Schritt nicht zur Auswahl). Braucht SD-Karte mit eingeschalteter Aufnahme und **ffmpeg** auf dem Server. Im Trockenlauf wird nichts gesendet. | ja |
| **Eigenen Schalter setzen / Knopf drücken** | Verkettet Abläufe: ein Ablauf kann einen Schalter setzen, der einen anderen Ablauf startet. | ja |
| **Türschloss: öffnen / entriegeln / verriegeln** | Siehe Sicherheit in [Kapitel 7](#türschlösser-homematic-ip). | ja |
| **Adresse aufrufen (GET / POST)** | Ruft eine Internet-Adresse auf, z. B. einen **Webhook** (IFTTT, Home Assistant, ioBroker) oder ein Gerät mit HTTP-Schnittstelle (etwa einen Shelly-Befehl). Im Schritt Art (GET/POST), **Adresse** und eine **Bezeichnung** fürs Logbuch eintragen. Läuft im Hintergrund; das Ergebnis steht im Logbuch (ohne Adresse). **Trockenlauf:** ruft nie auf. Konten ohne Schreibrecht für Regeln sehen die Adresse nicht. | ja |
| **Chime läuten (Türklingel-Gong)** | Lässt alle verbundenen Chimes einer Reolink-Video-Türklingel mit dem gewählten Klingelton läuten (10 Töne), z. B. als Gong bei einem Ereignis. Die Lautstärke stellst du unter Kameras → ✎ → Chime ein. Nur Reolink-Türklingeln. | ja |
| **Regel ein-/ausschalten** | Schaltet eine **andere Regel** ein, aus oder um – als würdest du den Schalter in der Regelliste bedienen. Beispiel: Die Regel „Nachtruhe“ schaltet um 22 Uhr die Regel „Bewegungslicht“ aus und um 6 Uhr wieder ein. Der Zustand bleibt nach einem Neustart erhalten; in der Liste steht an der Regel „von Regel ‚Nachtruhe‘ ausgeschaltet“, bis du sie selbst umschaltest. Eine ausgeschaltete Ablauf-Regel startet erst wieder, wenn ihr Auslöser neu eintritt. Schaltet ein Schritt die eigene Regel aus, warnt der Editor. Trockenlauf: schaltet nie. | ja |
| **Sound abspielen (Homematic Gong)** | Spielt auf einem Homematic-Soundmodul (z. B. HM-OU-CM-PCB, HM-OU-CFM-TW) einen **Titel** ab: Titelnummer (1–255), Lautstärke in Prozent, Wiederholungen. Das Modul wird vorher unter *Smart Home → Geräte suchen → Homematic-Soundmodule suchen* angelegt und erscheint dann unter *Aktoren*, dort mit ▶ zum Ausprobieren. Im Trockenlauf wird nichts abgespielt. | ja |
| **Rollladen fahren / anhalten (Homematic)** | Fährt einen Rollladen auf eine Position (0 % zu … 100 % auf) oder hält ihn an. Siehe Kapitel 7 (Rollläden). | ja |
| **Rechner aufwecken (Wake-on-LAN)** | Sendet das Magic Packet. | ja |

**Löschschutz:** Geräte, Sensoren, Thermostate, Türschlösser, Soundmodule, Wake-on-LAN-Ziele, eigene Schalter/Knöpfe und Kameras lassen sich **nicht entfernen, solange eine eingeschaltete Regel sie verwendet** (als Bedingung oder Aktion). Ein Hinweis nennt die betroffenen Regeln; erst die Regel **ausschalten oder löschen**, dann geht das Entfernen. Ausgeschaltete Regeln blockieren nicht – beim Entfernen verlieren sie aber die betroffenen Schritte.

### 10.4 Optionen bei Abläufen

- **Laufenden Ablauf sofort beenden, wenn die Bedingung wegfällt** (z. B. Schalter wird wieder ausgeschaltet): bricht einen laufenden Timer ab. Bei vorhandenen SONST-Schritten passiert das immer, damit sie aufräumen können.
- **Gleich anwenden, wenn die Regel angelegt oder eingeschaltet wird:** Ein Ablauf startet normalerweise erst, wenn sich die Bedingung **ändert**. Legst du eine Regel mitten im Zeitfenster an (z. B. „01:30–05:00 Uhr“ um 02:00), passiert deshalb zunächst nichts. Mit dieser Option läuft das **DANN** (Bedingung erfüllt) bzw. das **SONST** (nicht erfüllt) sofort einmal, sobald die Regel angelegt oder eingeschaltet wird. Bei einem Neustart der App läuft es nicht noch einmal. Standard: aus.
- **Am Ende des Ablaufs den auslösenden Schalter wieder ausschalten** (Standard an): Wird ein eigener Schalter als Auslöser genutzt, springt er nach dem Durchlauf selbst zurück auf „aus“ und ist wieder bereit. Danach läuft das SONST.
- **Sperrzeit nach dem Auslösen** (oben im Regel-Editor, in Sekunden, 0 = keine): Löst der Auslöser nach dem Start nochmal aus – z. B. weil jemand in einer Lichtschranke hin und her läuft –, wird das innerhalb dieser Zeit ignoriert (Logbuch: „Auslöser ignoriert“). Ein laufender Ablauf wird dadurch nicht ersetzt.
- Bei Abläufen mit **Tasten** als Auslöser ist „Laufenden Ablauf sofort beenden …“ bei neuen Regeln **aus**: Ein Tastendruck ist nur kurz TRUE, sonst würde sich z. B. ein Timer nach 5 Sekunden selbst abbrechen. Bei älteren Regeln mit Taste und Warten das Häkchen selbst ausschalten.
- Läuft ein Ablauf, zeigt die Kachel auf dem Dashboard die **Restzeit**.
- Laufende Abläufe überstehen einen **Neustart** der App (sie werden fortgesetzt).
- Im **Trockenlauf** werden Wartezeiten übersprungen und nichts wirklich geschaltet; alles steht im Logbuch.

### 10.5 Reaktionszeit

Regeln werden zyklisch ausgewertet und bei Änderungen sofort angestoßen. Mit aktivem **Homematic-Push** reagieren Sensor-Regeln in unter einer Sekunde. Zigbee wird alle ~1 s abgefragt (Cache).

---

### 10.6 Regeln in Gruppen ordnen

Bei vielen Regeln lassen sich diese in **eigene Gruppen** sortieren, z. B. „Timer“, „Licht“ oder „Garten“. Die Namen wählst du **frei**; vorgegeben ist nichts.

- **Gruppe anlegen:** Am schnellsten über das **📁** in einer Regelzeile („＋ Neue Gruppe …“). Außerdem beim **Anlegen einer neuen Regel** (Auswahl „Gruppe“ neben dem Namen) und im **Regel-Editor** (Auswahl „Gruppe“).
- **Regeln zuordnen:** In der Regelzeile mit **📁** („In eine Gruppe verschieben“) oder im Regel-Editor über die Auswahl „Gruppe“. So lassen sich auch bereits vorhandene Regeln nachträglich einsortieren.
- **Gruppenknöpfe:** Unter „Deine Regeln“ steht jede Gruppe als Knopf mit Namen, Anzahl der Regeln und wie viele davon an sind. Ein Klick **klappt die Liste der Gruppe auf oder zu**; welche Gruppen offen sind, merkt sich der Browser. Regeln ohne Gruppe stehen unten bei „Ohne Gruppe“. Gibt es keine Gruppe, bleibt die Liste wie gewohnt.
- **Sortieren:** Gruppen lassen sich mit **langem Drücken und Ziehen** verschieben, ebenso die Regeln innerhalb einer Gruppe.
- **Umbenennen und Löschen:** Mit ✎ und ✕ an der Gruppe. Beim Löschen bleiben die Regeln erhalten und landen bei „Ohne Gruppe“.
- Wie bei allen Änderungen auf dieser Seite gilt alles erst nach **Speichern** (Leiste unten). Die Gruppen gehören zur Sicherung (Kapitel 15).
- Die Gruppe ist nur eine Ordnung für die Liste und ändert nichts an der Wirkung einer Regel.

## 11. Wake-on-LAN

Weckt einen PC, ein NAS oder einen Server aus dem Standby/Ruhezustand per „Magic Packet“.

**Einrichten:** Reiter *Smart Home → Wake-on-LAN* (immer verfügbar, kein Häkchen nötig) → Name, **MAC-Adresse** (Windows: `ipconfig /all`, „Physische Adresse“; Linux: `ip link`) und optional **IP-Adresse** (für die Anzeige „erreichbar“ per Ping) sowie **Broadcast-Adresse** (nur bei anderem Netz) eintragen → **Anlegen**.

**Voraussetzungen:**

- Am Rechner ist Wake-on-LAN im **BIOS** und im **Netzwerktreiber** aktiviert (unter Windows: „Magic Packet zum Aufwecken“, ggf. Schnellstart aus).
- Der Server steht im **selben Netz** (Broadcast).

**Benutzen:**

- Am Dashboard: Kachel mit **Aufwecken**-Knopf (optional mit PIN). Mit IP zeigt die Kachel, ob der Rechner gerade erreichbar ist.
- In Regeln (Art „Ablauf“): Schritt **Rechner aufwecken**, z. B. werktags um 07:00.
- Im Trockenlauf wird **kein Paket gesendet**, nur protokolliert.

---

## 11a. Alexa (Sprachsteuerung)

*Einstellungen → System → Module → „Alexa“ einschalten, dann Smart Home → Alexa.* Die App gibt sich im Heimnetz als **Philips-Hue-Bridge** aus. Echo-Geräte finden sie ohne Cloud und ohne Amazon-Entwicklerkonto. Jedes freigegebene Gerät erscheint in der Alexa-App als **Lampe** oder als **Steckdose** (je Gerät wählbar) und lässt sich per Sprache **ein- und ausschalten**: „Alexa, schalte Flurlicht ein“.

**Einrichten**

1. Modul „Alexa“ einschalten (setzt Smart Home voraus). Unter *Smart Home → Alexa* steht dann, ob die Bridge läuft.
2. **Gerät freigeben:** Gerät oder eigenen Schalter/Knopf wählen, den **Namen für Alexa** festlegen (so wird er gesprochen), Art *Lampe* oder *Steckdose*, **Freigeben**. Freigeben darf nur ein Administrator.
3. Alexa suchen lassen: **„Alexa, suche meine Geräte“** oder in der Alexa-App *Geräte → + → Gerät hinzufügen → Licht → Philips Hue*. Fragt Alexa nach dem Link-Knopf der Bridge: bestätigen – die App akzeptiert immer.
4. In der Alexa-App Raum und Name prüfen. Die Art (Lampe/Steckdose) lässt sich dort bei Bedarf ändern.

**Gut zu wissen**

- **Eigene Schalter** sind ideal: „Alexa, schalte den Warmwasser-Timer ein“ setzt den Schalter, der wiederum eine **Regel** auslöst. Ein **Knopf** wird beim „Einschalten“ gedrückt, „Ausschalten“ tut nichts.
- **Sicherheit:** Geräte und Schalter **mit PIN** sind nie freigebbar. Bekommt ein freigegebenes Gerät später eine PIN, schaltet Alexa es nicht mehr. Türschlösser gibt es für Alexa nicht. Sprache umgeht so nie die PIN.
- **Nur Ein/Aus:** Dimmen und Farben werden nicht unterstützt. Ein Dimm-Befehl schaltet das Gerät ein.
- **Wie von Hand geschaltet:** Ein Sprachbefehl pausiert Regeln und Überschuss-Automatik für dieses Gerät (wie ein Tipp auf den Schalter). Alles steht im Logbuch („Alexa: …“).
- **Voraussetzungen:** Echo und Server im **selben Netz** (kein getrenntes VLAN, Multicast muss durchgehen). Die Bridge nutzt **Port 80** – er muss auf dem Server **frei** sein. Läuft dort schon ein Webserver (Apache, nginx), zeigt die Karte eine Meldung, und die App läuft normal weiter; den Webserver beenden (`systemctl stop apache2 && systemctl disable apache2`) und die App neu starten. Auch unter Proxmox/LXC muss die App als root laufen, damit sie Port 80 öffnen darf.
- **Technik, falls du Probleme suchst:** Die Bridge meldet sich Alexa gegenüber als **ältere Hue-Bridge (API 1.17)**, so wie Tasmota-Geräte – neuere Versionen verleiten Echo-Geräte zum HTTPS-Weg, den die App nicht anbietet. In der Karte „Alexa“ zeigt **Fehlersuche: letzte Anfragen von Alexa**, ob und wie Alexa bei einer Suche mit der Bridge spricht (SSDP = Suche im Netz, HTTP = Gespräch mit der Bridge).
- **Ändert sich ein Name oder eine Art**, in der Alexa-App die Geräte neu suchen lassen. Wird ein Gerät gelöscht, entfällt seine Freigabe automatisch.
- Funktioniert die Suche nicht: Läuft die Bridge (grüner Punkt), stimmt das Netz? Ein Echo mit Zigbee-Hub (z. B. Echo 4. Generation) findet Hue-Geräte in der Regel; Amazon ändert die lokale Anbindung gelegentlich – bei Problemen bitte melden.

---

## 11b. Klimaanlage (Midea / NetHome Plus)

Klimaanlagen, die du mit der App **NetHome Plus** bedienst (auch Comfee, Inventor, Pioneer u. a. mit Midea-Technik), lassen sich **lokal** steuern. Sie sind Geräte der normalen Geräteliste: Ein/Aus, Rechte, Sichtbarkeit, PIN, Dashboard, Regeln und Alexa funktionieren wie bei den anderen. Dazu kommen Modus, Solltemperatur, Lüfter und Schwenken.

**Voraussetzung:** Auf dem Server muss die Bibliothek **msmart-ng** installiert sein (steht in `requirements.txt`; nach dem Update einmal `venv/bin/pip install -r app/requirements.txt`, dann die App neu starten). Die Klimaanlage ist im selben WLAN/Netz wie der Server.

- **Anlegen:** *Smart Home → Geräte suchen*: unter „Welche Systeme hast du?“ **Klimaanlage (Midea / NetHome Plus)** ankreuzen, **Region** wählen (für Deutschland **DE**) und **Klimaanlagen suchen**. Die Treffer erscheinen mit IP und Protokoll; Name und Symbol änderst du vor dem **Hinzufügen**. Wird nichts gefunden, trägst du die **IP der Klimaanlage** ein (in der Router-Liste oder in NetHome Plus unter Geräteinfo zu sehen). Beim Anlegen holt die App **einmalig** den Schlüssel (Token) der Klimaanlage aus der NetHome-Plus-Cloud (mit dem Standardzugang der Bibliothek). Klappt das nicht, hilft unter „Eigenes NetHome-Plus-Konto“ die Eingabe deines Kontos – es wird **nur für diese Suche** gebraucht und **nicht gespeichert**. Danach läuft alles lokal ohne Cloud; Token und Schlüssel liegen nur auf dem Server und werden nie an den Browser geschickt.
- **Bedienen:** In der Geräteliste (Reiter Aktoren) zeigt die Zeile den Zustand („an · Kühlen · Soll 24 °C · innen 26,5 °C · außen 18 °C“). **❄ Klima** öffnet das Bedienfeld: **Modus** (Automatik, Kühlen, Entfeuchten, Heizen, Lüften …), **Solltemperatur** (− / + in halben Grad), **Lüfter**, **Schwenken**, bei manchen Geräten **Eco**. Änderungen gelten sofort. Ein-/Ausschalten wie bei jedem Gerät mit dem Schalter in der Zeile.
- **In Regeln:** Schritt **„Klimaanlage einstellen (Midea)“** in Abläufen: Ein/Aus, Modus, Solltemperatur und Lüfter – nur die ausgefüllten Felder werden gesetzt, der Rest bleibt wie er ist. Beispiel: *bei Sonnenüberschuss → Kühlen, 23 °C*. Mit „Ein/Aus“ plus dem normalen Schritt „Gerät ein-/ausschalten“ lässt sich die Klimaanlage auch in „Zustand halten“-Regeln schalten.
- **Verläufe:** Für jede Klimaanlage lassen sich **Innen-, Außen- und Solltemperatur** und der **an/aus-Zustand** aufzeichnen (Menü Verläufe).
- **Hinweise:** Das WLAN-Modul der Klimaanlage verträgt wenig Abfragen: Zustände werden 20 Sekunden zwischengespeichert, bei Nichterreichbarkeit versucht die App es erst nach 30 Sekunden wieder. Die erste Antwort kann einige Sekunden dauern. Gleichzeitig verbindet sich die Klimaanlage nur mit **einem** Programm: ist die NetHome-Plus-App am Handy gerade aktiv im WLAN verbunden, kann es kurz haken. Ein Rückschalt-Timer (Sicherheits-Timer) wird bei Klimaanlagen nicht benutzt.
- **Cloud-Weg (wenn kein lokaler Schlüssel zu bekommen ist):** Midea gibt den lokalen Schlüssel teils nicht mehr heraus (Meldung „Code 9999 system error“). Dann trägst du unter „Eigenes NetHome-Plus-Konto“ **E-Mail und Passwort aus der NetHome-Plus-App** ein und drückst **Klimaanlagen suchen**: Die App listet die Anlagen deines Kontos (Anzeige „Cloud“ statt IP) und steuert sie **über die Midea-Cloud** (Bibliothek `midea-beautiful-air`, ebenfalls in `requirements.txt`). Bedienung, Regeln und Verläufe sind gleich, nur etwas langsamer (Zustand wird 45 Sekunden zwischengespeichert) und mit Internet. **Das Konto wird in diesem Fall auf dem Server gespeichert** (in der Geräteliste der Anlage, nie im Browser sichtbar). Ändert sich dein Passwort, die Anlage entfernen und neu anlegen. Die Region (DE/US/KR) spielt beim Cloud-Weg keine Rolle. Solltemperatur 16–31 °C.
- **Fehlersuche:** „Anmeldung fehlgeschlagen“ → Klimaanlage in der Geräteliste entfernen und neu suchen/anlegen (neuer Token). „Zeitüberschreitung“ → WLAN und IP prüfen (feste IP im Router vergeben). „msmart-ng ist nicht installiert“ → Installation siehe Voraussetzung.

---

## 12. Logbuch, Betriebsbericht, Solarlogbuch, Watchdog

| Seite | Wo | Inhalt |
|---|---|---|
| **Logbuch** (Automatik/Regeln) | Buttons „📒 Logbuch“ auf Automatik und Regeln | Was wann und warum geschaltet wurde, auch Trockenlauf-Einträge und Fehler. Ungelesene Einträge zeigen ein Abzeichen. |
| **Betriebsbericht** | Einstellungen → Meldungen | Ein Blick genügt: läuft die Regelung, sind Prognose, Preise und Daten vollständig? Dazu Tagestabelle, Ereignisprotokoll und Betriebsstatistik (Ø/maximale Dauer eines Regeldurchlaufs, größte Lücke). Mit einem Klick als Text kopierbar, um die Anlage gemeinsam mit Claude auszuwerten. |
| **Solarlogbuch** | Einstellungen → PV-Prognose | VRM-Prognose gegen realen Ertrag der letzten Tage, Abweichung und der Korrekturfaktor, der den Tag getroffen hätte. |
| **Batterie-Watchdog** | Einstellungen | Erkennt und protokolliert, wenn die Batterie trotz Netzfluss über 15 Minuten nicht reagiert (Multiplus-Ladehänger). **Kein Alarm bei leerem Akku:** Steht der Akku am Mindest-SOC (minus/plus 2 %), liefert er bewusst nichts und das Haus läuft am Netz – das ist normal. Zeigt auch Vollzyklen und Lebensdauer-Hochrechnung. |

---

## 13. Benachrichtigungen (Telegram)

Die App meldet sich aufs Handy, wenn etwas nicht stimmt – und wenn es wieder in Ordnung ist. Gemeldet wird nur bei einem **Wechsel**, nicht bei jedem Durchlauf. Jede Meldung beginnt mit dem Namen der Anlage.

**Einrichten (einmalig, ca. 2 Minuten):**

1. In Telegram **@BotFather** öffnen → `/newbot` → Namen vergeben → **Token** kopieren und eintragen.
2. Den neuen Bot öffnen und ihm irgendeine Nachricht schreiben (für eine Gruppe: Bot hinzufügen und dort schreiben).
3. Hier **„Chat-ID ermitteln“** klicken und den Treffer anklicken, dann **Speichern** und **Test senden**.

**Einstellbar:** Welche Ereignisse gemeldet werden, „Akku niedrig unter (%)“ und die Uhrzeit der **Tages-Zusammenfassung** (Tagesbilanz plus Systemcheck, mit Kurzfassung des Betriebsberichts).

**Anlagenname:** Standardmäßig steht vor jeder Nachricht der Anlagenname in eckigen Klammern (z. B. „[Michas BlueNexus] …“). Mit dem Schalter **„Anlagenname vor jede Nachricht setzen“** lässt sich das abschalten, dann kommt die Nachricht ohne Vorspann.

Telegram kann zusätzlich in **Abläufen** als Schritt „Telegram-Nachricht senden“ genutzt werden.

**Mehrere Empfänger an einem Bot:** Unter *Einstellungen → Meldungen → Empfänger* können mehrere Personen denselben Bot nutzen (z. B. du und Anna). Die Person öffnet den Bot in Telegram und schreibt ihm einmal „Hallo“; dann klickst du **„+ Empfänger hinzufügen“**, wählst ihren Chat und vergibst einen Namen. Unter dem **✎** jedes Empfängers änderst du den Namen, schaltest **Systemmeldungen** (Fehler, Tagesbilanz …) für ihn ein oder aus oder entfernst ihn; **▶** schickt eine Testnachricht nur an ihn. Der erste Empfänger ist die Chat-ID oben und bekommt immer die Systemmeldungen.
In **Regeln** erscheint bei den Schritten „Telegram-Nachricht senden“ und „Kamera-Standbild senden“ (sobald es mehr als einen Empfänger gibt) die Zeile **„Senden an“** mit einem Häkchen je Person. Ohne Auswahl gehen Meldungen nur an die Empfänger mit „Systemmeldungen“. **Ein Foto wird nur einmal aufgenommen** und an alle Gewählten geschickt – die Kamera muss also nicht mehrfach auslösen. Beispiel: eine Regel „Lichtschranke Hof → zwei Fotos“ schickt beide Bilder an dich **und** Anna, ohne dass Anna die Regel, die CCU oder die Kameras selbst einrichten muss. Wer einen eigenen Bot hat (z. B. Annas App), bleibt davon unberührt: jede App hat ihren Bot und ihre Empfänger.

---

### Pushover (zweiter Meldeweg)

Neben Telegram kann die App über **Pushover** melden – mit **Priorität**, **eigenem Ton** und einem **Kamerabild als Anhang**. Pushover kostet nach der Testzeit einmalig ca. 5 $ je Plattform (Android/iOS); jede Person braucht ein eigenes Pushover-Konto samt App.

**Einrichten** (*Einstellungen → Meldungen → Pushover*): Auf pushover.net eine Anwendung anlegen („Create an Application/API Token“) und den **App-Token** hier eintragen. Dann je Person den **Benutzer-Schlüssel (User Key)** mit einem Namen eintragen – die App prüft ihn bei Pushover. Der erste Empfänger bekommt die Systemmeldungen; unter dem **✎** jedes Empfängers änderst du Name und **Systemmeldungen** oder entfernst ihn, **▶** schickt eine Testnachricht nur an ihn.

**Nur ein bestimmtes Handy:** Im Feld **Gerät** steht der Name des Handys wie in Pushover unter „Your Devices“ (z. B. `GalaxyS22`). Leer = Nachricht an **alle** Geräte des Kontos. Zwei Handys im selben Konto sprichst du getrennt an, indem du zwei Empfänger mit **demselben Schlüssel, aber verschiedenem Gerät** anlegst (z. B. „Ina (S22)“ und „Michael (S25)“). In Regeln wählst du dann, wer die Nachricht bekommt.

**In Regeln:** Neuer Schritt **„Pushover-Nachricht senden“** (erscheint nur, wenn Pushover eingerichtet ist): Text, Titel (optional), **Priorität** (leise, normal, hoch = durchbricht Ruhezeiten, **Notfall** = wiederholt jede Minute bis zu 30 Minuten, bis du bestätigst), **Ton**, optional **Bild** einer Kamera (wird einmal aufgenommen und an alle Gewählten geschickt) und – ab zwei Empfängern – **„Senden an“**. Ohne Auswahl gehen Nachrichten an die Empfänger mit „Systemmeldungen“. Ist die Kamera nicht erreichbar, geht der Text auch ohne Bild raus (nach einem zweiten Versuch). Pushover und Telegram sind getrennte Schritte; ein Telegram-Schritt schickt nichts über Pushover.

**Systemmeldungen** (Fehler, Tagesbilanz …) gehen an Telegram **und** an die Pushover-Systemempfänger – wer nur Pushover eingerichtet hat, bekommt sie dort. Im Betriebsbericht erscheint „Meldungen: Telegram + Pushover eingerichtet“.

**Löschen:** *Pushover-Zugang löschen* entfernt App-Token und alle Empfänger.

### Zugangsdaten löschen (widerrufen)

Jeder gespeicherte Zugang lässt sich mit einem roten Knopf **löschen** – immer mit Rückfrage, nur mit Schreibrecht auf den jeweiligen Bereich:

| Zugang | Wo | Was passiert |
|---|---|---|
| **CCU (Homematic)** | Smart Home → Geräte suchen → Homematic → **Zugang löschen** | Die App meldet sich bei der CCU ab (Push), Adresse/Benutzer/Passwort sind weg, die CCU wird nicht mehr angesprochen. Angelegte Homematic-Geräte bleiben in den Listen („nicht erreichbar“), bis du sie entfernst oder wieder einen Zugang einträgst. |
| **Tuya-Cloud** | Geräte suchen → Tuya → **Zugang löschen** | Access ID/Secret werden gelöscht; angelegte Tuya-Geräte laufen lokal weiter. |
| **Telegram** | Einstellungen → Meldungen → **Telegram-Zugang löschen** | Bot-Token, Chat-ID und alle Empfänger sind weg; es gehen keine Nachrichten mehr raus. |
| **Pushover** | Einstellungen → Meldungen → **Pushover-Zugang löschen** | App-Token und alle Pushover-Empfänger sind weg. |
| **VRM** | Einstellungen → PV-Prognose → **Zugang löschen** | Installations-ID und Token sind weg; keine Prognose mehr. |
| **Tibber** | Einstellungen → Tarif → **Token löschen** | Keine Preise mehr, bis ein Token eingetragen oder auf festen Tarif umgestellt wird. |
| **Zigbee-Gateway** | Geräte suchen → Zigbee → Gateway entfernen | Der API-Schlüssel des Gateways wird mit entfernt. |
| **Klimaanlage (Cloud-Weg)** | Gerät in der Rubrik Klimaanlagen entfernen | Das NetHome-Plus-Konto steht nur im Geräteeintrag und verschwindet mit ihm. |

**Wichtig:** Das **Abwählen eines Systems** („Welche Smart-Home-Systeme hast du?“) blendet nur Bereiche aus. Gespeicherte Zugänge und angelegte Geräte bleiben bestehen und arbeiten weiter. Wer ein System wirklich nicht mehr nutzen will, löscht seinen Zugang wie oben.

---

## 13b. Fernzugriff von unterwegs (Cloudflare Tunnel)

Mit einem **Cloudflare Tunnel** erreichst du die Steuerung auch von außen – **ohne einen Port im Router freizugeben**. Die App baut selbst eine gesicherte Verbindung zu Cloudflare auf (Programm `cloudflared`), und du rufst sie über eine Adresse wie `https://steuerung.deine-domain.de` auf. Gedacht für den Raspberry Pi oder jeden Linux-Server, auf dem die App läuft. Wer schon einen Tunnel anderswo betreibt (z. B. auf einem NAS), braucht das nicht.

**Was du brauchst:** ein kostenloses **Cloudflare-Konto** und eine **Domain**, die bei Cloudflare verwaltet wird (Nameserver auf Cloudflare umstellen). Der Raspberry Pi braucht nur Internet.

**Einrichten** (*Einstellungen → System → Fernzugriff*):
1. Bei Cloudflare im Zero-Trust-Dashboard ([one.dash.cloudflare.com](https://one.dash.cloudflare.com), Konto gibt es unter [cloudflare.com](https://dash.cloudflare.com/sign-up)) unter **Networks → Connectors → Tunnel erstellen → Cloudflared** einen Tunnel anlegen (Name frei).
2. Den angezeigten **Token** (langer Text, beginnt mit `eyJ`) kopieren, in der App einfügen und **Token speichern**. Auch der ganze Befehl `cloudflared service install …` darf eingefügt werden, die App schneidet den Token heraus. Den Installationsschritt bei Cloudflare überspringst du ([Anleitung von Cloudflare](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)).
3. Im Tunnel unter **Public Hostname** eine Adresse anlegen (z. B. `steuerung.deine-domain.de`), Dienst **HTTP**, Ziel `localhost:<Port der App>` (steht in der Anleitung der Karte).
4. In der App **„cloudflared installieren“** drücken (lädt das offizielle Programm von Cloudflare für Raspberry Pi 32/64 Bit bzw. x86 nach `app/bin/`), dann **Fernzugriff einschalten**. Nach kurzer Zeit steht dort **„Verbunden“**.
5. **Sicherheit (wichtig):** Bei Cloudflare unter **Zero Trust → Access → Applications → Self-hosted** eine Anwendung für deine Adresse anlegen und die Anmeldung per **E-Mail-Code** auf deine Adressen beschränken (kostenlos bis 50 Personen; [Anleitung von Cloudflare](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)). Erst dann ist die Steuerung wirklich abgesichert; die App-Anmeldung kommt als zweite Hürde dazu.

**Eigene Domain für den Fernzugriff** (z. B. `meinname.example.de`, die Hauptadresse bleibt dann frei für eine Projektseite):
1. Die Domain beim Anbieter registrieren. **Eine Übertragung zu Cloudflare ist nicht nötig**, die Domain bleibt beim Anbieter.
2. Bei Cloudflare **Domain hinzufügen** (kostenloser Tarif). Cloudflare liest vorhandene DNS-Einträge ein: Einträge des Anbieters zu seiner Startseite (A-Eintrag, `*`- und `www`-CNAME) **löschen**, Mail-Einträge (MX/SPF) nur behalten, wenn du Mail über den Anbieter nutzt.
3. Cloudflare nennt **zwei Nameserver** (`…ns.cloudflare.com`). Beim Domain-Anbieter die Nameserver darauf umstellen (bei All-Inkl: KAS → Domainverwaltung → Domain → Nameserver). **DNSSEC** dort vorher ausschalten. Danach wenige Minuten bis einige Stunden warten, bis Cloudflare „aktiv“ meldet.
4. Im Tunnel unter **Public Hostname** die neue Adresse hinzufügen (Subdomain, Domain, Dienst **HTTP**, Ziel `localhost:<Port der App>`). Ein bestehender Tunnel kann **mehrere Adressen** bedienen, die alte darf zunächst bleiben.
5. **NFC-Umzug:** Die Kennzeichen der Handys und die installierte App gelten nur für **eine** Adresse. Nach dem Wechsel: *NFC-Tags → Adresse für die Tags* ändern, Handys neu registrieren, App neu installieren, Tags neu beschreiben, danach die alte Adresse aus dem Tunnel entfernen.
6. **Fehlerbild „Zertifikat passt nicht“ nur im Heimnetz:** Ein lokaler DNS-Server (z. B. AdGuard Home oder der Router) kann die alte Antwort noch zwischenspeichern. Über Mobilfunk testen: Klappt es dort, ist alles richtig. Dann den DNS-Cache leeren oder kurz einen anderen Upstream (z. B. `1.1.1.1`) verwenden; sonst vergisst der Server die alte Antwort nach spätestens einem Tag. Am PC zusätzlich `ipconfig /flushdns` und im Browser den Host-Cache leeren.
7. **Mehrere Installationen unter einer Domain:** Jede Installation bekommt ihre eigene Unteradresse (`name.deinedomain.de`) und ihren eigenen Tunnel samt Token, den der Besitzer in seiner App einträgt. Der Betreiber der Domain ist dann auch für diese Adressen verantwortlich.

**Verhalten:** Der Schalter gilt auch nach einem Neustart der App oder des Pi (Autostart). Fällt `cloudflared` aus, startet die App es mit steigender Wartezeit neu. Unter **Protokoll von cloudflared** siehst du die letzten Zeilen (der Token wird darin immer unkenntlich gemacht). Der Token liegt nur auf dem Server (Datei `cloudflare_tunnel.json`, nicht im Repo) und wird `cloudflared` über eine Umgebungsvariable übergeben, er steht also nicht in der Prozessliste. **Token löschen** stoppt den Tunnel und entfernt den Token; den Tunnel selbst löschst du bei Cloudflare.

**Was die App selbst zur Sicherheit tut** (unabhängig von Cloudflare): Passwort-Raten wird gebremst; Benutzernamen dürfen nur Buchstaben, Ziffern, Leerzeichen und `. _ @ -` enthalten; die Anmeldung braucht für ein unbekanntes Konto gleich lange wie für ein bekanntes (niemand kann so erraten, welche Namen es gibt); nach der Anmeldung führt nur ein Pfad **auf dieser Seite** weiter (keine Weiterleitung auf fremde Adressen); ändernde Anfragen, die eine **fremde Webseite** auslöst, werden abgewiesen; Schutzkopfzeilen (kein Einbetten in fremde Seiten, kein Raten des Dateityps, HSTS über HTTPS); Anfragen sind auf 4 MB begrenzt; Dateien mit Zugangsdaten sind nur für den Besitzer lesbar. Die wichtigste zusätzliche Hürde bleibt **Cloudflare Access** vor der Adresse.

**Hinweise:** Nur Administratoren mit dem Recht „Einstellungen: System“ sehen und ändern die Karte. Über den Tunnel (HTTPS) markiert die App das Anmelde-Cookie automatisch als **„Secure“**: Der Browser sendet es dann nur noch verschlüsselt. Im Heimnetz über `http://` bleibt es ohne dieses Merkmal, damit die Anmeldung dort weiter funktioniert. Die App bremst Passwort-Raten an der Anmeldung (10 Versuche in 5 Minuten je Adresse; hinter dem Tunnel gilt die echte Besucher-Adresse von Cloudflare). Auf Windows wird `cloudflared` nicht automatisch installiert – dort das Programm von Hand installieren und im PATH ablegen.

---

## 13c. NFC-Tags (Handy scannen, Knopf auslösen)

*Smart Home → NFC-Tags* (Recht „Smart Home: NFC-Tags“; Lesen zeigt alles außer den Adressen, Schreiben verwaltet). Ein NFC-Tag trägt eine Internet-Adresse. Hältst du ein **registriertes Handy** daran, öffnet es die Adresse von selbst (auch bei geschlossener App, der Bildschirm muss entsperrt sein), und die Zentrale **drückt einen eigenen Knopf** bzw. schaltet einen eigenen Schalter oder startet einen Timer. Was daraus folgt (Licht, Video, Nachricht …), legst du wie immer in **Regeln** fest (WENN Knopf gedrückt).

**Geeignete Tags:** NFC-Tags (NTAG/MIFARE, 13,56 MHz), z. B. Aufkleber oder Schlüsselanhänger. Ältere 125-kHz-RFID-Tags (Türschloss-Chips, viele Arduino-Sets) kann ein Handy nicht lesen. Ob ein Tag taugt, zeigt die kostenlose App „NFC Tools“.

**Einrichten**
1. **Adresse eintragen:** Die Adresse deines Fernzugriffs (z. B. `https://nexus.deine-domain.de`). Sie funktioniert zu Hause und unterwegs. Das Kennzeichen eines Handys gilt immer nur für genau diese Adresse.
2. **Handys registrieren:** *Dieses Gerät registrieren* (am Handy selbst, in der App angemeldet) oder *Link für ein anderes Handy* (ein Einmal-Link, 15 Minuten gültig: auf dem anderen Handy öffnen und die Rückfrage mit **Jetzt registrieren** bestätigen; am besten im **Standardbrowser**). Das Handy bekommt ein langes zufälliges Kennzeichen im Browser, rund 10 Jahre gültig.
3. **Tag anlegen:** Name eingeben – die App legt dazu **immer einen eigenen Knopf** mit dem Namen des Tags an (Symbol 🏷️, **fest und nicht änderbar**, damit man NFC-Knöpfe in den Listen sofort erkennt). Beim Scannen wird dieser Knopf gedrückt; was daraus folgt, bestimmt die Regel. Der Knopf **Adresse** am Tag kopiert die Adresse **ohne `https://`** in die Zwischenablage – die meisten NFC-Apps (z. B. „NFC Tools“) setzen das Protokoll selbst davor. Dieselbe Adresse kannst du auf **beliebig viele Aufkleber** schreiben und in der Wohnung verteilen; einen zweiten Tag legst du nur an, wenn er für andere Handys freigegeben sein oder getrennt im Logbuch erscheinen soll. Mit **📋 Adresse** kopierst du die Adresse und schreibst sie mit „NFC Tools“ (*Schreiben → Datensatz hinzufügen → URL*) auf den Tag.
4. **Regel bauen:** WENN „Eigener Knopf“ wird gedrückt → DANN beliebige Aktionen.

**Sicherheit**
- Ausgelöst wird **nur von registrierten Handys**. Ein kopierter, fotografierter oder nachgebauter Tag nützt niemandem.
- **Handys löschen:** Mit dem Papierkorb in der Liste ist ein Handy sofort gesperrt (verlorenes Handy). Mit dem Papierkorb am **Tag** löschst du den Tag **zusammen mit seinem Knopf** (nicht, solange eine Regel den Knopf noch verwendet – erst die Regel löschen oder ausschalten). Unter „Eigene Schalter & Knöpfe“ gibt es für NFC-Knöpfe deshalb keinen Papierkorb; NFC-Tags legst und löschst du nur im Reiter NFC-Tags an. Mit ✎ am Tag änderst du den **Namen** (der zugehörige Knopf unter „Eigene Schalter & Knöpfe“ wird mit umbenannt; dort selbst lässt er sich nicht ändern) und legst fest, **welche Handys diesen Tag nutzen dürfen** (Standard: alle registrierten).
- **PIN-geschützte Knöpfe:** Hat der Knopf eines Tags eine PIN (Stift/Schloss am Knopf), fragt das Handy nach dem Scannen die **PIN** ab (Seite mit Ziffernfeld). Erst Handy **und** PIN zusammen lösen aus. Ein fremdes Handy sieht die PIN-Abfrage nie. Es gelten dieselben Grenzen wie am Dashboard: nach **5 falschen Eingaben** ist der Knopf 5 Minuten gesperrt; falsche Versuche stehen im Logbuch. Ein Doppel-Lesen zählt nur einmal. Abgelehnte Versuche stehen im Logbuch.
- Löschst du die Browserdaten des Handys, ist die Registrierung weg – einfach neu registrieren.
- **Fenster schließen:** Nach dem Scannen zeigt das Handy kurz „✓ ausgelöst“ und versucht, das Browserfenster selbst zu schließen. Ob das klappt, entscheidet der Browser: Öffnet er den Tag in einem **neuen Tab**, schließt er sich; nutzt er einen schon offenen Tab, bleibt die Seite stehen – dann erscheint nach kurzer Zeit ein Knopf **Schließen**. **Empfohlen und erprobt:** die App auf dem Startbildschirm installieren (am einfachsten über die öffentliche Einrichtungsseite `https://<deine-Tunnel-Adresse>/nfc`: dort steht ein Knopf **App installieren**, und die Seite zeigt, ob das Handy schon registriert ist; eine Anmeldung ist nicht nötig). Dann öffnet sich beim Scannen die App, zeigt kurz die Bestätigung und schließt sich von selbst wieder.
- **Cloudflare Access:** Ist vor die App eine Anmeldung gesetzt (Access), muss der Pfad `/nfc/*` davon ausgenommen sein, sonst erscheint beim Scannen die Cloudflare-Anmeldung. Die Handy-Registrierung ersetzt dort die Anmeldung.
- Die Registrierungen gehören zur Sicherung (Kapitel 15) und werden mit wiederhergestellt.

## 13d. Geräte teilen (zwischen BlueNexus-Anlagen)

*Smart Home → Teilen* (Recht „Smart Home: Geräte einrichten“, nur Administratoren). Zwei BlueNexus-Anlagen – z. B. deine und die deiner Mutter im selben Haus – können Geräte, Sensoren, Schalter und Knöpfe untereinander teilen. Der Geber behält alle Zugangsdaten und führt Befehle selbst aus. Das ist vor allem für **Cloud-Geräte mit Anmeldegrenze** wichtig, etwa die Klimaanlage: Der Medea-/NetHome-Login bleibt nur beim Geber, der Empfänger meldet sich dort nirgends zusätzlich an.

**Was sich teilen lässt:** Geräte (Steckdosen, Lampen, Klimaanlagen …), Sensoren, eigene Schalter und Knöpfe. Pro Eintrag legst du fest: **nur sehen** oder **sehen & bedienen** (Sensoren sind immer nur zum Sehen). Was selbst aus einer fremden Quelle stammt, lässt sich nicht weitergeben.

**Beim Geber (du)**
1. *Teilen → Teilen mit anderen:* Name der Person eintragen (z. B. „Marion“) → **Person anlegen**.
2. Es erscheint der **Zugangsschlüssel** (`bnx_…`) und die **Adresse** deines Systems. Der Schlüssel wird **nur dieses eine Mal** gezeigt, gespeichert ist nur sein Hash. Beides gibst du der Person.
3. **Geräte teilst du dort, wo sie stehen:** In *Aktoren*, *Sensoren* oder *Eigene Schalter & Knöpfe* auf das **✎** des Eintrags drücken und das **Teilen-Symbol** (drei verbundene Punkte) wählen. Ein Fenster fragt, **mit wem** (die angelegten Personen) und ob **nur sehen** oder **sehen & bedienen** (Sensoren nur sehen). Die Person sieht danach genau diesen Eintrag – keine lange Liste mit allem anderen. Am Namen erscheint zur Erinnerung das kleine **Teilen-Zeichen** (mit dem Mauszeiger darüber steht, mit wem). Zum Zurücknehmen Haken wieder entfernen.
4. Im Reiter *Teilen* klappst du eine Person mit **▸** auf und siehst darunter alles, was ihr geteilt ist – als normale Einträge wie in deinen Listen (Symbol, Name, Art). Rechts stellst du **nur sehen / sehen & bedienen** um und beendest mit dem **Papierkorb** das Teilen dieses Eintrags (bei dir bleibt das Gerät unverändert). Dazu steht dort, wann die Person zuletzt abgefragt hat. **Neuer Schlüssel** macht den alten sofort ungültig (z. B. wenn er in falsche Hände kam). Der Papierkorb löscht die Person samt aller Freigaben.

**Beim Empfänger (z. B. Marion oder Mama)**
1. *Teilen → Fremde Quellen:* Name (z. B. „Wohnung Micha“), **Adresse** und **Zugangsschlüssel** eintragen → **Verbinden**. Die App prüft dabei, ob die Verbindung klappt.
2. **Geräte holen:** angebotene Einträge ankreuzen → **Ausgewählte holen**. Sie erscheinen als normale Geräte bzw. Sensoren in der eigenen Anlage (Vermerk „von Wohnung Micha“), die Klimaanlage in der Rubrik Klimaanlagen mit dem vollen Bedienfeld (Modus, Temperatur, Lüfter). Danach lassen sie sich wie eigene umbenennen, aufs Dashboard legen, pro Benutzer sichtbar machen und in **Regeln** verwenden (WENN Sensor/Gerät …, DANN Gerät/Klimaanlage …).
3. **Umbenennen** geht ganz normal (✎ am Eintrag): Der eigene Name gilt nur bei dir, an der Funktion ändert sich nichts. **Quelle entfernen** löscht auch alle von dort geholten Einträge (nicht, solange eine Regel sie noch verwendet).

**Adresse: Tunnel oder lokal:** Die Anlage des Gebers muss vom Empfänger erreichbar sein. Der einheitliche Weg ist die **Tunnel-Adresse** (Kapitel 13b, `https://…`); sind beide Anlagen im selben Netz, geht auch die lokale Adresse mit Port (z. B. `http://192.168.2.40:5000`) – schneller und ohne Internet. Ist vor den Tunnel eine Cloudflare-Anmeldung (Access) gesetzt, muss der Pfad `/share/*` davon ausgenommen sein.

**Sicherheit**
- Ohne gültigen Schlüssel (Kopfzeile `Authorization: Bearer …`) antwortet die Schnittstelle `/share/v1/…` nur mit „ungültig“; falsche Versuche werden pro Adresse gebremst.
- Der Schlüssel gibt **nur die ausgewählten Einträge** frei, nur im erlaubten Umfang. Dashboard, Einstellungen, Konten und alle anderen Geräte bleiben unerreichbar. „Nur sehen“ wird **beim Geber** durchgesetzt, nicht nur im Bildschirm des Empfängers.
- Zugangsdaten (Medea-Konto, Gerätepasswörter, Tokens) verlassen den Geber nie.
- Befehle von außen stehen im Logbuch des Gebers („Freigabe ‚Mama‘: Klimaanlage … gestellt“). Sie zählen wie ein Handgriff: Regeln und Automatik des Gebers halten sich für dieses Gerät kurz zurück (Pause nach Handschaltung, Kapitel 10.5).
- Freigaben und Quellen gehören zur Sicherung (Kapitel 15). Beim Zurückspielen auf einem anderen System bleibt der Schlüssel gültig.

**Grenzen:** Ist der Geber oder seine Verbindung weg, zeigen die geholten Geräte „nicht erreichbar“, und der Empfänger kann sie nicht bedienen. Zustände werden etwa alle paar Sekunden abgefragt, Klingel-/Tür-Ereignisse kommen also mit kleiner Verzögerung. Kamerabilder, Thermostate, Schlösser und Rollläden lassen sich noch nicht teilen (folgt später).

## 14. Kosten, Tarife und Tarifwechsel

**Vertragskosten** (optional): Wer die festen Posten der Stromrechnung einträgt, bekommt in Telegram-Tagesbilanz und Monatsübersicht zusätzlich eine geschätzte **Gesamtsumme inkl. Gebühren**. Zwei Vorgehen, je nach Rechnung:

1. **Netto + eigene MwSt-Zeile (Tibber-Stil):** Nettobeträge eintragen (Grundgebühr, Netznutzung, Messstelle, §14a-Abzug) und den MwSt-Satz (meist 19 %).
2. **Ein Gesamtpreis, alles inklusive (fester Tarif):** Beträge **brutto** eintragen und die **MwSt auf 0** lassen, sonst wird die Steuer doppelt gerechnet.

**Tarifwechsel:** Ändert sich der Vertrag, den ersten Tag des neuen Tarifs unter **„Änderungen an Preis, Gebühren und MwSt gelten ab“** eintragen und speichern. Alles davor bleibt mit den alten Werten stehen, ab dem Datum gilt das Neue. Leer = ab heute. Das Datum darf zurückliegen (dann werden die Kosten ab diesem Tag neu berechnet), aber nicht in der Zukunft und nicht vor der letzten Änderung.

**Fester Tarif:** Der Preis wird je Vertragszeitraum gespeichert und rückwirkend korrekt auf die Tageskosten angewendet. Tage ohne Kosten (z. B. nach Datennachholen) werden automatisch repariert.

---

## 15. Update, Sicherung, Datenhaltung

- **Hintergrund-Animation:** Hinter den Karten läuft ein leuchtendes Knotennetz (Verlauf und Gitter bleiben immer). Unter *Einstellungen → Dashboard → Darstellung → Hintergrund-Animation* schaltest du sie **pro Gerät** ab, z. B. auf einem älteren Tablet oder Pi-Bildschirm. Sie pausiert bei verdecktem Tab und läuft nicht, wenn im Betriebssystem „Bewegung reduzieren“ eingestellt ist.
- **Uhrzeit & Zeitzone:** *Einstellungen → System → Uhrzeit & Zeitzone* zeigt die Uhr des Servers neben der Uhr deines Geräts und warnt bei Abweichung. Regeln, Zeitpläne und Sonnenzeiten richten sich nach der Server-Uhr – geht sie falsch, schaltet eine Regel zur falschen Zeit. Die **Zeitzone** (z. B. `Europe/Berlin`) stellst du dort direkt ein, sie gilt sofort und bleibt erhalten. Geht die **Uhr selbst** falsch (Abweichung von Minuten), fehlt der Zeitabgleich: auf dem Pi `sudo timedatectl set-ntp true`.
- **Update:** *Einstellungen → System → App-Version & Update* → „Nach Updates suchen“ → „Jetzt aktualisieren“. Alternativ per Terminal `git pull` im App-Ordner und Neustart des Dienstes (pm2 bzw. systemd). Persönliche Daten bleiben erhalten.
- **Daten** liegen als JSON-Dateien im Ordner `app/` und sind **nicht in Git** (stehen in `.gitignore`). Dazu gehören u. a. die Konfiguration, die Geräteregister (Geräte, Sensoren, Thermostate, Türschlösser, eigene Schalter, WOL-Ziele, Zigbee-/Homematic-Zugang), Regeln, laufende Abläufe, Historie, Ladeprotokoll, Benutzer und Vertragszeiträume.
- **Sicherung & Wiederherstellung (Umzug auf eine neue Installation):** *Einstellungen → System → Sicherung & Wiederherstellung* (nur Konten mit dem Recht „Benutzerverwaltung: Schreiben“).
  - **Herunterladen:** Passwort vergeben (mind. 8 Zeichen) → **Sicherung herunterladen**. Du bekommst **eine Datei** (`….bnx`) mit allen Einstellungen: Konten und Rechte, Zugangsdaten (Tibber, VRM, Telegram, Pushover, CCU, Tuya, Zigbee, Kameras, Fernzugriff), Geräte, Sensoren, Schalter, Regeln, Alexa-Freigaben, Verlaufs-Einstellungen, Dashboard. Mit dem Haken **„Verläufe und Historie mitnehmen“** kommen auch Energie-Historie, Ladeprotokoll, Monatsüberblick und die Diagramm-Daten dazu (Datei wird größer).
  - **Verschlüsselt:** Die Datei enthält Passwörter und Schlüssel und ist deshalb immer mit deinem Sicherungs-Passwort verschlüsselt (AES-256). **Ohne dieses Passwort ist sie nicht zu öffnen – es gibt keine Wiederherstellung des Passworts.** Datei und Passwort getrennt aufbewahren.
  - **Einspielen auf einer neuen Installation:** Nach der Installation im Browser öffnen. Auf der Seite „Konto anlegen“ steht unten **„Schon eine Sicherung? Alles wiederherstellen“**. Datei wählen (Endung **`.bnx`**; Sicherungen mit der früheren Endung **`.hnx`** lassen sich ebenfalls einspielen), Passwort eingeben, **Sicherung prüfen** (zeigt App-Name, Datum und Konten), **Jetzt wiederherstellen**. Die App startet neu – danach meldest du dich mit deinem **alten Konto** an, und alles ist wie vorher. Kein Terminal, kein SSH.
  - **Einspielen auf einer bestehenden App:** Dieselbe Karte in den Einstellungen. Das ersetzt **alle** aktuellen Einstellungen und Konten; der bisherige Stand wird vorher in `app/backups/vor-wiederherstellung-….zip` abgelegt (Rückweg).
  - **Nicht enthalten:** Zwischenspeicher (Preise, Prognose), Logbücher und die Cloudflare-Programmdatei (`cloudflared` wird bei Bedarf neu installiert, der Token ist in der Sicherung). Die Datei bleibt auf deinem Gerät – nichts wird in die Cloud geladen.
  - Über den Fernzugriff (Cloudflare) sind Uploads bis etwa 100 MB möglich; sehr große Sicherungen mit langer Historie besser im Heimnetz einspielen.
- **Testmodus (Einstellungen → System → Testmodus):** Mit einem Klick (die App startet dabei neu) darf die App das Gerät nicht mehr verlassen: Cerbo, Homematic, Shelly, Kameras, Tibber, Telegram, Tunnel und Alexa sind abgeschnitten, es wird nichts geschaltet oder gesendet. So prüfst du **eine eingespielte Sicherung** oder **ein Update**, ohne dass die echte Anlage etwas merkt; ein Banner oben erinnert daran. Danach „Testmodus beenden“. **Wichtig bei einer zweiten Installation:** Spielst du die Sicherung deiner echten Anlage auf einem zweiten Gerät ein, steuert dieses sonst dieselben Geräte mit und der Tunnel läuft doppelt. Deshalb zuerst den Testmodus einschalten, dann einspielen. Der Testmodus steht nicht in der Sicherung, eine eingespielte Sicherung schaltet ihn also nicht aus. Beim Demo-Betrieb und dem Testserver ist er fest eingeschaltet.
- **Sicherung gefahrlos ausprobieren (Testserver am PC, Windows):** `app\deploy\testserver.ps1` in der PowerShell starten (`-Neu` für eine frische, leere Installation). Es läuft im **Testmodus**: Die App darf **nichts nach außen senden** – kein Schalten, keine Nachrichten, kein Zugriff auf Cerbo, Geräte oder Kameras, kein zweiter Fernzugriff-Tunnel. Oben steht ein lila Streifen „TESTMODUS“. Adresse: `http://localhost:8813`. Dort „Schon eine Sicherung?“ → Datei einspielen und prüfen, ob alles übernommen wurde. Beenden mit Strg+C; die Testdaten liegen in `%TEMP%\BlueNexus-Test`. Auch ohne das Skript: Umgebungsvariable `BLUENEXUS_SANDBOX=1` vor dem Start setzen.
- **Demo-Instanz betreiben (öffentlich zum Ausprobieren):** Mit den Umgebungsvariablen `BLUENEXUS_DEMO=1` **und** `BLUENEXUS_SANDBOX=1` läuft BlueNexus als Demo: Der Cerbo, die Tibber-Preise, die PV-Prognose, Geräte, Homematic-CCU, Klimaanlagen, WLED, Sensoren und Kameras (Platzhalterbilder) sind **erfunden**, aber plausibel (Tagesverlauf, Preiskurve mit Spitzen, Prognose). Es wird nichts gespeichert und nichts geschaltet, Verbindungen nach außen sind gesperrt – einzige Ausnahme ist das echte Wetter (Open-Meteo). Der Verlauf rutscht beim Start um volle Wochen nach vorn, damit er nie veraltet. Empfohlen: ein eigener Container oder Rechner (nicht die echte Anlage), ein Nur-Lesen-Konto aus der Vorlage „Demo“ und ein eigener Tunnel mit eigener Adresse. Im Demo-Modus zeigt ein Hinweis „DEMO – alle Daten sind erfunden“ statt des Testmodus-Balkens; gesperrte Bereiche sehen bedienbar aus, ein Klick darauf meldet „Nur Ansicht in der Demo“. **Volle Ansicht:** Ein Nur-Lese-Konto sieht in der Demo auch die Verwaltungs-Knöpfe (Stifte, Formulare, PIN, Sichtbarkeit, Einstellungen mit allen Reitern), kann Dialoge öffnen und Hilfetexte lesen. Jedes Speichern, Löschen oder Schalten wird im Browser abgefangen und mit dem Hinweis beantwortet; der Server lehnt es zusätzlich ab. Das gilt nur im Demo-Modus (`BLUENEXUS_DEMO=1`), eine normale Installation zeigt diese Knöpfe weiterhin nur den Konten mit den passenden Rechten. Konto und Benutzerverwaltung bleiben auch in der Demo ausgeblendet.
- **Backups:** Vor riskanten Operationen (z. B. VRM-Nachimport) legt die App selbst Sicherungen im Ordner `app/backups/` an. Für eine Komplettsicherung den Ordner `app/` (ohne `__pycache__`) kopieren.
- **Passwörter und Tokens** (CCU, Tibber, VRM, Telegram, Tuya, Zigbee-Schlüssel) liegen nur auf dem Server und werden nie wieder angezeigt.
- **Python:** Der Server benötigt mindestens Python 3.9.

---

## 16. Beispiele

### 16.1 Licht, solange die Tür offen ist (Zustand halten)

1. Regeln → neue Regel „Flurlicht bei Tür“.
2. WENN: **Sensor** → Türsensor ist *wahr* (bzw. *offen*).
3. DANN: **Gerät einschalten** → Flurlicht. SONST: **Gerät ausschalten** → Flurlicht.
4. Mit Push von der CCU schaltet das Licht in unter einer Sekunde.

### 16.2 Warmwasser-Timer (Ablauf)

1. Einstellungen → Eigene Schalter: **Schalter** „Warmwasser-Timer“ anlegen.
2. Regel „Warmwasser“, Art **Ablauf**. WENN: **Eigener Schalter** „Warmwasser-Timer“ ist *an*.
3. DANN: Pumpe **einschalten** → **Warten** 60 Minuten → Pumpe **ausschalten**.
4. Optionen: „Laufenden Ablauf sofort beenden, wenn die Bedingung wegfällt“ an. Dann bricht das Ausschalten des Schalters den Timer ab (Pumpe geht per SONST aus).
5. Auf dem Dashboard zeigt die Kachel die Restzeit.

### 16.3 PC morgens wecken (Wake-on-LAN)

1. WOL-Ziel anlegen (Kapitel 11).
2. Regel, Art **Ablauf**, WENN **Uhrzeit (einmal pro Tag)** 07:00, an Werktagen.
3. DANN: **Rechner aufwecken** → dein PC.

### 16.3a Beleuchtung nach der Sonne schalten

**Am einfachsten – eine Regel:** Art **Zustand halten**, WENN **Nacht / Tag** = Nacht (z. B. Beginn +30 Min), DANN Beleuchtung **einschalten**, SONST **ausschalten**. Das Licht folgt dem Sonnenstand; nach einem Neustart stimmt der Zustand sofort wieder.

**Oder als zwei Ereignisse:**

1. Regel „Licht aus“, Art **Zustand halten**: WENN **Sonnenaufgang** (optional 15 Min danach), DANN Beleuchtung **ausschalten**.
2. Regel „Licht an“: WENN **Sonnenuntergang** (optional 30 Min vor), DANN Beleuchtung **einschalten**.
3. Voraussetzung: Unter *Einstellungen → Wetter* ist der Standort eingetragen.

### 16.3b Standbild aufs Handy, wenn etwas passiert

1. Regel, Art **Ablauf**. WENN: ein **Sensor** meldet Bewegung, ein **Knopf** (z. B. Klingel) wird gedrückt oder eine Tür geht auf.
2. DANN: **Telegram: Kamera-Standbild senden** → Kamera wählen, Text z. B. „Bewegung im Hof“.
3. **Sperrzeit** (bei Abläufen oben im Regel-Editor): z. B. 10 Sekunden. Löst der Auslöser nach dem Start nochmal aus – etwa weil jemand in der Lichtschranke hin und her läuft –, wird das innerhalb dieser Zeit ignoriert, es kommt also nicht jede Sekunde ein neues Foto. Das Logbuch vermerkt „Auslöser ignoriert“. 0 = keine Sperre.
4. **Lichtschranke/Kontakt über ein Homematic-Sendemodul** (z. B. HM-MOD-EM-8): Die Kanäle erscheinen bei der Sensorsuche als Sensor **„Eingang“** (Ja/Nein: TRUE = aktiv). In der Regel dann WENN *Sensor* … ist *TRUE*.
5. **Bewegung der Kamera selbst** als Auslöser: Sensor „Kamera – Person“ (oder „Bewegung“) wie oben unter *Kamera-Bewegung als Sensor* anlegen, dann WENN *Sensor* … ist *TRUE*. „Person“ löst weniger Fehlalarme aus als „Bewegung“ (Wind, Schatten).
6. Mehrere Kameras: mehrere Schritte hintereinander (oder ein **Warten** dazwischen, wenn das Bild später folgen soll).

### Kamera-Bewegung als Sensor (Reolink)

Unter *Smart Home → Sensoren* (sichtbar, sobald eine Kamera angelegt ist) gibt es **„Kamera-Bewegung suchen“**. Pro Reolink-Kamera werden angeboten:

- **Bewegung** (die normale Bewegungserkennung der Kamera),
- **Person, Fahrzeug, Tier** – nur wenn die Kamera diese KI-Erkennung kann und sie in der Kamera eingeschaltet ist (in der Reolink-App/Weboberfläche unter *Alarm/Erkennung*).
- **Klingel gedrückt** – nur bei Reolink-**Video-Türklingeln**: wird wahr, solange die Klingeltaste gemeldet wird. Damit lassen sich Regeln bauen wie „Klingel gedrückt → Foto + Pushover aufs Handy“. Voraussetzung wie bei jeder Kamera: In der Türklingel müssen **HTTP/HTTPS** und **RTSP** eingeschaltet sein (Reolink-App → Geräteeinstellungen → Netzwerk → Erweitert → Servereinstellungen).

Name und Symbol änderst du wie bei jedem Sensor vor dem Hinzufügen. Der Sensor ist **TRUE**, solange die Kamera die Erkennung meldet (die Kamera hält das meist einige Sekunden), sonst **FALSE**; ist die Kamera nicht erreichbar, gilt er als unbekannt. Die App fragt die Kamera etwa jede Sekunde ab, nur einmal pro Kamera, egal wie viele Sensoren daran hängen. Einsatz: Regel, Art **Ablauf**, WENN *Sensor* … ist *TRUE* → z. B. Telegram-Standbild, Licht, Sirene (Beispiel 16.3b; mit **Sperrzeit**, damit nicht jede Sekunde etwas passiert).

**Wie schnell?** Regeln mit Kamera- oder Zigbee-Sensoren prüft die App jede Sekunde; das Telegram-Foto ist immer ein frisches Bild im Moment des Auslösens. Der größte Zeitverlust liegt meist in der **Kamera selbst**: Die KI braucht eine Weile, bis sie „Person“ sicher erkennt (bei schnellem Vorbeilaufen kann die Person schon fast aus dem Bild sein). Hilfreich: In der Kamera die Erkennungs-**Empfindlichkeit** erhöhen und die Erkennungszone auf den Weg beschränken; als Auslöser bei Eile die einfache **Bewegung** nehmen (reagiert schneller als „Person“); oder im Ablauf nach dem ersten Foto ein **Warten** (1–2 s) und ein zweites Foto anhängen.

Eine Kamera lässt sich nicht löschen, solange eine Regel einen ihrer Sensoren braucht; sonst werden ihre Bewegungs-Sensoren beim Löschen mit entfernt.

### 16.3c Wandtaster als Auslöser (kurzer und langer Druck)

Ein Homematic-Wandtaster hat je Taste zwei Ereignisse: **kurz** und **lang** gedrückt. Bei der Sensorsuche (*Smart Home → Geräte suchen → Homematic-Sensoren suchen*) erscheinen sie als Sensoren **„Taste kurz gedrückt“** und **„Taste lang gedrückt“**.

1. Regel, Art **Ablauf**, WENN *Sensor* „Flur oben – Taste lang gedrückt“ ist *TRUE*.
2. DANN: Geräte **einschalten** → **Warten** 120 Sekunden → Geräte **ausschalten** (Zeit nach Bedarf).
3. Zweite Regel für „Flur unten – Taste lang gedrückt“: DANN alles **ausschalten**.

Wichtig: Tasten funktionieren **nur mit aktivem Push** der CCU (Smart Home → Sonstiges → Homematic-Push), weil ein Tastendruck ein Ereignis ist und sich nicht abfragen lässt. Ein Druck gilt etwa 5 Sekunden als TRUE und löst genau einen Ablauf aus. Ohne Push zeigt der Sensor „nicht lesbar“. Wer einen Taster für etwas anderes nutzt (z. B. kurz = Licht direkt am Gerät), kann die lange Taste trotzdem frei für Regeln verwenden.

### 16.3d Türklingel mit Gong

1. Soundmodul anlegen (Geräte suchen → Homematic-Soundmodule suchen) und den gewünschten Titel mit ▶ ausprobieren.
2. Regel, Art **Ablauf**: WENN der Auslöser (Klingeltaste als Sensor, eigener Knopf oder Taster) → DANN **Sound abspielen**: Modul, Titelnummer, Lautstärke.
3. Optional **Sperrzeit** setzen, damit wildes Klingeln nicht jede Sekunde den Gong auslöst.

### 16.3e Rollläden nach der Sonne (abends zu, morgens auf)

Zwei Regeln der Art **Ablauf** (Beispiel: eine Stunde nach Sonnenaufgang auf, eine Stunde nach Sonnenuntergang zu; am Wochenende morgens erst zwei Stunden nach Sonnenaufgang):

1. **Werktags:** WENN (alle müssen zutreffen) *Nacht / Tag (Sonnenstand)* = **Tag**, *Beginn verschoben um* **60**, *Ende um* **60**, **und** *Wochentag* **Mo bis Fr** → DANN **Rollladen** auf **100 %**; SONST **Rollladen** auf **0 %**.
2. **Wochenende:** Regel kopieren, *Wochentag* **Sa, So**, *Beginn verschoben um* **120**, *Ende* bleibt **60**.

Warum nicht mit „Nacht“ und Wochentag: Die Nacht reicht über Mitternacht; die Wochentags-Bedingung gilt immer für den **ganzen Kalendertag (0–24 Uhr)** und würde um 0:00 Uhr wegfallen – der SONST-Zweig führe dann mitten in der Nacht. Das Tag-Fenster liegt dagegen innerhalb eines Kalendertages. Mehrere Rollläden: mehrere Schritte im DANN und im SONST. Ein Ablauf löst nur im Moment des Wechsels aus – von Hand gefahrene Rollläden bleiben also, wo sie sind, bis zum nächsten Auslöser.

### 16.3f Video bei Tier-Erkennung

Ziel: Nur wenn die Kamera ein **Tier** erkannt hat, kommt ein Video aufs Handy – das Standbild kann sofort mitkommen.

1. Unter *Smart Home → Geräte suchen* mit „Kamera-Bewegung suchen“ den Kamera-Sensor **Tier** anlegen (Voraussetzung: Tiererkennung in der Kamera aktiv).
2. Neue Regel, Art **Ablauf**. WENN: Sensor „Hof – Tier“ ist wahr.
3. DANN: **Telegram: Kamera-Standbild senden** (sofort) und **Telegram: Video zum Ereignis senden** mit Filter **Tier**.

Das Video wird erst gesendet, wenn die Kamera die Aufnahme abgeschlossen hat (meist 1 bis 2 Minuten). Enthält die Aufnahme nur „Person“ oder „Bewegung“, wird nichts gesendet; das steht im Logbuch. Welche Aufnahmen auf einer Kamera liegen und ob der Abruf klappt, zeigt `./venv/bin/python camera_diag.py` im App-Ordner (nur Lesen).

### 16.4 Heizung bei viel Sonne anheben (Ablauf)

1. WENN: **Sonne morgen** über Schwellwert *und* **Akkustand** über 80 %.
2. DANN: **Thermostate** auf 22 °C setzen → **Warten** 4 Stunden → Thermostate auf 20 °C.
3. SONST: Thermostate auf 20 °C (räumt auf, auch bei vorzeitigem Abbruch).

### 16.5 Waschmaschine/Boiler nur bei günstigem Strom (Zustand halten)

1. WENN: **Laufzeit pro Tag** 120 Minuten, Zeitfenster 22:00–06:00. Die Regel wählt dann selbst die günstigsten Zeiten im Fenster aus.
2. DANN: Boiler einschalten. SONST: Boiler ausschalten.
3. Alternativ: WENN **Strompreis** unter 20 ct → Boiler an (läuft dann immer, solange der Preis niedrig ist).

### 16.6 Tür öffnen per Knopf (mit Sicherheit)

1. Türschloss unter „Türschlösser“ anlegen und **Entriegeln/Öffnen freigeben**.
2. Eigenen **Knopf** „Tür öffnen“ anlegen und mit **PIN** schützen.
3. Regel (Ablauf): WENN **Knopf** „Tür öffnen“ gedrückt → DANN **Türschloss öffnen**.
4. Zum Ausprobieren erst **Trockenlauf** – das Schloss wird dabei nie bewegt.

---

## 17. Fehlersuche (FAQ)

**Eine Regel schaltet nicht.**
Prüfe nacheinander: Ist „Regeln aktiv“ an und der **Trockenlauf aus**? Zeigt das **Logbuch** einen Eintrag (auch „nicht erreichbar“)? Ist ein Sensor/Gerät der Bedingung erreichbar? Gehört das Gerät auch zur Überschuss-Automatik? Bei einem Ablauf mit eigenem Schalter: Wurde der Schalter nach dem letzten Durchlauf wieder auf „aus“ gestellt?

**„Nicht erreichbar (UNREACH)“ bei Homematic.**
Das Gerät meldet der CCU keine Funkverbindung. In der CCU-Oberfläche nachsehen (Batterie, Reichweite). Die App schaltet bei fehlendem Messwert nichts.

**Homematic reagiert langsam.**
„Push von der CCU“ einschalten. Die CCU muss den Server unter dem Push-Port erreichen können.

**Ein Zigbee-Gateway ist ausgefallen.**
Die anderen Gateways laufen weiter. Geräte des ausgefallenen Gateways zeigen „Gateway <Name>: nicht erreichbar“. Ein ausgefallenes Gateway wird nur alle ~15 Sekunden neu abgefragt, damit die App nicht ausgebremst wird.

**Ein Zigbee-Gateway lässt sich nicht entfernen.**
Solange noch Geräte, Sensoren oder Thermostate an dem Gateway hängen, bleibt es erhalten (sonst gingen sie samt Regeln verloren). Erst diese entfernen, dann das Gateway.

**Zigbee verbindet nicht.**
In Phoscon muss „App autorisieren“ aktiv sein, wenn man „Mit Gateway verbinden“ drückt (nur ca. 1 Minute lang). Gateway-Adresse inkl. Port prüfen.

**Eine Taste (Wandtaster) löst nichts aus.**
Ist der **Homematic-Push** an? Unter *Smart Home → Sonstiges* die „Letzten Meldungen der CCU“ öffnen, Taste drücken, **Aktualisieren**: Steht dort eine Zeile mit der Kanaladresse (z. B. `PRESS_LONG` oder `PRESS_CONT`)? Wenn nicht, kommt die Meldung nicht bei der App an. Wurde die Taste nach einer neuen Sensorsuche angelegt? Steht „kurz“ oder „lang“ im Sensor richtig? Bei Abläufen mit Warten: Häkchen „Laufenden Ablauf sofort beenden …“ aus?

**Ein Gerät oder Modul wird bei der Suche nicht gefunden.**
Bei Homematic muss die CCU-Verbindung stehen. Sensor „Eingang“ (z. B. HM-MOD-EM-8), Tasten und Soundmodule erkennt die App an Kanaltyp bzw. Gerätetyp. Wird ein Modell nicht erkannt, den Namen des Kanals aus der CCU notieren und melden.

**Beim Klick auf Live sehe ich nur ein Standbild.**
Die Live-Ansicht verbindet bei Fehlern **automatisch immer wieder neu**, bis das Bild kommt („Verbinde … Versuch n“), und das letzte Standbild bleibt dahinter sichtbar. Bleibt es lange dabei, antwortet die Kamera nicht (zu viele gleichzeitige Verbindungen? Zugangsdaten/Port prüfen). Mit ■ beendest du den Versuch.

**Ich kann ein Gerät/einen Knopf/eine Kamera nicht entfernen.**
Eine **eingeschaltete Regel** verwendet es (der Hinweis nennt die Regeln). Die Regel ausschalten oder löschen, dann geht das Entfernen.

**Rechner wacht nicht auf.**
Wake-on-LAN im BIOS und Netzwerktreiber aktiviert? Schnellstart in Windows aus? Richtige MAC-Adresse? Server im selben Netz (sonst Broadcast-Adresse angeben)? Der Rechner muss per Kabel angeschlossen sein; WLAN weckt meist nicht.

**PIN vergessen / gesperrt.**
Ein Admin kann die PIN unter Smart Home → Aktoren neu setzen oder entfernen. Eine Sperre nach 5 Fehlversuchen endet nach 5 Minuten.

**Kosten stehen auf 0 € (fester Tarif).**
Die App repariert Tage ohne Kosten beim Start automatisch. Prüfe, ob unter Stromtarif ein Preis eingetragen ist.

**Es wird nicht geladen, obwohl der Preis niedrig ist.**
Dry-Run an? Ladelimit schon erreicht? Fester Tarif (lädt nie aktiv)? Mit der Intelligenten Planung entscheidet der Plan über das gesamte Zeitfenster, nicht nur der aktuelle Preis – der Ladeplan im Dashboard zeigt die geplanten Fenster.

**Browser zeigt alte Oberfläche nach einem Update.**
Seite hart neu laden (Strg+Shift+R) bzw. auf dem Handy den Browser-Cache der App leeren.

**Betriebsbericht zeigt keine Dauer-Werte.**
Die Statistik (Ø/max. Dauer eines Regeldurchlaufs) braucht einige Tage Betrieb, um aussagekräftig zu sein.

---

## Haftung

Nutzung auf **eigene Verantwortung**. Die Software schaltet Strom, Heizung und – wenn freigegeben – Türschlösser. Vor dem Scharfschalten alles im **Trockenlauf** prüfen, besonders Abläufe mit Türschloss, Thermostaten oder Netzladung.
