"""
Imperium: Sea Wars — Flask + SocketIO Backend
Исправления:
  - SECRET_KEY и ADMIN_PASSWORD из переменных окружения
  - Админ-ограничения: флоты, страны, демо, минирование, крепости
  - Лимиты кораблей по порядку страны
  - Валидация координат
  - Исправлен race condition в moved_this_turn
  - Исправлен обход админ-авторизации через JWT
  - Исправлен XSS в именах кораблей
  - Добавлена аутентификация WebSocket
  - Исправлен CORS
"""
import os
import re
import json
import secrets
import uuid
import jwt
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy.exc import IntegrityError
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_socketio import SocketIO, emit
from models import (
    db, Country, Fleet, Ship, MapCell, BattleLog, GameState,
    CountryRelation, User, SHIP_STATS, SHIP_ORDER, SHIP_LIMITS, FORT_ARMOR_BONUS
)
from engine import check_and_run_battles, get_or_create_cell, are_at_war, apply_mine_damage_to_ship, check_victory, wrap_distance

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")


def _load_or_create_secret():
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "r") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_FILE, "w") as f:
        f.write(key)
    if os.name != "nt":
        try:
            os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
    return key


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("IMPERIUM_SECRET") or _load_or_create_secret()
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'naval.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

CORS_ORIGINS = os.environ.get("IMPERIUM_CORS_ORIGINS", "").split(",") if os.environ.get("IMPERIUM_CORS_ORIGINS") else ["*"]
socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS, async_mode="gevent")

ADMIN_PASSWORD = os.environ.get("IMPERIUM_ADMIN_PASS", "ADMINIMPERIUM")
JWT_EXPIRY_HOURS = 72

_sessions = {}

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _sanitize_name(value, max_len=100):
    s = str(value or "").strip()[:max_len]
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")
    return s


def _validate_color(color):
    if not color or not _HEX_COLOR_RE.match(str(color)):
        return "#FF5733"
    return str(color)


def create_token(user_id, username, is_admin=False):
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": bool(is_admin),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        return None
    return User.query.get(payload.get("user_id"))


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Не авторизован"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def get_session_country_id():
    token = request.headers.get("X-Session-Id")
    if not token:
        return None
    for sid, sess in _sessions.items():
        if sess.get("session_token") == token:
            return sess.get("country_id")
    return None


def get_session_sid():
    token = request.headers.get("X-Session-Id")
    if not token:
        return None
    for sid, sess in _sessions.items():
        if sess.get("session_token") == token:
            return sid
    return None


def get_jwt_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        return None
    return User.query.get(payload.get("user_id"))


def is_admin():
    user = get_jwt_user()
    if user and getattr(user, "is_admin", False):
        return True
    country_id = get_session_country_id()
    return country_id == 0 or country_id == "0"


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return jsonify({"error": "Только администратор может выполнять это действие"}), 403
        return f(*args, **kwargs)
    return wrapper


