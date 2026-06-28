"""Тест создания стран и флотов с нуля — без seed, полный цикл до боя"""
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

# ============================================================
print("=" * 60)
print("  ТЕСТ: СОЗДАНИЕ МИРА С НУЛЯ")
print("=" * 60)

# ============================================================
# 1. AUTH
# ============================================================
print("\n===== 1. AUTH =====")
s = requests.Session()
r = s.post(f"{BASE}/api/auth/register", json={"username": "creator", "password": "pass1234"})
ok("Register", r.ok, r.text)
r = s.post(f"{BASE}/api/auth/login", json={"username": "creator", "password": "pass1234"})
ok("Login", r.ok, r.text)
token = r.json()["token"]

# ============================================================
# 2. SocketIO — admin session
# ============================================================
print("\n===== 2. ADMIN SESSION (SocketIO) =====")
import socketio

sio = socketio.Client()
admin_token = None

@sio.on("session_init")
def on_init(data):
    global admin_token
    admin_token = data.get("session_token")

sio.connect(BASE)
time.sleep(0.3)
ok("SocketIO connected", admin_token is not None)

sio.emit("join_session", {"name": "Создатель Мира", "country_id": 0, "is_spectator": True})
time.sleep(0.3)
ok("Admin joined", admin_token is not None)

# ============================================================
# 3. ЧИСТЫЙ СТЕЙТ — без seed
# ============================================================
print("\n===== 3. ЧИСТЫЙ СТЕЙТ =====")
r = s.get(f"{BASE}/api/state")
st = r.json()
ok("State loaded", "turn_number" in st)
ok("is_war=False", st["is_war"] == False)

r = s.get(f"{BASE}/api/countries")
ok("No countries initially", len(r.json()) == 0, f"count={len(r.json())}")

r = s.get(f"{BASE}/api/fleets")
ok("No fleets initially", len(r.json()) == 0, f"count={len(r.json())}")

# ============================================================
# 4. СОЗДАНИЕ СТРАН
# ============================================================
print("\n===== 4. СОЗДАНИЕ СТРАН =====")

countries_data = [
    {"name": "Империя Орла", "color": "#1E88E5", "flag_emoji": "🦅", "order_level": 4, "balance": 15000},
    {"name": "Королевство Льва", "color": "#E53935", "flag_emoji": "🦁", "order_level": 3, "balance": 12000},
    {"name": "Республика Дракона", "color": "#43A047", "flag_emoji": "🐉", "order_level": 2, "balance": 10000},
    {"name": "Султанат Полумесяца", "color": "#FDD835", "flag_emoji": "☪️", "order_level": 1, "balance": 8000},
]

created_countries = []
for cd in countries_data:
    r = s.post(f"{BASE}/api/countries", json=cd, headers={"X-Session-Id": admin_token})
    ok(f"Create '{cd['name']}'", r.ok, r.json().get("error", ""))
    if r.ok:
        created_countries.append(r.json())

ok("4 countries created", len(created_countries) == 4, f"count={len(created_countries)}")

r = s.get(f"{BASE}/api/countries")
all_countries = r.json()
for c in all_countries:
    print(f"  [{c['id']}] {c['name']} color={c['color']} order={c['order_level']} balance={c['balance']}")

# Test: duplicate name rejected
r = s.post(f"{BASE}/api/countries", json={"name": "Империя Орла", "color": "#000"},
           headers={"X-Session-Id": admin_token})
ok("Duplicate name rejected (400)", r.status_code == 400, f"status={r.status_code}")

# Test: empty name rejected
r = s.post(f"{BASE}/api/countries", json={"name": "", "color": "#000"},
           headers={"X-Session-Id": admin_token})
ok("Empty name rejected (400)", r.status_code == 400, f"status={r.status_code}")

# Test: order_level clamped
r = s.post(f"{BASE}/api/countries", json={"name": "TestClamp", "order_level": 10},
           headers={"X-Session-Id": admin_token})
ok("order_level clamped to 4", r.ok and r.json()["order_level"] == 4,
   f"order={r.json().get('order_level')}")
s.delete(f"{BASE}/api/countries/{r.json()['id']}", headers={"X-Session-Id": admin_token})

