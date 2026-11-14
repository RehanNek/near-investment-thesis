"""SVG chart renderer for the dashboard (site/index.html) and the images in THESIS.md (site/charts/).

No plotting library. Each chart is plain SVG, so the same drawing works as a static image on GitHub
and inline on the dashboard, where site/app.js adds hover tooltips from a small JSON blob emitted
next to each chart. Colors are CSS custom properties: the dashboard swaps them for dark mode, and
standalone files carry the light values.

Mark specs: 2px lines, columns at most 24px wide with a 4px rounded top and a square base, a 2px
surface gap between stacked segments, end dots with a 2px surface ring, solid hairline gridlines,
a legend whenever there are two or more series, and values labelled selectively.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from datetime import date, datetime

W = 720
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Entity colors, fixed across the whole report: color follows the entity, never its rank.
# Slots from the reference categorical palette: Intents = blue, L1 = orange, NEAR AI = aqua,
# KaiChing = yellow, HOT = magenta, bridge aggregators = green. "rest" is a neutral gray for
# "everything else", "ink" is for reference series such as NEAR issued, and o1-o3 are an ordinal
# blue ramp (bear / base / bull, or variants of one metric). Every combination drawn together was
# checked with the dataviz skill's validate_palette.js, in light and dark mode.
PALETTE = {
    #            light      dark
    "intents":  ("#2a78d6", "#3987e5"),
    "l1":       ("#eb6834", "#d95926"),
    "ai":       ("#1baf7a", "#199e70"),
    "kaiching": ("#eda100", "#c98500"),
    "hot":      ("#e87ba4", "#d55181"),
    "agg":      ("#008300", "#008300"),
    "rest":     ("#b5b3aa", "#5f5e59"),
    "ink":      ("#52514e", "#c3c2b7"),
    "o1":       ("#86b6ef", "#184f95"),
    "o2":       ("#2a78d6", "#3987e5"),
    "o3":       ("#104281", "#9ec5f4"),
}
CHROME = {
    "surface": ("#fcfcfb", "#1a1a19"),
    "page":    ("#f9f9f7", "#0d0d0d"),
    "text-1":  ("#0b0b0b", "#f0efec"),
    "text-2":  ("#52514e", "#c3c2b7"),
    "muted":   ("#898781", "#898781"),
    "grid":    ("#e1e0d9", "#2c2c2a"),
    "axis":    ("#c3c2b7", "#383835"),
    "border":  ("rgba(11,11,11,0.10)", "rgba(255,255,255,0.10)"),
    "wash":    ("rgba(11,11,11,0.05)", "rgba(255,255,255,0.07)"),
    "link":    ("#256abf", "#86b6ef"),
}


def css_vars(mode: int) -> str:
    """CSS custom properties for light (0) or dark (1) mode."""
    out = [f"--{k}:{v[mode]}" for k, v in CHROME.items()]
    out += [f"--c-{k}:{v[mode]}" for k, v in PALETTE.items()]
    return ";".join(out)


CHART_CSS = (
    ".c-bg{fill:var(--surface)}"
    ".c-grid{stroke:var(--grid);stroke-width:1;shape-rendering:crispEdges}"
    ".c-axis{stroke:var(--axis);stroke-width:1;shape-rendering:crispEdges}"
    f"svg text{{font-family:{FONT}}}"
    ".c-tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}"
    ".c-lbl{fill:var(--text-2);font-size:12px}"
    ".c-sm{fill:var(--text-2);font-size:11px}"
    ".c-val{fill:var(--text-1);font-size:12px;font-weight:600}"
    ".c-big{fill:var(--text-1);font-size:20px;font-weight:600}"
    ".c-head{fill:var(--text-1);font-size:12px;font-weight:600}"
    ".c-ref{stroke:var(--text-2);stroke-width:1}"
    ".c-event{stroke:var(--axis);stroke-width:1}"
    ".c-line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}"
    ".c-dash{stroke-dasharray:6 4}"
    ".c-ring{stroke:var(--surface);stroke-width:2}"
    ".c-node{fill:var(--surface);stroke:var(--axis);stroke-width:1}"
    ".c-arrow{stroke:var(--muted);stroke-width:1.5;fill:none}"
    ".c-head-fill{fill:var(--muted)}"
    ".c-hl{fill:var(--wash)}"
    + "".join(f".f-{k}{{fill:var(--c-{k})}}.k-{k}{{stroke:var(--c-{k})}}" for k in PALETTE)
)


# ---------- text and number formatting ----------

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def text(x, y, s, cls="c-lbl", anchor="start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{esc(s)}</text>'


def text_w(s, size=12, bold=False) -> float:
    """Rough rendered width of a label, for layout (system sans, mixed case)."""
    return len(str(s)) * size * (0.6 if bold else 0.55)


def isnum(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def compact(v: float, digits: int = 1) -> str:
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div * 0.9995:
            s = f"{v / div:.{digits}f}"
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s + suf
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    s = f"{v:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt(v, kind: str = "count", digits: int = 1) -> str:
    """Format a value for labels and tooltips."""
    if not isnum(v):
        return "–"
    if kind == "usd":
        return ("-" if v < 0 else "") + "$" + compact(abs(v), digits)
    if kind == "pct":
        return f"{v:.{digits}f}%" if abs(v) < 100 else f"{v:,.0f}%"
    if kind == "rate":
        return f"{v:.2f}%"
    if kind == "near":
        return compact(v, digits) + " NEAR"
    if kind == "index":
        return f"{v:,.0f}"
    return compact(v, digits)


def tick_fmt(v, kind: str) -> str:
    if kind == "usd":
        return "$" + compact(v, 2)
    if kind in ("pct", "rate"):
        return f"{v:g}%"
    if kind == "index":
        return f"{v:,.0f}"
    return compact(v, 2)


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw * 0.999)
    ticks = [math.floor(lo / step + 1e-9) * step]
    while ticks[-1] < hi - step * 1e-9:
        ticks.append(ticks[-1] + step)
    return [round(t, 10) for t in ticks]


# ---------- dates ----------

MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def as_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    s = str(x)
    if len(s) == 7:
        s += "-01"
    return date.fromisoformat(s[:10])


def month_add(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    return date(d.year + y, m + 1, 1)


def label_for(d: date, gran: str) -> str:
    if gran == "month":
        return f"{MON[d.month - 1]} {d.year}"
    if gran == "quarter":
        return f"{d.year} Q{(d.month - 1) // 3 + 1}"
    if gran == "week":
        return f"Week to {MON[d.month - 1]} {d.day}, {d.year}"
    return f"{MON[d.month - 1]} {d.day}, {d.year}"


def time_ticks(d0: date, d1: date, max_n: int = 8) -> list[tuple[date, str]]:
    span = (d1 - d0).days
    if span <= 100:
        out, d = [], date(d0.year, d0.month, 1)
        while d <= d1:
            for day in (1, 15):
                t = d.replace(day=day)
                if d0 <= t <= d1:
                    out.append((t, MON[t.month - 1] if day == 1 else f"{MON[t.month - 1]} 15"))
            d = month_add(d, 1)
        return out
    if span > 3 * 366:
        return [(date(y, 1, 1), str(y)) for y in range(d0.year, d1.year + 1) if d0 <= date(y, 1, 1) <= d1]
    months = []
    for k in (1, 2, 3, 6, 12):
        months, d = [], date(d0.year, d0.month, 1)
        if d < d0:
            d = month_add(d, 1)
        while d <= d1:
            if (d.month - 1) % k == 0:
                months.append(d)
            d = month_add(d, 1)
        if len(months) <= max_n:
            break
    return [(m, f"{MON[m.month - 1]} {m.year}" if (m.month == 1 or i == 0) else MON[m.month - 1])
            for i, m in enumerate(months)]


# ---------- chart pieces ----------

@dataclass
class Series:
    label: str
    values: list
    color: str
    dashed: bool = False
    end_label: str | None = None   # short name printed after the end value; None = value only
    show_end: bool = True
    kind: str | None = None        # value format, defaults to the chart's


@dataclass
class Event:
    when: date
    label: str


@dataclass
class Mark:
    when: date
    value: float
    label: str
    color: str = "ink"
    dy: float = -10          # label offset from the dot; positive = below
    dx: float = 0
    anchor: str = "middle"


@dataclass
class Ref:
    value: float
    label: str
    anchor: str = "start"   # "end" puts the label at the right end of the line


@dataclass
class Chart:
    id: str
    body: str
    height: float
    title: str
    desc: str
    hover: list = field(default_factory=list)

    def _open(self, extra: str) -> str:
        return (f'<svg viewBox="0 0 {W} {self.height:.0f}" role="img" '
                f'aria-labelledby="{self.id}-t {self.id}-d"{extra}>'
                f'<title id="{self.id}-t">{esc(self.title)}</title><desc id="{self.id}-d">{esc(self.desc)}</desc>')

    def inline(self) -> str:
        hv = f' data-hover="hover-{self.id}" tabindex="0"' if self.hover else ""
        return (self._open(f' class="chart" id="svg-{self.id}"{hv}')
                + f'<rect class="c-bg" width="{W}" height="{self.height:.0f}"/>' + self.body + "</svg>")

    def standalone(self) -> str:
        style = f"svg{{{css_vars(0)}}}" + CHART_CSS
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                + self._open(f' xmlns="http://www.w3.org/2000/svg" width="{W}" height="{self.height:.0f}"')
                + f"<style>{style}</style>"
                + f'<rect class="c-bg" width="{W}" height="{self.height:.0f}"/>' + self.body + "</svg>\n")


def legend(items, x: float, y: float, max_x: float) -> tuple[str, float]:
    """items: (label, color, shape 'line'|'rect', dashed). Returns (svg, height used)."""
    out, cx, cy = [], x, y
    for label, color, shape, dashed in items:
        key_w = 22 if shape == "line" else 16
        w = key_w + text_w(label) + 18
        if cx + w > max_x and cx > x:
            cx, cy = x, cy + 18
        if shape == "line":
            dash = " c-dash" if dashed else ""
            out.append(f'<line x1="{cx:.1f}" y1="{cy - 4:.1f}" x2="{cx + 16:.1f}" y2="{cy - 4:.1f}" class="c-line k-{color}{dash}"/>')
        else:
            out.append(f'<rect x="{cx:.1f}" y="{cy - 10:.1f}" width="10" height="10" rx="2" class="f-{color}"/>')
        out.append(text(cx + key_w, cy, label))
        cx += w
    return "".join(out), (cy - y) + 18 if items else 0


def _event_rows(xs_labels, x_min: float, x_max: float) -> list[tuple[float, str, int, str]]:
    """Greedy row assignment for event labels so they don't overlap. Returns (x, label, row, anchor)."""
    placed, rows_end = [], []
    for x, label in sorted(xs_labels):
        w = text_w(label, 11)
        anchor, left = "start", x + 4
        if left + w > x_max:
            anchor, left = "end", x - 4 - w
        right = left + w
        row = next((i for i, end in enumerate(rows_end) if left > end + 8), None)
        if row is None:
            rows_end.append(right)
            row = len(rows_end) - 1
        else:
            rows_end[row] = right
        placed.append((x, label, row, anchor))
    return placed