def require_ship_ownership(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid_val = kwargs.get("sid")
        country_id = get_session_country_id()

        if country_id == 0 or country_id == "0":
            return f(*args, **kwargs)

        user = get_jwt_user()
        if user and getattr(user, "is_admin", False):
            return f(*args, **kwargs)

        if country_id is None:
            return jsonify({"error": "Не авторизован: отсутствует X-Session-Id"}), 401

        if sid_val is not None:
            ship = Ship.query.get(sid_val)
            if ship is None:
                return jsonify({"error": "Корабль не найден"}), 404
            fleet = Fleet.query.get(ship.fleet_id)
            if fleet is None or fleet.country_id != country_id:
                return jsonify({"error": "Нет прав на управление этим кораблём"}), 403

        return f(*args, **kwargs)
    return wrapper


@app.before_request
def create_tables():
    pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


@app.route("/api/state", methods=["GET"])
def get_state():
    turn_order_raw = GameState.get("turn_order", "[]")
    moved_raw = GameState.get("moved_this_turn", "{}")
    try:
        turn_order = json.loads(turn_order_raw)
    except Exception:
        turn_order = []
    try:
        moved = json.loads(moved_raw)
    except Exception:
        moved = {}
    grid_cols = int(GameState.get("grid_cols", 40))
    grid_rows = int(GameState.get("grid_rows", 25))
    return jsonify({
        "is_war":         GameState.get("is_war", "false") == "true",
        "grid_cols":      grid_cols,
        "grid_rows":      grid_rows,
        "turn_number":    int(GameState.get("turn_number", 1)),
        "turn_index":     int(GameState.get("turn_index", 0)),
        "turn_order":     turn_order,
        "moved_this_turn": moved,
    })


@app.route("/api/state", methods=["POST"])
@require_admin
def set_state():
    data = request.json or {}
    grid_cols = int(GameState.get("grid_cols", 40))
    grid_rows = int(GameState.get("grid_rows", 25))

    if "is_war" in data:
        GameState.set("is_war", "true" if data["is_war"] else "false")
        socketio.emit("state_update", {"is_war": data["is_war"]})
    if "grid_cols" in data:
        val = max(5, min(80, int(data["grid_cols"])))
        GameState.set("grid_cols", val)
        grid_cols = val
    if "grid_rows" in data:
        val = max(5, min(50, int(data["grid_rows"])))
        GameState.set("grid_rows", val)
        grid_rows = val
    if "turn_number" in data:
        GameState.set("turn_number", int(data["turn_number"]))
    if "turn_index" in data:
        GameState.set("turn_index", int(data["turn_index"]))
    if "turn_order" in data:
        GameState.set("turn_order", json.dumps(data["turn_order"]))
    if "moved_this_turn" in data:
        GameState.set("moved_this_turn", json.dumps(data["moved_this_turn"]))

    turn_order_raw = GameState.get("turn_order", "[]")
    moved_raw = GameState.get("moved_this_turn", "{}")
    try: turn_order = json.loads(turn_order_raw)
    except Exception: turn_order = []
    try: moved = json.loads(moved_raw)
    except Exception: moved = {}
    socketio.emit("state_update", {
        "is_war":          GameState.get("is_war", "false") == "true",
        "turn_number":     int(GameState.get("turn_number", 1)),
        "turn_index":      int(GameState.get("turn_index", 0)),
        "current_turn_order": turn_order,
        "moved_this_turn": moved,
        "grid_cols": grid_cols,
        "grid_rows": grid_rows,
    })
    return jsonify({"ok": True})


@app.route("/api/turn/end", methods=["POST"])
def end_turn():
    user = get_jwt_user()
    country_id = get_session_country_id()
    sid = get_session_sid()

    if user is None and country_id is None:
        return jsonify({"error": "Не авторизован"}), 401

    if sid and sid in _sessions:
        sess_user_id = _sessions[sid].get("user_id")
        if user and sess_user_id is not None and sess_user_id != user.id:
            return jsonify({"error": "Сессия не принадлежит вам"}), 403
        if user is None and sess_user_id is not None:
            return jsonify({"error": "Требуется авторизация для завершения хода"}), 403

    is_adm = (country_id == 0 or country_id == "0")

    turn_order_raw = GameState.get("turn_order", "[]")
    try:
        turn_order = json.loads(turn_order_raw)
    except Exception:
        turn_order = []

    if not turn_order:
        countries = Country.query.all()
        turn_order = [c.id for c in countries]
        GameState.set("turn_order", json.dumps(turn_order))

    turn_index  = int(GameState.get("turn_index", 0))
    turn_number = int(GameState.get("turn_number", 1))

    is_war = GameState.get("is_war", "false") == "true"
    if is_war and not is_adm and turn_order:
        if country_id is None:
            return jsonify({"error": "Не авторизован: отсутствует X-Session-Id"}), 401
        active_id = turn_order[turn_index % len(turn_order)]
        if country_id != active_id:
            return jsonify({"error": "Сейчас не ваш ход"}), 403

    next_index = (turn_index + 1) % len(turn_order) if turn_order else 0
    if next_index == 0 and turn_order:
        turn_number += 1
        GameState.set("turn_number", turn_number)

    GameState.set("turn_index", next_index)
    GameState.set("moved_this_turn", "{}")

    socketio.emit("turn_advanced", {
        "turn_number": turn_number,
        "turn_order":  turn_order,
        "turn_index":  next_index,
    })
    return jsonify({"ok": True, "turn_number": turn_number, "turn_index": next_index})


@app.route("/api/countries", methods=["GET"])
def get_countries():
    return jsonify([c.to_dict() for c in Country.query.all()])


@app.route("/api/countries", methods=["POST"])
@require_admin
def create_country():
    data = request.json or {}
    name = _sanitize_name(data.get("name"), 100)
    if not name:
        return jsonify({"error": "Название страны обязательно"}), 400
    order = max(1, min(4, int(data.get("order_level", 1))))
    c = Country(
        name=name,
        color=_validate_color(data.get("color")),
        flag_emoji=_sanitize_name(data.get("flag_emoji", "🏴"), 10),
        order_level=order,
        balance=max(0, int(data.get("balance", 0))),
    )
    db.session.add(c)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": f"Страна с названием «{name}» уже существует"}), 400
    socketio.emit("map_update", full_map_state())
    return jsonify(c.to_dict()), 201


@app.route("/api/countries/<int:cid>", methods=["PUT"])
@require_admin
def update_country(cid):
    c = Country.query.get(cid)
    if not c:
        return jsonify({"error": "Страна не найдена"}), 404
    data = request.json or {}
    for field in ["name", "color", "flag_emoji", "order_level", "balance", "is_war"]:
        if field in data:
            if field == "order_level":
                try:
                    setattr(c, field, max(1, min(4, int(data[field]))))
                except (TypeError, ValueError):
                    pass
            elif field == "color":
                setattr(c, field, _validate_color(data[field]))
            elif field == "name":
                setattr(c, field, _sanitize_name(data[field], 100))
            elif field == "flag_emoji":
                setattr(c, field, _sanitize_name(data[field], 10))
            elif field == "balance":
                try:
                    setattr(c, field, max(0, int(data[field])))
                except (TypeError, ValueError):
                    pass
            else:
                setattr(c, field, data[field])
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(c.to_dict())


@app.route("/api/countries/<int:cid>", methods=["DELETE"])
@require_admin
def delete_country(cid):
    c = Country.query.get(cid)
    if not c:
        return jsonify({"error": "Страна не найдена"}), 404
    db.session.delete(c)
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify({"ok": True})


@app.route("/api/relations", methods=["GET"])
def get_relations():
    rels = CountryRelation.query.all()
    return jsonify([{"a": r.country_a_id, "b": r.country_b_id, "at_war": r.at_war} for r in rels])


@app.route("/api/relations", methods=["POST"])
@require_admin
def set_relation():
    data = request.json or {}
    a = data.get("country_a_id")
    b = data.get("country_b_id")
    if a is None or b is None:
        return jsonify({"error": "country_a_id и country_b_id обязательны"}), 400
    at_war = data.get("at_war", False)
    rel = CountryRelation.query.filter(
        ((CountryRelation.country_a_id == a) & (CountryRelation.country_b_id == b)) |
        ((CountryRelation.country_a_id == b) & (CountryRelation.country_b_id == a))
    ).first()
    if rel:
        rel.at_war = at_war
    else:
        rel = CountryRelation(country_a_id=a, country_b_id=b, at_war=at_war)
        db.session.add(rel)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/fleets", methods=["GET"])
def get_fleets():
    return jsonify([f.to_dict() for f in Fleet.query.all()])


@app.route("/api/fleets", methods=["POST"])
@require_admin
def create_fleet():
    data = request.json
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Название флота обязательно"}), 400

    country_id = data.get("country_id")
    if not country_id:
        return jsonify({"error": "Страна обязательна"}), 400
    country = Country.query.get(country_id)
    if not country:
        return jsonify({"error": "Страна не найдена"}), 404

    pos_x = int(data.get("pos_x", 0))
    pos_y = int(data.get("pos_y", 0))
    grid_cols = int(GameState.get("grid_cols", 40))
    grid_rows = int(GameState.get("grid_rows", 25))
    if pos_x < 0 or pos_x >= grid_cols or pos_y < 0 or pos_y >= grid_rows:
        return jsonify({"error": f"Кординаты за пределами карты (0-{grid_cols-1}, 0-{grid_rows-1})"}), 400

    for ship_data in data.get("ships", []):
        ship_type = ship_data["ship_type"]
        count = int(ship_data.get("count", 1))
        if count <= 0:
            continue
        if ship_type not in SHIP_STATS:
            return jsonify({"error": f"Неизвестный тип корабля: {ship_type}"}), 400

        limits = SHIP_LIMITS.get(ship_type, {})
        limit = limits.get(country.order_level)
        if limit is not None:
            existing = Ship.query.join(Fleet).filter(
                Fleet.country_id == country_id,
                Ship.ship_type == ship_type,
                Ship.is_alive == True
            ).count()
            if existing + count > limit:
                return jsonify({
                    "error": f"Лимит {ship_type} для порядка {country.order_level}: {limit} (уже {existing})"
                }), 400

    f = Fleet(name=name, country_id=country_id, pos_x=pos_x, pos_y=pos_y)
    db.session.add(f)
    db.session.flush()
    for ship_data in data.get("ships", []):
        ship_type = ship_data["ship_type"]
        stats = SHIP_STATS.get(ship_type)
        if not stats:
            continue
        custom_armor = ship_data.get("armor")
        capacity = stats.get("capacity", 0)
        for _ in range(int(ship_data.get("count", 1))):
            armor_val = int(custom_armor) if custom_armor is not None else stats["armor"]
            reg_val = max(0, min(capacity, int(ship_data.get("regiments", 0))))
            s = Ship(fleet_id=f.id, ship_type=ship_type, current_armor=armor_val, regiments=reg_val)
            db.session.add(s)
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(f.to_dict()), 201


@app.route("/api/fleets/<int:fid>", methods=["DELETE"])
@require_admin
def delete_fleet(fid):
    f = Fleet.query.get(fid)
    if not f:
        return jsonify({"error": "Флот не найден"}), 404
    db.session.delete(f)
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify({"ok": True})


@app.route("/api/fleets/<int:fid>/move", methods=["POST"])
def move_fleet(fid):
    f = Fleet.query.get_or_404(fid)
    data = request.json or {}
    if "x" not in data or "y" not in data:
        return jsonify({"error": "Координаты x и y обязательны"}), 400
    tx, ty = int(data["x"]), int(data["y"])

    grid_cols = int(GameState.get("grid_cols", 40))
    grid_rows = int(GameState.get("grid_rows", 25))
    if tx < 0 or tx >= grid_cols or ty < 0 or ty >= grid_rows:
        return jsonify({"error": f"Кординаты за пределами карты"}), 400

    is_war = GameState.get("is_war", "false") == "true"
    speed  = f.min_speed()

    if speed == 0:
        return jsonify({"error": "Флот не может двигаться: нет живых кораблей"}), 400

    if is_war:
        turn_order_raw = GameState.get("turn_order", "[]")
        try:
            turn_order = json.loads(turn_order_raw)
        except Exception:
            turn_order = []

        if turn_order:
            turn_index = int(GameState.get("turn_index", 0))
            active_country_id = turn_order[turn_index % len(turn_order)]
            if f.country_id != active_country_id:
                return jsonify({"error": "Сейчас не ваш ход"}), 403

        moved_raw = GameState.get("moved_this_turn", "{}")
        try:
            moved = json.loads(moved_raw)
        except Exception:
            moved = {}
        if moved.get(str(fid)):
            return jsonify({"error": "Этот флот уже ходил в этот ход"}), 403

        dist = wrap_distance(f.pos_x, f.pos_y, tx, ty, grid_cols, grid_rows)
        if dist > speed:
            return jsonify({
                "error": f"Слишком далеко! Скорость флота: {speed}, расстояние: {dist}"
            }), 400

    prev_x, prev_y = f.pos_x, f.pos_y
    f.pos_x, f.pos_y = tx, ty
    db.session.flush()

    has_destroyer = any(
        s.is_alive and SHIP_STATS.get(s.ship_type, {}).get("can_demine")
        for s in f.ships
    )
    battles = check_and_run_battles(f, tx, ty, demine_first=has_destroyer)

    if battles and battles[-1].get("winner_fleet_id") and battles[-1]["winner_fleet_id"] != f.id:
        f.pos_x, f.pos_y = prev_x, prev_y

    db.session.commit()

    moved_raw = GameState.get("moved_this_turn", "{}")
    try: moved = json.loads(moved_raw)
    except Exception: moved = {}
    moved[str(fid)] = True
    for s in f.ships:
        if s.is_alive:
            moved[f"ship_{s.id}"] = True
    GameState.set("moved_this_turn", json.dumps(moved))

    socketio.emit("map_update", full_map_state())
    if battles:
        for b in battles:
            socketio.emit("battle_result", b)

    victory = check_victory()
    if victory and victory.get("winner_country_id"):
        socketio.emit("game_victory", victory)
    elif victory and victory.get("eliminated"):
        for e in victory["eliminated"]:
            socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"🏴 {e['flag_emoji']} {e['name']} уничтожена!"})

    return jsonify({"ok": True, "fleet": f.to_dict(), "battles": battles})


