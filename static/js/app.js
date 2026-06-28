/* ═══════════════════════════════════════════════════════
   IMPERIUM: SEA WARS — Frontend App (Fixed + Enhanced)
   Fixes:
   1. Mine/Fort placement buttons now correctly visible/hidden
   2. Demining requires Destroyer in fleet (validated client+server)
   3. Individual ship movement (select ship, then move only that ship)
   4. Movement distance bug fixed (Chebyshev distance, no teleport)
   5. Turn system added (each country gets one move per turn)
═══════════════════════════════════════════════════════ */

const S = {
  sessionId:    null,
  playerName:   null,
  countryId:    null,
  isSpectator:  false,
  isAdmin:      false,
  authToken:    null,
  userId:       null,

  isWar:        false,
  gridCols:     40,
  gridRows:     25,

  fleets:       [],
  cells:        [],
  countries:    [],
  players:      [],
  relations:    [],

  selectedFleetId:  null,
  selectedShipId:   null,   // FIX: individual ship selection
  movingFleetId:    null,
  movingShipId:     null,   // FIX: individual ship movement mode

  // FIX: Turn system
  turnNumber:       1,
  currentTurnOrder: [],     // array of countryId in turn order
  turnIndex:        0,      // whose turn it is
  movedThisTurn:    {},     // { fleetId: true } — fleets that moved this turn
  shipMovedThisTurn:{},     // { shipId: true }

  adminToolMode: null,  // "demine" | "fort" | null

  offsetX: 0, offsetY: 0,
  scale:   1,
  cellW:   0, cellH:   0,
  imgLoaded: false,
  dragging:  false,
  dragStart: { x: 0, y: 0 },
  lastOffset: { x: 0, y: 0 },
  hoverCell:  { x: -1, y: -1 },

  animations: [],  // { fleetId, fromX, fromY, toX, toY, startTime, duration, trail: [{x,y,t}] }
};

const canvas  = document.getElementById("mapCanvas");
const ctx     = canvas.getContext("2d");
const mapImg  = new Image();
let   animId  = null;

function esc(s) {
  if (s == null) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#x27;");
}

const socket = io({ transports: ["websocket"] });

socket.on("connect", () => {
  if (S.sessionId) {
    socket.emit("rejoin", { session_id: S.sessionId, country_id: S.countryId });
  }
});

socket.on("session_init", (data) => {
  S.sessionId = data.session_token || data.session_id;
  S.players   = data.players || [];
  renderPlayerList();
  updateOnlineCount();
});

socket.on("players_update", (data) => {
  S.players = data.players || [];
  renderPlayerList();
  updateOnlineCount();
});

socket.on("map_update", (data) => {
  S.fleets = data.fleets || [];
  S.cells  = data.cells  || [];
  renderFleetList();
  renderFleetDetail();
  drawFrame();
});

socket.on("state_update", (data) => {
  if ("is_war" in data) {
    S.isWar = data.is_war;
    updateWarUI();
  }
  // FIX: sync turn state from server
  if ("turn_number" in data)     S.turnNumber       = data.turn_number;
  if ("current_turn_order" in data) S.currentTurnOrder = data.current_turn_order;
  if ("turn_index" in data)      S.turnIndex        = data.turn_index;
  if ("moved_this_turn" in data) S.movedThisTurn    = data.moved_this_turn || {};
  renderTurnUI();
  renderFleetDetail();
  drawFrame();
});

socket.on("battle_result", (data) => {
  showBattleModal(data);
});

socket.on("game_victory", (data) => {
  const modal = document.getElementById("victoryModal");
  const emoji = document.getElementById("victoryEmoji");
  const text  = document.getElementById("victoryText");
  emoji.textContent = data.winner_emoji || "\uD83C\uDFC6";
  const color = esc(data.winner_color || '#c9a84c');
  const eName = esc(data.winner_name || "");
  const eEmoji = esc(data.winner_emoji || "");
  text.innerHTML = `<span style="color:${color}">${eEmoji} ${eName}</span> победила! Все враги уничтожены.`;
  modal.style.display = "flex";
});

socket.on("chat_message", (data) => {
  showToast(`💬 ${data.name}: ${data.text}`, "info");
});

// FIX: Turn advance broadcast
socket.on("turn_advanced", (data) => {
  S.turnNumber       = data.turn_number;
  S.currentTurnOrder = data.turn_order;
  S.turnIndex        = data.turn_index;
  S.movedThisTurn    = {};
  S.shipMovedThisTurn= {};
  renderTurnUI();
  renderFleetList();
  renderFleetDetail();
  drawFrame();
  const activeCountry = S.countries.find(c => c.id === S.currentTurnOrder[S.turnIndex]);
  showToast(`⚓ Ход ${data.turn_number}: очередь ${activeCountry ? activeCountry.name : "?"}`, "info");
});

function updateOnlineCount() {
  const cnt = S.players.filter(p => p.online).length;
  const el = document.getElementById("onlineCount");
  if (el) el.textContent = `${cnt} онлайн`;
}

// ── INIT ───────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  const st = await api("/api/state");
  S.isWar    = st.is_war;
  S.gridCols = st.grid_cols;
  S.gridRows = st.grid_rows;
  // FIX: load turn state
  if (st.turn_number)       S.turnNumber       = st.turn_number;
  if (st.turn_order)        S.currentTurnOrder = st.turn_order;
  if (st.turn_index !== undefined) S.turnIndex = st.turn_index;
  if (st.moved_this_turn)   S.movedThisTurn    = st.moved_this_turn || {};
  updateWarUI();

  S.countries  = await api("/api/countries");
  S.relations  = await api("/api/relations");

  resizeCanvas();
  window.addEventListener("resize", () => { resizeCanvas(); drawFrame(); });

  mapImg.onload = () => { S.imgLoaded = true; fitMapToCanvas(); drawFrame(); };
  mapImg.onerror = () => { S.imgLoaded = false; drawFrame(); };
  mapImg.src = "/static/img/map.png";

  setupCanvasEvents();
  buildShipFormRows();
  renderTurnUI();

  const saved = localStorage.getItem("imp_session");
  if (saved) {
    try {
      const s = JSON.parse(saved);
      S.authToken  = s.token || null;
      S.playerName = s.name;
      S.countryId  = s.countryId;
      S.isSpectator = s.spectator || false;
      S.sessionId  = s.sessionId || null;
      S.isAdmin    = false;
      S.userId     = s.userId || null;
      if (S.authToken) {
        verifyToken();
      } else {
        applySession();
      }
    } catch { showLoginModal(); }
  } else {
    showLoginModal();
  }
});

async function verifyToken() {
  const res = await api("/api/auth/me");
  if (res.ok && res.user) {
    S.userId = res.user.id;
    S.playerName = res.user.display_name || res.user.username;
    S.isAdmin = res.user.is_admin || false;
    applySession();
  } else {
    S.authToken = null;
    localStorage.removeItem("imp_session");
    showLoginModal();
  }
}

function applySession() {
  socket.emit("join_session", {
    name:        S.playerName,
    country_id:  S.countryId,
    is_spectator: S.isSpectator,
    token:       S.authToken,
  });
  updateAdminUI();
  updatePlayerBadge();
  renderFleetList();
  renderAdminCountries();
  renderRelationMatrix();
  renderFleetDetail();
  renderTurnUI();
}

function updateAdminUI() {
  document.querySelectorAll(".admin-only").forEach(el => {
    el.style.display = S.isAdmin ? "" : "none";
  });
}

// ── CANVAS ─────────────────────────────────────────────
function resizeCanvas() {
  const container = document.getElementById("mapContainer");
  canvas.width  = container.clientWidth;
  canvas.height = container.clientHeight;
}

function fitMapToCanvas() {
  if (!S.imgLoaded) return;
  S.scale   = 1;
  S.offsetX = 0;
  S.offsetY = 0;
  computeCellSize();
}

function computeCellSize() {
  S.cellW = canvas.width  / S.gridCols;
  S.cellH = canvas.height / S.gridRows;
}

function drawFrame() {
  if (animId) cancelAnimationFrame(animId);
  animId = requestAnimationFrame(_draw);
}

