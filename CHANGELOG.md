# Änderungsprotokoll

Hier steht, was sich in welcher Version geändert hat. Die Versionsnummer steht in der App unter *Einstellungen → System* („Installierte Version“), in `app/VERSION` und als Tag/Release auf GitHub (`v1.6.0` …).

**Zählweise:** `1.x.0` = neue Funktionen, `1.x.y` = Fehlerbehebungen und Kleinigkeiten. Die genauen Einzeländerungen stehen im Verlauf der Commits.

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