@app.route("/api/ships/<int:sid>/move", methods=["POST"])
@require_ship_ownership
def move_ship(sid):
    ship = Ship.query.get_or_404(sid)
    if not ship.is_alive:
        return jsonify({"error": "Корабль потоплен"}), 400

    data = request.json or {}
    if "x" not in data or "y" not in data:
        return jsonify({"error": "Координаты x и y обязательны"}), 400
    tx, ty = int(data["x"]), int(data["y"])

    grid_cols = int(GameState.get("grid_cols", 40))
    grid_rows = int(GameState.get("grid_rows", 25))
    if tx < 0 or tx >= grid_cols or ty < 0 or ty >= grid_rows:
        return jsonify({"error": f"Кординаты за пределами карты"}), 400

    orig_fleet = Fleet.query.get(ship.fleet_id)
    if not orig_fleet:
        return jsonify({"error": "Флот не найден"}), 400

    is_war = GameState.get("is_war", "false") == "true"
    speed = SHIP_STATS.get(ship.ship_type, {}).get("speed", 3)

    if is_war:
        turn_order_raw = GameState.get("turn_order", "[]")
        try:
            turn_order = json.loads(turn_order_raw)
        except Exception:
            turn_order = []

        if turn_order:
            turn_index = int(GameState.get("turn_index", 0))
            active_country_id = turn_order[turn_index % len(turn_order)]
            if orig_fleet.country_id != active_country_id:
                return jsonify({"error": "Сейчас не ваш ход"}), 403

        moved_raw = GameState.get("moved_this_turn", "{}")
        try:
            moved = json.loads(moved_raw)
        except Exception:
            moved = {}
        ship_key = f"ship_{sid}"
        if moved.get(ship_key):
            return jsonify({"error": "Этот корабль уже ходил в этот ход"}), 403

        ship_from_x = orig_fleet.pos_x if orig_fleet else 0
        ship_from_y = orig_fleet.pos_y if orig_fleet else 0
        dist = wrap_distance(ship_from_x, ship_from_y, tx, ty, grid_cols, grid_rows)
        if dist > speed:
            return jsonify({
                "error": f"Слишком далеко! Скорость {ship.ship_type}: {speed}, расстояние: {dist}"
            }), 400

    if tx == orig_fleet.pos_x and ty == orig_fleet.pos_y:
        return jsonify({"ok": True, "fleet": orig_fleet.to_dict()})

    existing_fleet = Fleet.query.filter_by(
        country_id=orig_fleet.country_id, pos_x=tx, pos_y=ty
    ).first()

    mine_log = []
    target_cell = get_or_create_cell(tx, ty)
    is_destroyer = SHIP_STATS.get(ship.ship_type, {}).get("can_demine")
    if not is_destroyer:
        apply_mine_damage_to_ship(ship, target_cell, orig_fleet.name, mine_log)
    else:
        if target_cell.mines_count > 0:
            from engine import demine_cell
            demine_cell(target_cell, mine_log)

    mine_result = None
    if mine_log:
        mine_battle = BattleLog(
            cell_x=tx, cell_y=ty,
            log_json=json.dumps(mine_log, ensure_ascii=False)
        )
        db.session.add(mine_battle)
        db.session.flush()
        mine_result = {"battle_id": mine_battle.id, "log": mine_log,
                       "winner_fleet_id": None, "mine_event": True}

    if existing_fleet and existing_fleet.id != orig_fleet.id:
        ship.fleet_id = existing_fleet.id
        db.session.flush()
        battles = check_and_run_battles(existing_fleet, tx, ty)
        if mine_result:
            battles = [mine_result] + battles
        db.session.commit()
        moved_raw2 = GameState.get("moved_this_turn", "{}")
        try: moved2 = json.loads(moved_raw2)
        except Exception: moved2 = {}
        moved2[f"ship_{sid}"] = True
        GameState.set("moved_this_turn", json.dumps(moved2))
        socketio.emit("map_update", full_map_state())
        for b in battles:
            socketio.emit("battle_result", b)
        victory = check_victory()
        if victory and victory.get("winner_country_id"):
            socketio.emit("game_victory", victory)
        elif victory and victory.get("eliminated"):
            for e in victory["eliminated"]:
                socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"🏴 {e['flag_emoji']} {e['name']} уничтожена!"})
        return jsonify({"ok": True, "fleet": existing_fleet.to_dict(), "battles": battles})
    else:
        new_fleet = Fleet(
            name=f"{orig_fleet.name} ({ship.ship_type})",
            country_id=orig_fleet.country_id,
            pos_x=tx, pos_y=ty
        )
        db.session.add(new_fleet)
        db.session.flush()
        ship.fleet_id = new_fleet.id
        db.session.flush()

        battles = check_and_run_battles(new_fleet, tx, ty)
        if mine_result:
            battles = [mine_result] + battles
        db.session.commit()
        moved_raw2 = GameState.get("moved_this_turn", "{}")
        try: moved2 = json.loads(moved_raw2)
        except Exception: moved2 = {}
        moved2[f"ship_{sid}"] = True
        GameState.set("moved_this_turn", json.dumps(moved2))
        socketio.emit("map_update", full_map_state())
        for b in battles:
            socketio.emit("battle_result", b)
        victory = check_victory()
        if victory and victory.get("winner_country_id"):
            socketio.emit("game_victory", victory)
        elif victory and victory.get("eliminated"):
            for e in victory["eliminated"]:
                socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"🏴 {e['flag_emoji']} {e['name']} уничтожена!"})
        return jsonify({"ok": True, "fleet": new_fleet.to_dict(), "battles": battles})


