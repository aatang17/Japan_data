/* House chart chrome for ECharts. All colours come from tokens via cssVar();
   never pass a hex literal here or in page code.
   Chrome rules: horizontal gridlines only, no chart border or background,
   2px lines, crosshair tooltip with all series, zero line when data crosses
   zero, source line included in PNG exports, light-theme exports by default. */
"use strict";

function readPalette() {
  return {
    ink: cssVar("--obs-ink"),
    text: cssVar("--obs-text"),
    muted: cssVar("--obs-text-muted"),
    border: cssVar("--obs-border"),
    grid: cssVar("--obs-grid"),
    surface: cssVar("--obs-surface"),
    subtle: cssVar("--obs-surface-subtle"),
    series: [1, 2, 3, 4, 5, 6].map(i => cssVar("--obs-series-" + i)),
    divergePos: cssVar("--obs-diverge-pos"),
    divergeNeg: cssVar("--obs-diverge-neg"),
  };
}

/* palette for an explicit theme (used for light-mode PNG export) */
function paletteFor(theme) {
  const root = document.documentElement;
  const prev = root.getAttribute("data-theme");
  root.setAttribute("data-theme", theme);
  const p = readPalette();
  if (prev === null) root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", prev);
  return p;
}

function axisCommon(pal) {
  return {
    axisLine: { lineStyle: { color: pal.border } },
    axisTick: { show: false },
    axisLabel: { color: pal.muted, fontSize: 11 },
  };
}

/* cfg: { series: [{name, slot, points: [[iso, v|null], ...]}],
          unit: "%" | "index", yAxisName, trust, sourceLine,
          annotations?: [{x: iso, y: value, text}] }
   Annotations mark real readings (a peak, a policy date) on the first
   series: a small filled point with a label. The caller supplies the
   coordinates from its own data — nothing is computed here. */
