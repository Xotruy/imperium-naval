# Security & Bug Audit Report — Imperium Naval Frontend

**Audited files:** `static/js/app.js` (2019 lines), `templates/index.html` (240 lines)  
**Date:** 2026-06-28

---

## CRITICAL Issues (3)

### C1 — Admin state spoofing via localStorage
**app.js:179** | `S.isAdmin = s.isAdmin || false;`  
The admin flag is persisted in `localStorage` and trusted by the frontend for all privilege checks. Any user can open DevTools console and run:
```js
let s = JSON.parse(localStorage.getItem("imp_session"));
s.isAdmin = true;
localStorage.setItem("imp_session", JSON.stringify(s));
location.reload();
```
This grants full admin powers: delete fleets, toggle war, force demine, place forts, access the admin panel. **The server must independently verify admin status from the auth token on every mutating request.**

### C2 — Stored XSS via ship renaming
**app.js:1053-1056 + 1308-1310** | Ship custom names flow unsanitized into innerHTML  
`startRenameShip()` lets users set arbitrary text via `contentEditable`. That text is sent to the server and later rendered in `renderFleetDetail()` at line 1049 as `${displayName}` inside a template literal assigned to innerHTML. A payload like `<img src=x onerror=alert(document.cookie)>` executes for every user viewing that fleet's detail panel. Same pattern affects `f.name` (fleet names), `p.name` (player names), `c.name` (country names), and `user.display_name`/`user.username` (profile panel line 1637).

**Fix:** Create an escape helper and apply it everywhere:
```js
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
// Then: ${esc(displayName)} instead of ${displayName}
```

### C3 — XSS in victory modal via WebSocket data
**app.js:113-114** | Server-pushed `winner_name`, `winner_color`, `winner_emoji` injected raw into innerHTML  
The `game_victory` handler does:
```js
text.innerHTML = `<span style="color:${data.winner_color || '#c9a84c'}">${data.winner_emoji || ""} ${data.winner_name}</span> победила!`;
```
A compromised or malicious server (or MITM on non-TLS WebSocket) could inject arbitrary HTML/JS into every connected client. The `winner_color` goes into a `style` attribute — a value like `"><script>alert(1)</script>` breaks out.

**Fix:** Use `textContent` for the name and emoji. Validate color with a hex regex.

---

## HIGH Issues (7)

### H1 — Auth token stored in localStorage
**app.js:170-174, 1863-1873**  
The JWT/session token lives in `localStorage`, accessible to any JS on the page. Combined with the XSS issues above, an attacker can steal the token and impersonate any user. Tokens should be in `httpOnly` cookies that JavaScript cannot read.

### H2 — Admin check pattern is purely client-side (8+ locations)
**app.js:221-225, 675, 692-693, 1065, 1112, 1155-1163, 1207, 1265**  
Functions like `startMove()`, `toggleWar()`, `adminDemine()`, `placeFort()`, `deleteFleetConfirm()`, `deleteShipConfirm()` all gate actions on `S.isAdmin` or `fleet.country_id === S.countryId` — values loaded from localStorage. None of these protect anything if the server doesn't independently verify. The `updateAdminUI()` function (line 221) shows/hides DOM elements based on the spoofable flag.

### H3 — Fleet detail innerHTML with unsanitized server data
**app.js:1024-1114**  
`renderFleetDetail()` interpolates `fleet.name`, country name, ship types, and ship custom names into a large innerHTML string. Fleet names and ship names are user-controlled. The `onclick` attributes like `onclick="startShipMove(${s.id})"` use numeric IDs (safe), but the textual content around them is vulnerable.