def _line_path(points) -> str:
    """points: list of (x, y) or None for gaps."""
    d, pen = [], False
    for p in points:
        if p is None:
            pen = False
            continue
        d.append(f"{'L' if pen else 'M'}{p[0]:.1f},{p[1]:.1f}")
        pen = True
    return "".join(d)


def _rounded_top(x, y, w, h, r=4.0) -> str:
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}A{r:.1f},{r:.1f} 0 0 1 {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}A{r:.1f},{r:.1f} 0 0 1 {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def _rounded_right(x, y, w, h, r=4.0) -> str:
    r = min(r, h / 2, w)
    return (f"M{x:.1f},{y:.1f}H{x + w - r:.1f}A{r:.1f},{r:.1f} 0 0 1 {x + w:.1f},{y + r:.1f}"
            f"V{y + h - r:.1f}A{r:.1f},{r:.1f} 0 0 1 {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z")


def _arrowhead(x, y, direction=1) -> str:
    return f'<path d="M{x:.1f},{y:.1f}l{-7 * direction:.1f},-4v8z" class="c-head-fill"/>'


# ---------- line charts (one or more panels sharing a y scale) ----------

def _time_panel(cid, k, rect, dates, series, ylo, yhi, yticks, kind, gran, *, events=(), refs=(),
                marks=(), show_y=True, clip=False, xlim=None, title=None, tooltip_extra=None):
    x0, y0, x1, y1 = rect
    d0, d1 = xlim if xlim else (min(dates), max(dates))
    o0, o1 = d0.toordinal(), d1.toordinal()

    def sx(d):
        return x0 + (d.toordinal() - o0) / max(1, o1 - o0) * (x1 - x0)

    def sy(v):
        return y1 - (v - ylo) / (yhi - ylo) * (y1 - y0)

    out = []
    if title:
        out.append(text(x0, y0 - 14, title, "c-head"))  # clear of lines clipped at the top of the plot
    for t in yticks:
        y = sy(t)
        out.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{y:.1f}" y2="{y:.1f}" class="{"c-axis" if t == ylo else "c-grid"}"/>')
        if show_y:
            out.append(text(x0 - 8, y + 4, tick_fmt(t, kind), "c-tick", "end"))
    for d, lab in time_ticks(d0, d1):
        out.append(text(sx(d), y1 + 18, lab, "c-tick", "middle"))
    for ev in events:
        x = sx(ev.when)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0:.1f}" y2="{y1:.1f}" class="c-event"/>')
    for ref in refs:
        y = sy(ref.value)
        out.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{y:.1f}" y2="{y:.1f}" class="c-ref"/>')
        if ref.label:
            out.append(text(x1 - 4, y - 6, ref.label, "c-sm", "end") if ref.anchor == "end"
                       else text(x0 + 4, y - 6, ref.label, "c-sm"))

    clip_attr = ""
    if clip:
        out.append(f'<clipPath id="{cid}-clip{k}"><rect x="{x0 - 6:.1f}" y="{y0 - 6:.1f}" '
                   f'width="{x1 - x0 + 12:.1f}" height="{y1 - y0 + 12:.1f}"/></clipPath>')
        clip_attr = f' clip-path="url(#{cid}-clip{k})"'
    ends = []
    for s in series:
        pts = [(sx(d), sy(v)) if isnum(v) else None for d, v in zip(dates, s.values)]
        dash = " c-dash" if s.dashed else ""
        out.append(f'<path d="{_line_path(pts)}" class="c-line k-{s.color}{dash}"{clip_attr}/>')
        last = next((i for i in range(len(pts) - 1, -1, -1) if pts[i] is not None), None)
        if last is not None and s.show_end and s.values[last] <= yhi:
            ends.append((s, pts[last], s.values[last]))
    labels = []
    for s, (x, y), v in ends:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="f-{s.color} c-ring"/>')
        labels.append((y, x, s, v))
    # End labels: value, then the short name. Drop a label rather than nudge it off its line.
    kept_y = []
    for y, x, s, v in labels:
        if any(abs(y - ky) < 14 for ky in kept_y):
            continue
        kept_y.append(y)
        val = fmt(v, s.kind or kind)
        out.append(f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" class="c-val">{esc(val)}'
                   + (f'<tspan class="c-lbl" dx="5">{esc(s.end_label)}</tspan>' if s.end_label else "")
                   + "</text>")
    for m in marks:
        if not (ylo <= m.value <= yhi):
            continue
        x, y = sx(m.when), sy(m.value)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="f-{m.color} c-ring"/>')
        w = text_w(m.label, 11)
        tx = x + m.dx if m.anchor != "middle" else min(max(x, x0 + w / 2), x1 - w / 2)
        out.append(text(tx, y + m.dy + (4 if m.dy > 0 else 0), m.label, "c-sm", m.anchor))

    rows = []
    for i, d in enumerate(dates):
        items = []
        for s in series:
            v = s.values[i]
            if isnum(v):
                items.append({"l": s.label, "v": fmt(v, s.kind or kind, 2 if (s.kind or kind) in ("rate",) else 1),
                              "c": s.color, "d": s.dashed, "y": round(sy(v), 1) if ylo <= v <= yhi else None})
        if tooltip_extra:
            items += [{"l": l, "v": v} for l, v in tooltip_extra[i]]
        rows.append({"t": label_for(d, gran), "items": items})
    region = {"mode": "x", "plot": [x0, y0, x1, y1], "xs": [round(sx(d), 1) for d in dates], "rows": rows}
    return "".join(out), region


