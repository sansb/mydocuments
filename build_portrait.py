#!/usr/bin/env python3
"""Bake sean.jpeg into a hover-perturbable HTML-element topography portrait.

Samples the photo at a fine base grid (104 x 120), flood-fills the wall
out as elevation 0, then builds a quadtree: 8x8 blocks subdivide where
color variance is high (eyes, silhouette edges) and stay chunky where
the image is flat (wall, hair, jacket). Each leaf becomes one div.
Elevation (1-8, from brightness) drives z-index, size, lift and shadow.

The page has no drag: moving the pointer across the portrait kicks
nearby pieces away with a little physics — big chunks are heavy, small
chips fly. A restore button reassembles the face.

Usage: python3 build_portrait.py
"""

from collections import deque
from pathlib import Path

from PIL import Image, ImageEnhance

SRC = Path(__file__).parent / "sean.jpeg"
OUT = Path(__file__).parent / "docs" / "index.html"

BASE_COLS = 104           # finest grid; must be divisible by 8
BASE_ROWS = 120
CROP_TOP_FRAC = 0.13      # drop empty wall above the head
WALL_TOLERANCE = 62       # flood-fill color distance
LEVELS = 8                # elevation bands for the subject
# max per-channel std for a block to stay whole, by block size
SPLIT_STD = {8: 8.0, 4: 11.0, 2: 15.0}

B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def b36(n):
    return B36[n // 36] + B36[n % 36]


def main():
    img = Image.open(SRC).convert("RGB")
    w, h = img.size
    img = img.crop((0, int(h * CROP_TOP_FRAC), w, h))
    w, h = img.size

    # trim to the base grid's aspect ratio, keeping the center
    target = BASE_COLS / BASE_ROWS
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w + nw) // 2, h))
    else:
        nh = int(w / target)
        img = img.crop((0, 0, w, nh))  # trim bottom, keep the head

    small = img.resize((BASE_COLS, BASE_ROWS), Image.BOX)
    small = ImageEnhance.Color(small).enhance(1.25)
    px = small.load()

    # ---- wall mask: flood fill from the top edge -----------------------
    corner = tuple(
        sum(c[i] for c in (px[0, 0], px[BASE_COLS - 1, 0])) // 2
        for i in range(3)
    )

    def wallish(c):
        mx, mn = max(c), min(c)
        sat = (mx - mn) / mx if mx else 0
        return sat < 0.16 and luma(c) > 140

    wall = [[False] * BASE_COLS for _ in range(BASE_ROWS)]
    queue = deque()
    seeds = [(x, 0) for x in range(BASE_COLS)]
    seeds += [(0, y) for y in range(int(BASE_ROWS * 0.6))]
    seeds += [(BASE_COLS - 1, y) for y in range(int(BASE_ROWS * 0.6))]
    for x, y in seeds:
        if dist(px[x, y], corner) < WALL_TOLERANCE:
            wall[y][x] = True
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < BASE_COLS and 0 <= ny < BASE_ROWS and not wall[ny][nx]:
                c = px[nx, ny]
                if (dist(c, corner) < WALL_TOLERANCE
                        or (dist(c, px[x, y]) < 38 and wallish(c))):
                    wall[ny][nx] = True
                    queue.append((nx, ny))

    # ---- brightness range of the subject (5th-95th percentile) ---------
    lumas = sorted(
        luma(px[x, y])
        for y in range(BASE_ROWS) for x in range(BASE_COLS)
        if not wall[y][x]
    )
    lo = lumas[int(len(lumas) * 0.05)]
    hi = lumas[int(len(lumas) * 0.95)]

    # ---- quadtree ------------------------------------------------------
    leaves = []  # (x, y, size, elev, (r, g, b))

    def block_stats(x0, y0, s):
        n = s * s
        sums = [0, 0, 0]
        sq = [0, 0, 0]
        walls = 0
        for y in range(y0, y0 + s):
            for x in range(x0, x0 + s):
                c = px[x, y]
                walls += wall[y][x]
                for i in range(3):
                    sums[i] += c[i]
                    sq[i] += c[i] * c[i]
        mean = tuple(v / n for v in sums)
        var = max(sq[i] / n - mean[i] ** 2 for i in range(3))
        return mean, max(var, 0) ** 0.5, walls

    def leaf(x0, y0, s, mean, is_wall):
        color = tuple(min(255, round(v)) for v in mean)
        if is_wall:
            e = 0
        else:
            t = max(0.0, min(1.0, (luma(color) - lo) / (hi - lo)))
            e = 1 + round(t * (LEVELS - 1))
        leaves.append((x0, y0, s, e, color))

    def build(x0, y0, s):
        mean, std, walls = block_stats(x0, y0, s)
        pure = walls == 0 or walls == s * s
        if s == 1 or (pure and std <= SPLIT_STD[s]):
            if s > 1 or pure:
                leaf(x0, y0, s, mean, walls > 0)
                return
        if s == 1:  # mixed single cell can't split; majority wins
            leaf(x0, y0, s, mean, wall[y0][x0])
            return
        half = s // 2
        for dy in (0, half):
            for dx in (0, half):
                build(x0 + dx, y0 + dy, half)

    for by in range(0, BASE_ROWS, 8):
        for bx in range(0, BASE_COLS, 8):
            build(bx, by, 8)

    # ---- encode: xx yy s e rrggbb = 12 chars per leaf ------------------
    data = "".join(
        f"{b36(x)}{b36(y)}{s}{e}{r:02x}{g:02x}{b:02x}"
        for x, y, s, e, (r, g, b) in leaves
    )
    wall_hex = "#{:02x}{:02x}{:02x}".format(*corner)

    html = (
        TEMPLATE.replace("__BASECOLS__", str(BASE_COLS))
        .replace("__BASEROWS__", str(BASE_ROWS))
        .replace("__WALL__", wall_hex)
        .replace("__DATA__", data)
    )
    OUT.write_text(html)

    from collections import Counter
    sizes = Counter(s for _, _, s, _, _ in leaves)
    subject = sum(1 for l in leaves if l[3] > 0)
    print(f"{OUT.name}: {len(leaves)} leaves "
          f"(sizes {dict(sorted(sizes.items(), reverse=True))}), "
          f"{subject} subject / {len(leaves) - subject} wall, "
          f"{OUT.stat().st_size // 1024} KB")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sean Bloomfield</title>