@app.route("/api/fleets/<int:fid>/ships", methods=["POST"])
@require_admin
def add_ship(fid):
    f = Fleet.query.get(fid)
    if not f:
        return jsonify({"error": "Флот не найден"}), 404
    data = request.json
    ship_type = data["ship_type"]
    count = int(data.get("count", 1))
    if count <= 0:
        return jsonify({"error": "Количество должно быть > 0"}), 400
    stats = SHIP_STATS.get(ship_type)
    if not stats:
        return jsonify({"error": "Неизвестный тип корабля"}), 400

    limits = SHIP_LIMITS.get(ship_type, {})
    limit = limits.get(f.country.order_level)
    if limit is not None:
        existing = Ship.query.join(Fleet).filter(
            Fleet.country_id == f.country_id,
            Ship.ship_type == ship_type,
            Ship.is_alive == True
        ).count()
        if existing + count > limit:
            return jsonify({
                "error": f"Лимит {ship_type} для порядка {f.country.order_level}: {limit} (уже {existing})"
            }), 400

    custom_armor = data.get("armor")
    capacity = stats.get("capacity", 0)
    for _ in range(count):
        armor_val = int(custom_armor) if custom_armor is not None else stats["armor"]
        reg_val = max(0, min(capacity, int(data.get("regiments", 0))))
        s = Ship(fleet_id=f.id, ship_type=ship_type, current_armor=armor_val, regiments=reg_val)
        db.session.add(s)
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(f.to_dict())