def line_chart(cid, dates, series, *, kind, gran, title, desc, height=300, y_min=0.0, y_max=None,
               events=(), refs=(), marks=(), xlim=None, tooltip_extra=None, legend_items=None) -> Chart:
    dates = [as_date(d) for d in dates]
    vals = [v for s in series for v in s.values if isnum(v)] + [r.value for r in refs]
    ticks = nice_ticks(y_min, y_max if y_max is not None else max(vals))
    ylo, yhi = ticks[0], ticks[-1]
    # right margin fits the end labels
    right = 16
    for s in series:
        last = next((v for v in reversed(s.values) if isnum(v)), None)
        if last is not None and s.show_end:
            right = max(right, 18 + text_w(fmt(last, s.kind or kind), 12, True) + (text_w(s.end_label) + 6 if s.end_label else 0))
    left = 14 + max(text_w(tick_fmt(t, kind), 11) for t in ticks)
    x0, x1 = left, W - right
    items = legend_items if legend_items is not None else (
        [(s.label, s.color, "line", s.dashed) for s in series] if len(series) > 1 else [])
    leg, leg_h = legend(items, x0, 16, W - 8)
    d0, d1 = xlim if xlim else (min(dates), max(dates))
    span = max(1, d1.toordinal() - d0.toordinal())
    ev_xy = [(x0 + (as_date(e.when).toordinal() - d0.toordinal()) / span * (x1 - x0), e.label) for e in events]
    placed = _event_rows(ev_xy, x0, W - 4)
    n_rows = max((p[2] for p in placed), default=-1) + 1
    top = 8 + leg_h + n_rows * 15 + (10 if n_rows else 6)
    y0, y1 = top, height - 30
    ev_svg = ""
    for x, l, r, a in placed:
        ly = top - 8 - (n_rows - 1 - r) * 15
        ev_svg += text(x + 4 if a == "start" else x - 4, ly, l, "c-sm", a)
        ev_svg += f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ly - 9:.1f}" y2="{y0:.1f}" class="c-event"/>'
    body, region = _time_panel(cid, 0, (x0, y0, x1, y1), dates, series, ylo, yhi, ticks, kind, gran,
                               events=[Event(as_date(e.when), e.label) for e in events], refs=refs,
                               marks=[Mark(as_date(m.when), m.value, m.label, m.color, m.dy, m.dx, m.anchor) for m in marks],
                               xlim=(d0, d1), tooltip_extra=tooltip_extra)
    return Chart(cid, leg + ev_svg + body, height, title, desc, [region])