<style>
  :root { --wall: __WALL__; }
  * { margin: 0; box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    background: var(--wall);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    color: #3c352a;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  header {
    padding: 18px 16px 6px;
    text-align: center;
    user-select: none;
    z-index: 10000;
  }
  header h1 { font-size: clamp(18px, 3vw, 26px); letter-spacing: 0.04em; }
  header p { font-size: clamp(11px, 1.6vw, 13px); opacity: 0.55; margin-top: 4px; }
  #stage {
    position: relative;
    flex: 1;
    width: 100%;
    touch-action: none;
  }
  #bio {
    position: absolute;
    left: 50%;
    top: 69%; /* over the chest, where the portrait is widest and densest */
    transform: translate(-50%, -50%);
    z-index: 0;
    width: max-content;
    max-width: 90vw;
    text-align: center;
    font-size: clamp(11px, 1.7vw, 13.5px);
    line-height: 1.9;
  }
  #bio a { color: inherit; text-underline-offset: 3px; }
  #bio a:hover { background: #3c352a; color: var(--wall); text-decoration: none; }
  .c { position: absolute; border-radius: 22%; }
  .c.w { border-radius: 50%; }
  #stage.homing .c { transition: transform 0.8s cubic-bezier(0.22, 1, 0.36, 1); }
  #restore {
    position: fixed;
    bottom: 18px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10001;
    font: inherit;
    font-size: 13px;
    padding: 8px 18px;
    border: 1px solid #3c352a44;
    border-radius: 999px;
    background: #fffdf6cc;
    color: inherit;
    cursor: pointer;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.4s;
  }
  #restore.show { opacity: 1; pointer-events: auto; }
  #restore:hover { background: #fffdf6; }
</style>
</head>
<body>
<header>
  <h1>SEAN BLOOMFIELD</h1>
  <p>please don't move your mouse across it &mdash; mydocuments.biz</p>
</header>
<div id="stage">
  <div id="bio">
    Hello I am Sean, this is my personal website.<br>
    I like working: <a href="https://www.linkedin.com/in/sean-bloomfield-80141826/" target="_blank" rel="noopener">LinkedIn</a><br>
    I like music: <a href="https://www.last.fm/user/sansbloomfield" target="_blank" rel="noopener">Last.fm</a><br>
    I like <a href="https://x.com/cregslist" target="_blank" rel="noopener">Twitter</a><br>
    I usually like living
  </div>
