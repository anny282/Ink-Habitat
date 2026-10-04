/* Grasslands: a grassy slab with a recessed notch at the front right.
   Designed on a simple grid (u runs right-down, v runs left-down) and projected to the screen, so every edge is
   parallel to its neighbours and the walls are generated from the top outline. */
(function () {
  const A = .45, B = .62, T = 90, OX = 923, OY = 515;                  // grid -> screen slopes, slab thickness, position
  const P = (u, v) => [Math.round(OX + u - v), Math.round(OY + A * u + B * v)];
  const top = [[0,0],[800,0],[800,580],[480,580],[480,760],[0,760]].map(([u, v]) => P(u, v));

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

  registerScene('grasslands', {
    label: 'Grasslands', icon: '🌿',
    top, sides: slabSides(top, T, '#aa8f6d', '#85684a'),
    sky: ['#8ab3ff', '#cadcff'], ground: '#92b46e',
    backdrop(ctx, t) {                                                 // slow drifting clouds
      ctx.fillStyle = 'rgba(255,255,255,.55)';
      [[200,160,1],[900,90,1.3],[1500,230,.9],[500,300,.8]].forEach(([x0, y, s], i) => {
        const x = ((x0 + t * (8 + i * 3)) % 2400) - 220;
        [[0,0,90],[70,-18,70],[-70,-10,60],[130,6,55]].forEach(([dx, dy, r]) => { ctx.beginPath(); ctx.ellipse(x + dx * s, y + dy * s, r * s, r * .55 * s, 0, 0, TWO_PI); ctx.fill(); });
      });
    },
    decorate(ctx) {
      ctx.strokeStyle = 'rgba(225,245,195,.4)'; ctx.lineWidth = 4; ctx.lineJoin = 'round';     // light rim along the top edge
      ctx.beginPath(); top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.stroke();
      ctx.strokeStyle = '#6f9457'; ctx.lineWidth = 4;                                          // grass tufts
      [[100,120],[420,80],[700,70],[240,300],[620,260],[130,520],[400,520],[700,470],[330,680],[190,690]].forEach(([u, v]) => {
        const [x, y] = P(u, v);
        ctx.beginPath(); ctx.moveTo(x-8,y-6); ctx.lineTo(x-4,y); ctx.moveTo(x,y-9); ctx.lineTo(x+1,y); ctx.moveTo(x+9,y-6); ctx.lineTo(x+5,y); ctx.stroke();
      });
    }
  });
})();
