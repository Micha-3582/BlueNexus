# Änderungsprotokoll

Hier steht, was sich in welcher Version geändert hat. Die Versionsnummer steht in der App unter *Einstellungen → System* („Installierte Version“), in `app/VERSION` und als Tag/Release auf GitHub (`v1.6.0` …).

**Zählweise:** `1.x.0` = neue Funktionen, `1.x.y` = Fehlerbehebungen und Kleinigkeiten. Die genauen Einzeländerungen stehen im Verlauf der Commits.

## 1.54.0 – 11.11.2026
- Neu: **Aktivzeit und Sendefehler der Thermometer.** Meldet ein Thermometer (Firmware ab 2.0.9) zusätzlich die Aktivzeit und das Ergebnis des vorherigen Aufwachens, zeigt die Liste „Aktivzeit 1,8 s (Ø 1,9 s)“ und „Sendefehler 2 von 120“ (mit Zahl der Meldungen, die erst im 2. Versuch durchkamen). Daraus lässt sich der Stromverbrauch abschätzen. Ältere Firmware meldet die Felder nicht; die Meldungen werden wie bisher angenommen.
- Neu: **Thermometer-Firmware 2.0.8** ersetzt 2.0.7 (Diagnoseprotokoll mit Aktivzeit je Aufwachen). Aktualisiert wird weiterhin nur auf Knopfdruck je Gerät.

## 1.53.4 – 11.11.2026
- Neu: Im Bereich „ESP vorbereiten“ führt ein Link zur ausführlichen Anleitung auf der Homepage (Vorbereiten, Einrichten, Zurücksetzen).

## 1.53.3 – 11.11.2026
- Geändert: Die Anleitung zu „ESP vorbereiten“ nennt jetzt die empfohlene Reihenfolge: **erst flashen, dann löten.** Ein neues Modul wird per USB vorbereitet, bevor Regler und rote LED entfernt werden; dann braucht es beim Flashen keine Batterien. Der Hinweis „Batterien einlegen und USB stecken“ bleibt nur für schon umgebaute Module.

## 1.53.2 – 11.11.2026
- Neu: **Thermometer-Firmware 2.0.7** ersetzt 2.0.6 (sendet bei Verbindungsfehlern einmal erneut). Geräte mit 2.0.6 sehen „Update 2.0.7 verfügbar“; aktualisiert wird weiterhin nur auf Knopfdruck je Gerät.
- Korrigiert: Anleitung im Fenster „ESP vorbereiten“ und im Handbuch. Bei vorbereiteten Modulen (Regler und rote LED entfernt) versorgt USB den Chip nicht: Batterien müssen eingelegt sein **und** das USB-Kabel stecken. Download-Modus: RESET halten, BOOT halten, RESET loslassen, BOOT loslassen; danach RESET drücken.

## 1.53.1 – 10.11.2026
- Neu: **Thermometer-Firmware 2.0.6** ersetzt 2.0.5 (Geräte mit 2.0.5 sehen „Update 2.0.6 verfügbar“).
- Geändert: Das Anleitungs-Etikett trägt nicht mehr „USB nur ohne Batterien!“ (beim neuen Aufbau ohne Regler überholt, die Sicherheitshinweise stehen auf der Anleitungsseite), sondern „QR-Code scannen“. Handbuch: Etikett-Absatz und der veraltete Abschnitt „Neu flashen“ (Knöpfe gibt es nicht mehr) überarbeitet.

## 1.53.0 – 10.11.2026
- Neu: **Anleitungs-Etikett für die Platine** (Einstellungen → System → Funkthermometer, Knopf „🏷 Anleitungs-Etikett für die Platine“). Druckt einen QR-Code zur Anleitungsseite des Thermometers (Sicherheit, Einrichten, Zurücksetzen) mit „Anleitung“ und „USB nur ohne Batterien!“ auf ein Niimbot-Etikett (nur am Android-Handy, Chrome, https). Die Adresse ist fest und gilt für alle Thermometer; der Knopf ist auch ohne eingerichtetes Thermometer da.

## 1.52.3 – 10.11.2026
- Neu: **Thermometer-Firmware 2.0.5** ersetzt 2.0.2. Enthalten sind die Verbesserungen der Zwischenversionen: geringere Sendeleistung bei naher Funkstation, ein Brownout-Schutz, der auch nach Spannungseinbrüchen zählt (keine Neustart-Schleife mehr), und ein Diagnoseprotokoll im Gerät. Geräte mit 2.0.2 bis 2.0.4 sehen „Update 2.0.5 verfügbar“.

## 1.52.2 – 10.11.2026
- Neu: **Thermometer-Firmware 2.0.2** ersetzt 2.0.1. Das Einrichtungs-WLAN ist batterieschonender; mit Batterien kam es vorher zu Neustarts, und das WLAN verschwand immer wieder.
- Behoben: **Update-Anzeige.** Ein Thermometer mit einer neueren Firmware als im Paket bekam fälschlich „Update verfügbar“. Jetzt wird ein Update nur noch angeboten, wenn die Paketversion **höher** ist als die gemeldete (Zahl für Zahl verglichen); nie eine ältere. Das gilt auch für schon vorgemerkte Updates.

## 1.52.1 – 10.11.2026
- Geändert: Der animierte Hintergrund (Knotennetz) wird jetzt in einem eigenen Worker gezeichnet (OffscreenCanvas) und läuft damit unabhängig vom Rest der Seite weiter, auch wenn die Seite gerade etwas Schweres tut (Klick, Neuzeichnen, Daten laden). Auf Browsern ohne diese Technik zeichnet wie bisher die Seite selbst. Gilt für alle Seiten.

## 1.52.0 – 10.11.2026
- Neu: **Thermometer-Firmware 2.0.1** ersetzt 2.0.0. Das Thermometer ist beim Aufwachen deutlich kürzer wach (WLAN-Verbindung in etwa 0,6 s statt 2,9 s im Heimnetz), die Batterie hält dadurch rund viermal so lange. Thermometer mit 2.0.0 bekommen in der Liste „Update 2.0.1 verfügbar“ und lassen sich per Funk aktualisieren. In der Heimnetz-Auswahl steht jetzt, dass die Batterie dort deutlich länger hält als über Internet.

## 1.51.2 – 10.11.2026
- Behoben: In der Geräteübersicht (IP-Adressen) wurde ein Drucker mit seiner Kamera (gleiche Adresse) fälschlich als „doppelte IP-Adresse“ markiert. Eine Kamera darf dieselbe Adresse haben wie ein anderes Gerät; doppelt sind nur gleiche Adressen unter den Geräten bzw. unter den Kameras.

## 1.51.1 – 10.11.2026
- Behoben: Unter „ESP vorbereiten“ standen noch die alten Knöpfe („Einrichten und flashen“, „ESP32 löschen“) doppelt außerhalb des Aufklapp-Bereichs. Jetzt erscheinen sie nur noch nach dem Aufklappen.

## 1.51.0 – 10.11.2026
- Geändert: **Nur noch eine Thermometer-Firmware (2.0.0).** „Einrichten und flashen“ mit WLAN-Eingabe entfällt. Das USB-Fenster heißt **„ESP vorbereiten“** und spielt die mitgelieferte Firmware ohne Eingaben auf (Chips lassen sich auf Vorrat vorbereiten); eingerichtet wird das Thermometer am Einsatzort per Handy mit dem Kopplungscode, den BlueNexus erzeugt. Eine Kurzanleitung steht darunter. Die alte Firmware 1.1.1 liegt nicht mehr im Paket.
- Neu: **Firmware-Update per Funk** (ab Firmware 2.0.0). In der Liste erscheint „Update … verfügbar“ mit einem Knopf; das Thermometer lädt die Datei bei seiner nächsten Meldung (Heimnetz oder Tunnel, nur mit dem Schlüssel des Geräts).
- Neu: **Neuen Kopplungscode erzeugen** (🔑) für Thermometer ohne gespeicherten Code, z. B. mit alter Firmware: ID, Sensoren, Verläufe und Regeln bleiben erhalten.

## 1.50.2 – 10.11.2026
- Geändert: Der 🔑-Knopf zeigt den Kopplungscode jetzt **ohne Passwortabfrage** (nur für angemeldete Administratoren) und hat einen **Kopieren-Knopf**, der den langen Code mit einem Klick in die Zwischenablage legt.

## 1.50.1 – 10.11.2026
- Geändert: In der Thermometer-Liste sind die Knöpfe jetzt **quadratische Symbolknöpfe** wie im Smart-Home-Bereich (Etikett, Neu flashen, Kopplungscode, Intervall, Abgleichen, Umbenennen, Entfernen); die Beschreibung steht als Hover-Text.

## 1.50.0 – 10.11.2026
- Neu: **Kopplungscode später wieder ansehen.** Bei Thermometern, die mit Kopplungscode angelegt wurden, gibt es in der Liste einen 🔑-Knopf. Nach Eingabe des eigenen Passworts zeigt er den Code noch einmal an (und kopiert ihn). Für schon vorhandene Geräte gibt es keinen Code mehr; dort hilft nur neu anlegen.

## 1.49.1 – 10.11.2026
- Behoben: Auf dem Handy ließ sich die Einstellungsseite (System) seitlich verschieben. Ursache waren die versteckten Auswahlknöpfe der neuen Thermometer-Karten.

## 1.49.0 – 10.11.2026
- Geändert: **Funkthermometer einrichten mit Auswahl.** Oben wählst du den Weg: **Im Heimnetz (HTTP)** (läuft auch ohne Internet) oder **Über Internet (https)** (überall, braucht den Fernzugriff). Beide erzeugen einen **Kopplungscode**; beim Heimnetz enthält er die lokale `http://`-Adresse, und das Gerät bleibt von außen gesperrt. Das Flashen per USB steht jetzt eingeklappt darunter („Per USB flashen“). In der Liste steht „· per Code“ bzw. „· ohne USB“.

## 1.48.0 – 09.11.2026
- Neu: **Funkthermometer ohne USB anlegen** (für Standorte ohne eigene BlueNexus). Einstellungen → System → Funkthermometer → „Gerät ohne USB anlegen“ erzeugt Geräte-ID und Schlüssel und zeigt einen **Kopplungscode** (`bnxthermo1_…`, Adresse + ID + Schlüssel, ohne WLAN) zum Kopieren. Solche Geräte melden ihre Werte über die Internet-Adresse (Tunnel) an `/api/sensor/<ID>` – höchstens eine Meldung alle 20 Sekunden, andere Thermometer bleiben auf das lokale Netz beschränkt. Optional ein **Standort** je Gerät (in der Liste mit 📍).

