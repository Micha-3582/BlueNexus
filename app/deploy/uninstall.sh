#!/usr/bin/env bash
#
# Entfernt den Dienst und die Installation. Deine Daten (Konten, Einstellungen, Verläufe, Zugangsdaten) liegen im Ordner
# /opt/bluenexus/app und werden dabei GELÖSCHT – vorher ggf. sichern (z. B. den Ordner app/backups kopieren).
#
#   sudo /opt/bluenexus/app/deploy/uninstall.sh          (mit Rückfrage)
#   sudo /opt/bluenexus/app/deploy/uninstall.sh --yes    (ohne Rückfrage)
#
set -euo pipefail
# Alte Installationen (vor der Umbenennung) behalten ihre bisherigen Namen
if [ ! -d /opt/bluenexus ] && [ -d /opt/homenexus ]; then DEF_DIR=/opt/homenexus; DEF_USER=homenexus; DEF_SVC=homenexus          # frühere Installation unter altem Namen
elif [ ! -d /opt/bluenexus ] && [ -d /opt/victron-steuerung ]; then DEF_DIR=/opt/victron-steuerung; DEF_USER=victron; DEF_SVC=victron-steuerung
else DEF_DIR=/opt/bluenexus; DEF_USER=bluenexus; DEF_SVC=bluenexus; fi
INSTALL_DIR="${INSTALL_DIR:-$DEF_DIR}"
SERVICE_USER="${SERVICE_USER:-$DEF_USER}"
SERVICE="$DEF_SVC"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

if [ "${1:-}" != "--yes" ]; then
  echo "Das löscht $INSTALL_DIR samt ALLEN Daten der Steuerung und den Dienst '$SERVICE'."
  read -r -p "Wirklich entfernen? (ja/nein) " a < /dev/tty
  [ "$a" = "ja" ] || { echo "Abgebrochen."; exit 0; }
fi
$SUDO systemctl disable --now "$SERVICE" 2>/dev/null || true
$SUDO rm -f "/etc/systemd/system/${SERVICE}.service"
$SUDO systemctl daemon-reload 2>/dev/null || true
$SUDO rm -rf "$INSTALL_DIR"
$SUDO userdel -r "$SERVICE_USER" 2>/dev/null || true
echo "Entfernt."