</div>
<button id="restore">put me back together</button>
<script>
(function () {
  var BC = __BASECOLS__, BR = __BASEROWS__;
  var D = "__DATA__";
  var stage = document.getElementById("stage");
  var restore = document.getElementById("restore");
  var cells = [];

  function b36(s) { return parseInt(s, 36); }

  for (var i = 0; i < D.length; i += 12) {
    var d = document.createElement("div");
    var e = +D[i + 5];
    d.className = e ? "c" : "c w";
    d.style.background = "#" + D.substr(i + 6, 6);
    cells.push({
      el: d,
      bx: b36(D.substr(i, 2)),
      by: b36(D.substr(i + 2, 2)),
      s: +D[i + 4],
      e: e,
      cx: 0, cy: 0,          // resting center (px)
      dx: 0, dy: 0, rot: 0,  // displacement
      vx: 0, vy: 0, vr: 0    // velocity
    });
    stage.appendChild(d);
  }
  // paint order: elevation first, then smaller pieces above bigger ones
  cells.forEach(function (c) {
    c.el.style.zIndex = c.e * 10 + (4 - Math.round(Math.log2(c.s)));
  });

  var unit = 8;
  function layout() {
    var sw = stage.clientWidth, sh = stage.clientHeight;
    unit = Math.min(sw / BC, sh / BR);
    var ox = (sw - unit * BC) / 2, oy = (sh - unit * BR) / 2;
    cells.forEach(function (c) {
      var side = c.s * unit;
      // taller cells render larger, lifted up-left, with deeper shadow;
      // lift is in base units so height reads the same at every size
      var size = c.e ? side * (0.92 + c.e * 0.05) : side * 0.42;
      var lift = c.e * unit * 0.05;
      c.cx = ox + (c.bx + c.s / 2) * unit - lift;
      c.cy = oy + (c.by + c.s / 2) * unit - lift;
      var el = c.el.style;
      el.width = size + "px";
      el.height = size + "px";
      el.left = c.cx - size / 2 + "px";
      el.top = c.cy - size / 2 + "px";
      el.boxShadow = c.e
        ? lift + "px " + (lift + unit * 0.1) + "px " +
          (c.e * unit * 0.14 + size * 0.06) + "px rgba(60,40,20," +
          (0.1 + c.e * 0.035) + ")"
        : "none";
    });
  }
  layout();
  var rt;
  addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(layout, 100);
  });

  // ---- hover physics ------------------------------------------------
  var px = null, py = null, pvx = 0, pvy = 0, fresh = false;
  var active = new Set();
  var disturbed = false;
  var homing = false;

  stage.addEventListener("pointermove", function (ev) {
    var r = stage.getBoundingClientRect();
    var x = ev.clientX - r.left, y = ev.clientY - r.top;
    if (px !== null) { pvx = x - px; pvy = y - py; }
    px = x; py = y;
    fresh = true;
  });
  stage.addEventListener("pointerleave", function () { px = py = null; });

  function tick() {
    requestAnimationFrame(tick);
    if (homing) return;
    if (fresh && px !== null) {
      fresh = false;
      var R = Math.max(60, unit * 9);
      var speed = Math.min(Math.hypot(pvx, pvy), 40);
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        var ax = c.cx + c.dx - px, ay = c.cy + c.dy - py;
        var d = Math.hypot(ax, ay);
        if (d > R || d === 0) continue;
        var f = (1 - d / R);
        // push away from the cursor, dragged a little by its motion;
        // big pieces are heavy
        var mass = c.s;
        var k = f * f * (3 + speed * 0.55) / mass;
        c.vx += (ax / d) * k + pvx * f * 0.12 / mass;
        c.vy += (ay / d) * k + pvy * f * 0.12 / mass;
        c.vr += (Math.random() - 0.5) * f * 10 / mass;
        active.add(c);
        if (!disturbed) { disturbed = true; restore.classList.add("show"); }
      }
    }
    active.forEach(function (c) {
      c.dx += c.vx; c.dy += c.vy; c.rot += c.vr;
      c.vx *= 0.86; c.vy *= 0.86; c.vr *= 0.86;
      c.el.style.transform = "translate3d(" + c.dx.toFixed(2) + "px," +
        c.dy.toFixed(2) + "px,0) rotate(" + c.rot.toFixed(2) + "deg)";
      if (Math.hypot(c.vx, c.vy) < 0.04 && Math.abs(c.vr) < 0.04) {
        active.delete(c);
      }
    });
  }
  tick();

  restore.addEventListener("click", function () {
    var instant = matchMedia("(prefers-reduced-motion: reduce)").matches;
    homing = true;
    active.clear();
    stage.classList.toggle("homing", !instant);
    cells.forEach(function (c) {
      if (!c.dx && !c.dy && !c.rot) return;
      c.dx = c.dy = c.rot = c.vx = c.vy = c.vr = 0;
      if (!instant) c.el.style.transitionDelay = Math.random() * 0.5 + "s";
      c.el.style.transform = "";
    });
    disturbed = false;
    restore.classList.remove("show");
    setTimeout(function () {
      stage.classList.remove("homing");
      cells.forEach(function (c) { c.el.style.transitionDelay = ""; });
      homing = false;
    }, instant ? 0 : 1400);
  });
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
