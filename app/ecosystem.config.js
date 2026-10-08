// pm2-Konfiguration fuer BlueNexus (laeuft an jedem Ort, an dem das Repo liegt).
// Start:  cd <Ordner>/app && pm2 start ecosystem.config.js && pm2 save
//
// Voraussetzung: Code per git geklont und die Python-Umgebung unter app/venv angelegt (siehe app/DEPLOY-Proxmox.md).
const path = require('path');

module.exports = {
  apps: [
    {
      name: 'bluenexus',
      cwd: __dirname,
      script: 'webapp.py',
      interpreter: path.join(__dirname, 'venv', 'bin', 'python'),
      env: {
        PORT: 5005,
        // Server laufen oft auf UTC. Ohne das zeigen Preis-/Termin-Zeiten
        // verschoben an. Setzt die Zeitzone nur fuer diesen Prozess.
        TZ: 'Europe/Berlin',
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      max_memory_restart: '250M',
      time: true, // Zeitstempel in den pm2-Logs
    },
  ],
};
