/* scenes.js: combines the scene files into one registry (load this first, then each scene file).
   Each scene file calls registerScene(id, {...}). The order of the script tags is the scroll order.
   A scene has: label, icon, top (walkable polygon), sides (coloured faces), sky, ground,
   and optional backdrop(ctx,t) (sky layer: sun, clouds...) and decorate(ctx,t) (things on the island).
   All coordinates are in "world space" (the same space creatures walk in). */
const SCENES = {}, SCENE_ORDER = [], TWO_PI = Math.PI * 2;
function registerScene(id, def) { SCENES[id] = def; SCENE_ORDER.push(id); }

// Draws one scene. The sky layer and the island layer get separate transforms so the island can slide
// slightly faster than the sky while scrolling (parallax).
function paintScene(id, ctx, W, H, skyY, skyMat, isleMat, t) {
  const s = SCENES[id];
  ctx.setTransform(1, 0, 0, 1, 0, skyY);
  const g = ctx.createLinearGradient(0, 0, 0, H); g.addColorStop(0, s.sky[0]); g.addColorStop(1, s.sky[1]);
  ctx.fillStyle = g; ctx.fillRect(0, -1, W, H + 2);
  ctx.setTransform(skyMat); if (s.backdrop) s.backdrop(ctx, t);
  ctx.setTransform(isleMat);
  const poly = (pts, col) => { ctx.fillStyle = col; ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fill(); };
  s.sides.forEach(q => poly(q[1], q[0])); poly(s.top, s.ground);
  ctx.lineCap = 'round'; if (s.decorate) s.decorate(ctx, t);
}
