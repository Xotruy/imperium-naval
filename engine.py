"""
Боевой движок для Imperium: Sea Wars
Исправления:
  - Мины НЕ исчезают после боя (только после срабатывания)
  - Эсминец разминирует без урона
  - Линейный крейсер может отступить
  - Урон распределяется от меньших кораблей к большим
"""
import json
from models import db, Fleet, Ship, MapCell, BattleLog, CountryRelation, Country, User, GameState, SHIP_STATS, SHIP_ORDER, MINE_DAMAGE, FORT_ARMOR_BONUS, FORT_RADIUS


def are_at_war(country_a_id: int, country_b_id: int) -> bool:
    rel = CountryRelation.query.filter(
        ((CountryRelation.country_a_id == country_a_id) & (CountryRelation.country_b_id == country_b_id)) |
        ((CountryRelation.country_a_id == country_b_id) & (CountryRelation.country_b_id == country_a_id))
    ).first()
    return rel.at_war if rel else False


def get_or_create_cell(x: int, y: int) -> MapCell:
    cell = MapCell.query.filter_by(x=x, y=y).first()
    if not cell:
        cell = MapCell(x=x, y=y, mines_count=0)
        db.session.add(cell)
        db.session.flush()
    return cell


def apply_mine_damage(fleet: Fleet, cell: MapCell, log_lines: list) -> int:
    if cell.mines_count == 0:
        return 0

    flagship = fleet.flagship()
    if not flagship:
        return 0

    stats = SHIP_STATS[flagship.ship_type]
    if stats.get("mine_immune"):
        log_lines.append(f"💥 Флот «{fleet.name}» входит в заминированную клетку — "
                         f"«{flagship.ship_type}» имеет иммунитет к минам!")
        log_lines.append(f"🧹 Мины в клетке {cell.x},{cell.y} не сработали (иммунитет флагмана). Мины сохранены.")
        return 0

    total_mine_dmg = MINE_DAMAGE * cell.mines_count
    log_lines.append(f"💣 В клетке {cell.x},{cell.y} обнаружено мин: {cell.mines_count}. "
                     f"Урон от мин: {total_mine_dmg} — наносится флагману «{flagship.ship_type}» флота «{fleet.name}».")
    flagship.current_armor -= total_mine_dmg
    if flagship.current_armor <= 0:
        flagship.current_armor = 0
        flagship.is_alive = False
        log_lines.append(f"☠️ Флагман «{flagship.ship_type}» потоплен минами!")
    else:
        log_lines.append(f"🔴 Флагман «{flagship.ship_type}» получил урон, осталось брони: {flagship.current_armor}.")

    cell.mines_count = 0
    log_lines.append(f"🧹 Мины в клетке {cell.x},{cell.y} сработали и уничтожены.")
    return total_mine_dmg


def apply_mine_damage_to_ship(ship: Ship, cell: MapCell, fleet_name: str, log_lines: list) -> int:
    if cell.mines_count == 0:
        return 0

    stats = SHIP_STATS[ship.ship_type]
    if stats.get("mine_immune"):
        log_lines.append(f"💥 «{ship.ship_type}» флота «{fleet_name}» входит в заминированную клетку — "
                         f"имеет иммунитет к минам!")
        log_lines.append(f"🧹 Мины в клетке {cell.x},{cell.y} не сработали. Мины сохранены.")
        return 0

    total_mine_dmg = MINE_DAMAGE * cell.mines_count
    log_lines.append(f"💣 «{ship.ship_type}» флота «{fleet_name}» входит в клетку {cell.x},{cell.y} — "
                     f"мин: {cell.mines_count}, урон: {total_mine_dmg}.")
    ship.current_armor -= total_mine_dmg
    if ship.current_armor <= 0:
        ship.current_armor = 0
        ship.is_alive = False
        log_lines.append(f"☠️ «{ship.ship_type}» потоплен минами!")
    else:
        log_lines.append(f"🔴 «{ship.ship_type}» получил урон, осталось брони: {ship.current_armor}.")

    cell.mines_count = 0
    log_lines.append(f"🧹 Мины в клетке {cell.x},{cell.y} сработали и уничтожены.")
    return total_mine_dmg


def wrap_distance(x1, y1, x2, y2, grid_cols, grid_rows):
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    dx = min(dx, grid_cols - dx)
    dy = min(dy, grid_rows - dy)
    return max(dx, dy)


def demine_cell(cell: MapCell, log_lines: list):
    if cell.mines_count == 0:
        return
    count = cell.mines_count
    cell.mines_count = 0
    log_lines.append(f"🧹 Эсминец разминировал клетку [{cell.x},{cell.y}]. Обезврежено мин: {count}.")


