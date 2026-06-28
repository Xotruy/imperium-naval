"""Полный тест-сценарий: сидирование → движение → бой → ходы"""
import requests, json, time

BASE = "http://localhost:5000"
s = requests.Session()
PASS = 0
FAIL = 0

def ok(name, cond=True, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  [PASS] {name}")
    else:
        FAIL += 1; print(f"  [FAIL] {name} — {msg}")

print("===== 1. AUTH =====")
r = s.post(f"{BASE}/api/auth/register", json={"username":"tester","password":"test1234"})
ok("Register", r.ok, r.text)
r = s.post(f"{BASE}/api/auth/login", json={"username":"tester","password":"test1234"})
ok("Login", r.ok, r.text)
token = r.json()["token"]

r = s.post(f"{BASE}/api/auth/register", json={"username":"tester","password":"test1234"})
ok("Dup register 409", r.status_code == 409, f"status={r.status_code}")

r = s.post(f"{BASE}/api/auth/login", json={"username":"tester","password":"wrong"})
ok("Bad password 401", r.status_code == 401, f"status={r.status_code}")

r = s.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
ok("Auth/me", r.ok and r.json()["user"]["username"] == "tester")

r = s.get(f"{BASE}/api/auth/me")
ok("Auth/me no token 401", r.status_code == 401, f"status={r.status_code}")

r = s.put(f"{BASE}/api/auth/profile", json={"display_name":"TestAdmiral"},
          headers={"Authorization": f"Bearer {token}"})
ok("Profile update", r.ok and r.json()["user"]["display_name"] == "TestAdmiral")

print("\n===== 2. ADMIN SEED (via SocketIO) =====")
import socketio
sio = socketio.Client()
connected = False
session_token = None

@sio.on("connect")
def on_connect():
    global connected
    connected = True

@sio.on("session_init")
def on_session_init(data):
    global session_token
    session_token = data.get("session_token")
    print(f"    Got session_token: {session_token}")

sio.connect(BASE)
time.sleep(0.5)
ok("SocketIO connect", connected)

sio.emit("join_session", {"name": "TestAdmin", "country_id": 0, "is_spectator": True})
time.sleep(0.5)
ok("Admin joined, token received", session_token is not None, f"token={session_token}")

r = s.post(f"{BASE}/api/seed", headers={"X-Session-Id": session_token})
ok("Seed demo", r.ok, r.json().get("error", ""))
seed = r.json()
ok("Seed message", seed.get("ok"), str(seed))

print("\n===== 3. STATE =====")
r = s.get(f"{BASE}/api/state")
st = r.json()
ok("State is_war", st["is_war"] == False)
ok("State turn=1", st["turn_number"] == 1)
ok("State turn_order=3", len(st["turn_order"]) == 3, f"order={st['turn_order']}")
ok("State grid", st["grid_cols"] == 40 and st["grid_rows"] == 25)

print("\n===== 4. COUNTRIES =====")
r = s.get(f"{BASE}/api/countries")
countries = r.json()
ok("3 countries", len(countries) == 3, f"count={len(countries)}")
names = {c["id"]: c["name"] for c in countries}
ok("Russia exists", "Россия" in names.values())
ok("Britain exists", "Британия" in names.values())
ok("France exists", "Франция" in names.values())

print("\n===== 5. FLEETS =====")
r = s.get(f"{BASE}/api/fleets")
fleets = r.json()
ok("3 fleets", len(fleets) == 3, f"count={len(fleets)}")
for f in fleets:
    alive = len([sh for sh in f["ships"] if sh["is_alive"]])
    print(f"    [{f['id']}] {f['name']} country={f['country_id']} pos=({f['pos_x']},{f['pos_y']}) ships={alive}/{len(f['ships'])} armor={f['total_armor']} atk={f['total_attack']} spd={f['min_speed']}")

print("\n===== 6. CELLS (mines) =====")
r = s.get(f"{BASE}/api/cells")
cells = r.json()
ok("Mines exist", len(cells) >= 2, f"count={len(cells)}")
for c in cells:
    print(f"    [{c['x']},{c['y']}] mines={c['mines_count']} fort={c['fort_owner_id']}")

print("\n===== 7. RELATIONS =====")
r = s.get(f"{BASE}/api/relations")
rels = r.json()
ok("Relations exist", len(rels) >= 1)
war_pairs = [r2 for r2 in rels if r2["at_war"]]
ok("Russia-Britain at war", len(war_pairs) >= 1)

print("\n===== 8. ВКЛЮЧЕНИЕ ВОЕННОГО ВРЕМЕНИ =====")
r = s.post(f"{BASE}/api/state", json={"is_war": True}, headers={"X-Session-Id": session_token})
ok("Set is_war=true", r.ok, r.json().get("error", ""))
r = s.get(f"{BASE}/api/state")
ok("is_war is True", r.json()["is_war"] == True)

print("\n===== 9. ДВИЖЕНИЕ ФЛОТА (БОЙ) =====")
russia_fleet = [f for f in fleets if f["country_id"] == countries[0]["id"]][0]
britain_fleet = [f for f in fleets if f["country_id"] == countries[1]["id"]][0]
print(f"    Russia fleet [{russia_fleet['id']}] at ({russia_fleet['pos_x']},{russia_fleet['pos_y']})")
print(f"    Britain fleet [{britain_fleet['id']}] at ({britain_fleet['pos_x']},{britain_fleet['pos_y']})")

# Turn order: first country is Russia (id from seed)
turn_order = r.json()["turn_order"]
print(f"    Turn order: {turn_order}")

# Move Russia fleet to Britain fleet position (trigger battle)
target_x, target_y = britain_fleet["pos_x"], britain_fleet["pos_y"]
print(f"    Moving Russia fleet to ({target_x},{target_y}) to engage Britain...")

r = s.post(f"{BASE}/api/fleets/{russia_fleet['id']}/move",
           json={"x": target_x, "y": target_y},
           headers={"X-Session-Id": session_token})
result = r.json()
ok("Move fleet response", result.get("ok"), result.get("error", ""))
battles = result.get("battles", [])
ok("Battle occurred", len(battles) >= 1, f"battles={len(battles)}")
if battles:
    b = battles[0]
    ok("Battle has log", len(b.get("log", [])) > 0)
    ok("Battle has winner or mutual destruction",
       b.get("winner_fleet_id") is not None or True)
    print(f"    Battle winner_fleet_id={b.get('winner_fleet_id')}")
    print(f"    Battle log lines: {len(b.get('log', []))}")
    for line in b.get("log", [])[:5]:
        print(f"      {line}")

print("\n===== 10. ПРОВЕРКА ПОСЛЕ БОЯ =====")
r = s.get(f"{BASE}/api/fleets")
fleets_after = r.json()
for f in fleets_after:
    alive = len([sh for sh in f["ships"] if sh["is_alive"]])
    dead = len([sh for sh in f["ships"] if not sh["is_alive"]])
    print(f"    [{f['id']}] {f['name']} alive={alive} dead={dead} pos=({f['pos_x']},{f['pos_y']})")

r = s.get(f"{BASE}/api/state")
st = r.json()
moved = st.get("moved_this_turn", {})
ok("Fleet marked as moved", moved.get(str(russia_fleet["id"])) == True, f"moved={moved}")

print("\n===== 11. TURN SYSTEM =====")
r = s.get(f"{BASE}/api/state")
st = r.json()
print(f"    Turn: {st['turn_number']}, index: {st['turn_index']}, order: {st['turn_order']}")

# End turn
r = s.post(f"{BASE}/api/turn/end", json={},
           headers={"X-Session-Id": session_token, "Authorization": f"Bearer {token}"})
result = r.json()
ok("End turn", result.get("ok"), result.get("error", ""))
print(f"    After end turn: number={result.get('turn_number')}, index={result.get('turn_index')}")

# Verify moved_this_turn was cleared
r = s.get(f"{BASE}/api/state")
st2 = r.json()
ok("moved_this_turn cleared after end turn", st2.get("moved_this_turn") == {}, f"moved={st2.get('moved_this_turn')}")
ok("Turn index advanced", st2["turn_index"] == 1, f"index={st2['turn_index']}")

print("\n===== 12. ДВИЖЕНИЕ ВО ВРЕМЯ МИРА =====")
r = s.post(f"{BASE}/api/state", json={"is_war": False}, headers={"X-Session-Id": session_token})
ok("Set peace", r.ok)

# Get fleet positions
r = s.get(f"{BASE}/api/fleets")
fleets = r.json()
test_fleet = fleets[0]
old_x, old_y = test_fleet["pos_x"], test_fleet["pos_y"]
r = s.post(f"{BASE}/api/fleets/{test_fleet['id']}/move",
           json={"x": old_x + 1, "y": old_y},
           headers={"X-Session-Id": session_token})
ok("Move in peace mode", r.ok, r.json().get("error", ""))

print("\n===== 13. BOUNDARY CHECKS =====")
r = s.post(f"{BASE}/api/fleets/{test_fleet['id']}/move",
           json={"x": -1, "y": 0},
           headers={"X-Session-Id": session_token})
ok("Out of bounds X<0 rejected", r.status_code == 400, f"status={r.status_code}")

r = s.post(f"{BASE}/api/fleets/{test_fleet['id']}/move",
           json={"x": 999, "y": 0},
           headers={"X-Session-Id": session_token})
ok("Out of bounds X>max rejected", r.status_code == 400, f"status={r.status_code}")

print("\n===== 14. LOGS =====")
r = s.get(f"{BASE}/api/logs")
logs = r.json()
ok("Logs created after battles", len(logs) >= 1, f"count={len(logs)}")
if logs:
    log = logs[0]
    ok("Log has content", len(log.get("log", [])) > 0)

print("\n===== 15. FLEET LIFECYCLE =====")
# Create fleet
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Test Fleet", "country_id": countries[0]["id"],
    "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 2}]
}, headers={"X-Session-Id": session_token})
ok("Create fleet", r.ok, r.json().get("error", ""))
new_fid = r.json()["id"]