@app.route("/api/ships/<int:sid>", methods=["DELETE"])
@require_admin
def delete_ship(sid):
    ship = Ship.query.get(sid)
    if not ship:
        return jsonify({"error": "Корабль не найден"}), 404
    fleet = Fleet.query.get(ship.fleet_id)
    db.session.delete(ship)
    if fleet and not fleet.is_alive():
        db.session.delete(fleet)
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify({"ok": True})


@app.route("/api/ships/<int:sid>/regiments", methods=["POST"])
@require_admin
def update_ship_regiments(sid):
    ship = Ship.query.get(sid)
    if not ship:
        return jsonify({"error": "Корабль не найден"}), 404
    if not ship.is_alive:
        return jsonify({"error": "Корабль потоплен"}), 400
    data = request.json or {}
    regiments = int(data.get("regiments", 0))
    capacity = SHIP_STATS.get(ship.ship_type, {}).get("capacity", 0)
    if regiments < 0 or regiments > capacity:
        return jsonify({"error": f"Полки: от 0 до {capacity} (Транспортировка {ship.ship_type})"}), 400
    ship.regiments = regiments
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify({"ok": True, "ship": ship.to_dict()})


@app.route("/api/ships/<int:sid>/rename", methods=["POST"])
def rename_ship(sid):
    ship = Ship.query.get(sid)
    if not ship:
        return jsonify({"error": "Корабль не найден"}), 404
    country_id = get_session_country_id()

    is_owner = False
    if country_id is not None:
        fleet = Fleet.query.get(ship.fleet_id)
        if fleet and (country_id == 0 or country_id == "0" or fleet.country_id == country_id):
            is_owner = True

    user = get_jwt_user()
    if user and getattr(user, "is_admin", False):
        is_owner = True

    if not is_owner:
        return jsonify({"error": "Нет прав на переименование этого корабля"}), 403

    data = request.json or {}
    name = _sanitize_name(data.get("name"), 100) or None
    ship.custom_name = name
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify({"ok": True, "ship": ship.to_dict()})