def panel_line_chart(cid, panels, *, kind, gran, title, desc, height=320, y_min=0.0, y_max=None,
                     refs=(), legend_items=None) -> Chart:
    """Small multiples: panels = [(panel_title, dates, [Series], [Mark])], one shared y scale."""
    vals = [v for _, _, ss, _ in panels for s in ss for v in s.values if isnum(v)]
    ticks = nice_ticks(y_min, y_max if y_max is not None else max(vals))
    ylo, yhi = ticks[0], ticks[-1]
    left = 14 + max(text_w(tick_fmt(t, kind), 11) for t in ticks)
    leg, leg_h = legend(legend_items or [], left, 16, W - 8)
    y0, y1 = 8 + leg_h + 30, height - 30
    gap, n = 28, len(panels)
    pw = (W - left - 12 - gap * (n - 1)) / n
    body, regions = [leg], []
    for k, (ptitle, dates, ss, marks) in enumerate(panels):
        dates = [as_date(d) for d in dates]
        px0 = left + k * (pw + gap)
        svg_, region = _time_panel(cid, k, (px0, y0, px0 + pw, y1), dates, ss, ylo, yhi, ticks, kind, gran,
                                   refs=refs if k == n - 1 else [Ref(r.value, "", r.anchor) for r in refs],
                                   marks=[Mark(as_date(m.when), m.value, m.label, m.color, m.dy, m.dx, m.anchor) for m in marks],
                                   show_y=(k == 0), clip=True, title=ptitle)
        body.append(svg_)
        regions.append(region)
    return Chart(cid, "".join(body), height, title, desc, regions)


