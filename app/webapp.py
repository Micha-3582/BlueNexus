#!/usr/bin/env python3
"""
BlueNexus - Web-App
======================================
Mobile Web-Oberfläche + integrierter Regler (Scheduler-Thread).
- Dashboard: Status, Preis-Kurve, Plan, manueller Override, E-Auto-Termine
- Einrichtungsassistent (/setup) beim ersten Start
- Admin-Bereich (/admin) zum Anpassen aller Einstellungen

Start:
  pip install -r requirements.txt
  python webapp.py            # http://<host>:5005
"""
import copy
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from urllib.parse import urlparse

from flask.sessions import SecureCookieSessionInterface
from flask import (Flask, g, jsonify, make_response, redirect, render_template, request,
                   session, url_for, Response, stream_with_context)

import json
import os

import shelly
import store
import surplus
import tuya
import homematic
import midea
import verlauf
import zigbee
import planner
import autolog
import notify
import pushover
import tunnel
import opslog
import price_cache
import rules
import flows
import virtual
import visibility
import camera
import nfc
import webhook
import alexa
import sun
import wol
import report
import updater
import vrm
import vrm_import
import weather
import sandbox
sandbox.activate()                                           # Testmodus: keine Verbindungen nach aussen (muss vor allen anderen Modulen aktiv sein)
import auth
import backup
from auth import UserError, UserStore, is_expired, new_secret_key
from datasources import build_fixed_price_entries, fetch_tibber_prices
from logic import ESS_CHARGE, ESS_IDLE, Params, Slot, decide, merge_into_windows
from logic import _parse_iso as logic_parse_iso
import victron
from victron import Cerbo

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("webapp")
surplus_ctrl = surplus.SurplusController()
rule_engine = rules.RuleEngine()
flow_engine = flows.FlowEngine()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = new_secret_key(os.path.join(BASE_DIR, "secret.key"))
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(store.load_config().get("cookie_secure", False)),
)