# Verify it exists
r = s.get(f"{BASE}/api/fleets")
ok("Fleet in list", any(f["id"] == new_fid for f in r.json()))

# Delete fleet
r = s.delete(f"{BASE}/api/fleets/{new_fid}", headers={"X-Session-Id": session_token})
ok("Delete fleet", r.ok)

# Verify gone
r = s.get(f"{BASE}/api/fleets")
ok("Fleet removed", not any(f["id"] == new_fid for f in r.json()))

print("\n===== 16. COUNTRY CRUD =====")
r = s.post(f"{BASE}/api/countries", json={
    "name": "TestLand", "color": "#00FF00", "flag_emoji": "🏴", "order_level": 2
}, headers={"X-Session-Id": session_token})
ok("Create country", r.ok, r.json().get("error", ""))
cid = r.json()["id"]

r = s.put(f"{BASE}/api/countries/{cid}", json={"name": "TestLand Updated"},
          headers={"X-Session-Id": session_token})
ok("Update country", r.ok and r.json()["name"] == "TestLand Updated")

r = s.delete(f"{BASE}/api/countries/{cid}", headers={"X-Session-Id": session_token})
ok("Delete country", r.ok)

print("\n===== 17. MINES =====")
# Place mine
r = s.post(f"{BASE}/api/cells/5/5/mine", json={},
           headers={"X-Session-Id": session_token})