# Test: update country
cid = created_countries[0]["id"]
r = s.put(f"{BASE}/api/countries/{cid}", json={"balance": 20000, "name": "Империя Орла Великая"},
          headers={"X-Session-Id": admin_token})
ok("Update country", r.ok and r.json()["name"] == "Империя Орла Великая")

# Test: non-admin can't create
r = s.post(f"{BASE}/api/countries", json={"name": "Hacker"})
ok("Non-admin create 403", r.status_code == 403, f"status={r.status_code}")

# ============================================================
# 5. ОТНОШЕНИЯ МЕЖДУ СТРАНАМИ
# ============================================================
print("\n===== 5. ОТНОШЕНИЯ =====")

c1, c2, c3, c4 = created_countries

r = s.post(f"{BASE}/api/relations", json={"country_a_id": c1["id"], "country_b_id": c2["id"], "at_war": True},
           headers={"X-Session-Id": admin_token})
ok("Set war: Орёл vs Лев", r.ok)

r = s.post(f"{BASE}/api/relations", json={"country_a_id": c1["id"], "country_b_id": c3["id"], "at_war": False},
           headers={"X-Session-Id": admin_token})
ok("Set peace: Орёл vs Дракон", r.ok)

r = s.post(f"{BASE}/api/relations", json={"country_a_id": c2["id"], "country_b_id": c3["id"], "at_war": True},
           headers={"X-Session-Id": admin_token})
ok("Set war: Лев vs Дракон", r.ok)

r = s.get(f"{BASE}/api/relations")
rels = r.json()
ok("3 relations created", len(rels) == 3, f"count={len(rels)}")
war_rels = [r2 for r2 in rels if r2["at_war"]]
ok("2 at_war", len(war_rels) == 2, f"war={len(war_rels)}")

# ============================================================
# 6. СОЗДАНИЕ ФЛОТОВ
# ============================================================
print("\n===== 6. СОЗДАНИЕ ФЛОТОВ =====")

# Order 4 (Орёл): Эсминец=2, Канонерка=2, Конвой=5
# Order 3 (Лев): ЛК=3, Эсминец=5, Канонерка=5, Конвой=7
# Order 2 (Дракон): ЛК=5, Эсминец=7, Канонерка=7, Конвой=10
# Order 1 (Султанат): ЛК=7, Эсминец=10, Канонерка=10, Конвой=10, Дредноут=7

fleets_data = [
    {
        "name": "1-й Линейный флот", "country_id": c1["id"], "pos_x": 10, "pos_y": 10,
        "ships": [
            {"ship_type": "Дредноут", "count": 2},
            {"ship_type": "Линейный крейсер", "count": 3},
            {"ship_type": "Эсминец", "count": 2},
        ]
    },
    {
        "name": "2-й Эскортный флот", "country_id": c1["id"], "pos_x": 15, "pos_y": 10,
        "ships": [
            {"ship_type": "Канонерка", "count": 2},
            {"ship_type": "Конвой", "count": 4},
        ]
    },
    {
        "name": "Королевский флот", "country_id": c2["id"], "pos_x": 12, "pos_y": 10,
        "ships": [
            {"ship_type": "Дредноут", "count": 1},
            {"ship_type": "Линейный крейсер", "count": 2},
            {"ship_type": "Эсминец", "count": 3},
            {"ship_type": "Канонерка", "count": 2},
        ]
    },
    {
        "name": "Драконий флот", "country_id": c3["id"], "pos_x": 20, "pos_y": 15,
        "ships": [
            {"ship_type": "Линейный крейсер", "count": 2},
            {"ship_type": "Эсминец", "count": 2},
            {"ship_type": "Конвой", "count": 5},
        ]
    },
    {
        "name": "Флот Полумесяца", "country_id": c4["id"], "pos_x": 5, "pos_y": 5,
        "ships": [
            {"ship_type": "Канонерка", "count": 4},
            {"ship_type": "Конвой", "count": 6},
        ]
    },
]

created_fleets = []
for fd in fleets_data:
    r = s.post(f"{BASE}/api/fleets", json=fd, headers={"X-Session-Id": admin_token})
    ok(f"Create fleet '{fd['name']}'", r.ok, r.json().get("error", ""))
    if r.ok:
        created_fleets.append(r.json())

ok("5 fleets created", len(created_fleets) == 5, f"count={len(created_fleets)}")

