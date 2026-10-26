/* The ERPNext-AI-Assistant — app-owned panel (448×684 RTL, Arabic-first). */
(function () {
  if (window.__erpAiAssistantBooted) return;
  window.__erpAiAssistantBooted = 1;

  var I18N = {
    ar: {
      brand: "The ERPNext-AI-Assistant",
      subtitle: "مساعد ERPNext",
      chat: "محادثة",
      history: "السجل",
      newChat: "جديد",
      close: "إغلاق",
      send: "إرسال",
      placeholder: "اسأل عن العملاء أو الفواتير أو المخزون… (عمل فقط)",
      thinking: "التفكير",
      thoughtFor: "فكّر لـ {0} ث",
      empty: "ابدأ بسؤال متعلق بالعمل على هذا الموقع.",
      blocked: "تم حظر المساعد. تواصل مع مديرك.",
      ackTitle: "تأكيد الكتابة",
      openRecord: "فتح السجل",
      created: "تم الحفظ.",
      ackCheck: "راجعت التغيير وأوافق على تنفيذه",
      approve: "موافقة",
      reject: "رفض",
      workOnly: "مساعد عمل لنظام ERP — ليس ChatGPT عام.",
      loading: "جارٍ المعالجة…",
      open: "فتح المساعد",
      noHistory: "لا توجد محادثات بعد.",
      error: "تعذّر إكمال الطلب. حاول مرة أخرى.",
    },
    en: {
      brand: "The ERPNext-AI-Assistant",
      subtitle: "ERP workplace assistant",
      chat: "Chat",
      history: "History",
      newChat: "New",
      close: "Close",
      send: "Send",
      placeholder: "Ask about leads, invoices, stock… (work only)",
      thinking: "Thinking",
      thoughtFor: "Thought for {0}s",
      empty: "Ask a work-related question about this site.",
      blocked: "Assistant blocked. Contact your manager.",
      ackTitle: "Confirm write",
      openRecord: "Open record",
      created: "Saved.",
      ackCheck: "I reviewed and authorize this change",
      approve: "Approve",
      reject: "Reject",
      workOnly: "Workplace ERP assistant — not a general ChatGPT.",
      loading: "Working…",
      open: "Open assistant",
      noHistory: "No chats yet.",
      error: "Could not finish. Please try again.",
    },
  };

  function detectLang() {
    var htmlLang = (document.documentElement.lang || "").toLowerCase();
    if (htmlLang.indexOf("ar") === 0) return "ar";
    var boot = (window.frappe && frappe.boot && frappe.boot.lang) || "";
    if (String(boot).indexOf("ar") === 0) return "ar";
    return "ar"; // Arabic-first default for this product
  }

  function t(key, lang) {
    lang = lang || state.lang;
    var pack = I18N[lang] || I18N.ar;
    return pack[key] || I18N.en[key] || key;
  }

  function hasArabic(s) {
    return /[\u0600-\u06FF]/.test(s || "");
  }

  function csrf() {
    // CRM SPA sets window.csrf_token; Desk uses frappe.csrf_token / cookie.
    if (window.csrf_token) return window.csrf_token;
    if (window.frappe && frappe.csrf_token) return frappe.csrf_token;
    var m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function call(method, args) {
    var token = csrf();
    var body = new URLSearchParams();
    body.set("cmd", method);
    if (token) body.set("csrf_token", token);
    Object.keys(args || {}).forEach(function (k) {
      if (args[k] == null) return;
      body.set(k, typeof args[k] === "object" ? JSON.stringify(args[k]) : String(args[k]));
    });
    return fetch("/api/method/" + method, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Frappe-CSRF-Token": token,
        Accept: "application/json",
      },
      body: body.toString(),
    }).then(function (r) {
      return r.json().then(function (j) {
        if (j.exc_type === "CSRFTokenError" || j.exc || (r.status >= 400 && j.message == null)) {
          throw new Error(j.exc_type || j.exc || t("error"));
        }
        return j.message != null ? j.message : j;
      });
    });
  }

  function normalizeDeskPath(path) {
    // Frappe v16 serves Desk at /desk; /app redirects there.
    if (path === "/app" || path.indexOf("/app/") === 0) {
      return "/desk" + path.slice(4);
    }
    return path;
  }

  function pathMatches(pages) {
    var path = normalizeDeskPath(location.pathname || "");
    var raw = location.pathname || "";
    function hit(pat) {
      if (!pat) return false;
      if (raw === pat || raw.indexOf(pat) === 0) return true;
      if (path === pat || path.indexOf(pat) === 0) return true;
      // Settings may still list /app while browser is on /desk
      if (pat === "/app" || pat.indexOf("/app/") === 0) {
        var deskPat = "/desk" + pat.slice(4);
        if (raw === deskPat || raw.indexOf(deskPat) === 0) return true;
        if (path === deskPat || path.indexOf(deskPat) === 0) return true;
      }
      if (pat === "/desk" || pat.indexOf("/desk/") === 0) {
        if (raw.indexOf("/app") === 0 || path.indexOf("/desk") === 0) return true;
      }
      return false;
    }
    if (!pages || !pages.length) {
      return hit("/crm") || hit("/desk") || hit("/app");
    }
    return pages.some(function (p) {
      return p && p.enabled && hit(p.path_pattern || "");
    });
  }

  var state = {
    lang: detectLang(),
    open: false,
    tab: "chat",
    chatId: null,
    boot: null,
    pending: null,
    steps: [],
    thinkingMs: 0,
  };

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function ensureAssets() {
    if (!document.querySelector('link[data-erp-ai-css]')) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=ai10";
      link.setAttribute("data-erp-ai-css", "1");
      document.head.appendChild(link);
    }
  }

  function mount() {
    ensureAssets();
    if (document.getElementById("erp-ai-root")) return;
    var fab = el("button", "erp-ai-fab");
    fab.id = "erp-ai-fab";
    fab.type = "button";
    fab.title = t("open");
    fab.setAttribute("aria-label", t("open"));
    // Chat bubble icon (Desk + CRM)
    fab.innerHTML =
      '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false">' +
      '<path fill="currentColor" d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/>' +
      '<circle cx="8" cy="10" r="1.2" fill="currentColor"/>' +
      '<circle cx="12" cy="10" r="1.2" fill="currentColor"/>' +
      '<circle cx="16" cy="10" r="1.2" fill="currentColor"/>' +
      "</svg>";
    fab.addEventListener("click", function () {
      state.open = true;
      render();
    });
    document.body.appendChild(fab);

    var root = el("div", "erp-ai-root erp-ai-closed");
    root.id = "erp-ai-root";
    root.setAttribute("dir", "rtl");
    root.setAttribute("lang", state.lang);
    document.body.appendChild(root);
    render();
    watchDom();
    subscribeRealtime();
  }

  function watchDom() {
    var obs = new MutationObserver(function () {
      if (!document.getElementById("erp-ai-root") || !document.getElementById("erp-ai-fab")) {
        window.__erpAiAssistantBooted = 0;
        setTimeout(function () {
          if (!window.__erpAiAssistantBooted) {
            window.__erpAiAssistantBooted = 1;
            mount();
          }
        }, 50);
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }

  function subscribeRealtime() {
    try {
      if (!(window.frappe && frappe.realtime && frappe.realtime.on)) return;
      frappe.realtime.on("erp_ai_thinking", function (data) {
        if (!data) return;
        state.steps = state.steps.filter(function (s) {
          return s.id !== data.id;
        });
        state.steps.push(data);
        updateThinkingLive();
      });
    } catch (e) {}
  }

  function render() {
    var root = document.getElementById("erp-ai-root");
    var fab = document.getElementById("erp-ai-fab");
    if (!root || !fab) return;
    if (!state.open) {
      root.classList.add("erp-ai-closed");
      fab.hidden = false;
      return;
    }
    root.classList.remove("erp-ai-closed");
    fab.hidden = true;

    var persona =
      (state.boot && state.boot.persona) || {
        panel_label: t("brand"),
        panel_label_ar: t("subtitle"),
      };
    var title = state.lang === "ar" ? persona.panel_label_ar || t("subtitle") : persona.panel_label || t("brand");
    var brandMain = t("brand");

    root.innerHTML = "";
    root.setAttribute("dir", "rtl");
    root.setAttribute("lang", state.lang);

    var header = el("div", "erp-ai-header");
    var brand = el("div", "erp-ai-brand");
    brand.appendChild(el("strong", "", brandMain));
    brand.appendChild(el("span", "", title));
    header.appendChild(brand);
    var actions = el("div", "erp-ai-header-actions");
    var langBtn = el("button", "", state.lang === "ar" ? "EN" : "ع");
    langBtn.title = "Language / اللغة";
    langBtn.addEventListener("click", function () {
      state.lang = state.lang === "ar" ? "en" : "ar";
      render();
    });
    var neu = el("button", "", t("newChat"));
    neu.addEventListener("click", function () {
      state.chatId = null;
      state.tab = "chat";
      state.steps = [];
      render();
      bodyChat();
    });
    var close = el("button", "", t("close"));
    close.addEventListener("click", function () {
      state.open = false;
      render();
    });
    actions.appendChild(langBtn);
    actions.appendChild(neu);
    actions.appendChild(close);
    header.appendChild(actions);
    root.appendChild(header);

    var tabs = el("div", "erp-ai-tabs");
    var bChat = el("button", state.tab === "chat" ? "active" : "", t("chat"));
    var bHist = el("button", state.tab === "history" ? "active" : "", t("history"));
    bChat.addEventListener("click", function () {
      state.tab = "chat";
      render();
    });
    bHist.addEventListener("click", function () {
      state.tab = "history";
      render();
      loadHistory();
    });
    tabs.appendChild(bChat);
    tabs.appendChild(bHist);
    root.appendChild(tabs);

    var body = el("div", "erp-ai-body");
    body.id = "erp-ai-body";
    root.appendChild(body);

    if (state.boot && state.boot.blocked) {
      body.appendChild(el("div", "erp-ai-empty", t("blocked")));
      return;
    }

    if (state.tab === "history") {
      body.appendChild(el("div", "erp-ai-empty", t("loading")));
      return;
    }

    body.appendChild(el("div", "erp-ai-empty", t("empty")));

    var composer = el("div", "erp-ai-composer");
    var ta = el("textarea");
    ta.id = "erp-ai-input";
    ta.placeholder = t("placeholder");
    ta.setAttribute("dir", "auto");
    var row = el("div", "erp-ai-composer-row");
    row.appendChild(el("div", "erp-ai-hint", t("workOnly")));
    var send = el("button", "primary", t("send"));
    send.addEventListener("click", onSend);
    row.appendChild(send);
    composer.appendChild(ta);
    composer.appendChild(row);
    root.appendChild(composer);
  }

  function bodyChat() {
    var body = document.getElementById("erp-ai-body");
    if (!body) return;
    body.innerHTML = "";
    body.appendChild(el("div", "erp-ai-empty", t("empty")));
  }

  function parseOpenLinks(content) {
    var links = [];
    var text = String(content || "").replace(
      /\[\[open:([^\]|]+)\|([^\]|]+)(?:\|([^\]]*))?\]\]/g,
      function (_m, path, label, crm) {
        links.push({ desk_route: path, label: label, crm_route: crm || null });
        return "";
      }
    );
    return { text: text.replace(/\n+$/, "").trim(), links: links };
  }

  function openRecordButton(link) {
    var a = el("a", "erp-ai-open-link");
    a.href = (location.pathname.indexOf("/crm") === 0 && link.crm_route) || link.desk_route || "#";
    a.textContent = link.label || t("openRecord");
    a.addEventListener("click", function (ev) {
      var onCrm = (location.pathname || "").indexOf("/crm") === 0;
      var path = (onCrm && link.crm_route) || link.desk_route;
      if (!path) return;
      if (onCrm && link.crm_route) {
        window.location.assign(link.crm_route);
        ev.preventDefault();
        return;
      }
      if (window.frappe && frappe.set_route && link.route && link.route.length) {
        ev.preventDefault();
        frappe.set_route.apply(frappe, link.route);
        return;
      }
      if (window.frappe && frappe.set_route && path.indexOf("/desk/") === 0) {
        ev.preventDefault();
        var bits = path.split("/").filter(Boolean);
        frappe.set_route.apply(frappe, bits);
      }
    });
    return a;
  }

  function appendMsg(role, content, extra) {
    var body = document.getElementById("erp-ai-body");
    if (!body) return;
    var empty = body.querySelector(".erp-ai-empty");
    if (empty) empty.remove();
    var wrap = el("div", "erp-ai-msg " + role);
    if (extra && extra.thinking) wrap.appendChild(extra.thinking);
    var parsed = parseOpenLinks(content || "");
    var bubble = el("div", "bubble");
    bubble.textContent = parsed.text;
    bubble.setAttribute("dir", hasArabic(parsed.text) ? "rtl" : "auto");
    wrap.appendChild(bubble);
    (parsed.links || []).forEach(function (link) {
      wrap.appendChild(openRecordButton(link));
    });
    if (extra && extra.link && (content || "").indexOf("[[open:") === -1) {
      wrap.appendChild(openRecordButton(extra.link));
    }
    if (extra && extra.charts) {
      extra.charts.forEach(function (c) {
        wrap.appendChild(renderChart(c));
      });
    }
    if (extra && extra.ack) wrap.appendChild(renderAck(extra.ack));
    body.appendChild(wrap);
    body.scrollTop = body.scrollHeight;
    return wrap;
  }

  function thinkingBlock(steps, ms) {
    var det = el("details", "erp-ai-thinking");
    det.id = "erp-ai-thinking-live";
    if (steps && steps.some(function (s) {
      return s.status === "running";
    })) {
      det.open = true;
    }
    var sum = el("summary");
    sum.textContent = ms
      ? t("thoughtFor").replace("{0}", String(Math.max(1, Math.round(ms / 1000))))
      : t("thinking");
    det.appendChild(sum);
    var ol = el("ol");
    (steps || []).forEach(function (s) {
      var li = el("li");
      li.dataset.status = s.status || "";
      li.textContent = (state.lang === "ar" ? s.label_ar : s.label_en) || s.tool || "";
      ol.appendChild(li);
    });
    det.appendChild(ol);
    return det;
  }

  function updateThinkingLive() {
    var live = document.getElementById("erp-ai-thinking-live");
    if (!live) return;
    var parent = live.parentNode;
    var next = thinkingBlock(state.steps, state.thinkingMs);
    parent.replaceChild(next, live);
  }

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

  function renderAck(pending) {
    var box = el("div", "erp-ai-ack");
    box.appendChild(el("strong", "", t("ackTitle")));
    box.appendChild(el("div", "", (pending && pending.summary) || ""));
    var lab = el("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(" " + t("ackCheck")));
    box.appendChild(lab);
    var row = el("div", "erp-ai-composer-row");
    var ok = el("button", "primary", t("approve"));
    var no = el("button", "", t("reject"));
    ok.addEventListener("click", function () {
      if (!cb.checked) return;
      call("erpnext_ai_assistant.api.chat.approve_action", {
        pending_action: pending.pending_action,
        acknowledgment_text: t("ackCheck"),
        acknowledged: 1,
      }).then(function (res) {
        appendMsg("assistant", (res && res.message) || t("created"), {
          link: res && res.link,
        });
      });
    });
    no.addEventListener("click", function () {
      call("erpnext_ai_assistant.api.chat.reject_action", {
        pending_action: pending.pending_action,
      });
    });
    row.appendChild(no);
    row.appendChild(ok);
    box.appendChild(row);
    return box;
  }

  function onSend() {
    var ta = document.getElementById("erp-ai-input");
    if (!ta) return;
    var msg = (ta.value || "").trim();
    if (!msg) return;
    if (hasArabic(msg)) state.lang = "ar";
    ta.value = "";
    appendMsg("user", msg);
    state.steps = [];
    state.thinkingMs = 0;
    var started = Date.now();
    var think = thinkingBlock(state.steps, 0);
    var asstWrap = appendMsg("assistant", t("loading"), { thinking: think });
    call("erpnext_ai_assistant.api.chat.run", {
      message: msg,
      route: location.pathname,
      chat_id: state.chatId || "",
    })
      .then(function (res) {
        state.chatId = res.chat_id || state.chatId;
        state.steps = res.steps || state.steps;
        state.thinkingMs = Date.now() - started;
        if (asstWrap && asstWrap.parentNode) asstWrap.parentNode.removeChild(asstWrap);
        appendMsg("assistant", res.message || "", {
          thinking: thinkingBlock(state.steps, state.thinkingMs),
          charts: res.charts || [],
          ack: res.pending_action
            ? {
                pending_action: res.pending_action,
                summary: res.pending_summary || res.message || "",
              }
            : null,
        });
      })
      .catch(function (err) {
        if (asstWrap && asstWrap.parentNode) asstWrap.parentNode.removeChild(asstWrap);
        appendMsg("assistant", t("error") + (err && err.message ? " (" + err.message + ")" : ""));
      });
  }

  function loadHistory() {
    call("erpnext_ai_assistant.api.chat.list_chats", { limit: 30 }).then(function (rows) {
      var body = document.getElementById("erp-ai-body");
      if (!body) return;
      body.innerHTML = "";
      if (!rows || !rows.length) {
        body.appendChild(el("div", "erp-ai-empty", t("noHistory")));
        return;
      }
      rows.forEach(function (r) {
        var b = el("button", "erp-ai-history-item");
        b.type = "button";
        b.textContent = (r.title || r.name) + " · " + (r.modified || "");
        b.addEventListener("click", function () {
          state.chatId = r.name;
          state.tab = "chat";
          render();
          call("erpnext_ai_assistant.api.chat.get_chat_messages", { chat_id: r.name }).then(function (msgs) {
            var body2 = document.getElementById("erp-ai-body");
            if (!body2) return;
            body2.innerHTML = "";
            (msgs || []).forEach(function (m) {
              appendMsg(m.role === "user" ? "user" : "assistant", m.content || "");
            });
          });
        });
        body.appendChild(b);
      });
    });
  }

  function bootAndMaybeMount() {
    call("erpnext_ai_assistant.api.chat.bootstrap", {})
      .then(function (boot) {
        state.boot = boot || {};
        if (!boot || boot.allowed === false) {
          if (boot && boot.blocked) {
            mount();
            state.open = false;
            return;
          }
          if (!pathMatches(boot && boot.overlay_pages)) return;
          return;
        }
        if (!pathMatches(boot.overlay_pages)) return;
        mount();
      })
      .catch(function () {
        if (pathMatches([])) mount();
      });
  }

  function whenCsrfReady(fn, tries) {
    tries = tries == null ? 40 : tries;
    if (csrf() || tries <= 0) {
      fn();
      return;
    }
    setTimeout(function () {
      whenCsrfReady(fn, tries - 1);
    }, 250);
  }

  function start() {
    var run = function () {
      whenCsrfReady(bootAndMaybeMount);
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", run);
    } else {
      run();
    }
  }

  start();
})();
