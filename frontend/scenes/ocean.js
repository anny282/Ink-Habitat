/* Ocean floor: a sandy slab with a bump at the back and a bite taken out of the back right.
   Designed on a simple grid (u runs right-down, v runs left-down) and projected to the screen, so every edge is
   parallel to its neighbours and the walls are generated from the top outline. */
(function () {
  const A = .45, B = .62, T = 90, OX = 810, OY = 400;                  // grid -> screen slopes, slab thickness, position
  const P = (u, v) => [Math.round(OX + u - v), Math.round(OY + A * u + B * v)];
  const top = [[0,0],[250,0],[250,-100],[540,-100],[540,160],[960,160],[960,560],[0,560]].map(([u, v]) => P(u, v));

  function slabSides(poly, thick, light, dark) {                       // the visible walls of an extruded outline
    let area = 0; poly.forEach((p, i) => { const q = poly[(i + 1) % poly.length]; area += p[0] * q[1] - q[0] * p[1]; });
    const s = area > 0 ? 1 : -1, faces = [];
    poly.forEach((a, i) => {
      const b = poly[(i + 1) % poly.length], dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
      if (-s * dx / len < .15) return;                                 // outward normal points away from the viewer
      faces.push({ y: (a[1] + b[1]) / 2, col: s * dy / len < 0 ? light : dark, q: [a, b, [b[0], b[1] + thick], [a[0], a[1] + thick]] });
    });
    return faces.sort((p, q) => p.y - q.y).map(f => [f.col, f.q]);     // back to front
  }

  registerScene('ocean', {
    label: 'Ocean', icon: '🌊',
    top, sides: slabSides(top, T, '#8c7a68', '#5f4a39'),
    sky: ['#445b91', '#252c67'], ground: '#b8a68d',
    backdrop(ctx, t) {                                                 // water ripples and rising bubbles
      ctx.strokeStyle = 'rgba(196,225,244,.18)'; ctx.lineWidth = 5;
      for (let i = 0; i < 7; i++) { ctx.beginPath(); ctx.ellipse(220 + i * 245, 230 + (i % 3) * 60, 100, 20, 0, 0, TWO_PI); ctx.stroke(); }
      ctx.fillStyle = 'rgba(196,225,244,.28)';
      for (let i = 0; i < 12; i++) {
        const x = 150 + i * 155 + Math.sin(t * .8 + i) * 14, y = 1500 - ((t * 42 + i * 131) % 1500);
        ctx.beginPath(); ctx.arc(x, y, 5 + (i % 3) * 3, 0, TWO_PI); ctx.fill();
      }
    },
    decorate(ctx) {
      ctx.strokeStyle = 'rgba(255,245,225,.3)'; ctx.lineWidth = 4; ctx.lineJoin = 'round';     // light rim along the top edge
      ctx.beginPath(); top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.stroke();
      [[120,160],[430,-40],[560,300],[820,400],[170,420],[640,480]].forEach(([u, v], i) => {   // pebbles
        const [x, y] = P(u, v);
        ctx.fillStyle = '#65626e'; ctx.beginPath(); ctx.ellipse(x, y, i % 2 ? 11 : 9, i % 2 ? 8 : 6, -.2, 0, TWO_PI); ctx.fill();
        ctx.beginPath(); ctx.ellipse(x + 18, y + 5, 6, 4, -.2, 0, TWO_PI); ctx.fill();
      });
      ctx.strokeStyle = '#c35d63'; ctx.lineWidth = 6;                                          // coral
      [[200,60],[800,300]].forEach(([u, v]) => { const [x, y] = P(u, v);
        ctx.beginPath(); ctx.moveTo(x, y+18); ctx.lineTo(x, y-3); ctx.moveTo(x, y+8); ctx.lineTo(x-9, y+1); ctx.moveTo(x, y+1); ctx.lineTo(x+8, y-8); ctx.stroke(); });
      const [sx, sy] = P(360, 430);                                                            // starfish
      ctx.fillStyle = '#a06a2c'; ctx.beginPath();
      for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 9 : 24; ctx.lineTo(sx + Math.cos(a) * r, sy + Math.sin(a) * r); }
      ctx.closePath(); ctx.fill();
    }
  });
})();