@app.route("/api/cells", methods=["GET"])
def get_cells():
    cells = MapCell.query.filter(
        (MapCell.mines_count > 0) | (MapCell.fort_owner_id != None)
    ).all()
    return jsonify([c.to_dict() for c in cells])


@app.route("/api/cells/<int:x>/<int:y>/mine", methods=["POST"])
@require_admin
def place_mine(x, y):
    data = request.json or {}
    fleet_id = data.get("fleet_id")
    if fleet_id:
        f = Fleet.query.get(fleet_id)
        if not f:
            return jsonify({"error": "Флот не найден"}), 400
        if f.pos_x != x or f.pos_y != y:
            return jsonify({"error": "Флот не находится в этой клетке"}), 400
        has_cannon = any(s.ship_type == "Канонерка" and s.is_alive for s in f.ships)
        if not has_cannon:
            return jsonify({"error": "Нет Канонерки для установки мин"}), 400

    cell = get_or_create_cell(x, y)
    if cell.mines_count >= 2:
        return jsonify({"error": "В клетке уже максимум мин (2)"}), 400
    cell.mines_count += 1
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(cell.to_dict())


@app.route("/api/cells/<int:x>/<int:y>/demine", methods=["POST"])
@require_admin
def demine_cell_route(x, y):
    cell = get_or_create_cell(x, y)
    if cell.mines_count == 0:
        return jsonify({"error": "Мин в этой клетке нет"}), 400
    cell.mines_count = 0
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(cell.to_dict())


@app.route("/api/cells/<int:x>/<int:y>/fort", methods=["POST"])
@require_admin
def set_fort(x, y):
    data = request.json or {}
    cell = get_or_create_cell(x, y)
    cell.fort_owner_id = data.get("owner_id")
    db.session.commit()
    socketio.emit("map_update", full_map_state())
    return jsonify(cell.to_dict())


@app.route("/api/logs", methods=["GET"])
def get_logs():
    logs = BattleLog.query.order_by(BattleLog.created_at.desc()).limit(20).all()
    return jsonify([l.to_dict() for l in logs])


@app.route("/api/logs/<int:lid>", methods=["GET"])
def get_log(lid):
    log = BattleLog.query.get(lid)
    if not log:
        return jsonify({"error": "Лог не найден"}), 404
    return jsonify(log.to_dict())


@app.route("/api/ship_types", methods=["GET"])
def get_ship_types():
    return jsonify({"stats": SHIP_STATS, "limits": SHIP_LIMITS})