## 1.47.0 – 09.11.2026
- Neu: **Live-Werte der Anlage lassen sich teilen** (nur ansehen): Solar gesamt, PV-Wechselrichter gesamt sowie L1/L2/L3 und PV-Ladegerät (MPPT). Im Reiter *Teilen* beim Aufklappen einer Person anhaken; die Gegenseite holt sie wie Sensoren (Watt) ab und kann sie auf dem Dashboard und in Regeln nutzen.

## 1.46.5 – 09.11.2026
- Behoben: Geteilte Sensoren (z. B. Temperatur, Luftfeuchte) kamen bei der Gegenseite immer mit dem Standard-Symbol 📟 an. Jetzt wird das Symbol des Teilenden durchgereicht; hat der Sensor keins gewählt, nimmt die Gegenseite das passende Symbol zur Art des Messwerts (🌡️, 💧 …). Bereits geholte Sensoren mit dem alten Standard-Symbol werden beim Start entsprechend zurückgesetzt.

## 1.46.4 – 08.11.2026
- Behoben: Bei einer Kamera, die offline ist, erscheint hinter „offline“ nicht mehr das Symbol für ein fehlendes Bild.

## 1.46.3 – 08.11.2026
- Geändert: Auf dem Handy (unter 480 Pixel Breite) sind die Symbol-Knöpfe im Smart-Home-Menü und in den Einstellungen jetzt gleich groß (36 Pixel, rund).

## 1.46.2 – 08.11.2026
- Geändert: Die runden Symbol-Knöpfe der Reiterleisten (Smart Home, Einstellungen) sind auf schmalen Bildschirmen jetzt überall exakt rund (vorher leicht oval).

## 1.46.1 – 08.11.2026
- Behoben: Gewählte neue Symbole (z. B. 🪟 Fenster) wurden bei jedem Start der App wieder durch das Standard-Symbol (🏠) ersetzt. Eine alte Aufräum-Funktion für Handys ohne neue Emoji ist jetzt auf das eine Zeichen beschränkt, das dort wirklich fehlt. Bereits zurückgesetzte Symbole müssen einmal neu gewählt werden.
- Geändert: Auf schmalen Bildschirmen (Handy) zeigt die Reiterleiste der Einstellungen nur noch die Symbole (Name als Tooltip), wie im Smart-Home-Menü – ohne seitliches Scrollen.

## 1.46.0 – 08.11.2026
- Neu: Die Reiterleiste der **Einstellungen** (Anlage, Tarif & Laden, Solar, VRM, Automatik, Wetter, Meldungen, Dashboard, System, Konto & Benutzer) hat jetzt eigene Symbole vor der Beschriftung – im gleichen Linien-Stil wie das Smart-Home-Menü, auch auf der Seite „Automatik“.

## 1.45.4 – 08.11.2026
- Behoben: Der Bereich „Chime (Türgong)“ auf der Kameraseite und der Regelschritt „Chime läuten“ erscheinen nur noch bei Reolink-Video-Türklingeln, nicht mehr bei normalen Kameras (die haben keinen Chime). Erkannt wird die Türklingel am Modellnamen beim Hinzufügen; bei bestehenden Kameras am gespeicherten Modell.

## 1.45.3 – 08.11.2026
- Geändert: Regel-Editor, Schritt „Eigener Schalter“: Es werden nur noch Aktionen angeboten, die zur Art passen – ein Knopf kann nur **gedrückt** werden, ein Schalter oder Timer nur **ein-, aus- oder umgeschaltet** werden. Beim Wechsel des Ziels passt sich die Auswahl an. Beim Speichern prüft BlueNexus das zusätzlich; bestehende, nicht passende Regeln werden mit „(geht hier nicht)“ markiert und lassen sich erst nach Korrektur speichern.

## 1.45.2 – 08.11.2026
- Geändert: Kamera-Sensoren bekommen je Erkennung ein eigenes Symbol: 🏃 Bewegung, 🧍 Person, 🚗 Fahrzeug, 🐕 Tier, 🔔 Klingel – schon in der Trefferliste und beim Anlegen.

## 1.45.1 – 08.11.2026
- Geändert: In den Trefferlisten von „Geräte suchen“ zeigen Sensoren (Kamera, Homematic, Zigbee, Tasmota-Messwerte) jetzt gleich das passende Symbol zur Art des Messwerts (z. B. 🏃 Bewegung, 🌡️ Temperatur) statt des Steckers; nach dem Hinzufügen bleibt es dasselbe.

## 1.45.0 – 07.11.2026
- Neu: **Bewegungs-Erkennung für RTSP-Kameras über ONVIF.** Kameras ohne Reolink-Schnittstelle (z. B. Reolink Lumus 2K, nur Port 9000, RTSP 554 und ONVIF 8000) liefern jetzt Bewegung, Person, Fahrzeug und Tier als Sensoren. „Kameras suchen“ bietet sie an, danach lassen sie sich in Regeln, auf dem Dashboard und im Logbuch nutzen wie die Erkennungen der anderen Kameras. BlueNexus hält dafür ein ONVIF-Abo je Kamera (Meldung sofort, mit automatischer Wiederverbindung). Klingel und Chime bleiben Reolink-Kameras mit Schnittstelle vorbehalten.

## 1.44.1 – 07.11.2026
- Geändert: Das Symbol 🪟 (Fenster) steht in der Auswahl jetzt direkt hinter der Tür 🚪 statt ganz am Ende.

## 1.44.0 – 07.11.2026
- Neu: **Neuere Symbole (Emoji 13 bis 15) stehen wieder zur Wahl**, bei Aktoren, Sensoren, Schaltern und überall, wo man ein Symbol auswählt, zum Beispiel 🪟 Fenster, 🪴 Zimmerpflanze, 🪞 Spiegel, 🪜 Leiter, 🛗 Aufzug, 🫧 Blasen, 🪫 Akku fast leer, 🛜 WLAN, 🫖 Teekanne, 🪣 Eimer, 🪛 Schraubendreher, 🪚 Säge und weitere. Nur Zeichen, die gar keine Emoji sind (z. B. das Ein-/Aus-Zeichen ⏻), bleiben ausgeschlossen. Bereits gewählte Symbole bleiben unverändert.

## 1.43.1 – 07.11.2026
- Geändert: Bei ESPHome-Geräten steht „Verbindung stabil seit …“ nicht mehr in der Liste. Angezeigt werden nur noch Verbindungsabbrüche und Neustarts des Geräts.

## 1.43.0 – 07.11.2026
- Neu: **Kameratyp frei eintragbar.** Beim Stift einer Kamera gibt es unter dem Namen ein Feld „Kameratyp“ (z. B. RLC-820A). Der Eintrag erscheint oben rechts auf der Kamerakarte. Bleibt das Feld leer, steht dort der Standard („RTSP“ bzw. „Reolink“).

## 1.42.2 – 06.11.2026
- Geändert: **Regel-Editor: Auswahl der Bedingungsarten sinnvoll sortiert.** Erst Zeit (Uhrzeit, Wochentag, Sonne), dann Sensoren, Aktoren und Auslöser (Sensor, Wert ändert sich, Aktoren, Eigener Schalter, Telegram-Wort, Regel), zuletzt Energie (Strompreis, Laufzeit, Akku, Sonne morgen). Der Eintrag „Sensor“ heißt jetzt „Sensor (Wert oder Ja/Nein)“.

## 1.42.1 – 06.11.2026
- Behoben: **„Wert ändert sich um …“ fand den Sensor nicht** („keine Daten … nicht mehr vorhanden“). Die Regel-Abfrage las nur Sensoren aus Bedingungen der Art „Sensor“, nicht aus der neuen Bedingung. Jetzt werden auch deren Sensoren gelesen.

## 1.42.0 – 06.11.2026
- Neu: **Bedingung „Sensor: Wert ändert sich um …“.** In Regeln der Art Ablauf löst ein Messwert-Sensor jedes Mal aus, wenn er sich seit der letzten Auslösung um mindestens eine einstellbare Schrittweite verändert hat (z. B. Druckfortschritt um 1 %, Temperatur um 0,5 °C), wahlweise in beiden Richtungen, nur steigend oder nur fallend. Der Bezugswert bleibt auch nach einem Neustart erhalten.
- Neu: **Platzhalter in Nachrichten.** In Telegram- und Pushover-Texten sowie im Text zu Standbild und Video ersetzt BlueNexus **[WERT]** (Wert mit Einheit), **[ZAHL]**, **[ALT]** (vorheriger Wert), **[SENSOR]**, **[UHR]** und **[REGEL]** (zusätzlich zum bisherigen **[WER]**). Die Werte kommen vom ersten Sensor der Bedingung WENN. Alle Platzhalter stehen im Regel-Editor unter „Platzhalter in Nachrichten“ und als Hilfe-Fragezeichen an den Textfeldern.
- Beispiel: Druckfortschritt bei jedem Prozent per Telegram: „🖨️ [SENSOR]: [WERT] (vorher [ALT])“.

## 1.41.4 – 06.11.2026
- Behoben: **Druckerkamera: Live-Bild blieb nach wenigen Sekunden stehen.** Der Drucker erlaubt nur eine Kameraverbindung zugleich. Die Standbild-Abrufe der Kameraseite (alle paar Sekunden) öffneten eine zweite Verbindung und beendeten damit die Live-Ansicht. Solange eine Live-Ansicht der Druckerkamera läuft, gibt es jetzt keine neuen Abrufe mehr (das letzte Standbild bleibt stehen); ein gerade laufender Abruf darf vor dem Live-Start noch fertig werden.
- Der Versuch aus 1.41.2 (Zeitstempel aus der Serveruhr) bleibt drin, schadet nicht.

## 1.41.3 – 06.11.2026
- Neu (Fehlersuche): Endet ein Kamera-Livestrom unerwartet früh, schreibt BlueNexus Dauer, Rückgabecode und die letzten ffmpeg-Meldungen ins Server-Log (`pm2 logs`, Zeile mit `[camera]`). Dient zur Suche nach dem Live-Bild der Druckerkamera, das nach wenigen Sekunden stehen bleibt.

## 1.41.2 – 06.11.2026
- Behoben (Versuch): **Druckerkamera: Live-Bild blieb nach 2–3 Sekunden stehen.** Die Zeitstempel im Kamerastrom des Druckers springen; BlueNexus nimmt sie jetzt aus der Serveruhr und verwirft beschädigte Pakete. Gilt nur für die verschlüsselte Druckerkamera, andere Kameras bleiben unverändert.

## 1.41.1 – 06.11.2026
- Behoben: **Kameras: Seite ließ sich nach dem Vollbild nicht mehr scrollen.** Wer das Live-Bild im Vollbild geöffnet und mit dem runden ✕ wieder geschlossen hat, konnte die Seite nicht mehr scrollen, das Bild wirkte eingefroren, erst ein Reiterwechsel half. Ursache: Die Kameraseite und die allgemeine Scroll-Sperre für Vollbild-Fenster sperrten die Seite beide und kamen sich beim Aufheben in die Quere. Jetzt sperrt nur noch die allgemeine Sperre und gibt die Seite sicher wieder frei.