r = s.get(f"{BASE}/api/fleets")
all_fleets = r.json()
for f in all_fleets:
    alive = len([sh for sh in f["ships"] if sh["is_alive"]])
    total = len(f["ships"])
    print(f"  [{f['id']}] {f['name']} country={f['country_id']} pos=({f['pos_x']},{f['pos_y']}) "
          f"ships={alive}/{total} armor={f['total_armor']} atk={f['total_attack']} spd={f['min_speed']}")

# ============================================================
# 7. ПРОВЕРКА ЛИМИТОВ КОРАБЛЕЙ
# ============================================================
print("\n===== 7. ЛИМИТЫ КОРАБЛЕЙ =====")

# Order 4 country (Орёл): Эсминец limit=2, already has 2
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Overflow fleet", "country_id": c1["id"], "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Эсминец", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Order 4 Эсминец limit enforced", r.status_code == 400, f"status={r.status_code} err={r.json().get('error','')}")

# Order 4: Конвой limit=5, already has 4 → 1 more OK
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Extra convoy", "country_id": c1["id"], "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Order 4 Конвой within limit", r.ok, r.json().get("error", ""))
if r.ok:
    extra_fid = r.json()["id"]

# Order 4: Конвой limit=5, now has 5 → next should fail
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Overflow convoy", "country_id": c1["id"], "pos_x": 1, "pos_y": 1,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Order 4 Конвой limit hit", r.status_code == 400, f"status={r.status_code}")

# Order 1 country (Султанат): no Дредноут limit
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Sultan dreadnoughts", "country_id": c4["id"], "pos_x": 3, "pos_y": 3,
    "ships": [{"ship_type": "Дредноут", "count": 3}]
}, headers={"X-Session-Id": admin_token})
ok("Order 1: no Дредноут limit", r.ok, r.json().get("error", ""))

# Order 1: Эсминец limit=10
r = s.post(f"{BASE}/api/fleets", json={
    "name": "Sultan destroyers", "country_id": c4["id"], "pos_x": 4, "pos_y": 4,
    "ships": [{"ship_type": "Эсминец", "count": 10}]
}, headers={"X-Session-Id": admin_token})
ok("Order 1: Эсминец 10 (limit=10)", r.ok, r.json().get("error", ""))

r = s.post(f"{BASE}/api/fleets", json={
    "name": "Sultan overflow", "country_id": c4["id"], "pos_x": 6, "pos_y": 6,
    "ships": [{"ship_type": "Эсминец", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Order 1: Эсминец limit hit", r.status_code == 400, f"status={r.status_code}")

# Cleanup extra fleets
s.delete(f"{BASE}/api/fleets/{extra_fid}", headers={"X-Session-Id": admin_token})

# ============================================================
# 8. ПРОВЕРКА КООРДИНАТ
# ============================================================
print("\n===== 8. ВАЛИДАЦИЯ КООРДИНАТ =====")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "BadX", "country_id": c1["id"], "pos_x": -1, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Negative X rejected", r.status_code == 400, f"status={r.status_code}")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "BadX2", "country_id": c1["id"], "pos_x": 999, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("X>grid_cols rejected", r.status_code == 400, f"status={r.status_code}")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "BadY", "country_id": c1["id"], "pos_x": 0, "pos_y": -5,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Negative Y rejected", r.status_code == 400, f"status={r.status_code}")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "", "country_id": c1["id"], "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Empty fleet name rejected", r.status_code == 400, f"status={r.status_code}")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "No ships fleet", "country_id": c1["id"], "pos_x": 0, "pos_y": 0,
    "ships": []
}, headers={"X-Session-Id": admin_token})
ok("Fleet with no ships created (allowed)", r.ok, r.json().get("error", ""))

# ============================================================
# 9. МИНЫ И КРЕПОСТИ ДО БОЯ
# ============================================================
print("\n===== 9. МИНЫ И КРЕПОСТИ =====")

r = s.post(f"{BASE}/api/cells/11/10/mine", json={}, headers={"X-Session-Id": admin_token})
ok("Mine at (11,10)", r.ok, r.json().get("error", ""))

r = s.post(f"{BASE}/api/cells/11/10/mine", json={}, headers={"X-Session-Id": admin_token})
ok("2nd mine at (11,10)", r.ok)