# ---------- columns ----------

def column_chart(cid, cats, stacks, *, kind, gran, title, desc, height=300, lines=(), events=(),
                 label_last=True, tooltip_extra=None, total_label="Total", show_total=True,
                 legend_extra=()) -> Chart:
    cats = [as_date(c) for c in cats]
    n = len(cats)
    totals = [sum(max(0.0, s.values[i]) for s in stacks if isnum(s.values[i])) for i in range(n)]
    line_vals = [v for s in lines for v in s.values if isnum(v)]
    ticks = nice_ticks(0, max(totals + line_vals))
    ylo, yhi = ticks[0], ticks[-1]
    left = 14 + max(text_w(tick_fmt(t, kind), 11) for t in ticks)
    x0, x1 = left, W - 16
    items = [(s.label, s.color, "rect", False) for s in stacks] + [(s.label, s.color, "line", s.dashed) for s in lines]
    items += list(legend_extra)
    leg, leg_h = legend(items if len(items) > 1 else [], x0, 16, W - 8)
    band = (x1 - x0) / n
    cx = [x0 + band * (i + 0.5) for i in range(n)]
    idx = {c: i for i, c in enumerate(cats)}
    ev_xy = [(cx[idx[as_date(e.when)]], e.label) for e in events if as_date(e.when) in idx]
    placed = _event_rows(ev_xy, x0, W - 4)
    n_rows = max((p[2] for p in placed), default=-1) + 1
    top = 8 + leg_h + n_rows * 15 + (10 if n_rows else 6) + (14 if label_last else 0)
    y0, y1 = top, height - 30

    def sy(v):
        return y1 - (v - ylo) / (yhi - ylo) * (y1 - y0)

    out = [leg]
    for x, l, r, a in placed:
        ly = top - 8 - (14 if label_last else 0) - (n_rows - 1 - r) * 15
        out.append(text(x + 4 if a == "start" else x - 4, ly, l, "c-sm", a))
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ly - 9:.1f}" y2="{y1:.1f}" class="c-event"/>')
    for t in ticks:
        y = sy(t)
        out.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{y:.1f}" y2="{y:.1f}" class="{"c-axis" if t == ylo else "c-grid"}"/>')
        out.append(text(x0 - 8, y + 4, tick_fmt(t, kind), "c-tick", "end"))
    # x labels: monthly at quarter starts; otherwise every k-th so they fit
    lab = [(f"{MON[c.month - 1]} {c.year}" if gran == "month" else f"{MON[c.month - 1]} {c.day}") for c in cats]
    if gran == "month":
        show = [i for i, c in enumerate(cats) if (c.month - 1) % 3 == 0] if n > 12 else list(range(n))
        lab = [f"{MON[c.month - 1]} {c.year}" if (c.month == 1 or i == show[0]) else MON[c.month - 1]
               for i, c in enumerate(cats)]
    else:
        k = max(1, math.ceil(max(text_w(s, 11) for s in lab) * 1.3 / band))
        show = list(range(n - 1, -1, -k))
    for i in show:
        out.append(text(cx[i], y1 + 18, lab[i], "c-tick", "middle"))

    bw = min(24.0, band * 0.7)
    for i in range(n):
        segs = [(s, s.values[i]) for s in stacks if isnum(s.values[i]) and s.values[i] > 0]
        cum, top_j = 0.0, len(segs) - 1
        for j, (s, v) in enumerate(segs):
            yb, yt = sy(cum), sy(cum + v)
            cum += v
            if j > 0:
                yb -= 2  # surface gap above the segment below
            h = yb - yt
            if h <= 0.4:
                continue
            if j == top_j:
                out.append(f'<path d="{_rounded_top(cx[i] - bw / 2, yt, bw, h)}" class="f-{s.color}"/>')
            else:
                out.append(f'<rect x="{cx[i] - bw / 2:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{h:.1f}" class="f-{s.color}"/>')
    for s in lines:
        pts = [(cx[i], sy(v)) if isnum(v) else None for i, v in enumerate(s.values)]
        out.append(f'<path d="{_line_path(pts)}" class="c-line k-{s.color}{" c-dash" if s.dashed else ""}"/>')
    if label_last and n:
        out.append(text(cx[-1], sy(totals[-1]) - 7, fmt(totals[-1], kind), "c-val", "middle"))

    rows = []
    for i, c in enumerate(cats):
        items = [{"l": s.label, "v": fmt(s.values[i], s.kind or kind), "c": s.color}
                 for s in reversed(stacks) if isnum(s.values[i])]
        if show_total and len(stacks) > 1:
            items.append({"l": total_label, "v": fmt(totals[i], kind)})
        items += [{"l": s.label, "v": fmt(s.values[i], s.kind or kind), "c": s.color, "d": s.dashed}
                  for s in lines if isnum(s.values[i])]
        if tooltip_extra:
            items += [{"l": l, "v": v} for l, v in tooltip_extra[i]]
        rows.append({"t": label_for(c, gran), "items": items})
    region = {"mode": "x", "band": round(band, 1), "plot": [x0, y0, x1, y1], "xs": [round(x, 1) for x in cx], "rows": rows}
    return Chart(cid, "".join(out), height, title, desc, [region])