## 1.41.0 – 06.11.2026
- Neu: **Kamera des Bambu-Lab-Druckers.** In der Bearbeiten-Ansicht der Drucker-Zeile (Aktoren) gibt es einen **Kamera-Knopf**, der die Kamera des Druckers (X1C, X1E, H2D) unter *Kameras* anlegt. BlueNexus nutzt dafür den verschlüsselten Kamerastrom des Druckers (Port 322, Benutzer `bblp`, derselbe Zugangscode) und prüft beim Anlegen, ob ein Bild kommt. Danach läuft die Kamera wie jede andere (Standbild, Live-Ansicht, Freigaben, Sichtbarkeit). Am Drucker muss dafür die **Live-Ansicht im LAN** freigegeben sein; bei einem Fehler nennt BlueNexus diesen Hinweis. P1 und A1 senden ihr Bild auf anderem Weg, das ist noch nicht unterstützt.
- Intern: RTSP-Kameras können einen verschlüsselten Strom (`rtsps`) nutzen.

## 1.40.1 – 06.11.2026
- Behoben: **Trefferlisten verschiedener Systeme vermischten sich.** Wer unter *Geräte suchen* zuerst bei einem System (z. B. Tuya) und dann bei einem anderen (z. B. Zigbee) suchte, sah die Treffer beider Systeme in derselben Liste, und „Hinzufügen“ konnte beim falschen System landen. Jetzt behält jedes System-Fenster **seine eigene Trefferliste und Meldung**: beim Wechsel in ein anderes Fenster wird die Liste beiseitegelegt und beim Zurückkehren wieder angezeigt. Wechselt man während einer laufenden Suche das Fenster, werden die späteren Treffer nicht mehr in das andere Fenster geschrieben.

## 1.40.0 – 06.11.2026
- Neu: **Ein Suchknopf je System.** Unter *Smart Home → Geräte suchen* gibt es pro System genau einen Knopf („Shellys suchen“, „Tasmota / WLED suchen“, „Homematic suchen“, „Zigbee suchen“ …). Er findet alles, was das System liefert, und zeigt es **gruppiert in einer Liste**: bei Homematic Geräte, Sensoren, Thermostate, Türschlösser, Soundmodule und Rollläden, bei Zigbee Lichter/Steckdosen, Sensoren und Thermostate, bei Tasmota Geräte und Messwerte. Die zusätzlichen Knöpfe („Homematic-Sensoren suchen“, „Zigbee-Thermostate suchen“, „Tasmota-Messwerte suchen“ …) und das getrennte IP-Feld samt zweitem „Suchen“-Knopf bei Shelly und Tasmota entfallen: Steht eine IP im Feld, wird nur dieses Gerät gesucht.
- Verschoben: **Kamera-Bewegung** und **Tasmota-Messwerte** stehen nicht mehr im Reiter *Sensoren*, sondern bei *Geräte suchen* (neues Fenster **Kameras** mit „Kameras suchen“). Der Reiter *Sensoren* zeigt nur noch die Sensorliste.

## 1.39.3 – 06.11.2026
- Behoben: Das **Smart-Home-Menü** passte mit den Symbolen am Computer nicht mehr in die Leiste, der letzte Knopf („Sonstiges“) war abgeschnitten. Die Knöpfe sind etwas schmaler, und reicht die Breite trotzdem nicht, rutscht der Rest in eine zweite Zeile, sodass alles sichtbar ist und nichts gescrollt werden muss. Auf dem Handy bleibt es bei einer Zeile mit Symbolen.

## 1.39.2 – 06.11.2026
- Verbessert: Im **Smart-Home-Menü** (Aktoren, Sensoren, Thermostate …) stehen die Symbole jetzt auch am Computer vor der Beschriftung, nicht mehr nur auf dem Handy. Auf schmalen Bildschirmen bleiben wie bisher nur die Symbole.

## 1.39.1 – 06.11.2026
- Verbessert: Unter *Einstellungen → Geräte → Suchen* stehen die Such-Bereiche jetzt in derselben Reihenfolge wie die Auswahl der Systeme darüber: Shelly, Tasmota / WLED, Tuya, Homematic, Zigbee, Klimaanlage (Midea), ESPHome, Bambu Lab. „Suche in weiteren Netzen“ steht zuletzt.

## 1.39.0 – 06.11.2026
- Neu: **Bambu-Lab-Drucker (Druckstatus).** Unter *Einstellungen → Geräte* (Auswahl „Bambu Lab“) lässt sich ein 3D-Drucker von Bambu Lab (X1C, P1, A1 …) mit Adresse, Seriennummer und Zugangscode anlegen. BlueNexus hält eine Verbindung zum Drucker und zeigt in der Aktorenliste den Zustand („druckt 42 % · noch 1 h 15 min · Düse 220 °C · Bett 60 °C“, „fertig“, „pausiert“, „Fehlermeldung am Drucker“). In Regeln gibt es die Bedingung **druckt / druckt nicht**, ein Druckende („druckt“ wird „druckt nicht“) weckt die Regeln sofort, sodass zum Beispiel ein Chime läuten oder eine Meldung kommen kann. Düsen-, Bett- und Kammertemperatur, Druckfortschritt und Restzeit lassen sich über **Messwert als Sensor** einzeln als Sensoren anlegen. BlueNexus liest nur; der Drucker wird nicht gesteuert. Die Kamera folgt in einem späteren Schritt.

## 1.38.1 – 06.11.2026
- Verbessert: Die Knöpfe der **Eigenen Schalter & Knöpfe (Software)** haben jetzt dieselbe zierliche Symbolgröße wie die der Geräte (Ein/Aus und Drücken), sodass alle Knöpfe einheitlich aussehen.

## 1.38.0 – 06.11.2026
- Neu: **Ein Suchknopf für ESPHome.** „Gerät suchen“ findet bei einem ESPHome-Gerät alles auf einmal: Taster, Klimaanlagen, Schalter und Messwerte stehen in einer gemeinsamen Liste, aus der man auswählt. Die beiden getrennten Knöpfe („Taster, Klima & Schalter suchen“ und „Messwerte suchen“) entfallen, damit man nicht mehr den falschen erwischt.

## 1.37.1 – 06.11.2026
- Verbessert: Der **Test-Knopf der ESPHome-Taster** hat ein kleineres Dreieck in der Farbe und Strichstärke des Ein/Aus-Knopfs, so passt er optisch zu den Nachbarn.
- Intern: Die ESPHome-Geräteverwaltung (Suchen, Anlegen, Neu-Zuordnen) liegt jetzt in einer eigenen Datei und nicht mehr gemischt mit den anderen Geräten im Geräteregister. Am Verhalten ändert sich nichts.

## 1.37.0 – 06.11.2026
- Neu: **ESPHome-Schalter und Relais.** Ein ESPHome-Gerät mit einem Schalter (zum Beispiel ein selbstgebautes Relais) wird mit **Taster, Klima & Schalter suchen** gefunden und als Aktor angelegt. Er lässt sich wie jede Steckdose bedienen: Ein-/Aus-Knopf, Dashboard, Regeln und Automatik, lokal und ohne Cloud. Schaltet jemand am Gerät selbst, folgt BlueNexus sofort. Kommt ein Befehl nicht an, versucht BlueNexus es noch zweimal; bei Ausfall steht „nicht erreichbar“ samt Verbindungsmessung in der Zeile.

## 1.36.0 – 06.11.2026
- Neu: **Test-Knopf für ESPHome-Taster.** In der Aktorenliste hat jeder Taster rechts einen Abspielen-Knopf („Tastendruck auslösen“). Er löst in BlueNexus einen Tastendruck aus, als hätte jemand den Taster gedrückt, sodass Regeln, die auf ihn reagieren, laufen; am Taster selbst wird nichts gesendet. Bei einem Taster ohne Verbindung ist der Knopf grau. PIN, Sichtbarkeit und Rechte wie beim Schalten.

## 1.35.0 – 06.11.2026
- Neu: **Verbindungsmessung für ESPHome-Geräte (Taster).** BlueNexus zählt seit seinem Start, wie oft die Verbindung zu einem Taster abgerissen ist, wie lange er insgesamt und am längsten weg war und wann und warum der letzte Abbruch war (z. B. „Stille“ oder „Verbindung getrennt“). Die Zahlen stehen in der Aktorenliste hinter dem Gerät („3 Abbrüche in 2 h (zusammen 8 s weg, längster 4 s, zuletzt vor 12 min: Stille)“ oder „Verbindung stabil seit 5 h“) und jeder Abbruch im Protokoll. Zusätzlich erkennt BlueNexus **Neustarts des Geräts selbst** an der Betriebszeit, die der Taster in seinen Ping-Meldungen mitschickt („1 Neustart des Geräts (zuletzt vor 20 min)“). Der Zähler beginnt bei jedem Neustart von BlueNexus von vorn.

## 1.34.11 – 06.11.2026
- Fehlerbehebung: **Regeln reagierten mal sofort, mal erst nach bis zu 5 Sekunden** (z. B. Software-Knopf löst Chime aus). Die Regelrunde wartete vor jedem Auslösen auf das **langsamste** der beteiligten Geräte; ein WLAN-Gerät mit kurzem Aussetzer hielt so alle Regeln auf. Jetzt wartet die Runde **höchstens 0,6 Sekunden** auf die Geräte. Wer bis dahin nicht geantwortet hat, zählt mit seinem letzten bekannten Zustand (die Abfrage läuft im Hintergrund weiter). Ein Gerät ohne bekannten Zustand wird weiterhin abgewartet.

## 1.34.10 – 06.11.2026
- Verbessert: **Chime-Läuten aus einer Regel ist schneller.** Der Regelschritt „Chime läuten“ fragte bei jedem Mal erst die Liste der gekoppelten Chimes ab und läutete danach, also zwei Abrufe an die Türklingel hintereinander (der Knopf im Kamerafenster macht nur einen). Jetzt merkt sich BlueNexus die Chime-Nummern (10 Minuten), das Läuten ist ein einziger Abruf, und mehrere Chimes läuten gleichzeitig statt nacheinander. Hat sich ein Chime geändert, wird die Liste automatisch neu geholt.

## 1.34.9 – 06.11.2026
- Fehlerbehebung: **WLAN-Geräte (Tuya, Tasmota, Shelly …) standen kurz auf „nicht erreichbar“**, obwohl sie liefen. Ein einziger verpasster Abruf genügte, und die Anzeige blieb gut 10 Sekunden grau. Jetzt wird ein eben noch erreichbares Gerät bei einem Aussetzer **sofort noch einmal gefragt**; klappt auch das nicht, bleibt der **letzte bekannte Zustand bis zu 45 Sekunden** stehen, erst danach heißt es „nicht erreichbar“. Bei Tuya wird zusätzlich ein zweiter Versuch gemacht und die Wartezeit nach einem Ausfall von 15 auf 6 Sekunden verkürzt.