### H4 — Fleet list innerHTML with attribute injection
**app.js:977-991**  
```js
return `<div class="fleet-card..." onclick="selectFleet(${f.id})" title="${f.name}">
```
`f.name` goes directly into a `title` attribute. A name containing `" onmouseover="alert(1)` creates a new attribute and executes JS on hover.

### H5 — No WebSocket reconnection auth
**app.js:63-67**  
On reconnect, the client emits `rejoin` with only `session_id` and `country_id` — no auth token. If a session ID is intercepted, an attacker can rejoin as that user after they disconnect.

### H6 — Tooltip innerHTML from fleet/country data
**app.js:618-658**  
`showCellTooltip()` concatenates fleet names, country names, and mine/fort data into HTML strings assigned to `tt.innerHTML`. All dynamic values are unsanitized.

### H7 — Document click listener leak compounds on every badge render
**app.js:1904**  
Inside `updatePlayerBadge()`, a new anonymous listener is added to `document` every time the function runs:
```js
document.addEventListener("click", () => { menu.style.display = "none"; });
```
Each call to `updatePlayerBadge()` (happens on every `applySession()` and profile update) adds another listener that is never removed. After 20 calls, there are 20 overlapping listeners. Each one also holds a closure reference to the old `menu` element, preventing garbage collection.

**Fix:** Store the handler reference and remove it before adding a new one, or use `{ once: true }` or a named function.

---

## MEDIUM Issues (12)

### M1 — Login modal overlay accumulates on repeated calls
**app.js:1697-1736**  
`showLoginModal()` creates a new `div.modal-overlay` and appends it to `document.body`. Calling it twice (e.g., after token expiry) stacks two overlays. The old one has no cleanup. Same issue with `showCountryPicker()` (line 1781).

### M2 — Race between async move and WebSocket state replacement
**app.js:82-88, 766-803**  
`map_update` replaces `S.fleets` entirely. If `confirmMove()` is in-flight (awaiting the API response at line 789), the fleet data under `S.fleets` may change before the animation starts. The fleet reference captured at line 769 points to stale data.

### M3 — TypeLines animation continues after modal close
**app.js:1327-1336**  
`typeLines()` recurses via `setTimeout` with 40ms delay. If `closeBattleModal()` is called during the animation, the timeouts keep firing and attempting to append elements to a removed container. This causes silent DOM errors and wastes CPU.

**Fix:** Track an animation state flag and check it at the start of each `typeLines` call.

### M4 — Map image ignores pan/zoom
**app.js:262-263**  
`ctx.drawImage(mapImg, 0, 0, canvas.width, canvas.height)` draws the map to full canvas dimensions without applying `S.offsetX`, `S.offsetY`, or `S.scale`. The grid, fleets, and tooltips move with pan/zoom, but the background map stays fixed. This creates a visual disconnect.

### M5 — Coordinate hint element queried every frame
**app.js:385**  
`document.getElementById("coordHint")` is called inside `_draw()` on every animation frame. This DOM lookup is unnecessary overhead.

**Fix:** Cache the element reference once during init.

### M6 — Vacuous truth in turn completion check
**app.js:919-921**  
```js
const myFleetsMoved = S.fleets.filter(f => f.country_id === cid).every(f => S.movedThisTurn[f.id]);
```
For countries with zero fleets, `.filter()` returns `[]`, and `[].every()` returns `true`. The UI shows a checkmark for fleetless countries, which is misleading.

**Fix:** Add `&& filteredFleets.length > 0` to the condition.

### M7 — Admin login exposes password in prompt()
**app.js:1847**  
`prompt("Введите пароль администратора:")` — the password is visible in the UI and sent as plaintext. No rate limiting is possible from the client side.

### M8 — No Content-Security-Policy or X-Frame-Options
**index.html:1-7**  
No CSP meta tag or frame-protection headers. The page can be embedded in iframes for clickjacking, and inline scripts (used extensively) have no origin restrictions.

### M9 — Socket.IO CDN without Subresource Integrity
**index.html:26**  
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
```
No `integrity` attribute. A CDN compromise would inject malicious code into every client.

**Fix:** Add SRI hash: `integrity="sha384-..." crossorigin="anonymous"`.