def request_is_https() -> bool:
    """Kam die Anfrage ueber HTTPS? Direkt (https) oder ueber Cloudflare Tunnel/Proxy (X-Forwarded-Proto bzw. CF-Visitor). Ausserhalb einer Anfrage: nein."""
    try:
        if request.is_secure:
            return True
        if (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() == "https":
            return True
        return '"scheme":"https"' in (request.headers.get("CF-Visitor") or "").replace(" ", "").lower()
    except RuntimeError:
        return False


class AutoSecureSession(SecureCookieSessionInterface):
    """Anmelde-Cookie: "Secure" (nur ueber HTTPS gesendet), sobald die Anfrage ueber HTTPS kommt - z. B. durch den Cloudflare Tunnel.
    Im Heimnetz ueber http:// bleibt es ohne dieses Merkmal, sonst wuerde die Anmeldung dort nicht mehr gehen. Die feste Einstellung
    cookie_secure (immer Secure) bleibt moeglich."""

    def get_cookie_secure(self, app):
        return bool(app.config.get("SESSION_COOKIE_SECURE")) or request_is_https()


app.session_interface = AutoSecureSession()
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024                      # nur das Einspielen einer Sicherung darf gross sein, alles andere wird unten auf 4 MB begrenzt
SMALL_BODY_MAX = 4 * 1024 * 1024
BIG_BODY_ENDPOINTS = {"api_backup_import", "restore"}


@app.before_request
def _limit_body():
    """Nichts in der App braucht grosse Anfragen (schuetzt vor Riesen-Uploads) - ausser dem Einspielen einer Sicherung."""
    if request.endpoint in BIG_BODY_ENDPOINTS:
        return None
    if (request.content_length or 0) > SMALL_BODY_MAX:
        return jsonify(error="Anfrage zu groß."), 413
    if request.method in ("POST", "PUT", "PATCH") and request.content_length is None and request.headers.get("Transfer-Encoding"):
        return jsonify(error="Anfrage ohne Längenangabe nicht erlaubt."), 411
    return None


@app.after_request
def _security_headers(resp):
    """Schutzkopfzeilen: kein Raten des Dateityps, nicht in fremden Seiten einbettbar, keine Adresse an andere Seiten weitergeben; HSTS nur ueber HTTPS."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request_is_https():
        resp.headers.setdefault("Strict-Transport-Security", "max-age=15552000")      # 180 Tage, nur diese Adresse
    return resp

users = UserStore(os.path.join(BASE_DIR, "users.json"))


@app.context_processor
def inject_app_display_name():
    """Personalisierbarer Anzeigename (Kopfzeile/Titel) - fuer alle Templates
    verfuegbar, auch Login/Konto-Anlage (kein DB-Zugriff, nur die lokale Datei)."""
    return {"app_display_name": store.default_app_name(), "sandbox": sandbox.ACTIVE}


@app.context_processor
def inject_preview():
    """Name des Kontos, dessen Ansicht gerade als Vorschau laeuft (Hinweisleiste oben), sonst None."""
    return {"preview_user": getattr(g, "preview", None)}


PUBLIC_ENDPOINTS = {"login", "create_account", "restore", "nfc_tag", "nfc_pair", "nfc_index", "logout", "static", "service_worker", "manifest"}

_attempts: dict[str, list] = {}
_attempts_lock = threading.Lock()


def client_ip() -> str:
    # Hinter Cloudflare Tunnel steht die echte IP im Header.
    return (
        request.headers.get("CF-Connecting-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or request.remote_addr
        or "?"
    )


def too_many_attempts(ip: str) -> bool:
    """Einfache Bremse gegen Passwort-Raten (max. 10 Versuche / 5 Min pro IP)."""
    window, limit = 300, 10
    now = time.time()
    with _attempts_lock:
        tries = [t for t in _attempts.get(ip, []) if now - t < window]
        _attempts[ip] = tries
        return len(tries) >= limit


def note_failed_attempt(ip: str) -> None:
    now = time.time()
    with _attempts_lock:
        _attempts.setdefault(ip, []).append(now)
        if len(_attempts) > 2000:                                # alte Eintraege aufraeumen (kein unbegrenztes Wachsen bei vielen fremden Adressen)
            for k in [k for k, v in _attempts.items() if not v or now - v[-1] > 300]:
                _attempts.pop(k, None)


def _deny(msg: str, code: int = 403):
    if request.path.startswith("/api/"):
        return jsonify(error=msg), code
    if request.endpoint == "index":
        # Sonderfall: kein Zugriff aufs Dashboard selbst - ein redirect("index") liefe
        # sonst in eine Endlosschleife. Kommt nur bei sehr eigenwillig zusammengestellten
        # Rechten vor (Dashboard komplett ohne Zugriff).
        return msg, code
    return redirect(url_for("index"))


# Jeder Endpunkt gehoert zu genau einem Rechte-Bereich (siehe auth.AREAS). GET/HEAD
# braucht "read" auf diesen Bereich, alles andere (POST/PATCH/DELETE) "write". Endpunkte,
# die hier fehlen, sind nur mit Benutzerverwaltung=write erreichbar (sicherer Standard fuer
# neue/vergessene Routen) - ausser sie stehen in ALWAYS_ALLOWED (eigenes Konto, Ab-/Anmelden).
ALWAYS_ALLOWED_ENDPOINTS = {"preview_start", "preview_stop"}
ENDPOINT_AREA = {
    "api_update_own_account": "account", "api_modules": "settings_system",
    "api_alexa": "smarthome_einrichten", "api_alexa_settings": "smarthome_einrichten", "api_alexa_add": "smarthome_einrichten", "api_alexa_modify": "smarthome_einrichten", "api_alexa_order": "smarthome_einrichten", "api_zigbee_gateways_order": "smarthome_einrichten",
    # Dashboard: Status/Verlauf ansehen (read) - Geraete schalten/Override/Ladetermine (write)
    "index": "dashboard", "solar_log_page": "dashboard", "api_solar_log": "dashboard",
    "watchdog_page": "dashboard", "api_watchdog": "dashboard", "api_alarms": "dashboard",
    "api_battery_cycles": "dashboard", "api_status": "dashboard", "api_history": "dashboard",
    "api_week": "dashboard", "api_month": "dashboard", "api_live": "dashboard",
    "api_version": "dashboard", "api_override": "dashboard", "api_ev_add": "dashboard",
    "api_ev_modify": "dashboard", "api_shelly_list": "dashboard", "api_shelly_switch": "dashboard", "api_shelly_brightness": "dashboard", "api_shelly_wled": "dashboard", "api_shelly_midea": "dashboard", "api_midea_scan": "smarthome_einrichten", "api_midea_add": "smarthome_einrichten",
    "report_page": "dashboard", "api_report": "dashboard", "api_savings": "dashboard",
    "api_plan_sim": "dashboard", "api_price_history": "dashboard", "api_weather": "dashboard",
    "api_vrm_forecast": "dashboard", "api_vrm_forecast_history": "dashboard",
    # "api_my_tiles" bewusst NICHT hier - braucht nur Lesezugriff auch fuer sein POST (siehe Sonderfall unten)
    # Regeln
    "rules_page": "rules", "rules_log_page": "rules", "api_rules_get": "rules",
    "api_rules_add": "rules", "api_rules_modify": "rules",
    # Automatik (Ueberschuss)
    "automation_page": "automation", "automation_log_page": "automation",
    "api_shelly_auto": "automation", "api_shelly_auto_order": "automation",
    "api_automation_log": "automation",
    "api_automation_log_read": "automation", "api_automation_log_clear": "automation",
    "api_automation_save": "automation",
    # Einstellungen, je Karte/Reiter ein eigener Bereich
    "api_ess_min_soc": "settings_anlage", "api_ess_grid_setpoint": "settings_anlage",
    "api_grid_adjust": "settings_anlage", "api_test": "settings_anlage",
    "api_pv_calibration": "settings_tarif",
    "api_weather_location": "settings_wetter", "api_weather_search": "settings_wetter",
    "api_notify_info": "settings_meldungen", "api_notify_credentials": "settings_meldungen",
    "api_notify_detect": "settings_meldungen", "api_notify_settings": "settings_meldungen",
    "api_notify_test": "settings_meldungen", "api_notify_recipient_add": "settings_meldungen", "api_notify_recipient_modify": "settings_meldungen",
    "api_notify_recipients": "rules", "api_tibber_token_delete": "settings_tarif",
    "api_tunnel_info": "settings_system", "api_tunnel_log": "settings_system", "api_tunnel_token": "settings_system", "api_tunnel_enable": "settings_system",
    "api_tunnel_install": "settings_system",
    "api_pushover_info": "settings_meldungen", "api_pushover_credentials": "settings_meldungen", "api_pushover_recipient_add": "settings_meldungen",
    "api_pushover_recipient_modify": "settings_meldungen", "api_pushover_test": "settings_meldungen", "api_pushover_recipients": "rules",
    "api_vrm_info": "settings_vrm", "api_vrm_credentials": "settings_vrm", "api_vrm_restore": "settings_vrm",
    "smarthome_page": "settings_geraete",
    "verlauf_page": "verlauf", "api_verlauf_catalog": "verlauf", "api_verlauf_series": "verlauf", "api_verlauf_series_add": "verlauf", "api_verlauf_series_modify": "verlauf",
    "api_verlauf_data": "verlauf", "api_verlauf_charts": "verlauf", "api_verlauf_charts_save": "verlauf",
    "kameras_page": "kameras", "api_cameras_list": "kameras", "api_cameras_add": "kameras", "api_camera_modify": "kameras",
    "api_camera_snapshot": "kameras", "api_camera_stream": "kameras", "api_cameras_order": "kameras", "api_cameras_my_order": "kameras",
    "api_tuya_info": "smarthome_einrichten", "api_tuya_credentials": "smarthome_einrichten",
    "api_tuya_scan": "smarthome_einrichten", "api_tuya_add": "smarthome_einrichten",
    "api_device_families": "smarthome_einrichten", "api_homematic_info": "smarthome_einrichten", "api_homematic_credentials": "smarthome_einrichten", "api_homematic_push": "smarthome_einrichten", "api_rule_usage": "settings_geraete", "api_homematic_events": "smarthome_einrichten", "api_homematic_radio": "smarthome_einrichten", "api_homematic_pause": "smarthome_einrichten", "api_homematic_resume": "smarthome_einrichten",
    "api_homematic_scan": "smarthome_einrichten", "api_homematic_add": "smarthome_einrichten",
    "api_zigbee_info": "smarthome_einrichten", "api_zigbee_credentials": "smarthome_einrichten", "api_zigbee_pair": "smarthome_einrichten", "api_zigbee_gateway_delete": "smarthome_einrichten", "api_camera_motion_scan": "smarthome_einrichten", "api_camera_motion_add": "smarthome_einrichten", "api_zigbee_gateway_rename": "smarthome_einrichten",
    "api_zigbee_scan": "smarthome_einrichten", "api_zigbee_add": "smarthome_einrichten", "api_zigbee_sensor_scan": "smarthome_einrichten",
    "api_zigbee_sensor_add": "smarthome_einrichten", "api_zigbee_sp_scan": "smarthome_einrichten", "api_zigbee_sp_add": "smarthome_einrichten",
    "api_homematic_sensor_scan": "smarthome_einrichten", "api_homematic_sensor_add": "smarthome_einrichten",
    "api_sensor_modify": "settings_geraete", "api_sensors_list": "dashboard",
    "api_sensors_order": "settings_geraete", "api_virtual_order": "settings_geraete",
    "api_setpoints_order": "settings_geraete", "api_sounds_order": "settings_geraete", "api_blinds_order": "settings_geraete", "api_locks_order": "smarthome_sicherheit",
    "api_wol_list": "dashboard", "api_wol_wake": "dashboard", "api_wol_add": "settings_geraete", "api_wol_modify": "settings_geraete",
    "api_sound_list": "dashboard", "api_sound_scan": "smarthome_einrichten", "api_sound_add": "smarthome_einrichten", "api_sound_modify": "settings_geraete", "api_sound_play": "smarthome_einrichten",
    "api_blind_list": "dashboard", "api_blind_scan": "smarthome_einrichten", "api_blind_add": "smarthome_einrichten", "api_blind_modify": "settings_geraete",
    "api_blind_level": "settings_geraete", "api_blind_stop": "settings_geraete",
    "api_lock_list": "dashboard", "api_lock_scan": "smarthome_sicherheit", "api_lock_add": "smarthome_sicherheit", "api_lock_modify": "smarthome_sicherheit", "api_virtual_list": "dashboard", "api_virtual_press": "dashboard", "api_virtual_set": "dashboard",
    "api_virtual_add": "settings_geraete", "api_virtual_modify": "settings_geraete", "api_virtual_url": "settings_geraete",
    "api_setpoint_scan": "smarthome_einrichten", "api_setpoint_add": "smarthome_einrichten", "api_setpoint_list": "dashboard",
    "api_setpoint_modify": "settings_geraete",
    "api_shelly_icons": "settings_geraete", "api_shelly_order": "settings_geraete",
    "api_shelly_scan": "smarthome_einrichten", "api_tasmota_scan": "smarthome_einrichten",
    "api_shelly_add": "smarthome_einrichten", "api_shelly_preview": "smarthome_einrichten", "api_shelly_modify": "settings_geraete",
    "api_check_update": "settings_system", "api_update": "settings_system",
    "api_backup_export": "user_management", "api_backup_import": "user_management",
    "api_nfc": "smarthome_nfc", "api_nfc_phones": "smarthome_nfc", "api_nfc_phone": "smarthome_nfc", "api_nfc_pair": "smarthome_nfc",
    "api_nfc_tags": "smarthome_nfc", "api_nfc_tag": "smarthome_nfc", "api_nfc_base": "smarthome_nfc",
    "setup": "settings_anlage",
    # "admin" (die Seite selbst) steht bewusst NICHT hier - wer irgendeinen Einstellungsbereich
    # lesen darf, soll die Seite oeffnen koennen; welche Karten er darin sieht, entscheidet
    # admin.html pro Karte anhand von user_perms. Siehe Sonderfall in _require_login.
    # Benutzerverwaltung
    "api_users": "user_management", "api_users_item": "user_management",
}
# /api/config ist ein einziger Sammel-Endpunkt fuer fast alle Einstellungsbereiche -
# hier wird nicht der Endpunkt, sondern jedes einzelne Config-Feld einem Bereich zugeordnet
# (siehe api_config: GET blendet fremde Felder nicht aus, PATCH prueft nur veraenderte Felder).
# Seiten/Lese-Endpunkte, die fuer JEDES Konto mit mindestens einem Smart-Home-Bereich offen sind (Schreiben nutzt ENDPOINT_AREA)
SMARTHOME_AREAS = ("settings_geraete", "smarthome_sicherheit", "smarthome_einrichten", "smarthome_nfc")
ANY_READ = {"smarthome_page": SMARTHOME_AREAS, "api_device_families": SMARTHOME_AREAS, "api_automation_unread": ("automation", "rules")}
FIELD_AREA = {}
for _f in ("cerbo_host", "cerbo_port", "has_pv_inverter", "has_mppt", "battery_usable_kwh",
           "daily_usage_kwh", "pv_reserve_kwh", "battery_install_date", "battery_expected_cycles",
           ):
    FIELD_AREA[_f] = "settings_anlage"
FIELD_AREA["pv_inverters"] = "settings_anlage"
FIELD_AREA["scan_networks"] = "smarthome_einrichten"
for _f in ("tibber_token", "tariff_mode", "fixed_price_ct", "max_charge_soc", "absolute_cheap_price",
           "pv_tom_morning_factor", "morning_peak_start", "morning_peak_end", "evening_peak_start",
           "evening_peak_end", "min_peak_soc", "peak_avoid_price", "evening_comfort_soc",
           "valley_min_saving_ct", "night_safety_soc", "target_safe_soc", "hysterese_soc",
           "contract_fee_month_eur", "grid_fee_day_eur", "meter_fee_day_eur",
           "section14a_credit_day_eur", "vat_percent", "smart_planner_enabled", "pv_auto_calibration"):
    FIELD_AREA[_f] = "settings_tarif"
for _f in ("app_display_name", "show_live_values", "show_energy_chart", "show_flow_chart",
           "show_week_overview", "show_month_overview", "show_tibber_card", "show_override_card",
           "show_price_plan", "show_charge_log", "show_ev_card", "show_shelly_card", "show_sensors_card", "show_virtual_card",
           "show_weather_card", "show_plansim_card", "show_savings_card", "show_verlauf_card", "tile_order",
           "chart_energy_hourly", "chart_flow_hourly"):
    FIELD_AREA[_f] = "settings_anzeige"
for _f in ("dry_run", "poll_seconds", "energy_sample_seconds", "manual_override", "web_port"):
    FIELD_AREA[_f] = "settings_system"
for _f in ("surplus_enabled", "surplus_dry_run", "surplus_min_soc"):
    FIELD_AREA[_f] = "automation"
for _f in surplus.DEFAULTS:
    FIELD_AREA["surplus_" + _f] = "automation"
for _f in ("rules_enabled", "rules_dry_run", "rules_manual_hold_min", "rules_failsafe_min"):
    FIELD_AREA[_f] = "rules"
# Config-Felder ohne Eintrag hier (sollte es keine geben) faellt api_config auf "settings_anlage"
# zurueck - sicherer als sie komplett ungeprueft durchzulassen.


def _perms():
    return getattr(g, "perms", {})


AREA_LABEL = {a: label for a, label, _ in auth.AREAS}


def _gate_automation_save():
    body = request.get_json(silent=True) or {}
    cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
    need_rules = "rules" in body or "groups" in body or any(str(k).startswith("rules_") for k in cfg)
    need_auto = "devices" in body or "auto_order" in body or any(str(k).startswith("surplus_") for k in cfg)
    if not need_rules and not need_auto:
        need_rules = True
    for area, need in (("rules", need_rules), ("automation", need_auto)):
        if need:
            denied = _check_area(area, "write")
            if denied:
                return denied
    return None


def _check_area(area: str, need: str):
    if not auth.has_level(_perms(), area, need):
        verb = "sehen" if need == "read" else "ändern"
        return _deny(f"Dieses Konto darf „{AREA_LABEL.get(area, area)}“ nicht {verb}.")
    return None


@app.before_request
def _block_cross_site():
    """Aendernde Anfragen von einer FREMDEN Webseite (Cross-Site-Request-Forgery) abweisen. Moderne Browser melden die Herkunft in Sec-Fetch-Site;
    zusaetzlich zum SameSite-Cookie. Auch das Starten der Vorschau (GET) zaehlt als aendernd."""
    if request.headers.get("Sec-Fetch-Site") == "cross-site" and (request.method not in ("GET", "HEAD", "OPTIONS") or request.endpoint in ("preview_start", "preview_stop")):
        msg = "Anfrage von einer fremden Webseite abgewiesen."
        return (jsonify(error=msg), 403) if request.path.startswith("/api/") else (msg, 403)
    return None


@app.before_request
def _require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if users.is_empty():
        if request.path.startswith("/api/"):
            return jsonify(error="Kein Konto eingerichtet.", setup_required=True), 401
        return redirect(url_for("create_account"))
    username = session.get("user")
    user = users.get(username) if username else None
    if not user or is_expired(user):
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify(error="Nicht angemeldet.", login_required=True), 401
        return redirect(url_for("login", next=request.path))
    # Vorschau ("Als Benutzer ansehen"): Ein Administrator sieht die App mit den Rechten eines anderen Kontos - nur ansehen, siehe preview_start
    g.real_admin = auth.is_full_admin(auth.normalize_permissions(user.get("permissions")))
    g.preview = None
    view_as = session.get("view_as")
    if view_as:
        target = users.get(view_as) if g.real_admin else None
        if target and not auth.is_full_admin(auth.normalize_permissions(target.get("permissions"))):
            user, username, g.preview = target, view_as, target["username"]
        else:
            session.pop("view_as", None)
    g.user = username
    g.user_display = user["username"]
    g.perms = auth.mask_permissions(auth.normalize_permissions(user.get("permissions")), store.modules())      # Bereiche ausgeschalteter Module: Kein Zugriff
    g.dashboard_tiles = auth.normalize_tiles(user.get("dashboard_tiles"))     # Admin-Obergrenze
    g.my_tiles = auth.normalize_tiles(user.get("my_tiles"))                   # eigene Wahl ("Meine Ansicht")
    g.my_order = auth.normalize_tile_order(user.get("my_order"))              # eigene Reihenfolge ("Meine Ansicht")
    g.my_order_explicit = bool(user.get("my_order_explicit"))
    g.admin_order = auth.normalize_tile_order(user.get("dashboard_order"))    # vom Admin fuer dieses Konto vorgegebene Reihenfolge
    if g.perms.get("settings_anzeige", "none") == "none":
        # Wem "Einstellungen: Dashboard" entzogen wurde, der darf sein Dashboard nicht (mehr) selbst anpassen: frueher gespeicherte
        # eigene Auswahl/Reihenfolge ("Meine Ansicht") wirken dann nicht mehr - es gilt, was der Administrator vorgibt.
        g.my_tiles, g.my_order, g.my_order_explicit = None, None, False

    if g.preview and request.method not in ("GET", "HEAD", "OPTIONS") and request.endpoint not in ("preview_start", "preview_stop"):
        return jsonify(error="Vorschau-Modus: Das Konto wird nur angesehen, hier wird nichts geändert. Oben „Vorschau beenden“ drücken."), 403
    if request.endpoint in ALWAYS_ALLOWED_ENDPOINTS or request.endpoint == "api_config":
        return None                                    # api_config prueft jedes Feld einzeln selbst (siehe dort)
    if request.endpoint == "admin":
        # Jeder angemeldete Benutzer darf die Seite oeffnen - "Konto & Zugang" und "Meine Ansicht"
        # sind fuer jeden da (unabhaengig von Bereichsrechten), alle anderen Karten blenden sich
        # in admin.html einzeln je nach Bereich aus/sperren sich.
        return None
    if request.endpoint == "api_my_tiles":
        # Die eigene Ansicht ansehen/laden braucht nur Lesezugriff aufs Dashboard; sie AENDERN (Seite "Meine Ansicht" in den
        # Einstellungen) nur, wenn dem Konto der Bereich "Einstellungen: Dashboard" nicht entzogen wurde.
        blocked = _check_area("dashboard", "read")
        if blocked or request.method in ("GET", "HEAD", "OPTIONS"):
            return blocked
        return _check_area("settings_anzeige", "read")
    if request.endpoint == "api_cameras_my_order":                 # eigene Kamera-Reihenfolge: jedes Konto mit Recht "Kameras" (auch nur Lesen)
        return _check_area("kameras", "read")
    any_areas = ANY_READ.get(request.endpoint)
    if any_areas and request.method in ("GET", "HEAD", "OPTIONS"):
        if any(auth.has_level(g.perms, x, "read") for x in any_areas):
            return None
        return _deny("Kein Zugriff auf Smart Home mit diesem Konto.")
    if request.endpoint == "api_automation_save":                    # Speichern von Regeln UND/ODER Ueberschuss-Automatik: je nach Inhalt das jeweilige Recht (Regeln gehen auch ohne Energie-Modul)
        return _gate_automation_save()
    area = ENDPOINT_AREA.get(request.endpoint)
    if area is None:
        if not auth.is_full_admin(g.perms):
            return _deny("Kein Zugriff mit diesem Konto.")
        return None
    need = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "write"
    return _check_area(area, need)


# Reiter des Menues "Smart Home": (id, Name, Link, noetiges Recht, Gruppe) - Reihenfolge = Anzeige; Gruppen werden durch einen Strich getrennt
SMARTHOME_TABS = [
    ("aktoren", "Aktoren", "/smarthome#aktoren", "settings_geraete", 1),
    ("sensoren", "Sensoren", "/smarthome#sensoren", "settings_geraete", 1),
    ("thermostate", "Thermostate", "/smarthome#thermostate", "settings_geraete", 1),
    ("sicherheit", "Sicherheit", "/smarthome#sicherheit", "smarthome_sicherheit", 1),
    ("regeln", "Regeln", "/rules", "rules", 2),
    ("suchen", "Geräte suchen", "/smarthome#suchen", "smarthome_einrichten", 3),
    ("nfc", "NFC-Tags", "/smarthome#nfc", "smarthome_nfc", 3),
    ("wol", "Wake-on-LAN", "/smarthome#wol", "settings_geraete", 3),
    ("alexa", "Alexa", "/smarthome#alexa", "smarthome_einrichten", 3),
    ("sonstiges", "Sonstiges", "/smarthome#sonstiges", "smarthome_einrichten", 3),
]


# Bereiche, aus denen sich die Reiter der Seite /admin ergeben (ohne eines davon waere die Einstellungsseite leer; Automatik hat eine eigene Seite)
SETTINGS_PAGE_AREAS = ("settings_anlage", "settings_tarif", "settings_vrm", "settings_wetter", "settings_meldungen",
                       "settings_anzeige", "settings_system", "account", "user_management")


def _tab_has_system(tid: str, fam: dict) -> bool:
    """Reiter, die nur zu einem Smart-Home-System gehoeren, erscheinen nur, wenn das System gewaehlt ist oder schon Eintraege existieren."""
    try:
        if tid == "sensoren":
            return bool(fam["homematic"] or fam["zigbee"] or camera.load() or homematic.load_sensors())
        if tid == "thermostate":
            return bool(fam["homematic"] or fam["zigbee"] or homematic.load_setpoints())
        if tid == "sicherheit":
            return bool(fam["homematic"] or homematic.load_locks())
    except Exception:                                       # noqa: BLE001 - im Zweifel lieber anzeigen
        return True
    return True


def _smarthome_tabs(perms: dict) -> list:
    fam = _families()
    return [{"id": i, "label": n, "href": h, "group": grp} for i, n, h, area, grp in SMARTHOME_TABS
            if auth.has_level(perms, area, "read") and (i != "alexa" or store.module_on("alexa")) and (i != "nfc" or store.module_on("smarthome")) and _tab_has_system(i, fam)]


@app.context_processor
def inject_role():
    perms = _perms()
    settings_areas = [a for a in auth.AREA_IDS if a.startswith("settings_")]
    can_save_settings = any(perms.get(a) == "write" for a in settings_areas)
    tabs = _smarthome_tabs(perms)
    admin_page = any(perms.get(a, "none") != "none" for a in SETTINGS_PAGE_AREAS)       # irgendein Reiter auf /admin sichtbar?
    return {"modules": store.modules(), "settings_visible": admin_page or perms.get("automation", "none") != "none",
            "settings_home": "/admin" if admin_page else "/automation",
            "user_role": "admin" if auth.is_full_admin(perms) else "custom", "user_perms": perms,
            "can_save_settings": can_save_settings, "sh_tabs": tabs, "tile_ceiling": getattr(g, "dashboard_tiles", None),
            "sh_home": ("/smarthome" if any(t["href"].startswith("/smarthome") for t in tabs) else (tabs[0]["href"] if tabs else "/"))}


FIRSTNAME_RE = re.compile(r"[A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ \-']{0,29}")


@app.route("/create-account", methods=["GET", "POST"])
def create_account():
    """Einmaliger erster Schritt: legt den einzigen Admin-Zugang an, bevor
    irgendetwas anderes (auch /setup) erreichbar ist. Existiert bereits ein
    Konto, ist diese Route gesperrt - Aendern laeuft danach nur noch ueber
    die Einstellungen (mit aktuellem Passwort)."""
    if not users.is_empty():
        return redirect(url_for("login"))
    if request.method == "GET":
        return render_template("create_account.html", error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    first = " ".join((request.form.get("firstname") or "").split())
    if not FIRSTNAME_RE.fullmatch(first):
        return render_template("create_account.html", error="Bitte deinen Vornamen angeben (Buchstaben, bis 30 Zeichen) – daraus entsteht der Name deiner App."), 400
    if password != password2:
        return render_template("create_account.html", error="Die Passwörter stimmen nicht überein."), 400
    try:
        users.create(username, password)
    except UserError as e:
        return render_template("create_account.html", error=str(e)), 400

    cfg = store.load_config()
    cfg["owner_first_name"] = first
    store.save_config(cfg)

    session.clear()
    session["user"] = username.strip().lower()
    session.permanent = True
    return redirect(url_for("setup_modules") if not store.modules_chosen() else url_for("setup"))


def _restart_soon() -> bool:
    """Nach dem Einspielen einer Sicherung neu starten (unter systemd/pm2 automatisch). False = von Hand neu starten."""
    if not _under_process_manager():
        return False

    def _go():
        time.sleep(1.5)
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()
    return True


def _backup_upload():
    f = request.files.get("file")
    if not f:
        raise backup.BackupError("Bitte eine Sicherungsdatei wählen.")
    return f.read(), request.form.get("password") or ""


def _backup_action():
    """Gemeinsam fuer die Einstellungen und die Erstinstallation: erst pruefen (mode=inspect), dann einspielen (mode=restore)."""
    ip = client_ip()
    if too_many_attempts(ip):
        return jsonify(error="Zu viele Fehlversuche. Bitte einige Minuten warten."), 429
    try:
        blob, pw = _backup_upload()
        if request.form.get("mode") == "restore":
            info = backup.restore_backup(blob, pw, BASE_DIR)
            opslog.log("backup", "Sicherung eingespielt (%d Dateien)" % info["written"])
            info["restarting"] = _restart_soon()
            return jsonify(ok=True, **info)
        return jsonify(ok=True, **backup.inspect_backup(blob, pw))
    except backup.BackupError as e:
        if "Passwort" in str(e):
            note_failed_attempt(ip)
        return jsonify(error=str(e)), 400


@app.post("/api/backup/export")
def api_backup_export():
    body = request.get_json(silent=True) or {}
    try:
        data, name = backup.create_backup(str(body.get("password") or ""), bool(body.get("include_data")), BASE_DIR)
    except backup.BackupError as e:
        return jsonify(error=str(e)), 400
    opslog.log("backup", "Sicherung heruntergeladen (%s)" % ("mit Verläufen" if body.get("include_data") else "nur Einstellungen"))
    resp = Response(data, mimetype="application/octet-stream")
    resp.headers["Content-Disposition"] = 'attachment; filename="%s"' % name
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/backup/import")
def api_backup_import():
    return _backup_action()


@app.route("/restore", methods=["GET", "POST"])
def restore():
    """Nur bei einer frischen Installation (noch kein Konto): Sicherung einspielen statt alles neu einzurichten."""
    if not users.is_empty():
        return redirect(url_for("login"))
    if request.method == "POST":
        return _backup_action()
    return render_template("restore.html")


# ---- NFC-Tags (nfc.py): Handy scannt Tag -> Adresse /nfc/<Tag>; nur registrierte Handys (Cookie) loesen aus ----
def _nfc_cookie(resp, token: str):
    resp.set_cookie(nfc.COOKIE, token, max_age=nfc.COOKIE_MAX_AGE, httponly=True, samesite="Lax", secure=request_is_https(), path="/")
    return resp


def _og(title: str, text: str) -> dict:
    """Vorschau fuer Link-Vorschauen (WhatsApp, Telegram, Signal ...): Titel, kurzer Text, Bild - ohne personenbezogene Angaben."""
    base = ("https" if request_is_https() else "http") + "://" + request.host
    return {"title": title, "text": text, "image": base + "/static/og-image.png"}


def _nfc_page(ok: bool, title: str, text: str, code: int = 200):
    resp = make_response(render_template("nfc_result.html", ok=ok, title=title, text=text), code)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/nfc", methods=["GET"], strict_slashes=False)
def nfc_index():
    """Oeffentliche Einrichtungsseite fuer Handys, die nur NFC-Tags nutzen: App installieren (ohne Anmeldung) und sehen, ob dieses Handy registriert ist."""
    phone = nfc.identify(request.cookies.get(nfc.COOKIE, ""))
    resp = make_response(render_template("nfc_install.html", phone=phone["name"] if phone else None, smarthome=store.module_on("smarthome"),
                                           og=_og(f"{store.default_app_name()} – NFC einrichten", "App installieren und Handy für NFC-Tags nutzen: Handy an den Tag halten, fertig.")))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/nfc/<tid>", methods=["GET"])
def nfc_tag(tid):
    if request.method == "HEAD":
        return "", 204                                                         # Vorabruf durch Browser/Apps loest nichts aus
    if request.headers.get("Sec-Fetch-Dest") in ("image", "script", "style", "iframe", "frame", "embed", "object", "audio", "video", "track", "font"):
        return _nfc_page(False, "Abgelehnt", "Dieser Tag lässt sich nur als Seite öffnen.", 403)         # Bild/Frame-Einbettung einer fremden Seite (das Kennzeichen kaeme ohnehin nicht mit)
    if not store.module_on("smarthome"):
        return _nfc_page(False, "Nicht verfügbar", "Smart Home ist auf dieser Installation ausgeschaltet.", 404)
    ip = client_ip()
    if too_many_attempts(ip):
        return _nfc_page(False, "Zu viele Versuche", "Bitte einige Minuten warten.", 429)
    r = nfc.trigger(tid, request.cookies.get(nfc.COOKIE, ""))
    if r["ok"]:
        if r["why"] != "debounced":
            opslog.log("rules", f"NFC-Tag „{r['tag']}“ von „{r['phone']}“ ausgelöst: {r['text'].split(' – ', 1)[-1]}", dry=False)
            ctrl._rules_wake.set()
        return _nfc_page(True, r["tag"], r["text"].split(" – ", 1)[-1] if " – " in r["text"] else r["text"])
    note_failed_attempt(ip)
    if r["why"] in ("unknown_phone", "not_allowed"):
        opslog.log("rules", f"NFC-Tag „{r.get('tag', '?')}“ abgelehnt: {r['text']}", dry=False)
    return _nfc_page(False, "Nicht erlaubt" if r["why"] in ("unknown_phone", "not_allowed", "pin") else "Nicht möglich", r["text"], 403 if r["why"] != "unknown_tag" else 404)


@app.route("/nfc/pair/<code>", methods=["GET", "POST"])
def nfc_pair(code):
    """GET zeigt nur eine Rueckfrage (Link-Vorschauen von Chat-Apps rufen Links ab und wuerden den Einmal-Code sonst verbrauchen); erst der Knopf (POST) registriert."""
    ip = client_ip()
    if too_many_attempts(ip):
        return _nfc_page(False, "Zu viele Versuche", "Bitte einige Minuten warten.", 429)
    if request.method == "GET":
        info = nfc.pair_peek(code)
        if not info:
            return _nfc_page(False, "Link ungültig", "Der Registrierungs-Link ist abgelaufen oder wurde schon benutzt. Bitte in der App einen neuen erzeugen.", 410)
        resp = make_response(render_template("nfc_result.html", ok=True, title="Handy registrieren?", text=f"Dieses Handy als „{info}“ für NFC-Tags registrieren.", confirm=True,
                                           og=_og(f"{store.default_app_name()} – Handy registrieren", "Mit diesem persönlichen Link registrierst du dein Handy für NFC-Tags. Der Link ist 15 Minuten gültig und nur einmal benutzbar.")))
        resp.headers["Cache-Control"] = "no-store"
        return resp
    got = nfc.pair_use(code)
    if not got:
        note_failed_attempt(ip)
        return _nfc_page(False, "Link ungültig", "Der Registrierungs-Link ist abgelaufen oder wurde schon benutzt. Bitte in der App einen neuen erzeugen.", 410)
    phone, token = got
    opslog.log("rules", f"NFC: Handy „{phone['name']}“ registriert", dry=False)
    return _nfc_cookie(_nfc_page(True, "Handy registriert", f"„{phone['name']}“ darf jetzt NFC-Tags nutzen, für die es freigegeben ist."), token)


@app.route("/api/nfc", methods=["GET"])
def api_nfc():
    out = nfc.public()
    if not auth.has_level(g.perms, "smarthome_nfc", "write"):                # Lese-Konten (Demo) sehen die Liste, aber keine Adressen: die Tag-Kennung steckt in der Adresse
        out["base_url"], out["masked"] = "", True
        out["tags"] = [{**t, "id": f"t{i + 1}"} for i, t in enumerate(out["tags"])]
    return jsonify(out)


@app.route("/api/nfc/base", methods=["POST"])
def api_nfc_base():
    try:
        return jsonify(ok=True, base_url=nfc.set_base_url((request.get_json(silent=True) or {}).get("base_url")))
    except nfc.NfcError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/nfc/phones", methods=["POST"])
def api_nfc_phones():
    """Dieses Handy (bzw. diesen Browser) registrieren - der Administrator ist hier angemeldet."""
    try:
        phone, token = nfc.add_phone((request.get_json(silent=True) or {}).get("name"))
    except nfc.NfcError as e:
        return jsonify(error=str(e)), 400
    opslog.log("rules", f"NFC: Handy „{phone['name']}“ registriert", dry=False)
    return _nfc_cookie(jsonify(ok=True, id=phone["id"]), token)


@app.route("/api/nfc/pair", methods=["POST"])
def api_nfc_pair():
    """Einmal-Link, mit dem ein anderes Handy sich registriert (15 Minuten gueltig)."""
    try:
        code = nfc.pair_new((request.get_json(silent=True) or {}).get("name"))
    except nfc.NfcError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, path=f"/nfc/pair/{code}", minutes=nfc.PAIR_TTL_S // 60)


@app.route("/api/nfc/phones/<pid>", methods=["PATCH", "DELETE"])
def api_nfc_phone(pid):
    if request.method == "DELETE":
        if not nfc.remove_phone(pid):
            return jsonify(error="nicht gefunden"), 404
        opslog.log("rules", "NFC: Handy entfernt", dry=False)
        return jsonify(ok=True)
    try:
        ok = nfc.rename_phone(pid, (request.get_json(silent=True) or {}).get("name"))
    except nfc.NfcError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/nfc/tags", methods=["POST"])
def api_nfc_tags():
    b = request.get_json(silent=True) or {}
    try:
        bid = virtual.add(str(b.get("name") or ""), "button", nfc.TAG_ICON)["id"]       # ein neuer Tag legt immer einen eigenen Knopf mit dem Namen des Tags an
        try:
            t = nfc.add_tag(b.get("name"), bid)
        except nfc.NfcError:
            virtual.remove(bid)
            raise
    except (nfc.NfcError, virtual.VirtualError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(t), 201


@app.route("/api/nfc/tags/<tid>", methods=["PATCH", "DELETE"])
def api_nfc_tag(tid):
    if request.method == "DELETE":
        tag = next((x for x in nfc.load()["tags"] if x["id"] == tid), None)
        if not tag:
            return jsonify(error="nicht gefunden"), 404
        target = tag.get("target")
        busy = _in_use("virtual", target) if target else None
        if busy:
            return busy                                                      # der Knopf des Tags steckt noch in einer Regel
        nfc.remove_tag(tid)
        if target and not nfc.is_target(target) and virtual.remove(target):    # Tag und sein Knopf gehoeren zusammen
            alexa.remove_ref("virtual", target)
        return jsonify(ok=True)
    b = request.get_json(silent=True) or {}
    try:
        ok = nfc.update_tag(tid, name=b.get("name") if isinstance(b.get("name"), str) else None, phones=b.get("phones") if isinstance(b.get("phones"), list) else None,
                            target=b.get("target") if isinstance(b.get("target"), str) else None)
        if ok and isinstance(b.get("name"), str):                            # Tag und sein Knopf heissen gleich: den Knopf mit umbenennen
            t = next((x for x in nfc.load()["tags"] if x["id"] == tid), None)
            if t:
                virtual.update(t["target"], name=t["name"])
    except nfc.NfcError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/login", methods=["GET", "POST"])
def login():
    if users.is_empty():
        return redirect(url_for("create_account"))
    if request.method == "GET":
        if session.get("user") and users.get(session["user"]):
            return redirect(url_for("index"))
        return render_template("login.html", error=None)

    ip = client_ip()
    if too_many_attempts(ip):
        return render_template(
            "login.html", error="Zu viele Fehlversuche. Bitte einige Minuten warten."
        ), 429

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    remember = bool(request.form.get("remember"))

    user = users.verify(username, password)
    if not user:
        note_failed_attempt(ip)
        return render_template("login.html", error="Benutzername oder Passwort falsch."), 401

    session.clear()
    session["user"] = username.strip().lower()
    session.permanent = remember
    return redirect(_safe_next(request.args.get("next")))


def _safe_next(target) -> str:
    """Ziel nach der Anmeldung: nur ein Pfad auf dieser Seite (kein //fremde-seite, kein Backslash, kein Schema)."""
    t = str(target or "")
    if not t.startswith("/") or t.startswith("//") or "\\" in t or "\n" in t or "\r" in t or urlparse(t).netloc or urlparse(t).scheme:
        return url_for("index")
    return t


@app.route("/preview/<username>", methods=["GET"])
def preview_start(username):
    """Administrator: App mit den Rechten eines anderen Kontos ansehen (nur ansehen - alles Aendernde ist gesperrt). Gilt fuer die ganze
    Browser-Sitzung (alle Fenster), bis „Vorschau beenden“ gedrueckt wird. Nur fuer Konten, die selbst keine vollen Administratoren sind."""
    if not g.real_admin:
        return _deny("Die Vorschau darf nur ein Administrator starten.")
    target = users.get(username)
    if not target or auth.is_full_admin(auth.normalize_permissions(target.get("permissions"))):
        return redirect(url_for("admin"))
    session["view_as"] = target["username"]
    return redirect("/")


@app.route("/preview/stop", methods=["GET"])
def preview_stop():
    session.pop("view_as", None)
    return redirect("/admin#konto")


@app.post("/logout")
def logout():
    if session.get("view_as"):                          # Vorschau laeuft: nicht abmelden (sonst ist auch der Administrator draussen), nur die Vorschau beenden
        session.pop("view_as", None)
        return redirect("/admin#konto")
    session.clear()
    return redirect(url_for("login"))


@app.get("/sw.js")
def service_worker():
    """Service Worker MUSS vom Wurzelpfad kommen, sonst gilt er nur fuer /static/."""
    resp = app.send_static_file("sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    """PWA-Manifest mit personalisiertem Namen, damit mehrere installierte
    Instanzen (eigene Anlage, Anlage der Mutter, ...) auf dem Homescreen
    unterscheidbar sind - statt bei allen "BlueNexus" zu zeigen."""
    path = os.path.join(app.static_folder, "manifest.webmanifest")
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    name = store.default_app_name()
    m["name"] = name
    # Voller Name auch als Kurzname - eigenmaechtiges Abschneiden (z.B. auf
    # 12 Zeichen) reisst bei "Mamas BlueNexus" nur "Mamas" heraus.
    # Das Betriebssystem bricht/kuerzt lange Homescreen-Labels selbst sinnvoll.
    m["short_name"] = name
    resp = jsonify(m)
    resp.headers["Content-Type"] = "application/manifest+json"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.post("/api/account")
def api_update_own_account():
    """Eigenen Benutzernamen und/oder Passwort aendern. Beides optional, aber
    mindestens eines von beiden muss angegeben sein; das aktuelle Passwort
    wird immer verlangt."""
    body = request.json or {}
    if not users.verify(g.user, body.get("current") or ""):
        return jsonify(error="Aktuelles Passwort ist falsch."), 400
    new_username = (body.get("username") or "").strip()
    new_password = body.get("new") or ""
    if new_password and new_password != body.get("new2"):
        return jsonify(error="Die Passwörter stimmen nicht überein."), 400
    if not new_username and not new_password:
        return jsonify(error="Nichts zu ändern."), 400
    try:
        active = g.user
        if new_username and new_username.strip().lower() != active:
            users.rename(active, new_username)
            _vis_users_changed(active, new_username)
            active = new_username.strip().lower()
        if new_password:
            users.update_password(active, new_password)
    except UserError as exc:
        return jsonify(error=str(exc)), 400
    session["user"] = active
    return jsonify(ok=True)


def _user_out(u: dict) -> dict:
    return {"username": u["username"], "permissions": auth.normalize_permissions(u.get("permissions")),
            "created": u.get("created"), "last_login": u.get("last_login"),
            "expires": u.get("expires"), "is_me": u["username"].strip().lower() == g.user,
            "dashboard_tiles": auth.normalize_tiles(u.get("dashboard_tiles")),
            "dashboard_order": auth.normalize_tile_order(u.get("dashboard_order"))}


@app.route("/api/users", methods=["GET", "POST"])
def api_users():
    """Benutzerverwaltung (braucht Benutzerverwaltung=Schreiben) - Liste sowie Neuanlage mit
    frei waehlbaren Rechten je Bereich (siehe auth.AREAS), optionalem Ablaufdatum und optionaler
    Einschraenkung, welche Dashboard-Kacheln dieses Konto zusaetzlich zur globalen Einstellung sieht."""
    if request.method == "GET":
        mods = store.modules()
        return jsonify(users=[_user_out(u) for u in users.list()], areas=auth.visible_areas(mods), presets=auth.PRESETS,
                       groups=auth.visible_groups(mods), preset_labels=auth.PRESET_LABELS, dashboard_tiles=auth.visible_tiles(mods),
                       global_order=auth.normalize_tile_order([k for k in (store.load_config().get("tile_order") or []) if isinstance(k, str)]) or auth.DASHBOARD_TILE_KEYS)
    body = request.json or {}
    permissions = auth.normalize_permissions(body.get("permissions") or auth.PRESETS["user"])
    expires = (body.get("expires") or "").strip() or None
    try:
        u = users.create(body.get("username") or "", body.get("password") or "", permissions=permissions,
                          expires=expires, dashboard_tiles=body.get("dashboard_tiles"), dashboard_order=body.get("dashboard_order"))
    except UserError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, user=_user_out(u))


@app.route("/api/users/<username>", methods=["PATCH", "DELETE"])
def api_users_item(username):
    """Rechte/Ablauf/Passwort/Dashboard-Kacheln eines Benutzers aendern oder den Benutzer
    loeschen (braucht Benutzerverwaltung=Schreiben). Mindestens ein Zugang muss die
    Benutzerverwaltung behalten - sonst sperrt man sich versehentlich selbst aus."""
    if request.method == "DELETE":
        try:
            users.delete(username)
        except UserError as exc:
            return jsonify(error=str(exc)), 400
        _vis_users_changed(username, None)
        return jsonify(ok=True)

    body = request.json or {}
    if body.get("password") and (username or "").strip().lower() == g.user:
        # Das eigene Passwort nur ueber "Konto & Zugang" aendern: dort wird das aktuelle Passwort verlangt (hier ginge es ohne)
        return jsonify(error="Dein eigenes Passwort änderst du unter „Konto & Zugang“ – dort wird das aktuelle Passwort abgefragt."), 400
    try:
        if "permissions" in body:
            users.set_permissions(username, body["permissions"])
        if "expires" in body:
            users.set_expires(username, (body.get("expires") or "").strip() or None)
        if "dashboard_tiles" in body:
            users.set_dashboard_tiles(username, body["dashboard_tiles"])
        if "dashboard_order" in body:
            users.set_dashboard_order(username, body["dashboard_order"])
        if body.get("password"):
            users.update_password(username, body["password"])
    except UserError as exc:
        return jsonify(error=str(exc)), 400
    u = users.get(username)
    if not u:
        return jsonify(error="Benutzer nicht gefunden."), 404
    return jsonify(ok=True, user=_user_out(u))


ESS_TEXT = {ESS_CHARGE: "Netzladen", ESS_IDLE: "Normal / Warten"}


class Controller:
    """Hintergrund-Regler: holt Daten, entscheidet, schreibt ESS-Mode.
    Hält den letzten Status im Speicher für die Web-UI."""

    def __init__(self):
        self.lock = threading.Lock()
        self.status = {"ok": False, "reason": "startet ..."}
        self.prices = []          # aufbereitete Slots für die Kurve
        self.pv_cal = 1.0                                   # gelernter Korrekturfaktor der Prognose fuer morgen (1.0 = aus)
        self.soc_floor = None                        # letzter gelesener 'Minimaler SOC' des Cerbo (%)
        self.plansim = {"available": False, "reason": "noch nicht berechnet"}   # Ladeplan-Simulation (nur Anzeige)
        self.last_tick = None
        self.last_error = None
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self._tick_failed = False
        self._last_err_log = ("", 0.0)
        self._vrm_bad = False
        self._stop = threading.Event()
        self.last_system = None          # letzte Cerbo-Messung (vom Energie-Sampler)
        self.last_system_ts = 0.0
        self._surplus_dry_on: dict[str, bool] = {}   # Trockenlauf Ueberschuss-Automatik: gedachter Schaltzustand
        self._rules_dry_on: dict[str, bool] = {}     # Trockenlauf Regeln: gedachter Schaltzustand
        self._rules_wake = threading.Event()         # Meldung der CCU (Push) weckt die Regelschleife sofort

    def tick(self):
        cfg = store.load_config()
        if not store.is_configured(cfg):
            with self.lock:
                self.status = {"ok": False, "reason": "nicht eingerichtet"}
            return
        cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
        soc = cerbo.read_soc()
        current_ess = cerbo.read_ess_mode()
        thr = int(cfg.get("notify_low_soc", notify.DEFAULT_LOW_SOC))
        notify.event("low_soc", soc < thr or (notify.is_active("low_soc") and soc < thr + 5),
                     f"🪫 Akku niedrig: {soc:.0f} % (Schwelle {thr} %).", f"🔋 Akku wieder bei {soc:.0f} %.", cfg=cfg)
        notify.daily_summary(cfg, datetime.now(), extra=self._report_line)
        try:
            system = cerbo.read_system(has_pv_inverter=cfg.get("has_pv_inverter", True),
                                        has_mppt=cfg.get("has_mppt", True))
        except Exception as e:                           # noqa: BLE001
            system = None
            log.warning("System-Werte nicht lesbar: %s", e)
        price_note = None
        if cfg.get("tariff_mode") == "fixed":
            prices = build_fixed_price_entries(cfg.get("fixed_price_ct", 32.0))
        else:
            prices, price_note = self._tibber_prices(cfg, cerbo, current_ess)
        pv_note = None
        self.pv_cal = 1.0

        now = datetime.now()
        ev = store.active_ev(now)
        forced = bool(cfg.get("manual_override")) or ev is not None
        reason = "Manueller Ladetermin" if ev else "MANUELL"

        # Prognose fuer die Regelung: Victron VRM kennt die reale Anlage (lernt aus dem Ertragsverlauf) und ist
        # die Quelle. Nur wenn es nicht eingerichtet/erreichbar/aktuell ist, rechnet die Regelung mit dem
        # Durchschnitt der echten Tageserträge der letzten Tage.
        measured_today = store.solar_measured_today(now)
        vrm_data = vrm_ctl = vrm_why = None
        try:
            vrm_data = vrm.forecast()
            vrm_ctl, vrm_why = vrm.control_forecast(vrm_data, now, measured_today)
        except Exception as e:                               # noqa: BLE001
            vrm_why = "PV-Prognose (VRM) nicht verfügbar – Rückfall auf Durchschnitt der letzten Tage"
            log.warning("VRM-Prognose fuer die Regelung fehlgeschlagen: %s", e)
        if bool(vrm_why) != self._vrm_bad:
            self._vrm_bad = bool(vrm_why)
            opslog.log("vrm", vrm_why if vrm_why else "VRM-Prognose wieder verfügbar")
        if vrm_why:
            notify.event("vrm", True, f"⚠️ {vrm_why}", "✅ Die VRM-Prognose ist wieder verfügbar.", after_min=30)
        elif vrm_ctl:
            notify.event("vrm", False, "", "✅ Die VRM-Prognose ist wieder verfügbar.")
        if vrm_ctl:
            pv_source = "VRM"
            solar_today_for_control = vrm_ctl["today_kwh"]
            solar_tom_ctl = vrm_ctl["tomorrow_kwh"]
            if solar_tom_ctl is None:                        # VRM hat (noch) nichts fuer morgen
                solar_tom_ctl = store.recent_solar_average(7, now) or 0.0
                pv_note = "VRM liefert noch keine Prognose für morgen – für morgen Ø der letzten Tage"
            elif cfg.get("pv_auto_calibration"):             # gelernte Abweichung der VRM-Prognose (Solarlogbuch)
                cal = store.pv_calibration(now)
                if cal["ready"] and abs(cal["factor"] - 1) >= 0.01:
                    solar_tom_ctl = round(solar_tom_ctl * cal["factor"], 2)
                    self.pv_cal = cal["factor"]
                    pv_note = (f"Prognose für morgen um {abs(round((1 - cal['factor']) * 100))} % "
                               f"{'gesenkt' if cal['factor'] < 1 else 'erhöht'} (gelernt aus {cal['days']} Tagen)")
        else:
            avg = store.recent_solar_average(7, now)
            pv_source = "Ø letzte Tage"
            solar_today_for_control = round(max(measured_today, avg or 0.0), 2)
            solar_tom_ctl = avg or 0.0
            pv_note = vrm_why or "Kein VRM-Zugang eingerichtet (Einstellungen → VRM) – Prognose = Durchschnitt der letzten Tage"
            if vrm_why:
                log.warning(vrm_why)

        # Die VRM-Prognose ist schon anlagenkalibriert -> in decide() KEIN weiterer Korrekturfaktor.
        params = Params.from_config(cfg)
        params.pv_korrektur_faktor = 1.0
        try:                                             # Minimaler SOC am Cerbo (wie im VRM): darunter liefert der Akku nichts
            self.soc_floor = cerbo.read_min_soc()
        except Exception as e:                           # noqa: BLE001
            log.warning("Minimaler SOC nicht lesbar (letzter Wert %s %% bleibt): %s", self.soc_floor, e)
        params.soc_floor_pct = float(self.soc_floor or 0.0)
        try:                                             # Alarme von Multiplus/Quattro (VE.Bus) und Batterie (BMS)
            alarms = cerbo.read_alarms()
            for key, val in alarms["values"].items():
                if key.startswith("_"):
                    continue
                label = victron.ALARM_LABELS.get(key, key)
                notify.event("alarm_" + key, bool(val), f"⚠️ {label}", f"✅ {label}: wieder in Ordnung.",
                             flag="alarms", cfg=cfg)
        except Exception as e:                           # noqa: BLE001
            log.warning("Alarme nicht lesbar: %s", e)
        state = store.load_state()
        self._apply_periodic_full_charge(state, params, soc, now)
        d = decide(soc=soc, price_entries=prices, solar_today_raw=solar_today_for_control,
                   solar_tom_raw=solar_tom_ctl, state=state, now=now,
                   manual_override=forced, force_reason=reason,
                   params=params)
        # Intelligente Planung (Beta, Standard aus): ersetzt die stufenweisen Schwellenwerte oben durch eine
        # jeden Tick neu berechnete, kostenoptimale Planung. Greift NICHT bei manuellem Override/Ladetermin, festem
        # Tarif, fehlenden Preisen oder wenn die harte Ladesperre (Ladelimit) bereits gezogen hat - diese
        # Sicherheitsfaelle bleiben unveraendert bei der bewaehrten Logik oben.
        if (cfg.get("smart_planner_enabled", True) and not forced and cfg.get("tariff_mode") != "fixed"
                and d.reason != "Keine Preisdaten" and "Ladelimit" not in d.strategy):
            try:
                sm = self._smart_decision(now, soc, prices, vrm_data, params, state)
                if sm is not None:
                    charge_now, plan_slots, txt = sm
                    d.allow_now, d.ess_mode, d.strategy = charge_now, (ESS_CHARGE if charge_now else ESS_IDLE), txt
                    d.plan, d.plan_windows = plan_slots, (merge_into_windows(plan_slots) if plan_slots else "")
            except Exception as e:                           # noqa: BLE001
                log.warning("Intelligente Planung fehlgeschlagen, Rückfall auf Standard-Logik: %s", e)
        # Erst JETZT speichern (state.smart_commit_slot wird ggf. erst in _smart_decision() oben gesetzt -
        # vorher zu speichern wuerde das Commitment beim naechsten Tick wieder verlieren).
        store.save_state(state)
        store.log_charge_state(d.ess_mode == ESS_CHARGE, d.strategy, now)
        try:                                            # Simulation laeuft nur mit - sie steuert nichts und darf nie stoeren
            if cfg.get("tariff_mode") == "fixed":
                self.plansim = {"available": False, "reason": "Nur bei dynamischem Tarif."}
            else:
                self.plansim = self._run_plansim(now, soc, prices, d, vrm_data, params, forced)
        except Exception as e:                          # noqa: BLE001
            log.warning("Ladeplan-Simulation fehlgeschlagen: %s", e)
            self.plansim = {"available": False, "reason": f"Simulation fehlgeschlagen: {e}"}
        # Solar-Logbuch: VRM-Tagesprognose einmal pro Tag einfrieren, vergangene Tage mit dem realen Ertrag abschließen.
        try:
            store.record_vrm_forecast(vrm_data["today_kwh"] if vrm_data and vrm_data.get("hours") else None, now)
        except Exception as e:                               # noqa: BLE001
            log.warning("Solar-Logbuch konnte nicht geschrieben werden: %s", e)
        if time.time() - getattr(self, "_savings_ts", 0) > 3600:      # abgeschlossene Tage stuendlich in die Ersparnis-Datei uebernehmen
            self._savings_ts = time.time()
            try:
                store.savings(cfg, now)
            except Exception as e:                           # noqa: BLE001
                log.warning("Ersparnis-Auswertung fehlgeschlagen: %s", e)
        try:
            store.record_forecast_hours(vrm_data, now)
        except Exception as e:                               # noqa: BLE001
            log.warning("VRM-Prognose (Stunden) konnte nicht gespeichert werden: %s", e)

        dry = bool(cfg.get("dry_run", True))
        wrote = False
        if d.ess_mode != current_ess:
            wrote = cerbo.write_ess_mode(d.ess_mode, dry_run=dry)
            opslog.count("ess_writes", now=now)
            opslog.log("ess", ("(Trockenlauf) " if dry and not wrote else "") + f"ESS-Modus {ESS_TEXT.get(current_ess, current_ess)} → {ESS_TEXT.get(d.ess_mode, d.ess_mode)} "
                       f"({d.strategy}; Preis {d.now_price} ct, Akku {soc:.0f} %)" + ("" if wrote or dry else " [Schreiben fehlgeschlagen]"),
                       dry=dry, price=d.now_price, soc=round(soc, 1), strategy=d.strategy)      # "(Trockenlauf)" immer am Anfang

        with self.lock:
            self.prices = self._prep_prices(prices, d, Params.from_config(cfg).absolute_cheap_price)
            self.status = {
                "ok": True,
                "soc": round(soc, 1),
                "ess_mode": d.ess_mode,
                "ess_current": current_ess,
                "ess_text": ESS_TEXT.get(d.ess_mode, str(d.ess_mode)),
                "allow_now": d.allow_now,
                "now_price": d.now_price,
                "now_slot": d.now_slot,
                "strategy": d.strategy,
                "reason": d.reason,
                "balance": d.balance,
                "plan_windows": d.plan_windows,
                "plan_count": len(d.plan),
                "plan_slots": [{"start": s.start.isoformat(timespec="minutes"),
                                "price": round(s.price, 2)} for s in d.plan],
                "charge_power_w": Params.from_config(cfg).charge_power_w,
                "pv_today": d.solar_today_korr,
                "pv_tom": d.solar_tom_korr,
                "pv_source": pv_source,
                "dry_run": dry,
                "wrote": wrote,
                "ev_active": ev,
                "pv_note": " · ".join(x for x in (price_note, pv_note) if x) or None,
                "system": system,
                "override": bool(cfg.get("manual_override")),
                "tariff_mode": cfg.get("tariff_mode", "tibber"),
                "full_charge": self._full_charge_status(cfg, state, now),
            }
        # Hinweis: Das Energie-Logging läuft in einem eigenen, feineren Takt
        # (run_energy / energy_sample_seconds), NICHT hier - sonst würde die
        # Trapez-Integration doppelt zählen.

        opslog.count("src_vrm" if pv_source == "VRM" else "src_avg", now=now)
        if cfg.get("tariff_mode") != "fixed":
            opslog.count("tibber_cache" if price_note else "tibber_live", now=now)
        if d.ess_mode == ESS_CHARGE:
            opslog.count("charge_ticks", now=now)

        self.last_tick = now.isoformat(timespec="seconds")
        self.last_error = None

    def _prep_prices(self, entries, decision, absolute_cheap_price=0.0):
        # Datums-genauer Abgleich: geplante Slots über den vollen Zeitstempel
        # markieren, NICHT nur über die Uhrzeit - sonst würde z.B. 13:45 an
        # heute UND morgen als geplant erscheinen.
        planned = {p.start.isoformat(timespec="minutes") for p in decision.plan}
        out = []
        for item in entries:
            try:
                start = logic_parse_iso(item["startsAt"])
            except (KeyError, ValueError):
                continue
            ct = round(item["total"] * 100, 2)
            out.append({
                "start": start.isoformat(timespec="seconds"),
                "label": f"{start:%H:%M}",
                "ct": ct,
                "level": item.get("level", "NORMAL"),
                "planned": start.isoformat(timespec="minutes") in planned,
                # Rein optische Vorschau der "Immer laden unter"-Schwelle (siehe
                # logic.decide()) - im Unterschied zu "planned" KEIN Ergebnis der
                # eigentlichen Planung, sondern nur "dieser Slot WUERDE die Regel
                # ausloesen, sobald er dran ist". Reagiert die Steuerung ja ohnehin
                # erst live pro Tick, aber so sieht man vorab, wo es greifen wird.
                "cheap_lock": bool(absolute_cheap_price) and ct <= absolute_cheap_price,
            })
        return out

    @staticmethod
    def _apply_periodic_full_charge(state, params, soc, now):
        """Periodische Vollladung fuer Batteriegesundheit/BMS-Balancing (angeregt durch Victrons 'GX Opportunity
        Loads'-Folien, Venus OS v3.80, 29.09.2026 - siehe Params.periodic_full_charge_days). Hebt NUR die
        Ladeobergrenze (params.max_charge_soc) an, wenn eine Vollladung faellig ist - WANN tatsaechlich geladen
        wird, entscheidet weiterhin die ganz normale preis-/sonnenbewusste Logik danach (Intelligente Planung
        bzw. Standard-Strategien). Es wird nie blind/sofort geladen (Michael, 30.09.: "niemals blind laden und
        die preise ausser acht lassen") - ist gerade kein guenstiger Moment oder scheint keine Sonne, wartet die
        angehobene Grenze einfach weiter, auch ueber mehrere Tage hinweg. pv_reserve_kwh bleibt dabei unangetastet,
        d.h. per Netz wird trotzdem nur bis zur gewohnten Reserve-Grenze zugekauft - die letzten Prozent bis zum
        Ziel soll nach Moeglichkeit die Sonne selbst beisteuern, nicht erzwungener Netzbezug."""
        interval = float(params.periodic_full_charge_days or 0)
        if interval <= 0:
            state.full_charge_pending = False
            return
        target = float(params.periodic_full_charge_target_soc or 100.0)
        due = True
        if state.last_full_charge_date:
            try:
                last = datetime.strptime(state.last_full_charge_date, "%Y-%m-%d").date()
                due = (now.date() - last).days >= interval
            except ValueError:
                due = True
        if due and params.max_charge_soc < target:
            if not state.full_charge_pending:
                opslog.log("battery", f"Periodische Vollladung fällig (alle {interval:.0f} Tage) – "
                           f"Ladeobergrenze bis {target:.0f} % angehoben, sobald Preis/Sonne es hergeben.")
            state.full_charge_pending = True
            params.max_charge_soc = target
        if soc >= target - 0.5 and (state.full_charge_pending or not state.last_full_charge_date):
            if state.full_charge_pending:
                opslog.log("battery", f"Vollladung erreicht ({soc:.0f} %) – nächste periodische Vollladung "
                           f"in {interval:.0f} Tagen fällig.")
            state.last_full_charge_date = now.date().isoformat()
            state.full_charge_pending = False

    @staticmethod
    def _full_charge_status(cfg, state, now):
        """Anzeige-Info fuer die Karte 'Periodische Vollladung' (admin.html): wie viele Tage noch bis zur
        naechsten Faelligkeit, bzw. ob gerade eine faellig ist und auf einen guenstigen Moment/genug Sonne
        wartet. Reine Anzeige - die eigentliche Entscheidung trifft _apply_periodic_full_charge()."""
        interval = float(cfg.get("periodic_full_charge_days") or 0)
        if interval <= 0:
            return {"enabled": False}
        target = float(cfg.get("periodic_full_charge_target_soc") or 100.0)
        last = state.last_full_charge_date or None
        days_since = next_date = None
        if last:
            try:
                last_d = datetime.strptime(last, "%Y-%m-%d").date()
                days_since = (now.date() - last_d).days
                next_date = (last_d + timedelta(days=int(interval))).isoformat()
            except ValueError:
                pass
        days_left = None if days_since is None else max(0, int(interval) - days_since)
        return {"enabled": True, "interval_days": interval, "target_soc": target, "last_date": last,
                "pending": bool(state.full_charge_pending), "days_left": days_left, "next_date": next_date}

    @staticmethod
    def _buffered_floor(params):
        """Untergrenze fuer den Planer (planner.py): der echte Cerbo-Minimalwert (params.soc_floor_pct) plus
        Sicherheitspuffer (params.smart_planner_safety_buffer_pct) - siehe _smart_decision(). Von der Ladeplan-
        Simulation (_run_plansim) genauso benutzt, damit deren 'Bisherige Steuerung' wirklich das zeigt, was live
        passiert, statt mit dem ungenutzten alten night_safety_soc-Default (30%) zu rechnen (Michael, 29.09.:
        Simulation zeigte eine bei 30% schnurgerade SOC-Linie, obwohl der echte Minimalwert+Puffer nur 20% sind)."""
        return min(params.soc_floor_pct + max(0.0, params.smart_planner_safety_buffer_pct),
                   params.max_charge_soc - 1)

    # ------------------------------------------------------------ Ladeplan-Simulation (nur Anzeige)
    @staticmethod
    def _hour_map(hours, now):
        """VRM-Stundenwerte -> {(datum_iso, stunde): Wh}."""
        out = {}
        for h in hours or []:
            day = now.date() if h.get("day") == "today" else now.date() + timedelta(days=1)
            out[(day.isoformat(), int(h["hour"]))] = float(h["wh"])
        return out

    def _smart_decision(self, now, soc, prices, vrm_data, params, state=None):
        """Intelligente Planung (Beta): baut JEDEN Tick frisch aus der aktuellen VRM-Prognose (Sonne + Verbrauch)
        und den Tibber-Preisen einen kostenoptimalen Ladeplan (gleiches Verfahren wie die Ladeplan-Simulation,
        siehe planner.py) und sagt, ob JETZT geladen werden soll. Kein Schwellenwert-Geruest (Peak-Fenster,
        Mindest-SOC-Stufen, "guenstig genug?") mehr - jeder Tick denkt mit dem echten, gerade gemessenen Akkustand
        und der jeweils aktuellsten Prognose neu; weicht die Wirklichkeit von der Prognose ab (Wolken, falsche
        Schaetzung), korrigiert sich das von selbst beim naechsten Tick.
        Commitment (state.smart_commit_slot): hat ein Tick innerhalb einer Viertelstunde einmal "jetzt laden"
        beschlossen, bleibt es dabei bis zum Ende dieser Viertelstunde, auch wenn ein spaeterer Tick (z.B. weil
        der reale SOC inzwischen minimal hoeher ist als die Prognose) knapp auf "reicht schon" umschwenken wuerde -
        sonst flattert die Ladung in Grenzfaellen minuetlich an/aus, statt die 15 Minuten durchzuziehen (Michael,
        28.09.2026). Gleiches Prinzip wie state.commit_slot in logic.decide() fuer die Standard-Logik, nur ein
        eigenes Feld, weil beide Planer unabhaengig voneinander laufen.
        Rueckgabe: (jetzt_laden, geplante_Slots, Text) oder None, wenn die Datenlage nicht reicht (Aufrufer
        faellt dann auf die Standard-Logik zurueck)."""
        if not vrm_data or not vrm_data.get("hours"):
            return None
        solar = self._hour_map(vrm_data["hours"], now)
        if self.pv_cal != 1.0:                               # gleiche Korrektur wie in der Steuerung (nur morgen)
            today_iso = now.date().isoformat()
            solar = {k: (v if k[0] == today_iso else v * self.pv_cal) for k, v in solar.items()}
        cons = self._hour_map((vrm_data.get("cons") or {}).get("hours"), now)
        now_q = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        seen, slots = set(), []
        for item in prices:
            start = logic_parse_iso(item["startsAt"])
            if start >= now_q and start not in seen:
                seen.add(start)
                slots.append(Slot(name="", price=item["total"] * 100, start=start))
        slots.sort(key=lambda x: x.start)
        if not slots or slots[0].start != now_q:
            return None
        res = planner.run(now, soc, params, slots, solar, cons or None, set(), floor_soc=self._buffered_floor(params))
        if not res or not res.get("times"):
            return None
        charge_kwh = res["sim"]["charge_kwh"]
        charge_now = charge_kwh[0] > 1e-6
        plan_slots = [Slot(name="", price=res["prices"][i], start=logic_parse_iso(t))
                      for i, t in enumerate(res["times"]) if charge_kwh[i] > 1e-6]
        # Commitment: einmal in dieser Viertelstunde "laden" beschlossen -> bis zum Slot-Ende dabei bleiben.
        now_slot_name = now_q.isoformat(timespec="minutes")
        committed = ""
        if state is not None:
            committed = state.smart_commit_slot
            if committed and committed != now_slot_name:
                committed = ""                  # neue Viertelstunde angebrochen -> altes Commitment verfaellt
            if charge_now:
                committed = now_slot_name
            elif committed == now_slot_name:
                charge_now = True                # Commitment zieht die Ladung ueber diesen Tick hinweg durch
            state.smart_commit_slot = committed
        windows_txt = merge_into_windows(plan_slots) if plan_slots else ""
        txt = (f"🧠 Intelligente Planung – {'lädt jetzt' if charge_now else 'wartet'} "
               f"({res['prices'][0]:.1f} ct" + (f", geplant: {windows_txt}" if windows_txt else "") + ")")
        return charge_now, plan_slots, txt

    def _run_plansim(self, now, soc, prices, d, vrm_data, params, manual=False):
        if not vrm_data or not vrm_data.get("hours"):
            return {"available": False, "reason": "Die Simulation braucht die VRM-Prognose (Einstellungen → VRM)."}
        solar = self._hour_map(vrm_data["hours"], now)
        if self.pv_cal != 1.0:                               # gleiche Korrektur wie in der Steuerung (nur morgen)
            today_iso = now.date().isoformat()
            solar = {k: (v if k[0] == today_iso else v * self.pv_cal) for k, v in solar.items()}
        cons = self._hour_map((vrm_data.get("cons") or {}).get("hours"), now)
        # eigene Slot-Liste: logic.build_slots dedupliziert nach Uhrzeit (nur 24 h) - der Planer braucht heute UND morgen
        now_q = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        seen, slots = set(), []
        for item in prices:
            start = logic_parse_iso(item["startsAt"])
            if start >= now_q and start not in seen:
                seen.add(start)
                slots.append(Slot(name="", price=item["total"] * 100, start=start))
        slots.sort(key=lambda x: x.start)
        res = planner.run(now, soc, params, slots, solar, cons or None, {x.start for x in d.plan},
                          floor_soc=self._buffered_floor(params))
        if not res:
            return {"available": False, "reason": "Zu wenig Preis- oder Prognosedaten für eine Simulation."}
        try:
            if not manual:                                  # bei manuellem Laden/Ladetermin ist der Vergleich mit der Regel-Steuerung verfaelscht
                store.record_plansim(now, res)
        except Exception as e:                              # noqa: BLE001
            log.warning("Simulations-Protokoll nicht schreibbar: %s", e)
        return {"available": True, "computed": now.isoformat(timespec="seconds"), "result": res,
                "cons_source": "VRM-Verbrauchsprognose" if cons else "Tagesverbrauch (Einstellung) / 24 h",
                "current_strategy": d.strategy, "manual": bool(manual)}

    # ------------------------------------------------------------ Tibber-Preise mit Ausfallsicherung
    _price_fail_since = None
    PRICE_GRACE_MIN = 10          # so lange ohne brauchbare Preise, bevor ein laufendes Netzladen gestoppt wird

    def _tibber_prices(self, cfg, cerbo, current_ess):
        """Preise von Tibber. Faellt der Abruf aus, gelten die zuletzt geholten Preise weiter, solange sie die aktuelle
        Zeit abdecken. Gibt es keine brauchbaren mehr, wird ein laufendes Netzladen nach PRICE_GRACE_MIN gestoppt
        (sichere Rueckfallstufe) und der Durchlauf mit einer klaren Meldung beendet.
        Rueckgabe: (Preise, Hinweistext oder None)."""
        now = datetime.now()
        try:
            prices = fetch_tibber_prices(cfg["tibber_token"])
            if not prices:
                raise ValueError("Tibber lieferte keine Preise")
            if self._price_fail_since is not None:
                opslog.log("tibber", "Tibber-Preise wieder verfügbar")
            self._price_fail_since = None
            notify.event("tibber", False, "", "✅ Tibber-Preise sind wieder verfügbar.")
            try:
                store.record_prices(prices)                  # Preis-Historie (nur bei Aenderung wird geschrieben)
            except Exception as e:                           # noqa: BLE001
                log.warning("Preis-Historie nicht schreibbar: %s", e)
            try:
                price_cache.save(prices, now)
            except Exception as e:                           # noqa: BLE001
                log.warning("Preis-Zwischenspeicher nicht schreibbar: %s", e)
            return prices, None
        except Exception as e:                               # noqa: BLE001
            log.warning("Tibber-Preise nicht abrufbar: %s", e)
            if self._price_fail_since is None:
                opslog.log("tibber", f"Tibber-Abruf fehlgeschlagen: {e}")
            self._price_fail_since = self._price_fail_since or now
            cached = price_cache.load()
            if cached and price_cache.covers(cached["prices"], now):
                stand = str(cached.get("fetched", ""))[11:16]
                notify.event("tibber", True, f"⚠️ Tibber ist seit 20 Minuten nicht erreichbar – die Steuerung nutzt die gespeicherten Preise von {stand} Uhr.",
                             after_min=20)
                return cached["prices"], f"Tibber nicht erreichbar – nutze die Preise von {stand} Uhr"
            stopped = ""
            waited = (now - self._price_fail_since).total_seconds() / 60
            if current_ess == ESS_CHARGE and waited >= self.PRICE_GRACE_MIN:
                try:
                    cerbo.write_ess_mode(ESS_IDLE, dry_run=bool(cfg.get("dry_run", True)))
                    stopped = " – Netzladen wurde gestoppt"
                    opslog.log("tibber", f"Keine brauchbaren Preise seit {waited:.0f} min – Netzladen gestoppt (Ruhe-Modus)")
                    log.warning("Keine brauchbaren Strompreise seit %.0f min - Netzladen gestoppt (Ruhe-Modus)", waited)
                except Exception as e2:                      # noqa: BLE001
                    log.error("Netzladen konnte nicht gestoppt werden: %s", e2)
            notify.event("tibber", True, "⛔ Keine Strompreise verfügbar" + (" – das laufende Netzladen wurde gestoppt." if stopped else "."), after_min=0)
            raise RuntimeError(f"Keine Strompreise verfügbar ({e}){stopped}")

    def _report_line(self):
        """Kurzfassung des Betriebsberichts fuer die Tages-Zusammenfassung per Telegram."""
        try:
            r = report.build(days=1, ctrl=_ctrl_info())
        except Exception as e:                               # noqa: BLE001
            return f"🩺 Systemcheck nicht möglich: {e}"
        bad = [c for c in r["checks"] if c["status"] in ("fail", "warn")]
        if not bad:
            return "🩺 Systemcheck: ✅ läuft sauber"
        return "🩺 Systemcheck: " + ("❌ Probleme" if r["verdict"] == "fail" else "⚠️ Hinweise") + "".join(f"\n• {c['title']}: {c['detail']}" for c in bad[:4])

    def safe_tick(self):
        """Tick mit Fehlerabfang - für Hintergrundschleife und On-Demand-Aufrufe."""
        if not store.module_on("energy"):
            return                                       # Modul Energie aus: nichts regeln (Daten bleiben unberuehrt)
        t_start = time.time()
        try:
            self.tick()
            opslog.note_tick(True, dur_s=time.time() - t_start)
            if self._tick_failed:
                self._tick_failed = False
                opslog.log("tick_ok", "Steuerung läuft wieder normal")
            notify.event("tick_error", False, "", "✅ Die Steuerung läuft wieder normal.")
        except Exception as e:                           # noqa: BLE001
            self.last_error = str(e)
            with self.lock:
                self.status = {"ok": False, "reason": f"Fehler: {e}"}
            log.error("Tick fehlgeschlagen: %s", e)
            opslog.note_tick(False, dur_s=time.time() - t_start)
            self._tick_failed = True
            if str(e) != self._last_err_log[0] or time.time() - self._last_err_log[1] > 1800:      # nicht bei jedem Durchlauf wiederholen
                opslog.log("tick_error", str(e))
                self._last_err_log = (str(e), time.time())
            notify.event("tick_error", True, f"⚠️ Die Steuerung meldet seit 10 Minuten einen Fehler: {e}", after_min=10)

    def run(self, interval):
        while not self._stop.is_set():
            self.safe_tick()
            # Intervall bei jedem Durchlauf frisch lesen -> Änderung in den
            # Einstellungen greift ohne Neustart.
            try:
                interval = max(10, int(store.load_config().get("poll_seconds", 300)))
            except Exception:                            # noqa: BLE001
                interval = 300
            # Auf das Zeitraster ausrichten: der nächste Tick fällt genau auf ein
            # Vielfaches des Intervalls seit voller Stunde. Bei Teilern von 900 s
            # (z.B. 60, 300, 900) trifft das exakt die Viertelstunden :00/:15/:30/:45,
            # sodass Tibber-Slots punktgenau geschaltet werden.
            nowt = time.time()
            sleep_s = interval - (nowt % interval)
            if sleep_s < 1:                              # schon auf dem Raster
                sleep_s += interval
            self._stop.wait(sleep_s)

    def _check_battery_watchdog(self, system: dict, now: datetime):
        """Erkennt den Bulk/Absorption-Haenger vom 01.09.2026: Batterie bewegt
        sich trotz nennenswertem Netzfluss nicht. Nur Erkennung + Log-Warnung,
        kein automatischer Eingriff (siehe Projekt-Notiz - ein Modbus-Befehl
        half beim echten Vorfall nachweislich nicht, nur ein physischer Reset)."""
        try:
            grid_w = system["grid"]["total"]
            batt_a = system["battery"]["current"]
            soc = system["battery"]["soc"]
        except (KeyError, TypeError):
            return
        is_frozen = abs(grid_w) > 150 and abs(batt_a) < 0.5
        detail = {"grid_w": round(grid_w, 1), "battery_a": round(batt_a, 2), "soc": soc}
        try:
            wd = store.battery_watchdog_update(is_frozen, now, detail)
        except Exception as e:                               # noqa: BLE001
            log.warning("Batterie-Watchdog: %s", e)
            return
        if wd["just_warned"]:
            log.warning(
                "Batterie-Watchdog: Batterie reagiert seit >=15 Min nicht (Netz %.0f W, "
                "Batteriestrom %.2f A, SOC %.1f%%) - moeglicher Ladealgorithmus-Haenger "
                "am Multiplus, siehe Projekt-Notiz (Vorfall 01.09.2026)",
                grid_w, batt_a, soc,
            )
        if wd["just_warned"]:
            notify.push("watchdog", f"🔋 Batterie-Watchdog: Die Batterie reagiert seit 15 Minuten nicht (Netz {grid_w:.0f} W, Batteriestrom {batt_a:.2f} A, "
                                    f"Akku {soc:.0f} %). Möglicher Ladehänger am Multiplus – ggf. Anlage prüfen.")
            opslog.log("watchdog", f"Batterie reagiert nicht (Netz {grid_w:.0f} W, {batt_a:.2f} A, Akku {soc:.0f} %)")
        if wd["just_resolved"]:
            notify.push("watchdog", f"✅ Batterie-Watchdog: wieder normal nach {wd['just_resolved']['duration_min']:.0f} Minuten.")
            opslog.log("watchdog", f"wieder normal nach {wd['just_resolved']['duration_min']:.0f} Minuten")
            ev = wd["just_resolved"]
            log.info("Batterie-Watchdog: wieder normal nach %.1f Min (seit %s)",
                     ev["duration_min"], ev["start"])

    def run_energy(self):
        """Eigener, feiner Takt nur für die Energie-Messung. Tastet die
        Momentanleistung häufig ab (Standard 10 s) und integriert sie zu kWh -
        deutlich genauer als der 60-s-Regeltakt, näher an VRM. Läuft unabhängig
        vom Dashboard. Einziger Aufrufer von log_energy_sample (kein Doppelzählen)."""
        while not self._stop.is_set():
            try:
                cfg = store.load_config()
                if store.is_configured(cfg) and store.module_on("energy", cfg):
                    cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
                    system = cerbo.read_system(has_pv_inverter=cfg.get("has_pv_inverter", True),
                                                has_mppt=cfg.get("has_mppt", True))
                    now = datetime.now()
                    with self.lock:
                        price_ct = self.status.get("now_price") if self.status.get("ok") else None
                    store.log_energy_sample(system, now, price_ct=price_ct)
                    self.last_system, self.last_system_ts = system, time.time()
                    self._check_battery_watchdog(system, now)
            except Exception as e:                       # noqa: BLE001
                log.warning("Energie-Sampler: %s", e)
            try:
                iv = max(3, int(store.load_config().get("energy_sample_seconds", 10)))
            except Exception:                            # noqa: BLE001
                iv = 10
            self._stop.wait(iv)

    def _verlauf_extra(self) -> dict:
        """Strompreis jetzt (ct/kWh) fuer die Verlaufs-Reihe: Festpreis bzw. aktueller Tibber-Viertelstundenpreis (wie in den Regeln)."""
        cfg, now, price = store.load_config(), datetime.now(), None
        if cfg.get("tariff_mode") == "fixed":
            fp = float(cfg.get("fixed_price_ct") or 0)
            price = fp if fp > 0 else None
        else:
            slots = store.price_slots(now.date().isoformat())
            if slots:
                price = slots[now.hour * 4 + now.minute // 15]
            if price is None:
                with self.lock:
                    price = self.status.get("now_price")
        return {"price_ct": price}

    def _rules_ctx(self, cfg: dict, system, now: datetime) -> dict:
        """Messwerte fuer die Bedingungen der Regeln (Preis, Akku, Sonne morgen)."""
        with self.lock:
            st = dict(self.status)
        prices, price_ct = None, None
        if cfg.get("tariff_mode") == "fixed":
            fp = float(cfg.get("fixed_price_ct") or 0)
            if fp > 0:
                prices, price_ct = [fp] * 96, fp
        else:
            prices = store.price_slots(now.date().isoformat())
            if prices:
                price_ct = prices[now.hour * 4 + now.minute // 15]
            if price_ct is None:
                price_ct = st.get("now_price")
        try:
            soc = float(system["battery"]["soc"]) if system else None
        except (KeyError, TypeError, ValueError):
            soc = None
        ctx = {"soc": soc, "price_ct": price_ct, "prices_today": prices, "pv_tomorrow": st.get("pv_tom"), "sun": sun.for_config(cfg, now.date())}
        if not store.module_on("energy", cfg):           # Modul Energie aus: keine (veralteten) Energiewerte fuer Regeln - solche Bedingungen gelten als "keine Daten"
            ctx.update({"soc": None, "price_ct": None, "prices_today": None, "pv_tomorrow": None})
        used = {c.get("sensor_id") for r in rules.list_rules() if r.get("enabled", True)
                for c in rules.all_conditions(r) if c.get("type") == "sensor"}
        if used:                                         # nur die Sensoren abfragen, die eine aktive Regel auch braucht
            try:
                sens = [s for s in homematic.load_sensors() if s["id"] in used]
                ctx["sensors"] = homematic.read_values(sens, latch=True)      # latch: kurze Impulse (Lichtschranke) gehen den Regeln nicht verloren
                ctx["sensor_info"] = {s["id"]: s for s in sens}
            except Exception as e:                       # noqa: BLE001
                log.warning("Regeln: Sensorwerte nicht lesbar: %s", e)
        return ctx

    def run_surplus(self):
        """Ueberschuss-Automatik fuer Shelly-Geraete (alle 10 s) - eigener Baustein, eigener Schalter, eigener Trockenlauf, eigenes Logbuch.
        Nutzt die Messwerte des Energie-Samplers; ohne frische Werte wird nichts geschaltet."""
        while not self._stop.is_set():
            try:
                cfg = store.load_config()
                if cfg.get("surplus_enabled") and store.module_on("energy", cfg) and store.module_on("smarthome", cfg):
                    system = self.last_system if time.time() - self.last_system_ts < 45 else None
                    if system:
                        dry = bool(cfg.get("surplus_dry_run", True))
                        ruled = {i for r in rules.list_rules() for i in rules.devices_of(r)}         # Geraete mit Regeln gehoeren den Regeln (Schutz vor Doppelschaltung)
                        devs = sorted((d for d in shelly.list_with_status() if d["id"] not in ruled), key=lambda d: d.get("prio") or 10 ** 6)   # Prioritaet
                        if dry:      # Trockenlauf: mit gedachtem statt echtem Zustand rechnen
                            for d in devs:
                                if d["id"] in self._surplus_dry_on:
                                    d["on"] = self._surplus_dry_on[d["id"]]
                        now = datetime.now()
                        if dry:
                            surplus_ctrl.disarm_all()
                        else:        # Sicherheits-Timer der zugeschalteten Geraete verlaengern (nur bei frischen Messwerten)
                            fs = surplus.settings(cfg)["failsafe_min"]
                            for d in surplus_ctrl.due_rearm(now, cfg, devs):
                                try:
                                    shelly.set_state(d["id"], True, timer_s=int(fs * 60))
                                    surplus_ctrl.mark_armed(d["id"], now)
                                except shelly.ShellyError as e:
                                    log.warning("Sicherheits-Timer %s: %s", d["name"], e)
                        act = surplus_ctrl.step(now, system, cfg, devs)
                        if act:
                            self._apply_surplus(act, dry, cfg)
                else:
                    surplus_ctrl.reset_timers()
                    surplus_ctrl.disarm_all()   # Timer laufen aus -> Geraete schalten sich selbst ab
                    self._surplus_dry_on.clear()
            except Exception as e:                       # noqa: BLE001
                log.warning("Ueberschuss-Automatik: %s", e)
            self._stop.wait(10)

    def _apply_surplus(self, act, dry: bool, cfg: dict):
        action, dev, why = act
        on = action == "on"
        verb = "eingeschaltet" if on else "ausgeschaltet"
        ok = True
        if dry:
            self._surplus_dry_on[dev["id"]] = on
            text = f"(Trockenlauf) {dev['name']} würde {verb} – {why}"
        else:
            try:
                fs = surplus.settings(cfg)["failsafe_min"]
                timer_s = int(fs * 60) if on and fs > 0 and dev.get("kind") not in ("tuya", "zigbee") else None
                shelly.set_state(dev["id"], on, timer_s=timer_s)
                if timer_s:
                    surplus_ctrl.mark_armed(dev["id"])
                elif not on:
                    surplus_ctrl.disarm(dev["id"])
                text = f"{dev['name']} {verb} – {why}"
            except shelly.ShellyError as e:
                ok = False
                text = f"{dev['name']}: Schalten fehlgeschlagen ({e})"
        log.info("Ueberschuss-Automatik: %s", text)
        opslog.log("surplus", text, dry=dry)
        autolog.log("surplus", text, dev=dev["name"], action=(action if ok else "fail"), dry=dry)
        surplus_ctrl.log(text)
        notify.push("surplus", ("🧪 " if dry else "🔌 ") + text, cfg)      # auch im Trockenlauf (Text beginnt dann mit "(Trockenlauf)")

    def run_rules(self):
        """Regel-Engine fuer Geraete (alle 10 s) - eigener Baustein, eigener Schalter, eigener Trockenlauf, eigenes Logbuch."""
        last_flush = 0.0
        while not self._stop.is_set():
            try:
                self._rules_wake.clear()                 # Meldungen waehrend dieser Runde loesen gleich die naechste aus
                cfg = store.load_config()
                all_rules = rules.list_rules()
                if rules.enabled(cfg) and store.module_on("smarthome", cfg) and (all_rules or rule_engine.owner):        # auch mit nur ausgeschalteten/geloeschten Regeln: was sie eingeschaltet haben, wird abgeschaltet
                    dry = rules.dry_run(cfg)
                    need = set(rule_engine.owner)                       # nur Geraete abfragen, die Regeln betreffen (macht die Runde schnell)
                    for r in all_rules:
                        need.update(rules.devices_of(r))
                        need.update(c["device_id"] for c in rules.all_conditions(r) if c.get("type") == "device")
                    devs = shelly.list_with_status(ids=need)
                    used_s = {c.get("sensor_id") for r in all_rules if r.get("enabled", True) for c in rules.all_conditions(r) if c.get("type") == "sensor"}
                    homematic.set_watch([d["address"] for d in devs if d.get("kind") == "homematic" and d.get("address")]
                                        + [s_["address"] for s_ in homematic.load_sensors() if s_["id"] in used_s])      # nur deren Meldungen wecken die Regeln
                    if dry:      # Trockenlauf: mit gedachtem statt echtem Zustand rechnen
                        for d in devs:
                            if d["id"] in self._rules_dry_on:
                                d["on"] = self._rules_dry_on[d["id"]]
                    now = datetime.now()
                    system = self.last_system if time.time() - self.last_system_ts < 45 else None
                    if dry:
                        rule_engine.disarm_all()
                    else:        # Sicherheits-Timer der eingeschalteten Geraete verlaengern
                        fs = rules.settings(cfg)["failsafe_min"]
                        for d in rule_engine.due_rearm(now, devs, fs):
                            try:
                                shelly.set_state(d["id"], True, timer_s=int(fs * 60))
                                rule_engine.mark_armed(d["id"], now)
                            except shelly.ShellyError as e:
                                log.warning("Sicherheits-Timer %s: %s", d["name"], e)
                    ctx = self._rules_ctx(cfg, system, now)
                    ctx["devices"] = {d["id"]: d for d in devs}                      # Zustand/Leistung anderer Geraete als Bedingung
                    ctx["virtual"] = virtual.snapshot()                              # eigene Schalter/Knoepfe
                    pressed = virtual.pressed_ids()
                    for act in rule_engine.step(now, ctx, cfg, devs, rules.compile_all(all_rules)):
                        self._apply_rule(act, dry, cfg)
                    for ev in flow_engine.step(now, ctx, [r for r in all_rules if flows.is_flow(r)]):
                        self._log_flow_event(ev, dry)
                    for act in flow_engine.advance(skip_waits=dry):
                        try:
                            self._apply_flow(act, dry, cfg)
                        except Exception as e:                                       # noqa: BLE001
                            log.warning("Ablauf-Schritt fehlgeschlagen: %s", e)         # ein kaputter Schritt darf die folgenden nicht verschlucken
                            autolog.log("rules", f"Regel „{act.get('rule', '')}“: Schritt fehlgeschlagen ({e})", dev=act.get("rule", ""), action="fail", dry=dry, rule=act.get("rule_id"))
                    virtual.consume(pressed)                                         # Knopfdruck war genau einen Durchlauf lang sichtbar
                    if time.time() - last_flush > 60:
                        rule_engine.flush()
                        last_flush = time.time()
                else:
                    rule_engine.reset()
                    rule_engine.disarm_all()    # Timer laufen aus -> Geraete schalten sich selbst ab
                    self._rules_dry_on.clear()
                    for ev in flow_engine.cancel_all("Regeln insgesamt ausgeschaltet – laufender Ablauf abgebrochen"):
                        self._log_flow_event(ev, False)
                    flow_engine.forget()
                    virtual.consume(virtual.pressed_ids())
            except Exception as e:                       # noqa: BLE001
                log.warning("Regel-Engine: %s", e)
            fast = any(c.get("type") in ("sensor", "device") for r in rules.list_rules() if r.get("enabled", True) for c in rules.all_conditions(r))
            live_s = {c.get("sensor_id") for r in rules.list_rules() if r.get("enabled", True) for c in rules.all_conditions(r) if c.get("type") == "sensor"}
            polled = any(s_.get("source") in ("zigbee", "camera") for s_ in homematic.load_sensors() if s_["id"] in live_s)      # Zigbee/Kamera melden nichts von selbst: jede Sekunde abfragen
            iv = 1 if polled else (10 if homematic.push_active() else (2 if fast else 10))      # mit Push (Meldung der CCU) genuegt die Reserve-Runde; sonst alle 2 s abfragen
            nd = flow_engine.next_due()
            vd = virtual.next_due()
            if vd:                                                          # ein Nachlauf-Timer laeuft ab: genau dann nachsehen (Geraete gehen pünktlich aus)
                nd = min(nd, vd) if nd else vd
            if nd:
                iv = min(iv, max(0.2, nd - time.time()))                       # laufender Ablauf: genau zum naechsten Schritt aufwachen
            self._rules_wake.wait(iv)                    # Meldung der CCU weckt sofort
            self._stop.wait(0.05)

    def _log_flow_event(self, ev, dry: bool):
        kind, rule, why = ev
        text = ("(Trockenlauf) " if dry else "") + f"Regel „{rule.get('name', '')}“: {why}"
        log.info("Regeln: %s", text)
        opslog.log("rules", text, dry=dry)
        autolog.log("rules", text, dev=rule.get("name", ""), action=kind, dry=dry, rule=rule.get("id"))

    def _apply_flow(self, act, dry: bool, cfg: dict):
        """Ein Schritt eines Ablaufs: Geraet schalten, Sollwert setzen, Nachricht senden, eigenen Schalter setzen."""
        st, rule = act["step"], act["rule"]
        after = f" (nach {int(act['after_s'] // 60)} min {int(act['after_s'] % 60)} s)" if dry and act.get("after_s") else ""
        t = st.get("type", "switch")
        jobs = []                                         # (aktion-fuers-logbuch, geraet, text, ok, fehler)
        names = {d["id"]: d["name"] for d in shelly.load_devices()}
        if t in ("switch", "toggle"):
            name = names.get(st["device_id"], st["device_id"])
            err = None
            on = st.get("state") == "on"
            if t == "toggle":                                  # aktuellen Zustand lesen (im Trockenlauf: den gedachten)
                try:
                    cur = next((d for d in shelly.list_with_status(ids={st["device_id"]})), None)
                except Exception as e:                         # noqa: BLE001
                    cur, err = None, str(e)
                if st["device_id"] in self._rules_dry_on and dry:
                    on = not self._rules_dry_on[st["device_id"]]
                elif cur and cur.get("online"):
                    on = not cur.get("on")
                else:
                    err = err or "Gerät nicht erreichbar – Umschalten nicht möglich"
            if not err:
                if dry:
                    self._rules_dry_on[st["device_id"]] = on
                else:
                    try:
                        shelly.set_state(st["device_id"], on, timer_s=0 if on else None)
                    except shelly.ShellyError as e:
                        err = str(e)
            jobs.append(("on" if on else "off", name, (f"{name} umgeschaltet → {'ein' if on else 'aus'}" if t == "toggle" else f"{name} {'eingeschaltet' if on else 'ausgeschaltet'}") if not err else f"{name}: Schalten fehlgeschlagen ({err})", err))
        elif t == "setpoint":
            if dry:
                names_sp = [s["name"] for s in homematic.load_setpoints() if "*" in st["device_ids"] or s["id"] in st["device_ids"]]
                jobs.append(("setpoint", ", ".join(names_sp) or "Thermostate", f"Solltemperatur {st['value']:g} °C würde gesetzt: {', '.join(names_sp) or '–'}", None))
            else:
                try:
                    for name, v, err in homematic.set_setpoints(st["device_ids"], st["value"]):
                        jobs.append(("setpoint" if not err else "fail", name, f"{name}: Solltemperatur {v:g} °C" if not err else f"{name}: Solltemperatur setzen fehlgeschlagen ({err})", err))
                except homematic.HomematicError as e:
                    jobs.append(("fail", "Thermostate", f"Solltemperatur setzen fehlgeschlagen ({e})", str(e)))
        elif t == "wol":
            tgt = next((x for x in wol.load() if x["id"] == st["id"]), None)
            if not tgt:
                jobs.append(("fail", st["id"], "Rechner zum Aufwecken existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("wol", tgt["name"], f"{tgt['name']} würde per Wake-on-LAN aufgeweckt", None))
            else:
                try:
                    wol.wake(st["id"])
                    jobs.append(("wol", tgt["name"], f"{tgt['name']}: Wake-on-LAN-Paket gesendet", None))
                except wol.WolError as e:
                    jobs.append(("fail", tgt["name"], f"{tgt['name']}: {e}", str(e)))
        elif t == "lock":
            what = {"lock": "verriegelt", "unlock": "entriegelt", "open": "geöffnet"}[st["state"]]
            lname = next((k["name"] for k in homematic.load_locks() if k["id"] == st["id"]), st["id"])
            if dry:
                jobs.append(("lock", lname, f"Türschloss {lname} würde {what}", None))
            else:
                try:
                    homematic.lock_action(st["id"], st["state"])
                    jobs.append(("lock", lname, f"Türschloss {lname} {what}", None))
                    if st["state"] != "lock":
                        notify.push("rules", f"🔓 Türschloss {lname} {what} (Regel „{rule}“)", cfg)
                except homematic.HomematicError as e:
                    jobs.append(("fail", lname, f"Türschloss {lname}: {e}", str(e)))
        elif t == "notify":
            sent = False if dry else notify.message(st["text"], cfg, st.get("to"))
            who = (" an " + notify.names(st.get("to"))) if st.get("to") else ""
            jobs.append(("notify", "Telegram", f"Nachricht{who} {'gesendet' if sent else ('würde gesendet' if dry else 'NICHT gesendet (Telegram nicht eingerichtet)')}: {st['text']}", None if (sent or dry) else "Telegram nicht eingerichtet"))
        elif t == "pushover":
            cam = camera.get(st["camera"]) if st.get("camera") else None
            who = (" an " + pushover.names(st.get("to"))) if st.get("to") else ""
            with_img = f" mit Bild von {cam['name']}" if cam else ""
            if st.get("camera") and not cam:
                jobs.append(("fail", st["camera"], "Kamera für das Pushover-Bild existiert nicht mehr", "weg"))
            elif cam and not store.module_on("cameras", cfg if cfg else None):
                jobs.append(("fail", cam["name"], "Pushover mit Bild nicht möglich: Modul Kameras ist ausgeschaltet", "aus"))
            elif dry:
                jobs.append(("notify", "Pushover", f"Pushover-Nachricht{who}{with_img} würde gesendet: {st['text']}", None))
            else:
                sent = pushover.message(st["text"], cfg, st.get("title"), st.get("priority", 0), st.get("sound"), st.get("to"),
                                        (lambda cam=cam: camera.snapshot(cam, max_age=0.0)) if cam else None)
                jobs.append(("notify", "Pushover", f"Pushover-Nachricht{who}{with_img} {'wird gesendet' if sent else 'NICHT gesendet (Pushover nicht eingerichtet)'}: {st['text']}",
                             None if sent else "Pushover nicht eingerichtet"))
        elif t == "sound":
            sname = next((x["name"] for x in homematic.load_sounds() if x["id"] == st["id"]), None)
            what = f"Titel {st['track']}, {st['volume']} %" + (f", {st['repeats']}×" if st["repeats"] > 1 else "")
            if sname is None:
                jobs.append(("fail", st["id"], "Soundmodul existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("sound", sname, f"{sname}: Sound würde abgespielt ({what})", None))
            else:
                try:
                    homematic.sound_play(st["id"], st["track"], st["volume"], st["repeats"])
                    jobs.append(("sound", sname, f"{sname}: Sound abgespielt ({what})", None))
                except homematic.HomematicError as e:
                    jobs.append(("fail", sname, f"{sname}: {e}", str(e)))
        elif t == "blind":
            bl = next((x for x in homematic.load_blinds() if x["id"] == st["id"]), None)
            what = "anhalten" if st.get("action") == "stop" else f"auf {st['level']} %"
            if bl is None:
                jobs.append(("fail", st["id"], "Rollladen existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("blind", bl["name"], f"{bl['name']}: Rollladen würde {what}", None))
            else:
                try:
                    if st.get("action") == "stop":
                        homematic.blind_stop(st["id"])
                    else:
                        homematic.blind_set(st["id"], st["level"])
                    jobs.append(("blind", bl["name"], f"{bl['name']}: Rollladen {what}", None))
                except homematic.HomematicError as e:
                    jobs.append(("fail", bl["name"], f"{bl['name']}: {e}", str(e)))
        elif t == "ac":
            ad = next((x for x in shelly.load_devices() if x["id"] == st["id"] and x.get("kind") == "midea"), None)
            parts = [{"on": "einschalten", "off": "ausschalten"}.get(st.get("power"), "")] + ([f"Modus {midea.MODE_LABELS.get(st['mode'], st['mode'])}"] if st.get("mode") else []) \
                + ([f"{st['target']:g} °C"] if st.get("target") is not None else []) + ([f"Lüfter {midea.FAN_LABELS.get(st['fan'], st['fan'])}"] if st.get("fan") else [])
            what = ", ".join(p for p in parts if p)
            if ad is None:
                jobs.append(("fail", st["id"], "Klimaanlage existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("ac", ad["name"], f"{ad['name']}: Klimaanlage würde gestellt: {what}", None))
            else:
                try:
                    shelly.midea_set(st["id"], power=({"on": True, "off": False}.get(st.get("power"))), mode=st.get("mode"), target=st.get("target"), fan=st.get("fan"))
                    jobs.append(("ac", ad["name"], f"{ad['name']}: Klimaanlage gestellt: {what}", None))
                except shelly.ShellyError as e:
                    jobs.append(("fail", ad["name"], f"{ad['name']}: {e}", str(e)))
        elif t == "wled":
            wd = next((x for x in shelly.load_devices() if x["id"] == st["id"] and x.get("kind") == "wled"), None)
            what = f"Voreinstellung {st['preset']}" if st.get("mode") == "preset" else f"Farbe {st['color']}" + (f", Helligkeit {st['brightness']} %" if st.get("brightness") else "")
            if wd is None:
                jobs.append(("fail", st["id"], "WLED-Gerät existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("wled", wd["name"], f"{wd['name']}: WLED würde auf {what} gestellt", None))
            else:
                try:
                    shelly.wled_apply(st["id"], st.get("mode"), st.get("preset"), st.get("color"), st.get("brightness"))
                    jobs.append(("wled", wd["name"], f"{wd['name']}: WLED auf {what} gestellt", None))
                except shelly.ShellyError as e:
                    jobs.append(("fail", wd["name"], f"{wd['name']}: {e}", str(e)))
        elif t == "photo":
            cam = camera.get(st["id"])
            if not store.module_on("cameras", cfg if cfg else None):
                jobs.append(("fail", st["id"], "Kamera-Standbild nicht möglich: Modul Kameras ist ausgeschaltet", "aus"))
            elif not cam:
                jobs.append(("fail", st["id"], "Kamera für das Standbild existiert nicht mehr", "weg"))
            elif dry:
                jobs.append(("notify", cam["name"], f"Standbild von {cam['name']} würde per Telegram gesendet" + (" an " + notify.names(st.get("to")) if st.get("to") else ""), None))
            else:
                cap = (st.get("text") or "").strip() or f"📷 {cam['name']}"
                sent = notify.photo(lambda cam=cam: camera.snapshot(cam, max_age=0.0), cap, cfg, st.get("to"))
                who = (" an " + notify.names(st.get("to"))) if st.get("to") else ""
                jobs.append(("notify", cam["name"], f"Standbild von {cam['name']} {'wird per Telegram' + who + ' gesendet' if sent else 'NICHT gesendet (Telegram nicht eingerichtet)'}", None if sent else "Telegram nicht eingerichtet"))
        elif t == "video":
            cam = camera.get(st["id"])
            what = ", ".join(camera.VIDEO_LABEL[x] for x in camera.VIDEO_TYPES if x in (st.get("filter") or [])) or "jedes Ereignis"
            if not store.module_on("cameras", cfg if cfg else None):
                jobs.append(("fail", st["id"], "Video nicht möglich: Modul Kameras ist ausgeschaltet", "aus"))
            elif not cam:
                jobs.append(("fail", st["id"], "Kamera für das Video existiert nicht mehr", "weg"))
            elif cam.get("kind", "reolink") != "reolink":
                jobs.append(("fail", cam["name"], f"Video von {cam['name']} nicht möglich: nur Reolink-Kameras mit SD-Karte werden unterstützt", "kein Reolink"))
            elif dry:
                jobs.append(("notify", cam["name"], f"Video von {cam['name']} ({what}) würde per Telegram gesendet" + (" an " + notify.names(st.get("to")) if st.get("to") else ""), None))
            else:
                sent = notify.video(cam, set(st.get("filter") or []), (st.get("text") or "").strip(), cfg, st.get("to"))
                who = (" an " + notify.names(st.get("to"))) if st.get("to") else ""
                jobs.append(("notify", cam["name"], f"Video von {cam['name']} ({what}) {'wird, sobald die Aufnahme fertig ist, per Telegram' + who + ' gesendet' if sent else 'NICHT gesendet (Telegram nicht eingerichtet)'}", None if sent else "Telegram nicht eingerichtet"))
        elif t == "http":
            label = st.get("label") or "Web-Aufruf"
            meth = st.get("method", "GET")
            if dry:
                jobs.append(("notify", label, f"Web-Aufruf „{label}“ ({meth}) würde ausgeführt", None))
            else:
                webhook.fire(f"rule-{act['rule_id']}", f"{rule} – {label}", st["url"], meth)         # im Hintergrund; Ergebnis steht im Logbuch (ohne Adresse)
                jobs.append(("notify", label, f"Web-Aufruf „{label}“ ({meth}) wird ausgeführt", None))
        elif t == "virtual":
            vname = next((v["name"] for v in virtual.load() if v["id"] == st["id"]), None)
            if vname is None:
                jobs.append(("fail", st["id"], "Eigener Schalter existiert nicht mehr", "weg"))
            else:
                what = {"on": "eingeschaltet", "off": "ausgeschaltet", "press": "gedrückt", "toggle": "umgeschaltet"}[st["state"]]
                if not dry:
                    ok = (virtual.press(st["id"]) if st["state"] == "press" else virtual.toggle(st["id"]) if st["state"] == "toggle"
                          else virtual.set_state(st["id"], st["state"] == "on"))
                    if ok:
                        self._rules_wake.set()
                jobs.append(("virtual", vname, f"Eigener Schalter {vname} {what}", None))
        for action, dev, text, err in jobs:
            full = ("(Trockenlauf) " if dry else "") + f"Regel „{rule}“: {text}{after}"
            log.info("Regeln: %s", full)
            opslog.log("rules", full, dry=dry)
            autolog.log("rules", full, dev=dev, action=("fail" if err else action), dry=dry, rule=act["rule_id"])

    def _apply_rule(self, act, dry: bool, cfg: dict):
        action, dev, why, rule_id = act
        if action in ("adopt", "manual", "paused"):      # nur ins Logbuch: nichts wird geschaltet
            text = ("(Trockenlauf) " if dry else "") + f"{dev['name']} {why}"          # "(Trockenlauf)" steht immer am Anfang
            log.info("Regeln: %s", text)
            opslog.log("rules", text, dry=dry)
            autolog.log("rules", text, dev=dev["name"], action=action, dry=dry, rule=rule_id)
            return
        on = action == "on"
        verb = "eingeschaltet" if on else "ausgeschaltet"
        ok = True
        if dry:
            self._rules_dry_on[dev["id"]] = on
            text = f"(Trockenlauf) {dev['name']} würde {verb} – {why}"
        else:
            try:
                fs = rules.settings(cfg)["failsafe_min"]
                timer_s = int(fs * 60) if on and fs > 0 and dev.get("kind") not in ("tuya", "zigbee") else None
                shelly.set_state(dev["id"], on, timer_s=timer_s)
                if timer_s:
                    rule_engine.mark_armed(dev["id"])
                elif not on:
                    rule_engine.disarm(dev["id"])
                text = f"{dev['name']} {verb} – {why}"
            except shelly.ShellyError as e:
                ok = False
                text = f"{dev['name']}: Schalten fehlgeschlagen ({e})"
        if ok:
            rule_engine.set_owner(dev["id"], "rule" if on else None, rule_id)
        log.info("Regeln: %s", text)
        opslog.log("rules", text, dry=dry)
        autolog.log("rules", text, dev=dev["name"], action=(action if ok else "fail"), dry=dry, rule=rule_id)
        notify.push("rules", ("🧪 " if dry else "📐 ") + text, cfg)

    def start(self):
        cfg = store.load_config()
        interval = int(cfg.get("poll_seconds", 300))
        threading.Thread(target=self.run, args=(interval,), daemon=True).start()
        threading.Thread(target=self.run_energy, daemon=True).start()
        threading.Thread(target=self.run_surplus, daemon=True).start()
        threading.Thread(target=self.run_rules, daemon=True).start()
        self.verlauf = verlauf.Sampler(lambda: self.last_system if time.time() - self.last_system_ts < 45 else None, self._verlauf_extra)
        threading.Thread(target=self.verlauf.run, daemon=True).start()
        def _fixed_price_housekeeping():                                                    # Festpreis: erst Perioden auf den Preis ergaenzen, dann Kosten nachgeholter Tage nachrechnen
            if not store.module_on("energy"):
                return
            try:
                store.migrate_contract_periods()
            except Exception as e:                                                          # noqa: BLE001
                log.warning("Tarif-Perioden: %s", e)
            store.repair_fixed_costs_once()
        threading.Thread(target=_fixed_price_housekeeping, daemon=True).start()
        homematic.add_listener(self._rules_wake.set)               # Meldung der CCU -> Regeln sofort pruefen
        homematic.push_start()
        tunnel.startup()                                           # Cloudflare-Tunnel (Fernzugriff) wieder verbinden, falls eingeschaltet
        _alexa_sync()                                              # Alexa-Anbindung (Hue-Emulation), nur wenn das Modul an ist


ctrl = Controller()


# --- Routen ---------------------------------------------------------------
@app.route("/")
def index():
    if store.module_on("energy") and not store.is_configured():
        return redirect("/setup")
    return render_template("index.html")


# ---------------------------------------------------------------- Alexa (Hue-Emulation, siehe alexa.py)
_alexa_cache: dict = {}                                       # geraete-id -> (Zeit, an?)  - Echo fragt oft und von vielen Geraeten gleichzeitig
_alexa_pool = None
ALEXA_TTL_S = 4.0                                             # so lange gilt ein gelesener Zustand
ALEXA_DEADLINE_S = 1.0                                        # laenger darf eine Antwort an Echo nie dauern - sonst verwirft Alexa das Geraet still


def _alexa_states(devs: list) -> dict:
    """{hid: (an?, erreichbar?)} - eigene Schalter aus dem Speicher; Hardware-Geraete kurz zwischengespeichert und mit festem Zeitlimit
    abgefragt (ein langsames/offline Geraet haelt Alexa nie auf; dann gilt der letzte bekannte Zustand)."""
    global _alexa_pool
    out, now = {}, time.time()
    ids = {d["ref"] for d in devs if d["kind"] == "shelly"}
    stale = {i for i in ids if now - _alexa_cache.get(i, (0, None))[0] > ALEXA_TTL_S}
    if stale:
        if _alexa_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _alexa_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="alexa-state")
        from concurrent.futures import wait
        futs = {i: _alexa_pool.submit(lambda i=i: next(iter(shelly.list_with_status(ids={i})), None)) for i in stale}          # je Geraet einzeln: ein langsames haelt die anderen nicht auf
        done, _ = wait(list(futs.values()), timeout=ALEXA_DEADLINE_S)
        for i, f in futs.items():
            try:
                x = f.result(timeout=0) if f in done else None
            except Exception:                                # noqa: BLE001
                x = None
            if x is not None:
                _alexa_cache[i] = (time.time(), bool(x.get("on")))
            else:                                            # Zeitlimit/Fehler: letzten Zustand behalten, in 1 s erneut versuchen
                _alexa_cache[i] = (now - ALEXA_TTL_S + 1.0, _alexa_cache.get(i, (0, False))[1])
    snap = virtual.snapshot()
    for d in devs:
        if d["kind"] == "virtual":
            info = snap.get(d["ref"])
            out[d["hid"]] = (bool(info and info.get("on")), info is not None)
        else:
            out[d["hid"]] = (bool(_alexa_cache.get(d["ref"], (0, False))[1]), True)
    return out


def _alexa_set(dev: dict, on: bool) -> bool:
    """Schalten per Sprache. Geraete mit PIN werden NIE per Sprache geschaltet (Sicherheit)."""
    if dev["kind"] == "virtual":
        vid = dev["ref"]
        item = next((v for v in virtual.load() if v["id"] == vid), None)
        if not item or virtual.has_pin(vid):
            return False
        if item["kind"] == "button":
            ok = virtual.press(vid) if on else True              # Knopf: "ein" = druecken, "aus" tut nichts
        else:
            ok = virtual.set_state(vid, on)
        ctrl._rules_wake.set()
        if on or item["kind"] != "button":
            opslog.log("rules", f"Alexa: {item['name']} {'gedrückt' if item['kind'] == 'button' else ('eingeschaltet' if on else 'ausgeschaltet')}", dry=False)
        return bool(ok)
    did = dev["ref"]
    d = next((x for x in shelly.load_devices() if x["id"] == did), None)
    if not d or shelly.has_pin(did) or d.get("switchable", True) is False:
        return False
    shelly.set_state(did, on, timer_s=0 if on else None)
    _alexa_cache[did] = (time.time(), bool(on))                 # Zustand sofort merken (naechste Abfrage von Alexa zeigt ihn gleich richtig)
    cfg_ = store.load_config()
    surplus_ctrl.note_manual(did, hold_min=surplus.settings(cfg_)["manual_hold_min"])       # wie von Hand geschaltet: Automatik/Regeln pausieren fuer dieses Geraet
    rule_engine.note_manual(did, hold_min=rules.settings(cfg_)["manual_hold_min"])
    opslog.log("rules", f"Alexa: {d['name']} {'eingeschaltet' if on else 'ausgeschaltet'}", dry=False)
    return True


def _alexa_serial() -> str:
    """Eigene, dauerhaft gespeicherte Bridge-Kennung dieser App-Instanz (jede Installation hat ihre eigene)."""
    cfg_ = store.load_config()
    ser = str(cfg_.get("alexa_serial") or "")
    if len(ser) != 12 or any(c not in "0123456789abcdef" for c in ser):
        ser = alexa.new_serial()
        cfg_["alexa_serial"] = ser
        try:
            store.save_config(cfg_)
        except OSError as e:
            log.warning("Alexa-Kennung nicht speicherbar: %s", e)
    return ser


alexa_bridge = alexa.Bridge(_alexa_states, _alexa_set, http_port=int(store.load_config().get("alexa_port", 80) or 80),
                            bind_ip=str(store.load_config().get("alexa_bind_ip") or ""), serial=str(store.load_config().get("alexa_serial") or ""))
alexa_bridge.public_port = 80 if alexa_bridge.http_port != 80 else None        # Echo spricht immer Port 80 - ein anderer interner Port heisst: Webserver davor


def _alexa_sync():
    """Bruecke starten/stoppen je nach Modul (Alexa UND Smart Home muessen an sein)."""
    want = store.module_on("alexa") and store.module_on("smarthome") and not sandbox.ACTIVE
    try:
        if want and not alexa_bridge.running:
            alexa_bridge.serial = _alexa_serial()                 # eigene, feste Kennung dieser Installation (beim ersten Start erzeugt und gespeichert)
            alexa_bridge.start()
        elif not want and alexa_bridge.running:
            alexa_bridge.stop()
    except Exception as e:                                   # noqa: BLE001
        log.warning("Alexa-Anbindung: %s", e)


def _alexa_eligible() -> list:
    """Geraete, die freigegeben werden duerfen: schaltbar und OHNE PIN, noch nicht freigegeben."""
    used = {(x["kind"], x["ref"]) for x in alexa.load()}
    out = []
    for d in shelly.load_devices():
        if d.get("switchable", True) is False or d.get("pin_hash") or ("shelly", d["id"]) in used:
            continue
        out.append({"kind": "shelly", "ref": d["id"], "name": d.get("name", d["id"]), "icon": d.get("icon", "🔌"), "what": "Gerät"})
    for v in virtual.load():
        if v.get("pin_hash") or ("virtual", v["id"]) in used:
            continue
        out.append({"kind": "virtual", "ref": v["id"], "name": v.get("name", v["id"]), "icon": v.get("icon", "🔘"), "what": "Knopf" if v.get("kind") == "button" else "Schalter"})
    return out


@app.route("/api/alexa", methods=["GET"])
def api_alexa():
    """Alexa-Anbindung: Status der Bruecke, freigegebene Geraete, freigebbare Geraete."""
    if not alexa_bridge.running:
        alexa_bridge.serial = _alexa_serial()                # eigene Kennung (einmalig erzeugt) schon vor dem ersten Start anzeigen
    names = {("shelly", d["id"]): d for d in shelly.load_devices()}
    names.update({("virtual", v["id"]): v for v in virtual.load()})
    devices = []
    for x in alexa.load():
        src = names.get((x["kind"], x["ref"]))
        devices.append({**x, "source": (src or {}).get("name") or "(Gerät fehlt)", "missing": src is None, "icon": (src or {}).get("icon", ""),
                        "pin": bool(src and src.get("pin_hash"))})
    return jsonify(module=store.module_on("alexa"), status=alexa_bridge.status(), devices=devices, eligible=_alexa_eligible() if auth.is_full_admin(g.perms) else [])


@app.route("/api/alexa/settings", methods=["POST"])
def api_alexa_settings():
    """Interner Port der Bridge (80 = direkt; z. B. 8099, wenn ein Webserver auf Port 80 davor die Hue-Anfragen weiterreicht)."""
    denied = _admin_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        port = int(str(body.get("port", alexa_bridge.http_port)).strip())
    except ValueError:
        return jsonify(error="Port: Zahl erwartet"), 400
    if port != 80 and not 1024 <= port <= 65535:
        return jsonify(error="Port: 80 oder zwischen 1024 und 65535"), 400
    bind_ip = str(body.get("bind_ip", alexa_bridge.bind_ip) or "").strip()
    if bind_ip:
        parts = bind_ip.split(".")
        if len(parts) != 4 or not all(x.isdigit() and 0 <= int(x) <= 255 for x in parts):
            return jsonify(error="Adresse der Bridge: eine IPv4-Adresse (z. B. 192.168.2.41) oder leer lassen"), 400
    cfg = store.load_config()
    cfg["alexa_port"] = port
    cfg["alexa_bind_ip"] = bind_ip
    store.save_config(cfg)
    was = alexa_bridge.running
    if was:
        alexa_bridge.stop()
    alexa_bridge.http_port = port
    alexa_bridge.bind_ip = bind_ip
    alexa_bridge.public_port = 80 if port != 80 else None
    if was or (store.module_on("alexa") and store.module_on("smarthome")):
        _alexa_sync()
    return jsonify(ok=True, status=alexa_bridge.status())


@app.route("/api/alexa/devices", methods=["POST"])
def api_alexa_add():
    denied = _admin_only()
    if denied:
        return denied
    b = request.get_json(silent=True) or {}
    ok = next((e for e in _alexa_eligible() if e["kind"] == b.get("kind") and e["ref"] == str(b.get("ref"))), None)
    if not ok:
        return jsonify(error="Dieses Gerät kann nicht freigegeben werden (mit PIN, nicht schaltbar oder schon freigegeben)."), 400
    try:
        item = alexa.add(ok["kind"], ok["ref"], b.get("name") or ok["name"], b.get("type") or "light")
    except alexa.AlexaError as e:
        return jsonify(error=str(e)), 400
    return jsonify(item), 201


@app.route("/api/alexa/devices/order", methods=["POST"])
def api_alexa_order():
    return _order_route(alexa.reorder)


@app.route("/api/alexa/devices/<hid>", methods=["PATCH", "DELETE"])
def api_alexa_modify(hid):
    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        return (jsonify(ok=True), 200) if alexa.remove(hid) else (jsonify(error="nicht gefunden"), 404)
    b = request.get_json(silent=True) or {}
    try:
        found = alexa.update(hid, name=b.get("name") if isinstance(b.get("name"), str) else None, typ=b.get("type") if isinstance(b.get("type"), str) else None)
    except alexa.AlexaError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if found else (jsonify(error="nicht gefunden"), 404)


@app.route("/setup/modules", methods=["GET", "POST"])
def setup_modules():
    """Erster Schritt der Einrichtung: Welche Module nutzt diese Installation? (nur Administratoren; spaeter auch unter Einstellungen -> System)"""
    if request.method == "POST":
        sel = {k: bool(request.form.get(k)) for k in store.MODULES}
        if not (sel["energy"] or sel["smarthome"] or sel["cameras"]):
            return render_template("modules.html", mods=sel, error="Bitte mindestens ein Modul wählen."), 400
        cfg = store.load_config()
        cfg["modules"] = sel
        store.save_config(cfg)
        _alexa_sync()
        if sel["energy"] and not store.is_configured(cfg):
            return redirect("/setup")
        if sel["smarthome"] and not isinstance(cfg.get("device_families"), dict):      # Smart Home ohne Energie-Assistent: gleich dorthin, wo die Systeme gewaehlt werden
            return redirect("/smarthome#suchen")
        return redirect("/")
    return render_template("modules.html", mods=store.modules(), error=None)


@app.route("/api/modules", methods=["GET", "POST"])
def api_modules():
    """Module (Energie / Smart Home / Kameras) ansehen und umschalten. Aendert nur die Konfiguration - Daten bleiben erhalten."""
    if request.method == "GET":
        return jsonify(modules=store.modules(), chosen=store.modules_chosen())
    body = request.get_json(silent=True) or {}
    cur = store.modules()
    new = {k: bool(body.get(k, cur[k])) for k in store.MODULES}
    if not (new["energy"] or new["smarthome"] or new["cameras"]):
        return jsonify(error="Mindestens ein Modul (Energie, Smart Home oder Kameras) muss an bleiben."), 400
    cfg = store.load_config()
    cfg["modules"] = new
    store.save_config(cfg)
    if new["smarthome"] and not cur["smarthome"]:
        ctrl._rules_wake.set()
    _alexa_sync()
    return jsonify(ok=True, modules=store.modules(cfg))


@app.route("/setup")
def setup():
    return render_template("setup.html", cfg=store.load_config())


@app.route("/admin")
def admin():
    if not any(g.perms.get(x, "none") != "none" for x in SETTINGS_PAGE_AREAS):          # nichts einzustellen -> nicht auf einer leeren Seite landen
        return redirect(url_for("automation_page") if g.perms.get("automation", "none") != "none" else url_for("index"))
    return render_template("admin.html", cfg=store.load_config(), session_user_display=g.user_display, page_mode="admin")


@app.route("/smarthome")
def smarthome_page():
    """Smart Home: Geraete, Sensoren, Thermostate, Sicherheit, Suche, WOL - dieselbe Vorlage/Skripte wie /admin, nur andere Reiter."""
    return render_template("admin.html", cfg=store.load_config(), session_user_display=g.user_display, page_mode="smarthome")


@app.route("/solar-log")
def solar_log_page():
    return render_template("solar_log.html")


@app.route("/api/solar-log")
def api_solar_log():
    data = store.solar_log()
    try:                                          # vom VRM gemessener Tagesertrag zum Vergleich mit unserer Messung
        vm = vrm.daily_solar()
    except Exception as e:                        # noqa: BLE001
        log.warning("VRM-Tagesertrag nicht verfügbar: %s", e)
        vm = {}
    for row in data.get("rows", []):
        if row["date"] in vm:
            row["vrm_measured"] = vm[row["date"]]
    return jsonify(data)


@app.route("/watchdog")
def watchdog_page():
    return render_template("watchdog.html")


@app.route("/api/watchdog")
def api_watchdog():
    return jsonify(store.battery_watchdog_state())


@app.route("/api/alarms")
def api_alarms():
    """Diagnose: Alarmregister von Multiplus (VE.Bus) und Batterie (BMS) roh auslesen (siehe victron.ALARM_REGS).
    Noch nicht am echten Cerbo verifiziert - dient erstmal dazu, das gemeinsam mit Michael zu pruefen, bevor
    daraus eine feste Anzeige/Meldung wird."""
    cfg = store.load_config()
    if not store.is_configured(cfg):
        return jsonify(error="Cerbo ist noch nicht eingerichtet"), 400
    try:
        cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
        return jsonify(ok=True, **cerbo.read_alarms())
    except Exception as e:                                   # noqa: BLE001
        return jsonify(error=str(e)), 400


@app.route("/api/battery-cycles")
def api_battery_cycles():
    """Lebenslaufende Akku-Nutzung: Durchsatz und daraus die aequivalenten Vollzyklen (siehe store.battery_cycle_stats),
    plus live der Alterungszustand (SOH) direkt vom BMS, wie am Cerbo unter Batterie -> Alterungszustand."""
    data = store.battery_cycle_stats()
    cfg = store.load_config()
    if store.is_configured(cfg):
        try:
            data["soh_pct"] = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502)).read_soh()
        except Exception as e:                               # noqa: BLE001
            log.warning("Alterungszustand (SOH) nicht lesbar: %s", e)
            data["soh_pct"] = None
    return jsonify(data)


def _next15(iso):
    return (datetime.fromisoformat(iso) + timedelta(minutes=15)).isoformat(timespec="minutes")


def _window_stats(start_iso, end_iso, price_at, power_kw):
    """Kennzahlen für ein Ladefenster start–end: kWh, Kosten (€) und
    (dauer­gewichteter) Ø-Preis. Rechnet über die tatsächliche Überlappung mit
    den Viertelstunden-Preis-Slots – auch wenn start/end nicht aufs 15-Min-Raster
    fallen (z.B. echter Ladebeginn 00:47)."""
    s = datetime.fromisoformat(start_iso)
    e = datetime.fromisoformat(end_iso)
    kwh = cost = wsum = wdur = 0.0
    t = s
    while t < e:
        slot_start = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
        seg_end = min(e, slot_start + timedelta(minutes=15))
        dur_h = (seg_end - t).total_seconds() / 3600.0
        kwh_seg = dur_h * power_kw
        kwh += kwh_seg
        p = price_at.get(slot_start.strftime("%Y-%m-%dT%H:%M"))
        if p is not None:
            cost += p / 100.0 * kwh_seg
            wsum += p * dur_h
            wdur += dur_h
        t = seg_end
    return {"avg_price": round(wsum / wdur, 1) if wdur else None,
            "kwh": round(kwh, 2), "cost": round(cost, 2)}


def _window_stats_measured(start_iso, end_iso, price_at, gbatt_at):
    """Wie _window_stats, aber mit der TATSÄCHLICH gemessenen Netz→Batterie-Energie
    (aus dem Energie-Sampler) statt der geschätzten Ladeleistung. Für bereits
    geladene/laufende Fenster – so stimmt die Menge mit dem Flüsse-Chart überein."""
    s = datetime.fromisoformat(start_iso)
    e = datetime.fromisoformat(end_iso)
    kwh = cost = wsum = wdur = 0.0
    t = s
    while t < e:
        slot_start = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
        key = slot_start.strftime("%Y-%m-%dT%H:%M")
        seg_end = min(e, slot_start + timedelta(minutes=15))
        frac = (seg_end - t).total_seconds() / 900.0          # Anteil am 15-Min-Bucket
        kwh_seg = gbatt_at.get(key, 0.0) * frac
        kwh += kwh_seg
        dur_h = (seg_end - t).total_seconds() / 3600.0
        p = price_at.get(key)
        if p is not None:
            cost += p / 100.0 * kwh_seg
            wsum += p * dur_h
            wdur += dur_h
        t = seg_end
    return {"avg_price": round(wsum / wdur, 1) if wdur else None,
            "kwh": round(kwh, 2), "cost": round(cost, 2)}


def build_charge_overview(status, charge, prices):
    """Kombiniert geplante Ladefenster (aus dem Plan) mit tatsächlich geladenen
    (aus dem Protokoll) inkl. Menge und Kosten. Geladene/laufende Fenster nutzen die
    gemessene Netz→Batterie-Energie, geplante die geschätzte Ladeleistung."""
    power_kw = (status.get("charge_power_w") or 3500) / 1000.0
    price_at = {p["start"][:16]: p["ct"] for p in prices}
    now_iso = datetime.now().isoformat(timespec="minutes")
    gbatt_at = store.energy_grid_charge_buckets(now_iso[:10])
    items = []
    for s in charge.get("sessions", []):
        items.append({"start": s["start"], "end": s["end"], "status": "geladen",
                      "strategy": s.get("strategy", ""),
                      **_window_stats_measured(s["start"], s["end"], price_at, gbatt_at)})
    op = charge.get("open")
    if op:
        items.append({"start": op["start"], "end": None, "status": "läuft",
                      "strategy": op.get("strategy", ""),
                      **_window_stats_measured(op["start"], now_iso, price_at, gbatt_at)})
    # geplante (zukünftige) Fenster: zusammenhängende Plan-Slots mergen.
    # Nur HEUTE (die Karte zeigt nur den heutigen Tag) und bereits laufende
    # Slots (vom offenen Vorgang abgedeckt) ausblenden. Sonst würden morgige
    # Plan-Slots hier ohne Datum erscheinen und wie heute aussehen.
    today = now_iso[:10]
    ps = [x for x in status.get("plan_slots", [])
          if x["start"][:10] == today and not (op and x["start"] <= now_iso)]
    ps = sorted(ps, key=lambda x: x["start"])
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and _next15(ps[j]["start"]) == ps[j + 1]["start"]:
            j += 1
        start, end = ps[i]["start"], _next15(ps[j]["start"])
        items.append({"start": start, "end": end, "status": "geplant", "strategy": "",
                      **_window_stats(start, end, price_at, power_kw)})
        i = j + 1
    items.sort(key=lambda x: x["start"])
    return items


@app.route("/api/status")
def api_status():
    with ctrl.lock:
        status = dict(ctrl.status)
        prices = list(ctrl.prices)
    charge = store.list_charge_sessions()
    cfg = store.load_config()
    admin_tiles = getattr(g, "dashboard_tiles", None)  # Admin-Obergrenze (Einstellungen -> Weitere Benutzer)
    my_tiles = getattr(g, "my_tiles", None)            # eigene Wahl des Kontos selbst ("Meine Ansicht")
    ui = {"chart_energy_hourly": bool(cfg.get("chart_energy_hourly", False)),
          "chart_flow_hourly": bool(cfg.get("chart_flow_hourly", False)),
          # Alle Dashboard-Kacheln einzeln ein-/ausblendbar (Einstellungen ->
          # Kacheln), Default ueberall an - siehe TILE_IDS in index.html.
          # show_tibber_card wird bei festem Tarif zusaetzlich im Admin-UI
          # gesperrt (updateTariffFields), hier nur normal ausgelesen.
          "show_live_values": bool(cfg.get("show_live_values", True)),
          "show_energy_chart": bool(cfg.get("show_energy_chart", True)),
          "show_flow_chart": bool(cfg.get("show_flow_chart", True)),
          "show_week_overview": bool(cfg.get("show_week_overview", True)),
          "show_month_overview": bool(cfg.get("show_month_overview", True)),
          "show_tibber_card": bool(cfg.get("show_tibber_card", True)),
          "show_override_card": bool(cfg.get("show_override_card", True)),
          "show_price_plan": bool(cfg.get("show_price_plan", True)),
          "show_charge_log": bool(cfg.get("show_charge_log", True)),
          "show_ev_card": bool(cfg.get("show_ev_card", True)),
          "show_shelly_card": bool(cfg.get("show_shelly_card", True)),
          "show_sensors_card": bool(cfg.get("show_sensors_card", True)),
          "show_virtual_card": bool(cfg.get("show_virtual_card", True)),
          "show_weather_card": bool(cfg.get("show_weather_card", True)),
          "show_savings_card": bool(cfg.get("show_savings_card", True)),
          "show_verlauf_card": bool(cfg.get("show_verlauf_card", True)) and auth.has_level(g.perms, "verlauf", "read"),
          "show_plansim_card": bool(cfg.get("show_plansim_card", True)) and cfg.get("tariff_mode") != "fixed",
          "tile_order": [k for k in (cfg.get("tile_order") or []) if isinstance(k, str)]}
    for k in auth._off(store.modules(cfg), auth.MODULE_TILES):             # Module aus: deren Kacheln sind weg (Daten bleiben)
        ui[k] = False
    admin_order = getattr(g, "admin_order", None)      # vom Admin fuer dieses Konto vorgegeben
    my_order = _own_order_effective(getattr(g, "my_order", None), getattr(g, "my_order_explicit", False), admin_order, admin_tiles, cfg)   # eigene Reihenfolge ("Meine Ansicht"), nur wenn wirklich abweichend
    if my_order is not None:
        ui["tile_order"] = my_order                    # Vorrang: eigene Wahl > Vorgabe des Admins > globale Reihenfolge
    elif admin_order is not None:
        ui["tile_order"] = admin_order
    for restriction in (admin_tiles, my_tiles):
        if restriction is not None:
            for k in auth.DASHBOARD_TILE_KEYS:
                if k not in restriction:
                    ui[k] = False
    return jsonify({
        "status": status,
        "ui": ui,
        "prices": prices,
        "ev_schedules": store.list_ev(),
        "charge_log": charge,
        "charge_overview": build_charge_overview(status, charge, prices),
        "energy_history": store.energy_history_today(),
        "energy_min_day": store.energy_min_day(),
        "last_tick": ctrl.last_tick,
        "last_error": ctrl.last_error,
        "battery_watchdog": store.battery_watchdog_state(),
        "now": datetime.now().isoformat(timespec="seconds"),
    })


def _own_order_effective(my_order, explicit, admin_order, admin_tiles, cfg):
    """Die eigene Reihenfolge eines Kontos ("Meine Ansicht") zaehlt nur, wenn sie von der Grundlage abweicht (Vorgabe des Admins, sonst die
    globale). Aeltere Eintraege (ohne Markierung "explicit") entstanden oft durch Speichern OHNE Umsortieren und stehen dann in der Standard-
    bzw. globalen Reihenfolge - die duerfen eine spaeter gesetzte Vorgabe des Admins nicht verdraengen. Verglichen wird nur die Reihenfolge
    der Kacheln, die das Konto ueberhaupt sehen darf."""
    if my_order is None:
        return None
    glob = auth.complete_tile_order([k for k in (cfg.get("tile_order") or []) if isinstance(k, str)])
    allowed = set(admin_tiles) if admin_tiles is not None else set(auth.DASHBOARD_TILE_KEYS)
    flt = lambda lst: [k for k in lst if k in allowed]
    mine, base = flt(my_order), flt(auth.complete_tile_order(admin_order) if admin_order is not None else glob)
    if mine == base:
        return None
    if not explicit and mine in (flt(auth.DASHBOARD_TILE_KEYS), flt(glob)):
        return None
    return my_order


@app.route("/api/my-tiles", methods=["GET", "POST"])
def api_my_tiles():
    """"Meine Ansicht": jedes Konto darf selbst waehlen, welche Dashboard-Kacheln es zusaetzlich zur
    globalen Einstellung und einer moeglichen Admin-Obergrenze (siehe Weitere Benutzer) sehen will -
    rein persoenlich, wirkt sich auf niemand sonst aus."""
    if request.method == "GET":
        user = users.get(g.user) or {}
        return jsonify(tiles=auth.visible_tiles(store.modules()), my_tiles=getattr(g, "my_tiles", None),
                       my_order=_own_order_effective(getattr(g, "my_order", None), getattr(g, "my_order_explicit", False), auth.normalize_tile_order(user.get("dashboard_order")),
                                                     getattr(g, "dashboard_tiles", None), store.load_config()),
                       admin_order=auth.normalize_tile_order(user.get("dashboard_order")),
                       base_order=auth.complete_tile_order(auth.normalize_tile_order(user.get("dashboard_order")) or [k for k in (store.load_config().get("tile_order") or []) if isinstance(k, str)]),
                       admin_tiles=getattr(g, "dashboard_tiles", None))
    body = request.json or {}
    try:
        if "my_tiles" in body:
            users.set_my_tiles(g.user, body.get("my_tiles"))
        if "my_order" in body:
            users.set_my_order(g.user, body.get("my_order"))
    except UserError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True)


@app.route("/api/history")
def api_history():
    now = datetime.now()
    day = request.args.get("day") or now.strftime("%Y-%m-%d")
    return jsonify({
        "day": day,
        "history": store.energy_history_for_day(day, now),
        "min_day": store.energy_min_day(),
        "max_day": now.strftime("%Y-%m-%d"),
    })


@app.route("/api/week")
def api_week():
    """Wochenrueckblick: Solar/Verbrauch/Netz/Kosten einer 7-Tage-Woche.
    ?offset=0 aktuelle Woche (Default), 1 die davor, usw. - so bleibt
    Aelteres ueber die Pfeile erreichbar statt aus der Anzeige zu fallen."""
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    cfg = store.load_config()
    return jsonify({
        **store.energy_week_summary(offset_weeks=offset),
        "tariff_mode": cfg.get("tariff_mode", "tibber"),
        "has_contract_fees": bool(store.contract_fixed_cost_eur(cfg, 1)) or bool(float(cfg.get("vat_percent", 0) or 0)),
    })


@app.route("/api/month")
def api_month():
    """Monatsuebersicht: eine Zeile je Kalendermonat (Solar/Verbrauch/Netz/
    Autarkie/Kosten), aus dem dauerhaften Monats-Archiv (nicht auf die 35-Tage-
    Historie beschraenkt - siehe store.monthly_overview)."""
    cfg = store.load_config()
    return jsonify({
        **store.monthly_overview(),
        "tariff_mode": cfg.get("tariff_mode", "tibber"),
        "has_contract_fees": bool(store.contract_fixed_cost_eur(cfg, 1)) or bool(float(cfg.get("vat_percent", 0) or 0)),
    })


_live_cache = {"ts": 0.0, "data": None}
_live_lock = threading.Lock()


@app.route("/api/live")
def api_live():
    """Schnelle Live-Werte direkt vom Cerbo (SOC, ESS, System-Kacheln).
    Unabhängig vom 5-Min-Regelzyklus. Kurzer Cache (2 s) gegen Überlastung."""
    now = time.time()
    with _live_lock:
        if _live_cache["data"] and (now - _live_cache["ts"]) < 1:
            return jsonify(_live_cache["data"])
        cfg = store.load_config()
        if not store.is_configured(cfg):
            return jsonify({"ok": False, "reason": "nicht eingerichtet"})
        try:
            cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
            system = cerbo.read_system(has_pv_inverter=cfg.get("has_pv_inverter", True),
                                        has_mppt=cfg.get("has_mppt", True))
            pv_sources = []
            for src in cfg.get("pv_inverters") or []:
                try:
                    power = cerbo.read_pvinverter_power(int(src["unit"]))
                except Exception as e:                       # noqa: BLE001
                    power = None
                    log.warning("PV-Wechselrichter '%s' (Unit %s) nicht lesbar: %s",
                                src.get("name"), src.get("unit"), e)
                pv_sources.append({"name": src.get("name") or f"Unit {src.get('unit')}",
                                    "unit": src.get("unit"), "power": power})
            data = {"ok": True, "soc": round(cerbo.read_soc(), 1),
                    "ess_mode": cerbo.read_ess_mode(),
                    "system": system,
                    "pv_sources": pv_sources,
                    "has_pv_inverter": cfg.get("has_pv_inverter", True),
                    "has_mppt": cfg.get("has_mppt", True),
                    "battery_usable_kwh": cfg.get("battery_usable_kwh"),
                    "grid_today": store.energy_grid_today(),
                    "now": datetime.now().isoformat(timespec="seconds")}
        except Exception as e:                           # noqa: BLE001
            data = {"ok": False, "reason": str(e)}
        _live_cache["ts"] = now
        _live_cache["data"] = data
    return jsonify(data)


@app.route("/api/ess/min-soc", methods=["GET", "POST"])
def api_ess_min_soc():
    """'Minimaler SOC' der Anlage am Cerbo lesen/setzen (wie im VRM-Portal). Schreiben nur ausserhalb des Trockenlaufs."""
    cfg = store.load_config()
    if not store.is_configured(cfg):
        return jsonify(error="Cerbo ist noch nicht eingerichtet"), 400
    cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
    try:
        if request.method == "GET":
            return jsonify(ok=True, min_soc=cerbo.read_min_soc())
        try:
            pct = int(float((request.get_json(silent=True) or {}).get("min_soc")))
        except (TypeError, ValueError):
            return jsonify(error="Bitte eine ganze Zahl eintragen"), 400
        if not 0 <= pct <= 100:
            return jsonify(error="Minimaler Akkustand: zwischen 0 und 100 %"), 400
        if cfg.get("dry_run", True):
            return jsonify(error="Der Trockenlauf der Ladesteuerung ist an – dabei wird nichts am Cerbo geändert. Schalte ihn unter Einstellungen aus."), 400
        old = cerbo.read_min_soc()
        cerbo.write_min_soc(pct, dry_run=False)
        new = old
        for _ in range(10):                              # der Cerbo uebernimmt den Wert erst einen Moment spaeter
            time.sleep(0.5)
            new = cerbo.read_min_soc()
            if abs(new - pct) <= 0.6:
                break
        if abs(new - pct) > 0.6:
            return jsonify(error=f"Der Cerbo meldet noch {new:g} % statt {pct} % – bitte kurz warten und im VRM-Portal prüfen"), 400
        opslog.log("ess", f"Minimaler Akkustand (Cerbo) von {old:g} % auf {new:g} % gesetzt")
        return jsonify(ok=True, min_soc=new)
    except Exception as e:                               # noqa: BLE001
        log.warning("Minimaler SOC: %s", e)
        return jsonify(error=str(e)), 400


@app.route("/api/ess/grid-setpoint", methods=["GET", "POST"])
def api_ess_grid_setpoint():
    """ESS 'Sollwert Netz' (W) am Cerbo lesen/setzen - der Netzbezug, den der Multiplus zu halten versucht (negativ = leichte Einspeisung)."""
    cfg = store.load_config()
    if not store.is_configured(cfg):
        return jsonify(error="Cerbo ist noch nicht eingerichtet"), 400
    cerbo = Cerbo(cfg["cerbo_host"], cfg.get("cerbo_port", 502))
    try:
        if request.method == "GET":
            return jsonify(ok=True, watt=cerbo.read_grid_setpoint())
        try:
            watt = int(float((request.get_json(silent=True) or {}).get("watt")))
        except (TypeError, ValueError):
            return jsonify(error="Bitte eine ganze Zahl (Watt) eintragen"), 400
        if not -1000 <= watt <= 1000:
            return jsonify(error="Sollwert Netz: zwischen -1000 und 1000 W"), 400
        if watt % 10:
            return jsonify(error="Sollwert Netz: nur in 10-W-Schritten (wie am Cerbo), z. B. -10 oder -20"), 400
        if cfg.get("dry_run", True):
            return jsonify(error="Der Trockenlauf der Ladesteuerung ist an – dabei wird nichts am Cerbo geändert. Schalte ihn unter Einstellungen aus."), 400
        old = cerbo.read_grid_setpoint()
        cerbo.write_grid_setpoint(watt, dry_run=False)
        new = old
        for _ in range(10):                              # der Cerbo uebernimmt den Wert erst einen Moment spaeter
            time.sleep(0.5)
            new = cerbo.read_grid_setpoint()
            if new == watt:
                break
        if new != watt:
            return jsonify(error=f"Der Cerbo meldet noch {new} W statt {watt} W – bitte kurz warten und in der Remote-Konsole prüfen"), 400
        opslog.log("ess", f"Sollwert Netz (Cerbo) von {old} W auf {new} W gesetzt")
        return jsonify(ok=True, watt=new)
    except Exception as e:                               # noqa: BLE001
        log.warning("Sollwert Netz: %s", e)
        return jsonify(error=str(e)), 400


# Felder, deren echter Wert nur bei Schreibrecht auf ihren Bereich rausgeht - fuer
# Zugangs-Token (nie im Klartext an einen reinen Leser) und interne IP-Adressen (Michael:
# "man soll sehen dass da eine IP reinkommt, aber nicht meine internen IPs gelistet").
SECRET_FIELDS = {"tibber_token", "cerbo_host"}


def _masked(d: dict, area: str, fields) -> dict:
    """Ersetzt die genannten Felder in `d` durch "" + ein "<feld>_set"-Flag, wenn das
    angemeldete Konto auf `area` kein Schreibrecht hat - fuer Kennungen, die zwar keine
    Passwoerter sind (Access-ID, Chat-ID, Installations-ID, IP-Bereiche), aber trotzdem
    nicht vor jedem Nur-Lese-Konto (z.B. Demo) im Klartext stehen sollen."""
    if not auth.has_level(g.perms, area, "write"):
        for f in fields:
            if d.get(f):
                d[f + "_set"] = True
                d[f] = ""
    return d


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        cfg = store.load_config()
        # Steuerungs-Parameter mit Defaults auffüllen, damit die UI Werte zeigt
        defaults = Params().__dict__
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        cfg.setdefault("has_pv_inverter", True)
        cfg.setdefault("has_mppt", True)
        cfg.setdefault("tariff_mode", "tibber")
        cfg.setdefault("fixed_price_ct", 32.0)
        cfg.setdefault("pv_inverters", [])
        cfg["app_display_name"] = store.default_app_name(cfg)
        for f in SECRET_FIELDS:
            has_write = auth.has_level(g.perms, FIELD_AREA.get(f, "settings_anlage"), "write")
            cfg[f + "_set"] = bool(cfg.get(f))
            if not has_write:
                cfg[f] = ""
        return jsonify(cfg)
    body = request.get_json(silent=True) or {}
    try:
        valid_from = store.validate_valid_from(body.get("contract_valid_from"))        # optional: Tarifwechsel gilt ab (heute oder frueher)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    cfg = store.load_config()
    allowed = ["app_display_name", "cerbo_host", "cerbo_port", "tibber_token", "dry_run", "poll_seconds",
               "energy_sample_seconds", "manual_override", "web_port",
               "chart_energy_hourly", "chart_flow_hourly",
               "show_live_values", "show_energy_chart", "show_flow_chart",
               "show_week_overview", "show_month_overview", "show_tibber_card",
               "show_override_card", "show_price_plan", "show_charge_log",
               "show_ev_card", "show_shelly_card", "show_sensors_card", "show_virtual_card", "show_weather_card", "show_plansim_card", "show_savings_card", "show_verlauf_card", "pv_auto_calibration", "smart_planner_enabled", "surplus_enabled", "surplus_dry_run", "rules_enabled", "rules_dry_run", "rules_manual_hold_min", "rules_failsafe_min",
               "surplus_min_soc", "tile_order", "scan_networks",
               "has_pv_inverter", "has_mppt", "tariff_mode",
               "fixed_price_ct", "pv_inverters",
               "contract_fee_month_eur", "grid_fee_day_eur", "meter_fee_day_eur",
               "section14a_credit_day_eur", "vat_percent", "battery_install_date",
               "battery_expected_cycles"] + list(Params().__dict__.keys())
    allowed = allowed + ["surplus_" + k for k in surplus.DEFAULTS]     # einstellbare Automatik-Werte
    if "scan_networks" in body:
        try:
            body["scan_networks"] = ", ".join(tuya.parse_networks(body["scan_networks"]))
        except tuya.TuyaError as e:
            return jsonify(error=str(e)), 400
    if not (isinstance(body.get("tile_order", []), list)
            and all(isinstance(k, str) for k in body.get("tile_order", []))):
        body.pop("tile_order", None)          # Kachelreihenfolge: nur Liste von Textschluesseln
    denied = []
    for key in allowed:
        if key not in body:
            continue
        if body[key] != cfg.get(key) and not auth.has_level(g.perms, FIELD_AREA.get(key, "settings_anlage"), "write"):
            denied.append(key)         # dieses Feld darf dieses Konto nicht aendern - stillschweigend uebergehen,
            continue                   # sonst wuerde das gemeinsame "Speichern" ueber alle Reiter hinweg immer scheitern
        cfg[key] = body[key]
    store.save_config(cfg)
    try:                                    # neue Vertragskosten-Periode ab heute, falls sich etwas geaendert hat
        changed = store.record_contract_period_if_changed(cfg, day=valid_from)
        if changed and valid_from and valid_from < datetime.now().date().isoformat():
            threading.Thread(target=store.restate_fixed_costs, args=(valid_from,), daemon=True).start()       # rueckwirkender Wechsel: Kosten ab dem Datum neu rechnen
    except Exception as e:                  # noqa: BLE001
        log.warning("Vertragskosten-Periode nicht speicherbar: %s", e)
    if denied:
        log.info("api_config: %s hat keine Schreibrechte fuer %s - Feld(er) uebersprungen", g.user, ", ".join(denied))
    # Sofort einen Regel-Durchlauf anstoßen, damit Preise/Status gleich erscheinen
    # (der periodische Thread schläft sonst bis zu poll_seconds).
    threading.Thread(target=ctrl.safe_tick, daemon=True).start()
    return jsonify({"ok": True, "configured": store.is_configured(cfg)})


@app.route("/api/grid-adjust", methods=["POST"])
def api_grid_adjust():
    """Setzt die heutigen Netzwerte manuell (z.B. aus der Victron-App), falls
    sie z.B. wegen einer Pause der App nicht vollstaendig erfasst wurden."""
    body = request.get_json(silent=True) or {}
    try:
        imp_today = float(body.get("import", 0))
        exp_today = float(body.get("export", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Zahlen"}), 400
    result = store.set_grid_today(imp_today, exp_today)
    with _live_lock:                                     # Live-Cache invalidieren
        _live_cache["ts"] = 0
    return jsonify({"ok": True, "grid_today": result})


def _under_process_manager():
    """True, wenn ein Prozessmanager die App bei Beenden neu startet
    (systemd Restart=always ODER pm2 autorestart). Dann kann sich die App
    zum Update selbst beenden und wird automatisch neu gestartet."""
    return bool(os.environ.get("INVOCATION_ID")      # systemd
                or os.environ.get("pm_id")            # pm2
                or os.environ.get("PM2_HOME"))


@app.route("/api/version")
def api_version():
    return jsonify({"version": updater.current_version(),
                    "under_systemd": _under_process_manager()})


@app.route("/api/check-update")
def api_check_update():
    return jsonify(updater.check_update())


@app.route("/api/update", methods=["POST"])
def api_update():
    if sandbox.ACTIVE:
        return jsonify(error="Im Testmodus gesperrt."), 403
    result = updater.do_update()
    if result.get("ok"):
        # Unter systemd/pm2: sauber beenden -> Prozessmanager startet neu.
        if _under_process_manager():
            result["restarting"] = True

            def _restart():
                time.sleep(1.5)
                os._exit(0)
            threading.Thread(target=_restart, daemon=True).start()
        else:
            result["restarting"] = False   # manuell neu starten
    return jsonify(result)


@app.route("/api/override", methods=["POST"])
def api_override():
    body = request.get_json(silent=True) or {}
    cfg = store.load_config()
    cfg["manual_override"] = bool(body.get("value"))
    store.save_config(cfg)
    threading.Thread(target=ctrl.safe_tick, daemon=True).start()
    return jsonify({"manual_override": cfg["manual_override"]})


@app.route("/api/ev", methods=["POST"])
def api_ev_add():
    body = request.get_json(silent=True) or {}
    start, end = body.get("start"), body.get("end")
    if not start or not end:
        return jsonify({"error": "Start und Ende erforderlich"}), 400
    try:
        s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        return jsonify({"error": "Ungültiges Zeitformat"}), 400
    if e <= s:
        return jsonify({"error": "Ende muss nach Start liegen"}), 400
    entry = store.add_ev(s.isoformat(timespec="minutes"),
                         e.isoformat(timespec="minutes"), body.get("note", ""))
    threading.Thread(target=ctrl.safe_tick, daemon=True).start()
    return jsonify(entry), 201


@app.route("/api/ev/<eid>", methods=["DELETE", "PATCH"])
def api_ev_modify(eid):
    if request.method == "DELETE":
        # Nur noch nicht gestartete Termine dürfen gelöscht werden. Laufende
        # sind nur stoppbar (das Geladene bleibt in den Ladevorgängen erhalten).
        entry = next((i for i in store.list_ev() if i["id"] == eid), None)
        if not entry:
            return jsonify({"error": "nicht gefunden"}), 404
        try:
            started = datetime.fromisoformat(entry["start"]) <= datetime.now()
        except (ValueError, KeyError):
            started = False
        if started:
            return jsonify({"error": "bereits gestartet – nur stoppbar"}), 409
        store.delete_ev(eid)
        threading.Thread(target=ctrl.safe_tick, daemon=True).start()
        return jsonify({"ok": True})
    body = request.get_json(silent=True) or {}
    if body.get("action") == "stop":
        entry = store.stop_ev(eid)
        if not entry:
            return jsonify({"error": "nicht laufend"}), 400
        threading.Thread(target=ctrl.safe_tick, daemon=True).start()
        return jsonify(entry)
    entry = store.toggle_ev(eid, body.get("enabled", True))
    if not entry:
        return jsonify({"error": "nicht gefunden"}), 404
    return jsonify(entry)


def _scan_networks() -> list[str]:
    """Weitere Netze/VLANs fuer alle Geraetesuchen (Einstellung `scan_networks`; frueher am Tuya-Zugang gespeichert)."""
    cfg = store.load_config()
    text = cfg.get("scan_networks") or ", ".join(tuya.load_credentials().get("networks") or [])
    try:
        return tuya.parse_networks(text)
    except tuya.TuyaError:
        return []


# --- Sichtbarkeit einzelner Geraete/Schalter/Sensoren pro Benutzer (Feld "users", siehe visibility.py) ---
_VIS_KINDS = {"camera": camera.users_registry, "shelly": shelly.users_registry, "virtual": virtual.users_registry, "wol": wol.users_registry, "sensor": homematic.users_registry, "sound": homematic.sound_users_registry, "blind": homematic.blind_users_registry}


def _visible(item: dict) -> bool:
    return visibility.can_see(item, g.user, auth.is_full_admin(g.perms))


def _admin_only():
    """None = ok (Administrator). Sonst 403: Geraete benennen, aendern, entfernen, anlegen duerfen nur Administratoren; Bedienen darf jeder mit Dashboard-Recht."""
    if auth.is_full_admin(g.perms):
        return None
    return jsonify(error="Das darf nur ein Administrator: Geräte anlegen, umbenennen, ändern oder entfernen. Bedienen (schalten/drücken) geht trotzdem."), 403


def _vis_filter(items: list) -> list:
    """Nur die Eintraege, die dieses Konto sehen darf; die Benutzerlisten selbst sieht nur ein Administrator."""
    admin = auth.is_full_admin(g.perms)
    out = [x for x in items if visibility.can_see(x, g.user, admin)]
    if not admin:
        for x in out:
            x.pop("users", None)
    return out


def _vis_guard(kind: str, item_id: str):
    """None = ok. Sonst 404, wenn der Eintrag fuer dieses Konto unsichtbar ist (Existenz nicht verraten)."""
    load, _save = _VIS_KINDS[kind]()
    it = next((x for x in load() if x.get("id") == item_id), None)
    if it is not None and not _visible(it):
        return jsonify(error="nicht gefunden"), 404
    return None


def _vis_set(kind: str, item_id: str, body: dict):
    """'users' aus einem PATCH uebernehmen (nur Administratoren). None = ok/nichts zu tun, sonst Fehlerantwort."""
    if "users" not in body:
        return None
    if not auth.is_full_admin(g.perms):
        return jsonify(error="Nur ein Administrator kann festlegen, wer ein Gerät sehen darf."), 403
    load, save = _VIS_KINDS[kind]()
    items = load()
    try:
        found = visibility.apply(items, item_id, body.get("users"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if not found:
        return jsonify(error="nicht gefunden"), 404
    save(items)
    return None


def _vis_users_changed(old, new):
    """Benutzer umbenannt (new gesetzt) oder geloescht (new None): Eintraege in allen Registern nachziehen."""
    for fn in _VIS_KINDS.values():
        load, save = fn()
        items = load()
        if (visibility.rename_user(items, old, new) if new else visibility.drop_user(items, old)):
            save(items)


@app.route("/api/shelly", methods=["GET"])
def api_shelly_list():
    """?dashboard=1: nur die in den Einstellungen fuers Dashboard freigegebenen."""
    if not store.module_on("smarthome"):
        return jsonify([])                                   # Modul Smart Home aus (Geraete bleiben gespeichert)
    devs = _vis_filter(shelly.list_with_status(only_shown=request.args.get("dashboard") == "1", live=request.args.get("light") != "1"))      # ?light=1: ohne Live-Abfrage (schnell)
    ruled = {i for r in rules.list_rules() if r.get("enabled", True) for i in rules.devices_of(r)} if rules.enabled(store.load_config()) else set()
    show_ip = auth.has_level(g.perms, "settings_geraete", "write")
    for d in devs:
        d["automated"] = bool(d.get("auto")) or d["id"] in ruled      # "Auto"-Hinweis im Dashboard: Ueberschuss-Automatik oder aktive Regel
        if not show_ip and d.get("ip"):
            d["ip_hidden"] = True
            d["ip"] = "•.•.•.•"                    # interne IP nicht ohne Schreibrecht auf Geraete-Verwaltung zeigen
    return jsonify(devs)


@app.route("/api/shelly/auto", methods=["GET"])
def api_shelly_auto():
    """Ueberschuss-Automatik (eigener Baustein)."""
    cfg = store.load_config()
    return jsonify({"enabled": bool(cfg.get("surplus_enabled")),
                    "dry_run": bool(cfg.get("surplus_dry_run", True)),
                    "min_soc": cfg.get("surplus_min_soc", surplus.DEFAULT_MIN_SOC),
                    "settings": surplus.settings(cfg), "defaults": surplus.DEFAULTS,
                    "bounds": surplus.BOUNDS,
                    "events": autolog.recent("surplus", 8)})


def _sun_info(cfg: dict) -> dict:
    """Heutige Zeiten fuer Sonnenaufgang/-untergang (Anzeige im Regel-Editor); ohne Standort configured=False."""
    t = sun.for_config(cfg, datetime.now().date())
    return {"configured": t is not None, "sunrise": sun.hhmm(t["sunrise"]) if t else None, "sunset": sun.hhmm(t["sunset"]) if t else None}


@app.route("/api/rules", methods=["GET"])
def api_rules_get():
    """Regeln (eigener Baustein): Regeln, Status, Einstellungen, letzte Aktionen."""
    cfg = store.load_config()
    rl = [n for r in rules.list_rules() for n in rules.to_new(r)]
    if not auth.has_level(g.perms, "rules", "write"):                        # Lese-Konten sehen die Adressen von Web-Aufrufen nicht (koennen Zugangsschluessel enthalten)
        rl = copy.deepcopy(rl)
        for r in rl:
            for br in ("then", "else"):
                for stp in r.get(br) or []:
                    if isinstance(stp, dict) and stp.get("type") == "http":
                        stp["url"], stp["url_hidden"] = "", True
    return jsonify({"enabled": rules.enabled(cfg), "dry_run": rules.dry_run(cfg),
                    "settings": rules.settings(cfg), "defaults": rules.DEFAULTS, "bounds": rules.BOUNDS,
                    "tariff_mode": cfg.get("tariff_mode", "tibber"),
                    "groups": rules.load().get("groups", []), "rules": rl, "status": {**rules.rollup_status(dict(rule_engine.status)), **dict(flow_engine.status)}, "owner": dict(rule_engine.owner),
                    "sun": _sun_info(cfg), "events": autolog.recent("rules", 8)})


@app.route("/api/automation/log", methods=["GET"])
def api_automation_log():
    """Logbuch: ?module=surplus|rules&days=N&limit=N (neueste zuerst)."""
    module = request.args.get("module", "")
    if module not in autolog.MODULES:
        return jsonify(error="module: surplus oder rules"), 400
    try:
        days = int(request.args["days"]) if request.args.get("days") else None
        limit = max(1, min(1000, int(request.args.get("limit", 300))))
    except ValueError:
        return jsonify(error="Zahl erwartet"), 400
    return jsonify({"module": module, "entries": autolog.recent(module, limit, days)})


@app.route("/api/automation/unread", methods=["GET"])
def api_automation_unread():
    """Ungelesene Logbuch-Eintraege je Baustein (fuer die roten Punkte)."""
    return jsonify({m: autolog.unread(m) for m in autolog.MODULES})


@app.route("/api/automation/log/read", methods=["POST"])
def api_automation_log_read():
    module = (request.get_json(silent=True) or {}).get("module", "")
    if module not in autolog.MODULES:
        return jsonify(error="module: surplus oder rules"), 400
    autolog.mark_read(module)
    return jsonify(ok=True)


@app.route("/api/automation/log/clear", methods=["POST"])
def api_automation_log_clear():
    """Logbuch eines Bausteins leeren (Knopf auf der Logbuch-Seite)."""
    module = (request.get_json(silent=True) or {}).get("module", "")
    if module not in autolog.MODULES:
        return jsonify(error="module: surplus oder rules"), 400
    return jsonify(ok=True, deleted=autolog.clear(module))


@app.route("/automation-log")
def automation_log_page():
    """Logbuch der Ueberschuss-Automatik (eigene Seite)."""
    return render_template("automation_log.html", module="surplus", log_title="Logbuch – Überschuss-Automatik",
                           log_hint="Jede Schalt-Aktion der Überschuss-Automatik.", back_url="/automation", back_label="zur Überschuss-Automatik")


@app.route("/rules-log")
def rules_log_page():
    """Logbuch der Regeln (eigene Seite)."""
    return render_template("automation_log.html", module="rules", log_title="Logbuch – Regeln",
                           log_hint="Jede Schalt-Aktion der Regeln.", back_url="/rules", back_label="zu den Regeln")


@app.route("/api/automation", methods=["POST"])
def api_automation_save():
    """Speichern der Automatik-Seite: Regeln, Ueberschuss-Geraete und die Einstellungen BEIDER Bausteine auf einmal.
    Erst wird ALLES geprueft, dann geschrieben. Ein Geraet darf nur zu einem Baustein gehoeren."""
    body = request.get_json(silent=True) or {}
    try:
        items = body.get("rules")
        if items is not None:
            if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
                raise rules.RuleError("Regeln: Liste erwartet")
            norm_items = [rules.normalize_rule(x) for x in items]         # nur pruefen
            if body.get("groups") is not None:
                rules.normalize_groups(body["groups"], {g["id"] for g in rules.load().get("groups", [])})
            if any(not str(x.get("name") or "").strip() for x in items):
                raise rules.RuleError("Jede Regel braucht einen Namen")
            locks = {k["id"]: k for k in homematic.load_locks()}
            cam_ids = {c["id"] for c in camera.load()}
            sound_ids = {s_["id"] for s_ in homematic.load_sounds()}
            blind_ids = {b_["id"] for b_ in homematic.load_blinds()}
            wled_ids = {w_["id"] for w_ in shelly.load_devices() if w_.get("kind") == "wled"}
            ac_ids = {w_["id"] for w_ in shelly.load_devices() if w_.get("kind") == "midea"}
            for x in norm_items:
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "ac" and a["id"] not in ac_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Die Klimaanlage existiert nicht (mehr)")
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "wled" and a["id"] not in wled_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Das WLED-Gerät existiert nicht (mehr)")
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "blind" and a["id"] not in blind_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Der Rollladen existiert nicht (mehr)")
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "sound" and a["id"] not in sound_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Das Soundmodul existiert nicht (mehr)")
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "pushover" and a.get("camera") and a["camera"] not in cam_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Die Kamera für das Pushover-Bild existiert nicht (mehr)")
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "video" and a["id"] in cam_ids and next((c for c in camera.load() if c["id"] == a["id"]), {}).get("kind", "reolink") != "reolink":
                        raise rules.RuleError(f"Regel „{x['name']}“: Video zum Ereignis gibt es nur für Reolink-Kameras")
                    if a.get("type") in ("photo", "video") and a["id"] not in cam_ids:
                        raise rules.RuleError(f"Regel „{x['name']}“: Die Kamera für das Standbild existiert nicht (mehr)")                                         # Entriegeln/Oeffnen nur bei Schloessern mit ausdruecklicher Freigabe
                for a in x.get("then", []) + x.get("else", []):
                    if a.get("type") == "lock":
                        lk = locks.get(a["id"])
                        if not lk:
                            raise rules.RuleError(f"Regel „{x['name']}“: Das Türschloss existiert nicht (mehr)")
                        if a["state"] != "lock" and not lk.get("allow_open"):
                            raise rules.RuleError(f"Regel „{x['name']}“: {lk['name']} ist nicht zum Entriegeln/Öffnen durch Regeln freigegeben (Smart Home → Sicherheit)")
        dev_updates = []
        for x in body.get("devices") or []:
            if not isinstance(x, dict) or not x.get("id"):
                raise rules.RuleError("Geräteangabe ungültig")
            fields = {}
            for k, hi, what in (("power_w", 20000, "Leistung (W)"), ("min_on_min", 1440, "Mindest-Einschaltdauer"), ("min_off_min", 1440, "Mindest-Ausschaltdauer")):
                if x.get(k) not in (None, ""):
                    try:
                        v = float(str(x[k]).replace(",", "."))
                    except ValueError:
                        raise rules.RuleError(f"{what}: Zahl erwartet")
                    if not 0 <= v <= hi:
                        raise rules.RuleError(f"{what}: zwischen 0 und {hi}")
                    fields[k] = v
            dev_updates.append((str(x["id"]), bool(x.get("auto")), fields))
        order = body.get("auto_order")
        if order is not None and not (isinstance(order, list) and all(isinstance(i, str) for i in order)):
            raise rules.RuleError("Reihenfolge ungültig")
        # Ein Geraet gehoert entweder zur Ueberschuss-Automatik ODER zu Regeln
        auto_ids = {d for d, auto, _ in dev_updates if auto} if body.get("devices") is not None else {d["id"] for d in shelly.load_devices() if d.get("auto")}
        rule_devs = {i for x in norm_items for i in rules.devices_of(x)} if items is not None else {i for r in rules.list_rules() for i in rules.devices_of(r)}
        both = auto_ids & rule_devs
        if both:
            names = {d["id"]: d["name"] for d in shelly.load_devices()}
            raise rules.RuleError("Diese Geräte sind gleichzeitig in der Überschuss-Automatik und in einer Regel – bitte nur eins von beiden: "
                                  + ", ".join(names.get(i, i) for i in sorted(both)))
        cfg_in = body.get("config") or {}
        upd = {}
        for k in ("surplus_enabled", "surplus_dry_run", "rules_enabled", "rules_dry_run"):
            if k in cfg_in:
                upd[k] = bool(cfg_in[k])
        if "surplus_min_soc" in cfg_in:
            try:
                v = int(float(cfg_in["surplus_min_soc"]))
            except (TypeError, ValueError):
                raise rules.RuleError("Akku mindestens: Zahl erwartet")
            if not 50 <= v <= 100:
                raise rules.RuleError("Akku mindestens: zwischen 50 und 100 %")
            upd["surplus_min_soc"] = v
        for prefix, defaults, bounds in (("surplus_", surplus.DEFAULTS, surplus.BOUNDS), ("rules_", rules.DEFAULTS, rules.BOUNDS)):
            for k in defaults:
                if prefix + k in cfg_in:
                    try:
                        v = float(cfg_in[prefix + k])
                    except (TypeError, ValueError):
                        raise rules.RuleError(f"{prefix}{k}: Zahl erwartet")
                    lo, hi = bounds[k]
                    if not lo <= v <= hi:
                        raise rules.RuleError(f"{k}: zwischen {lo} und {hi}")
                    upd[prefix + k] = v
    except rules.RuleError as e:
        return jsonify(error=str(e)), 400
    try:
        if items is not None:
            rules.replace_all(items, body.get("groups"))
            ctrl._rules_wake.set()                                       # neue/geaenderte Regeln gleich auswerten (Ausgangszustand erfassen)
        for dev_id, auto, fields in dev_updates:
            shelly.update(dev_id, auto=auto, **fields)
        if order is not None:
            shelly.reorder_auto(order)
    except (shelly.ShellyError, rules.RuleError) as e:
        return jsonify(error=str(e)), 400
    if upd:
        cfg = store.load_config()
        cfg.update(upd)
        store.save_config(cfg)
    return jsonify(ok=True)


@app.route("/api/rules", methods=["POST"])
def api_rules_add():
    try:
        return jsonify(rules.add_rule(request.get_json(silent=True) or {})), 201
    except rules.RuleError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/rules/<rule_id>", methods=["PATCH", "DELETE"])
def api_rules_modify(rule_id):
    if request.method == "DELETE":
        return (jsonify(ok=True), 200) if rules.delete_rule(rule_id) else (jsonify(error="Regel nicht gefunden."), 404)
    try:
        r = rules.update_rule(rule_id, request.get_json(silent=True) or {})
    except rules.RuleError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(r), 200) if r else (jsonify(error="Regel nicht gefunden."), 404)


@app.route("/api/shelly/auto-order", methods=["POST"])
def api_shelly_auto_order():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    shelly.reorder_auto(ids)
    return jsonify(ok=True)


@app.route("/api/notify", methods=["GET"])
def api_notify_info():
    d = {**notify.credentials_public(), **notify.settings_public(store.load_config())}
    recs = notify.recipients()
    can_see = auth.has_level(g.perms, "settings_meldungen", "write")
    d["recipients"] = [{"id": r["id"], "name": r["name"], "system": r["system"], **({"chat_id": r["chat_id"]} if can_see else {})} for r in recs]
    return jsonify(_masked(d, "settings_meldungen", ["chat_id"]))


# ---- Pushover (zweiter Meldeweg): Zugang, Empfaenger, Test ----
@app.route("/api/pushover", methods=["GET"])
def api_pushover_info():
    can_see = auth.has_level(g.perms, "settings_meldungen", "write")
    recs = [{"id": r["id"], "name": r["name"], "system": r["system"], "device": r["device"], **({"user_key": r["user_key"][:4] + "…" + r["user_key"][-3:]} if can_see else {})}
            for r in pushover.recipients()]
    return jsonify({**pushover.credentials_public(), "recipients": recs, "priorities": {str(k): v for k, v in pushover.PRIORITIES.items()}, "sounds": pushover.SOUNDS})


@app.route("/api/pushover/recipients", methods=["GET"])
def api_pushover_recipients():
    """Empfaenger (nur Namen, keine Schluessel) fuer den Regel-Editor."""
    return jsonify(pushover.recipients_light())


@app.route("/api/pushover/credentials", methods=["POST", "DELETE"])
def api_pushover_credentials():
    if request.method == "DELETE":                          # App-Token und alle Empfaenger loeschen
        pushover.clear_credentials()
        return jsonify(ok=True)
    try:
        pushover.save_token((request.get_json(silent=True) or {}).get("token"))
    except pushover.PushoverError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/pushover/recipient", methods=["POST"])
def api_pushover_recipient_add():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(pushover.add_recipient(b.get("name"), b.get("user_key"), bool(b.get("system")), device=b.get("device") or "")), 201
    except pushover.PushoverError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/pushover/recipient/<rid>", methods=["PATCH", "DELETE"])
def api_pushover_recipient_modify(rid):
    try:
        if request.method == "DELETE":
            ok = pushover.remove_recipient(rid)
        else:
            b = request.get_json(silent=True) or {}
            ok = pushover.update_recipient(rid, name=b.get("name") if isinstance(b.get("name"), str) else None,
                                           system=b.get("system") if isinstance(b.get("system"), bool) else None)
    except pushover.PushoverError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Empfänger nicht gefunden"), 404)


@app.route("/api/pushover/test", methods=["POST"])
def api_pushover_test():
    rid = (request.get_json(silent=True) or {}).get("id")
    try:
        pushover.send(f"{notify._prefix(store.load_config())}✅ Testnachricht – Pushover funktioniert.", only=rid)
    except pushover.PushoverError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


# ---- Fernzugriff: Cloudflare Tunnel (tunnel.py) ----
@app.route("/api/tunnel", methods=["GET"])
def api_tunnel_info():
    return jsonify(tunnel.status())


@app.route("/api/tunnel/log", methods=["GET"])
def api_tunnel_log():
    return jsonify(lines=tunnel.log_lines())


@app.route("/api/tunnel/token", methods=["POST", "DELETE"])
def api_tunnel_token():
    if request.method == "DELETE":                          # Tunnel stoppen und Token loeschen
        tunnel.clear_credentials()
        return jsonify(ok=True)
    try:
        tunnel.save_token((request.get_json(silent=True) or {}).get("token"))
    except tunnel.TunnelError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/tunnel/enable", methods=["POST"])
def api_tunnel_enable():
    try:
        tunnel.set_enabled(bool((request.get_json(silent=True) or {}).get("enabled")))
    except tunnel.TunnelError as e:
        return jsonify(error=str(e)), 400
    return jsonify(tunnel.status())


@app.route("/api/tunnel/install", methods=["POST"])
def api_tunnel_install():
    try:
        v = tunnel.install()
    except tunnel.TunnelError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, version=v)


@app.route("/api/tibber/token", methods=["DELETE"])
def api_tibber_token_delete():
    """Tibber-Token loeschen (die App holt dann keine Preise mehr, bis wieder einer eingetragen ist)."""
    cfg = store.load_config()
    cfg.pop("tibber_token", None)
    store.save_config(cfg)
    return jsonify(ok=True)


@app.route("/api/notify/recipients", methods=["GET"])
def api_notify_recipients():
    """Empfaenger (nur Namen, keine Chat-IDs) fuer den Regel-Editor: wer soll eine Nachricht bzw. ein Foto bekommen."""
    return jsonify(notify.recipients_light())


@app.route("/api/notify/recipient", methods=["POST"])
def api_notify_recipient_add():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(notify.add_recipient(b.get("name"), b.get("chat_id"), bool(b.get("system")))), 201
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/notify/recipient/<rid>", methods=["PATCH", "DELETE"])
def api_notify_recipient_modify(rid):
    try:
        if request.method == "DELETE":
            ok = notify.remove_recipient(rid)
        else:
            b = request.get_json(silent=True) or {}
            ok = notify.update_recipient(rid, name=b.get("name") if isinstance(b.get("name"), str) else None,
                                         system=b.get("system") if isinstance(b.get("system"), bool) else None)
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Empfänger nicht gefunden"), 404)


@app.route("/api/notify/credentials", methods=["POST", "DELETE"])
def api_notify_credentials():
    if request.method == "DELETE":                          # Telegram-Zugang loeschen (Token, Chat-ID, Empfaenger)
        notify.clear_credentials()
        return jsonify(ok=True)
    body = request.get_json(silent=True) or {}
    try:
        notify.save_credentials(body.get("token"), body.get("chat_id"))
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/notify/detect", methods=["POST"])
def api_notify_detect():
    """Chat-ID ermitteln: erst dem Bot in Telegram eine Nachricht schreiben, dann hier abfragen."""
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(notify.detect_chats(body.get("token")))
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/notify/settings", methods=["POST"])
def api_notify_settings():
    body = request.get_json(silent=True) or {}
    try:
        upd = notify.validate_settings(body)
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400
    cfg = store.load_config()
    if "notify_events" in upd:                               # Schalter zusammenfuehren, nicht ersetzen
        merged = dict(cfg.get("notify_events") or {})
        merged.update(upd.pop("notify_events"))
        upd["notify_events"] = merged
    cfg.update(upd)
    store.save_config(cfg)
    return jsonify(ok=True)


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    cfg = store.load_config()
    rid = (request.get_json(silent=True) or {}).get("id")
    try:
        notify.send(f"{notify._prefix(cfg)}✅ Testnachricht – die Benachrichtigungen funktionieren.", to=[rid] if rid else None)
    except notify.NotifyError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/plan-sim", methods=["GET"])
def api_plan_sim():
    """Ladeplan-Simulation (nur Anzeige): letzter Lauf + Tages-Vergleich der letzten Tage."""
    with ctrl.lock:
        data = dict(ctrl.plansim)
    data["history"] = store.plansim_log()
    return jsonify(data)


@app.route("/api/prices/history", methods=["GET"])
def api_price_history():
    """Gespeicherte Tibber-Preise je Viertelstunde. Mit ?day=YYYY-MM-DD nur dieser eine Tag (Tage-zurueck-Blick
    im Strompreis-Diagramm, siehe index.html priceDay), sonst ?days=N (Standard 90) als Sammelabfrage + Kurzinfo."""
    day = request.args.get("day", "")
    if day:
        return jsonify({"day": day, "record": store.price_day(day)})
    try:
        n = max(1, min(800, int(request.args.get("days", 90))))
    except ValueError:
        n = 90
    return jsonify({"info": store.price_history_info(), "days": store.price_history(n)})


def _ctrl_info():
    with ctrl.lock:
        st = dict(ctrl.status)
    return {"status": st, "last_tick": ctrl.last_tick, "last_system_ts": ctrl.last_system_ts, "started": ctrl.started_at,
            "plansim": getattr(ctrl, "plansim", None)}


@app.route("/automation")
def automation_page():
    return render_template("automation.html")


@app.route("/rules")
def rules_page():
    return render_template("rules.html", families=_families())


@app.route("/report")
def report_page():
    return render_template("report.html")


@app.route("/api/report", methods=["GET"])
def api_report():
    """Betriebsbericht ("schlauer Zettel"). ?format=md liefert den kompakten Text zum Kopieren, sonst JSON."""
    try:
        days = max(1, min(30, int(request.args.get("days", 7))))
    except ValueError:
        days = 7
    rep_ = report.build(days=days, ctrl=_ctrl_info())
    if request.args.get("format") == "md":
        return app.response_class(report.to_markdown(rep_), mimetype="text/plain; charset=utf-8")
    return jsonify(rep_)


@app.route("/api/savings", methods=["GET"])
def api_savings():
    """Ersparnis gegenueber "alles aus dem Netz": heute, 7/30 Tage, gesamt + Tagesliste."""
    return jsonify(store.savings(store.load_config()))


@app.route("/api/pv-calibration", methods=["GET"])
def api_pv_calibration():
    """Gelernter Korrekturfaktor der VRM-Prognose (aus dem Solarlogbuch) und ob er angewendet wird."""
    return jsonify({**store.pv_calibration(), "enabled": bool(store.load_config().get("pv_auto_calibration"))})


@app.route("/api/weather", methods=["GET"])
def api_weather():
    """Wettervorhersage fuer den Standort (nur Anzeige). ?refresh=1 umgeht den Zwischenspeicher."""
    return jsonify(weather.forecast(force=request.args.get("refresh") == "1"))


@app.route("/api/weather/location", methods=["GET", "POST"])
def api_weather_location():
    if request.method == "GET":
        return jsonify(weather.get_location())
    body = request.get_json(silent=True) or {}
    try:
        weather.save_location(body.get("lat"), body.get("lon"), body.get("name", ""))
    except weather.WeatherError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/weather/search", methods=["GET"])
def api_weather_search():
    try:
        return jsonify(weather.search_places(request.args.get("q", "")))
    except weather.WeatherError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/vrm", methods=["GET"])
def api_vrm_info():
    return jsonify(_masked(vrm.credentials_public(), "settings_vrm", ["installation_id"]))    # ohne Token


@app.route("/api/vrm/credentials", methods=["POST", "DELETE"])
def api_vrm_credentials():
    if request.method == "DELETE":
        vrm.clear_credentials()
        return jsonify(ok=True)
    body = request.get_json(silent=True) or {}
    try:
        vrm.save_credentials(body.get("installation_id"), body.get("token"))
    except vrm.VrmError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/vrm/restore", methods=["POST"])
def api_vrm_restore():
    """Fehlende Verlaufsdaten aus dem VRM nachholen. Ohne {"apply": true} nur Vorschau."""
    body = request.get_json(silent=True) or {}
    days = body.get("days")
    try:
        days = int(days) if days else None
    except (TypeError, ValueError):
        days = None
    try:
        return jsonify(vrm_import.run(apply=bool(body.get("apply")), days=days))
    except vrm.VrmError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("VRM-Import fehlgeschlagen: %s", e)
        return jsonify(error=f"Import fehlgeschlagen: {e}"), 500


@app.route("/api/vrm/forecast/history", methods=["GET"])
def api_vrm_forecast_history():
    """Gemerkte VRM-Stundenprognose eines vergangenen Tages (?day=YYYY-MM-DD) fuer die schraffierten Balken im Energieverlauf."""
    day = request.args.get("day", "")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return jsonify(error="Ungültiger Tag."), 400
    return jsonify(store.forecast_hours_for_day(day))


@app.route("/api/vrm/forecast", methods=["GET"])
def api_vrm_forecast():
    """Solar-Prognose aus dem VRM-Portal (?refresh=1 = Zwischenspeicher umgehen, z. B. beim Testen)."""
    return jsonify(vrm.forecast(force=request.args.get("refresh") == "1"))


@app.route("/api/tuya", methods=["GET"])
def api_tuya_info():
    return jsonify(_masked(tuya.credentials_public(), "smarthome_einrichten", ["api_key", "networks"]))   # ohne Secret


@app.route("/api/tuya/credentials", methods=["POST", "DELETE"])
def api_tuya_credentials():
    if request.method == "DELETE":
        tuya.clear_credentials()
        return jsonify(ok=True)
    body = request.get_json(silent=True) or {}
    try:
        tuya.save_credentials(body.get("region"), body.get("api_key"), body.get("api_secret"),
                              body.get("networks"))
    except tuya.TuyaError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/tuya/scan", methods=["POST"])
def api_tuya_scan():
    """Tuya-Geraete: Schluessel aus der Cloud + Suche im LAN (dauert ca. 20-30 s)."""
    try:
        return jsonify(shelly.tuya_scan(_scan_networks()))
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Tuya-Suche fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


def _in_use(kind: str, rid: str):
    """Loeschen verhindern, solange eine eingeschaltete Regel das Ding verwendet (409 mit den Regelnamen), sonst None."""
    names = rules.used_by(kind, rid)
    if not names:
        return None
    many = len(names) > 1
    return jsonify(error=f"Wird in {'den Regeln' if many else 'der Regel'} " + ", ".join(f"„{n}“" for n in names)
                         + f" verwendet – erst {'diese Regeln' if many else 'diese Regel'} löschen oder ausschalten.", rules=names), 409


@app.route("/api/rule-usage", methods=["GET"])
def api_rule_usage():
    """Welche eingeschalteten Regeln verwenden dieses Ding? (?kind=device|sensor|virtual|wol|lock|setpoint|sound|camera|blind&id=...)"""
    denied = _admin_only()
    if denied:
        return denied
    return jsonify(rules=rules.used_by(request.args.get("kind", ""), request.args.get("id", "")))


def _edits() -> dict:
    """Name/Symbol, die in der Trefferliste vor dem Hinzufuegen eingegeben wurden: {schluessel: {name, icon}}."""
    e = (request.get_json(silent=True) or {}).get("edits")
    return e if isinstance(e, dict) else {}


def _edit_err(edits: dict, kind: str):
    """Fehler-Antwort bei ungueltigem Symbol (vor dem Anlegen pruefen, damit nichts halb angelegt wird), sonst None."""
    for ed in edits.values():
        ic = ed.get("icon") if isinstance(ed, dict) else None
        if ic is None:
            continue
        if kind in ("device", "sound", "blind") and ic not in shelly.ICONS:
            return jsonify(error="Unbekanntes Symbol"), 400
        if kind == "sensor" and not (isinstance(ic, str) and 0 < len(ic.strip()) <= 12):
            return jsonify(error="Unbekanntes Symbol"), 400
    return None


def _apply_edits(added: list, edits: dict, kind: str):
    """Eingegebenen Namen/Symbol auf die gerade angelegten Eintraege anwenden (Schluessel: id, CCU-Adresse oder Tuya-Geraete-ID)."""
    for e in added or []:
        ed = next((edits[k] for k in (e.get("id"), e.get("address"), e.get("dev_id")) if k in edits), None)
        if not isinstance(ed, dict):
            continue
        name = ed.get("name") if isinstance(ed.get("name"), str) else None
        icon = ed.get("icon") if isinstance(ed.get("icon"), str) else None
        if kind == "device":
            shelly.update(e["id"], name=name, icon=icon)
        elif kind == "sensor":
            homematic.update_sensor(e["id"], name=name, icon=icon)
        elif kind == "setpoint":
            homematic.update_setpoint(e["id"], name=name)
        elif kind == "lock":
            homematic.update_lock(e["id"], name=name)
        elif kind == "sound":
            homematic.update_sound(e["id"], name=name, icon=icon)
        elif kind == "blind":
            homematic.update_blind(e["id"], name=name, icon=icon)


@app.route("/api/tuya/add", methods=["POST"])
def api_tuya_add():
    dev_id = str((request.get_json(silent=True) or {}).get("dev_id") or "")
    bad = _edit_err(_edits(), "device")
    if bad:
        return bad
    try:
        entry = shelly.add_tuya(dev_id, str((request.get_json(silent=True) or {}).get("ip") or ""))
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    _apply_edits([entry], _edits(), "device")
    return jsonify({"added": entry["id"]}), 201


@app.route("/api/homematic", methods=["GET"])
def api_homematic_info():
    return jsonify(_masked(homematic.credentials_public(), "smarthome_einrichten", ["host", "user"]))     # ohne Passwort


@app.route("/api/homematic/credentials", methods=["POST", "DELETE"])
def api_homematic_credentials():
    """CCU-Zugang speichern und gleich testen (Anmeldung + Geraete zaehlen) bzw. loeschen (DELETE: Push abmelden, Zugang vergessen)."""
    if request.method == "DELETE":
        homematic.clear_credentials()
        return jsonify(ok=True)
    body = request.get_json(silent=True) or {}
    try:
        homematic.save_credentials(body.get("host"), body.get("user"), body.get("password") or "")
        info = homematic.test_connection()
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Homematic-Test fehlgeschlagen: %s", e)
        return jsonify(error=f"Test fehlgeschlagen: {e}"), 500
    return jsonify(ok=True, **info)


@app.route("/api/homematic/radio", methods=["GET"])
def api_homematic_radio():
    """Funk-Diagnose: Duty Cycle der Funkmodule, gespraechigste Geraete und Befehle der App (Fehlersuche bei Duty Cycle 100 %)."""
    try:
        return jsonify(homematic.radio_report())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/pause", methods=["POST"])
def api_homematic_pause():
    """Test: Zugriff der App auf die CCU fuer einige Minuten sperren (endet von selbst). Geraete gelten dann als nicht erreichbar, Regeln schalten sie nicht."""
    try:
        minutes = float((request.get_json(silent=True) or {}).get("minutes", 30))
    except (TypeError, ValueError):
        return jsonify(error="Minuten: Zahl erwartet"), 400
    left = homematic.pause(minutes)
    opslog.log("rules", f"Homematic: Zugriff für {int(left // 60)} Minuten pausiert (Funk-Test)")
    return jsonify(ok=True, paused_s=int(left))


@app.route("/api/homematic/resume", methods=["POST"])
def api_homematic_resume():
    homematic.resume()
    opslog.log("rules", "Homematic: Pause beendet")
    return jsonify(ok=True)


@app.route("/api/homematic/events", methods=["GET"])
def api_homematic_events():
    """Letzte Meldungen der CCU (nur Fehlersuche): welche Taste/welcher Sensor hat zuletzt was gemeldet."""
    return jsonify(events=homematic.recent_events(), push=homematic.push_active())


@app.route("/api/homematic/push", methods=["GET", "POST"])
def api_homematic_push():
    """Push von der CCU (schnelle Reaktion ohne staendiges Abfragen): Status lesen bzw. ein-/ausschalten."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        try:
            homematic.save_push(bool(body.get("enabled")), body.get("port"))
        except homematic.HomematicError as e:
            return jsonify(error=str(e)), 400
    return jsonify(homematic.push_status())


@app.route("/api/homematic/scan", methods=["POST"])
def api_homematic_scan():
    """Schaltbare Homematic-/HomematicIP-Kanaele (Schalter, Dimmer) der CCU suchen."""
    try:
        return jsonify(shelly.homematic_scan())
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Homematic-Suche fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/homematic/add", methods=["POST"])
def api_homematic_add():
    body = request.get_json(silent=True) or {}
    addrs = body.get("addresses")
    if addrs is None and body.get("address"):
        addrs = [body.get("address")]
    if not isinstance(addrs, list) or not addrs or not all(isinstance(a, str) for a in addrs):
        return jsonify(error="Kein Kanal angegeben"), 400
    bad = _edit_err(_edits(), "device")
    if bad:
        return bad
    try:
        added = shelly.add_homematic(addrs)
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    _apply_edits(added, _edits(), "device")
    return jsonify({"added": len(added)}), 201


@app.route("/api/homematic/sensors/scan", methods=["POST"])
def api_homematic_sensor_scan():
    """Lesbare Sensoren der CCU suchen (Temperatur, Luftfeuchte, Fenster/Tuer, Bewegung, Anwesenheit, Helligkeit, Leistung)."""
    try:
        return jsonify(homematic.sensors_scan())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Sensor-Suche fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/homematic/sensors/add", methods=["POST"])
def api_homematic_sensor_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        return jsonify(error="Kein Sensor angegeben"), 400
    bad = _edit_err(_edits(), "sensor")
    if bad:
        return bad
    try:
        added = homematic.add_sensors(ids)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    _apply_edits(added, _edits(), "sensor")
    return jsonify({"added": len(added)}), 201


FAMILIES = ("shelly", "tasmota", "tuya", "homematic", "zigbee", "midea", "wol")


def _families() -> dict:
    """Welche Smart-Home-Systeme der Nutzer verwendet. Ohne gespeicherte Auswahl: was schon eingerichtet ist (Geraete/Zugang)."""
    saved = store.load_config().get("device_families")
    if isinstance(saved, dict):
        return {k: bool(saved.get(k)) for k in FAMILIES}
    kinds = {d.get("kind", "shelly") for d in shelly.load_devices()}
    return {"shelly": "shelly" in kinds, "tasmota": "tasmota" in kinds or "wled" in kinds,
            "tuya": "tuya" in kinds or bool(tuya.credentials_public().get("configured")),
            "homematic": "homematic" in kinds or bool(homematic.credentials_public().get("configured")),
            "zigbee": "zigbee" in kinds or bool(zigbee.credentials_public().get("configured")),
            "midea": "midea" in kinds,
            "wol": bool(wol.load())}


@app.route("/api/device-families", methods=["GET", "POST"])
def api_device_families():
    """Auswahl der Smart-Home-Systeme (Einstellungen -> Geraete): blendet nicht benoetigte Such-/Einrichtungsbereiche aus."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        cfg = store.load_config()
        cfg["device_families"] = {k: bool(body.get(k)) for k in FAMILIES}
        store.save_config(cfg)
    return jsonify(families={**_families(), "camera": bool(camera.load())}, chosen=isinstance(store.load_config().get("device_families"), dict))


@app.route("/api/virtual", methods=["GET"])
def api_virtual_list():
    """Eigene Schalter/Knoepfe; 'running' = ein von diesem Schalter ausgeloester Ablauf laeuft noch (mit Restzeit)."""
    if not store.module_on("smarthome"):
        return jsonify([])
    items = _vis_filter([virtual.public(x) for x in virtual.load()])    # ohne PIN-Hash; nur fuer dieses Konto sichtbare
    snap = virtual.snapshot()
    nfc_ids = {t.get("target") for t in nfc.load()["tags"]}
    for v in items:
        v["nfc"] = v["id"] in nfc_ids                                      # gehoert zu einem NFC-Tag: Symbol fest
        if v.get("kind") == "timer":                                     # Nachlauf-Timer: laeuft er noch, und wie lange
            v["on"] = bool(snap.get(v["id"], {}).get("on"))
            v["remaining_s"] = snap.get(v["id"], {}).get("remaining_s", 0)
    flow_rules = [r for r in rules.list_rules() if flows.is_flow(r)]
    for v in items:
        for r in flow_rules:
            if any(c.get("type") == "virtual" and c.get("id") == v["id"] and c.get("is") != "pressed" for c in r["when"]["conds"]):
                rest = flow_engine.remaining(r["id"])
                if rest is not None:
                    v["running"] = {"rule": r.get("name", ""), "remaining_s": int(rest)}
                    break
    return jsonify(items)


@app.route("/api/virtual", methods=["POST"])
def api_virtual_add():
    denied = _admin_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(virtual.public(virtual.add(body.get("name"), body.get("kind"), body.get("icon"), body.get("minutes"),
                                                  url=body.get("url") if isinstance(body.get("url"), str) else None,
                                                  method=body.get("method") if isinstance(body.get("method"), str) else None))), 201
    except virtual.VirtualError as e:
        return jsonify(error=str(e)), 400


# --- Verlaufsgraphen (verlauf.py): Messwerte fein aufzeichnen und als Diagramme zeigen ---------------------------
@app.route("/verlauf")
def verlauf_page():
    return render_template("verlauf.html")


@app.route("/api/verlauf/catalog", methods=["GET"])
def api_verlauf_catalog():
    """Was sich aufzeichnen laesst (nur Administratoren)."""
    denied = _admin_only()
    if denied:
        return denied
    have = {s["id"] for s in verlauf.load_series()}
    return jsonify(sources=[{**c, "known": c["id"] in have} for c in verlauf.catalog()], intervals=list(verlauf.INTERVALS),
                   defaults=verlauf.DEFAULT_INTERVAL)


@app.route("/api/verlauf/series", methods=["GET"])
def api_verlauf_series():
    return jsonify(series=verlauf.load_series(), stats=verlauf.stats())


@app.route("/api/verlauf/series", methods=["POST"])
def api_verlauf_series_add():
    denied = _admin_only()
    if denied:
        return denied
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(verlauf.add_series(str(b.get("source") or ""), b.get("interval_s"), b.get("label") or "")), 201
    except verlauf.VerlaufError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/verlauf/series/<path:sid>", methods=["PATCH", "DELETE"])
def api_verlauf_series_modify(sid):
    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        ok = verlauf.remove_series(sid)
        if ok and (request.get_json(silent=True) or {}).get("delete_data"):
            verlauf.delete_data(sid)
        return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)
    b = request.get_json(silent=True) or {}
    try:
        ok = verlauf.update_series(sid, label=b.get("label"), interval_s=b.get("interval_s"))
    except verlauf.VerlaufError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/verlauf/data", methods=["GET"])
def api_verlauf_data():
    """?series=a,b&from=<ms>&to=<ms>&points=<n> -> je Reihe Punkte [ms, Mittel, Min, Max] (None = Luecke)."""
    reg = {s["id"]: s for s in verlauf.load_series()}
    ids = [i for i in (request.args.get("series") or "").split(",") if i in reg][:verlauf.MAX_SERIES_PER_CHART]
    try:
        t1 = float(request.args.get("to") or time.time() * 1000) / 1000
        t0 = float(request.args.get("from") or (t1 - 86400) * 1000) / 1000
        pts = int(request.args.get("points") or 1500)
    except ValueError:
        return jsonify(error="Zeitraum ungültig"), 400
    if not t0 < t1 <= time.time() + 3600 or t1 - t0 > 420 * 86400:
        return jsonify(error="Zeitraum ungültig (höchstens 420 Tage)"), 400
    return jsonify(series=verlauf.query({i: reg[i] for i in ids}, t0, t1, pts), now=int(time.time() * 1000))


@app.route("/api/verlauf/charts", methods=["GET"])
def api_verlauf_charts():
    return jsonify(charts=verlauf.load_charts())


@app.route("/api/verlauf/charts", methods=["POST"])
def api_verlauf_charts_save():
    denied = _admin_only()
    if denied:
        return denied
    try:
        return jsonify(charts=verlauf.save_charts((request.get_json(silent=True) or {}).get("charts")))
    except verlauf.VerlaufError as e:
        return jsonify(error=str(e)), 400


# --- Kameras (Reolink): Standbild + Live ueber die App; Zugangsdaten/IP bleiben auf dem Server -----------------
@app.route("/kameras")
def kameras_page():
    return render_template("kameras.html")


@app.route("/api/cameras", methods=["GET"])
def api_cameras_list():
    admin = auth.is_full_admin(g.perms)
    items = [camera.public(x, admin) for x in camera.load() if _visible(x)]               # nur Kameras, die dieses Konto sehen darf (ohne Passwort; IP/Benutzer nur fuer Admins)
    mine = (users.get(g.user) or {}).get("camera_order") or []                            # eigene Reihenfolge zuerst, Neues hinten in der Reihenfolge der Verwaltung
    pos = {i: n for n, i in enumerate(mine)}
    items.sort(key=lambda c: pos.get(c["id"], len(pos)))
    return jsonify(cameras=items, live=bool(camera.ffmpeg_path()), max_live_min=camera.MAX_LIVE_S // 60)


@app.route("/api/cameras", methods=["POST"])
def api_cameras_add():
    denied = _admin_only()
    if denied:
        return denied
    b = request.get_json(silent=True) or {}
    try:
        item = camera.add(b.get("name"), b.get("host"), b.get("user"), b.get("password"), b.get("port"), b.get("channel"), bool(b.get("https")),
                          b.get("kind") or "reolink", b.get("path_main") or "", b.get("path_sub") or "")
    except camera.CameraError as e:
        return jsonify(error=str(e)), 400
    return jsonify(camera.public(item, True)), 201


@app.route("/api/cameras/my-order", methods=["POST"])
def api_cameras_my_order():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        users.set_camera_order(g.user, ids)
    except UserError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True)


@app.route("/api/cameras/order", methods=["POST"])
def api_cameras_order():
    denied = _admin_only()
    if denied:
        return denied
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    camera.reorder(ids)
    return jsonify(ok=True)


@app.route("/api/cameras/<cid>", methods=["PATCH", "DELETE"])
def api_camera_modify(cid):
    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        busy = _in_use("camera", cid)
        if busy:
            return busy
        for sid in camera.motion_sensor_ids(cid):                  # Bewegungs-Sensoren dieser Kamera: in Regeln benutzt = Kamera bleibt, sonst mit entfernen
            busy = _in_use("sensor", sid)
            if busy:
                return busy
        if not camera.remove(cid):
            return jsonify(error="nicht gefunden"), 404
        for sid in camera.motion_sensor_ids(cid):
            homematic.remove_sensor(sid)
        rules.remove_device(cid)                                   # Standbild-Schritte dieser Kamera aus den Regeln nehmen
        return jsonify(ok=True)
    b = request.get_json(silent=True) or {}
    err = _vis_set("camera", cid, b)
    if err:
        return err
    try:
        ok = camera.update(cid, name=b.get("name"), host=b.get("host"), user=b.get("user"), password=b.get("password"), port=b.get("port"),
                           channel=b.get("channel"), https=b.get("https") if isinstance(b.get("https"), bool) else None,
                           path_main=b.get("path_main"), path_sub=b.get("path_sub"),
                           show=b.get("show") if isinstance(b.get("show"), bool) else None)
    except camera.CameraError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


def _camera_for_me(cid):
    cam = camera.get(cid)
    if not cam or not _visible(cam):
        return None
    return cam


@app.route("/api/cameras/<cid>/snapshot", methods=["GET"])
def api_camera_snapshot(cid):
    cam = _camera_for_me(cid)
    if not cam:
        return jsonify(error="nicht gefunden"), 404
    try:
        data = camera.snapshot(cam)
    except camera.CameraError as e:
        return jsonify(error=str(e)), 503
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/api/cameras/<cid>/stream", methods=["GET"])
def api_camera_stream(cid):
    cam = _camera_for_me(cid)
    if not cam:
        return jsonify(error="nicht gefunden"), 404
    try:
        gen = camera.stream(cam, camera.norm_quality(request.args.get("q")))
    except camera.CameraError as e:
        return jsonify(error=str(e)), 429 if "Zu viele" in str(e) else (501 if "nicht installiert" in str(e) else 503)
    return Response(stream_with_context(gen), mimetype=camera.MJPEG_TYPE,
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.route("/api/wol", methods=["GET"])
def api_wol_list():
    """Wake-on-LAN-Ziele (ohne PIN-Hash), mit 'up' = per Ping erreichbar (None = unbekannt/keine IP)."""
    if not store.module_on("smarthome"):
        return jsonify([])
    items = _vis_filter([wol.public(x, request.args.get("light") != "1") for x in wol.load()])         # ?light=1: ohne Ping
    if not auth.has_level(g.perms, "settings_geraete", "write"):               # MAC/IP/Broadcast nur mit Schreibrecht im Klartext (wie bei den Geraete-IPs)
        for x in items:
            if x.get("mac"):
                x["mac"] = "••:••:••:••:••:••"
            for k in ("ip", "broadcast"):
                if x.get(k):
                    x[k] = "•.•.•.•"
            x["ip_hidden"] = True
    return jsonify(items)


@app.route("/api/wol", methods=["POST"])
def api_wol_add():
    denied = _admin_only()
    if denied:
        return denied
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(wol.public(wol.add(b.get("name"), b.get("mac"), b.get("ip") or "", b.get("broadcast") or "", b.get("port"), b.get("icon")), False)), 201
    except wol.WolError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/wol/<wid>", methods=["PATCH", "DELETE"])
def api_wol_modify(wid):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("wol", wid)
    if hidden:
        return hidden
    if request.method == "DELETE":
        busy = _in_use("wol", wid)
        if busy:
            return busy
        ok = wol.remove(wid)
        if ok:
            rules.remove_device(wid)
        return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)
    b = request.get_json(silent=True) or {}
    err = _vis_set("wol", wid, b)
    if err:
        return err
    try:
        if "pin" in b:                                                     # nur Administratoren legen PINs fest / entfernen sie
            if not auth.is_full_admin(g.perms):
                return jsonify(error="Nur ein Administrator kann PINs setzen, ändern oder entfernen."), 403
            if not wol.set_pin(wid, str(b.get("pin") or "")):
                return jsonify(error="nicht gefunden"), 404
            _pin_fails.pop("wol:" + wid, None)
        ok = wol.update(wid, name=b.get("name"), mac=b.get("mac"), ip=b.get("ip"), broadcast=b.get("broadcast"), port=b.get("port"),
                        icon=b.get("icon"), show=b.get("show") if isinstance(b.get("show"), bool) else None)
    except wol.WolError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/wol/<wid>/wake", methods=["POST"])
def api_wol_wake(wid):
    hidden = _vis_guard("wol", wid)
    if hidden:
        return hidden
    blocked = _pin_gate("wol:" + wid, lambda _k: wol.has_pin(wid), lambda _k, pin: wol.check_pin(wid, pin))
    if blocked:
        return blocked
    try:
        sent = wol.wake(wid)
    except wol.WolError as e:
        return jsonify(error=str(e)), 400
    name = next((x["name"] for x in wol.load() if x["id"] == wid), wid)
    opslog.log("rules", f"Wake-on-LAN an {name} gesendet", dry=False)
    return jsonify(ok=True, sent=sent)


@app.route("/api/virtual/order", methods=["POST"])
def api_virtual_order():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    wol.reorder(ids)
    virtual.reorder(ids)
    return jsonify(ok=True)


def _order_ids():
    ids = (request.get_json(silent=True) or {}).get("ids")
    return ids if isinstance(ids, list) and all(isinstance(i, str) for i in ids) else None


def _order_route(fn):
    """Gemeinsame Pruefung fuer die Reihenfolge-Endpunkte der Geraetelisten (nur Administratoren)."""
    denied = _admin_only()
    if denied:
        return denied
    ids = _order_ids()
    if ids is None:
        return jsonify(error="ids fehlt"), 400
    fn(ids)
    return jsonify(ok=True)


@app.route("/api/homematic/setpoints/order", methods=["POST"])
def api_setpoints_order():
    return _order_route(homematic.reorder_setpoints)


@app.route("/api/homematic/sounds/order", methods=["POST"])
def api_sounds_order():
    return _order_route(homematic.reorder_sounds)


@app.route("/api/homematic/blinds/order", methods=["POST"])
def api_blinds_order():
    return _order_route(homematic.reorder_blinds)


@app.route("/api/homematic/locks/order", methods=["POST"])
def api_locks_order():
    return _order_route(homematic.reorder_locks)


@app.route("/api/sensors/order", methods=["POST"])
def api_sensors_order():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    homematic.reorder_sensors(ids)
    return jsonify(ok=True)


@app.route("/api/virtual/<vid>", methods=["PATCH", "DELETE"])
def api_virtual_modify(vid):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("virtual", vid)
    if hidden:
        return hidden
    if request.method == "DELETE":
        if nfc.is_target(vid):
            return jsonify(error="Dieser Knopf gehört zu einem NFC-Tag und wird mit dem Tag unter Smart Home → NFC-Tags gelöscht."), 400
        busy = _in_use("virtual", vid)
        if busy:
            return busy
        ok = virtual.remove(vid)
        if ok:
            alexa.remove_ref("virtual", vid)
            nfc.remove_target(vid)
    else:
        body = request.get_json(silent=True) or {}
        err = _vis_set("virtual", vid, body)
        if err:
            return err
        if "pin" in body:                                                  # PIN setzen / mit leerem Wert entfernen
            if not auth.is_full_admin(g.perms):
                return jsonify(error="Nur ein Administrator kann PINs setzen, ändern oder entfernen."), 403
            try:
                if not virtual.set_pin(vid, str(body.get("pin") or "")):
                    return jsonify(error="nicht gefunden"), 404
            except virtual.VirtualError as e:
                return jsonify(error=str(e)), 400
            _pin_fails.pop(vid, None)
        if isinstance(body.get("icon"), str) and body["icon"].strip() != nfc.TAG_ICON and nfc.is_target(vid):
            return jsonify(error="Das Symbol eines NFC-Knopfs ist fest (Etikett)."), 400
        try:
            if isinstance(body.get("name"), str) and nfc.is_target(vid) and body["name"].strip() != next((v["name"] for v in virtual.load() if v["id"] == vid), ""):
                return jsonify(error="Der Name eines NFC-Knopfs wird unter Smart Home → NFC-Tags geändert."), 400
            ok = virtual.update(vid, name=body.get("name") if isinstance(body.get("name"), str) else None,
                                icon=body.get("icon") if isinstance(body.get("icon"), str) else None,
                                show=body.get("show") if isinstance(body.get("show"), bool) else None,
                                minutes=body.get("minutes") if body.get("minutes") not in (None, "") else None,
                                url=body.get("url") if isinstance(body.get("url"), str) and body.get("url").strip() else None,
                                clear_url=body.get("clear_url") is True,
                                method=body.get("method") if isinstance(body.get("method"), str) else None)
        except virtual.VirtualError as e:
            return jsonify(error=str(e)), 400
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


_pin_fails: dict[str, list] = {}                          # schalter-id -> [Fehlversuche, Zeit des ersten]
PIN_MAX_FAILS, PIN_LOCK_S = 5, 300


def _pin_gate(vid: str, has_fn=None, check_fn=None):
    """None = darf durch (keine PIN noetig oder richtig). Sonst eine Fehlerantwort (403/429). 5 Fehlversuche sperren den Schalter 5 Minuten.
    Standard: eigene Schalter/Knoepfe; mit has_fn/check_fn auch fuer Geraete (Schluessel mit Praefix, damit sich die Sperren nicht mischen)."""
    has_fn, check_fn = has_fn or virtual.has_pin, check_fn or virtual.check_pin
    if not has_fn(vid):
        return None
    now = time.time()
    rec = _pin_fails.get(vid)
    if rec and rec[0] >= PIN_MAX_FAILS and now - rec[1] < PIN_LOCK_S:
        return jsonify(error=f"Zu viele falsche Eingaben – bitte {int(PIN_LOCK_S - (now - rec[1])) // 60 + 1} Minuten warten", pin_required=True, locked=True), 429
    if rec and now - rec[1] >= PIN_LOCK_S:
        _pin_fails.pop(vid, None)
        rec = None
    pin = (request.get_json(silent=True) or {}).get("pin")
    if not pin:
        return jsonify(error="PIN erforderlich", pin_required=True), 403
    if check_fn(vid, str(pin)):
        _pin_fails.pop(vid, None)
        return None
    rec = _pin_fails.setdefault(vid, [0, now])
    rec[0] += 1
    left = PIN_MAX_FAILS - rec[0]
    log.warning("Falsche PIN an Schalter bzw. Gerät %s (%d von %d)", vid, rec[0], PIN_MAX_FAILS)
    return jsonify(error="PIN falsch" + (f" – noch {left} Versuche" if left > 0 else " – gesperrt für 5 Minuten"), pin_required=True), 403


@app.route("/api/virtual/<vid>/url", methods=["GET"])
def api_virtual_url(vid):
    """Hinterlegte Web-Adresse eines Knopfs - nur fuer Administratoren (zum Ansehen/Aendern; sonst bleibt sie geheim)."""
    if not auth.is_full_admin(g.perms):
        return jsonify(error="Nur Administratoren dürfen die Adresse sehen."), 403
    it = next((v for v in virtual.load() if v["id"] == vid), None)
    if not it:
        return jsonify(error="nicht gefunden"), 404
    resp = jsonify(url=it.get("url", ""), method=it.get("method", "GET"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/virtual/<vid>/press", methods=["POST"])
def api_virtual_press(vid):
    hidden = _vis_guard("virtual", vid)
    if hidden:
        return hidden
    blocked = _pin_gate(vid)
    if blocked:
        return blocked
    t0 = time.time()
    if not virtual.press(vid):
        return jsonify(error="Knopf nicht gefunden"), 404
    opslog.log("rules", f"Eigener Knopf {next((v['name'] for v in virtual.load() if v['id'] == vid), vid)} gedrückt", dry=False)
    ctrl._rules_wake.set()
    if any(v["id"] == vid and v.get("url") for v in virtual.load()):         # Knopf mit Web-Aufruf: kurz auf das Ergebnis warten (Adresse bleibt geheim)
        res = webhook.result_since(vid, t0, 4.0)
        return jsonify(ok=True, call=("läuft" if res is None else "ok" if res[0] else "fehler"), call_text=("" if res is None else res[1]))
    return jsonify(ok=True)


@app.route("/api/virtual/<vid>/set", methods=["POST"])
def api_virtual_set(vid):
    hidden = _vis_guard("virtual", vid)
    if hidden:
        return hidden
    blocked = _pin_gate(vid)
    if blocked:
        return blocked
    if not virtual.set_state(vid, bool((request.get_json(silent=True) or {}).get("on"))):
        return jsonify(error="Schalter nicht gefunden"), 404
    ctrl._rules_wake.set()
    return jsonify(ok=True)


@app.route("/api/homematic/locks", methods=["GET"])
def api_lock_list():
    try:
        return jsonify(homematic.list_locks_with_state(live=request.args.get("light") != "1"))
    except Exception as e:                               # noqa: BLE001
        log.warning("Schlossliste: %s", e)
        return jsonify([])


@app.route("/api/homematic/locks/scan", methods=["POST"])
def api_lock_scan():
    try:
        return jsonify(homematic.locks_scan())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/locks/add", methods=["POST"])
def api_lock_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = homematic.add_locks(ids)
        _apply_edits(res, _edits(), "lock")
        return jsonify(added=res)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/locks/<lid>", methods=["PATCH", "DELETE"])
def api_lock_modify(lid):
    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        busy = _in_use("lock", lid)
        if busy:
            return busy
        ok = homematic.remove_lock(lid)
        if ok:
            rules.remove_device(lid)
    else:
        body = request.get_json(silent=True) or {}
        ok = homematic.update_lock(lid, name=body.get("name") if isinstance(body.get("name"), str) else None,
                                   allow_open=body.get("allow_open") if isinstance(body.get("allow_open"), bool) else None)
        if ok and body.get("allow_open") is False:                 # Freigabe entzogen: Regeln mit Entriegeln/Oeffnen fuer dieses Schloss ausschalten
            items = rules.list_rules()
            changed = False
            for r in items:
                if r.get("when") and any(a.get("type") == "lock" and a.get("id") == lid and a.get("state") != "lock" for a in r["then"] + r["else"]) and r.get("enabled", True):
                    r["enabled"] = False
                    changed = True
            if changed:
                rules.replace_all(items)
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/homematic/sounds", methods=["GET"])
def api_sound_list():
    return jsonify(_vis_filter(homematic.load_sounds()))


@app.route("/api/homematic/sounds/scan", methods=["POST"])
def api_sound_scan():
    try:
        return jsonify(homematic.sounds_scan())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Soundmodul-Suche fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/homematic/sounds/add", methods=["POST"])
def api_sound_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        bad = _edit_err(_edits(), "sound")
        if bad:
            return bad
        res = homematic.add_sounds(ids)
        _apply_edits(res, _edits(), "sound")
        return jsonify(added=res)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/sounds/<sid>", methods=["PATCH", "DELETE"])
def api_sound_modify(sid):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("sound", sid)
    if hidden:
        return hidden
    if request.method == "DELETE":
        busy = _in_use("sound", sid)
        if busy:
            return busy
        ok = homematic.remove_sound(sid)
        if ok:
            rules.remove_device(sid)
    else:
        body = request.get_json(silent=True) or {}
        err = _vis_set("sound", sid, body)
        if err:
            return err
        icon = body.get("icon") if isinstance(body.get("icon"), str) else None
        if icon is not None and icon not in shelly.ICONS:
            return jsonify(error="Unbekanntes Symbol"), 400
        ok = homematic.update_sound(sid, name=body.get("name"), icon=icon)
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/homematic/sounds/<sid>/play", methods=["POST"])
def api_sound_play(sid):
    """Test-Knopf: Titel auf dem Soundmodul abspielen."""
    hidden = _vis_guard("sound", sid)
    if hidden:
        return hidden
    b = request.get_json(silent=True) or {}
    try:
        name = homematic.sound_play(sid, b.get("track", 1), b.get("volume", 100), b.get("repeats", 1))
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    opslog.log("rules", f"Soundmodul {name}: Test-Sound abgespielt")
    return jsonify(ok=True, name=name)


@app.route("/api/homematic/blinds", methods=["GET"])
def api_blind_list():
    """Rollladen mit aktueller Position (0 = zu, 100 = auf); ?light=1 ohne Live-Abfrage der CCU."""
    if not store.module_on("smarthome"):
        return jsonify([])
    return jsonify(_vis_filter(homematic.list_blinds_with_level(live=request.args.get("light") != "1")))


@app.route("/api/homematic/blinds/scan", methods=["POST"])
def api_blind_scan():
    try:
        return jsonify(homematic.blinds_scan())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Rollladen-Suche fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/homematic/blinds/add", methods=["POST"])
def api_blind_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        bad = _edit_err(_edits(), "blind")
        if bad:
            return bad
        res = homematic.add_blinds(ids)
        _apply_edits(res, _edits(), "blind")
        return jsonify(added=res)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/blinds/<bid>", methods=["PATCH", "DELETE"])
def api_blind_modify(bid):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("blind", bid)
    if hidden:
        return hidden
    if request.method == "DELETE":
        busy = _in_use("blind", bid)
        if busy:
            return busy
        ok = homematic.remove_blind(bid)
        if ok:
            rules.remove_device(bid)
    else:
        body = request.get_json(silent=True) or {}
        err = _vis_set("blind", bid, body)
        if err:
            return err
        icon = body.get("icon") if isinstance(body.get("icon"), str) else None
        if icon is not None and icon not in shelly.ICONS:
            return jsonify(error="Unbekanntes Symbol"), 400
        ok = homematic.update_blind(bid, name=body.get("name"), icon=icon)
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/homematic/blinds/<bid>/level", methods=["POST"])
def api_blind_level(bid):
    """Rollladen auf eine Position fahren (0 = zu, 100 = auf)."""
    hidden = _vis_guard("blind", bid)
    if hidden:
        return hidden
    try:
        name = homematic.blind_set(bid, (request.get_json(silent=True) or {}).get("level"))
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    opslog.log("rules", f"Rollladen {name}: von Hand auf {int(round(float((request.get_json(silent=True) or {}).get('level'))))} % gefahren")
    return jsonify(ok=True, name=name)


@app.route("/api/homematic/blinds/<bid>/stop", methods=["POST"])
def api_blind_stop(bid):
    hidden = _vis_guard("blind", bid)
    if hidden:
        return hidden
    try:
        name = homematic.blind_stop(bid)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400
    opslog.log("rules", f"Rollladen {name}: von Hand angehalten")
    return jsonify(ok=True, name=name)


@app.route("/api/homematic/setpoints", methods=["GET"])
def api_setpoint_list():
    try:
        return jsonify(homematic.list_setpoints_with_values(live=request.args.get("light") != "1"))
    except Exception as e:                               # noqa: BLE001
        log.warning("Thermostatliste: %s", e)
        return jsonify([])


@app.route("/api/homematic/setpoints/scan", methods=["POST"])
def api_setpoint_scan():
    try:
        return jsonify(homematic.setpoints_scan())
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/setpoints/add", methods=["POST"])
def api_setpoint_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = homematic.add_setpoints(ids)
        _apply_edits(res, _edits(), "setpoint")
        return jsonify(added=res)
    except homematic.HomematicError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/homematic/setpoints/<sp_id>", methods=["PATCH", "DELETE"])
def api_setpoint_modify(sp_id):
    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        busy = _in_use("setpoint", sp_id)
        if busy:
            return busy
        ok = homematic.remove_setpoint(sp_id)
        if ok:
            rules.remove_device(sp_id)
    else:
        ok = homematic.update_setpoint(sp_id, name=(request.get_json(silent=True) or {}).get("name"))
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/zigbee", methods=["GET"])
def api_zigbee_info():
    info = zigbee.credentials_public()                                                             # ohne Schluessel
    for gw in info["gateways"]:
        _masked(gw, "smarthome_einrichten", ["host"])
    return jsonify(_masked(info, "smarthome_einrichten", ["host"]))


@app.route("/api/zigbee/credentials", methods=["POST"])
def api_zigbee_credentials():
    """Gateway anlegen/aendern (Adresse, Name, optional vorhandener Schluessel) und testen; ohne Schluessel: vom Gateway holen (Phoscon: App autorisieren)."""
    body = request.get_json(silent=True) or {}
    host, name, gw_id = body.get("host"), body.get("name") or "", body.get("id") or ""
    try:
        if (body.get("key") or "").strip():
            gw = zigbee.save_gateway(host, body.get("key"), name, gw_id)
        else:
            gw = zigbee.save_gateway(host, "", name, gw_id)
            if not gw.get("key"):
                zigbee.pair(host, name, gw["id"])
        info = zigbee.test_connection(gw["id"])
    except zigbee.ZigbeeError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                               # noqa: BLE001
        log.warning("Zigbee-Test fehlgeschlagen: %s", e)
        return jsonify(error=f"Test fehlgeschlagen: {e}"), 500
    return jsonify(ok=True, **info)


@app.route("/api/zigbee/pair", methods=["POST"])
def api_zigbee_pair():
    """Neuen Schluessel vom Gateway holen (in Phoscon vorher "App autorisieren")."""
    body = request.get_json(silent=True) or {}
    try:
        zigbee.pair(body.get("host"), body.get("name") or "", body.get("id") or "")
        return jsonify(ok=True, **zigbee.test_connection(zigbee.save_gateway(body.get("host"), "", "", body.get("id") or "")["id"]))
    except zigbee.ZigbeeError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/zigbee/gateways/order", methods=["POST"])
def api_zigbee_gateways_order():
    return _order_route(zigbee.reorder_gateways)


@app.route("/api/zigbee/gateways/<gw_id>", methods=["PATCH"])
def api_zigbee_gateway_rename(gw_id):
    """Nur den Namen eines Gateways aendern (Adresse und Schluessel bleiben)."""
    if not zigbee.rename_gateway(gw_id, (request.get_json(silent=True) or {}).get("name") or ""):
        return jsonify(error="nicht gefunden oder Name leer"), 404
    return jsonify(ok=True)


@app.route("/api/zigbee/gateways/<gw_id>", methods=["DELETE"])
def api_zigbee_gateway_delete(gw_id):
    """Gateway entfernen - nur wenn nichts mehr daran haengt (sonst gingen Geraete, Sensoren und Regeln verloren)."""
    if not zigbee.gateway(gw_id) or not any(g["id"] == gw_id for g in zigbee.load_gateways()):
        return jsonify(error="nicht gefunden"), 404
    n = zigbee.in_use(gw_id)
    if n:
        return jsonify(error=f"An diesem Gateway hängen noch {n} Geräte, Sensoren oder Thermostate – zuerst unter Geräte/Sensoren/Thermostate entfernen."), 409
    zigbee.remove_gateway(gw_id)
    return jsonify(ok=True)


def _zb_call(fn, *a):
    try:
        return jsonify(fn(*a)), 200
    except (zigbee.ZigbeeError, shelly.ShellyError) as e:
        return jsonify(error=str(e)), 400


@app.route("/api/zigbee/scan", methods=["POST"])
def api_zigbee_scan():
    return _zb_call(shelly.zigbee_scan)


@app.route("/api/zigbee/add", methods=["POST"])
def api_zigbee_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = shelly.add_zigbee(ids)
        _apply_edits(res, _edits(), "device")
        return jsonify(added=res)
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/cameras/motion/scan", methods=["POST"])
def api_camera_motion_scan():
    """Bewegungs-/Personen-/Fahrzeug-/Tier-Erkennung der Reolink-Kameras als Sensoren anbieten."""
    try:
        return jsonify(camera.motion_sensors_scan())
    except camera.CameraError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/cameras/motion/add", methods=["POST"])
def api_camera_motion_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = camera.add_motion_sensors(ids)
        _apply_edits(res, _edits(), "sensor")
        return jsonify(added=res)
    except camera.CameraError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/zigbee/sensors/scan", methods=["POST"])
def api_zigbee_sensor_scan():
    return _zb_call(zigbee.sensors_scan)


@app.route("/api/zigbee/sensors/add", methods=["POST"])
def api_zigbee_sensor_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = zigbee.add_sensors(ids)
        _apply_edits(res, _edits(), "sensor")
        return jsonify(added=res)
    except zigbee.ZigbeeError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/zigbee/setpoints/scan", methods=["POST"])
def api_zigbee_sp_scan():
    return _zb_call(zigbee.setpoints_scan)


@app.route("/api/zigbee/setpoints/add", methods=["POST"])
def api_zigbee_sp_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        res = zigbee.add_setpoints(ids)
        _apply_edits(res, _edits(), "setpoint")
        return jsonify(added=res)
    except zigbee.ZigbeeError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/sensors", methods=["GET"])
def api_sensors_list():
    """Angelegte Sensoren mit aktuellem Wert (fuer Einstellungen und Regel-Bedingungen)."""
    if not store.module_on("smarthome"):
        return jsonify([])
    try:
        return jsonify(_vis_filter(homematic.list_sensors_with_values(live=request.args.get("light") != "1")))
    except Exception as e:                               # noqa: BLE001
        log.warning("Sensorliste: %s", e)
        return jsonify([])


@app.route("/api/sensors/<sensor_id>", methods=["PATCH", "DELETE"])
def api_sensor_modify(sensor_id):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("sensor", sensor_id)
    if hidden:
        return hidden
    if request.method == "DELETE":
        busy = _in_use("sensor", sensor_id)
        if busy:
            return busy
        ok = homematic.remove_sensor(sensor_id)
    else:
        body = request.get_json(silent=True) or {}
        err = _vis_set("sensor", sensor_id, body)
        if err:
            return err
        ok = homematic.update_sensor(sensor_id, name=body.get("name"), show=body.get("show") if isinstance(body.get("show"), bool) else None,
                                      invert=body.get("invert") if isinstance(body.get("invert"), bool) else None,
                                      icon=body.get("icon") if isinstance(body.get("icon"), str) else None)
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/shelly/icons", methods=["GET"])
def api_shelly_icons():
    return jsonify(shelly.ICONS)


@app.route("/api/shelly/order", methods=["POST"])
def api_shelly_order():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    shelly.reorder(ids)
    return jsonify(ok=True)


@app.route("/api/shelly/scan", methods=["POST"])
def api_shelly_scan():
    """Durchsucht das lokale /24-Netz nach Shelly-Geraeten (dauert ca. 2-5 s)."""
    try:
        return jsonify(shelly.discover(extra_networks=_scan_networks()))
    except Exception as e:                               # noqa: BLE001
        log.warning("Shelly-Scan fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/tasmota/scan", methods=["POST"])
def api_tasmota_scan():
    """Durchsucht das lokale /24-Netz und die eingestellten weiteren Netze nach Tasmota-Geraeten."""
    try:
        return jsonify(shelly.tasmota_discover(extra_networks=_scan_networks()))
    except Exception as e:                               # noqa: BLE001
        log.warning("Tasmota-Scan fehlgeschlagen: %s", e)
        return jsonify(error=f"Suche fehlgeschlagen: {e}"), 500


@app.route("/api/shelly/preview", methods=["POST"])
def api_shelly_preview():
    """Gefundenes Geraet (per IP) nur ansehen: Kanaele mit Name/Symbol zum Vorab-Bearbeiten, noch nichts angelegt."""
    body = request.get_json(silent=True) or {}
    try:
        items = shelly.add_by_ip(body.get("ip", ""), body.get("password", ""), preview=True)
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    return jsonify({"ip": body.get("ip", "").strip(), "devices": shelly.preview_public(items)})


@app.route("/api/shelly", methods=["POST"])
def api_shelly_add():
    body = request.get_json(silent=True) or {}
    try:
        added = shelly.add_by_ip(body.get("ip", ""), body.get("password", ""), body.get("edits") if isinstance(body.get("edits"), dict) else None)
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    return jsonify({"added": len(added)}), 201


@app.route("/api/shelly/<dev_id>", methods=["PATCH", "DELETE"])
def api_shelly_modify(dev_id):
    denied = _admin_only()
    if denied:
        return denied
    hidden = _vis_guard("shelly", dev_id)
    if hidden:
        return hidden
    if request.method == "DELETE":
        busy = _in_use("device", dev_id)
        if busy:
            return busy
        ok = shelly.remove(dev_id)
        if ok:
            rules.remove_device(dev_id)
            alexa.remove_ref("shelly", dev_id)
    else:
        body = request.get_json(silent=True) or {}
        err = _vis_set("shelly", dev_id, body)
        if err:
            return err
        try:
            if "pin" in body:                                              # PIN setzen / mit leerem Wert entfernen
                if not auth.is_full_admin(g.perms):
                    return jsonify(error="Nur ein Administrator kann PINs setzen, ändern oder entfernen."), 403
                if not shelly.set_pin(dev_id, str(body.get("pin") or "")):
                    return jsonify(error="nicht gefunden"), 404
                _pin_fails.pop(dev_id, None)
            ok = shelly.update(dev_id, name=body.get("name"), icon=body.get("icon"),
                               show=body.get("show"), auto=body.get("auto"),
                               power_w=body.get("power_w"), min_on_min=body.get("min_on_min"),
                               min_off_min=body.get("min_off_min"),
                               switchable=body.get("switchable"))
        except shelly.ShellyError as e:
            return jsonify(error=str(e)), 400
    return jsonify(ok=True) if ok else (jsonify(error="nicht gefunden"), 404)


@app.route("/api/shelly/<dev_id>/switch", methods=["POST"])
def api_shelly_switch(dev_id):
    hidden = _vis_guard("shelly", dev_id)
    if hidden:
        return hidden
    blocked = _pin_gate(dev_id, shelly.has_pin, shelly.check_pin)               # Sicherheits-PIN (falls eingerichtet) - gilt fuer jedes Geraet
    if blocked:
        return blocked
    on = bool((request.get_json(silent=True) or {}).get("on"))
    try:
        result = shelly.set_state(dev_id, on, timer_s=0 if on else None)     # 0 = evtl. laufenden Auto-Timer aufheben
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400      # nicht 502/504: Cloudflare ersetzt diese Antworten durch eine eigene Fehlerseite
    cfg_ = store.load_config()
    surplus_ctrl.note_manual(dev_id, hold_min=surplus.settings(cfg_)["manual_hold_min"])      # Ueberschuss-Automatik pausiert fuer dieses Geraet
    rule_engine.note_manual(dev_id, hold_min=rules.settings(cfg_)["manual_hold_min"])         # Regeln pausieren ebenfalls (eigene Einstellung)
    return jsonify(result)


@app.route("/api/shelly/<dev_id>/brightness", methods=["POST"])
def api_shelly_brightness(dev_id):
    """Helligkeit eines WLED-Geraets (1-100 %); schaltet es ein. PIN und Sichtbarkeit wie beim Schalten."""
    hidden = _vis_guard("shelly", dev_id)
    if hidden:
        return hidden
    blocked = _pin_gate(dev_id, shelly.has_pin, shelly.check_pin)
    if blocked:
        return blocked
    try:
        level = shelly.set_brightness(dev_id, (request.get_json(silent=True) or {}).get("level"))
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    rule_engine.note_manual(dev_id, hold_min=rules.settings(store.load_config())["manual_hold_min"])
    return jsonify(ok=True, level=level)


@app.route("/api/midea/scan", methods=["POST"])
def api_midea_scan():
    """Klimaanlagen (Midea / NetHome Plus) im Heimnetz suchen. Ein eigenes NetHome-Plus-Konto ist nur zum einmaligen Holen des Schluessels da und wird nicht gespeichert."""
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(shelly.midea_scan(b.get("region"), b.get("account"), b.get("password"), b.get("ip")))
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/midea/add", methods=["POST"])
def api_midea_add():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return jsonify(error="ids fehlt"), 400
    try:
        bad = _edit_err(_edits(), "device")
        if bad:
            return bad
        res = shelly.add_midea(ids)
        _apply_edits(res, _edits(), "device")
        return jsonify(added=[{k: v for k, v in e.items() if k not in ("token", "key", "cloud_password", "cloud_account")} for e in res])        # Schluessel bleiben auf dem Server
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/shelly/<dev_id>/midea", methods=["GET", "POST"])
def api_shelly_midea(dev_id):
    """Klimaanlage bedienen: GET = Moeglichkeiten + Zustand, POST {power, mode, target, fan, swing, eco} = setzen. PIN und Sichtbarkeit wie beim Schalten."""
    hidden = _vis_guard("shelly", dev_id)
    if hidden:
        return hidden
    try:
        if request.method == "GET":
            return jsonify(shelly.midea_details(dev_id))
        blocked = _pin_gate(dev_id, shelly.has_pin, shelly.check_pin)
        if blocked:
            return blocked
        b = request.get_json(silent=True) or {}
        power = b.get("power")
        res = shelly.midea_set(dev_id, power=(None if power is None else bool(power)), mode=b.get("mode"), target=b.get("target"), fan=b.get("fan"), swing=b.get("swing"),
                               eco=b.get("eco") if isinstance(b.get("eco"), bool) else None)
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    rule_engine.note_manual(dev_id, hold_min=rules.settings(store.load_config())["manual_hold_min"])
    return jsonify(ok=True, state=res)


@app.route("/api/shelly/<dev_id>/wled", methods=["GET", "POST"])
def api_shelly_wled(dev_id):
    """WLED bedienen: GET = Effekte/Voreinstellungen/aktuelle Farbe, POST {color|effect|palette|preset} = setzen. PIN und Sichtbarkeit wie beim Schalten."""
    hidden = _vis_guard("shelly", dev_id)
    if hidden:
        return hidden
    try:
        if request.method == "GET":
            return jsonify(shelly.wled_details(dev_id))
        blocked = _pin_gate(dev_id, shelly.has_pin, shelly.check_pin)
        if blocked:
            return blocked
        b = request.get_json(silent=True) or {}
        if b.get("save_preset") is not None:                  # aktuellen Zustand der Lampe als Voreinstellung speichern
            return jsonify(ok=True, **shelly.wled_save_preset(dev_id, b.get("save_preset")))
        res = shelly.wled_set(dev_id, color=b.get("color"), effect=b.get("effect"), preset=b.get("preset"), palette=b.get("palette"))
    except shelly.ShellyError as e:
        return jsonify(error=str(e)), 400
    rule_engine.note_manual(dev_id, hold_min=rules.settings(store.load_config())["manual_hold_min"])
    return jsonify(ok=True, **res)


@app.route("/api/test-connection", methods=["POST"])
def api_test():
    """Wizard: prüft Cerbo + Tibber mit den übergebenen Werten."""
    body = request.get_json(silent=True) or {}
    result = {"cerbo": None, "tibber": None}
    try:
        c = Cerbo(body.get("cerbo_host", ""), int(body.get("cerbo_port", 502)))
        result["cerbo"] = {"ok": True, "soc": round(c.read_soc(), 1),
                           "ess_mode": c.read_ess_mode()}
    except Exception as e:                               # noqa: BLE001
        result["cerbo"] = {"ok": False, "error": str(e)}
    if body.get("tariff_mode") == "fixed":
        price = body.get("fixed_price_ct", 0)
        if price and float(price) > 0:
            result["tibber"] = {"ok": True, "slots": len(build_fixed_price_entries(price))}
        else:
            result["tibber"] = {"ok": False, "error": "Bitte einen Preis > 0 ct/kWh eintragen"}
        return jsonify(result)
    try:
        p = fetch_tibber_prices(body.get("tibber_token", ""))
        result["tibber"] = {"ok": True, "slots": len(p)}
    except Exception as e:                               # noqa: BLE001
        result["tibber"] = {"ok": False, "error": str(e)}
    return jsonify(result)


def main():
    try:
        nfc.migrate_icons()                                  # NFC-Knoepfe mit dem alten Symbol bekommen das Etikett
    except Exception as e:                               # noqa: BLE001
        log.warning("NFC-Symbole: %s", e)
    ctrl.start()
    cfg = store.load_config()
    try:
        n = store.backfill_prices_from_history()
        if n:
            log.info("Preis-Historie: %d Slots aus dem Verlauf zurückgerechnet", n)
    except Exception as e:                               # noqa: BLE001
        log.warning("Preis-Historie-Nachtrag fehlgeschlagen: %s", e)
    notify.push("startup", "🔄 Die Steuerung wurde gestartet.", cfg)
    opslog.count("restarts")
    try:                                                 # Umstellung: Ueberschuss-Automatik und Regeln haben jetzt getrennte Schalter/Einstellungen
        c = store.load_config()
        if not c.get("_automation_split"):
            if "rules_enabled" in c:                       # vorher galt ein gemeinsamer Schalter (rules_*) fuer beides
                c["surplus_enabled"] = bool(c["rules_enabled"])
                c["surplus_dry_run"] = bool(c.get("rules_dry_run", True))
            for k in ("manual_hold_min", "failsafe_min"):
                if "surplus_" + k in c and "rules_" + k not in c:
                    c["rules_" + k] = c["surplus_" + k]
            c["_automation_split"] = True
            store.save_config(c)
    except Exception as e:                               # noqa: BLE001
        log.warning("Trennung der Automatik-Einstellungen fehlgeschlagen: %s", e)
    try:                                                 # Umstellung alter Regeln: Ueberschuss-Regeln -> Flag "In der Ueberschuss-Automatik"
        for dev_id in rules.pending_auto():
            shelly.update(dev_id, auto=True)
            log.info("Regeln: Gerät %s steht jetzt in der Überschuss-Automatik", dev_id)
    except Exception as e:                               # noqa: BLE001
        log.warning("Regel-Umstellung fehlgeschlagen: %s", e)
    opslog.log("startup", "Steuerung gestartet")
    # PORT-Umgebungsvariable hat Vorrang (pm2/systemd), sonst web_port aus Config
    port = int(os.environ.get("PORT", cfg.get("web_port", 5005)))
    log.info("Web-App startet auf Port %s (dry_run=%s)", port, cfg.get("dry_run"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=24)         # Live-Kamerabilder belegen je einen Thread (max. camera.MAX_STREAMS)
    except ImportError:
        app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