## 1.34.8 – 05.11.2026
- Fehlerbehebung: Bei der ESPHome-Klimaanlage bot das Klima-Fenster die Lüfterstufen **„Flüster“ und „maximal“** an, obwohl die Anlage sie nicht kann (die ESPHome-Komponente meldet sie immer). Jetzt erscheinen nur noch Automatik, niedrig, mittel und hoch wie bei den Midea-Anlagen.

## 1.34.7 – 04.11.2026
- Fehlerbehebung: **ESPHome-Klimaanlage schaltete sich beim Einstellen ein.** Bei ESPHome ist der Modus zugleich der Ein/Aus-Schalter; wer bei ausgeschalteter Anlage „Heizen“ oder einen Lüfter wählte, startete sie damit. Jetzt gilt wie bei den Midea-Anlagen: **Ist die Anlage aus, wird nur vorgemerkt** (Modus, Soll, Lüfter, Schwenken, Eco); das Klima-Fenster zeigt die Vorwahl, und erst **Einschalten** schickt alles gemeinsam an die Anlage. Ausschalten verwirft die Vorwahl, ebenso das Einschalten per Fernbedienung. Ein Neustart von BlueNexus vergisst die Vorwahl.
- Intern: `t_esphome_ac` prüft Vorwahl, Einschalten mit und ohne eigene Angaben und das Verwerfen.

## 1.34.6 – 04.11.2026
- Geändert: Der Ein/Aus-Knopf in der Aktorenliste hieß beim Daraufzeigen „Testschalten“, obwohl dort alles normal bedient wird. Jetzt steht dort **„Einschalten“** oder **„Ausschalten“**, je nach Zustand, bei reiner Überwachung „Nur Überwachung – nicht schaltbar“.

## 1.34.5 – 04.11.2026
- Geändert: **Bezeichnungen passen sich den eingebundenen Systemen an.** Der Regelschritt heißt „Klimaanlage einstellen (Midea)“, „(ESPHome)“ oder „(Midea, ESPHome)“, je nachdem, was vorhanden ist; die Zeile bei den **Thermostaten** nennt nur Homematic und/oder Zigbee, wenn sie genutzt werden. Der Hinweis bei leeren **Sensoren** nennt auch Tasmota und ESPHome, die Hilfe zum Smart-Home-Modul auch ESPHome.

## 1.34.4 – 04.11.2026
- Geändert: Die Zeile unter der Überschrift **Klimaanlagen** hieß immer „Midea-Klimaanlagen bedienen.“ Jetzt nennt sie nur die Modelle, die wirklich eingebunden sind („Midea und ESPHome-Klimaanlagen bedienen.“, nur „ESPHome-…“, nur „Midea-…“) und lautet ohne Anlage „Klimaanlagen bedienen.“

## 1.34.3 – 04.11.2026
- Fehlerbehebung: **Suche nach einem ESPHome-Gerät mit langsamer Weboberfläche** (z. B. der Klima-Stick) klappte oft nicht oder fand nur einen Teil der Einträge. Die Suche versucht es jetzt bis zu dreimal, wartet länger auf die Einträge und findet sie vollständig.
- Geändert: In der Trefferliste steht bei einer Klimaanlage „Klimaanlage“ statt „Taster“; die Meldungen der Suche nennen Taster und Klimaanlagen.

## 1.34.2 – 04.11.2026
- Fehlerbehebung: **ESPHome-Klimaanlage nach dem Neuflashen.** Meldet das Gerät nach einer neuen Firmware die Klima unter einer anderen Kennung, ordnet BlueNexus den Eintrag wie bei Tastern und Messwerten **von selbst neu zu** (Regeln, Verlauf und Freigaben bleiben). Bis dahin zeigt die Anlage „Klima fehlt am Gerät“ und schaltet nicht ins Leere.
- Fehlerbehebung: Lüfterstufen wie **Silent/Turbo** werden in der Schreibweise des Geräts gesendet (neuere Firmware schreibt sie groß).

## 1.34.1 – 04.11.2026
- Fehlerbehebung: **ESPHome-Klimaanlage – Einschalten schlug fehl**, weil der Stick die Verbindung bei Last ohne Antwort schließt. BlueNexus prüft jetzt nach einem Abbruch, ob der Befehl trotzdem angekommen ist (der Stick meldet den neuen Zustand), und versucht es sonst bis zu dreimal neu.

## 1.34.0 – 04.11.2026
- Neu: **ESPHome-Klimaanlage.** Ein ESPHome-Gerät mit Klima-Entität (z. B. ein Midea-WLAN-Stick mit ESPHome) wird unter *Geräte suchen → ESPHome → Taster & Klima suchen* als Klimaanlage angelegt, lokal und ohne Cloud. Es steht bei den Klimaanlagen und bedient sich wie eine Midea-Anlage: Kachel, Klima-Fenster (Modus, Solltemperatur, Lüfter, Schwenken, Eco), Regelschritt „Klimaanlage einstellen“ und Überschuss-Automatik. Die Midea-Anbindung bleibt daneben unverändert.
- Fehlerbehebung: **Neuere ESPHome-Staende wurden nicht erkannt** („antwortet kein ESPHome-Gerät“). Kennungen wie `sensor-name` statt `sensor/Name`, eine Leerzeile zwischen `event:` und `data:` im Ereignisstrom und die Einheit °C als Ersatzzeichen werden jetzt gelesen. Ältere Geräte funktionieren weiter.
- Intern: neuer Test `t_esphome_ac` (nachgebildeter Stick).

## 1.33.1 – 31.10.2026
- Geändert: **Rauchmelder-Knöpfe melden sich verständlich.** Nach **🚨 Alarm** erscheint kurz „Alarm am Melder ausgelöst“, nach **🛑 Stop** „Alarm beendet“. Das Fenster mit den technischen Angaben entfällt; sie stehen weiter im Protokoll des Servers. Bei einem Fehler steht nur noch, dass der Melder nicht erreichbar ist oder den Befehl nicht angenommen hat.

## 1.33.0 – 31.10.2026
- Neu: **Regelschritt „Rauchmelder: Alarm auslösen / beenden (Homematic)“.** Eine Regel kann den Alarm an einem Homematic-Rauchmelder auslösen (der Melder piepst laut) oder wieder beenden. Der Schritt erscheint, sobald ein Rauchmelder angelegt ist. Ein Rauchmelder, den eine eingeschaltete Regel benutzt, lässt sich nicht löschen; wird er trotzdem entfernt, verschwindet der Schritt aus den Regeln.
- Geändert: Die Knöpfe am Rauchmelder heißen jetzt **🚨 Alarm** und **🛑 Stop** (vorher Piepsen und Ruhe).
- Intern: `t_homematic` prüft den neuen Regelschritt.

## 1.32.2 – 31.10.2026
- Fehlerbehebung: **Rauchmelder piepste nicht.** Die CCU liefert die Befehlsliste des Melders als Text; BlueNexus nahm die Zeichenposition statt der Listenstelle und schickte so einen falschen Wert (19 statt 2). Jetzt wird die Liste richtig gelesen, **Piepsen** und **Ruhe** senden die passenden Werte.

## 1.32.1 – 31.10.2026
- Fehlerbehebung: Der Knopf **🔔 Piepsen** meldete „Melder piepst“, sobald die CCU den Befehl annahm, auch wenn der Melder nichts tat. Jetzt steht ein Fenster mit dem tatsächlich gesendeten Befehl (Name, Wert, Kanal und die Werteliste der CCU), damit sich ein abgelehnter oder wirkungsloser Befehl eingrenzen lässt. Das Protokoll enthält dieselben Angaben.

## 1.32.0 – 30.10.2026
- Neu: **Homematic-Rauchmelder von Hand auslösen.** In *Einstellungen → Sensoren* hat ein Rauchmelder die Knöpfe **🔔 Piepsen** (löst „Einbruch Alarm“ aus, der Melder piepst laut; vorher kommt eine Rückfrage) und **Ruhe** (beendet den Alarm). Braucht das Recht „Sicherheit: Schreiben“. Der Befehlswert wird bei der CCU nachgelesen, falls das nicht klappt, wird der Name gesendet.
- Intern: `t_homematic` prüft Auslösen und Beenden.

## 1.31.0 – 30.10.2026
- Neu: **Homematic-Rauchmelder** (z. B. HmIP-SWSD) erscheinen unter *Sensoren suchen*. Der Sensor zeigt **Alarm** oder **kein Alarm** (Rauch-, Einbruch- und Verbundalarm zählen als Alarm), ist in Regeln, auf dem Dashboard und im Logbuch nutzbar und wird bei Alarm sofort gemeldet, wenn der Push der CCU aktiv ist.
- Intern: `t_homematic` um einen Rauchmelder erweitert.

## 1.30.2 – 30.10.2026
- Fehlerbehebung: **ESPHome-Gerät neu geflasht – Eintrag blieb stumm oder wurde doppelt.** Meldet ein Gerät nach einer neuen Firmware einen Eingang oder Messwert unter einem anderen Namen, meldete der angelegte Eintrag nichts mehr, zeigte aber weiter „bereit“. Jetzt erkennt BlueNexus, dass das Gerät den Eintrag nicht mehr meldet, zeigt **„Eingang fehlt am Gerät“** und ordnet den Eintrag einem eindeutig passenden neuen Namen **von selbst** zu (Kennung, Regeln, Verlauf und Freigaben bleiben erhalten). Passt nichts eindeutig, wird nichts geraten: **Taster suchen** und **Hinzufügen** ordnen dann den einzelnen offenen Eintrag dem neuen Eingang zu, statt ihn doppelt anzulegen. Gilt für Taster und Messwerte.
- Verbesserung: **Zeitmessung am ESPHome-Taster.** Dauert es länger als 1 Sekunde vom Druck bis zum Ende der Regelrunde, steht das im Protokoll des Servers („Druck bis Regelrunde … s, bis Runde fertig … s“). Damit lässt sich eine Verzögerung zwischen Druck und Aktion eingrenzen.
- Handbuch: Hinweise zu `api:` in der ESPHome-Konfiguration (Neustart alle 15 Minuten ohne Home Assistant) und zum Neuflashen eines Geräts.
- Intern: `t_esphome` um Zuordnung, Zeitmessung und Neuflashen (Taster und Messwert) erweitert.

