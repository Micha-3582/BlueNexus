#!/usr/bin/env bash
#
# BlueNexus – Installation für Raspberry Pi / Debian / Ubuntu (ein Befehl, auch zum Aktualisieren).
#
#   curl -fsSL https://raw.githubusercontent.com/Micha-3582/BlueNexus/main/app/deploy/install.sh | bash
#
# Was passiert: Pakete installieren (git, Python, ffmpeg für Kameras), eigenen Dienst-Benutzer "bluenexus" anlegen, Code von GitHub holen
# nach /opt/bluenexus, Python-Umgebung einrichten und die App als Dienst (systemd) starten – startet auch nach jedem Neustart
# des Geräts von selbst. Danach im Browser  http://<IP-des-Geräts>:5005  öffnen.
#
# Wahlweise (Umgebungsvariablen vor dem Befehl, z. B.  curl … | BLUENEXUS_REPO=… bash ):
#   BLUENEXUS_REPO Git-Adresse (Standard: das öffentliche Original-Repo)
#   GIT_TOKEN      Zugriffs-Token (nur Lesen) für ein PRIVATES Repo – wird nur für den Dienst-Benutzer gespeichert (Updates)
#   INSTALL_DIR    Zielordner               (Standard: /opt/bluenexus)
#   PORT           Port der Weboberfläche   (Standard: 5005)
#   SERVICE_USER   Dienst-Benutzer          (Standard: bluenexus)
#   NO_FFMPEG=1    ffmpeg nicht installieren (nur nötig für Kameras)
#   SKIP_SERVICE=1 keinen systemd-Dienst anlegen (zum Testen)
#
set -euo pipefail

DEFAULT_REPO="https://github.com/Micha-3582/BlueNexus.git"
# Alte Installationen (vor der Umbenennung) behalten ihre bisherigen Namen
if [ ! -d /opt/bluenexus ] && [ -d /opt/homenexus ]; then DEF_DIR=/opt/homenexus; DEF_USER=homenexus; DEF_SVC=homenexus          # frühere Installation unter altem Namen
elif [ ! -d /opt/bluenexus ] && [ -d /opt/victron-steuerung ]; then DEF_DIR=/opt/victron-steuerung; DEF_USER=victron; DEF_SVC=victron-steuerung
else DEF_DIR=/opt/bluenexus; DEF_USER=bluenexus; DEF_SVC=bluenexus; fi
REPO="${1:-${BLUENEXUS_REPO:-${VICTRON_REPO:-$DEFAULT_REPO}}}"
INSTALL_DIR="${INSTALL_DIR:-$DEF_DIR}"
PORT="${PORT:-5005}"
SERVICE_USER="${SERVICE_USER:-$DEF_USER}"
SERVICE="$DEF_SVC"
USER_HOME="/var/lib/${SERVICE_USER}"

say()  { printf '\033[1;34m>>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFEHLER:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- Voraussetzungen
[ "$(uname -s)" = "Linux" ] || die "Dieses Skript läuft nur unter Linux (Raspberry Pi OS, Debian, Ubuntu)."
command -v apt-get >/dev/null 2>&1 || die "apt-get nicht gefunden – bitte Raspberry Pi OS / Debian / Ubuntu verwenden."
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || die "Bitte als root ausführen oder sudo installieren (Befehl: sudo bash install.sh)."
  SUDO="sudo"
fi
ARCH="$(uname -m)"
say "System: $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-Linux}") ($ARCH)"
case "$ARCH" in
  aarch64|arm64|armv7l|armv8l|x86_64|amd64) ;;
  armv6l) warn "Raspberry Pi Zero/1 (armv6): läuft, aber langsam – ein Pi 3/4/5 ist deutlich besser." ;;
  *) warn "Unbekannte Architektur '$ARCH' – ich versuche es trotzdem." ;;
esac

as_user() {   # Befehl als Dienst-Benutzer ausführen (HOME zeigt auf dessen Ordner, damit Git-Zugangsdaten dort liegen)
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u "$SERVICE_USER" -- env HOME="$USER_HOME" "$@"
  else
    sudo -u "$SERVICE_USER" env HOME="$USER_HOME" "$@"
  fi
}

# ---------------------------------------------------------------- Pakete
say "Installiere Pakete (git, python3, venv, curl$( [ "${NO_FFMPEG:-0}" = 1 ] || echo ', ffmpeg')) ... (kann einige Minuten dauern)"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
PKGS="git python3 python3-venv python3-pip curl ca-certificates"
[ "${NO_FFMPEG:-0}" = 1 ] || PKGS="$PKGS ffmpeg"
# shellcheck disable=SC2086
$SUDO apt-get install -y --no-install-recommends $PKGS >/dev/null

PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python $PYV ist zu alt – die App braucht mindestens Python 3.9 (Raspberry Pi OS Bullseye oder neuer)."
say "Python $PYV"

# ---------------------------------------------------------------- Dienst-Benutzer
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  say "Lege Benutzer '$SERVICE_USER' an (nur für die App, ohne Anmeldung)"
  $SUDO useradd --system --home-dir "$USER_HOME" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
$SUDO mkdir -p "$INSTALL_DIR" "$USER_HOME"
$SUDO chown "$SERVICE_USER":"$(id -gn "$SERVICE_USER")" "$INSTALL_DIR" "$USER_HOME"