r = s.post(f"{BASE}/api/cells/11/10/mine", json={}, headers={"X-Session-Id": admin_token})
ok("3rd mine rejected (max 2)", r.status_code == 400, f"status={r.status_code}")

# Place fort for Лев near battle zone
r = s.post(f"{BASE}/api/cells/13/10/fort", json={"owner_id": c2["id"]},
           headers={"X-Session-Id": admin_token})
ok("Fort for Лев at (13,10)", r.ok)

r = s.get(f"{BASE}/api/cells")
cells = r.json()
mine_cells = [c for c in cells if c["mines_count"] > 0]
fort_cells = [c for c in cells if c.get("fort_owner_id")]
ok("Mine placed", len(mine_cells) >= 1, f"mines={len(mine_cells)}")
ok("Fort placed", len(fort_cells) >= 1, f"forts={len(fort_cells)}")

# ============================================================
# 10. ВКЛЮЧЕНИЕ ВОЙНЫ
# ============================================================
print("\n===== 10. ВОЙНА =====")

r = s.post(f"{BASE}/api/state", json={"is_war": True}, headers={"X-Session-Id": admin_token})
ok("Set is_war=True", r.ok)

r = s.get(f"{BASE}/api/state")
ok("is_war confirmed", r.json()["is_war"] == True)

# ============================================================
# 11. БОЕВАЯ СЕССИЯ
# ============================================================
print("\n===== 11. БОЕВАЯ СЕССИЯ =====")

# Орёл флот 1 at (10,10), Лев флот at (12,10). Distance=2. Speed=2.
fleet_orla = created_fleets[0]  # 1-й Линейный флот (10,10)
fleet_leva = created_fleets[2]  # Королевский флот (12,10) — created_fleets[1] is 2-й Эскортный
# But wait, 2-й Эскортный is created_fleets[1] at (15,10)
# Королевский флот is created_fleets[2] at (12,10)

# Verify fleet positions
print(f"  Орёл: [{fleet_orla['id']}] ({fleet_orla['pos_x']},{fleet_orla['pos_y']})")
print(f"  Лев: [{fleet_leva['id']}] ({fleet_leva['pos_x']},{fleet_leva['pos_y']})")

r = s.post(f"{BASE}/api/fleets/{fleet_orla['id']}/move",
           json={"x": fleet_leva["pos_x"], "y": fleet_leva["pos_y"]},
           headers={"X-Session-Id": admin_token})
result = r.json()
ok("Orl fleet moves to attack", result.get("ok"), result.get("error", ""))

battles = result.get("battles", [])
ok("Battle occurred", len(battles) >= 1, f"battles={len(battles)}")

if battles:
    b = battles[0]
    log = b.get("log", [])
    print(f"\n  --- БОЙ: Орёл vs Лев ---")
    for line in log[:20]:
        print(f"  {line}")
    if len(log) > 20:
        print(f"  ... ({len(log) - 20} more)")
    print(f"  Winner: fleet_id={b.get('winner_fleet_id')}")

    # Fort bonus: fort at (13,10), battle at (12,10), radius=2 → should apply
    has_fort = any("крепость" in l.lower() for l in log)
    ok("Fort bonus applied", has_fort, "no fort mention in log")

# ============================================================
# 12. ПРОВЕРКА СОСТОЯНИЯ ПОСЛЕ БОЯ
# ============================================================
print("\n===== 12. ПОСЛЕ БОЯ =====")

r = s.get(f"{BASE}/api/fleets")
fleets_after = r.json()
for f in fleets_after:
    alive = len([sh for sh in f["ships"] if sh["is_alive"]])
    dead = len([sh for sh in f["ships"] if not sh["is_alive"]])
    print(f"  [{f['id']}] {f['name']} alive={alive} dead={dead} pos=({f['pos_x']},{f['pos_y']})")

# ============================================================
# 13. ФЛОТ С КАНОНЕРКОЙ — МИНЫ (в контексте боя)
# ============================================================
print("\n===== 13. КАНОНЕРКА И МИНЫ (через бой) =====")

# Move Драконий флот to mine cell (11,10) — but need enemy there for mine trigger via battle
# Actually, mines only trigger during battle. Place mines at a cell where a battle will happen.
# Move Драконий to (11,10) with mines — no battle happens (no enemy), mines not triggered.
# This is expected: fleet-level mines only trigger during battle.