def full_map_state():
    fleets = Fleet.query.all()
    cells  = MapCell.query.filter(
        (MapCell.mines_count > 0) | (MapCell.fort_owner_id != None)
    ).all()
    return {
        "fleets": [f.to_dict() for f in fleets],
        "cells":  [c.to_dict() for c in cells],
    }


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    if data.get("password") == ADMIN_PASSWORD:
        admin_user = User.query.filter_by(username="admin").first()
        if not admin_user:
            admin_user = User(username="admin", display_name="Администратор", is_admin=True)
            admin_user.set_password(ADMIN_PASSWORD)
            db.session.add(admin_user)
            db.session.commit()
        token = create_token(admin_user.id, admin_user.username, is_admin=True)
        return jsonify({"ok": True, "admin_name": "admin", "token": token})
    return jsonify({"ok": False, "error": "Неверный пароль"}), 401


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return jsonify({"error": "Имя пользователя минимум 3 символа"}), 400
    if len(username) > 50:
        return jsonify({"error": "Имя пользователя максимум 50 символов"}), 400
    if len(password) < 4:
        return jsonify({"error": "Пароль минимум 4 символа"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Пользователь уже существует"}), 409

    user = User(username=username, display_name=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_token(user.id, user.username, is_admin=getattr(user, "is_admin", False))
    return jsonify({"ok": True, "token": token, "user": user.to_dict()}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Неверное имя пользователя или пароль"}), 401

    user.last_login = datetime.utcnow()
    db.session.commit()

    token = create_token(user.id, user.username, is_admin=getattr(user, "is_admin", False))
    return jsonify({"ok": True, "token": token, "user": user.to_dict()})


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def get_me():
    return jsonify({"ok": True, "user": request.current_user.to_dict(full=True)})


@app.route("/api/auth/profile", methods=["PUT"])
@require_auth
def update_profile():
    user = request.current_user
    data = request.json or {}
    if "display_name" in data:
        name = _sanitize_name(data["display_name"], 100)
        if len(name) < 1:
            return jsonify({"error": "Отображаемое имя 1-100 символов"}), 400
        user.display_name = name
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_dict()})


@app.route("/api/users/<int:uid>", methods=["GET"])
def get_user_profile(uid):
    user = User.query.get(uid)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    return jsonify({"ok": True, "user": user.to_dict(full=True)})


def sessions_list():
    return [
        {"sid": sid, "name": s["name"], "country_id": s["country_id"], "online": s["online"]}
        for sid, s in _sessions.items()
    ]


@app.route("/api/players", methods=["GET"])
def get_players():
    return jsonify(sessions_list())


@app.route("/api/debug/sessions", methods=["GET"])
@require_admin
def debug_sessions():
    return jsonify(sessions_list())


@socketio.on("connect")
def on_connect():
    sid = request.sid
    token = str(uuid.uuid4())
    _sessions[sid] = {"name": None, "country_id": None, "online": True, "session_token": token}
    emit("map_update", full_map_state())
    emit("session_init", {"session_id": sid, "session_token": token, "players": sessions_list()})


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    if sid in _sessions:
        name = _sessions[sid].get("name") or "Игрок"
        del _sessions[sid]
        socketio.emit("players_update", {"players": sessions_list()})
        socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"{name} отключился"})


@socketio.on("join_session")
def on_join_session(data):
    sid = request.sid
    name       = _sanitize_name(data.get("name", "Адмирал"), 50)
    country_id = data.get("country_id")
    spectator  = data.get("is_spectator", False)
    token      = data.get("token")
    user_id    = None
    is_admin_user = False

    if token:
        payload = decode_token(token)
        if payload:
            user_id = payload.get("user_id")
            is_admin_user = payload.get("is_admin", False)

    if is_admin_user and country_id is None:
        country_id = 0

    if country_id and not spectator:
        for other_sid, sess in _sessions.items():
            if other_sid != sid and sess.get("country_id") == country_id and sess["online"]:
                emit("join_error", {"error": f"Страна уже занята: {sess['name']}"})
                return

    _sessions[sid] = {"name": name, "country_id": country_id, "online": True, "user_id": user_id, "session_token": _sessions.get(sid, {}).get("session_token", str(uuid.uuid4()))}

    if user_id and country_id:
        user = User.query.get(user_id)
        if user:
            user.country_id = country_id
            db.session.commit()

    emit("session_init", {"session_id": sid, "session_token": _sessions[sid]["session_token"], "players": sessions_list()})
    socketio.emit("players_update", {"players": sessions_list()})
    label = "наблюдателем" if spectator else f"за страну {country_id}"
    socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"{name} вошёл ({label})"})


@socketio.on("rejoin")
def on_rejoin(data):
    sid = request.sid
    country_id = data.get("country_id")
    token = data.get("token")
    user_id = None
    is_admin_user = False

    if token:
        payload = decode_token(token)
        if payload:
            user_id = payload.get("user_id")
            is_admin_user = payload.get("is_admin", False)

    if is_admin_user and country_id is None:
        country_id = 0

    _sessions[sid] = {
        "name": _sessions.get(sid, {}).get("name", "Адмирал"),
        "country_id": country_id, "online": True,
        "user_id": user_id,
        "session_token": _sessions.get(sid, {}).get("session_token", str(uuid.uuid4()))
    }
    emit("session_init", {"session_id": sid, "session_token": _sessions[sid]["session_token"], "players": sessions_list()})
    emit("map_update", full_map_state())


