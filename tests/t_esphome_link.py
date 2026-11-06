"""ESPHome-Verbindungsmessung (1.35.0): Abbrueche, Ausfallzeit, laengster Ausfall, Grund; erscheint im Status des Tasters."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import esphome

ip = "10.9.9.9"
import threading; stop = threading.Event()
esphome._hosts[ip] = {"online": False, "stop": stop, "thread": None}
assert esphome.link_stats(ip) is None
esphome._set_online(ip, True, stop)                       # erste Verbindung ist kein Abbruch
l = esphome.link_stats(ip)
assert l["drops"] == 0 and l["down_s"] == 0, l
esphome._last_err[ip] = "Stille (25 s ohne Meldung)"
esphome._set_online(ip, False, stop)                      # Abbruch
time.sleep(0.3)
l = esphome.link_stats(ip)
assert l["drops"] == 1 and l["down_now"] is True and l["down_s"] >= 0.2 and l["last_reason"].startswith("Stille"), l
esphome._set_online(ip, True, stop)                       # wieder da
l = esphome.link_stats(ip)
assert l["drops"] == 1 and l["down_now"] is False and 0.2 <= l["longest_s"] < 2, l
esphome._set_online(ip, False, stop); time.sleep(0.5); esphome._set_online(ip, True, stop)
l = esphome.link_stats(ip)
assert l["drops"] == 2 and l["longest_s"] >= 0.45 and l["down_s"] >= 0.7, l
esphome._set_online(ip, True, stop)                       # online -> online zaehlt nichts
assert esphome.link_stats(ip)["drops"] == 2
print("OK")
# Betriebszeit aus Ping-Meldungen: Neustart = Betriebszeit faellt zurueck
ip2 = "10.9.9.8"
esphome._note_uptime(ip2, 3000); esphome._note_uptime(ip2, 3010)
assert esphome.link_stats(ip2)["restarts"] == 0
esphome._note_uptime(ip2, 12)
l = esphome.link_stats(ip2)
assert l["restarts"] == 1 and l["uptime_s"] == 12 and l["last_restart_ago_s"] is not None, l
esphome._note_uptime(ip2, "kaputt"); esphome._note_uptime(ip2, 20)
assert esphome.link_stats(ip2)["restarts"] == 1
print("OK Neustart")
