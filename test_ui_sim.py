"""Тест через API — симуляция действий из UI: создание стран и флотов"""
import requests, json, time

BASE = "http://localhost:5000"
PASS = 0
FAIL = 0

def ok(name, cond=True, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  [PASS] {name}")
    else:
        FAIL += 1; print(f"  [FAIL] {name} — {msg}")

print("=" * 60)
print("  UI SIMULATION: страны и флоты через интерфейс")
print("=" * 60)

# ============================================================
# 1. AUTH — как из UI
# ============================================================
print("\n===== 1. LOGIN как из UI =====")
s = requests.Session()

# Register
r = s.post(f"{BASE}/api/auth/register", json={
    "username": "ui_tester", "password": "pass1234", "display_name": "Тестер UI"
})
ok("Register via API", r.ok, r.text)
token = r.json().get("token")

# Verify token
r = s.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
ok("Verify token", r.ok and r.json().get("user", {}).get("username") == "ui_tester")

# ============================================================
# 2. ADMIN SESSION — join_as_admin
# ============================================================
print("\n===== 2. ADMIN SESSION (SocketIO) =====")
import socketio

sio = socketio.Client()
admin_token = None

@sio.on("session_init")
def on_init(data):
    global admin_token
    admin_token = data.get("session_token")

map_events = []
@sio.on("map_update")
def on_map(data):
    map_events.append(data)

sio.connect(BASE)
time.sleep(0.3)
ok("SocketIO connected", admin_token is not None)

sio.emit("join_session", {"name": "Admin", "country_id": 0, "is_spectator": True})
time.sleep(0.3)
ok("Admin joined", admin_token is not None)

# ============================================================
# 3. ПРОВЕРКА: UI api() добавляет X-Session-Id + Bearer
# ============================================================
print("\n===== 3. API HEADER SIMULATION =====")

# Simulate what the JS api() function does:
# opts.headers["X-Session-Id"] = S.sessionId;
# opts.headers["Authorization"] = `Bearer ${S.authToken}`;
headers = {
    "Content-Type": "application/json",
    "X-Session-Id": admin_token,
    "Authorization": f"Bearer {token}"
}

r = s.get(f"{BASE}/api/state", headers=headers)
ok("State with both headers", r.ok and "is_war" in r.json())

r = s.get(f"{BASE}/api/countries", headers=headers)
ok("Countries with both headers", r.ok)

# ============================================================
# 4. ADD COUNTRY — как через форму "Добавить" в Admin Panel
# ============================================================
print("\n===== 4. ADD COUNTRY (UI Form) =====")

# The UI sends: { name, color, flag_emoji: emoji, order_level: order }
countries_to_create = [
    {"name": "Российская Империя", "color": "#2196F3", "flag_emoji": "🇷🇺", "order_level": 4},
    {"name": "Британская Империя", "color": "#F44336", "flag_emoji": "🇬🇧", "order_level": 3},
    {"name": "Французская Республика", "color": "#4CAF50", "flag_emoji": "🇫🇷", "order_level": 2},
]

created = []
for cd in countries_to_create:
    r = s.post(f"{BASE}/api/countries", json=cd, headers=headers)
    ok(f"Add country '{cd['name']}'", r.ok, r.json().get("error", ""))
    if r.ok:
        created.append(r.json())

ok("3 countries created", len(created) == 3, f"count={len(created)}")

# Verify UI behavior: after addCountry(), UI calls renderAdminCountries() and renderRelationMatrix()
# These just re-fetch the data
r = s.get(f"{BASE}/api/countries", headers=headers)
ok("Countries visible after add", len(r.json()) == 3, f"count={len(r.json())}")

# ============================================================
# 5. RELATION MATRIX — как через UI toggle
# ============================================================
print("\n===== 5. RELATION TOGGLE (UI) =====")

c1, c2, c3 = created

# UI calls: toggleRelation(aId, bId, !isWar)
# Which sends: { country_a_id: aId, country_b_id: bId, at_war: true }
r = s.post(f"{BASE}/api/relations", json={
    "country_a_id": c1["id"], "country_b_id": c2["id"], "at_war": True
}, headers=headers)
ok("Toggle war: Russia vs Britain", r.ok)

r = s.post(f"{BASE}/api/relations", json={
    "country_a_id": c1["id"], "country_b_id": c3["id"], "at_war": True
}, headers=headers)
ok("Toggle war: Russia vs France", r.ok)

r = s.get(f"{BASE}/api/relations", headers=headers)
rels = r.json()
ok("2 war relations", len([r2 for r2 in rels if r2["at_war"]]) == 2)

# ============================================================
# 6. REBUILD TURN ORDER — как через UI
# ============================================================
print("\n===== 6. REBUILD TURN ORDER (UI) =====")

# UI calls: rebuildTurnOrder()
# Which sends: { turn_order: [c.id for c in countries], turn_index: 0, turn_number: S.turnNumber, moved_this_turn: {} }
r = s.post(f"{BASE}/api/state", json={
    "turn_order": [c1["id"], c2["id"], c3["id"]],
    "turn_index": 0,
    "turn_number": 1,
    "moved_this_turn": {}
}, headers=headers)
ok("Rebuild turn order", r.ok)

r = s.get(f"{BASE}/api/state", headers=headers)
st = r.json()
ok("Turn order has 3 entries", len(st["turn_order"]) == 3)
ok("Turn index=0", st["turn_index"] == 0)

# ============================================================
# 7. ADD FLEET — как через форму "Новый флот"
# ============================================================
print("\n===== 7. ADD FLEET (UI Form) =====")

# The UI sends: { name, country_id, pos_x, pos_y, ships: [{ ship_type, count, armor }] }
fleet_data = {
    "name": "Балтийский флот",
    "country_id": c1["id"],
    "pos_x": 10,
    "pos_y": 10,
    "ships": [
        {"ship_type": "Дредноут", "count": 1, "armor": 1000},
        {"ship_type": "Линейный крейсер", "count": 2, "armor": 500},
        {"ship_type": "Эсминец", "count": 2, "armor": 300},
    ]
}
r = s.post(f"{BASE}/api/fleets", json=fleet_data, headers=headers)
ok("Create fleet via UI", r.ok, r.json().get("error", ""))
fleet1 = r.json() if r.ok else None

if fleet1:
    ok("Fleet has id", "id" in fleet1)
    ok("Fleet name", fleet1["name"] == "Балтийский флот")
    ok("Fleet country_id", fleet1["country_id"] == c1["id"])
    ok("Fleet position", fleet1["pos_x"] == 10 and fleet1["pos_y"] == 10)
    ok("Fleet has ships", len(fleet1["ships"]) == 5)
    ok("Fleet armor", fleet1["total_armor"] > 0)
    ok("Fleet attack", fleet1["total_attack"] > 0)
    print(f"  Fleet: [{fleet1['id']}] {fleet1['name']} armor={fleet1['total_armor']} atk={fleet1['total_attack']} spd={fleet1['min_speed']}")

# Add second fleet
fleet_data2 = {
    "name": "Гранд Флит",
    "country_id": c2["id"],
    "pos_x": 12,
    "pos_y": 10,
    "ships": [
        {"ship_type": "Дредноут", "count": 2, "armor": 1000},
        {"ship_type": "Канонерка", "count": 3, "armor": 200},
    ]
}
r = s.post(f"{BASE}/api/fleets", json=fleet_data2, headers=headers)
ok("Create Britain fleet", r.ok, r.json().get("error", ""))
fleet2 = r.json() if r.ok else None

# ============================================================
# 8. ПРОВЕРКА ОШИБОК UI — что показывается при ошибках
# ============================================================
print("\n===== 8. UI ERROR HANDLING =====")

# What happens when addCountry sends empty name?
r = s.post(f"{BASE}/api/countries", json={"name": "", "color": "#000", "flag_emoji": "🏴", "order_level": 1}, headers=headers)
ok("Empty country name returns 400", r.status_code == 400, f"status={r.status_code}")
err = r.json()
ok("Error has message", "error" in err, f"response={err}")

# What happens when createFleet sends invalid country?
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Bad Fleet", "country_id": 999, "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers=headers)
ok("Invalid country_id returns error", r.status_code in [400, 404], f"status={r.status_code}")