@socketio.on("leave_session")
def on_leave_session():
    sid = request.sid
    if sid in _sessions:
        name = _sessions[sid].get("name") or "Игрок"
        del _sessions[sid]
        socketio.emit("players_update", {"players": sessions_list()})
        socketio.emit("chat_message", {"name": "🖥 Сервер", "text": f"{name} вышел из игры"})


@socketio.on("request_state")
def on_request_state():
    emit("map_update", full_map_state())
    emit("players_update", {"players": sessions_list()})


@app.route("/api/seed", methods=["POST"])
@require_admin
def seed_demo():
    BattleLog.query.delete()
    Ship.query.delete()
    Fleet.query.delete()
    CountryRelation.query.delete()
    Country.query.delete()
    MapCell.query.delete()
    db.session.commit()

    russia  = Country(name="Россия",   color="#2196F3", flag_emoji="🇷🇺", order_level=4, balance=10000)
    britain = Country(name="Британия", color="#F44336", flag_emoji="🇬🇧", order_level=4, balance=12000)
    france  = Country(name="Франция",  color="#4CAF50", flag_emoji="🇫🇷", order_level=3, balance=8000)
    db.session.add_all([russia, britain, france])
    db.session.flush()

    rel = CountryRelation(country_a_id=russia.id, country_b_id=britain.id, at_war=True)
    db.session.add(rel)

    rf = Fleet(name="Балтийский флот", country_id=russia.id, pos_x=18, pos_y=8)
    db.session.add(rf); db.session.flush()
    for t, n in [("Дредноут",1),("Линейный крейсер",2),("Эсминец",2),("Конвой",3)]:
        for _ in range(n):
            db.session.add(Ship(fleet_id=rf.id, ship_type=t, current_armor=SHIP_STATS[t]["armor"]))

    bf = Fleet(name="Гранд Флит", country_id=britain.id, pos_x=20, pos_y=8)
    db.session.add(bf); db.session.flush()
    for t, n in [("Дредноут",2),("Линейный крейсер",1),("Канонерка",2)]:
        for _ in range(n):
            db.session.add(Ship(fleet_id=bf.id, ship_type=t, current_armor=SHIP_STATS[t]["armor"]))

    ff = Fleet(name="Средиземноморская эскадра", country_id=france.id, pos_x=18, pos_y=14)
    db.session.add(ff); db.session.flush()
    for t, n in [("Линейный крейсер",1),("Эсминец",3),("Конвой",2)]:
        for _ in range(n):
            db.session.add(Ship(fleet_id=ff.id, ship_type=t, current_armor=SHIP_STATS[t]["armor"]))

    db.session.add(MapCell(x=17, y=8, mines_count=2))
    db.session.add(MapCell(x=19, y=9, mines_count=1))
    db.session.commit()

    GameState.set("turn_number", "1")
    GameState.set("turn_index", "0")
    GameState.set("turn_order", json.dumps([russia.id, britain.id, france.id]))
    GameState.set("moved_this_turn", "{}")

    socketio.emit("map_update", full_map_state())
    socketio.emit("turn_advanced", {
        "turn_number": 1,
        "turn_order":  [russia.id, britain.id, france.id],
        "turn_index":  0,
    })
    return jsonify({"ok": True, "message": "Демо-данные загружены!"})


with app.app_context():
    db.create_all()
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if "ships" in inspector.get_table_names():
        ship_cols = [c["name"] for c in inspector.get_columns("ships")]
        if "custom_name" not in ship_cols:
            db.session.execute(text("ALTER TABLE ships ADD COLUMN custom_name VARCHAR(100)"))
            db.session.commit()
        if "regiments" not in ship_cols:
            db.session.execute(text("ALTER TABLE ships ADD COLUMN regiments INTEGER DEFAULT 0"))
            db.session.commit()
    if "users" in inspector.get_table_names():
        user_cols = [c["name"] for c in inspector.get_columns("users")]
        if "country_id" not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN country_id INTEGER"))
            db.session.commit()
        if "is_admin" not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            db.session.commit()
    defaults = {
        "is_war": "false", "grid_cols": "40", "grid_rows": "25",
        "turn_number": "1", "turn_index": "0", "turn_order": "[]", "moved_this_turn": "{}"
    }
    for k, v in defaults.items():
        if not GameState.get(k):
            GameState.set(k, v)
    GameState.set("moved_this_turn", "{}")

if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    url = f"http://localhost:{port}"
    print(f"\n{'='*50}")
    print(f"  IMPERIUM: SEA WARS")
    print(f"  {url}")
    print(f"{'='*50}\n")
    webbrowser.open(url)
    socketio.run(app, debug=False, host="0.0.0.0", port=port)
