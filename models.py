from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import json
from datetime import datetime

db = SQLAlchemy()

SHIP_STATS = {
    "Дредноут":       {"armor": 1000, "attack": 500, "speed": 2, "capacity": 0, "mine_immune": True},
    "Линейный крейсер": {"armor": 500,  "attack": 250, "speed": 3, "capacity": 0, "can_retreat": True},
    "Эсминец":        {"armor": 300,  "attack": 150, "speed": 4, "capacity": 3, "can_demine": True},
    "Канонерка":      {"armor": 200,  "attack": 100, "speed": 4, "capacity": 5, "can_mine": True},
    "Конвой":         {"armor": 50,   "attack": 10,  "speed": 5, "capacity": 7},
}

SHIP_ORDER = ["Конвой", "Канонерка", "Эсминец", "Линейный крейсер", "Дредноут"]

SHIP_LIMITS = {
    "Дредноут":         {1: 7, 2: 5},
    "Линейный крейсер": {1: 7, 2: 5, 3: 3},
    "Эсминец":          {1: 10, 2: 7, 3: 5, 4: 2},
    "Канонерка":        {1: 10, 2: 7, 3: 5, 4: 2},
    "Конвой":           {1: 10, 2: 10, 3: 7, 4: 5},
}

MINE_DAMAGE = 150
FORT_ARMOR_BONUS = 500
FORT_RADIUS = 2


class Country(db.Model):
    __tablename__ = "countries"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), unique=True, nullable=False)
    color       = db.Column(db.String(10), default="#FF0000")
    flag_emoji  = db.Column(db.String(10), default="🏴")
    order_level = db.Column(db.Integer, default=1)
    balance     = db.Column(db.Integer, default=0)
    is_war      = db.Column(db.Boolean, default=False)

    fleets      = db.relationship("Fleet", backref="country", lazy=True, cascade="all,delete")
    enemies     = db.relationship(
        "CountryRelation",
        primaryjoin="Country.id == CountryRelation.country_a_id",
        lazy=True, cascade="all,delete"
    )

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "color": self.color,
            "flag_emoji": self.flag_emoji, "order_level": self.order_level,
            "balance": self.balance, "is_war": self.is_war
        }


class CountryRelation(db.Model):
    __tablename__ = "country_relations"
    id           = db.Column(db.Integer, primary_key=True)
    country_a_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    country_b_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    at_war       = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("country_a_id", "country_b_id", name="uq_relation_pair"),)


class Fleet(db.Model):
    __tablename__ = "fleets"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    pos_x      = db.Column(db.Integer, default=0)
    pos_y      = db.Column(db.Integer, default=0)
    ships      = db.relationship("Ship", backref="fleet", lazy=True, cascade="all,delete")

    def min_speed(self):
        alive = [s for s in self.ships if s.is_alive]
        if not alive:
            return 0
        return min(SHIP_STATS[s.ship_type]["speed"] for s in alive)

    def flagship(self):
        alive = [s for s in self.ships if s.is_alive]
        if not alive:
            return None
        return max(alive, key=lambda s: SHIP_STATS[s.ship_type]["armor"])

    def total_armor(self):
        return sum(s.current_armor for s in self.ships if s.is_alive)

    def total_attack(self):
        return sum(SHIP_STATS[s.ship_type]["attack"] for s in self.ships if s.is_alive)

    def total_regiments(self):
        return sum(s.regiments or 0 for s in self.ships if s.is_alive)

    def is_alive(self):
        return any(s.is_alive for s in self.ships)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "country_id": self.country_id,
            "pos_x": self.pos_x, "pos_y": self.pos_y,
            "country": self.country.to_dict() if self.country else None,
            "ships": [s.to_dict() for s in self.ships],
            "min_speed": self.min_speed(),
            "total_armor": self.total_armor(),
            "total_attack": self.total_attack(),
            "total_regiments": self.total_regiments(),
            "is_alive": self.is_alive(),
        }


class Ship(db.Model):
    __tablename__ = "ships"
    id           = db.Column(db.Integer, primary_key=True)
    fleet_id     = db.Column(db.Integer, db.ForeignKey("fleets.id"), nullable=False)
    ship_type    = db.Column(db.String(50), nullable=False)
    custom_name  = db.Column(db.String(100), nullable=True)
    current_armor = db.Column(db.Integer, nullable=False)
    regiments    = db.Column(db.Integer, default=0)
    is_alive     = db.Column(db.Boolean, default=True)

    def display_name(self):
        return self.custom_name or self.ship_type

    def to_dict(self):
        stats = SHIP_STATS.get(self.ship_type, {})
        capacity = stats.get("capacity", 0)
        return {
            "id": self.id, "fleet_id": self.fleet_id,
            "ship_type": self.ship_type,
            "custom_name": self.custom_name,
            "display_name": self.display_name(),
            "max_armor": stats.get("armor", 0),
            "current_armor": self.current_armor,
            "attack": stats.get("attack", 0),
            "speed": stats.get("speed", 0),
            "capacity": capacity,
            "regiments": self.regiments or 0,
            "is_alive": self.is_alive,
        }


class MapCell(db.Model):
    __tablename__ = "map_cells"
    id           = db.Column(db.Integer, primary_key=True)
    x            = db.Column(db.Integer, nullable=False)
    y            = db.Column(db.Integer, nullable=False)
    mines_count  = db.Column(db.Integer, default=0)
    fort_owner_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=True)
    __table_args__ = (db.UniqueConstraint("x", "y", name="uq_cell_xy"),)

    def to_dict(self):
        return {
            "x": self.x, "y": self.y,
            "mines_count": self.mines_count,
            "fort_owner_id": self.fort_owner_id,
        }


class BattleLog(db.Model):
    __tablename__ = "battle_logs"
    id         = db.Column(db.Integer, primary_key=True)
    cell_x     = db.Column(db.Integer)
    cell_y     = db.Column(db.Integer)
    log_json   = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "cell_x": self.cell_x, "cell_y": self.cell_y,
            "log": json.loads(self.log_json) if self.log_json else [],
            "created_at": self.created_at.isoformat()
        }


class GameState(db.Model):
    __tablename__ = "game_state"
    id       = db.Column(db.Integer, primary_key=True)
    key      = db.Column(db.String(50), unique=True)
    value    = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        row = GameState.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = GameState.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = GameState(key=key, value=str(value))
            db.session.add(row)
        db.session.commit()


class User(db.Model):
    __tablename__ = "users"
    id              = db.Column(db.Integer, primary_key=True)
    username        = db.Column(db.String(50), unique=True, nullable=False)
    password_hash   = db.Column(db.String(128), nullable=False)
    display_name    = db.Column(db.String(100), default="")
    country_id      = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=True)
    is_admin        = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    last_login      = db.Column(db.DateTime)

    games_played    = db.Column(db.Integer, default=0)
    games_won       = db.Column(db.Integer, default=0)
    total_battles   = db.Column(db.Integer, default=0)
    ships_sunk      = db.Column(db.Integer, default=0)
    ships_lost      = db.Column(db.Integer, default=0)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self, full=False):
        d = {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "country_id": self.country_id,
            "is_admin": getattr(self, "is_admin", False),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
        if full:
            d.update({
                "games_played": self.games_played or 0,
                "games_won": self.games_won or 0,
                "total_battles": self.total_battles or 0,
                "ships_sunk": self.ships_sunk or 0,
                "ships_lost": self.ships_lost or 0,
            })
        return d