## 1.30.1 – 30.10.2026
- Fehlerbehebung: **Falsche PIN im Bereich Smart Home** verhält sich jetzt wie am Dashboard. Bisher schloss sich das PIN-Fenster nach einer falschen Eingabe mit einer Meldung und einem großen roten Kreuz, und man musste den Knopf neu drücken. Jetzt bleibt das Fenster offen (roter Rahmen, „Falsche PIN – bitte erneut“, Wackeln) und die PIN kann gleich noch einmal eingegeben werden, bis sie stimmt, abgebrochen wird oder der Server nach zu vielen Fehlversuchen sperrt. Gilt für den Testschalter der Aktoren, Wake-on-LAN und die eigenen Schalter & Knöpfe.

## 1.30.0 – 30.10.2026
- Neu: **ESPHome-Messwerte als Sensoren.** Im Fenster *ESPHome* (Geräte suchen) gibt es neben **Taster suchen** jetzt **Messwerte suchen**: Temperatur (°C, °F), Luftfeuchte (%), Leistung (W, kW), Luftdruck (hPa, mbar, kPa, Pa), Helligkeit (lx), Spannung (V) und Funkstärke (dBm) eines ESPHome-Geräts werden zu **Sensoren** mit Dashboard, Verlauf, Regeln und Teilen. Die Werte kommen über dieselbe dauerhafte Verbindung wie beim Taster; nach einem kurzen Abbruch gilt der letzte Wert noch 2 Minuten. Andere Einheiten (z. B. ppm, Akku in %) werden noch nicht angeboten, die Suche nennt ihre Zahl. Nur für Geräte mit Dauerstrom (nicht für Batteriegeräte im Tiefschlaf).
- Neu: **Neue IP-Adresse eines ESPHome-Geräts:** die Suche mit der neuen Adresse wiederholen, die Einträge (Taster und Messwerte) ziehen um.
- Fehlerbehebung: Wird einem schon verbundenen Gerät ein Eintrag hinzugefügt, baut BlueNexus die Verbindung einmal neu auf, damit der Anfangswert ankommt (sonst blieb der neue Sensor bis zur nächsten Änderung leer).
- Intern: `t_esphome` um Messwerte, Einheiten, Umrechnung, fehlende Werte (null), Schonfrist, Verbindung nach Ausfall und IP-Umzug erweitert; geprüft am echten Gerät (WLAN-Signal als Messwert).

## 1.29.2 – 30.10.2026
- Verbesserung: **ESPHome-Taster verbindet nach einem Aussetzer schneller neu** (nach 1 Sekunde statt 3) und erkennt eine tote Verbindung nach 25 statt 45 Sekunden. Beim ESP8266 beendet das Gerät den Ereignis-Strom manchmal von selbst oder verliert das WLAN, ohne die Verbindung zu schließen; in dieser Zeit gehen Tastendrücke verloren. Messung am echten Gerät: Verbindung bricht alle ein bis zwei Minuten ab, Neuaufbau dauert 5 bis 10 Sekunden. Zusätzlich im Handbuch: Empfehlungen für die ESPHome-Konfiguration des Tasters (`power_save_mode: none`, `log: false`).

## 1.29.1 – 30.10.2026
- Verbesserung: **ESPHome-Taster reagiert direkt.** Ein Druck war bisher 5 Sekunden lang „gedrückt“, in dieser Zeit konnte kein zweiter Druck erkannt werden. Jetzt ist ein Druck ein **kurzer Impuls**: Jeder Druck löst genau einen Ablauf aus, auch bei schnell aufeinanderfolgenden Drücken (bis zu 5 wartende Drücke werden nacheinander abgearbeitet). Die Anzeige in der Liste und auf dem Dashboard zeigt „gedrückt“ nur noch 3 Sekunden. Die Verbindung zum Gerät wartet länger auf die Annahme (schwaches WLAN).
- Fehlerbehebung: Änderungsmeldungen eines ESPHome-Geräts enthalten keine Angabe zur Art des Eingangs; solche Meldungen wurden verworfen, Tastendrücke kamen nicht an (1.29.0 am echten Gerät aufgefallen und noch am selben Tag behoben).
- Intern: Test `t_esphome` um schnelle Drücke und eine Ablauf-Regel erweitert.

## 1.29.0 – 30.10.2026
- Neu: **ESPHome-Taster.** Ein Gerät mit ESPHome-Firmware und eingeschalteter Weboberfläche (`web_server`) lässt sich unter *Smart Home → Geräte suchen* über das neue System **ESPHome** (Häkchen bei „Welche Systeme hast du?“) einbinden: IP-Adresse eintragen, **Suchen**, Name und Symbol anpassen, **Hinzufügen**. Der Taster steht danach unter **Aktoren** (nicht schaltbar, Anzeige „bereit“ / „gedrückt“) und auf dem Dashboard und ist in Regeln unter **„Meine Aktoren“** als Bedingung **„wird gedrückt“** nutzbar. BlueNexus hält dafür eine dauerhafte Verbindung zum Gerät und erkennt jeden Druck sofort; nach einem Ausfall verbindet es sich von selbst wieder, ein Druck während des Ausfalls wird nicht nachgeholt. Ein Druck gilt etwa 5 Sekunden als „gedrückt“. Die Eigenen Schalter & Knöpfe (Software) bleiben davon getrennt.
- Intern: Neues Modul `app/esphome.py`, neuer Test `tests/t_esphome.py` mit nachgebildetem ESPHome-Gerät (121 Tests).

## 1.28.6 – 29.10.2026
- Fehlerbehebung: Spricht der **Cloudflare-Tunnel** die App über die **LAN-Adresse des eigenen Rechners** an (im Cloudflare-Dashboard Ziel „IP:Port“ statt `localhost`), wurde seit 1.27.3 die Adresse der Besucher nicht mehr übernommen. Alle Besucher hatten dann dieselbe **Bremse gegen Passwort-Raten** (10 Fehlversuche in 5 Minuten für alle zusammen), und in Logbüchern und Meldungen stand die Adresse des Rechners statt der des Besuchers. Jetzt zählt die Besucher-Adresse aus den Kopfzeilen des Tunnels auch dann, wenn die Anfrage von der **eigenen Adresse des Rechners** kommt (nicht nur von `localhost`). Von anderen Rechnern im Heimnetz werden diese Kopfzeilen weiterhin ignoriert.
- Intern: Neuer Test `tests/t_clientip.py` (120 Tests).

## 1.28.5 – 29.10.2026
- Verbesserung: In der **Wetter-Vorhersage** ist das Symbol vor der Sonnenscheindauer jetzt das **farbige (gelbe) Sonnen-Emoji** ☀️ und genauso groß wie die anderen Symbole der Zeile (💧 💨). Vorher war es ein schmaleres, einfarbiges graues Zeichen.

## 1.28.4 – 29.10.2026
- Sicherheit (Ergebnis der zweiten Nachprüfung): Die **Zugänge zu Zentralen und Clouds** (Homematic-CCU, Zigbee-Gateway, Tuya, Midea-Cloud) und die **Funkthermometer** (anlegen, ändern, löschen, kalibrieren, gemerktes WLAN vergessen) ändert nur noch ein **Administrator**, auch mit Schreibrecht im Bereich. Ansehen bleibt möglich. Hintergrund: Wer die Adresse der CCU änderte, behielt das gespeicherte Passwort, und es ging danach an die neue Adresse. Und beim Anlegen eines Thermometers baute der Server die Konfiguration mit dem gemerkten WLAN-Passwort und gab sie an den Browser des Kontos.
- Intern: Neuer Test `tests/t_sicherheit3.py` (119 Tests).

## 1.28.3 – 29.10.2026
- Sicherheit: **Alles rund um Telegram und Pushover richtet nur noch der Administrator ein**: Bot und Zugang, Empfänger anlegen, ändern und löschen, Chats freigeben oder ablehnen, die Einstellungen der Meldungen und die Test-Nachrichten. Auch mit dem Recht „Einstellungen: Meldungen“ = Schreiben können andere Konten das nicht; Ansehen bleibt möglich. Wer Meldungen bekommen soll, muss dem Bot nur einmal schreiben, den Rest stellt der Administrator ein. (Die Systemempfänger bekommen auch die Codes von „Passwort vergessen“, deshalb ist die Regel bewusst streng.) Die Regel aus 1.28.1, dass Konten mit diesem Recht normale Empfänger anlegen dürfen, entfällt damit.
- Intern: Test `t_sicherheit2` auf die strengere Regel angepasst.

## 1.28.2 – 29.10.2026
- Sicherheit: Bei **Web-Aufrufen** (eigener Knopf mit Adresse und Regel-Schritt „Adresse aufrufen“) darf das Ziel nicht mehr der **Server selbst** sein (`localhost`, `127.0.0.1`, `[::1]`). Geräte im Heimnetz (z. B. `192.168.…`) und Adressen im Internet gehen weiter. Ein manipulierter Aufruf konnte sonst Dienste erreichen, die nur auf dem Server selbst lauschen. Bei Bestandsinstallationen mit einem solchen Ziel meldet das Logbuch „Diese Zieladresse ist nicht erlaubt“.
- Intern: Webhook-Test um die Sperre erweitert.

## 1.28.1 – 29.10.2026
- Sicherheit (Ergebnis der Nachprüfung): **Systemempfänger** (bei Telegram und Pushover die Empfänger, die Systemmeldungen und die Codes von „Passwort vergessen“ bekommen) dürfen nur noch **Administratoren** anlegen, ändern und löschen. Ein Konto mit dem Recht „Einstellungen: Meldungen“ konnte sich bisher als Systemempfänger eintragen, den Code für ein Administratorkonto empfangen und es so übernehmen. Normale Empfänger (z. B. für Regel-Nachrichten) darf weiter anlegen, wer das Recht hat.
- Sicherheit: Den **Telegram-Bot**, den **Pushover-Zugang** und den **VRM-Zugang** ersetzen oder löschen sowie **Module ein- und ausschalten** und die **Zeitzone** ändern dürfen nur Administratoren, auch mit Schreibrecht im jeweiligen Bereich. Ansehen bleibt wie bisher möglich.
- Sicherheit: Anmeldungen aus der Zeit vor 1.28.0 (Cookie ohne Kennung) gelten nur noch für Konten, die damals schon bestanden, und nur solange sich das Passwort seitdem nicht geändert hat. Bisher blieben solche Cookies auch nach einer Passwortänderung oder für ein neu angelegtes gleichnamiges Konto gültig. Niemand wird durch das Update abgemeldet.
- Sicherheit: **Gerätekennungen** (MAC, Adresse, Seriennummer), die ein Gerät oder eine Zentrale selbst meldet (Shelly, Tasmota, WLED, Homematic, Zigbee, Tuya), enthalten nur noch Buchstaben, Ziffern und `. _ : -`. Normale Kennungen bleiben unverändert, bestehende Geräte ebenfalls. Damit kann ein manipuliertes Gerät im Heimnetz keine Zeichen in Seiten und Adressen einschmuggeln.
- Intern: Neuer Test `tests/t_sicherheit2.py` (118 Tests).

