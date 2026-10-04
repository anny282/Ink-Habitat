/* Desert: a stepped sand slab. The island is designed on a simple grid (u runs right-down, v runs left-down)
   and projected to the screen, so every edge is parallel to its neighbours and the sides are generated from the top
   outline. Shape: two lobes at the back, and a recessed notch at the front right. */
(function () {
  const A = .45, B = .62, T = 90, OX = 620, OY = 528;                 // grid -> screen slopes, slab thickness, position
  const P = (u, v) => [Math.round(OX + u - v), Math.round(OY + A * u + B * v)];
  const top = [[0,0],[330,0],[330,-300],[780,-300],[780,170],[470,170],[470,520],[0,520]].map(([u, v]) => P(u, v));

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

  registerScene('desert', {
    label: 'Desert', icon: '🏜️',
    top, sides: slabSides(top, T, '#c47b45', '#96512e'),
    sky: ['#80c6e8', '#c9edf2'], ground: '#f6c98a',
    backdrop(ctx, t) {                                                 // pulsing sun and distant dunes
      ctx.fillStyle = 'rgba(255,226,154,.35)'; ctx.beginPath(); ctx.arc(1530, 245, 104 + Math.sin(t * .8) * 6, 0, TWO_PI); ctx.fill();
      ctx.fillStyle = '#ffe29a'; ctx.beginPath(); ctx.arc(1530, 245, 92, 0, TWO_PI); ctx.fill();
      ctx.fillStyle = 'rgba(233,196,143,.75)'; ctx.beginPath(); ctx.ellipse(470, 520, 480, 100, 0, Math.PI, TWO_PI); ctx.fill();
      ctx.fillStyle = 'rgba(223,174,120,.6)'; ctx.beginPath(); ctx.ellipse(1450, 560, 420, 85, 0, Math.PI, TWO_PI); ctx.fill();
    },
    decorate(ctx) {
      ctx.strokeStyle = 'rgba(255,240,205,.5)'; ctx.lineWidth = 4; ctx.lineJoin = 'round';   // light rim along the top edge
      ctx.beginPath(); top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.stroke();
      [[120,80],[560,-200],[700,-90],[80,400],[400,300],[640,60],[260,450]].forEach(([u, v], i) => {   // pebbles
        const [x, y] = P(u, v);
        ctx.fillStyle = '#b09c80'; ctx.beginPath(); ctx.ellipse(x, y, i % 3 === 0 ? 12 : 9, i % 3 === 0 ? 8 : 6, -.2, 0, TWO_PI); ctx.fill();
        ctx.fillStyle = '#a69277'; ctx.beginPath(); ctx.ellipse(x + 19, y + 6, 6, 4, -.2, 0, TWO_PI); ctx.fill();
      });
    }
  });
})();