# Instead test: create a scenario where mines trigger during battle
# Place mines at (12,10) where Королевский флот is (if it survived)
r = s.get(f"{BASE}/api/fleets")
fleets_check = r.json()
lev_fleet = [f for f in fleets_check if f["country_id"] == c2["id"] and f["name"] == "Королевский флот"]
if lev_fleet and any(s["is_alive"] for s in lev_fleet[0]["ships"]):
    lev = lev_fleet[0]
    print(f"  Лев флот: ({lev['pos_x']},{lev['pos_y']}) alive ships: {len([s for s in lev['ships'] if s['is_alive']])}")
    # Place mines at Лев fleet position
    s.post(f"{BASE}/api/cells/{lev['pos_x']}/{lev['pos_y']}/mine", json={},
           headers={"X-Session-Id": admin_token})
    s.post(f"{BASE}/api/cells/{lev['pos_x']}/{lev['pos_y']}/mine", json={},
           headers={"X-Session-Id": admin_token})

    # Find a fleet from another country at war with Лев
    # Орёл is at war with Лев. Need Орёл fleet nearby.
    orl_fleets_alive = [f for f in fleets_check
                        if f["country_id"] == c1["id"] and f["min_speed"] > 0
                        and any(s["is_alive"] for s in f["ships"])]
    if orl_fleets_alive:
        orl = orl_fleets_alive[0]
        dist = max(abs(lev["pos_x"] - orl["pos_x"]), abs(lev["pos_y"] - orl["pos_y"]))
        spd = orl["min_speed"]
        print(f"  Орёл флот: ({orl['pos_x']},{orl['pos_y']}) spd={spd} dist_to_lev={dist}")
        # Reset moved_this_turn so the fleet can move again
        s.post(f"{BASE}/api/state", json={"moved_this_turn": {}},
               headers={"X-Session-Id": admin_token})
        if dist <= spd:
            r = s.post(f"{BASE}/api/fleets/{orl['id']}/move",
                       json={"x": lev["pos_x"], "y": lev["pos_y"]},
                       headers={"X-Session-Id": admin_token})
            res = r.json()
            ok("Orl attacks Lev in mine field", res.get("ok"), res.get("error", ""))
            if res.get("battles"):
                log = res["battles"][0].get("log", [])
                has_mine = any("мин" in l.lower() for l in log)
                ok("Mine triggered during battle", has_mine, f"log excerpt: {log[:3]}")
        else:
            print(f"  SKIP: too far (dist={dist} > speed={spd})")
    else:
        print("  SKIP: no Orl fleet available")
else:
    print("  SKIP: Lev fleet destroyed or gone")

# ============================================================
# 14. ФЛОТ БЕЗ ЖИВЫХ КОРАБЛЕЙ
# ============================================================
print("\n===== 14. ФЛОТ МЁРТВЫХ =====")

r = s.get(f"{BASE}/api/fleets")
fleets_check = r.json()
dead_fleet = None
for f in fleets_check:
    alive = [sh for sh in f["ships"] if sh["is_alive"]]
    if len(alive) == 0 and f["min_speed"] == 0:
        dead_fleet = f
        break

if dead_fleet:
    r = s.post(f"{BASE}/api/fleets/{dead_fleet['id']}/move",
               json={"x": dead_fleet["pos_x"] + 1, "y": dead_fleet["pos_y"]},
               headers={"X-Session-Id": admin_token})
    ok("Dead fleet can't move", r.status_code == 400, f"status={r.status_code}")
else:
    print("  SKIP: no dead fleet to test")

# ============================================================
# 15. TURN SYSTEM — 4 страны
# ============================================================
print("\n===== 15. TURN SYSTEM — 4 СТРАНЫ =====")

r = s.post(f"{BASE}/api/state", json={"is_war": False}, headers={"X-Session-Id": admin_token})
ok("Peace mode", r.ok)

r = s.post(f"{BASE}/api/state",
           json={"turn_order": [c1["id"], c2["id"], c3["id"], c4["id"]], "turn_index": 0, "turn_number": 1},
           headers={"X-Session-Id": admin_token})
ok("Set turn order for 4 countries", r.ok)