# ---------------------------------------------------------------- Code von GitHub
if [ -n "${GIT_TOKEN:-}" ]; then
  say "Speichere den Zugriffs-Token für den Dienst-Benutzer (für Updates)"
  host="$(printf '%s' "$REPO" | sed -E 's#^https?://([^/]+)/.*#\1#')"
  printf 'https://x-access-token:%s@%s\n' "$GIT_TOKEN" "$host" | $SUDO tee "$USER_HOME/.git-credentials" >/dev/null
  $SUDO chown "$SERVICE_USER" "$USER_HOME/.git-credentials"; $SUDO chmod 600 "$USER_HOME/.git-credentials"
  as_user git config --global credential.helper store
fi
if [ -d "$INSTALL_DIR/.git" ]; then
  say "Aktualisiere vorhandene Installation ($INSTALL_DIR)"
  as_user git -C "$INSTALL_DIR" pull --ff-only
else
  [ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ] || die "$INSTALL_DIR ist nicht leer und keine Installation – bitte leeren oder INSTALL_DIR ändern."
  say "Hole den Code: $REPO"
  as_user env GIT_TERMINAL_PROMPT=0 git clone --quiet "$REPO" "$INSTALL_DIR" \
    || die "Der Code konnte nicht geholt werden. Bei einem privaten Repo: GIT_TOKEN=… (Token mit Leserecht) vor den Befehl setzen."
fi
APP="$INSTALL_DIR/app"
[ -f "$APP/webapp.py" ] || die "Im Repo fehlt app/webapp.py – ist die Adresse richtig?"

# ---------------------------------------------------------------- Python-Umgebung
say "Richte die Python-Umgebung ein ... (auf dem Pi dauert das einige Minuten)"
as_user python3 -m venv "$APP/.venv"
as_user "$APP/.venv/bin/pip" install --quiet --upgrade pip
if ! as_user "$APP/.venv/bin/pip" install --quiet -r "$APP/requirements.txt"; then
  warn "Installation der Python-Pakete fehlgeschlagen – installiere Bauwerkzeuge und versuche es noch einmal ..."
  $SUDO apt-get install -y --no-install-recommends build-essential python3-dev libffi-dev libssl-dev >/dev/null
  as_user "$APP/.venv/bin/pip" install --quiet -r "$APP/requirements.txt" || die "Python-Pakete konnten nicht installiert werden (siehe Meldung oben)."
fi

# ---------------------------------------------------------------- Dienst
TZNAME="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo Europe/Berlin)"
[ -n "$TZNAME" ] || TZNAME="Europe/Berlin"
if [ "${SKIP_SERVICE:-0}" = 1 ] || [ ! -d /run/systemd/system ]; then
  warn "Kein systemd-Dienst angelegt (SKIP_SERVICE=1 oder systemd nicht aktiv)."
  echo "Starten von Hand:  sudo -u $SERVICE_USER env PORT=$PORT TZ=$TZNAME $APP/.venv/bin/python $APP/webapp.py"
  exit 0
fi
say "Lege den Dienst '$SERVICE' an (Start beim Hochfahren, Neustart bei Fehlern)"
$SUDO tee "/etc/systemd/system/${SERVICE}.service" >/dev/null <<EOF
[Unit]
Description=BlueNexus
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP}
Environment=PORT=${PORT}
Environment=TZ=${TZNAME}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP}/.venv/bin/python webapp.py
Restart=always
RestartSec=5
# Port 80 für die Alexa-Anbindung (Hue-Emulation) ohne Root-Rechte
AmbientCapabilities=CAP_NET_BIND_SERVICE
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE" >/dev/null 2>&1
$SUDO systemctl restart "$SERVICE"

# ---------------------------------------------------------------- Warten, bis die Oberfläche antwortet
say "Warte, bis die App antwortet ..."
code=000
for _ in $(seq 1 45); do
  code="$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:${PORT}/" || true)"
  case "$code" in 200|301|302|401) break ;; esac
  sleep 2
done
case "$code" in
  200|301|302|401) ;;
  *) die "Die App antwortet nicht. Meldungen ansehen mit:  sudo journalctl -u ${SERVICE} -n 50 --no-pager" ;;
esac

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "============================================================"
echo " Fertig! Die Steuerung läuft als Dienst '${SERVICE}'."
echo ""
echo "   Im Browser öffnen:   http://${IP:-<IP-des-Geräts>}:${PORT}"
echo ""
echo " Dort legst du beim ersten Mal dein Konto an, wählst die Module"
echo " und gehst den Einrichtungsassistenten durch."
echo ""
echo " Tipp: Dem Gerät im Router eine feste IP-Adresse geben."
echo " Von unterwegs: in der App unter Einstellungen → System → Fernzugriff."
echo ""
echo " Nützliche Befehle:"
echo "   sudo systemctl status ${SERVICE}      # läuft er?"
echo "   sudo systemctl restart ${SERVICE}     # neu starten"
echo "   sudo journalctl -u ${SERVICE} -f      # Meldungen live ansehen"
echo "   sudo ${INSTALL_DIR}/app/deploy/update.sh   # aktualisieren (geht auch per Knopf in der App)"
echo "============================================================"
