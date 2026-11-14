// Hover layer for the dashboard charts (site/index.html).
// Line charts get a crosshair that snaps to the nearest date, column charts a band highlight,
// bar charts a row highlight; each shows one tooltip listing every series at that point.
// Data comes from the JSON blob viz/build.py writes next to each chart. Labels are inserted with
// textContent. With a chart focused, the arrow keys step through the points and Escape closes.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.createElement("div");
  tip.className = "tooltip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  document.body.appendChild(tip);

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }

  function fill(row) {
    tip.replaceChildren();
    var t = document.createElement("div");
    t.className = "t";
    t.textContent = row.t;
    tip.appendChild(t);
    row.items.forEach(function (it) {
      var r = document.createElement("div");
      r.className = "row";
      var k = document.createElement("span");
      k.className = "key" + (it.d ? " dashed" : "") + (it.c ? "" : " none");
      if (it.c) k.style.borderTopColor = "var(--c-" + it.c + ")";
      var v = document.createElement("span");
      v.className = "v";
      v.textContent = it.v;
      var l = document.createElement("span");
      l.className = "l";
      l.textContent = it.l;
      r.append(k, v, l);
      tip.appendChild(r);
    });
  }

  function place(cx, cy) {
    tip.hidden = false;
    var pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    var x = cx + pad, y = cy + pad;
    if (x + w > window.innerWidth - 8) x = cx - pad - w;
    if (y + h > window.innerHeight - 8) y = cy - pad - h;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }

  function nearest(arr, v) {
    var best = 0, bd = Infinity;
    for (var i = 0; i < arr.length; i++) {
      var d = Math.abs(arr[i] - v);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  document.querySelectorAll("svg.chart[data-hover]").forEach(function (svg) {
    var blob = document.getElementById(svg.dataset.hover);
    if (!blob) return;
    var regions = JSON.parse(blob.textContent);
    var layer = el("g", { "class": "c-hover", "aria-hidden": "true", "pointer-events": "none" }, svg);
    var active = null;

    function toSvg(cx, cy) {
      var p = svg.createSVGPoint(); p.x = cx; p.y = cy;
      return p.matrixTransform(svg.getScreenCTM().inverse());
    }
    function toClient(x, y) {
      var p = svg.createSVGPoint(); p.x = x; p.y = y;
      var q = p.matrixTransform(svg.getScreenCTM());
      return [q.x, q.y];
    }
    function positions(r) { return r.mode === "y" ? r.ys : r.xs; }

    function draw(r, i) {
      layer.replaceChildren();
      var x0 = r.plot[0], y0 = r.plot[1], x1 = r.plot[2], y1 = r.plot[3];
      if (r.mode === "y") {
        el("rect", { x: x0, y: r.ys[i] - 13, width: x1 - x0, height: 26, rx: 4, "class": "c-hl" }, layer);
      } else if (r.band) {
        el("rect", { x: r.xs[i] - r.band / 2, y: y0, width: r.band, height: y1 - y0, "class": "c-hl" }, layer);
      } else {
        var x = r.xs[i];
        el("line", { x1: x, x2: x, y1: y0, y2: y1, "class": "c-ref" }, layer);
        r.rows[i].items.forEach(function (it) {
          if (it.y !== null && it.y !== undefined && it.c) {
            el("circle", { cx: x, cy: it.y, r: 4, "class": "f-" + it.c + " c-ring" }, layer);
          }
        });
      }
    }

    function show(r, i, cx, cy) { active = { r: r, i: i }; draw(r, i); fill(r.rows[i]); place(cx, cy); }
    function hide() { active = null; layer.replaceChildren(); tip.hidden = true; }

    svg.addEventListener("pointermove", function (ev) {
      var p = toSvg(ev.clientX, ev.clientY);
      var r = regions.find(function (g) {
        return p.x >= g.plot[0] - 12 && p.x <= g.plot[2] + 12 && p.y >= g.plot[1] - 16 && p.y <= g.plot[3] + 8;
      });
      if (!r) { hide(); return; }
      var i = r.mode === "y" ? nearest(r.ys, p.y) : nearest(r.xs, p.x);
      show(r, i, ev.clientX, ev.clientY);
    });
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { hide(); return; }
      var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
      if (!step) return;
      ev.preventDefault();
      var r = active ? active.r : regions[0];
      var i = active ? active.i + step : (step > 0 ? 0 : positions(r).length - 1);
      if (i < 0 || i >= positions(r).length) {
        var k = regions.indexOf(r) + (i < 0 ? -1 : 1);
        if (k >= 0 && k < regions.length) { r = regions[k]; i = i < 0 ? positions(r).length - 1 : 0; }
        else { i = Math.max(0, Math.min(positions(r).length - 1, i)); }
      }
      var at = r.mode === "y" ? [r.plot[2] - 80, r.ys[i]] : [r.xs[i], r.plot[1] + 8];
      var c = toClient(at[0], at[1]);
      show(r, i, c[0], c[1]);
    });
  });
})();

// On GitHub Pages (https://<owner>.github.io/<repo>/site/) a link to a file in the repo, such as "../THESIS.md" or
// "../queries/l1_activity.sql", would open as raw text or download. There, send it to the same file on github.com.
// Opened from disk or from any other host, the links stay as they are.
(function () {
  "use strict";
  var owner = /^([^.]+)\.github\.io$/.exec(location.hostname);
  var repo = location.pathname.split("/")[1];
  if (!owner || !repo) return;
  var base = "https://github.com/" + owner[1] + "/" + repo + "/";
  document.querySelectorAll('a[href^="../"]').forEach(function (a) {
    var path = a.getAttribute("href").slice(3), hash = "", i = path.indexOf("#");
    if (i >= 0) { hash = path.slice(i); path = path.slice(0, i); }
    var isFolder = path.slice(-1) === "/";
    a.href = base + (isFolder ? "tree/main/" + path.slice(0, -1) : "blob/main/" + path) + hash;
  });
})();
