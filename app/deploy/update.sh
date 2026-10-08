#!/usr/bin/env bash
#
# Aktualisieren (Alternative zum Update-Knopf in der App): holt den neuesten Code von GitHub,
# installiert neue Python-Pakete und startet den Dienst neu. Eigene Daten bleiben unberührt.
#
#   sudo /opt/bluenexus/app/deploy/update.sh
#
set -euo pipefail
DEF_DIR=/opt/bluenexus; DEF_USER=bluenexus; DEF_SVC=bluenexus
INSTALL_DIR="${INSTALL_DIR:-$DEF_DIR}"
SERVICE_USER="${SERVICE_USER:-$DEF_USER}"
SERVICE="$DEF_SVC"
USER_HOME="/var/lib/${SERVICE_USER}"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

as_user() {
  if [ "$(id -u)" -eq 0 ]; then runuser -u "$SERVICE_USER" -- env HOME="$USER_HOME" "$@"
  else sudo -u "$SERVICE_USER" env HOME="$USER_HOME" "$@"; fi
}

[ -d "$INSTALL_DIR/.git" ] || { echo "Keine Installation in $INSTALL_DIR gefunden." >&2; exit 1; }
echo ">> Hole den neuesten Code ..."
as_user git -C "$INSTALL_DIR" pull --ff-only
echo ">> Prüfe Python-Pakete ..."
as_user "$INSTALL_DIR/app/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/app/requirements.txt"
echo ">> Starte den Dienst neu ..."
$SUDO systemctl restart "$SERVICE"
sleep 2
$SUDO systemctl is-active --quiet "$SERVICE" && echo "Aktualisiert – die Steuerung läuft." || { echo "Der Dienst läuft nicht – Meldungen: sudo journalctl -u $SERVICE -n 50 --no-pager" >&2; exit 1; }
