// Live presence and battle pop-ups for any page that includes this after the Socket.IO client:
// "<friend> wants to battle!" with Accept / No thanks, and "You're in a battle" with a way back to it.
// The battle itself runs on /battle.html?room=<id> (server side: backend/rooms.py).
(() => {
  if (!window.io) return;
  const socket = io({ transports: ["websocket", "polling"] });
  window.liveSocket = socket;   // the friends page sends invites through this
  const activity = location.pathname.endsWith("/draw-creature.html") ? "drawing" : "online";
  socket.on("connect", () => socket.emit("activity", { state: activity }));

  const box = document.createElement("div");
  box.setAttribute("role", "status");
  box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:50;max-width:min(340px,calc(100vw - 32px));" +
    "background:#fff;color:#26314F;border:2px solid #26314F;border-radius:16px;padding:12px 14px;" +
    "font:15px/1.4 'Atkinson Hyperlegible',system-ui,sans-serif;box-shadow:0 4px 14px #0003";
  box.hidden = true;
  document.addEventListener("DOMContentLoaded", () => document.body.append(box));
  if (document.body) document.body.append(box);

  const button = (label, onClick, main) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label; b.onclick = onClick;
    b.style.cssText = "font:inherit;font-weight:700;color:#26314F;border:2px solid " + (main ? "#26314F" : "#C9CFE6") +
      ";background:" + (main ? "#F2B134" : "#fff") + ";border-radius:10px;padding:5px 12px;cursor:pointer";
    return b;
  };
  const show = (text, buttons) => {
    const p = document.createElement("p"), row = document.createElement("div");
    p.style.margin = "0 0 8px"; p.textContent = text;
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end";
    row.append(...buttons);
    box.replaceChildren(p, row); box.hidden = false;
  };
  const go = id => location.assign(`/battle.html?room=${encodeURIComponent(id)}`);
  let timer = null;

  socket.on("battle", v => {
    clearInterval(timer);
    const room = new URLSearchParams(location.search).get("room");
    if (room && room === v.battleId && ["invited", "picking", "playing", "prize"].includes(v.stage)) {
      box.hidden = true;
      return;
    }
    if (v.stage === "invited" && !v.inviter) {
      const shownAt = Date.now();
      const left = () => Math.max(0, Math.ceil((v.deadline - v.serverNow - (Date.now() - shownAt)) / 1000));
      const answer = async accept => {
        const res = await socket.timeout(10000).emitWithAck("answer", { battleId: v.battleId, accept }).catch(() => null);
        if (accept && res && res.ok) go(v.battleId); else box.hidden = true;
      };
      const render = () => show(`${v.opponent.name} wants to battle! (${left()}s)`,
        [button("No thanks", () => answer(false)), button("Let's go!", () => answer(true), true)]);
      render();
      timer = setInterval(() => { if (left() <= 0) { clearInterval(timer); box.hidden = true; } else box.querySelector("p").textContent = `${v.opponent.name} wants to battle! (${left()}s)`; }, 1000);
    } else if (["invited", "picking", "playing", "prize"].includes(v.stage)) {
      show(`You're in a battle with ${v.opponent.name}.`, [button("Go to battle", () => go(v.battleId), true)]);
    } else {
      box.hidden = true;
    }
  });
})();
