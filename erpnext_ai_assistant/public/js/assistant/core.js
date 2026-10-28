/* The ERPNext-AI-Assistant panel: shared state, text, and server calls. Loaded first. */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_core) return; // loaded twice (Desk hooks + crm_include.js): keep the first
  A.loaded_core = 1;
  // One version for every asset: hooks.py puts it on each script URL; the stylesheet reuses it.
  var script = document.currentScript;
  var tagged = script && /[?&]v=([^&#]+)/.exec(script.src || "");
  A.version = tagged ? tagged[1] : A.version || "dev";

  var I18N = {
    ar: {
      brand: "ERP Assistant",
      subtitle: "مساعد أعمالك",
      chat: "محادثة",
      history: "السجل",
      newChat: "محادثة جديدة",
      close: "إغلاق",
      switchLang: "Switch to English",
      send: "إرسال",
      placeholder: "اسأل عن سجل أو نوع مستند أو خطوة عمل… (عمل فقط)",
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
      rejected: "تم الرفض. لم يُحفظ شيء.",
      approveFailed: "تعذّر التنفيذ: ",
      workOnly: "يجيب من بيانات العمل المتاحة لك. لا يُنفَّذ أي تعديل قبل موافقتك.",
      attach: "إرفاق ملف أو صورة",
      template: "تنزيل القالب",
      loading: "جارٍ المعالجة…",
      open: "فتح المساعد",
      expand: "توسيع",
      shrink: "الحجم الأصلي",
      noHistory: "لا توجد محادثات بعد.",
      error: "تعذّر إكمال الطلب. حاول مرة أخرى.",
      memory: "ذاكرة",
      memoryFact: "حقيقة للتذكر",
      memoryKey: "المفتاح",
      memoryConfirm: "أؤكد حفظ هذه الحقيقة",
      memorySave: "حفظ",
      memoryClear: "مسح ذاكرتي",
      memoryEmpty: "لا حقائق محفوظة.",
      memorySaved: "تم الحفظ.",
      memoryNeedConfirm: "فعّل التأكيد أولاً.",
    },
    en: {
      brand: "ERP Assistant",
      subtitle: "Your business assistant",
      chat: "Chat",
      history: "History",
      newChat: "New chat",
      close: "Close",
      switchLang: "التبديل إلى العربية",
      send: "Send",
      placeholder: "Ask about a record, a DocType, or a work step… (work only)",
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
      rejected: "Rejected. Nothing was saved.",
      approveFailed: "Could not save: ",
      workOnly: "Answers from the business data you can access. Nothing changes until you approve.",
      attach: "Attach a file or image",
      template: "Download template",
      loading: "Working…",
      open: "Open assistant",
      expand: "Expand",
      shrink: "Original size",
      noHistory: "No chats yet.",
      error: "Could not finish. Please try again.",
      memory: "Memory",
      memoryFact: "Fact to remember",
      memoryKey: "Key",
      memoryConfirm: "I confirm saving this fact",
      memorySave: "Save",
      memoryClear: "Clear my memory",
      memoryEmpty: "No saved facts.",
      memorySaved: "Saved.",
      memoryNeedConfirm: "Confirm first.",
    },
  };

  // The panel speaks the logged-in user's ERPNext language. A manual switch is kept for this browser session.
  function detectLang() {
    try {
      var chosen = sessionStorage.getItem("erp-ai-lang");
      if (chosen === "ar" || chosen === "en") return chosen;
    } catch (e) {}
    var boot = String((window.frappe && frappe.boot && frappe.boot.lang) || "").toLowerCase();
    if (boot) return boot.indexOf("ar") === 0 ? "ar" : "en";
    var htmlLang = (document.documentElement.lang || "").toLowerCase();
    if (htmlLang) return htmlLang.indexOf("ar") === 0 ? "ar" : "en";
    return "ar"; // no user language known: Arabic-first product default
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
          var detail = "";
          try {
            var server = JSON.parse(j._server_messages || "[]");
            if (server && server.length) {
              var first = typeof server[0] === "string" ? JSON.parse(server[0]) : server[0];
              detail = (first && (first.message || first.title)) || "";
            }
          } catch (e) {}
          detail = String(detail).replace(/<[^>]+>/g, "");
          throw new Error(detail || j.exc_type || j.exception || t("error"));
        }
        return j.message != null ? j.message : j;
      });
    });
  }
  var state = {
    lang: detectLang(),
    open: false,
    files: [],
    tab: "chat",
    chatId: null,
    boot: null,
    pending: null,
    steps: [],
    thinkingMs: 0,
    expanded: false,
  };
  try {
    state.expanded = sessionStorage.getItem("erp-ai-expanded") === "1";
  } catch (e) {}
  function textNode(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    n.textContent = text == null ? "" : String(text);
    return n;
  }

  // Header icons: 24×24 outline strokes, drawn as SVG elements so no markup string is ever parsed.
  var ICONS = {
    close: ["M6 6l12 12", "M18 6L6 18"],
    newChat: ["M4 20h4L18.5 9.5l-4-4L4 16v4z", "M13 7l4 4", "M14 20h6"],
    expand: ["M4 9V4h5", "M15 4h5v5", "M20 15v5h-5", "M9 20H4v-5"],
    shrink: ["M9 4v5H4", "M20 9h-5V4", "M15 20v-5h5", "M4 15h5v5"],
  };

  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    (ICONS[name] || []).forEach(function (d) {
      var path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.8");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.appendChild(path);
    });
    return svg;
  }

  // An icon-only button still has a name: the tooltip and the screen-reader label, in the panel's language.
  function iconButton(name, label) {
    var b = el("button", "erp-ai-icon-btn");
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.appendChild(icon(name));
    return b;
  }

  // Text only. The launcher icon sets innerHTML explicitly where it is built.
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  A.detectLang = detectLang;
  A.t = t;
  A.hasArabic = hasArabic;
  A.csrf = csrf;
  A.call = call;
  A.textNode = textNode;
  A.el = el;
  A.icon = icon;
  A.iconButton = iconButton;
  A.I18N = I18N;
  A.state = state;
})();