### M10 — No WebSocket disconnect feedback
**app.js:61-67**  
There is no `socket.on("disconnect", ...)` handler. When the connection drops, the UI continues showing stale data with no indication to the user that they're disconnected.

### M11 — Create fleet doesn't validate grid bounds
**app.js:1565-1566**  
```js
const px = parseInt(document.getElementById("newFleetX").value) || 0;
const py = parseInt(document.getElementById("newFleetY").value) || 0;
```
No check against `S.gridCols`/`S.gridRows`. A fleet placed at (100, 50) on a 40x25 grid would be invisible and unmovable.

### M12 — Ship move triggers full fleet animation
**app.js:872**  
When an individual ship moves via `confirmShipMove()`, it calls `startFleetAnimation(shipFleet.id, ...)` which animates the fleet marker from its current position to the destination. But the fleet's `pos_x`/`pos_y` didn't change — only the ship moved. The visual movement doesn't correspond to the actual game state change.

---

## LOW Issues (10)

### L1 — Armor division by zero
**app.js:1046**  
`Math.round((s.current_armor / maxA) * 100)` — if `s.max_armor` is 0 or undefined, `maxA` is 1 (the fallback), but if the server sends `max_armor: 0`, division by zero produces `Infinity` or `NaN`.

### L2 — Canvas cell size recomputed every frame
**app.js:254**  
`computeCellSize()` runs inside `_draw()` on every animation frame, even when canvas dimensions haven't changed. Minor but unnecessary CPU usage.

### L3 — End turn sends null country_id for non-admin non-player
**app.js:956-958**  
If `S.countryId` is null and `S.isAdmin` is false, the POST body sends `{ country_id: null }`, which could cause a server error.

### L4 — Initial page load has no error handling
**app.js:145-157**  
Three sequential `await api(...)` calls with no try/catch. If the server is down, the page throws unhandled errors and shows a blank screen.

### L5 — No CSRF protection on state-mutating API calls
**app.js:1948-1966**  
The `api()` helper sends Bearer tokens but no CSRF tokens. While Bearer auth mitigates basic CSRF, it doesn't protect against subdomain XSS or other advanced CSRF vectors.

### L6 — Float precision in animation map key
**app.js:371**  
`drawX.toFixed(2)` used as a string key for cell grouping. Floating-point rounding can cause two visually-adjacent fleets to land in different cells.

### L7 — Admin status cleared when player joins a country
**app.js:1830**  
`joinGame()` sets `S.isAdmin = false`. An admin who wants to also play as a country loses all admin powers after selecting a nation.

### L8 — Resize listener not debounced
**app.js:160**  
`window.addEventListener("resize", () => { resizeCanvas(); drawFrame(); })` fires on every resize event. During window drag resizing, this triggers hundreds of canvas redraws.

### L9 — Ship count input accepts negative values despite min="0"
**app.js:1525**  
`<input type="number" ... min="0" max="20">` — browser validation can be bypassed with keyboard input or DevTools. The `createFleet()` function doesn't check for negative counts.

### L10 — `window` global pollution
**app.js:1993-2019**  
24 functions are exposed on the `window` object. Any other script on the page (or XSS payload) can override them.

---

## Summary by Severity

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 7 |
| Medium | 12 |
| Low | 10 |
| **Total** | **32** |

## Top 5 Recommendations (Priority Order)

1. **Add server-side authorization** — Never trust `S.isAdmin`, `S.countryId`, or `S.isSpectator` from the client. Verify every mutating request against the JWT/session token.
2. **HTML-escape all dynamic content** — Implement `esc()` helper and apply to every value entering innerHTML. This fixes C2, C3, H3, H4, H6, M1.
3. **Move auth tokens to httpOnly cookies** — Eliminates token theft via XSS (H1).
4. **Add CSP and SRI headers** — Mitigates XSS impact and CDN compromise (M8, M9).
5. **Fix memory leaks** — Remove document click listener in `updatePlayerBadge()`, guard `typeLines()` against modal close, clean up login overlays (H7, M1, M3).