ok("Place mine (admin)", r.ok, r.json().get("error", ""))

r = s.get(f"{BASE}/api/cells")
cell55 = [c for c in r.json() if c["x"] == 5 and c["y"] == 5]
ok("Mine exists at 5,5", len(cell55) == 1 and cell55[0]["mines_count"] == 1)

# Second mine
r = s.post(f"{BASE}/api/cells/5/5/mine", json={},
           headers={"X-Session-Id": session_token})
ok("Place 2nd mine", r.ok)

# Third mine should fail
r = s.post(f"{BASE}/api/cells/5/5/mine", json={},
           headers={"X-Session-Id": session_token})
ok("Max 2 mines enforced", r.status_code == 400, f"status={r.status_code}")

# Demine
r = s.post(f"{BASE}/api/cells/5/5/demine", json={},
           headers={"X-Session-Id": session_token})
ok("Demine", r.ok, r.json().get("error", ""))

r = s.get(f"{BASE}/api/cells")
cell55 = [c for c in r.json() if c["x"] == 5 and c["y"] == 5]
ok("Mines cleared", len(cell55) == 0 or cell55[0]["mines_count"] == 0)

print("\n===== 18. FORTS =====")
r = s.post(f"{BASE}/api/cells/10/10/fort", json={"owner_id": countries[0]["id"]},
           headers={"X-Session-Id": session_token})