def distribute_damage(fleet: Fleet, damage: int, log_lines: list):
    if damage <= 0:
        return
    log_lines.append(f"⚔️ Флот «{fleet.name}» получает {damage} урона (от слабых к сильным).")
    remaining = damage
    for ship_type in SHIP_ORDER:
        if remaining <= 0:
            break
        ships_of_type = [s for s in fleet.ships if s.ship_type == ship_type and s.is_alive]
        for ship in ships_of_type:
            if remaining <= 0:
                break
            if ship.current_armor <= remaining:
                remaining -= ship.current_armor
                ship.current_armor = 0
                ship.is_alive = False
                log_lines.append(f"   ☠️ {ship.ship_type} (ID={ship.id}) потоплен.")
            else:
                ship.current_armor -= remaining
                log_lines.append(f"   🔸 {ship.ship_type} (ID={ship.id}) повреждён, осталось брони: {ship.current_armor}.")
                remaining = 0


def resolve_battle(attacker_fleet: Fleet, defender_fleet: Fleet, cell: MapCell) -> dict:
    log_lines = []
    log_lines.append(f"⚓ ══════════════════════════════════════")
    log_lines.append(f"⚓ МОРСКОЙ БОЙ в клетке [{cell.x}, {cell.y}]")
    log_lines.append(f"⚓ «{attacker_fleet.name}» ({attacker_fleet.country.name}) "
                     f"vs «{defender_fleet.name}» ({defender_fleet.country.name})")
    log_lines.append(f"⚓ ══════════════════════════════════════")

    log_lines.append(f"\n📍 ФАЗА 1: МИНЫ")
    apply_mine_damage(attacker_fleet, cell, log_lines)

    log_lines.append(f"\n📍 ФАЗА 2: СИЛЫ")
    att_armor  = attacker_fleet.total_armor()
    att_attack = attacker_fleet.total_attack()
    def_armor  = defender_fleet.total_armor()
    def_attack = defender_fleet.total_attack()

    fort_bonus = 0
    nearby_fort = MapCell.query.filter(
        MapCell.fort_owner_id == defender_fleet.country_id,
        MapCell.x >= cell.x - FORT_RADIUS, MapCell.x <= cell.x + FORT_RADIUS,
        MapCell.y >= cell.y - FORT_RADIUS, MapCell.y <= cell.y + FORT_RADIUS,
    ).first()
    if nearby_fort:
        fort_bonus = FORT_ARMOR_BONUS
        log_lines.append(f"🏰 Клетка [{cell.x},{cell.y}] находится в радиусе крепости «{defender_fleet.country.name}» "
                         f"(крепость в [{nearby_fort.x},{nearby_fort.y}])! "
                         f"Защитник получает +{fort_bonus} к эффективной броне.")

    att_alive_before = sum(1 for s in attacker_fleet.ships if s.is_alive)
    def_alive_before = sum(1 for s in defender_fleet.ships if s.is_alive)

    log_lines.append(f"   Атакующий «{attacker_fleet.name}»: {att_alive_before} кораблей, "
                     f"Броня={att_armor}, Атака={att_attack}")
    log_lines.append(f"   Защитник «{defender_fleet.name}»: {def_alive_before} кораблей, "
                     f"Броня={def_armor}{f' (+{fort_bonus} крепость)' if fort_bonus else ''}, Атака={def_attack}")

    log_lines.append(f"\n📍 ФАЗА 3: ОБМЕН ЗАЛПАМИ")
    log_lines.append(f"   «{attacker_fleet.name}» наносит {att_attack} урона флоту «{defender_fleet.name}».")
    log_lines.append(f"   «{defender_fleet.name}» наносит {def_attack} урона флоту «{attacker_fleet.name}».")

    log_lines.append(f"\n📍 ФАЗА 4: РАСПРЕДЕЛЕНИЕ УРОНА")
    actual_dmg_to_defender = max(0, att_attack - fort_bonus)
    if fort_bonus and att_attack <= fort_bonus:
        log_lines.append(f"   🏰 Атака ({att_attack}) полностью поглощена крепостными укреплениями! Флот защитника не пострадал.")
    elif fort_bonus and att_attack > fort_bonus:
        log_lines.append(f"   🏰 Крепость поглощает {fort_bonus} урона. Остаток {actual_dmg_to_defender} достигает кораблей защитника.")
        distribute_damage(defender_fleet, actual_dmg_to_defender, log_lines)
    else:
        distribute_damage(defender_fleet, att_attack, log_lines)
    distribute_damage(attacker_fleet, def_attack, log_lines)

    log_lines.append(f"\n📍 ИТОГИ БОЯ")
    att_alive_after = sum(1 for s in attacker_fleet.ships if s.is_alive)
    def_alive_after = sum(1 for s in defender_fleet.ships if s.is_alive)

    log_lines.append(f"   «{attacker_fleet.name}»: уцелело {att_alive_after}/{att_alive_before} кораблей.")
    log_lines.append(f"   «{defender_fleet.name}»: уцелело {def_alive_after}/{def_alive_before} кораблей.")

    winner_fleet = None
    can_retreat = False
    if att_alive_after > 0 and def_alive_after == 0:
        winner_fleet = attacker_fleet
        log_lines.append(f"\n🏆 ПОБЕДИТЕЛЬ: «{attacker_fleet.name}» ({attacker_fleet.country.name})!")
    elif def_alive_after > 0 and att_alive_after == 0:
        winner_fleet = defender_fleet
        log_lines.append(f"\n🏆 ПОБЕДИТЕЛЬ: «{defender_fleet.name}» ({defender_fleet.country.name})!")
    elif att_alive_after == 0 and def_alive_after == 0:
        log_lines.append(f"\n💀 ВЗАИМНОЕ УНИЧТОЖЕНИЕ! Оба флота потоплены.")
    else:
        att_has_retreat = any(
            s.is_alive and SHIP_STATS.get(s.ship_type, {}).get("can_retreat")
            for s in attacker_fleet.ships
        )
        if att_has_retreat:
            can_retreat = True
            log_lines.append(f"\n⚖️ БОЙ ПРОДОЛЖАЕТСЯ — атакующий отступает (Линейный крейсер может выйти из боя).")
            winner_fleet = defender_fleet
        else:
            log_lines.append(f"\n⚖️ БОЙ ПРОДОЛЖАЕТСЯ — оба флота выжили. Атакующий отступает.")
            winner_fleet = defender_fleet

    db.session.flush()

    battle = BattleLog(
        cell_x=cell.x, cell_y=cell.y,
        log_json=json.dumps(log_lines, ensure_ascii=False)
    )
    db.session.add(battle)
    db.session.flush()

    return {
        "battle_id": battle.id,
        "log": log_lines,
        "winner_fleet_id": winner_fleet.id if winner_fleet else None,
        "can_retreat": can_retreat,
        "attacker": {
            "fleet_id": attacker_fleet.id,
            "fleet_name": attacker_fleet.name,
            "ships_alive": att_alive_after,
        },
        "defender": {
            "fleet_id": defender_fleet.id,
            "fleet_name": defender_fleet.name,
            "ships_alive": def_alive_after,
        }
    }