function lineOptions(cfg, pal, narrow) {
  // Annual data has no meaningful position between two points, so a fiscal-year
  // series uses a category axis: a time axis would label it by month and imply
  // readings we do not have. Time remains the default for every other caller.
  const isCat = cfg.xType === "category";
  const dp = cfg.dp !== undefined ? cfg.dp : (cfg.unit === "%" ? 2 : 1);
  let crossesZero = false;
  cfg.series.forEach(s => s.points.forEach(p => { if (p[1] !== null && p[1] < 0) crossesZero = true; }));

  const latestOf = s => {
    for (let i = s.points.length - 1; i >= 0; i--) if (s.points[i][1] !== null) return s.points[i][1];
    return -Infinity;
  };
  const ordered = cfg.series.slice().sort((a, b) => latestOf(b) - latestOf(a));

  return {
    animation: false,
    color: pal.series,
    legend: Object.assign(
      {
        show: cfg.series.length > 1,
        itemWidth: 16, itemHeight: 8, itemGap: narrow ? 10 : 18,
        textStyle: { color: pal.text, fontSize: narrow ? 11 : 12, padding: [0, 0, 0, 2] },
        data: ordered.map(s => s.name),
      },
      // narrow containers: legend below the plot; wide: top-right, clear of
      // the y-axis name at top-left
      narrow ? { bottom: 0, left: 0 } : { top: 0, right: 0 }),
    grid: narrow
      ? { left: 8, right: 12, bottom: cfg.series.length > 1 ? 44 : 8, containLabel: true,
          top: cfg.yAxisName ? 26 : 12 }
      : { left: 8, right: 20, bottom: 8, containLabel: true,
          top: cfg.series.length > 1 ? 34 : (cfg.yAxisName ? 28 : 16) },
    xAxis: Object.assign(axisCommon(pal), isCat
      ? { type: "category", boundaryGap: false, splitLine: { show: false },
          data: cfg.series[0].points.map(p => p[0]) }
      : { type: "time", splitLine: { show: false } }),
    yAxis: Object.assign(axisCommon(pal), {
      type: "value",
      scale: cfg.unit !== "%",           // index levels never forced to zero
      name: cfg.yAxisName || "",
      nameTextStyle: { color: pal.muted, fontSize: 11, align: "left" },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: pal.grid, width: 1 } },
    }),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: pal.muted, width: 1 } },
      backgroundColor: pal.surface,
      borderColor: pal.border,
      textStyle: { color: pal.text, fontSize: 12 },
      formatter: params => {
        const date = isCat ? params[0].name
          : fmtPeriod(new Date(params[0].value[0]).toISOString());
        const rows = params.slice()
          .sort((a, b) => ((isCat ? b.value : b.value[1]) ?? -Infinity) -
                          ((isCat ? a.value : a.value[1]) ?? -Infinity))
          .map(p => {
            const v = isCat ? p.value : p.value[1];
            const txt = v === null || v === undefined ? "—"
              : fmtNum(v, dp) + (cfg.unit === "%" ? "%"
                : (cfg.unitSuffix ? " " + cfg.unitSuffix : ""));
            return p.marker + " " + escapeHtml(p.seriesName) +
              ' <span class="num" style="float:right;margin-left:16px;font-weight:600">' + txt + "</span>";
          });
        const trust = TRUST_LABELS[cfg.trust] ? '<div style="margin-top:4px;font-size:11px;color:' +
          pal.muted + '">' + TRUST_LABELS[cfg.trust] + "</div>" : "";
        return '<div style="font-weight:600;margin-bottom:2px">' + date + "</div>" +
          rows.join("<br>") + trust;
      },
    },
    series: ordered.map(s => ({
      name: s.name,
      type: "line",
      showSymbol: isCat,
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { width: 2 },
      itemStyle: { color: pal.series[(s.slot - 1) % 6] },
      emphasis: { focus: "none" },
      data: isCat ? s.points.map(p => p[1]) : s.points.map(p => [p[0], p[1]]),
      markLine: crossesZero && s === ordered[0] ? {
        silent: true, symbol: "none",
        label: { show: false },
        lineStyle: { color: pal.muted, width: 1, type: "solid" },
        data: [{ yAxis: 0 }],
      } : undefined,
      markPoint: cfg.annotations && cfg.annotations.length && s === ordered[0] ? {
        silent: true,
        symbol: "circle", symbolSize: 7,
        itemStyle: { color: pal.ink },
        // narrow plots: the label sits left of the point, since a peak near
        // the right edge would push a centered label off the canvas
        label: { show: true, position: narrow ? "left" : "top",
                 distance: 8, color: pal.ink, fontSize: 11, fontWeight: 600,
                 formatter: p => p.data.text },
        data: cfg.annotations.map(a => ({ coord: [a.x, a.y], text: a.text })),
      } : undefined,
    })),
  };
}

/* cfg: { series: [{name, slot, points}], line: {name, points} | null,
          unit: "pp", yAxisName, trust, sourceLine }
   Stacked bars per series (contributions) with an optional line overlay
   (the total the stacks decompose). */