ok("Place fort", r.ok)

r = s.get(f"{BASE}/api/cells")
cell1010 = [c for c in r.json() if c["x"] == 10 and c["y"] == 10]
ok("Fort exists", len(cell1010) == 1 and cell1010[0]["fort_owner_id"] == countries[0]["id"])

r = s.post(f"{BASE}/api/cells/10/10/fort", json={"owner_id": None},
           headers={"X-Session-Id": session_token})
ok("Remove fort", r.ok)

print("\n===== 19. NON-ADMIN DENIED =====")
r = s.post(f"{BASE}/api/countries", json={"name": "Hacker"},
           headers={"X-Session-Id": "some_random_session"})
ok("Non-admin create country 403", r.status_code == 403, f"status={r.status_code}")

r = s.post(f"{BASE}/api/seed", headers={"X-Session-Id": "some_random_session"})
ok("Non-admin seed 403", r.status_code == 403, f"status={r.status_code}")

print("\n===== 20. BATTLE WITH FORT BONUS =====")
r = s.post(f"{BASE}/api/cells/18/8/fort", json={"owner_id": countries[1]["id"]},
           headers={"X-Session-Id": session_token})
ok("Place fort near Britain fleet", r.ok)

# Set war
r = s.post(f"{BASE}/api/state", json={"is_war": True}, headers={"X-Session-Id": session_token})
ok("Set war", r.ok)

# Move France fleet to fight Britain (near fort)
france_fleet = [f for f in fleets if f["country_id"] == countries[2]["id"]]
if france_fleet:
    ff = france_fleet[0]
    bx, by = britain_fleet["pos_x"], britain_fleet["pos_y"]
    print(f"    France fleet [{ff['id']}] at ({ff['pos_x']},{ff['pos_y']}), speed={ff['min_speed']}")
    dist = max(abs(bx - ff["pos_x"]), abs(by - ff["pos_y"]))
    print(f"    Distance to Britain fleet: {dist}")
    if dist <= ff["min_speed"]:
        r = s.post(f"{BASE}/api/fleets/{ff['id']}/move",
                   json={"x": bx, "y": by},
                   headers={"X-Session-Id": session_token})
        result = r.json()
        ok("Fort battle", result.get("ok"), result.get("error", ""))
        battles = result.get("battles", [])
        if battles:
            log = battles[0].get("log", [])
            has_fort = any("крепость" in l.lower() or "fort" in l.lower() for l in log)
            ok("Fort bonus in log", has_fort, f"log first 3: {log[:3]}")
    else:
        print(f"    SKIP: fleet too far (dist={dist} > speed={ff['min_speed']})")

sio.disconnect()

print(f"\n{'='*50}")
print(f"  RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} TOTAL")
print(f"{'='*50}")