function _draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  computeCellSize();
  let cw = S.cellW * S.scale, ch = S.cellH * S.scale;

  ctx.save();
  const offsetX = (canvas.width - cw * S.gridCols) / 2 + S.offsetX;
  const offsetY = (canvas.height - ch * S.gridRows) / 2 + S.offsetY;
  ctx.translate(offsetX, offsetY);

  if (S.imgLoaded) {
    ctx.drawImage(mapImg, 0, 0, canvas.width, canvas.height);
  } else {
    ctx.fillStyle = "#060d1a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  ctx.save();
  ctx.strokeStyle = "rgba(30,90,160,0.35)";
  ctx.lineWidth = 0.5;
  for (let x = 0; x <= S.gridCols; x++) {
    ctx.beginPath(); ctx.moveTo(x * cw, 0); ctx.lineTo(x * cw, canvas.height); ctx.stroke();
  }
  for (let y = 0; y <= S.gridRows; y++) {
    ctx.beginPath(); ctx.moveTo(0, y * ch); ctx.lineTo(canvas.width, y * ch); ctx.stroke();
  }
  ctx.restore();

  ctx.save();
  ctx.fillStyle = "rgba(201,168,76,0.5)";
  ctx.font = `${Math.max(8, Math.min(11, cw * 0.3))}px 'Share Tech Mono', monospace`;
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  for (let x = 0; x < S.gridCols; x += 5) {
    for (let y = 0; y < S.gridRows; y += 5) {
      ctx.fillText(`${x},${y}`, x * cw + 2, y * ch + 2);
    }
  }
  ctx.restore();

  // FIX: show move range for fleet OR individual ship
  const movingId = S.movingFleetId || S.movingShipId;
  if (movingId) {
    let spd, fromX, fromY;
    if (S.movingFleetId) {
      const mf = S.fleets.find(f => f.id === S.movingFleetId);
      if (mf) { spd = S.isWar ? mf.min_speed : 999; fromX = mf.pos_x; fromY = mf.pos_y; }
    } else if (S.movingShipId) {
      // Find which fleet this ship is in
      for (const f of S.fleets) {
        const sh = (f.ships || []).find(s => s.id === S.movingShipId && s.is_alive);
        if (sh) {
          const shipStats = { "Дредноут": 2, "Линейный крейсер": 3, "Эсминец": 4, "Канонерка": 4, "Конвой": 5 };
          spd = S.isWar ? (shipStats[sh.ship_type] || 3) : 999;
          fromX = f.pos_x; fromY = f.pos_y;
          break;
        }
      }
    }
    if (spd !== undefined) {
      ctx.save();
      for (let dx = -spd; dx <= spd; dx++) {
        for (let dy = -spd; dy <= spd; dy++) {
          let tx2 = fromX + dx, ty2 = fromY + dy;
          if (tx2 < 0) tx2 += S.gridCols;
          if (tx2 >= S.gridCols) tx2 -= S.gridCols;
          if (ty2 < 0) ty2 += S.gridRows;
          if (ty2 >= S.gridRows) ty2 -= S.gridRows;
          // Chebyshev distance with wrap
          let ddx = Math.abs(dx), ddy = Math.abs(dy);
          ddx = Math.min(ddx, S.gridCols - ddx);
          ddy = Math.min(ddy, S.gridRows - ddy);
          if (Math.max(ddx, ddy) > spd) continue;
          ctx.fillStyle = S.movingShipId ? "rgba(150,255,100,0.12)" : "rgba(33,150,243,0.15)";
          ctx.fillRect(tx2 * cw + 1, ty2 * ch + 1, cw - 2, ch - 2);
        }
      }
      ctx.strokeStyle = S.movingShipId ? "rgba(150,255,100,0.8)" : "rgba(33,150,243,0.8)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(fromX * cw, fromY * ch, cw, ch);
      ctx.restore();
    }
  }

  if (S.hoverCell.x >= 0 && S.hoverCell.y >= 0) {
    ctx.save();
    const hx = S.hoverCell.x, hy = S.hoverCell.y;
    if (S.movingFleetId || S.movingShipId) {
      ctx.fillStyle = "rgba(33,150,243,0.3)";
      ctx.strokeStyle = "rgba(33,150,243,1)";
    } else {
      ctx.fillStyle = "rgba(201,168,76,0.08)";
      ctx.strokeStyle = "rgba(201,168,76,0.5)";
    }
    ctx.lineWidth = 1;
    ctx.fillRect(hx * cw, hy * ch, cw, ch);
    ctx.strokeRect(hx * cw + .5, hy * ch + .5, cw - 1, ch - 1);
    ctx.restore();
  }

  for (const cell of S.cells) {
    const px = cell.x * cw, py = cell.y * ch;
    if (cell.mines_count > 0) drawMines(px, py, cw, ch, cell.mines_count);
    if (cell.fort_owner_id) drawFort(px, py, cw, ch, cell.fort_owner_id);
  }

  // draw fleets, highlight ships that moved this turn
  const cellMap = {};
  const animMap = {};
  for (const anim of S.animations) {
    animMap[anim.fleetId] = anim;
  }
  for (const f of S.fleets) {
    if (!f.is_alive) continue;
    let drawX = f.pos_x, drawY = f.pos_y;
    const anim = animMap[f.id];
    if (anim) {
      drawX = anim.fromX + (anim.toX - anim.fromX) * anim.progress;
      drawY = anim.fromY + (anim.toY - anim.fromY) * anim.progress;
    }
    const key = `${drawX.toFixed(2)},${drawY.toFixed(2)}`;
    if (!cellMap[key]) cellMap[key] = [];
    cellMap[key].push({ fleet: f, drawX, drawY });
  }
  for (const [key, entries] of Object.entries(cellMap)) {
    const [cx, cy] = key.split(",").map(Number);
    const px = cx * cw, py = cy * ch;
    entries.forEach((entry, i) => {
      const offX = i * Math.min(cw * 0.25, 8);
      const offY = i * Math.min(ch * 0.2, 6);
      drawFleetMarker(entry.fleet, px + offX, py + offY, cw, ch);
    });
  }

  const ch2 = document.getElementById("coordHint");
  if (S.hoverCell.x >= 0) {
    ch2.textContent = `[ ${S.hoverCell.x} , ${S.hoverCell.y} ]`;
  }
  ctx.restore();
}