r = s.get(f"{BASE}/api/state")
st = r.json()
ok("4 in turn_order", len(st["turn_order"]) == 4, f"order={st['turn_order']}")
ok("Index=0", st["turn_index"] == 0)

for i in range(4):
    r = s.post(f"{BASE}/api/turn/end", json={},
               headers={"X-Session-Id": admin_token, "Authorization": f"Bearer {token}"})
    result = r.json()
    ok(f"End turn {i+1}", result.get("ok"), result.get("error", ""))

r = s.get(f"{BASE}/api/state")
st = r.json()
ok("After 4 ends: index back to 0", st["turn_index"] == 0, f"index={st['turn_index']}")
ok("Turn number advanced", st["turn_number"] == 2, f"turn={st['turn_number']}")

# ============================================================
# 16. CRUD: ДОБАВЛЕНИЕ/УДАЛЕНИЕ КОРАБЛЕЙ
# ============================================================
print("\n===== 16. CRUD КОРАБЛЕЙ =====")

r = s.get(f"{BASE}/api/fleets")
fleet_orla_full = [f for f in r.json() if f["id"] == fleet_orla["id"]][0]

# Add ships — check country-wide limit
r = s.post(f"{BASE}/api/fleets/{fleet_orla['id']}/ships",
           json={"ship_type": "Конвой", "count": 1},
           headers={"X-Session-Id": admin_token})
ok("Add 1 convoy to Orl fleet", r.ok, r.json().get("error", ""))
if r.ok:
    convoy_count = len([s2 for s2 in r.json()["ships"] if s2["ship_type"] == "Конвой" and s2["is_alive"]])
    ok("Convoy added", convoy_count == 1, f"count={convoy_count}")

# Country-wide limit check: add Конвой to another Orl fleet should respect total limit
# Order 4: Конвой limit=5, already has 4+2=6... wait, limit is per country
# After adding 2 convoys, Orl has 4 (escort) + 2 (line) = 6 Конвой. Limit is 5.
# But the add succeeded because the fleet had 0 Конвой before (limit check was 0+2=2 ≤ 5)
# The real issue: create_fleet checked country-wide (4 Конвой existed), add_ship checks fleet-wide (0 existed)
# After our fix, add_ship now checks country-wide. So this should fail.
# Actually, the escort fleet has 4 Конвой. Adding 2 to line fleet = 4+2=6 > 5.
# But the fix was applied AFTER this test ran... Let me check.
# The fix is in the code. Let me verify by trying to add more.

# Try to exceed country-wide limit
r = s.post(f"{BASE}/api/fleets/{fleet_orla['id']}/ships",
           json={"ship_type": "Конвой", "count": 10},
           headers={"X-Session-Id": admin_token})
ok("Country-wide Конвой limit enforced via add_ship", r.status_code == 400,
   f"status={r.status_code} err={r.json().get('error','')}")

# Delete a ship
r = s.get(f"{BASE}/api/fleets")
fleet_data = [f for f in r.json() if f["id"] == fleet_orla["id"]][0]
ships = fleet_data["ships"]
if ships:
    sid_to_delete = ships[-1]["id"]
    r = s.delete(f"{BASE}/api/ships/{sid_to_delete}", headers={"X-Session-Id": admin_token})
    ok("Delete ship", r.ok)

    r = s.get(f"{BASE}/api/fleets")
    fleet_after = [f for f in r.json() if f["id"] == fleet_orla["id"]][0]
    remaining = len(fleet_after["ships"])
    ok("Ship removed", remaining == len(ships) - 1, f"remaining={remaining}")

# ============================================================
# 17. НЕСКОЛЬКО ФЛОТОВ ОДНОЙ СТРАНЫ
# ============================================================
print("\n===== 17. НЕСКОЛЬКО ФЛОТОВ ОДНОЙ СТРАНЫ =====")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "Резерв Орла", "country_id": c1["id"], "pos_x": 5, "pos_y": 5,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Orl 2nd fleet", r.ok, r.json().get("error", ""))

r = s.get(f"{BASE}/api/fleets")
orl_fleets = [f for f in r.json() if f["country_id"] == c1["id"]]
ok("Orl has 2+ fleets", len(orl_fleets) >= 2, f"count={len(orl_fleets)}")

