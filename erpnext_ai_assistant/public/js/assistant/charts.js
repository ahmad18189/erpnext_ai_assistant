/* The ERPNext-AI-Assistant panel: SVG charts drawn from answer data. */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_charts) return; // loaded twice (Desk hooks + crm_include.js): keep the first
  A.loaded_charts = 1;
  var state = A.state, t = A.t, el = A.el, textNode = A.textNode;

  var CHART_COLORS = [
    "#0f1b2e",
    "#2563eb",
    "#0d9488",
    "#ca8a04",
    "#dc2626",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
  ];

  function svgEl(name, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attrs || {}).forEach(function (k) {
      n.setAttribute(k, String(attrs[k]));
    });
    return n;
  }

  function normalizeChart(payload) {
    var labels = (payload && payload.labels) || [];
    var values = ((payload && payload.values) || []).map(function (v) {
      var n = Number(v);
      return isFinite(n) ? n : 0;
    });
    // Align lengths
    while (labels.length < values.length) labels.push("#" + (labels.length + 1));
    while (values.length < labels.length) values.push(0);
    return {
      type: ((payload && payload.type) || "bar").toLowerCase(),
      title: (payload && payload.title) || "",
      labels: labels,
      values: values,
      value: payload && payload.value,
    };
  }

  function truncateLabel(s, max) {
    s = String(s == null ? "" : s);
    if (s.length <= max) return s;
    return s.slice(0, Math.max(1, max - 1)) + "…";
  }

  function renderChart(payload) {
    var data = normalizeChart(payload);
    var box = el("div", "erp-ai-chart");
    var head = el("div", "erp-ai-chart-title");
    head.textContent = data.title || "";
    box.appendChild(head);

    if (data.type === "kpi") {
      var kpi = el("div", "erp-ai-chart-kpi");
      kpi.textContent = String(
        data.value != null ? data.value : data.values[0] != null ? data.values[0] : 0
      );
      box.appendChild(kpi);
      return box;
    }

    if (!data.values.length) {
      box.appendChild(el("div", "erp-ai-chart-empty", state.lang === "ar" ? "لا بيانات" : "No data"));
      return box;
    }

    if (data.type === "pie") {
      box.appendChild(renderPieSvg(data));
      box.appendChild(renderLegend(data));
      return box;
    }
    if (data.type === "line") {
      box.appendChild(renderLineSvg(data));
      box.appendChild(renderLegend(data));
      return box;
    }
    // default bar
    box.appendChild(renderBarSvg(data));
    box.appendChild(renderLegend(data));
    return box;
  }

  function renderLegend(data) {
    var ul = el("ul", "erp-ai-chart-legend");
    data.labels.forEach(function (lab, i) {
      var li = el("li");
      var sw = el("span", "erp-ai-chart-swatch");
      sw.style.background = CHART_COLORS[i % CHART_COLORS.length];
      li.appendChild(sw);
      li.appendChild(document.createTextNode(" " + lab + " · " + data.values[i]));
      ul.appendChild(li);
    });
    return ul;
  }

  function renderBarSvg(data) {
    var w = 420;
    var h = 220;
    var padL = 36;
    var padR = 12;
    var padT = 18;
    var padB = 48;
    var plotW = w - padL - padR;
    var plotH = h - padT - padB;
    var max = Math.max.apply(null, data.values.concat([1]));
    var n = data.values.length;
    var gap = 8;
    var bw = Math.max(10, (plotW - gap * (n + 1)) / n);
    var svg = svgEl("svg", {
      viewBox: "0 0 " + w + " " + h,
      width: "100%",
      height: "220",
      role: "img",
      "aria-label": data.title || "bar chart",
    });

    // grid + y ticks
    for (var t = 0; t <= 4; t++) {
      var yv = max * (t / 4);
      var y = padT + plotH - (yv / max) * plotH;
      svg.appendChild(
        svgEl("line", {
          x1: padL,
          y1: y,
          x2: w - padR,
          y2: y,
          stroke: "#e2e8f0",
          "stroke-width": 1,
        })
      );
      var yt = svgEl("text", {
        x: padL - 6,
        y: y + 3,
        "text-anchor": "end",
        "font-size": 10,
        fill: "#64748b",
        "font-family": "Cairo, system-ui, sans-serif",
      });
      yt.textContent = String(Math.round(yv * 10) / 10);
      svg.appendChild(yt);
    }

    // baseline
    svg.appendChild(
      svgEl("line", {
        x1: padL,
        y1: padT + plotH,
        x2: w - padR,
        y2: padT + plotH,
        stroke: "#94a3b8",
        "stroke-width": 1.5,
      })
    );

    data.values.forEach(function (v, i) {
      var num = Number(v) || 0;
      var bh = num <= 0 ? 0 : Math.max(4, (num / max) * plotH); // min visible height for non-zero
      var x = padL + gap + i * (bw + gap);
      var y = padT + plotH - bh;
      var color = CHART_COLORS[i % CHART_COLORS.length];
      var rect = svgEl("rect", {
        x: x,
        y: y,
        width: bw,
        height: bh,
        rx: 4,
        fill: color,
      });
      rect.appendChild(
        (function () {
          var tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
          tip.textContent = data.labels[i] + ": " + num;
          return tip;
        })()
      );
      svg.appendChild(rect);

      var val = svgEl("text", {
        x: x + bw / 2,
        y: y - 4,
        "text-anchor": "middle",
        "font-size": 11,
        "font-weight": 700,
        fill: "#0f172a",
        "font-family": "Cairo, system-ui, sans-serif",
      });
      val.textContent = String(num);
      svg.appendChild(val);

      var lab = svgEl("text", {
        x: x + bw / 2,
        y: padT + plotH + 14,
        "text-anchor": "middle",
        "font-size": 10,
        fill: "#475569",
        "font-family": "Cairo, system-ui, sans-serif",
      });
      // wrap long labels with slight rotation for many bars
      if (n > 4) {
        lab.setAttribute("transform", "rotate(-28 " + (x + bw / 2) + " " + (padT + plotH + 14) + ")");
        lab.setAttribute("text-anchor", "end");
      }
      lab.textContent = truncateLabel(data.labels[i], n > 5 ? 8 : 12);
      svg.appendChild(lab);
    });

    return svg;
  }

  function renderLineSvg(data) {
    var w = 420;
    var h = 200;
    var padL = 36;
    var padR = 12;
    var padT = 16;
    var padB = 40;
    var plotW = w - padL - padR;
    var plotH = h - padT - padB;
    var max = Math.max.apply(null, data.values.concat([1]));
    var n = data.values.length;
    var svg = svgEl("svg", {
      viewBox: "0 0 " + w + " " + h,
      width: "100%",
      height: "200",
      role: "img",
    });
    for (var t = 0; t <= 4; t++) {
      var y = padT + plotH * (1 - t / 4);
      svg.appendChild(
        svgEl("line", {
          x1: padL,
          y1: y,
          x2: w - padR,
          y2: y,
          stroke: "#e2e8f0",
          "stroke-width": 1,
        })
      );
    }
    var pts = data.values.map(function (v, i) {
      var x = padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
      var y = padT + plotH - ((Number(v) || 0) / max) * plotH;
      return { x: x, y: y, v: Number(v) || 0, lab: data.labels[i] };
    });
    var d = pts
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + p.x + " " + p.y;
      })
      .join(" ");
    svg.appendChild(
      svgEl("path", {
        d: d,
        fill: "none",
        stroke: "#2563eb",
        "stroke-width": 2.5,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      })
    );
    pts.forEach(function (p, i) {
      svg.appendChild(
        svgEl("circle", {
          cx: p.x,
          cy: p.y,
          r: 4,
          fill: CHART_COLORS[i % CHART_COLORS.length],
          stroke: "#fff",
          "stroke-width": 1.5,
        })
      );
      var lab = svgEl("text", {
        x: p.x,
        y: h - 12,
        "text-anchor": "middle",
        "font-size": 10,
        fill: "#475569",
        "font-family": "Cairo, system-ui, sans-serif",
      });
      lab.textContent = truncateLabel(p.lab, 10);
      svg.appendChild(lab);
    });
    return svg;
  }

  function renderPieSvg(data) {
    var size = 180;
    var cx = size / 2;
    var cy = size / 2;
    var r = 68;
    var total = data.values.reduce(function (a, b) {
      return a + (Number(b) || 0);
    }, 0) || 1;
    var svg = svgEl("svg", {
      viewBox: "0 0 " + size + " " + size,
      width: "100%",
      height: String(size),
      role: "img",
    });
    var angle = -Math.PI / 2;
    data.values.forEach(function (v, i) {
      var slice = ((Number(v) || 0) / total) * Math.PI * 2;
      var x1 = cx + r * Math.cos(angle);
      var y1 = cy + r * Math.sin(angle);
      angle += slice;
      var x2 = cx + r * Math.cos(angle);
      var y2 = cy + r * Math.sin(angle);
      var large = slice > Math.PI ? 1 : 0;
      var path =
        "M " +
        cx +
        " " +
        cy +
        " L " +
        x1 +
        " " +
        y1 +
        " A " +
        r +
        " " +
        r +
        " 0 " +
        large +
        " 1 " +
        x2 +
        " " +
        y2 +
        " Z";
      if (slice <= 0) return;
      // full circle edge case
      if (Math.abs(slice - Math.PI * 2) < 1e-6) {
        svg.appendChild(
          svgEl("circle", {
            cx: cx,
            cy: cy,
            r: r,
            fill: CHART_COLORS[i % CHART_COLORS.length],
          })
        );
      } else {
        svg.appendChild(
          svgEl("path", {
            d: path,
            fill: CHART_COLORS[i % CHART_COLORS.length],
            stroke: "#fff",
            "stroke-width": 1.5,
          })
        );
      }
    });
    return svg;
  }

  A.svgEl = svgEl;
  A.normalizeChart = normalizeChart;
  A.truncateLabel = truncateLabel;
  A.renderChart = renderChart;
  A.renderLegend = renderLegend;
  A.renderBarSvg = renderBarSvg;
  A.renderLineSvg = renderLineSvg;
  A.renderPieSvg = renderPieSvg;
  A.CHART_COLORS = CHART_COLORS;
})();