function stackOptions(cfg, pal, narrow) {
  const isCat = cfg.xType === "category";
  const names = cfg.series.map(s => s.name).concat(cfg.line ? [cfg.line.name] : []);
  return {
    animation: false,
    color: pal.series,
    legend: Object.assign(
      {
        show: true,
        itemWidth: 16, itemHeight: 8, itemGap: narrow ? 8 : 14,
        textStyle: { color: pal.text, fontSize: narrow ? 11 : 12, padding: [0, 0, 0, 2] },
        data: names,
      },
      narrow ? { bottom: 0, left: 0 } : { top: 0, right: 0 }),
    grid: narrow
      ? { left: 8, right: 12, top: 12, bottom: 56, containLabel: true }
      : { left: 8, right: 20, top: 34, bottom: 8, containLabel: true },
    xAxis: Object.assign(axisCommon(pal), { type: "time", splitLine: { show: false } }),
    yAxis: Object.assign(axisCommon(pal), {
      type: "value",
      name: cfg.yAxisName || "",
      nameTextStyle: { color: pal.muted, fontSize: 11, align: "left" },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: pal.grid, width: 1 } },
    }),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: pal.muted, width: 1 } },
      backgroundColor: pal.surface,
      borderColor: pal.border,
      textStyle: { color: pal.text, fontSize: 12 },
      formatter: params => {
        const date = isCat ? params[0].name
          : fmtPeriod(new Date(params[0].value[0]).toISOString());
        const rows = params.slice()
          .sort((a, b) => ((isCat ? b.value : b.value[1]) ?? -Infinity) -
                          ((isCat ? a.value : a.value[1]) ?? -Infinity))
          .map(p => {
            const v = isCat ? p.value : p.value[1];
            const txt = v === null || v === undefined ? "—" : fmtSigned(v, 2, cfg.unit);
            return p.marker + " " + escapeHtml(p.seriesName) +
              ' <span class="num" style="float:right;margin-left:16px;font-weight:600">' + txt + "</span>";
          });
        return '<div style="font-weight:600;margin-bottom:2px">' + date + "</div>" + rows.join("<br>");
      },
    },
    series: cfg.series.map((s, i) => ({
      name: s.name,
      type: "bar",
      stack: "contrib",
      barCategoryGap: "20%",
      itemStyle: { color: pal.series[(s.slot - 1) % 6] },
      emphasis: { focus: "none" },
      data: isCat ? s.points.map(p => p[1]) : s.points.map(p => [p[0], p[1]]),
      markLine: i === 0 ? {
        silent: true, symbol: "none", label: { show: false },
        lineStyle: { color: pal.muted, width: 1, type: "solid" },
        data: [{ yAxis: 0 }],
      } : undefined,
    })).concat(cfg.line ? [{
      name: cfg.line.name,
      type: "line",
      showSymbol: isCat,
      symbolSize: 5,
      connectNulls: false,
      z: 10,
      lineStyle: { width: 2, color: pal.ink },
      itemStyle: { color: pal.ink },
      emphasis: { focus: "none" },
      data: cfg.line.points.map(p => [p[0], p[1]]),
    }] : []),
  };
}

/* cfg: { items: [{name, value, weight, note?}], unit: "%" | "pp",
          valueLabel?, trust, sourceLine }
   note is an optional pre-formatted secondary tooltip line. */
function barOptions(cfg, pal) {
  const items = cfg.items.slice().sort((a, b) => (a.value ?? -Infinity) - (b.value ?? -Infinity));
  const unit = cfg.unit || "%";
  const dp = unit === "pp" ? 2 : 1;
  return {
    animation: false,
    grid: { left: 8, right: 62, top: 8, bottom: 8, containLabel: true },
    xAxis: Object.assign(axisCommon(pal), {
      type: "value",
      splitLine: { show: true, lineStyle: { color: pal.grid, width: 1 } },
      axisLabel: { color: pal.muted, fontSize: 11,
                   formatter: v => unit === "%" ? v + "%" : v },
      axisLine: { show: false },
    }),
    yAxis: Object.assign(axisCommon(pal), {
      type: "category",
      data: items.map(i => i.name),
      axisLabel: { color: pal.text, fontSize: 12 },
    }),
    tooltip: {
      trigger: "item",
      backgroundColor: pal.surface,
      borderColor: pal.border,
      textStyle: { color: pal.text, fontSize: 12 },
      formatter: p => {
        const it = items[p.dataIndex];
        const trust = TRUST_LABELS[cfg.trust] ? '<div style="margin-top:4px;font-size:11px;color:' +
          pal.muted + '">' + TRUST_LABELS[cfg.trust] + "</div>" : "";
        const note = it.note ? "<br>" + '<span style="color:' + pal.muted + '">' +
          escapeHtml(it.note) + "</span>" : "";
        return "<b>" + escapeHtml(it.name) + "</b><br>" +
          (cfg.valueLabel || MEASURE_SHORT.yoy) +
          ': <span class="num" style="font-weight:600">' + fmtSigned(it.value, dp, unit) + "</span>" +
          note + "<br>" +
          '<span style="color:' + pal.muted + '">Weight: ' + fmtNum(it.weight, 0) + " / 10,000</span>" +
          trust;
      },
    },
    series: [{
      type: "bar",
      barWidth: 16,
      data: items.map(i => ({
        value: i.value,
        itemStyle: { color: (i.value ?? 0) >= 0 ? pal.divergePos : pal.divergeNeg },
      })),
      label: {
        show: true,
        position: "right",
        color: pal.ink,
        fontSize: 11.5,
        fontWeight: 600,
        formatter: p => fmtSigned(items[p.dataIndex].value, dp, unit),
      },
      markLine: {
        silent: true, symbol: "none", label: { show: false },
        lineStyle: { color: pal.muted, width: 1, type: "solid" },
        data: [{ xAxis: 0 }],
      },
    }],
  };
}