// ── DRAW HELPERS ───────────────────────────────────────
function drawMines(px, py, cw, ch, count) {
  const cx = px + cw / 2, cy = py + ch / 2;
  const r  = Math.min(cw, ch) * 0.22;
  ctx.save();
  ctx.fillStyle = "rgba(255,183,77,0.15)";
  ctx.fillRect(px, py, cw, ch);
  for (let i = 0; i < count; i++) {
    const ox = count === 1 ? 0 : (i === 0 ? -r * 0.6 : r * 0.6);
    ctx.beginPath();
    ctx.arc(cx + ox, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "#ffb74d";
    ctx.fill();
    ctx.strokeStyle = "#ff8f00"; ctx.lineWidth = 1;
    ctx.stroke();
    for (let a = 0; a < 8; a++) {
      const angle = (a / 8) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(cx + ox + Math.cos(angle) * r, cy + Math.sin(angle) * r);
      ctx.lineTo(cx + ox + Math.cos(angle) * (r + r * 0.55), cy + Math.sin(angle) * (r + r * 0.55));
      ctx.strokeStyle = "#ffb74d"; ctx.lineWidth = 1.2;
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawFort(px, py, cw, ch, ownerId) {
  const country = S.countries.find(c => c.id === ownerId);
  const color   = country ? country.color : "#ffffff";
  ctx.save();
  ctx.fillStyle = hexToRgba(color, 0.15);
  ctx.fillRect(px, py, cw, ch);
  ctx.strokeStyle = color; ctx.lineWidth = 2;
  ctx.strokeRect(px + 2, py + 2, cw - 4, ch - 4);
  const sz = Math.min(cw, ch) * 0.35;
  const mx = px + cw / 2, my = py + ch / 2;
  ctx.fillStyle = color;
  ctx.fillRect(mx - sz/2, my - sz/3, sz, sz * 0.7);
  const bw = sz / 3;
  for (let b = 0; b < 3; b++) {
    ctx.fillRect(mx - sz/2 + b * bw, my - sz/3 - bw * 0.7, bw * 0.7, bw * 0.7);
  }
  ctx.restore();
}

function drawFleetMarker(fleet, px, py, cw, ch) {
  const isSelected = fleet.id === S.selectedFleetId;
  const isMoving   = fleet.id === S.movingFleetId;
  const hasMoved   = S.movedThisTurn[fleet.id];
  const country    = fleet.country || {};
  const color      = country.color || "#ffffff";
  const shipCount  = fleet.ships ? fleet.ships.filter(s => s.is_alive).length : 0;
  const markerSize = Math.min(cw * 0.7, ch * 0.75, 36);
  const mx = px + cw / 2, my = py + ch / 2;

  const anim = S.animations.find(a => a.fleetId === fleet.id);

  ctx.save();
  if (hasMoved && S.isWar) {
    ctx.globalAlpha = 0.45;
  }

  // Glow trail during animation
  if (anim) {
    const glowAlpha = 0.3 * (1 - anim.progress);
    ctx.beginPath();
    ctx.arc(mx, my, markerSize * 0.9, 0, Math.PI * 2);
    ctx.fillStyle = hexToRgba(color, glowAlpha);
    ctx.fill();
    // Wake effect
    const wakeLen = markerSize * 1.5;
    const grad = ctx.createRadialGradient(mx, my, markerSize * 0.3, mx, my, wakeLen);
    grad.addColorStop(0, hexToRgba(color, 0.2));
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(mx, my, wakeLen, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.beginPath();
  ctx.arc(mx, my, markerSize / 2, 0, Math.PI * 2);
  ctx.fillStyle = hexToRgba(color, 0.85);
  ctx.fill();
  ctx.strokeStyle = isSelected ? "#ffffff" : "rgba(255,255,255,0.5)";
  ctx.lineWidth = isSelected ? 2 : 1;
  ctx.stroke();

  const fontSize = Math.max(10, markerSize * 0.45);
  ctx.font = `${fontSize}px serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(country.flag_emoji || "⚓", mx, my);

  if (shipCount > 0) {
    const br = markerSize * 0.27;
    const bx = px + cw - br * 0.6, by = py + br * 0.6;
    ctx.beginPath();
    ctx.arc(bx, by, br, 0, Math.PI * 2);
    ctx.fillStyle = "#0a0e14";
    ctx.fill();
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = `bold ${Math.max(7, br * 1.2)}px Rajdhani, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(shipCount, bx, by + 0.5);
  }

  if (fleet.country_id === S.countryId && !S.isSpectator) {
    ctx.fillStyle = "#c9a84c";
    ctx.font = `bold ${Math.max(7, markerSize * 0.2)}px Share Tech Mono, monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText("YOU", mx, py + 2);
  }

  // FIX: "MOVED" badge in war mode
  if (hasMoved && S.isWar) {
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = "#ef5350";
    ctx.font = `bold ${Math.max(7, markerSize * 0.18)}px Share Tech Mono, monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText("MOVED", mx, py + ch - 2);
  }

  ctx.restore();
}

// ── CANVAS EVENTS ──────────────────────────────────────
function setupCanvasEvents() {
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("click",     onCanvasClick);
  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mouseup",   onMouseUp);
  canvas.addEventListener("mouseleave", () => {
    S.hoverCell = { x: -1, y: -1 };
    drawFrame();
    document.getElementById("tooltip").style.display = "none";
  });
  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    cancelMove();
  });
}

function screenToCell(sx, sy) {
  computeCellSize();
  const cw = S.cellW * S.scale, ch = S.cellH * S.scale;
  const offsetX = (canvas.width - cw * S.gridCols) / 2 + S.offsetX;
  const offsetY = (canvas.height - ch * S.gridRows) / 2 + S.offsetY;
  return {
    x: Math.floor((sx - offsetX) / cw),
    y: Math.floor((sy - offsetY) / ch),
  };
}

function onMouseMove(e) {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  if (S.dragging) {
    S.offsetX = S.lastOffset.x + (e.clientX - S.dragStart.x);
    S.offsetY = S.lastOffset.y + (e.clientY - S.dragStart.y);
    drawFrame();
    return;
  }

  const cell = screenToCell(sx, sy);
  if (cell.x !== S.hoverCell.x || cell.y !== S.hoverCell.y) {
    S.hoverCell = cell;
    drawFrame();
    showCellTooltip(e.clientX, e.clientY, cell.x, cell.y);
  }
}

function onMouseDown(e) {
  if (e.button === 1 || e.button === 2) {
    S.dragging = true;
    S.dragStart = { x: e.clientX, y: e.clientY };
    S.lastOffset = { x: S.offsetX, y: S.offsetY };
    canvas.style.cursor = "grabbing";
  }
}

function onMouseUp(e) {
  S.dragging = false;
  canvas.style.cursor = (S.movingFleetId || S.movingShipId) ? "crosshair" : "default";
}

function onCanvasClick(e) {
  if (S.dragging) return;
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;
  const cell = screenToCell(sx, sy);

  if (S.movingShipId) {
    confirmShipMove(cell.x, cell.y);
    return;
  }
  if (S.movingFleetId) {
    confirmMove(cell.x, cell.y);
    return;
  }

  if (S.adminToolMode === "demine") {
    execAdminDemine(cell.x, cell.y);
    return;
  }
  if (S.adminToolMode === "fort") {
    execAdminRemoveFort(cell.x, cell.y);
    return;
  }

  const fleetHere = S.fleets.find(f =>
    f.pos_x === cell.x && f.pos_y === cell.y && f.is_alive
  );
  if (fleetHere) {
    selectFleet(fleetHere.id);
  } else {
    selectFleet(null);
  }
}

// ── TOOLTIP ────────────────────────────────────────────
function showCellTooltip(mx, my, cx, cy) {
  const tt = document.getElementById("tooltip");
  const fleetsHere = S.fleets.filter(f => f.pos_x === cx && f.pos_y === cy && f.is_alive);
  const cellData   = S.cells.find(c => c.x === cx && c.y === cy);
  const lines = [];

  if (S.adminToolMode === "demine") {
    const mines = cellData ? cellData.mines_count : 0;
    lines.push(`<b>\uD83E\uDDF9 Разминирование [${esc(cx)},${esc(cy)}]</b>`);
    lines.push(`Мин: ${mines}`);
    if (mines === 0) lines.push(`<span style="color:var(--text-dim)">Нет мин — клик бесполезен</span>`);
  } else if (S.adminToolMode === "fort") {
    const fortOwner = cellData && cellData.fort_owner_id ? S.countries.find(c => c.id === cellData.fort_owner_id) : null;
    lines.push(`<b>\uD83C\uDFF0 Снять крепость [${esc(cx)},${esc(cy)}]</b>`);
    lines.push(`Крепость: ${fortOwner ? esc(fortOwner.name) : "нет"}`);
    if (!fortOwner) lines.push(`<span style="color:var(--text-dim)">Нет крепости — клик бесполезен</span>`);
  }

  if (fleetsHere.length) {
    fleetsHere.forEach(f => {
      const c = f.country || {};
      lines.push(`${esc(c.flag_emoji) || "\u2693"} <b>${esc(f.name)}</b>`);
      lines.push(`&nbsp; Броня: ${esc(f.total_armor)} | Атака: ${esc(f.total_attack)}`);
      lines.push(`&nbsp; Кораблей: ${esc(f.ships.filter(s=>s.is_alive).length)}`);
    });
  }
  if (cellData && !S.adminToolMode) {
    if (cellData.mines_count)   lines.push(`\uD83D\uDCA3 Мины: ${esc(cellData.mines_count)}`);
    if (cellData.fort_owner_id) {
      const fc = S.countries.find(c => c.id === cellData.fort_owner_id);
      lines.push(`\uD83C\uDFF0 Крепость: ${fc ? esc(fc.name) : "?"} (+500 брони защитнику)`);
    }
  }

  if (!lines.length) { tt.style.display = "none"; return; }

  tt.innerHTML = lines.join("<br>");
  tt.style.display = "block";
  tt.style.left = (mx + 14) + "px";
  tt.style.top  = (my - 10) + "px";
}

// ── FLEET SELECTION ────────────────────────────────────
function selectFleet(id) {
  S.selectedFleetId = id;
  S.selectedShipId  = null;
  S.movingFleetId   = null;
  S.movingShipId    = null;
  removeMoveHint();
  renderFleetList();
  renderFleetDetail();
  drawFrame();
}

// ── FIX: TURN VALIDATION ───────────────────────────────
function canMove(countryId) {
  if (!S.isWar) return true; // peace: always can move
  if (S.isAdmin) return true;
  if (!S.currentTurnOrder || !S.currentTurnOrder.length) return true;
  const activeCountryId = S.currentTurnOrder[S.turnIndex];
  return activeCountryId === countryId;
}

function isFleetMoved(fleetId) {
  return S.isWar && S.movedThisTurn[fleetId];
}

// ── FLEET MOVEMENT ─────────────────────────────────────
function startMove(fleetId) {
  if (S.isSpectator && !S.isAdmin) {
    showToast("Наблюдатель не может перемещать флоты", "error"); return;
  }
  const fleet = S.fleets.find(f => f.id === fleetId);
  if (!fleet) return;
  if (!S.isAdmin && fleet.country_id !== S.countryId) {
    showToast("Это не ваш флот!", "error"); return;
  }
  // FIX: turn check
  if (!canMove(fleet.country_id)) {
    const activeCountry = S.countries.find(c => c.id === S.currentTurnOrder[S.turnIndex]);
    showToast(`Сейчас ход ${activeCountry ? activeCountry.name : "?"}`, "error"); return;
  }
  // FIX: already moved this turn check
  if (isFleetMoved(fleetId)) {
    showToast("Этот флот уже переместился в этот ход!", "error"); return;
  }

  S.movingFleetId   = fleetId;
  S.movingShipId    = null;
  S.selectedFleetId = fleetId;
  canvas.style.cursor = "crosshair";
  addMoveHint("🚢 Кликните на клетку для перемещения флота   [ПКМ — отмена]");
  drawFrame();
}

function cancelMove() {
  S.movingFleetId = null;
  S.movingShipId  = null;
  S.adminToolMode = null;
  canvas.style.cursor = "default";
  removeMoveHint();
  document.getElementById("btnAdminDemine")?.classList.remove("active");
  document.getElementById("btnAdminFort")?.classList.remove("active");
  drawFrame();
}

// ── FLEET MOVEMENT ANIMATION ───────────────────────────
function startFleetAnimation(fleetId, fromX, fromY, toX, toY) {
  // Handle wrap-around: pick the shorter path
  let dx = toX - fromX, dy = toY - fromY;
  if (Math.abs(dx) > S.gridCols / 2) {
    dx = dx > 0 ? dx - S.gridCols : dx + S.gridCols;
  }
  if (Math.abs(dy) > S.gridRows / 2) {
    dy = dy > 0 ? dy - S.gridRows : dy + S.gridRows;
  }
  const realToX = fromX + dx;
  const realToY = fromY + dy;
  const dist = Math.max(Math.abs(dx), Math.abs(dy));
  const duration = Math.max(200, Math.min(800, dist * 120));

  S.animations.push({
    fleetId, fromX, fromY, toX: realToX, toY: realToY,
    startTime: performance.now(),
    duration,
    progress: 0,
  });
  drawFrame();
  requestAnimationFrame(updateAnimations);
}

function updateAnimations() {
  const now = performance.now();
  let active = false;
  for (const anim of S.animations) {
    const elapsed = now - anim.startTime;
    anim.progress = Math.min(1, elapsed / anim.duration);
    // ease-out
    anim.progress = 1 - Math.pow(1 - anim.progress, 2);
    if (anim.progress < 1) active = true;
  }
  S.animations = S.animations.filter(a => a.progress < 1);
  if (active) {
    drawFrame();
    requestAnimationFrame(updateAnimations);
  }
}

async function confirmMove(tx, ty) {
  if (!S.movingFleetId) return;
  const fid = S.movingFleetId;
  const fleet = S.fleets.find(f => f.id === fid);
  if (!fleet) { cancelMove(); return; }

  // Client-side Chebyshev distance validation with wrap-around
  if (S.isWar) {
    let dx = Math.abs(tx - fleet.pos_x);
    let dy = Math.abs(ty - fleet.pos_y);
    dx = Math.min(dx, S.gridCols - dx);
    dy = Math.min(dy, S.gridRows - dy);
    const dist = Math.max(dx, dy);
    if (dist > fleet.min_speed) {
      showToast(`Слишком далеко! Скорость: ${fleet.min_speed}, расстояние: ${dist}`, "error");
      cancelMove(); return;
    }
  }

  cancelMove();

  try {
    const fromX = fleet.pos_x, fromY = fleet.pos_y;
    const res = await api(`/api/fleets/${fid}/move`, "POST", { x: tx, y: ty });
    if (res.error) { showToast(res.error, "error"); return; }
    startFleetAnimation(fid, fromX, fromY, tx, ty);
    S.movedThisTurn[fid] = true;
    if (fleet && fleet.ships) {
      fleet.ships.forEach(s => {
        if (s.is_alive) S.shipMovedThisTurn[s.id] = true;
      });
    }
    renderTurnUI();
    renderFleetDetail();
    showToast(`Флот перемещён в [${tx}, ${ty}]`, "success");
  } catch (err) {
    showToast(err.message || "Ошибка перемещения", "error");
  }
}

// ── FIX: INDIVIDUAL SHIP MOVEMENT ─────────────────────
function startShipMove(shipId) {
  // Find ship and its fleet
  let shipFleet = null, targetShip = null;
  for (const f of S.fleets) {
    const sh = (f.ships || []).find(s => s.id === shipId && s.is_alive);
    if (sh) { shipFleet = f; targetShip = sh; break; }
  }
  if (!shipFleet || !targetShip) return;

  if (S.isSpectator && !S.isAdmin) {
    showToast("Наблюдатель не может перемещать корабли", "error"); return;
  }
  if (!S.isAdmin && shipFleet.country_id !== S.countryId) {
    showToast("Это не ваш корабль!", "error"); return;
  }
  if (!canMove(shipFleet.country_id)) {
    const ac = S.countries.find(c => c.id === S.currentTurnOrder[S.turnIndex]);
    showToast(`Сейчас ход ${ac ? ac.name : "?"}`, "error"); return;
  }
  if (S.isWar && S.shipMovedThisTurn[shipId]) {
    showToast("Этот корабль уже переместился!", "error"); return;
  }

  S.movingShipId    = shipId;
  S.movingFleetId   = null;
  S.selectedShipId  = shipId;
  S.selectedFleetId = shipFleet.id;
  canvas.style.cursor = "crosshair";
  const shipStats = { "Дредноут": 2, "Линейный крейсер": 3, "Эсминец": 4, "Канонерка": 4, "Конвой": 5 };
  const spd = shipStats[targetShip.ship_type] || 3;
  addMoveHint(`⚓ Перемещение: ${targetShip.ship_type} (скорость ${spd})   [ПКМ — отмена]`);
  drawFrame();
}

async function confirmShipMove(tx, ty) {
  if (!S.movingShipId) return;
  const shipId = S.movingShipId;
  let shipFleet = null, targetShip = null;
  for (const f of S.fleets) {
    const sh = (f.ships || []).find(s => s.id === shipId && s.is_alive);
    if (sh) { shipFleet = f; targetShip = sh; break; }
  }
  if (!shipFleet || !targetShip) { cancelMove(); return; }

  // Chebyshev distance for individual ship with wrap-around
  if (S.isWar) {
    const shipStats = { "Дредноут": 2, "Линейный крейсер": 3, "Эсминец": 4, "Канонерка": 4, "Конвой": 5 };
    const spd = shipStats[targetShip.ship_type] || 3;
    let dx = Math.abs(tx - shipFleet.pos_x);
    let dy = Math.abs(ty - shipFleet.pos_y);
    dx = Math.min(dx, S.gridCols - dx);
    dy = Math.min(dy, S.gridRows - dy);
    const dist = Math.max(dx, dy);
    if (dist > spd) {
      showToast(`Слишком далеко! Скорость ${targetShip.ship_type}: ${spd}, расстояние: ${dist}`, "error");
      cancelMove(); return;
    }
  }

  cancelMove();

  try {
    const fromX = shipFleet.pos_x, fromY = shipFleet.pos_y;
    const res = await api(`/api/ships/${shipId}/move`, "POST", { x: tx, y: ty });
    if (res.error) { showToast(res.error, "error"); return; }
    startFleetAnimation(shipFleet.id, fromX, fromY, tx, ty);
    S.shipMovedThisTurn[shipId] = true;
    renderTurnUI();
    showToast(`${targetShip.ship_type} перемещён в [${tx}, ${ty}]`, "success");
  } catch (err) {
    showToast(err.message || "Ошибка перемещения корабля", "error");
  }
}

function addMoveHint(text) {
  removeMoveHint();
  const el = document.createElement("div");
  el.className = "move-hint"; el.id = "moveHint";
  el.textContent = text || "🎯 Кликните на клетку   [ПКМ — отмена]";
  document.getElementById("mapContainer").appendChild(el);
}
function removeMoveHint() {
  document.getElementById("moveHint")?.remove();
}

// ── FIX: TURN SYSTEM ───────────────────────────────────
function renderTurnUI() {
  const el = document.getElementById("turnInfo");
  if (!el) return;

  if (!S.isWar) {
    el.innerHTML = `<div style="color:var(--green);font-size:12px;font-family:var(--mono);">☮ МИРНОЕ ВРЕМЯ — свободное движение</div>`;
    return;
  }

  if (!S.currentTurnOrder || !S.currentTurnOrder.length) {
    el.innerHTML = `<div style="color:var(--text-dim);font-size:12px">Нет стран. Добавьте страны для начала ходов.</div>`;
    return;
  }

  const activeId = S.currentTurnOrder[S.turnIndex % S.currentTurnOrder.length];
  const activeCo = S.countries.find(c => c.id === activeId);
  const isMyTurn = S.countryId && activeId === S.countryId;

  let html = `<div style="font-family:var(--mono);font-size:11px;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">
    ХОД ${S.turnNumber} | ПОРЯДОК ХОДОВ:
  </div>`;

  html += `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">`;
  S.currentTurnOrder.forEach((cid, i) => {
    const co = S.countries.find(c => c.id === cid);
    const isActive = i === (S.turnIndex % S.currentTurnOrder.length);
    const myFleetsMoved = S.fleets
      .filter(f => f.country_id === cid)
      .every(f => S.movedThisTurn[f.id]);
    html += `<div style="
      padding:3px 8px;border-radius:4px;font-size:11px;
      border:1px solid ${isActive ? (co ? co.color : "#fff") : "var(--border)"};
      background:${isActive ? hexToRgba(co ? co.color : "#fff", 0.15) : "transparent"};
      color:${isActive ? (co ? co.color : "#fff") : "var(--text-dim)"};
      font-weight:${isActive ? "700" : "400"};
    ">${co ? co.flag_emoji + " " + co.name : "?"}${myFleetsMoved ? " ✓" : ""}</div>`;
  });
  html += `</div>`;

  if (isMyTurn) {
    html += `<div style="color:var(--gold);font-size:12px;font-weight:700;font-family:var(--mono);margin-bottom:6px">
      ⚡ ВАШ ХОД! Переместите флоты.
    </div>`;
  } else if (activeCo) {
    html += `<div style="color:var(--text-dim);font-size:12px;font-family:var(--mono);margin-bottom:6px">
      Ждём ход: ${activeCo.flag_emoji} ${activeCo.name}
    </div>`;
  }

  // End turn button — only for current player or admin (not spectators)
  if ((isMyTurn || S.isAdmin) && !(S.isSpectator && !S.isAdmin)) {
    html += `<button class="btn btn-sm btn-accent" onclick="endTurn()" style="width:100%">
      ✅ Завершить ход ${S.isAdmin && !isMyTurn ? "(Мастер)" : ""}
    </button>`;
  }

  el.innerHTML = html;
}

async function endTurn() {
  if (S.isSpectator && !S.isAdmin) {
    showToast("Наблюдатель не может завершать ходы", "error"); return;
  }
  const res = await api("/api/turn/end", "POST", {
    country_id: S.countryId || (S.isAdmin ? S.currentTurnOrder[S.turnIndex] : null)
  });
  if (res.error) { showToast(res.error, "error"); return; }
}

// ── FLEET LIST ─────────────────────────────────────────
function renderFleetList() {
  const el = document.getElementById("fleetList");
  if (!el) return;
  const myFleets    = S.countryId ? S.fleets.filter(f => f.country_id === S.countryId) : [];
  const otherFleets = S.fleets.filter(f => f.country_id !== S.countryId);
  const all = [...myFleets, ...otherFleets];

  el.innerHTML = all.map(f => {
    const c   = f.country || {};
    const sel = f.id === S.selectedFleetId ? " selected" : "";
    const dead = !f.is_alive ? " dead" : "";
    const own  = f.country_id === S.countryId;
    const moved = S.isWar && S.movedThisTurn[f.id];
    const aliveCnt = f.ships ? f.ships.filter(s => s.is_alive).length : 0;
    return `<div class="fleet-card${sel}${dead}" onclick="selectFleet(${f.id})" title="${esc(f.name)}">
      ${own ? `<span class="own-badge">МОЙ</span>` : ""}
      ${moved ? `<span style="position:absolute;top:4px;left:6px;font-size:9px;color:#ef5350;font-family:var(--mono)">MOVED</span>` : ""}
      <div class="fleet-card-header">
        <span class="fleet-flag">${esc(c.flag_emoji) || "\u2693"}</span>
        <span class="fleet-name">${esc(f.name)}</span>
      </div>
      <div class="fleet-stats">
        <span class="fleet-stat">\uD83D\uDEE1 ${esc(f.total_armor)}</span>
        <span class="fleet-stat">\u2694\uFE0F ${esc(f.total_attack)}</span>
        <span class="fleet-stat">\uD83D\uDEA2 ${esc(aliveCnt)}</span>
        ${f.total_regiments ? `<span class="fleet-stat">\uD83C\uDFD6 ${esc(f.total_regiments)}</span>` : ''}
        <span class="fleet-coords">[${esc(f.pos_x)},${esc(f.pos_y)}]</span>
      </div>
    </div>`;
  }).join("") || `<div class="empty-hint">Флотов нет.<br>Создайте в управлении.</div>`;
}

// ── FLEET DETAIL ───────────────────────────────────────
function renderFleetDetail() {
  const el = document.getElementById("fleetDetail");
  if (!el) return;
  const fleet = S.fleets.find(f => f.id === S.selectedFleetId);
  if (!fleet) {
    el.innerHTML = `<div class="empty-hint">Выберите флот на карте или в списке</div>`;
    return;
  }
  const c      = fleet.country || {};
  const canCtrl = S.isAdmin || (!S.isSpectator && fleet.country_id === S.countryId);
  const alive  = fleet.ships ? fleet.ships.filter(s => s.is_alive) : [];
  const dead   = fleet.ships ? fleet.ships.filter(s => !s.is_alive) : [];

  // FIX: correct ability checks
  const hasDestroyer = alive.some(s => s.ship_type === "Эсминец");
  const hasGunboat   = alive.some(s => s.ship_type === "Канонерка");
  const cell = S.cells.find(c => c.x === fleet.pos_x && c.y === fleet.pos_y);
  const minesInCell   = cell ? cell.mines_count : 0;
  const canPlaceMine  = hasGunboat && minesInCell < 2;
  // FIX: can demine only if has Destroyer AND there are mines
  const canDemine     = hasDestroyer && minesInCell > 0;
  // can place/remove fort if admin
  const fortHere      = cell ? cell.fort_owner_id : null;

  const fleetMoved = S.isWar && S.movedThisTurn[fleet.id];
  const allShipsMoved = S.isWar && alive.length > 0 && alive.every(s => S.shipMovedThisTurn[s.id]);
  const noShips = alive.length === 0;
  const myTurn     = canMove(fleet.country_id);

  el.innerHTML = `
    <div class="detail-header">
      <span class="detail-flag">${esc(c.flag_emoji) || "\u2693"}</span>
      <div class="detail-info">
        <h3>${esc(fleet.name)}</h3>
        <p>${esc(c.name) || "?"} \u00B7 [${esc(fleet.pos_x)}, ${esc(fleet.pos_y)}]</p>
        ${fleetMoved && S.isWar ? `<p style="color:#ef5350;font-size:10px;font-family:var(--mono)">\u2717 Уже переместился в этот ход</p>` : ""}
      </div>
    </div>
    <div class="detail-stats">
      <div class="stat-box"><div class="sv">${esc(fleet.total_armor)}</div><div class="sl">БРОНЯ</div></div>
      <div class="stat-box"><div class="sv">${esc(fleet.total_attack)}</div><div class="sl">АТАКА</div></div>
      <div class="stat-box"><div class="sv">${esc(fleet.min_speed)}</div><div class="sl">СКОРОСТЬ</div></div>
      <div class="stat-box"><div class="sv">${esc(alive.length)}/${esc(fleet.ships.length)}</div><div class="sl">КОРАБЛИ</div></div>
      ${fleet.total_regiments ? `<div class="stat-box"><div class="sv">${esc(fleet.total_regiments)}</div><div class="sl">ПОЛКИ</div></div>` : ''}
    </div>

    <div style="font-size:10px;color:var(--text-dim);font-family:var(--mono);padding:4px 2px;letter-spacing:1px">СОСТАВ ФЛОТА:</div>
    <table class="ship-table">
      <thead><tr><th>Тип</th><th>Имя</th><th>Броня</th><th>Ур.</th><th>Полки</th><th></th></tr></thead>
      <tbody>
        ${[...alive, ...dead].map(s => {
          const maxA = s.max_armor || 1;
          const pct  = Math.max(0, Math.round((s.current_armor / maxA) * 100));
          const sMoved = S.isWar && (S.shipMovedThisTurn[s.id] || S.movedThisTurn[fleet.id]);
          const canMoveShip = canCtrl && s.is_alive && myTurn && !sMoved && !fleetMoved;
          const displayName = esc(s.custom_name || s.ship_type);
          const cap = s.capacity || 0;
          const reg = s.regiments || 0;
          const regStyle = reg > 0 ? "color:var(--gold)" : "color:var(--text-dim)";
          return `<tr class="${s.is_alive ? (sMoved ? "ship-moved-row" : "") : "dead-row"}">
            <td style="font-size:11px">${esc(s.ship_type)}${sMoved ? ' <span style="color:#ef5350;font-size:9px">\u2713</span>' : ''}</td>
            <td style="font-size:11px">
              <span id="shipName_${s.id}" data-orig="${esc(s.custom_name || s.ship_type)}"
                style="cursor:pointer;border-bottom:1px dashed var(--text-dim);padding:0 2px"
                title="Клик для переименования"
                onclick="startRenameShip(${s.id})">${displayName}</span>
            </td>
            <td>
              <div class="ship-armor-bar"><div class="ship-armor-fill" style="width:${pct}%"></div></div>
              <span style="font-size:10px;margin-left:4px;color:var(--text-dim)">${esc(s.current_armor)}</span>
            </td>
            <td style="font-size:10px;color:var(--text-dim)">${esc(s.attack)}</td>
            <td style="font-size:10px;${regStyle}" ${S.isAdmin && s.is_alive && cap > 0 ? `title="Клик для редактирования полков"` : ""} ${S.isAdmin && s.is_alive && cap > 0 ? `onclick="startEditRegiments(${s.id}, ${cap}, ${reg})"` : ""}>${cap > 0 ? `${esc(reg)}/${esc(cap)}` : "\u2014"}</td>
            <td style="display:flex;gap:2px">
              ${canMoveShip ? `<button class="btn btn-sm btn-ghost" style="padding:1px 5px;font-size:10px" onclick="startShipMove(${s.id})" title="Переместить только этот корабль">\u25B6</button>` : ""}
              ${S.isAdmin && s.is_alive ? `<button class="btn btn-sm btn-red" style="padding:1px 5px;font-size:10px" onclick="deleteShipConfirm(${s.id}, ${fleet.id})" title="Удалить корабль">\u2715</button>` : ""}
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>

    ${canCtrl && !noShips ? `
    <div class="action-btns">
      <button class="btn btn-sm btn-primary"
        onclick="startMove(${fleet.id})"
        ${fleetMoved || allShipsMoved || !myTurn ? "disabled title='Не ваш ход, флот уже ходил или все корабли уже двигались отдельно'" : ""}>
        🚢 Флот
      </button>

      ${canPlaceMine ? `
      <button class="btn btn-sm btn-ghost" onclick="placeMine(${fleet.id}, ${fleet.pos_x}, ${fleet.pos_y})"
        title="Канонерка устанавливает мину в текущей клетке [${fleet.pos_x},${fleet.pos_y}]">
        💣 Поставить мину
      </button>` : `
      <button class="btn btn-sm btn-ghost" disabled
        title="${!hasGunboat ? 'Нет Канонерки в флоте' : minesInCell >= 2 ? 'Максимум мин (2)' : 'Мину нельзя поставить'}">
        💣 Мина ${!hasGunboat ? '(нет Канонерки)' : '(макс)'}
      </button>`}

      ${canDemine ? `
      <button class="btn btn-sm btn-ghost" onclick="demine(${fleet.id}, ${fleet.pos_x}, ${fleet.pos_y})"
        title="Эсминец разминирует клетку [${fleet.pos_x},${fleet.pos_y}]">
        🧹 Разминировать
      </button>` : `
      <button class="btn btn-sm btn-ghost" disabled
        title="${!hasDestroyer ? 'Нет Эсминца в флоте' : 'Нет мин в клетке'}">
        🧹 Деминировать ${!hasDestroyer ? '(нет Эсминца)' : '(нет мин)'}
      </button>`}

      ${fortHere && S.isAdmin ? `
      <button class="btn btn-sm btn-red" onclick="removeFort(${fleet.pos_x}, ${fleet.pos_y})"
        title="Убрать крепость (только для мастера)">
        🏰 Убрать крепость
      </button>` : ""}

      ${minesInCell > 0 && S.isAdmin ? `
      <button class="btn btn-sm btn-red" onclick="adminDemine(${fleet.pos_x}, ${fleet.pos_y})"
        title="Принудительно убрать все мины (только для администратора)">
        🧹 Убрать мины (Адм.)
      </button>` : ""}

      ${S.isAdmin ? `<button class="btn btn-sm btn-red" onclick="deleteFleetConfirm(${fleet.id})" title="Только для администратора">✕ Удалить</button>` : ""}
    </div>` : ""}
  `;
}

// ── PLAYER LIST ────────────────────────────────────────
function renderPlayerList() {
  const el = document.getElementById("playerList");
  if (!el) return;
  if (!S.players || !S.players.length) {
    el.innerHTML = `<div class="empty-hint">Нет игроков онлайн</div>`;
    return;
  }
  el.innerHTML = S.players.map(p => {
    const c = S.countries.find(c => c.id === p.country_id);
    return `<div class="player-row">
      <span class="${p.online ? "online-dot" : "offline-dot"}"></span>
      <span class="player-name">${esc(p.name) || "Наблюдатель"}</span>
      <span class="player-country">${c ? esc(c.flag_emoji) + " " + esc(c.name) : "\uD83D\uDC41 Наблюдатель"}</span>
    </div>`;
  }).join("");
}

// ── WAR TOGGLE ─────────────────────────────────────────
function updateWarUI() {
  const dot   = document.querySelector(".war-toggle .dot");
  const label = document.getElementById("warLabel");
  if (!dot || !label) return;
  if (S.isWar) {
    dot.className = "dot war";
    label.textContent = "ВОЕННОЕ ВРЕМЯ";
    label.style.color = "#ef9a9a";
  } else {
    dot.className = "dot peace";
    label.textContent = "МИРНОЕ ВРЕМЯ";
    label.style.color = "#a5d6a7";
  }
  const ws = document.getElementById("warSwitch");
  if (ws) ws.checked = S.isWar;
  renderTurnUI();
}

async function toggleWar(val) {
  if (S.isSpectator && !S.isAdmin) {
    showToast("Наблюдатель не может менять режим войны", "error");
    updateWarUI();
    return;
  }
  if (!S.isAdmin) {
    showToast("Только администратор может менять режим войны", "error");
    updateWarUI();
    return;
  }
  S.isWar = val;
  updateWarUI();
  await api("/api/state", "POST", { is_war: val });
}

// ── FIX: MINE ACTIONS with proper validation ───────────
async function placeMine(fleetId, x, y) {
  // FIX: client-side validation before server call
  const fleet = S.fleets.find(f => f.id === fleetId);
  if (!fleet) return;
  const hasGunboat = (fleet.ships || []).some(s => s.ship_type === "Канонерка" && s.is_alive);
  if (!hasGunboat) {
    showToast("Нет Канонерки — установить мину невозможно", "error"); return;
  }
  const cell = S.cells.find(c => c.x === x && c.y === y);
  if (cell && cell.mines_count >= 2) {
    showToast("Максимум 2 мины в клетке", "error"); return;
  }
  const res = await api(`/api/cells/${x}/${y}/mine`, "POST", { fleet_id: fleetId });
  if (res.error) showToast(res.error, "error");
  else showToast(`💣 Мина установлена в [${x},${y}]`, "success");
}

async function demine(fleetId, x, y) {
  // FIX: client-side validation
  const fleet = S.fleets.find(f => f.id === fleetId);
  if (!fleet) return;
  const hasDestroyer = (fleet.ships || []).some(s => s.ship_type === "Эсминец" && s.is_alive);
  if (!hasDestroyer) {
    showToast("Нет Эсминца — разминирование невозможно", "error"); return;
  }
  const cell = S.cells.find(c => c.x === x && c.y === y);
  if (!cell || cell.mines_count === 0) {
    showToast("Мин в этой клетке нет", "error"); return;
  }
  const res = await api(`/api/cells/${x}/${y}/demine`, "POST", { fleet_id: fleetId });
  if (res.error) showToast(res.error, "error");
  else showToast(`🧹 Клетка [${x},${y}] разминирована`, "success");
}

// Admin-only: force remove all mines from cell without Destroyer requirement
async function adminDemine(x, y) {
  if (!S.isAdmin) { showToast("Только для администратора", "error"); return; }
  const res = await api(`/api/cells/${x}/${y}/demine`, "POST", {});
  if (res.error) showToast(res.error, "error");
  else showToast(`🧹 Мины убраны администратором [${x},${y}]`, "success");
}

// FIX: Fort removal
async function removeFort(x, y) {
  if (!S.isAdmin) { showToast("Только для мастера", "error"); return; }
  const res = await api(`/api/cells/${x}/${y}/fort`, "POST", { owner_id: null });
  if (res.error) showToast(res.error, "error");
  else { showToast(`🏰 Крепость в [${x},${y}] убрана`, "success"); renderFleetDetail(); }
}

// ── ADMIN TOOL MODE (header buttons) ────────────────────
function toggleAdminTool(mode) {
  if (S.adminToolMode === mode) {
    S.adminToolMode = null;
    canvas.style.cursor = "default";
    removeMoveHint();
    document.getElementById("btnAdminDemine")?.classList.remove("active");
    document.getElementById("btnAdminFort")?.classList.remove("active");
    return;
  }
  S.adminToolMode = mode;
  S.movingFleetId = null;
  S.movingShipId  = null;
  canvas.style.cursor = "crosshair";
  document.getElementById("btnAdminDemine")?.classList.toggle("active", mode === "demine");
  document.getElementById("btnAdminFort")?.classList.toggle("active", mode === "fort");
  const label = mode === "demine" ? "🧹 Кликните на клетку для разминирования   [ПКМ — отмена]"
                                  : "🏰 Кликните на клетку для снятия крепости   [ПКМ — отмена]";
  addMoveHint(label);
  drawFrame();
}

async function execAdminDemine(x, y) {
  const cell = S.cells.find(c => c.x === x && c.y === y);
  if (!cell || cell.mines_count === 0) {
    showToast("Мин в клетке нет", "error"); return;
  }
  const res = await api(`/api/cells/${x}/${y}/demine`, "POST", {});
  if (res.error) showToast(res.error, "error");
  else showToast(`🧹 Мины убраны в [${x},${y}]`, "success");
}

async function execAdminRemoveFort(x, y) {
  const cell = S.cells.find(c => c.x === x && c.y === y);
  if (!cell || !cell.fort_owner_id) {
    showToast("Крепости в клетке нет", "error"); return;
  }
  const res = await api(`/api/cells/${x}/${y}/fort`, "POST", { owner_id: null });
  if (res.error) showToast(res.error, "error");
  else showToast(`🏰 Крепость в [${x},${y}] убрана`, "success");
}

// Place fort — admin only, marks cell as fortified by the fleet's country
async function placeFort(fleetId, x, y) {
  if (!S.isAdmin) { showToast("Только для мастера", "error"); return; }
  const fleet = S.fleets.find(f => f.id === fleetId);
  if (!fleet) return;
  const res = await api(`/api/cells/${x}/${y}/fort`, "POST", { owner_id: fleet.country_id });
  if (res.error) showToast(res.error, "error");
  else { showToast(`🏰 Крепость «${fleet.country?.name || "?"}» возведена в [${x},${y}]`, "success"); renderFleetDetail(); }
}

// ── DELETE FLEET ───────────────────────────────────────
async function deleteFleetConfirm(fid) {
  if (!confirm("Удалить флот?")) return;
  await api(`/api/fleets/${fid}`, "DELETE");
  selectFleet(null);
  showToast("Флот удалён", "info");
}

async function deleteShipConfirm(sid, fid) {
  if (!confirm("Удалить корабль?")) return;
  const res = await api(`/api/ships/${sid}`, "DELETE");
  if (res.error) { showToast(res.error, "error"); return; }
  showToast("Корабль удалён", "info");
  const fleet = S.fleets.find(f => f.id === fid);
  if (fleet && !fleet.ships.some(s => s.is_alive)) {
    selectFleet(null);
  } else {
    renderFleetDetail();
  }
}

function startRenameShip(shipId) {
  const inp = document.getElementById(`shipName_${shipId}`);
  if (!inp) return;
  inp.contentEditable = true;
  inp.focus();
  const sel = window.getSelection();
  sel.selectAllChildren(inp);
  inp.onblur = () => finishRenameShip(shipId, inp.textContent.trim());
  inp.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    if (e.key === "Escape") { inp.textContent = inp.dataset.orig || ""; inp.blur(); }
  };
}

async function finishRenameShip(shipId, name) {
  try {
    const res = await api(`/api/ships/${shipId}/rename`, "POST", { name });
    if (res.error) { showToast(res.error, "error"); return; }
    renderFleetDetail();
  } catch (e) {
    showToast("Ошибка переименования", "error");
  }
}

function startEditRegiments(shipId, capacity, current) {
  if (!S.isAdmin) return;
  const el = document.getElementById(`shipName_${shipId}`);
  if (!el) return;
  const parent = el.closest("td");
  if (!parent) return;
  const origHTML = parent.innerHTML;
  parent.innerHTML = `<input type="number" id="regInput_${shipId}" value="${current}" min="0" max="${capacity}" style="width:45px;font-size:11px;background:var(--bg-card);color:var(--gold);border:1px solid var(--gold);border-radius:3px;padding:1px 3px" /> <span style="font-size:9px;color:var(--text-dim)">/ ${capacity}</span>`;
  const inp = parent.querySelector("input");
  inp.focus();
  inp.select();
  inp.onblur = () => saveRegiments(shipId, parseInt(inp.value) || 0);
  inp.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    if (e.key === "Escape") { parent.innerHTML = origHTML; }
  };
}

async function saveRegiments(shipId, value) {
  try {
    const res = await api(`/api/ships/${shipId}/regiments`, "POST", { regiments: value });
    if (res.error) { showToast(res.error, "error"); }
    renderFleetDetail();
  } catch (e) {
    showToast("Ошибка обновления полков", "error");
  }
}

// ── BATTLE MODAL ───────────────────────────────────────
function showBattleModal(data) {
  const modal = document.getElementById("battleModal");
  const scroll = document.getElementById("battleLogScroll");
  scroll.innerHTML = "";
  modal.style.display = "flex";
  typeLines(data.log || [], scroll, 0);
}

function typeLines(lines, container, idx) {
  if (idx >= lines.length) return;
  const line = lines[idx];
  const el   = document.createElement("div");
  el.className = "log-line " + classifyLogLine(line);
  el.textContent = line;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  setTimeout(() => typeLines(lines, container, idx + 1), 40);
}

function classifyLogLine(line) {
  if (line.includes("══"))     return "header";
  if (line.includes("ФАЗА"))   return "phase";
  if (line.includes("☠️"))    return "death";
  if (line.includes("💣") || line.includes("💥") || line.includes("мин")) return "mine";
  if (line.includes("🏆"))     return "win";
  if (line.includes("урон") || line.includes("🔴") || line.includes("🔸")) return "damage";
  return "info";
}

function closeBattleModal() {
  document.getElementById("battleModal").style.display = "none";
}

// ── PANELS ─────────────────────────────────────────────
function openPanel(name) {
  closeAllPanels();
  if (name === "admin")    { loadAdminPanel(); document.getElementById("adminPanel").style.display = "flex"; }
  if (name === "addFleet") { loadAddFleetPanel(); document.getElementById("addFleetPanel").style.display = "flex"; }
  if (name === "logs")     { loadLogsPanel(); document.getElementById("logsPanel").style.display = "flex"; }
  if (name === "profile")  { loadProfilePanel(); document.getElementById("profilePanel").style.display = "flex"; }
}

function closePanel(name) {
  const map = { admin: "adminPanel", addFleet: "addFleetPanel", logs: "logsPanel", profile: "profilePanel" };
  const el = document.getElementById(map[name]);
  if (el) el.style.display = "none";
}

function closeAllPanels() {
  ["adminPanel","addFleetPanel","logsPanel","profilePanel"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
}

document.querySelectorAll(".panel-overlay").forEach(el => {
  el.addEventListener("click", (e) => { if (e.target === el) closeAllPanels(); });
});

// ── ADMIN PANEL ────────────────────────────────────────
async function loadAdminPanel() {
  S.countries = await api("/api/countries");
  S.relations = await api("/api/relations");
  renderAdminCountries();
  renderRelationMatrix();
  const st = await api("/api/state");
  S.isWar    = st.is_war;
  S.gridCols = st.grid_cols;
  S.gridRows = st.grid_rows;
  document.getElementById("warSwitch").checked = S.isWar;
  document.getElementById("gridCols").value    = S.gridCols;
  document.getElementById("gridRows").value    = S.gridRows;
  updateWarUI();
}

function renderAdminCountries() {
  const el = document.getElementById("countryList");
  if (!el) return;
  el.innerHTML = S.countries.map(c => `
    <div class="country-row">
      <span class="country-swatch" style="background:${esc(c.color)}"></span>
      <span style="font-size:18px">${esc(c.flag_emoji)}</span>
      <span class="country-row-name">${esc(c.name)}</span>
      <span style="font-size:11px;color:var(--text-dim)">Орден ${esc(c.order_level)}</span>
      <button class="btn btn-sm btn-red" onclick="deleteCountry(${c.id})">\u2715</button>
    </div>`).join("") || "<div class='empty-hint'>Стран нет</div>";
}

async function addCountry() {
  const name  = document.getElementById("newCountryName").value.trim();
  const color = document.getElementById("newCountryColor").value;
  const emoji = document.getElementById("newCountryEmoji").value.trim() || "🏴";
  const order = parseInt(document.getElementById("newCountryOrder").value);
  if (!name) return showToast("Введите название", "error");
  await api("/api/countries", "POST", { name, color, flag_emoji: emoji, order_level: order });
  S.countries = await api("/api/countries");
  renderAdminCountries();
  renderRelationMatrix();
  // FIX: rebuild turn order when countries added
  await rebuildTurnOrder();
  document.getElementById("newCountryName").value = "";
  showToast(`Страна «${name}» добавлена`, "success");
}

async function deleteCountry(id) {
  if (!confirm("Удалить страну?")) return;
  await api(`/api/countries/${id}`, "DELETE");
  S.countries = await api("/api/countries");
  renderAdminCountries();
  renderRelationMatrix();
  await rebuildTurnOrder();
}

async function rebuildTurnOrder() {
  S.currentTurnOrder = S.countries.map(c => c.id);
  S.turnIndex = 0;
  await api("/api/state", "POST", {
    turn_order: S.currentTurnOrder,
    turn_index: 0,
    turn_number: S.turnNumber,
    moved_this_turn: {}
  });
  renderTurnUI();
}

function renderRelationMatrix() {
  const el = document.getElementById("relationMatrix");
  if (!el || S.countries.length < 2) {
    if (el) el.innerHTML = "<div class='empty-hint'>Нужно минимум 2 страны</div>";
    return;
  }
  const rows = [];
  for (let i = 0; i < S.countries.length; i++) {
    for (let j = i + 1; j < S.countries.length; j++) {
      const a = S.countries[i], b = S.countries[j];
      const rel = S.relations.find(r =>
        (r.a === a.id && r.b === b.id) || (r.a === b.id && r.b === a.id)
      );
      const isWar = rel ? rel.at_war : false;
      rows.push(`<div class="relation-row">
        <span class="rel-names">${esc(a.flag_emoji)} ${esc(a.name)} — ${esc(b.flag_emoji)} ${esc(b.name)}</span>
        <span class="war-badge ${isWar ? "war" : "peace"}">${isWar ? "\u2694 ВОЙНА" : "\u270C МИР"}</span>
        <button class="btn btn-sm btn-ghost" onclick="toggleRelation(${a.id},${b.id},${!isWar})">
          ${isWar ? "Мир" : "Война"}
        </button>
      </div>`);
    }
  }
  el.innerHTML = rows.join("") || "<div class='empty-hint'>Нет пар стран</div>";
}

async function toggleRelation(aId, bId, atWar) {
  await api("/api/relations", "POST", { country_a_id: aId, country_b_id: bId, at_war: atWar });
  S.relations = await api("/api/relations");
  renderRelationMatrix();
  showToast(atWar ? "⚔️ Война объявлена!" : "✌️ Мир заключён", atWar ? "error" : "success");
}

async function applyGridSettings() {
  const cols = parseInt(document.getElementById("gridCols").value);
  const rows = parseInt(document.getElementById("gridRows").value);
  if (cols < 5 || rows < 5) return showToast("Минимум 5x5", "error");
  S.gridCols = cols; S.gridRows = rows;
  await api("/api/state", "POST", { grid_cols: cols, grid_rows: rows });
  drawFrame();
  showToast("Сетка обновлена", "success");
}

// ── ADD FLEET PANEL ────────────────────────────────────
let shipLimitsData = null;

async function loadAddFleetPanel() {
  S.countries = await api("/api/countries");
  const sel = document.getElementById("newFleetCountry");
  sel.innerHTML = S.countries.map(c =>
    `<option value="${c.id}">${esc(c.flag_emoji)} ${esc(c.name)} (Орден ${esc(c.order_level)})</option>`
  ).join("");
  if (S.countryId) sel.value = S.countryId;

  if (!shipLimitsData) {
    const st = await api("/api/ship_types");
    shipLimitsData = st.limits || {};
  }
  sel.onchange = () => updateShipLimits();
  buildShipFormRows();
  updateShipLimits();
}

function buildShipFormRows() {
  const container = document.getElementById("shipFormRows");
  if (!container) return;
  const types = ["Дредноут","Линейный крейсер","Эсминец","Канонерка","Конвой"];
  const stats  = {
    "Дредноут":[1000,500,2,"Иммунитет к минам",0],
    "Линейный крейсер":[500,250,3,"Может выйти из боя",0],
    "Эсминец":[300,150,4,"Обезвреживает мины",3],
    "Канонерка":[200,100,4,"Ставит мины",5],
    "Конвой":[50,10,5,"",7]
  };
  container.innerHTML = types.map(t => {
    const cap = stats[t][4];
    return `<div class="ship-form-row" style="flex-wrap:wrap">
      <span class="ship-type-name" style="min-width:120px">${t}</span>
      <span class="ship-stat" style="flex:1;min-width:120px">\u2694${stats[t][1]} \uD83D\uDE80${stats[t][2]}</span>
      <span style="font-size:10px;color:var(--text-dim);margin-right:6px;min-width:100px">${stats[t][3]}</span>
      <div style="display:flex;align-items:center;gap:4px">
        <span style="font-size:10px;color:var(--text-dim)">\u041A\u043E\u043B-\u0432\u043E:</span>
        <input type="number" class="inp-sm ship-count-input" id="sc_${t.replace(/ /g,'_')}" value="0" min="0" max="20" style="width:45px">
      </div>
      <div style="display:flex;align-items:center;gap:4px">
        <span class="ship-limit-label" data-type="${t}" style="font-size:10px;color:var(--gold);min-width:50px"></span>
      </div>
      <div style="display:flex;align-items:center;gap:4px">
        <span style="font-size:10px;color:var(--text-dim)">\u0411\u0440\u043E\u043D\u044F:</span>
        <input type="number" class="inp-sm" id="sa_${t.replace(/ /g,'_')}" value="${stats[t][0]}" min="1" max="9999" style="width:65px" title="\u041C\u043E\u0436\u043D\u043E \u0438\u0437\u043C\u0435\u043D\u0438\u0442\u044C \u0434\u043B\u044F \u0443\u043D\u0438\u043A\u0430\u043B\u044C\u043D\u044B\u0445 \u043A\u043E\u0440\u0430\u0431\u043B\u0435\u0439">
      </div>
      ${cap > 0 ? `<div style="display:flex;align-items:center;gap:4px">
        <span style="font-size:10px;color:var(--text-dim)">\u041F\u043E\u043B\u043A\u0438:</span>
        <input type="number" class="inp-sm ship-reg-input" id="sr_${t.replace(/ /g,'_')}" value="0" min="0" max="${cap}" style="width:45px" title="\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430 \u043F\u043E\u043B\u043A\u043E\u0432 (\u043C\u0430\u043A\u0441. ${cap})">
      </div>` : ''}
    </div>`;
  }).join("");
}

function updateShipLimits() {
  if (!shipLimitsData) return;
  const sel = document.getElementById("newFleetCountry");
  if (!sel) return;
  const cid = parseInt(sel.value);
  const country = S.countries.find(c => c.id === cid);
  if (!country) return;
  const orderLevel = country.order_level;

  const types = ["Дредноут","Линейный крейсер","Эсминец","Канонерка","Конвой"];
  for (const t of types) {
    const limits = shipLimitsData[t] || {};
    const limit = limits[orderLevel];
    const input = document.getElementById(`sc_${t.replace(/ /g,'_')}`);
    const label = document.querySelector(`.ship-limit-label[data-type="${t}"]`);
    if (input) {
      input.max = limit != null ? limit : 20;
      if (limit != null && parseInt(input.value) > limit) input.value = limit;
    }
    if (label) {
      label.textContent = limit != null ? `/ ${limit}` : "/ ∞";
    }
  }
}

async function createFleet() {
  const name  = document.getElementById("newFleetName").value.trim();
  const cid   = parseInt(document.getElementById("newFleetCountry").value);
  const px    = parseInt(document.getElementById("newFleetX").value) || 0;
  const py    = parseInt(document.getElementById("newFleetY").value) || 0;
  if (!name) return showToast("Введите название флота", "error");

  const types = ["Дредноут","Линейный крейсер","Эсминец","Канонерка","Конвой"];
  const country = S.countries.find(c => c.id === cid);
  const orderLevel = country ? country.order_level : null;

  const ships = [];
  for (const t of types) {
    const count = parseInt(document.getElementById(`sc_${t.replace(/ /g,'_')}`).value) || 0;
    const armor = parseInt(document.getElementById(`sa_${t.replace(/ /g,'_')}`).value) || undefined;
    const regEl = document.getElementById(`sr_${t.replace(/ /g,'_')}`);
    const regiments = regEl ? (parseInt(regEl.value) || 0) : 0;
    if (count > 0) {
      if (shipLimitsData && orderLevel != null) {
        const limit = (shipLimitsData[t] || {})[orderLevel];
        if (limit != null && count > limit) {
          return showToast(`Лимит ${t} для Ордена ${orderLevel}: ${limit} (указано ${count})`, "error");
        }
      }
      ships.push({ ship_type: t, count, armor, regiments });
    }
  }
  if (!ships.length) return showToast("Добавьте хотя бы 1 корабль", "error");

  const res = await api("/api/fleets", "POST", { name, country_id: cid, pos_x: px, pos_y: py, ships });
  if (res.error) return showToast(res.error, "error");
  if (res.id) {
    showToast(`Флот «${name}» создан!`, "success");
    closePanel("addFleet");
    selectFleet(res.id);
  }
}

// ── LOGS PANEL ─────────────────────────────────────────
async function loadLogsPanel() {
  const logs = await api("/api/logs");
  const el = document.getElementById("logsList");
  if (!logs.length) { el.innerHTML = `<div class="empty-hint">Боёв ещё не было</div>`; return; }
  el.innerHTML = logs.map(l => `
    <div class="log-card" onclick="this.querySelector('.log-card-body').classList.toggle('expanded')">
      <div class="log-card-header">
        <span>\u2694\uFE0F Бой в клетке [${esc(l.cell_x)}, ${esc(l.cell_y)}]</span>
        <span>${esc(new Date(l.created_at).toLocaleString("ru"))}</span>
      </div>
      <div class="log-card-body">${esc((l.log || []).join("\n"))}</div>
    </div>`).join("");
}

// ── PROFILE PANEL ──────────────────────────────────────
async function loadProfilePanel() {
  const el = document.getElementById("profileContent");
  if (!el) return;

  if (!S.authToken) {
    el.innerHTML = `<div class="empty-hint">Войдите в аккаунт для просмотра профиля</div>`;
    return;
  }

  const res = await api("/api/auth/me");
  if (!res.ok || !res.user) {
    el.innerHTML = `<div class="empty-hint">Ошибка загрузки профиля</div>`;
    return;
  }

  const user = res.user;
  const winRate = user.games_played > 0 ? Math.round((user.games_won / user.games_played) * 100) : 0;
  const initials = (user.display_name || user.username).substring(0, 2).toUpperCase();

  el.innerHTML = `
    <div class="profile-header">
      <div class="profile-avatar">${esc(initials)}</div>
      <div class="profile-info">
        <h3>${esc(user.display_name || user.username)}</h3>
        <p>@${esc(user.username)}</p>
        <p style="font-size:10px;margin-top:4px">Регистрация: ${esc(new Date(user.created_at).toLocaleDateString("ru"))}</p>
      </div>
    </div>

    <div class="profile-stats">
      <div class="profile-stat">
        <div class="ps-value">${user.games_played}</div>
        <div class="ps-label">Игр</div>
      </div>
      <div class="profile-stat">
        <div class="ps-value">${user.games_won}</div>
        <div class="ps-label">Побед</div>
      </div>
      <div class="profile-stat">
        <div class="ps-value">${winRate}%</div>
        <div class="ps-label">Винрейт</div>
      </div>
      <div class="profile-stat">
        <div class="ps-value">${user.total_battles}</div>
        <div class="ps-label">Боёв</div>
      </div>
      <div class="profile-stat">
        <div class="ps-value">${user.ships_sunk}</div>
        <div class="ps-label">Потоплено</div>
      </div>
      <div class="profile-stat">
        <div class="ps-value">${user.ships_lost}</div>
        <div class="ps-label">Потеряно</div>
      </div>
    </div>

    <div class="profile-section">
      <h4>НАСТРОЙКИ</h4>
      <label>Отображаемое имя:
        <input type="text" id="profileDisplayName" class="inp" value="${esc(user.display_name || "")}" style="margin-top:6px">
      </label>
      <button class="btn btn-accent" onclick="updateProfile()" style="width:100%">Сохранить</button>
    </div>
  `;
}

async function updateProfile() {
  const displayName = document.getElementById("profileDisplayName").value.trim();
  if (!displayName) return showToast("Введите имя", "error");
  const res = await api("/api/auth/profile", "PUT", { display_name: displayName });
  if (res.ok) {
    S.playerName = res.user.display_name || res.user.username;
    saveSession();
    updatePlayerBadge();
    showToast("Профиль обновлён", "success");
  } else {
    showToast(res.error || "Ошибка", "error");
  }
}

// ── LOGIN MODAL ────────────────────────────────────────
let authMode = "login";

function showLoginModal() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.id = "loginOverlay";
  overlay.innerHTML = `
    <div class="modal login-modal">
      <div class="modal-body" style="padding:24px">
        <div class="login-title">⚓ IMPERIUM</div>
        <div class="login-subtitle">SEA WARS — Морские сражения</div>

        <div class="auth-tabs">
          <div class="auth-tab active" id="tabLogin" onclick="switchAuthTab('login')">Вход</div>
          <div class="auth-tab" id="tabRegister" onclick="switchAuthTab('register')">Регистрация</div>
        </div>

        <div id="authForm">
          <label>Имя пользователя:
            <input type="text" id="authUsername" class="inp" placeholder="admin" style="margin-top:6px">
          </label>
          <label>Пароль:
            <input type="password" id="authPassword" class="inp" placeholder="••••" style="margin-top:6px">
          </label>
          <div id="authDisplayNameRow" style="display:none">
            <label>Отображаемое имя:
              <input type="text" id="authDisplayName" class="inp" placeholder="Адмирал" style="margin-top:6px">
            </label>
          </div>
          <div id="authError" style="color:var(--red);font-size:12px;margin-bottom:8px;display:none"></div>
        </div>

        <div class="or-divider">или</div>
        <div class="spectator-btn" onclick="joinAsSpectator()">👁 Войти как наблюдатель</div>
        <div class="spectator-btn" onclick="joinAsAdmin()">🔑 Войти как администратор</div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary" onclick="submitAuth()">Войти →</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

function switchAuthTab(mode) {
  authMode = mode;
  document.getElementById("tabLogin").classList.toggle("active", mode === "login");
  document.getElementById("tabRegister").classList.toggle("active", mode === "register");
  document.getElementById("authDisplayNameRow").style.display = mode === "register" ? "block" : "none";
  document.getElementById("authError").style.display = "none";
}

async function submitAuth() {
  const username = document.getElementById("authUsername").value.trim();
  const password = document.getElementById("authPassword").value;
  const errEl = document.getElementById("authError");

  if (!username || !password) {
    errEl.textContent = "Заполните все поля";
    errEl.style.display = "block";
    return;
  }

  let res;
  if (authMode === "register") {
    const displayName = document.getElementById("authDisplayName").value.trim() || username;
    res = await api("/api/auth/register", "POST", { username, password, display_name: displayName });
  } else {
    res = await api("/api/auth/login", "POST", { username, password });
  }

  if (res.error) {
    errEl.textContent = res.error;
    errEl.style.display = "block";
    return;
  }

  S.authToken = res.token;
  S.userId = res.user.id;
  S.playerName = res.user.display_name || res.user.username;
  S.isSpectator = true;

  saveSession();
  document.getElementById("loginOverlay").remove();
  showCountryPicker();
}

function showCountryPicker() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.id = "countryPickerOverlay";
  overlay.innerHTML = `
    <div class="modal login-modal">
      <div class="modal-body" style="padding:24px">
        <div class="login-title">⚓ ВЫБЕРИТЕ СТРАНУ</div>
        <div class="login-subtitle">Присоединяйтесь к морским сражениям</div>
        <div class="country-picker" id="countryPicker"></div>
        <div class="or-divider">или</div>
        <div class="spectator-btn" onclick="joinAsSpectator()">👁 Войти как наблюдатель</div>
        <div class="spectator-btn" onclick="joinAsAdmin()">🔑 Войти как администратор</div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary" onclick="joinGame()">Войти в игру →</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  renderCountryPicker();
}

let selectedLoginCountry = null;

async function renderCountryPicker() {
  S.countries = await api("/api/countries");
  S.players   = (await api("/api/players")) || [];
  const picker = document.getElementById("countryPicker");
  if (!picker) return;
  picker.innerHTML = S.countries.map(c => {
    const taken = S.players.find(p => p.country_id === c.id && p.online);
    return `<div class="country-option ${taken ? "taken" : ""}" onclick="pickCountry(${c.id}, this)">
      <span class="co-emoji">${esc(c.flag_emoji)}</span>
      <span class="co-name" style="color:${esc(c.color)}">${esc(c.name)}</span>
      <span class="${taken ? "co-taken" : "co-online"}">${taken ? "занято: " + esc(taken.name) : "свободно"}</span>
    </div>`;
  }).join("") || `<div class="empty-hint">Стран нет. Спросите у мастера.</div>`;
}

function pickCountry(id, el) {
  document.querySelectorAll(".country-option").forEach(e => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedLoginCountry = id;
}

async function joinGame() {
  if (!selectedLoginCountry) return showToast("Выберите страну", "error");
  S.countryId   = selectedLoginCountry;
  S.isSpectator = false;
  S.isAdmin = false;
  saveSession();
  document.getElementById("countryPickerOverlay").remove();
  applySession();
}

function joinAsSpectator() {
  S.countryId   = null;
  S.isSpectator = true;
  S.isAdmin     = false;
  saveSession();
  const overlay = document.getElementById("countryPickerOverlay");
  if (overlay) overlay.remove();
  applySession();
}

async function joinAsAdmin() {
  const password = prompt("Введите пароль администратора:");
  if (password === null) return;
  const res = await api("/api/admin/login", "POST", { password });
  if (!res || res.error || !res.ok) {
    return showToast(res && res.error ? res.error : "Неверный пароль", "error");
  }
  S.playerName  = "admin";
  S.countryId   = 0;
  S.isSpectator = true;
  S.isAdmin     = true;
  if (res.token) S.authToken = res.token;
  saveSession();
  closeAllPanels();
  const loginOvl = document.getElementById("loginOverlay");
  if (loginOvl) loginOvl.remove();
  const pickerOvl = document.getElementById("countryPickerOverlay");
  if (pickerOvl) pickerOvl.remove();
  applySession();
}

function saveSession() {
  localStorage.setItem("imp_session", JSON.stringify({
    token: S.authToken,
    userId: S.userId,
    name: S.playerName,
    countryId: S.countryId,
    spectator: S.isSpectator,
    sessionId: S.sessionId,
  }));
}

function updatePlayerBadge() {
  const hdr = document.querySelector(".hdr-controls");
  const old = document.getElementById("playerBadge");
  if (old) old.remove();
  if (!S.playerName) return;
  const c = S.countries.find(c => c.id === S.countryId);
  const badge = document.createElement("div");
  badge.id = "playerBadge";
  badge.className = "hdr-player-badge";
  badge.style.position = "relative";
  const spectatorTag = (S.isSpectator && !S.isAdmin) ? ' <span style="font-size:9px;color:var(--text-dim);background:var(--bg-card);padding:1px 4px;border-radius:3px">\uD83D\uDC41</span>' : '';
  badge.innerHTML = `${esc(c ? c.flag_emoji : "\uD83D\uDC41")} <b>${esc(S.playerName)}</b>${spectatorTag}
    <span style="font-size:10px;color:var(--text-dim);margin-left:4px">\u25BC</span>`;
  if (c) badge.style.borderColor = c.color;

  const menu = document.createElement("div");
  menu.className = "hdr-profile-menu";
  menu.style.display = "none";
  menu.innerHTML = `
    <div class="menu-item" onclick="openPanel('profile')">\uD83D\uDC64 Мой профиль</div>
    <div class="menu-item danger" onclick="logoutSession()">\uD83D\uDEAA Выйти</div>
  `;
  badge.appendChild(menu);

  badge.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.style.display = menu.style.display === "none" ? "block" : "none";
  });

  const dismissMenu = () => { menu.style.display = "none"; };
  badge._dismissHandler = dismissMenu;
  document.addEventListener("click", dismissMenu);

  hdr.prepend(badge);
}

function logoutSession() {
  localStorage.removeItem("imp_session");
  socket.emit("leave_session");
  S.authToken = null; S.userId = null;
  S.playerName = null; S.countryId = null;
  S.sessionId  = null; S.isSpectator = false;
  S.isAdmin    = false;
  updateAdminUI();
  showLoginModal();
}

// ── DEMO ───────────────────────────────────────────────
async function seedDemo() {
  if (!confirm("Загрузить демо-данные? Все текущие данные будут удалены.")) return;
  const res = await api("/api/seed", "POST");
  S.countries = await api("/api/countries");
  S.relations = await api("/api/relations");
  // FIX: reset turn state on demo load
  S.turnNumber = 1;
  S.currentTurnOrder = S.countries.map(c => c.id);
  S.turnIndex = 0;
  S.movedThisTurn = {};
  S.shipMovedThisTurn = {};
  await api("/api/state", "POST", {
    turn_order: S.currentTurnOrder,
    turn_index: 0,
    turn_number: 1,
    moved_this_turn: {}
  });
  renderFleetList();
  renderFleetDetail();
  renderPlayerList();
  renderTurnUI();
  showToast(res.message || "Демо загружено!", "success");
}

window.applyGridSettings = applyGridSettings;

// ── API HELPER ─────────────────────────────────────────
async function api(url, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (S.sessionId) opts.headers["X-Session-Id"] = S.sessionId;
  if (S.authToken) opts.headers["Authorization"] = `Bearer ${S.authToken}`;
  if (body) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(url, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return { error: err.error || `HTTP ${res.status}` };
    }
    return res.json();
  } catch (e) {
    return { error: e.message || "Network error" };
  }
}

// ── TOAST ──────────────────────────────────────────────
function showToast(msg, type = "info") {
  let wrap = document.querySelector(".toast-wrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.className = "toast-wrap";
    document.body.appendChild(wrap);
  }
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  wrap.appendChild(t);
  setTimeout(() => t.remove(), 3100);
}

// ── COLOR HELPER ───────────────────────────────────────
function hexToRgba(hex, alpha) {
  if (!hex || hex.length < 7) return `rgba(200,200,200,${alpha})`;
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── EXPOSE GLOBALS ─────────────────────────────────────
window.selectFleet      = selectFleet;
window.startMove        = startMove;
window.startShipMove    = startShipMove;
window.cancelMove       = cancelMove;
window.placeMine        = placeMine;
window.demine           = demine;
window.adminDemine      = adminDemine;
window.removeFort       = removeFort;
window.placeFort        = placeFort;
window.deleteFleetConfirm = deleteFleetConfirm;
window.deleteShipConfirm  = deleteShipConfirm;
window.toggleWar        = toggleWar;
window.addCountry       = addCountry;
window.deleteCountry    = deleteCountry;
window.toggleRelation   = toggleRelation;
window.createFleet      = createFleet;
window.closeBattleModal = closeBattleModal;
window.openPanel        = openPanel;
window.closePanel       = closePanel;
window.seedDemo         = seedDemo;
window.joinGame         = joinGame;
window.joinAsSpectator  = joinAsSpectator;
window.pickCountry      = pickCountry;
window.logoutSession    = logoutSession;
window.updateShipLimits   = updateShipLimits;
window.endTurn          = endTurn;
window.renderTurnUI     = renderTurnUI;
window.startEditRegiments = startEditRegiments;
