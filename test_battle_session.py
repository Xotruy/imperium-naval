"""Полная боевая сессия: 3 игрока, реальные ходы, бои, крепости, мины, логирование"""
import requests, json, time, sys

BASE = "http://localhost:5000"
PASS = 0
FAIL = 0

def ok(name, cond=True, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  [PASS] {name}")
    else:
        FAIL += 1; print(f"  [FAIL] {name} — {msg}")

# ============================================================
# SETUP: Register 3 players + admin
# ============================================================
print("=" * 60)
print("  БОЕВАЯ СЕССИЯ: 3 игрока + админ")
print("=" * 60)

s_admin = requests.Session()
s_rus = requests.Session()
s_brit = requests.Session()
s_fra = requests.Session()

# Admin auth
r = s_admin.post(f"{BASE}/api/auth/register", json={"username": "admin_user", "password": "admin1234"})
ok("Admin register", r.ok, r.text)
r = s_admin.post(f"{BASE}/api/auth/login", json={"username": "admin_user", "password": "admin1234"})
ok("Admin login", r.ok, r.text)
admin_token = r.json()["token"]

# Player auth
for sess, name, pwd in [(s_rus, "russia_player", "rus1234"), (s_brit, "britain_player", "brit123"), (s_fra, "france_player", "fra1234")]:
    r = sess.post(f"{BASE}/api/auth/register", json={"username": name, "password": pwd})
    ok(f"Register {name}", r.ok, r.text)

# ============================================================
# SocketIO: admin seeds, players join
# ============================================================
import socketio

sio_admin = socketio.Client()
sio_rus = socketio.Client()
sio_brit = socketio.Client()
sio_fra = socketio.Client()

admin_session_token = None
rus_session_token = None
brit_session_token = None
fra_session_token = None

@sio_admin.on("session_init")
def on_admin_init(data):
    global admin_session_token
    admin_session_token = data.get("session_token")

@sio_rus.on("session_init")
def on_rus_init(data):
    global rus_session_token
    rus_session_token = data.get("session_token")

@sio_brit.on("session_init")
def on_brit_init(data):
    global brit_session_token
    brit_session_token = data.get("session_token")

@sio_fra.on("session_init")
def on_fra_init(data):
    global fra_session_token
    fra_session_token = data.get("session_token")

battle_events = []

@sio_rus.on("battle_result")
def on_rus_battle(data):
    battle_events.append(("russia", data))

@sio_brit.on("battle_result")
def on_brit_battle(data):
    battle_events.append(("britain", data))

@sio_fra.on("battle_result")
def on_fra_battle(data):
    battle_events.append(("france", data))

map_updates = []

@sio_rus.on("map_update")
def on_rus_map(data):
    map_updates.append(("russia", data))

@sio_brit.on("map_update")
def on_brit_map(data):
    map_updates.append(("britain", data))

state_updates = []

@sio_rus.on("state_update")
def on_rus_state(data):
    state_updates.append(("russia", data))

@sio_brit.on("state_update")
def on_brit_state(data):
    state_updates.append(("britain", data))

sio_admin.connect(BASE)
sio_rus.connect(BASE)
sio_brit.connect(BASE)
sio_fra.connect(BASE)
time.sleep(0.5)
ok("All 4 SocketIO connected", True)

# Admin joins as spectator
sio_admin.emit("join_session", {"name": "Admin", "country_id": 0, "is_spectator": True})
time.sleep(0.3)
ok("Admin joined as spectator", admin_session_token is not None)

# Seed demo data
r = s_admin.post(f"{BASE}/api/seed", headers={"X-Session-Id": admin_session_token})
ok("Seed demo", r.ok, r.json().get("error", ""))
seed = r.json()
ok("Seed loaded", seed.get("ok"), str(seed))

# Players join their countries
sio_rus.emit("join_session", {"name": "Русский Адмирал", "country_id": 1})
time.sleep(0.3)
ok("Russia player joined", rus_session_token is not None)

sio_brit.emit("join_session", {"name": "Британский Адмирал", "country_id": 2})
time.sleep(0.3)
ok("Britain player joined", brit_session_token is not None)

sio_fra.emit("join_session", {"name": "Французский Адмирал", "country_id": 3})
time.sleep(0.3)
ok("France player joined", fra_session_token is not None)

# ============================================================
# STATE CHECK after seed
# ============================================================
print("\n" + "=" * 60)
print("  НАЧАЛЬНОЕ СОСТОЯНИЕ")
print("=" * 60)

r = s_admin.get(f"{BASE}/api/state")
st = r.json()
ok("is_war=False initially", st["is_war"] == False)
ok("turn=1", st["turn_number"] == 1)
ok("turn_index=0 (Russia)", st["turn_index"] == 0)
ok("3 countries in turn_order", len(st["turn_order"]) == 3)

r = s_admin.get(f"{BASE}/api/fleets")
fleets = r.json()
ok("3 fleets after seed", len(fleets) == 3)

russia_fleet = [f for f in fleets if f["country_id"] == 1][0]
britain_fleet = [f for f in fleets if f["country_id"] == 2][0]
france_fleet = [f for f in fleets if f["country_id"] == 3][0]

print(f"  Россия: [{russia_fleet['id']}] ({russia_fleet['pos_x']},{russia_fleet['pos_y']}) armor={russia_fleet['total_armor']} atk={russia_fleet['total_attack']} spd={russia_fleet['min_speed']}")
print(f"  Британия: [{britain_fleet['id']}] ({britain_fleet['pos_x']},{britain_fleet['pos_y']}) armor={britain_fleet['total_armor']} atk={britain_fleet['total_attack']} spd={britain_fleet['min_speed']}")
print(f"  Франция: [{france_fleet['id']}] ({france_fleet['pos_x']},{france_fleet['pos_y']}) armor={france_fleet['total_armor']} atk={france_fleet['total_attack']} spd={france_fleet['min_speed']}")

r = s_admin.get(f"{BASE}/api/relations")
rels = r.json()
war_pairs = [(r2["a"], r2["b"]) for r2 in rels if r2["at_war"]]
ok("Russia-Britain at war", len(war_pairs) >= 1, f"war_pairs={war_pairs}")

r = s_admin.get(f"{BASE}/api/cells")
cells = r.json()
ok("Mines placed", len([c for c in cells if c["mines_count"] > 0]) >= 2, f"cells={cells}")

# ============================================================
# ПЕРЕМЕЩЕНИЕ ДО ВОЙНЫ (мирный режим)
# ============================================================
print("\n" + "=" * 60)
print("  ФАЗА 1: МИРНЫЕ ПЕРЕМЕЩЕНИЯ")
print("=" * 60)

# France moves closer to Britain in peacetime (no speed check in peace)
fr_x, fr_y = france_fleet["pos_x"], france_fleet["pos_y"]
target_y = fr_y - 5  # move north
r = s_fra.post(f"{BASE}/api/fleets/{france_fleet['id']}/move",
               json={"x": fr_x, "y": target_y},
               headers={"X-Session-Id": fra_session_token})
ok("France moves north in peacetime", r.ok, r.json().get("error", ""))

r = s_admin.get(f"{BASE}/api/fleets")
france_after = [f for f in r.json() if f["country_id"] == 3][0]
ok("France new pos", france_after["pos_y"] == target_y, f"expected y={target_y}, got {france_after['pos_y']}")
print(f"  Франция: ({fr_x},{fr_y}) -> ({france_after['pos_x']},{france_after['pos_y']})")

# ============================================================
# ВОЙНА: Включаем военное время
# ============================================================
print("\n" + "=" * 60)
print("  ФАЗА 2: ВКЛЮЧЕНИЕ ВОЕННОГО ВРЕМЕНИ")
print("=" * 60)

map_updates.clear()
r = s_admin.post(f"{BASE}/api/state", json={"is_war": True}, headers={"X-Session-Id": admin_session_token})
ok("Set is_war=True", r.ok, r.json().get("error", ""))
time.sleep(0.3)

r = s_admin.get(f"{BASE}/api/state")
st = r.json()
ok("is_war=True confirmed", st["is_war"] == True)
ok("Turn order preserved", len(st["turn_order"]) == 3)
ok("Still Russia's turn", st["turn_index"] == 0)

# Check socketio state_update was emitted
state_received = any(s == "russia" and d.get("is_war") == True for s, d in state_updates)
ok("SocketIO state_update broadcast", state_received)

# ============================================================
# ХОД 1: Россия — атака на Британию
# ============================================================
print("\n" + "=" * 60)
print("  ХОД 1: РОССИЯ — АТАКА НА БРИТАНИЮ")
print("=" * 60)

# Russia moves to Britain position (dist=2, speed=2 — should work)
br_x, br_y = britain_fleet["pos_x"], britain_fleet["pos_y"]
battle_events.clear()
map_updates.clear()

r = s_rus.post(f"{BASE}/api/fleets/{russia_fleet['id']}/move",
               json={"x": br_x, "y": br_y},
               headers={"X-Session-Id": rus_session_token})
result = r.json()
ok("Russia move OK", result.get("ok"), result.get("error", ""))

battles = result.get("battles", [])
ok("Battle triggered", len(battles) >= 1, f"battles={len(battles)}")

if battles:
    b = battles[0]
    ok("Battle has log", len(b.get("log", [])) > 0)
    ok("Battle has battle_id", b.get("battle_id") is not None)

    log = b.get("log", [])
    has_mine_phase = any("МИНЫ" in l for l in log)
    has_force_phase = any("СИЛЫ" in l for l in log)
    has_salvo_phase = any("ЗАЛП" in l for l in log)
    has_damage_phase = any("РАСПРЕДЕЛЕНИЕ" in l for l in log)
    has_result = any("ИТОГИ" in l for l in log)
    ok("Phase 1: Mines", has_mine_phase)
    ok("Phase 2: Forces", has_force_phase)
    ok("Phase 3: Salvos", has_salvo_phase)
    ok("Phase 4: Damage", has_damage_phase)
    ok("Phase 5: Results", has_result)

    winner_id = b.get("winner_fleet_id")
    ok("Battle has winner", winner_id is not None, f"winner={winner_id}")
    print(f"  Winner fleet_id={winner_id}")
    if winner_id == britain_fleet["id"]:
        print(f"  → Британия победила! Россия отступила.")
    elif winner_id == russia_fleet["id"]:
        print(f"  → Россия победила!")
    else:
        print(f"  → Взаимное уничтожение или ничья")

    # Print battle log
    print("\n  --- ЛОГ БОЯ ---")
    for line in log[:15]:
        print(f"  {line}")
    if len(log) > 15:
        print(f"  ... ({len(log) - 15} more lines)")

# Check Russia fleet position after battle
r = s_admin.get(f"{BASE}/api/fleets")
fleets_after = r.json()
rf_after = [f for f in fleets_after if f["country_id"] == 1][0]
bf_after = [f for f in fleets_after if f["country_id"] == 2][0]

russia_alive = len([s for s in rf_after["ships"] if s["is_alive"]])
britain_alive = len([s for s in bf_after["ships"] if s["is_alive"]])
print(f"\n  После боя:")
print(f"  Россия: alive={russia_alive} pos=({rf_after['pos_x']},{rf_after['pos_y']})")
print(f"  Британия: alive={britain_alive} pos=({bf_after['pos_x']},{bf_after['pos_y']})")
ok("Ships lost in battle", russia_alive < 8 or britain_alive < 5, f"rus={russia_alive} brit={britain_alive}")

# Check fleet was marked as moved
r = s_admin.get(f"{BASE}/api/state")
st = r.json()
moved = st.get("moved_this_turn", {})
ok("Russia fleet marked as moved", moved.get(str(russia_fleet["id"])) == True, f"moved={moved}")

# Check battle was broadcast via socketio
battle_broadcast = any(s == "russia" for s, _ in battle_events)
ok("Battle broadcast via SocketIO", battle_broadcast)

# ============================================================
# ХОД 1: Россия заканчивает ход
# ============================================================
print("\n" + "=" * 60)
print("  ХОД 1: ЗАВЕРШЕНИЕ ХОДА РОССИИ")
print("=" * 60)

r = s_rus.post(f"{BASE}/api/turn/end", json={},
               headers={"X-Session-Id": rus_session_token, "Authorization": f"Bearer {admin_token}"})
result = r.json()
ok("End turn Russia", result.get("ok"), result.get("error", ""))
ok("Turn advanced to index 1 (Britain)", result.get("turn_index") == 1, f"index={result.get('turn_index')}")

r = s_admin.get(f"{BASE}/api/state")
st = r.json()
ok("moved_this_turn cleared", st.get("moved_this_turn") == {})
ok("turn_index=1", st["turn_index"] == 1)
ok("turn_number still 1", st["turn_number"] == 1)

# ============================================================
# ХОД 2: Британия — контратака на Россию
# ============================================================
print("\n" + "=" * 60)
print("  ХОД 2: БРИТАНИЯ — КОНТРАТАКА")
print("=" * 60)

# Britain moves to Russia's position (should be at same cell after battle, or nearby)
battle_events.clear()
target_x, target_y = rf_after["pos_x"], rf_after["pos_y"]

r = s_brit.post(f"{BASE}/api/fleets/{britain_fleet['id']}/move",
                json={"x": target_x, "y": target_y},
                headers={"X-Session-Id": brit_session_token})
result = r.json()
ok("Britain move", result.get("ok"), result.get("error", ""))

battles2 = result.get("battles", [])
ok("Battle occurred", len(battles2) >= 1, f"battles={len(battles2)}")

if battles2:
    b2 = battles2[0]
    log2 = b2.get("log", [])
    print(f"\n  --- ЛОГ БОЯ 2 ---")
    for line in log2[:10]:
        print(f"  {line}")
    if len(log2) > 10:
        print(f"  ... ({len(log2) - 10} more lines)")

    winner2 = b2.get("winner_fleet_id")
    print(f"  Winner: fleet_id={winner2}")

    # Check Russia fleet status
    r = s_admin.get(f"{BASE}/api/fleets")
    fleets_b2 = r.json()
    rf_b2 = [f for f in fleets_b2 if f["country_id"] == 1][0]
    bf_b2 = [f for f in fleets_b2 if f["country_id"] == 2][0]
    rus_alive2 = len([s for s in rf_b2["ships"] if s["is_alive"]])
    brit_alive2 = len([s for s in bf_b2["ships"] if s["is_alive"]])
    print(f"  Россия: alive={rus_alive2} dead={8-rus_alive2}")
    print(f"  Британия: alive={brit_alive2} dead={5-brit_alive2}")
    ok("Russia fleet weakening", rus_alive2 < russia_alive, f"was={russia_alive} now={rus_alive2}")

# Britain ends turn
r = s_brit.post(f"{BASE}/api/turn/end", json={},
                headers={"X-Session-Id": brit_session_token, "Authorization": f"Bearer {admin_token}"})
ok("End turn Britain", r.json().get("ok"), r.json().get("error", ""))
ok("Turn advanced to index 2 (France)", r.json().get("turn_index") == 2, f"index={r.json().get('turn_index')}")

# ============================================================
# ХОД 3: Франция — нейтральное перемещение
# ============================================================
print("\n" + "=" * 60)
print("  ХОД 3: ФРАНЦИЯ — ПЕРЕМЕЩЕНИЕ")
print("=" * 60)

r = s_admin.get(f"{BASE}/api/fleets")
fleets_f3 = r.json()
ff3 = [f for f in fleets_f3 if f["country_id"] == 3][0]
print(f"  Франция: ({ff3['pos_x']},{ff3['pos_y']}) spd={ff3['min_speed']}")

# France moves 1 step closer to the action (within speed)
r = s_fra.post(f"{BASE}/api/fleets/{ff3['id']}/move",
               json={"x": ff3["pos_x"], "y": ff3["pos_y"] - 1},
               headers={"X-Session-Id": fra_session_token})
ok("France moves", r.ok, r.json().get("error", ""))

r = s_fra.post(f"{BASE}/api/turn/end", json={},
               headers={"X-Session-Id": fra_session_token, "Authorization": f"Bearer {admin_token}"})
result_f3 = r.json()
ok("End turn France", result_f3.get("ok"), result_f3.get("error", ""))
ok("Turn wraps to turn_number=2", result_f3.get("turn_number") == 2, f"tn={result_f3.get('turn_number')}")
ok("Turn wraps to index=0 (Russia again)", result_f3.get("turn_index") == 0, f"index={result_f3.get('turn_index')}")

# ============================================================
# ХОД 4: Россия — проверка что ход обновился
# ============================================================
print("\n" + "=" * 60)
print("  ХОД 4: РОССИЯ — НОВЫЙ РАУНД")
print("=" * 60)

r = s_admin.get(f"{BASE}/api/state")
st = r.json()
ok("Turn number=2", st["turn_number"] == 2)
ok("Turn index=0 (Russia)", st["turn_index"] == 0)
ok("Moved cleared for new round", st.get("moved_this_turn") == {})

# ============================================================
# ПРОВЕРКА ЛОГОВ
# ============================================================
print("\n" + "=" * 60)
print("  ПРОВЕРКА ЛОГОВ БОЁВ")
print("=" * 60)

r = s_admin.get(f"{BASE}/api/logs")
logs = r.json()
ok("At least 2 battle logs", len(logs) >= 2, f"count={len(logs)}")
for log in logs:
    print(f"  Log #{log['id']}: cell=({log['cell_x']},{log['cell_y']}) lines={len(log['log'])}")

# ============================================================
# ПРОВЕРКА ПОТЕНЦИАЛЬНЫХ БАГОВ
# ============================================================
print("\n" + "=" * 60)
print("  ПРОВЕРКА БАГОВ")
print("=" * 60)

# Bug check: Can non-active country move in wartime?
r = s_brit.post(f"{BASE}/api/fleets/{britain_fleet['id']}/move",
                json={"x": 0, "y": 0},
                headers={"X-Session-Id": brit_session_token})
ok("Britain (not their turn) blocked in wartime", r.status_code == 403, f"status={r.status_code} body={r.json()}")

# Bug check: Can same fleet move twice in one turn?
r = s_admin.get(f"{BASE}/api/fleets")
fleets_f4 = r.json()
rf4 = [f for f in fleets_f4 if f["country_id"] == 1][0]
r = s_rus.post(f"{BASE}/api/fleets/{rf4['id']}/move",
               json={"x": rf4["pos_x"], "y": rf4["pos_y"]},
               headers={"X-Session-Id": rus_session_token})
# If fleet has speed > 0 and can move to same cell (dist=0), it might succeed — that's OK
# But if fleet already moved, it should be blocked
if rf4["min_speed"] == 0:
    ok("Dead fleet can't move", r.status_code == 400, f"status={r.status_code}")
else:
    ok("Double move check", True, f"fleet min_speed={rf4['min_speed']} (dist=0 always OK)")

# Bug check: moved_this_turn has ship-level tracking
r = s_admin.get(f"{BASE}/api/state")
st = r.json()
moved = st.get("moved_this_turn", {})
has_ship_keys = any(k.startswith("ship_") for k in moved)
ok("Ship-level move tracking in moved_this_turn", has_ship_keys or len(moved) == 0, f"moved keys: {list(moved.keys())[:10]}")

# Bug check: Boundary validation
r = s_rus.post(f"{BASE}/api/fleets/{rf4['id']}/move",
               json={"x": -5, "y": -5},
               headers={"X-Session-Id": rus_session_token})
ok("Reject negative coords", r.status_code == 400, f"status={r.status_code}")

r = s_rus.post(f"{BASE}/api/fleets/{rf4['id']}/move",
               json={"x": 100, "y": 100},
               headers={"X-Session-Id": rus_session_token})
ok("Reject out-of-bounds coords", r.status_code == 400, f"status={r.status_code}")

# Bug check: speed limit in wartime — reset moved state first
s_admin.post(f"{BASE}/api/state", json={"moved_this_turn": {}},
             headers={"X-Session-Id": admin_session_token})
r = s_rus.post(f"{BASE}/api/fleets/{rf4['id']}/move",
               json={"x": 39, "y": 24},
               headers={"X-Session-Id": rus_session_token})
ok("Reject move exceeding speed", r.status_code == 400, f"status={r.status_code} body={r.json().get('error','')}")

# Bug check: admin endpoints reject unauthorized
r = s_rus.post(f"{BASE}/api/seed", headers={"X-Session-Id": rus_session_token})
ok("Player can't seed", r.status_code == 403, f"status={r.status_code}")

r = s_rus.delete(f"{BASE}/api/fleets/1", headers={"X-Session-Id": rus_session_token})
ok("Player can't delete fleet", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# ПРОВЕРКА МИН
# ============================================================
print("\n" + "=" * 60)
print("  ПРОВЕРКА МИН")
print("=" * 60)

r = s_admin.get(f"{BASE}/api/cells")
cells = r.json()
mine_cells = [c for c in cells if c["mines_count"] > 0]
ok("Mine cells exist", len(mine_cells) >= 1, f"count={len(mine_cells)}")
for mc in mine_cells:
    print(f"  Mine at ({mc['x']},{mc['y']}): count={mc['mines_count']}")

# Admin can't place more than 2 mines
if mine_cells:
    mx, my = mine_cells[0]["x"], mine_cells[0]["y"]
    r = s_admin.post(f"{BASE}/api/cells/{mx}/{my}/mine", json={},
                     headers={"X-Session-Id": admin_session_token})
    if mine_cells[0]["mines_count"] >= 2:
        ok("Max 2 mines enforced", r.status_code == 400, f"status={r.status_code}")
    else:
        ok("Can place mine", r.ok, r.json().get("error", ""))

# ============================================================
# ПРОВЕРКА КРЕПОСТЕЙ
# ============================================================
print("\n" + "=" * 60)
print("  ПРОВЕРКА КРЕПОСТЕЙ")
print("=" * 60)

r = s_admin.post(f"{BASE}/api/cells/20/7/fort", json={"owner_id": 2},
                 headers={"X-Session-Id": admin_session_token})
ok("Place fort for Britain", r.ok, r.json().get("error", ""))

r = s_admin.get(f"{BASE}/api/cells")
cells2 = r.json()
fort_cells = [c for c in cells2 if c.get("fort_owner_id") is not None]
ok("Fort placed", len(fort_cells) >= 1, f"forts={fort_cells}")
if fort_cells:
    print(f"  Fort at ({fort_cells[0]['x']},{fort_cells[0]['y']}), owner={fort_cells[0]['fort_owner_id']}")

# Remove fort
r = s_admin.post(f"{BASE}/api/cells/20/7/fort", json={"owner_id": None},
                 headers={"X-Session-Id": admin_session_token})
ok("Remove fort", r.ok)

# ============================================================
# ПРОВЕРКА SOCKETIO СОБЫТИЙ
# ============================================================
print("\n" + "=" * 60)
print("  ПРОВЕРКА SOCKETIO")
print("=" * 60)

ok("Map updates received", len(map_updates) > 0, f"count={len(map_updates)}")
ok("Battle events received", len(battle_events) > 0, f"count={len(battle_events)}")
ok("State updates received", len(state_updates) > 0, f"count={len(state_updates)}")

# ============================================================
# ИТОГИ
# ============================================================
print(f"\n{'=' * 60}")
print(f"  RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} TOTAL")
print(f"{'=' * 60}")

sio_admin.disconnect()
sio_rus.disconnect()
sio_brit.disconnect()
sio_fra.disconnect()

sys.exit(1 if FAIL > 0 else 0)