# ---------- horizontal bars ----------

def hbar_chart(cid, rows, *, kind, color, title, desc, value_fmt=None) -> Chart:
    """rows: [(label, value)] in display order. Bars carry their value at the tip."""
    row_h, bar_h, top = 28, 14, 8
    height = top + len(rows) * row_h + 10
    label_w = max(text_w(l) for l, _ in rows) + 14
    x0, x1 = label_w + 4, W - 70
    vmax = max(v for _, v in rows) or 1
    out = [f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="{top:.1f}" y2="{top + len(rows) * row_h:.1f}" class="c-axis"/>']
    ys, hrows = [], []
    for i, (label, v) in enumerate(rows):
        y = top + i * row_h + (row_h - bar_h) / 2
        w = max(1.0, (x1 - x0) * v / vmax)
        out.append(text(x0 - 10, y + bar_h - 3, label, "c-lbl", "end"))
        out.append(f'<path d="{_rounded_right(x0 + 1, y, w, bar_h)}" class="f-{color}"/>')
        val = value_fmt(v) if value_fmt else fmt(v, kind)
        out.append(text(x0 + 1 + w + 6, y + bar_h - 3, val, "c-val"))
        ys.append(round(y + bar_h / 2, 1))
        hrows.append({"t": label, "items": [{"l": title, "v": val, "c": color}]})
    region = {"mode": "y", "plot": [0, top, W, top + len(rows) * row_h], "ys": ys, "rows": hrows}
    return Chart(cid, "".join(out), height, title, desc, [region])


# ---------- flow diagram ----------

def node(x, y, w, h, color, value, lines, note=None, *, center=False) -> str:
    out = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" class="c-node"/>']
    colors = color if isinstance(color, (list, tuple)) else [color]
    for k, c in enumerate(colors):
        out.append(f'<rect x="{x + 12 + k * 28:.1f}" y="{y + 12:.1f}" width="24" height="4" rx="2" class="f-{c}"/>')
    vy = y + (h / 2 - 8 if center else 40)
    out.append(text(x + 12, vy, value, "c-big"))
    for k, line in enumerate(lines):
        out.append(text(x + 12, vy + 20 + k * 15, line, "c-lbl"))
    if note:
        for k, line in enumerate(note if isinstance(note, (list, tuple)) else [note]):
            out.append(text(x + 12, vy + 20 + len(lines) * 15 + 6 + k * 14, line, "c-sm"))
    return "".join(out)


def varrow(x, y1, y2, label="", cls="c-sm") -> str:
    """A downward arrow from y1 to y2, with an optional one-line note to its right."""
    out = [f'<line x1="{x:.1f}" y1="{y1 + 2:.1f}" x2="{x:.1f}" y2="{y2 - 7:.1f}" class="c-arrow"/>',
           f'<path d="M{x:.1f},{y2 - 1:.1f}l-4,-7h8z" class="c-head-fill"/>']
    if label:
        out.append(text(x + 14, (y1 + y2) / 2 + 4, label, cls))
    return "".join(out)


def arrow(x1, y, x2, label_lines=()) -> str:
    out = [f'<line x1="{x1 + 3:.1f}" y1="{y:.1f}" x2="{x2 - 6:.1f}" y2="{y:.1f}" class="c-arrow"/>',
           _arrowhead(x2 - 1, y)]
    mid = (x1 + x2) / 2
    for k, line in enumerate(label_lines):
        out.append(text(mid, y - 8 - (len(label_lines) - 1 - k) * 13, line, "c-sm", "middle"))
    return "".join(out)