def check_and_run_battles(moved_fleet: Fleet, x: int, y: int, demine_first: bool = False) -> list:
    cell = get_or_create_cell(x, y)

    if demine_first and cell.mines_count > 0:
        has_destroyer = any(
            s.is_alive and SHIP_STATS.get(s.ship_type, {}).get("can_demine")
            for s in moved_fleet.ships
        )
        if has_destroyer:
            mine_log = []
            demine_cell(cell, mine_log)
            if mine_log:
                mine_battle = BattleLog(
                    cell_x=x, cell_y=y,
                    log_json=json.dumps(mine_log, ensure_ascii=False)
                )
                db.session.add(mine_battle)
                db.session.flush()

    if cell.mines_count > 0:
        has_destroyer = any(
            s.is_alive and SHIP_STATS.get(s.ship_type, {}).get("can_demine")
            for s in moved_fleet.ships
        )
        if not has_destroyer:
            mine_log = []
            apply_mine_damage(moved_fleet, cell, mine_log)
            if mine_log:
                mine_battle = BattleLog(
                    cell_x=x, cell_y=y,
                    log_json=json.dumps(mine_log, ensure_ascii=False)
                )
                db.session.add(mine_battle)
                db.session.flush()

    enemy_fleets = Fleet.query.filter(
        Fleet.pos_x == x,
        Fleet.pos_y == y,
        Fleet.id != moved_fleet.id,
        Fleet.country_id != moved_fleet.country_id
    ).all()

    results = []
    for enemy in enemy_fleets:
        if not are_at_war(moved_fleet.country_id, enemy.country_id):
            continue
        if not enemy.is_alive():
            continue
        result = resolve_battle(moved_fleet, enemy, cell)
        results.append(result)

        if result["winner_fleet_id"] == enemy.id:
            break
    return results


def check_victory():
    countries = Country.query.all()
    if len(countries) < 2:
        return None

    alive_countries = []
    for c in countries:
        has_ships = Ship.query.join(Fleet).filter(
            Fleet.country_id == c.id,
            Ship.is_alive == True
        ).first()
        if has_ships:
            alive_countries.append(c)

    if len(alive_countries) == 0:
        return {"draw": True, "eliminated": [], "alive_count": 0}

    if len(alive_countries) == 1:
        winner = alive_countries[0]
        all_countries = [c.id for c in countries]
        losers = [cid for cid in all_countries if cid != winner.id]

        for user in User.query.all():
            if user.country_id == winner.id:
                user.games_won = (user.games_won or 0) + 1
            if user.country_id in losers or user.country_id == winner.id:
                user.games_played = (user.games_played or 0) + 1

        db.session.commit()

        is_war = GameState.get("is_war", "false") == "true"
        GameState.set("is_war", "false")

        return {
            "winner_country_id": winner.id,
            "winner_name": winner.name,
            "winner_emoji": winner.flag_emoji,
            "winner_color": winner.color,
        }

    eliminated = []
    for c in countries:
        has_ships = Ship.query.join(Fleet).filter(
            Fleet.country_id == c.id,
            Ship.is_alive == True
        ).first()
        if not has_ships:
            eliminated.append({"id": c.id, "name": c.name, "flag_emoji": c.flag_emoji})

    return {"eliminated": eliminated, "alive_count": len(alive_countries)}