# What happens when createFleet sends unknown ship type?
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Bad Ships", "country_id": c1["id"], "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Несуществующий", "count": 1}]
}, headers=headers)
ok("Unknown ship type returns 400", r.status_code == 400, f"status={r.status_code}")

# What happens when createFleet sends out-of-bounds position?
r = s.post(f"{BASE}/api/fleets", json={
    "name": "OOB Fleet", "country_id": c1["id"], "pos_x": 999, "pos_y": 999,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers=headers)
ok("Out-of-bounds position returns 400", r.status_code == 400, f"status={r.status_code}")

# What happens when addCountry sends duplicate name?
r = s.post(f"{BASE}/api/countries", json={"name": "Российская Империя", "color": "#000", "order_level": 1}, headers=headers)
ok("Duplicate country name returns 400", r.status_code == 400, f"status={r.status_code}")

# ============================================================
# 9. VERIFY MAP UPDATE via SocketIO
# ============================================================
print("\n===== 9. MAP UPDATE via SocketIO =====")

map_events.clear()
# Create a new country to trigger map_update
r = s.post(f"{BASE}/api/countries", json={
    "name": "Fourth Nation", "color": "#9C27B0", "flag_emoji": "🏴", "order_level": 1
}, headers=headers)
ok("Create 4th country", r.ok, r.json().get("error", ""))
time.sleep(0.3)
ok("map_update emitted", len(map_events) > 0, f"events={len(map_events)}")

if map_events:
    last_map = map_events[-1]
    ok("map_update has fleets", "fleets" in last_map)
    ok("map_update has cells", "cells" in last_map)

# ============================================================
# 10. DELETE COUNTRY — как через UI
# ============================================================
print("\n===== 10. DELETE COUNTRY (UI) =====")

# Create temp country
r = s.post(f"{BASE}/api/countries", json={"name": "ToDelete", "color": "#000", "order_level": 1}, headers=headers)
ok("Create temp country", r.ok)
temp_id = r.json()["id"]

# Delete it (UI calls: deleteCountry(id) -> api(`/api/countries/${id}`, "DELETE"))
r = s.delete(f"{BASE}/api/countries/{temp_id}", headers=headers)
ok("Delete country", r.ok)

r = s.get(f"{BASE}/api/countries", headers=headers)
ok("Country gone from list", not any(c["id"] == temp_id for c in r.json()))

# ============================================================
# 11. DELETE FLEET — как через UI
# ============================================================
print("\n===== 11. DELETE FLEET (UI) =====")

# Create fleet to delete
r = s.post(f"{BASE}/api/fleets", json={
    "name": "ToDelete Fleet", "country_id": c3["id"], "pos_x": 20, "pos_y": 20,
    "ships": [{"ship_type": "Конвой", "count": 2}]
}, headers=headers)
ok("Create fleet to delete", r.ok)
del_fid = r.json()["id"]

# Delete (UI calls: deleteFleetConfirm(fid) -> api(`/api/fleets/${fid}`, "DELETE"))
r = s.delete(f"{BASE}/api/fleets/{del_fid}", headers=headers)
ok("Delete fleet", r.ok)

r = s.get(f"{BASE}/api/fleets", headers=headers)
ok("Fleet gone from list", not any(f["id"] == del_fid for f in r.json()))

# ============================================================
# 12. DELETE SHIP — как через UI
# ============================================================
print("\n===== 12. DELETE SHIP (UI) =====")

if fleet1:
    r = s.get(f"{BASE}/api/fleets", headers=headers)
    f_data = [f for f in r.json() if f["id"] == fleet1["id"]][0]
    ship_count_before = len(f_data["ships"])
    
    sid = f_data["ships"][0]["id"]
    # UI calls: deleteShipConfirm(sid, fid) -> api(`/api/ships/${sid}`, "DELETE")
    r = s.delete(f"{BASE}/api/ships/{sid}", headers=headers)
    ok("Delete ship", r.ok)
    
    r = s.get(f"{BASE}/api/fleets", headers=headers)
    f_after = [f for f in r.json() if f["id"] == fleet1["id"]][0]
    ok("Ship count decreased", len(f_after["ships"]) == ship_count_before - 1)

# ============================================================
# 13. FULL CYCLE: seed → battle → verify
# ============================================================
print("\n===== 13. FULL CYCLE via UI =====")

# Load demo data (UI calls: seedDemo() -> api("/api/seed", "POST"))
r = s.post(f"{BASE}/api/seed", headers=headers)
ok("Seed demo", r.ok, r.json().get("error", ""))

# Verify countries
r = s.get(f"{BASE}/api/countries", headers=headers)
countries = r.json()
ok("Demo has 3 countries", len(countries) == 3, f"count={len(countries)}")

# Verify fleets
r = s.get(f"{BASE}/api/fleets", headers=headers)
fleets = r.json()
ok("Demo has 3 fleets", len(fleets) == 3, f"count={len(fleets)}")

# Verify state
r = s.get(f"{BASE}/api/state", headers=headers)
st = r.json()
ok("Demo state: turn=1", st["turn_number"] == 1)
ok("Demo state: is_war=False", st["is_war"] == False)

# Verify relations
r = s.get(f"{BASE}/api/relations", headers=headers)
rels = r.json()
ok("Demo has relations", len(rels) >= 1)

# ============================================================
# 14. ADMIN PANEL: toggle war, end turn
# ============================================================
print("\n===== 14. ADMIN ACTIONS (UI) =====")

# Toggle war (UI calls: toggleWar(true) -> api("/api/state", "POST", { is_war: true }))
r = s.post(f"{BASE}/api/state", json={"is_war": True}, headers=headers)
ok("Toggle war ON", r.ok)

r = s.get(f"{BASE}/api/state", headers=headers)
ok("is_war=True confirmed", r.json()["is_war"] == True)

# End turn (UI calls: endTurn() -> api("/api/turn/end", "POST"))
r = s.post(f"{BASE}/api/turn/end", json={}, headers=headers)
ok("End turn", r.ok, r.json().get("error", ""))

r = s.get(f"{BASE}/api/state", headers=headers)
ok("Turn advanced", r.json()["turn_index"] == 1, f"index={r.json()['turn_index']}")

# Toggle war off
r = s.post(f"{BASE}/api/state", json={"is_war": False}, headers=headers)
ok("Toggle war OFF", r.ok)

# ============================================================
# 15. PLAYER JOIN FLOW — register → pick country → join
# ============================================================
print("\n===== 15. PLAYER JOIN FLOW =====")

# Register new player
s2 = requests.Session()
r = s2.post(f"{BASE}/api/auth/register", json={"username": "player1", "password": "pass1234"})
ok("Player register", r.ok)
player_token = r.json().get("token")

# Pick country and join via SocketIO
sio2 = socketio.Client()
player_session = None

@sio2.on("session_init")
def on_p_init(data):
    global player_session
    player_session = data.get("session_token")

sio2.connect(BASE)
time.sleep(0.3)

# Join with country_id (UI calls: joinGame() -> socket.emit("join_session", { name, country_id, ... }))
sio2.emit("join_session", {"name": "Player1", "country_id": 1, "is_spectator": False, "token": player_token})
time.sleep(0.3)
ok("Player joined with country", player_session is not None)

# Verify player can see fleets
r = s2.get(f"{BASE}/api/fleets")
ok("Player sees fleets", len(r.json()) > 0)

# Verify player can see state
r = s2.get(f"{BASE}/api/state")
ok("Player sees state", r.ok)

# ============================================================
# 16. FLEET COUNTRY SELECT — verify country dropdown works
# ============================================================
print("\n===== 16. COUNTRY DROPDOWN DATA =====")

# UI loadAddFleetPanel() calls: S.countries = await api("/api/countries")
r = s.get(f"{BASE}/api/countries", headers=headers)
countries_for_fleet = r.json()
ok("Country list for fleet dropdown", len(countries_for_fleet) >= 3)

for c in countries_for_fleet:
    ok(f"Country {c['name']} has id/color/emoji",
       all(k in c for k in ["id", "color", "flag_emoji"]),
       f"keys={list(c.keys())}")

# ============================================================
# 17. SHIP TYPES DATA — verify buildShipFormRows() data
# ============================================================
print("\n===== 17. SHIP TYPES DATA =====")

# UI buildShipFormRows() uses hardcoded stats, but server also provides:
r = s.get(f"{BASE}/api/ship_types", headers=headers)
ok("Ship types endpoint", r.ok)
data = r.json()
ok("Has stats", "stats" in data)
ok("Has limits", "limits" in data)
ok("5 ship types", len(data["stats"]) == 5, f"types={list(data['stats'].keys())}")

# ============================================================
# 18. EDGE CASE: non-admin can't create country/fleet
# ============================================================
print("\n===== 18. NON-ADMIN RESTRICTIONS =====")

# Player without admin session tries to create country
player_headers = {"Content-Type": "application/json", "X-Session-Id": player_session}
r = s2.post(f"{BASE}/api/countries", json={"name": "HackerLand", "color": "#000", "order_level": 1}, headers=player_headers)
ok("Non-admin create country 403", r.status_code == 403, f"status={r.status_code}")

r = s2.post(f"{BASE}/api/fleets", json={
    "name": "Hacker Fleet", "country_id": 1, "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers=player_headers)
ok("Non-admin create fleet 403", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'=' * 60}")
print(f"  RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} TOTAL")
print(f"{'=' * 60}")

sio.disconnect()
sio2.disconnect()
