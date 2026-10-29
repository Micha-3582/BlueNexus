import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from logic import PersistentState
import datetime as dt
print("STATE_PATH", store.STATE_PATH)
st = PersistentState(last_full_charge_date=(dt.date.today() - dt.timedelta(days=18)).isoformat())
try:
    store.save_state(st)
    print("save_state returned normally")
except Exception as e:
    print("EXCEPTION:", repr(e))
print("exists?", os.path.exists(store.STATE_PATH))
if os.path.exists(store.STATE_PATH):
    print(open(store.STATE_PATH).read())
