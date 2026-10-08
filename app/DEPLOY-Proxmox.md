# BlueNexus – Betrieb auf einem eigenen Linux-Server (pm2)

Für alle, die BlueNexus nicht mit dem Ein-Befehl-Installer (siehe README) auf einem Raspberry Pi einrichten,
sondern auf einem vorhandenen Linux-Server (z. B. Proxmox-Container, Debian/Ubuntu) mit **pm2** betreiben wollen.

Erreichbar danach unter `http://<server-ip>:5005`.

## Voraussetzungen
- Linux mit Python 3.9 oder neuer, `git`, `node`/`npm` (für pm2: `npm install -g pm2`).
- Ein freier Port (Standard **5005**, änderbar über die Umgebungsvariable `PORT`).

## 1. Code per Git holen (ermöglicht In-App-Updates)

Statt Dateien zu kopieren wird **geklont** – so funktioniert der Update-Knopf in der App.

```bash
cd /root
git clone https://github.com/Micha-3582/BlueNexus.git
```

Ergebnis: `/root/BlueNexus/app/...`

## 2. Python-Umgebung

```bash
cd /root/BlueNexus/app
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

## 3. Unter pm2 starten

```bash
cd /root/BlueNexus/app
pm2 start ecosystem.config.js
pm2 save
pm2 list
```

`pm2 save` nicht vergessen – sonst ist die App nach einem Neustart des Servers weg (zusätzlich einmal `pm2 startup` ausführen).

## 4. Einrichten

Browser: **http://<server-ip>:5005** → der Einrichtungsassistent führt durch Vorname, Anlage und Zugänge.
Alle Einstellungen liegen danach in `app/` (z. B. `config.json`), bleiben bei Updates erhalten und sind nicht im Git.

Wer eine **Victron-ESS-Anlage** hat: Zum Start bleibt der **Trockenlauf AN** (Einstellungen → System). Erst nach einem
Parallelvergleich mit einer bisherigen Steuerung scharfschalten, und die alte Steuerung dann stoppen – sonst schreiben zwei
Regler gleichzeitig den ESS-Modus.

## Aktualisieren

- **Einfach:** in der App unter *Einstellungen → System* „Nach Updates suchen“ → „Jetzt aktualisieren“. Die App beendet sich,
  **pm2 startet sie neu**.
- **Am Terminal:**
  ```bash
  cd /root/BlueNexus && git pull --ff-only
  ./app/venv/bin/pip install -r app/requirements.txt   # nur bei neuen Abhängigkeiten
  pm2 restart bluenexus
  ```

## Zeitzone
`ecosystem.config.js` setzt `TZ: 'Europe/Berlin'` nur für diesen Prozess. Die Logik rechnet zeitzonen-robust; die Zeitzone
sorgt nur für die korrekte Anzeige der Uhrzeiten. Für einen anderen Standort dort anpassen.

## Fehlersuche
| Symptom | Prüfung |
|---|---|
| Seite nicht erreichbar | `pm2 logs bluenexus`, Port 5005 frei? |
| „Cerbo nicht erreichbar“ | Modbus TCP am Cerbo an? `./venv/bin/python cerbo_test.py --host <IP>` |
| Update-Knopf sagt „kein Git“ | Code wurde kopiert statt per `git clone` geholt |
| App nach Neustart weg | `pm2 save` und `pm2 startup` vergessen |
| Zeiten verschoben | `TZ` in `ecosystem.config.js` prüfen, danach `pm2 restart bluenexus` |