## 1.28.0 – 29.10.2026
- Sicherheit: **Sitzungen enden jetzt, wenn sich das Passwort eines Kontos ändert.** Bisher blieb ein Gerät, auf dem man einmal angemeldet war, bis zu ein Jahr angemeldet – auch nach einer Passwortänderung (z. B. ein verlorenes Handy oder ein fremder Rechner). Jetzt werden nach jeder Passwortänderung (selbst unter *Konto & Zugang*, durch den Administrator unter *Weitere Benutzer*, über *Passwort vergessen* und mit `reset_password.py`) alle **anderen** Geräte abgemeldet. Das Gerät, an dem man sein eigenes Passwort ändert, bleibt angemeldet.
- Sicherheit: Löscht man ein Konto und legt später eines **mit demselben Namen** neu an (oder vergibt den alten Namen nach einer Umbenennung neu), erbt das neue Konto nicht mehr die Anmeldung des alten. Jedes Konto bekommt dazu beim Anlegen eine zufällige Kennung.
- Hinweis zum Update: Wer schon angemeldet ist, bleibt angemeldet (bestehende Anmeldungen gelten einmalig weiter und bekommen die neue Kennung). Wer sichergehen will, dass ein früher verlorenes Gerät abgemeldet ist, ändert einmal das Passwort des Kontos.
- Intern: Neuer Test `tests/t_sitzung.py` (117 Tests).

## 1.27.3 – 29.10.2026
- Sicherheit (Ergebnis einer Prüfung des Codes, keine Lücke mit bekanntem Missbrauch): Die **Geräteübersicht** (Einstellungen → System) ist wirklich nur für Administratoren. Bisher sah sie auch ein normales Konto, dem nur das Ansehen der Benutzerliste erlaubt war (Gerätenamen mit IP und MAC).
- Sicherheit: **App aktualisieren, Fernzugriff (Tunnel-Token, ein/aus, cloudflared installieren und aktualisieren) und Testmodus ändern** dürfen nur Administratoren, auch wenn ein Konto im Bereich System Schreibrecht hat. Ansehen bleibt wie bisher möglich.
- Sicherheit: Die **Bremse gegen Passwort-Raten** ließ sich umgehen, wenn man die App direkt im Heimnetz erreichte und selbst eine Absenderadresse in die Anfrage schrieb. Die Absenderadresse aus den Kopfzeilen des Fernzugriffs zählt jetzt nur noch, wenn die Anfrage vom Tunnel bzw. Webserver auf demselben Rechner kommt. Über den Fernzugriff hat weiterhin jeder Besucher seine eigene Bremse.
- Sicherheit: Die **Adresse einer Kamera** wird beim Ändern genauso geprüft wie beim Anlegen (keine Zeichen wie `/ @ ? #`).
- Sicherheit: Die **Alexa-Bridge** sendet keine offene Kopfzeile `Access-Control-Allow-Origin: *` mehr. Echo-Geräte brauchen sie nicht.
- Intern: Neuer Test mit allen Punkten (`tests/t_sicherheit.py`, 116 Tests) und eine Liste, welche Endpunkte unter „Benutzerverwaltung“ hängen; neue Einträge brauchen eine bewusste Entscheidung.

## 1.27.2 – 29.10.2026
- Fehlerbehebung: Das **Kalender-Symbol** in der Benutzerliste ist jetzt genauso groß wie die anderen Symbole der Zeile (Knopfgröße, Symbolgröße und Höhe passen zu 🛠️ 👁 ⧉ 🔑).

## 1.27.1 – 29.10.2026
- Verbesserung: In der **Benutzerliste** braucht der Ablauf eines Kontos keine eigene Spalte mehr. Stattdessen sitzt in jeder Zeile ein **Kalender-Symbol**: **weiß** = läuft nie ab, **orange** = hat ein Ablaufdatum, **rot** = ist abgelaufen (das Konto kann sich nicht mehr anmelden). Ein Klick öffnet ein kleines Fenster, in dem man das Datum wählt und speichert oder mit **Kein Ablauf** wieder entfernt; der Mauszeiger-Text zeigt das Datum. Die Liste hat dadurch mehr Platz für die Rechte. Administratoren laufen nie ab und haben kein Symbol.

## 1.27.0 – 29.10.2026
- Neu: In der **Benutzerliste** (Einstellungen → Konto & Benutzer) zeigt die neue Spalte **Zuletzt aktiv**, wann ein Konto zuletzt etwas bedient hat. **Letzter Login** zeigt weiterhin nur, wann zuletzt das Passwort eingegeben wurde – wer angemeldet bleibt, meldet sich nicht neu an, deshalb war dieses Datum oft alt. Gezählt wird echte Bedienung (eine Seite öffnen, schalten, speichern oder drücken), nicht die Abfragen im Hintergrund eines offen gelassenen Dashboards und nicht die Vorschau eines Administrators. Der Wert ist auf etwa 10 Minuten genau (es wird höchstens alle 10 Minuten gespeichert). Bei Konten, die seit dem Update noch nichts bedient haben, steht „–“.
- Intern: Die Testsammlung (jetzt 115 Tests) liegt im Repo unter `tests/` (`python tests/run_all.py`); zwei ungenutzte Funktionen entfernt. Am Verhalten der App ändert sich dadurch nichts.

## 1.26.17 – 28.10.2026
- Verbesserung: Bei **allen Fenstern** der App (Dialoge, Auswahl- und Einstellungsfenster, Farbwähler, PIN-Eingabe, Kamera-Vollbild, Geräteübersicht) scrollt die Seite dahinter nicht mehr mit dem Mausrad mit. Die Seite wird festgehalten, solange ein Fenster offen ist, und danach an derselben Stelle wieder freigegeben. Erkannt wird das automatisch, einzelne Fenster müssen nichts dafür tun.

## 1.26.16 – 28.10.2026
- Fehlerbehebung: Bei geöffneter **Geräteübersicht** scrollt die Seite dahinter nicht mehr mit, wenn man am Anfang oder Ende der Liste weiter mit dem Mausrad dreht. Die Seite wird, solange das Fenster offen ist, festgehalten und danach an derselben Stelle freigegeben.

## 1.26.15 – 28.10.2026
- Verbesserung: Die **Geräteübersicht** ist nicht mehr dauerhaft aufgeklappt, sondern öffnet sich per Knopf **Geräteübersicht öffnen** in einem eigenen Fenster (schließen mit ✕, Esc oder Klick daneben). Die Spalten (IP-Adresse, Name, Art, MAC, Hinweis) lassen sich per Klick auf die Überschrift **auf- und absteigend sortieren**; die IP-Adressen werden dabei nach Zahlen sortiert, Einträge ohne IP stehen am Ende. Kopieren und CSV übernehmen die aktuelle Suche und Sortierung.

## 1.26.14 – 28.10.2026
- Fehlerbehebung: In der Geräteübersicht stehen **Zigbee-Geräte** (hinter dem Gateway) und **Homematic-Geräte** (hinter der CCU) nicht mehr mit einer scheinbaren IP-Adresse, sondern am Ende der Liste mit dem Hinweis „über Gateway …“ bzw. „Adresse …“. Mehrkanalige Homematic-Geräte lösen keine Warnung „doppelte IP-Adresse“ mehr aus.

## 1.26.13 – 28.10.2026
- Neu: **Geräteübersicht** unter *Einstellungen → System* (nur Administratoren): alle Geräte mit IP-Adresse (Steckdosen und Schalter, Klimaanlagen, Kameras, Zigbee-Gateways, Homematic-Zentrale, Wake-on-LAN-Rechner, Cerbo GX, Funkthermometer), sortiert nach IP, mit Suche, Kopieren und CSV-Export. Doppelt vergebene IP-Adressen werden markiert. Es werden nie Passwörter oder Schlüssel ausgegeben.

## 1.26.12 – 28.10.2026
- Fehlerbehebung: Die Tuya-Suche durchsucht jetzt **immer auch das eigene Netz des Servers** per Verbindungsversuch – bisher nur bei leerer Liste „Weitere Netze“. War dort ein Netz eingetragen, wurde das eigene Netz nur per Broadcast abgedeckt, und manche (neue oder besonders gesprächige) Geräte kamen mit „im Heimnetz nicht gefunden“ zurück.

## 1.26.11 – 28.10.2026
- Verbesserung: Die Tuya-Suche meldet genauer, was die Tuya-Cloud geliefert hat: „keine Geräte geliefert“ (Verknüpfung/Region prüfen) oder „Geräte ohne Schlüssel“ (Zugangsdaten/API-Dienste prüfen). Bisher kam in beiden Fällen nur „keine Geräte gefunden“. Die Anzahl steht zusätzlich im Betriebsbericht-Protokoll.

## 1.26.10 – 28.10.2026
- Verbesserung: Die Meldung bei einer Klimaanlage, die mehrmals die Anmeldung ablehnt, ist verständlicher: Sie sagt jetzt, dass das meist nur eine kurze Schwäche des WLAN-Moduls ist und von selbst vergeht, und nennt den Schlüssel nur noch als Ausweg, wenn es dauerhaft so bleibt oder die Anlage neu gekoppelt wurde.

## 1.26.9 – 28.10.2026
- Fehlerbehebung: In Verlaufs-Diagrammen **bleiben ausgeblendete Reihen ausgeblendet** (Klick auf die Legende). Bisher wurden sie bei jedem neuen Messwert wieder eingeblendet.
- Fehlerbehebung: Das Diagramm-Skript wird mit der Programmversion geladen (`?v=`), damit nach einem Update nicht noch die alte Fassung aus dem Zwischenspeicher läuft (dann fehlte die minutengenaue, interpolierte Anzeige im Infokasten).

## 1.26.8 – 28.10.2026
- Verbesserung: Der Infokasten in Linien- und Flächendiagrammen **interpoliert** jetzt zwischen zwei Messpunkten – der angezeigte Wert liegt genau auf der gezeichneten Linie. Stufenreihen, An/Aus-Werte, Punkt- und Balkendiagramme zeigen weiter den letzten bekannten Wert.

## 1.26.7 – 28.10.2026
- Verbesserung: Der Infokasten in Verlaufs-Diagrammen (Linien, Punkte, Stufen) zeigt jetzt an jeder Stelle **alle** Reihen mit ihrem **letzten bekannten Wert** links vom Mauszeiger – nicht mehr nur dort, wo gerade ein eigener Messpunkt liegt. Die Uhrzeit im Kasten folgt der Mausposition. Balken- und gestapelte Diagramme bleiben unverändert.

## 1.26.6 – 28.10.2026
- Verbesserung: Das Smart-Home-**Logbuch** zeigt jetzt auch Telegram-Nachrichten, die nichts ausgelöst haben: ein **unbekanntes Wort** eines freigegebenen Empfängers („unbekanntes Wort „toll“ von Michael – nichts ausgelöst“), eine **Rückfrage** (wartet auf „ja“) und ein **Abbruch** mit „nein“. Bisher standen sie nur im Betriebsbericht.