/* cfg: { categories: ["2025-07", ...], series: [{name, slot, points: [v|null]}],
          dp, unitSuffix, yAxisName, trust, sourceLine }
   Grouped vertical bars: two flows measured in the same unit over the same
   months, side by side rather than stacked — they are different acts and their
   sum means nothing. Zero baseline always; a bar axis is never truncated. */
function colsOptions(cfg, pal, narrow) {
  const dp = cfg.dp === undefined ? 1 : cfg.dp;
  const suffix = cfg.unitSuffix ? " " + cfg.unitSuffix : "";
  const fmt = v => (v === null || v === undefined ? "—" : fmtNum(v, dp) + suffix);
  return {
    animation: false,
    color: pal.series,
    legend: Object.assign(
      { itemWidth: 14, itemHeight: 8, itemGap: narrow ? 10 : 18,
        textStyle: { color: pal.text, fontSize: narrow ? 11 : 12, padding: [0, 0, 0, 2] },
        data: cfg.series.map(s => s.name) },
      narrow ? { bottom: 0, left: 0 } : { top: 0, right: 0 }),
    grid: { left: 8, right: 12, containLabel: true,
            top: narrow ? 26 : 34, bottom: narrow ? 44 : 8 },
    xAxis: Object.assign(axisCommon(pal), {
      type: "category", data: cfg.categories,
      splitLine: { show: false },
      axisLabel: { color: pal.muted, fontSize: 11,
                   // a month label per bar is unreadable at phone width
                   interval: narrow ? 2 : 0, rotate: narrow ? 0 : 0 },
    }),
    yAxis: Object.assign(axisCommon(pal), {
      type: "value", min: 0,
      name: cfg.yAxisName || "",
      nameTextStyle: { color: pal.muted, fontSize: 11, align: "left" },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: pal.grid, width: 1 } },
    }),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: pal.subtle } },
      backgroundColor: pal.surface,
      borderColor: pal.border,
      textStyle: { color: pal.text, fontSize: 12 },
      formatter: params => {
        const rows = params.map(p => p.marker + " " + escapeHtml(p.seriesName) +
          ' <span class="num" style="float:right;margin-left:16px;font-weight:600">' +
          fmt(p.value) + "</span>");
        const note = (cfg.notes && cfg.notes[params[0].dataIndex])
          ? '<div style="margin-top:4px;font-size:11px;color:' + pal.muted + '">' +
            escapeHtml(cfg.notes[params[0].dataIndex]) + "</div>" : "";
        const trust = TRUST_LABELS[cfg.trust] ? '<div style="margin-top:4px;font-size:11px;color:' +
          pal.muted + '">' + TRUST_LABELS[cfg.trust] + "</div>" : "";
        return '<div style="font-weight:600;margin-bottom:2px">' +
          escapeHtml(params[0].name) + "</div>" + rows.join("<br>") + note + trust;
      },
    },
    series: cfg.series.map(s => ({
      name: s.name,
      type: "bar",
      barMaxWidth: 22,
      itemStyle: { color: pal.series[(s.slot - 1) % 6] },
      emphasis: { focus: "none" },
      data: s.points,
    })),
  };
}