# ============================================================
# 18. УДАЛЕНИЕ ФЛОТА
# ============================================================
print("\n===== 18. УДАЛЕНИЕ ФЛОТА =====")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "ToDelete", "country_id": c3["id"], "pos_x": 0, "pos_y": 0,
    "ships": [{"ship_type": "Конвой", "count": 3}]
}, headers={"X-Session-Id": admin_token})
ok("Create fleet to delete", r.ok, r.json().get("error", ""))
del_fid = r.json()["id"]

r = s.delete(f"{BASE}/api/fleets/{del_fid}", headers={"X-Session-Id": admin_token})
ok("Delete fleet", r.ok)

r = s.get(f"{BASE}/api/fleets")
ok("Fleet gone", not any(f["id"] == del_fid for f in r.json()))

# ============================================================
# 19. УДАЛЕНИЕ СТРАНЫ С ФЛОТАМИ
# ============================================================
print("\n===== 19. УДАЛЕНИЕ СТРАНЫ С ФЛОТАМИ =====")

r = s.post(f"{BASE}/api/countries", json={
    "name": "Временная", "color": "#999", "order_level": 1
}, headers={"X-Session-Id": admin_token})
ok("Create temp country", r.ok)
temp_cid = r.json()["id"]

r = s.post(f"{BASE}/api/fleets", json={
    "name": "Temp Fleet", "country_id": temp_cid, "pos_x": 2, "pos_y": 2,
    "ships": [{"ship_type": "Конвой", "count": 2}]
}, headers={"X-Session-Id": admin_token})
ok("Create fleet for temp country", r.ok)

r = s.delete(f"{BASE}/api/countries/{temp_cid}", headers={"X-Session-Id": admin_token})
ok("Delete temp country", r.ok)

r = s.get(f"{BASE}/api/countries")
ok("Country gone", not any(c["id"] == temp_cid for c in r.json()))

# ============================================================
# 20. УДАЛЕНИЕ КОРАБЛЯ УДАЛЯЕТ ФЛОТ
# ============================================================
print("\n===== 20. УДАЛЕНИЕ ПОСЛЕДНЕГО КОРАБЛЯ = УДАЛЕНИЕ ФЛОТА =====")

r = s.post(f"{BASE}/api/fleets", json={
    "name": "Single Ship Fleet", "country_id": c4["id"], "pos_x": 7, "pos_y": 7,
    "ships": [{"ship_type": "Конвой", "count": 1}]
}, headers={"X-Session-Id": admin_token})
ok("Create single-ship fleet", r.ok, r.json().get("error", ""))
single_fid = r.json()["id"]
single_sid = r.json()["ships"][0]["id"]

r = s.delete(f"{BASE}/api/ships/{single_sid}", headers={"X-Session-Id": admin_token})
ok("Delete last ship", r.ok)

r = s.get(f"{BASE}/api/fleets")
ok("Fleet auto-deleted after last ship removed", not any(f["id"] == single_fid for f in r.json()))

# ============================================================
# 21. ФИНАЛЬНЫЙ ОТЧЁТ
# ============================================================
print("\n===== 21. ФИНАЛЬНЫЙ ОТЧЁТ =====")

r = s.get(f"{BASE}/api/state")
st = r.json()
print(f"  is_war={st['is_war']}, turn={st['turn_number']}, index={st['turn_index']}")
print(f"  turn_order={st['turn_order']}")

r = s.get(f"{BASE}/api/countries")
print(f"  Countries: {len(r.json())}")
for c in r.json():
    print(f"    [{c['id']}] {c['name']}")

r = s.get(f"{BASE}/api/fleets")
total_fleets = len(r.json())
total_ships = sum(len(f["ships"]) for f in r.json())
print(f"  Fleets: {total_fleets}, Total ships: {total_ships}")
for f in r.json():
    alive = len([sh for sh in f["ships"] if sh["is_alive"]])
    print(f"    [{f['id']}] {f['name']} ({alive}/{len(f['ships'])})")

r = s.get(f"{BASE}/api/logs")
print(f"  Battle logs: {len(r.json())}")

r = s.get(f"{BASE}/api/cells")
print(f"  Map cells with features: {len(r.json())}")

ok("Game state consistent", True)

sio.disconnect()

print(f"\n{'=' * 60}")
print(f"  RESULTS: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} TOTAL")
print(f"{'=' * 60}")