## 1.26.5 – 28.10.2026
- Fix: Nach einem Update lädt die Seite erst dann neu, wenn die App **über denselben Weg** (z. B. den Cloudflare-Tunnel) wieder richtig antwortet: mindestens 20 Sekunden Anzeige, die Versionsnummer hat sich geändert und zwei gültige Antworten in Folge. Eine Cloudflare-Fehlerseite oder ein Verbindungsfehler zählt nicht. So erscheint die Fehlerseite „nicht erreichbar“ nicht mehr, weil die Seite zu früh neu lädt.

## 1.26.4 – 28.10.2026
- Verbesserung: Nach einem erfolgreichen Update im System-Reiter verschwinden die Knöpfe „Jetzt aktualisieren“ und „Nach Updates suchen“; stattdessen steht groß eine grüne Meldung mit Kreisel: „Aktualisiert – die App startet jetzt neu“. Die Seite lädt selbst neu, sobald die App wieder antwortet (statt nach fester Zeit), bei Verzögerung gibt es einen Hinweis.

## 1.26.3 – 28.10.2026
- Änderung: Bei falscher PIN **dreht** sich das PIN-Feld kurz hin und her und klingt ab (statt seitlich zu rutschen).
- Fix: Sobald man die **erste Ziffer** eingibt, verschwinden der rote Rahmen und die Warnung. Die **Erfolgsmeldung** hat danach wieder den normalen Rahmen (der rote Rahmen blieb vorher stehen).

## 1.26.2 – 28.10.2026
- Verbesserung: Bei einer **falschen PIN** zeigt das PIN-Feld die Meldung jetzt deutlich: roter Rahmen, rote Fettschrift „✗ Falsche PIN – bitte erneut“, rote Kreise, kurzes Wackeln des Feldes und am Handy ein kurzer Vibrationsimpuls.

## 1.26.1 – 28.10.2026
- Änderung: Die Erfolgsmeldung im PIN-Feld (grüner Haken „Befehl angenommen“) bleibt **eine Sekunde länger** sichtbar (2,1 s statt 1,1 s). Die Fehleranzeige (rotes Kreuz) bleibt bei 1,9 s.

## 1.26.0 – 28.10.2026
- Neu: **Thermometer neu flashen, ohne es zu verlieren.** Beim Thermometer gibt es den Knopf „Neu flashen“ (und im Formular die Auswahl „Einrichten für“). Das Gerät behält ID, Sensoren, Aufzeichnung in den Verläufen, Regeln und Abgleich; nur der Schlüssel wird erneuert, der alte gilt bis zur ersten Meldung mit dem neuen weiter. Bisher entstand bei jedem Flashen ein neues Thermometer mit neuen Sensoren, die Aufzeichnung der alten brach ab.
- Fehlgeschlagenes Neu-Flashen löscht ein vorhandenes Thermometer nie.

## 1.25.0 – 27.10.2026
- Firmware 1.1.1 (im Flash-Fenster mitgeliefert): wählt den **Access Point mit dem stärksten Signal** (die Bibliothek nahm bisher den ersten gefundenen mit gleichem Namen und merkte ihn sich – bei mehreren Access Points oft einen weit entfernten) und gibt vor dem Tiefschlaf die letzten Diagnosezeilen noch aus.
- Neu: Die Liste zeigt **an welchem Access Point** das Thermometer hängt („AP aa:bb:cc:…“) – ab Firmware 1.1.1.
- Thermometer mit Firmware 1.1.0 laufen weiter; für den Access-Point-Fix einmal neu flashen.

## 1.24.0 – 27.10.2026
- Neu: **Farbwähler mit „Übernehmen“** im Diagramm-Dialog der Verläufe (PC und Handy): Palette, eigene Farbe über Regler oder Hex-Wert, „Standard“, „Abbrechen“. Der Farbwähler des Browsers ließ sich nicht bestätigen, und ein Klick daneben hakte versehentlich eine andere Reihe an.

## 1.23.2 – 27.10.2026
- Änderung: In den Verläufen heißt „⚙ Datenreihen“ jetzt **„⚙ Messwerte“** („Neuen Messwert hinzufügen“), und der Knopf steht **vor** „＋ Diagramm“ (erst die Messwerte festlegen, dann das Diagramm anlegen).

## 1.23.1 – 27.10.2026
- Verbesserung: In *Verläufe → Datenreihen* hebt sich der Bereich zum **Hinzufügen** jetzt deutlich von der Liste ab (blau umrandete Fläche mit Überschrift „Neue Datenreihe hinzufügen“, farbiger Knopf „Aufzeichnen“); die Liste darunter hat eine eigene Überschrift „Das wird aufgezeichnet (Anzahl)“.

## 1.23.0 – 27.10.2026
- Neu: **Meldungen für Funkthermometer** per Telegram/Pushover: „meldet sich nicht mehr“ (nach 3 verpassten Meldungen, mit Meldung beim Wiederkommen) und „Batterie bald wechseln“ (zweimal in Folge unter 3,0 V, nur mit verdrahteter Batteriemessung). Beides in den Einstellungen unter Meldungen einzeln abschaltbar.
- Der Knopf „Etikett“ ist jetzt auch am PC zu sehen und erklärt dort, dass das Drucken am Android-Handy geht (vorher war er am PC ausgeblendet).

## 1.22.0 – 27.10.2026
- Fix (Firmware 1.1.0, im Flash-Fenster mitgeliefert): Das Thermometer legte sich nach der ersten Meldung teils für **6 Stunden** schlafen, ohne zu senden, weil ein nicht verdrahteter Batterie-Messeingang Zufallswerte liefert und die Firmware sie für eine leere Batterie hielt. Jetzt zählt „Batterie leer“ nur bei glaubhaften Werten (1,8 bis 2,75 V) und erst nach drei Aufwachen in Folge (bzw. zwei Brownouts).
- Firmware 1.1.0: **keine 5 Minuten Wachzeit** und **kein Einrichtungs-WLAN** mehr (eingerichtet wird nur am PC); nach RESET zeigt die blaue LED das Ergebnis (3× kurz = gesendet, 1× lang = Fehler). Ohne gültige Konfiguration blinkt sie eine Minute schnell und schläft.
- Neu: Die Liste zeigt „Aufwachen Nr. … (Zeitgeber / RESET-Taste / …)“ (ab Firmware 1.1) – daran sieht man, ob der Zeitgeber ankommt.
- Thermometer mit Firmware 1.0.x bitte einmal neu flashen („Einrichten und flashen“; ein vorhandener Eintrag kann vorher mit ✕ entfernt werden).

## 1.21.0 – 27.10.2026
- Neu: **Messintervall** pro Funkthermometer einstellbar (Knopf „Intervall“, 1 bis 60 Minuten) – zum Testen oder Abgleichen kurz, sonst 15 Minuten. Bis das Thermometer den neuen Wert geholt hat, gilt für „meldet sich nicht mehr“ das bisher gemeldete Intervall.

## 1.20.0 – 27.10.2026
- Neu: **Etikett fürs Thermometer-Gehäuse.** Der Knopf „Etikett“ am Funkthermometer druckt auf dem Niimbot-Drucker ein Etikett mit Namen, Geräte-ID und QR-Code (Android-Handy, Chrome, https – wie bei den NFC-Tags). Der QR-Code öffnet das Thermometer in BlueNexus (Zeile wird hervorgehoben).
- Das Etikettenfenster unterstützt eine kleine zweite Zeile unter dem Namen sowie eigene Titel und Erklärtexte (für weitere Verwendungen).

## 1.19.0 – 27.10.2026
- Neu: **Abgleichen (Kalibrieren)** beim Funkthermometer: Referenz-Temperatur und/oder -Luftfeuchte eintragen, BlueNexus rechnet den Korrekturwert aus und wendet ihn auf alle künftigen Messungen an (Sensoren, Regeln, Diagramme). Nur mit frischer Messung (höchstens 5 Minuten; RESET-Taste am Thermometer misst sofort neu), mit Plausibilitätsgrenzen (±10 °C, ±30 %) und „Abgleich löschen“. Die Liste zeigt den Korrekturwert.

## 1.18.0 – 27.10.2026
- Änderung: Nach dem Flashen erscheint ein **großes Fenster „Jetzt die RESET-Taste am Thermometer drücken“** (pulsierende Taste, Zähler, nach 30 Sekunden der Hinweis „noch einmal drücken“, Abbrechen), damit der Schritt nicht zu übersehen ist. Es schließt sich mit „Thermometer verbunden“ von selbst.
- Änderung: Das Funkthermometer wird **nur noch am PC** eingerichtet (anstecken, einmalig anlernen). Die Einrichtung ohne PC (Zugangsdaten zum Abtippen, Hotspot am Handy) und „Neuer Schlüssel“ entfallen; das Anlegen ohne WLAN-Angaben wird abgelehnt.
- Änderung: Der Knopf „Zurücksetzen …“ heißt jetzt **„ESP32 löschen“**.

## 1.17.3 – 27.10.2026
- Änderung: Beim Funkthermometer entfallen die automatischen Neustart-Versuche nach dem Flashen (am echten Board wirkte keiner: RTS-, Soft- und Hard-Reset). Das Fenster fordert sofort zum Druck auf die **RESET-Taste** auf, wartet bis 90 Sekunden und weist nach 30 Sekunden darauf hin, die Taste noch einmal zu drücken.

## 1.17.2 – 27.10.2026
- Verbesserung: Nach dem Flashen probiert das Funkthermometer-Fenster mehrere **Neustart-Verfahren** nacheinander (RTS-Reset, Soft-Reset, Hard-Reset) und prüft nach jedem, ob sich das Thermometer meldet; das erste, das wirkt, steht im Fenster. Wirkt keins, kommt die Aufforderung zur **RESET-Taste** am Board sofort.

## 1.17.1 – 27.10.2026
- Fix: Nach einem Update zeigte die installierte Web-App teils noch die **alte Skriptdatei** aus dem Zwischenspeicher („BNXC is not defined“ im Funkthermometer-Fenster). Das Skript wird jetzt mit der Versionsnummer angefordert (`?v=…`), sodass der Browser nach jedem Update die neue Datei holt; der Zwischenspeicher der App wurde dafür einmal geleert.