/* mount a chart; returns {render, exportPNG, exportCSV, dispose} */
function obsChart(el, kind, cfg) {
  let chart = null;
  const optionsFor = (pal, widthPx) => {
    const narrow = (widthPx || el.clientWidth) < 520;
    if (kind === "line") return lineOptions(cfg, pal, narrow);
    if (kind === "stack") return stackOptions(cfg, pal, narrow);
    if (kind === "cols") return colsOptions(cfg, pal, narrow);
    return barOptions(cfg, pal);
  };

  function render(newCfg) {
    if (newCfg) cfg = newCfg;
    if (chart) chart.dispose();
    chart = echarts.init(el, null, { renderer: "canvas" });
    chart.setOption(optionsFor(readPalette()));
  }

  function exportPNG(filename) {
    // exports are light-theme by default: they end up in decks and documents
    const pal = paletteFor("light");
    const off = document.createElement("div");
    off.style.cssText = "position:fixed;left:-99999px;width:1200px;height:560px";
    document.body.appendChild(off);
    const tmp = echarts.init(off, null, { renderer: "canvas" });
    const opts = optionsFor(pal, 1200);
    opts.graphic = [{
      type: "text", left: 10, bottom: 6,
      style: { text: cfg.sourceLine || "", fontSize: 11, fill: pal.muted },
    }];
    opts.grid.bottom = 30;
    tmp.setOption(opts);
    const url = tmp.getDataURL({ pixelRatio: 2, backgroundColor: pal.surface });
    tmp.dispose();
    off.remove();
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  }

  function exportCSV(filename, headerLines) {
    let csv = (headerLines || []).map(l => "# " + l).join("\n") + "\n";
    if (kind === "cols") {
      csv += "period," + cfg.series.map(c => '"' + c.name.replace(/"/g, '""') + '"').join(",") + "\n";
      cfg.categories.forEach((cat, i) => {
        csv += cat + "," + cfg.series.map(s => {
          const v = s.points[i];
          return v === null || v === undefined ? "" : v;
        }).join(",") + "\n";
      });
    } else if (kind === "line" || kind === "stack") {
      const cols = kind === "stack" && cfg.line ? cfg.series.concat([cfg.line]) : cfg.series;
      const periods = new Set();
      cols.forEach(s => s.points.forEach(p => periods.add(p[0])));
      csv += "period," + cols.map(c => '"' + c.name.replace(/"/g, '""') + '"').join(",") + "\n";
      Array.from(periods).sort().forEach(period => {
        const row = cols.map(s => {
          const hit = s.points.find(p => p[0] === period);
          return hit && hit[1] !== null ? hit[1] : "";
        });
        csv += fmtPeriod(period) + "," + row.join(",") + "\n";
      });
    } else {
      csv += "group,value,weight_per_10000\n";
      cfg.items.forEach(i => {
        csv += '"' + i.name.replace(/"/g, '""') + '",' + (i.value ?? "") + "," + (i.weight ?? "") + "\n";
      });
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  window.addEventListener("resize", () => { if (chart) chart.resize(); });
  render();
  return { render, exportPNG, exportCSV, dispose: () => chart && chart.dispose() };
}

/* tiny inline-SVG sparkline; gaps in the data stay gaps */
function sparkSVG(points, w, h) {
  w = w || 110; h = h || 26;
  const vals = points.map(p => p[1]).filter(v => v !== null && v !== undefined);
  if (vals.length < 2) return "";
  const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  const span = max - min || 1;
  const n = points.length;
  const segs = [];
  let cur = [];
  points.forEach((p, i) => {
    if (p[1] === null || p[1] === undefined) {
      if (cur.length > 1) segs.push(cur);
      cur = [];
      return;
    }
    const x = (i / (n - 1)) * (w - 2) + 1;
    const y = h - 2 - ((p[1] - min) / span) * (h - 4);
    cur.push(x.toFixed(1) + "," + y.toFixed(1));
  });
  if (cur.length > 1) segs.push(cur);
  const lines = segs.map(s => '<polyline points="' + s.join(" ") + '"/>').join("");
  return '<svg class="spark" width="' + w + '" height="' + h +
    '" viewBox="0 0 ' + w + " " + h + '" aria-hidden="true">' + lines + "</svg>";
}