## 1.17.0 – 27.10.2026
- Neu: **WLAN merken** beim Funkthermometer. Mit dem Haken „WLAN für weitere Thermometer merken“ speichert BlueNexus Name und Passwort des WLANs auf dem Server (nur Administratoren, Teil der Sicherung); bei weiteren Thermometern ist es vorbelegt und das Passwortfeld bleibt leer. „Gemerktes WLAN vergessen“ löscht es wieder. Das Passwort wird nie an die Oberfläche zurückgegeben.
- Die Konfiguration des Geräts (cfg.bin) baut jetzt der **Server** (bytegleich zur Referenz des Thermometer-Projekts); Eingabefehler werden geprüft, bevor ein Thermometer angelegt wird.
- Rückfrage, wenn weder ein Passwort eingetragen noch eins gemerkt ist (ein offenes WLAN ist selten; sonst kann sich das Thermometer nicht verbinden).
- Das Passwortfeld wird nach dem Flashen nicht mehr geleert; die Wartezeit auf die erste Messung ist auf 60 Sekunden verkürzt, nach 20 Sekunden erscheint der Hinweis auf die RESET-Taste.

## 1.16.2 – 27.10.2026
- Fix: Das Funkthermometer startet nach dem Flashen jetzt **von allein neu** (vorher blieb der Chip im Download-Modus stehen, bis man das USB-Kabel zog). Der Neustart zieht den Chip jetzt zuerst in den Reset und lässt ihn dann los.

## 1.16.1 – 27.10.2026
- Neu: **Diagnose beim Funkthermometer.** Meldet sich ein frisch geflashtes Thermometer nicht, sagt das Fenster, ob überhaupt eine Anfrage angekommen ist (und warum sie abgelehnt wurde: falscher Schlüssel, außerhalb des lokalen Netzes, ungültige Daten) oder ob nichts ankam (Chip nicht neu gestartet, WLAN, Adresse). Die Liste zeigt den letzten abgelehnten Versuch; während des Wartens steht der Hinweis auf die RESET-Taste.

## 1.16.0 – 27.10.2026
- Neu: **Funkthermometer (ESP32-C3) einrichten und flashen** unter *Einstellungen → System*: WLAN-Name und -Passwort eintragen, **Einrichten und flashen** – BlueNexus legt das Thermometer an (ID + Schlüssel), spielt die Firmware per USB (Web Serial, Chrome/Edge) auf die Platine, schreibt die Konfiguration und wartet auf die erste Messung. Das WLAN-Passwort verlässt den Browser nicht.
- Neu: Das Thermometer erscheint mit vier **Sensoren** (Temperatur, Luftfeuchte, Batterie, Funkstärke) unter Smart Home → Sensoren; nach 3 verpassten Meldungen gelten sie als „nicht erreichbar“. Annahme der Messwerte unter `POST /api/sensor/<ID>` (nur lokales Netz, Schlüssel-Hash, Bremse).
- Neu: **Ohne PC einrichten** (ID und Schlüssel zum Abtippen), **Zurücksetzen** (Chip löschen), Umbenennen, neuer Schlüssel, Entfernen.
- Neu: Sensorarten „Spannung“ (V) und „Funkstärke“ (dBm); Batteriespannung mit zwei Nachkommastellen.

## 1.15.1 – 27.10.2026
- Fix: **[WER]** und „bedient von“ funktionieren jetzt auch über **Regel-Ketten**: Löst ein Konto einen Knopf aus, schaltet daraufhin eine Regel einen Taster, und eine zweite Regel meldet „Taster ist an“, wird das Konto am Anfang der Kette genannt (vorher „unbekannt“).
- Fix: Schritte eines **Ablaufs** (z. B. Taster einschalten) stehen im Geräte-Logbuch jetzt als **Regel „Name“** statt „System“.

## 1.15.0 – 27.10.2026
- Verbesserung: Der **Hardware-Monitor** läuft jetzt **live** (alle 3 Sekunden, solange der Betriebsbericht offen ist) und zeigt kleine Verlaufslinien der letzten Minuten.
- Neu: echte **Prozessor-Auslastung** in % der zugewiesenen Kerne, dazu der Anteil von BlueNexus selbst. In Containern (z. B. Proxmox) war die „Last“ der Wert des ganzen Servers und wirkte deshalb zu hoch; sie steht jetzt als „Systemlast“ mit Erklärung und wird im Container nicht mehr bewertet.
- Jede Kachel hat ein Fragezeichen mit Erklärung. Viel Auslagerung bei reichlich freiem Speicher löst keine Warnung mehr aus.

## 1.14.0 – 27.10.2026
- Neu: **Hardware-Monitor** im Betriebsbericht (bei jeder Installation, auch ohne Energie): freier Arbeitsspeicher und Anteil von BlueNexus, Prozessor-Last, Temperatur, Auslagerung (Swap), Speicherplatz und Laufzeit als Kacheln mit Farbbalken, dazu die Prüfung „Hardware“ (Warnung bei knappem Speicher, Hitze, Überlast; beim Raspberry Pi auch Unterspannung/Drosselung). Erscheint auch im Text zum Kopieren. Ohne Linux-Werte (z. B. Entwicklung unter Windows) entfällt der Block.

## 1.13.2 – 27.10.2026
- Fix: Der **Betriebsbericht** zeigt ohne das Modul Energie nichts mehr aus der Energie-Regelung: kein Akku/ESS/Strategie, keine Tagesbilanz mit Preisen und Prognosen, keine Durchlauf-Fehler/Unterbrechungen, keine Regler-Einstellungen und keine Energie-Ereignisse. Auch der Text zum Kopieren ist entsprechend kürzer.
- Fix: Beschreibungen unter *Betriebsbericht* und *Pushover* erwähnen Regelung, Preise und Kamerabild nur noch, wenn das jeweilige Modul eingeschaltet ist.
- Fix: Die Sichtbarkeits-Übersicht in der Benutzerverwaltung listet Geräte/Schalter/Sensoren nur mit Modul Smart Home und Kameras nur mit Modul Kameras.

## 1.13.1 – 27.10.2026
- Verbesserung: Das **PIN-Feld** bleibt nach der vierten Ziffer kurz offen und zeigt das Ergebnis: „Wird gesendet …“, dann ein **grüner Haken** mit „Befehl angenommen“ bzw. ein rotes Kreuz mit der Fehlermeldung; danach blendet es sich selbst aus. Gilt für Geräte, eigene Schalter/Knöpfe und Wake-on-LAN (Dashboard, Favoriten, Smart Home).

## 1.13.0 – 27.10.2026
- Neu: In Regeln lässt sich festlegen, **wer** etwas bedient hat. Geräte und Schalter in der Bedingung WENN haben die Option **„bedient von“** (Konten ankreuzen), und im Text einer Telegram- oder Pushover-Nachricht ersetzt der Platzhalter **[WER]** den Namen des Kontos, das den Auslöser zuletzt bedient hat (z. B. „Toröffner betätigt von [WER]“).
- Das Geräte-Logbuch merkt sich dazu den Anmeldenamen des Kontos.

## 1.12.4 – 27.10.2026
- Änderung: **Dunkel** ist jetzt die Standard-Darstellung. Wer bisher auf „Automatisch“ stand (nie umgestellt), sieht dunkel; Hell und Automatisch bleiben unter *Einstellungen → Dashboard → Darstellung* wählbar.

## 1.12.3 – 27.10.2026
- Fix: Die **Nulllinie** in den Diagrammen wird jetzt immer gezeichnet, auch wenn die Achse bei 0 keine Beschriftung hat (z. B. −500 / 500 / 1.500).

## 1.12.2 – 27.10.2026
- Verbesserung: In den Diagrammen ist die **Nulllinie** jetzt deutlich stärker und heller gezeichnet, damit Bezug und Einspeisung besser zu unterscheiden sind.

## 1.12.1 – 26.10.2026
- Fix: Die Symbol-Auswahl klappt jetzt überall vollständig auf (Aktoren, Thermostate, Schlösser, Rechner, Soundmodule, Rollläden, Geräte suchen) – wie bei den Sensoren, ohne eigene Bildlaufleiste.

## 1.12.0 – 26.10.2026
- Neu: deutlich größere **Symbol-Auswahl** (rund 340 statt 165): Haus und Werkzeug, Technik und Geräte, Wetter, Pflanzen, Fahrzeuge, Küche, Tiere, Feier und Büro, Warn- und Statuszeichen. Alle Symbole sind so gewählt, dass sie auf Android und iPhone dargestellt werden (Emoji bis Version 12).

## 1.11.3 – 26.10.2026
- Fix: Symbole, die ältere Android- und iPhone-Versionen nicht kennen (auf dem Handy nur ein Kästchen mit Kreuz, z. B. das Ein-/Aus-Zeichen ⏻), sind aus der Auswahl entfernt. Es stehen nur noch Symbole bis Emoji 12 zur Wahl (Android 10 / iOS 13). Bereits gespeicherte Symbole dieser Art werden beim Start durch gängige ersetzt; das Rollladen-Standardsymbol ist jetzt 🏠.

## 1.11.2 – 26.10.2026
- Fix: Administratoren haben das Logbuch und Wake-on-LAN jetzt unabhängig vom gespeicherten Stand immer. Bei einem Administrator, dessen Rechte zwischen 1.11.0 und 1.11.1 gespeichert wurden, stand dort „Kein“, und der Reiter Logbuch fehlte.

## 1.11.1 – 26.10.2026
- Fix: Nach dem Update auf 1.11.0 fehlte Administratoren aus älteren Versionen der Reiter Logbuch (das neue Recht war bei ihnen noch nicht gesetzt). Bestehende Administratoren behalten das Logbuch jetzt automatisch, andere Konten weiterhin nicht.

## 1.11.0 – 26.10.2026
- Neu: eigenes Recht **Logbuch** je Konto (Smart Home). Ohne das Recht bleibt es wie bisher nur für Administratoren; mit **Lesen** sieht ein Konto im Reiter Logbuch die Einträge zu den ihm freigegebenen Geräten.

## 1.10.0 – 26.10.2026
- Neu: eigenes Recht **Wake-on-LAN** je Konto (Kein / Lesen / Schreiben) in der Benutzerverwaltung. Lesen = freigegebene Rechner ansehen, Schreiben = aufwecken. Bei „Kein“ oder ohne freigegebenen Rechner sieht das Konto den Reiter und die Rechner auf dem Dashboard nicht mehr. Bestehende Konten behalten ihr bisheriges Recht.

## 1.9.4 – 26.10.2026
- Fix: Die Erklärtexte unter **Aktoren** und **Sensoren** passen sich an: Konten lesen nichts von PIN-Schutz, und die Sensor-Quellen (Homematic, Zigbee, Tasmota, Kameras) stehen nur, wenn sie eingerichtet sind.

## 1.9.3 – 26.10.2026
- Änderung: Der Dashboard-Haken (Auge) eines Administrators an Geräten, Sensoren und Schaltern gilt nur noch für sein eigenes Dashboard. Was einem Konto freigegeben ist, erscheint dort; ob es auf dem eigenen Dashboard gezeigt wird, entscheidet das Konto selbst mit seinem Auge. (Ersetzt die Korrekturen aus 1.9.1/1.9.2.)

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
