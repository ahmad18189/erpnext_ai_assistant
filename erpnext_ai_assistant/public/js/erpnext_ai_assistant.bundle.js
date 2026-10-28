/* The ERPNext-AI-Assistant — app-owned panel (448×684 RTL, Arabic-first). */
(function () {
  if (window.__erpAiAssistantBooted) return;
  window.__erpAiAssistantBooted = 1;

  var I18N = {
    ar: {
      brand: "ERP Assistant",
      subtitle: "مساعد أعمالك",
      chat: "محادثة",
      history: "السجل",
      newChat: "جديد",
      close: "إغلاق",
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
      newChat: "New",
      close: "Close",
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

  function normalizeDeskPath(path) {
    // Frappe v15 serves Desk at /app. Accept a /desk pattern from older settings.
    if (path === "/desk" || path.indexOf("/desk/") === 0) {
      return "/app" + path.slice(5);
    }
    return path;
  }

  function pathMatches(pages) {
    var path = normalizeDeskPath(location.pathname || "");
    var raw = location.pathname || "";
    function hit(pat) {
      if (!pat) return false;
      var normalized = normalizeDeskPath(pat);
      if (raw === pat || (pat !== "/" && raw.indexOf(pat) === 0)) return true;
      if (path === normalized || (normalized !== "/" && path.indexOf(normalized) === 0)) return true;
      return false;
    }
    var appRoutes = (state.boot && state.boot.app_routes) || [];
    if (appRoutes.some(function (row) { return hit(row && row.route); })) return true;
    if (!pages || !pages.length) {
      return hit("/app") || hit("/desk");
    }
    return pages.some(function (p) {
      return p && p.enabled && hit(p.path_pattern || "");
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

  var EXPAND_ICON =
    '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M4 9V4h5v2H6v3H4zm10-5h5v5h-2V6h-3V4zM4 15h2v3h3v2H4v-5zm13 3v-3h2v5h-5v-2h3z"/></svg>';
  var SHRINK_ICON =
    '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M9 4v3H6v2h5V4H9zm4 0v5h5V7h-3V4h-2zM4 13v2h3v3h2v-5H4zm9 0v5h2v-3h3v-2h-5z"/></svg>';

  function textNode(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    n.textContent = text == null ? "" : String(text);
    return n;
  }

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
      link.href = "/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=ai22";
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
    root.classList.toggle("erp-ai-expanded", !!state.expanded);
    fab.hidden = true;

    var branding = (state.boot && state.boot.branding) || {};
    var brandMain = branding.title || t("brand");
    var brandSub = personaLine();
    var hint =
      state.lang === "ar"
        ? branding.hint || t("workOnly")
        : branding.hint_en || t("workOnly");

    root.innerHTML = "";
    root.setAttribute("dir", state.lang === "ar" ? "rtl" : "ltr");
    root.setAttribute("lang", state.lang);

    var header = el("div", "erp-ai-header");
    var brand = el("div", "erp-ai-brand");
    brand.appendChild(textNode("strong", "", brandMain));
    brand.appendChild(textNode("span", "erp-ai-persona", brandSub));
    header.appendChild(brand);
    var actions = el("div", "erp-ai-header-actions");
    var langBtn = el("button", "", state.lang === "ar" ? "EN" : "ع");
    langBtn.title = "Language / اللغة";
    langBtn.addEventListener("click", function () {
      state.lang = state.lang === "ar" ? "en" : "ar";
      render();
    });
    var sizeBtn = el("button", "erp-ai-size", state.expanded ? SHRINK_ICON : EXPAND_ICON);
    sizeBtn.type = "button";
    sizeBtn.title = state.expanded ? t("shrink") : t("expand");
    sizeBtn.setAttribute("aria-label", sizeBtn.title);
    sizeBtn.setAttribute("aria-pressed", state.expanded ? "true" : "false");
    sizeBtn.addEventListener("click", function () {
      state.expanded = !state.expanded;
      try {
        sessionStorage.setItem("erp-ai-expanded", state.expanded ? "1" : "0");
      } catch (e) {}
      root.classList.toggle("erp-ai-expanded", state.expanded);
      sizeBtn.title = state.expanded ? t("shrink") : t("expand");
      sizeBtn.setAttribute("aria-label", sizeBtn.title);
      sizeBtn.setAttribute("aria-pressed", state.expanded ? "true" : "false");
      sizeBtn.innerHTML = state.expanded ? SHRINK_ICON : EXPAND_ICON;
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
    actions.appendChild(sizeBtn);
    actions.appendChild(close);
    header.appendChild(actions);
    root.appendChild(header);

    var tabs = el("div", "erp-ai-tabs");
    var bChat = el("button", state.tab === "chat" ? "active" : "", t("chat"));
    var bHist = el("button", state.tab === "history" ? "active" : "", t("history"));
    var bMem = el("button", state.tab === "memory" ? "active" : "", t("memory"));
    bChat.addEventListener("click", function () {
      state.tab = "chat";
      render();
    });
    bHist.addEventListener("click", function () {
      state.tab = "history";
      render();
      loadHistory();
    });
    bMem.addEventListener("click", function () {
      state.tab = "memory";
      render();
      loadMemoryPanel();
    });
    tabs.appendChild(bChat);
    tabs.appendChild(bHist);
    tabs.appendChild(bMem);
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

    if (state.tab === "memory") {
      renderMemoryForm(body);
      return;
    }

    renderCheatSheet(body);

    var composer = el("div", "erp-ai-composer");
    if (state.files.length) {
      var chips = el("div", "erp-ai-files");
      state.files.forEach(function (file, index) {
        var chip = el("button", "erp-ai-file-chip", "");
        chip.type = "button";
        chip.appendChild(textNode("span", "", file.name));
        chip.addEventListener("click", function () {
          state.files.splice(index, 1);
          render();
        });
        chips.appendChild(chip);
      });
      composer.appendChild(chips);
    }
    var ta = el("textarea");
    ta.id = "erp-ai-input";
    ta.placeholder = t("placeholder");
    ta.setAttribute("dir", "auto");
    var row = el("div", "erp-ai-composer-row");
    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = "image/*,.csv,.xlsx,.txt,.pdf";
    fileInput.hidden = true;
    fileInput.addEventListener("change", function () {
      Array.prototype.forEach.call(fileInput.files || [], function (file) {
        state.files.push(file);
      });
      render();
    });
    var attach = el("button", "erp-ai-attach", "+");
    attach.type = "button";
    attach.title = t("attach");
    attach.addEventListener("click", function () {
      fileInput.click();
    });
    row.appendChild(attach);
    row.appendChild(fileInput);
    row.appendChild(textNode("div", "erp-ai-hint", hint));
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
    renderCheatSheet(body);
  }

  function cheatLines() {
    var erp = state.boot && state.boot.has_erpnext;
    if (state.lang === "ar") {
      var ar = [
        { text: "عدّ أو اعرض السجلات التي تستطيع قراءتها.", example: "كم عدد المهام" },
        { text: "افتح شاشة في هذا المكتب.", example: "افتح أداة الاستيراد" },
        { text: "أنشئ أو عدّل سجلًا حقلًا واحدًا. لا يُحفظ شيء قبل موافقتك.", example: "اعمل مهمة اجتماع غدا" },
        { text: "راجع جدولًا ثم استورده فقط بعد موافقتك.", example: "راجع ملف الاستيراد" },
      ];
      if (erp) ar.push({ text: "اسأل عن خطوات العمل في دليل ERPNext.", example: "كيف أنشئ مهمة" });
      ar.push({ text: "احفظ حقيقة عنك فقط بعد تفعيل التأكيد.", example: "" });
      return ar;
    }
    var en = [
      { text: "Count or list records you can read.", example: "how many todos" },
      { text: "Open a screen on this Desk.", example: "open the import tool" },
      { text: "Create or update one field at a time. Nothing is saved until you approve.", example: "create a todo" },
      { text: "Review a spreadsheet, then import it only after you approve.", example: "review the import file" },
    ];
    if (erp) en.push({ text: "Ask how to do something in the ERPNext manual.", example: "how do I create a todo" });
    en.push({ text: "Save a fact about you only after you check the confirm box.", example: "" });
    return en;
  }

  function renderCheatSheet(body) {
    var box = el("div", "erp-ai-cheat");
    cheatLines().forEach(function (line) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "erp-ai-cheat-line";
      button.textContent = line.text;
      button.addEventListener("click", function () {
        var input = document.getElementById("erp-ai-input");
        if (input && line.example) input.value = line.example;
      });
      box.appendChild(button);
    });
    body.appendChild(box);
  }

  function renderMemoryForm(body) {
    body.innerHTML = "";
    var wrap = el("div", "erp-ai-memory");
    var keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.id = "erp-ai-mem-key";
    keyInput.placeholder = t("memoryKey");
    keyInput.setAttribute("dir", "auto");
    keyInput.maxLength = 80;
    var factInput = document.createElement("textarea");
    factInput.id = "erp-ai-mem-fact";
    factInput.placeholder = t("memoryFact");
    factInput.setAttribute("dir", "auto");
    factInput.rows = 3;
    var confirmRow = el("label", "erp-ai-memory-confirm");
    var confirmBox = document.createElement("input");
    confirmBox.type = "checkbox";
    confirmBox.id = "erp-ai-mem-confirm";
    confirmRow.appendChild(confirmBox);
    confirmRow.appendChild(document.createTextNode(" " + t("memoryConfirm")));
    var actions = el("div", "erp-ai-memory-actions");
    var saveBtn = el("button", "primary", t("memorySave"));
    saveBtn.type = "button";
    saveBtn.addEventListener("click", function () {
      if (!confirmBox.checked) {
        status.textContent = t("memoryNeedConfirm");
        return;
      }
      call("erpnext_ai_assistant.api.chat.save_my_memory", {
        key: (keyInput.value || "").trim(),
        value: (factInput.value || "").trim(),
        confirmed: 1,
      })
        .then(function () {
          status.textContent = t("memorySaved");
          keyInput.value = "";
          factInput.value = "";
          confirmBox.checked = false;
          loadMemoryPanel();
        })
        .catch(function () {
          status.textContent = t("error");
        });
    });
    var clearBtn = el("button", "", t("memoryClear"));
    clearBtn.type = "button";
    clearBtn.addEventListener("click", function () {
      call("erpnext_ai_assistant.api.chat.clear_my_memory", {})
        .then(function () {
          loadMemoryPanel();
        })
        .catch(function () {
          status.textContent = t("error");
        });
    });
    actions.appendChild(saveBtn);
    actions.appendChild(clearBtn);
    var status = textNode("div", "erp-ai-memory-status", "");
    var list = el("div", "erp-ai-memory-list");
    list.id = "erp-ai-mem-list";
    list.appendChild(textNode("div", "erp-ai-empty", t("loading")));
    wrap.appendChild(keyInput);
    wrap.appendChild(factInput);
    wrap.appendChild(confirmRow);
    wrap.appendChild(actions);
    wrap.appendChild(status);
    wrap.appendChild(list);
    body.appendChild(wrap);
  }

  function loadMemoryPanel() {
    var list = document.getElementById("erp-ai-mem-list");
    if (!list) return;
    call("erpnext_ai_assistant.api.chat.list_my_memory", {})
      .then(function (res) {
        list.innerHTML = "";
        var items = (res && res.items) || [];
        if (!items.length) {
          list.appendChild(textNode("div", "erp-ai-empty", t("memoryEmpty")));
          return;
        }
        items.forEach(function (row) {
          var item = el("div", "erp-ai-memory-item");
          item.appendChild(textNode("strong", "", row.key || ""));
          var val = textNode("div", "", "");
          val.textContent = row.value || "";
          item.appendChild(val);
          list.appendChild(item);
        });
      })
      .catch(function () {
        list.innerHTML = "";
        list.appendChild(textNode("div", "erp-ai-empty", t("error")));
      });
  }

  function parseOpenLinks(content) {
    var links = [];
    var text = String(content || "").replace(
      /\[\[open:([^\]|]+)\|([^\]|]+)(?:\|([^\]]*))?\]\]/g,
      function (_m, path, label, crm) {
        links.push({
          desk_route: safeLocalPath(path),
          label: label,
          crm_route: safeLocalPath(crm || ""),
        });
        return "";
      }
    );
    return { text: text.replace(/\n+$/, "").trim(), links: links };
  }

  function safeLocalPath(path) {
    if (!path || typeof path !== "string") return "";
    if (path.indexOf("://") !== -1 || path.indexOf("//") === 0 || path.indexOf("\\") !== -1) return "";
    if (path.charAt(0) !== "/") return "";
    if (path.indexOf("/app/") === 0 || path.indexOf("/desk/") === 0) return path;
    var routes = (state.boot && state.boot.app_routes) || [];
    for (var i = 0; i < routes.length; i++) {
      var route = (routes[i] && routes[i].route) || "";
      if (route && (path === route || path.indexOf(route.replace(/\/$/, "") + "/") === 0)) return path;
    }
    return "";
  }

  function openRecordButton(link) {
    var onCrm = (location.pathname || "").indexOf("/crm") === 0;
    var path = safeLocalPath((onCrm && link.crm_route) || link.desk_route || "");
    var a = el("a", "erp-ai-open-link");
    a.href = path || "#";
    a.textContent = link.label || t("openRecord");
    a.addEventListener("click", function (ev) {
      var path = safeLocalPath((onCrm && link.crm_route) || link.desk_route || "");
      if (!path) {
        ev.preventDefault();
        return;
      }
      if (onCrm && path.indexOf("/crm/") === 0) {
        window.location.assign(path);
        ev.preventDefault();
        return;
      }
      if (window.frappe && frappe.set_route && link.route && link.route.length) {
        ev.preventDefault();
        frappe.set_route.apply(frappe, link.route);
        return;
      }
      if (window.frappe && frappe.set_route && (path.indexOf("/app/") === 0 || path.indexOf("/desk/") === 0)) {
        ev.preventDefault();
        var bits = path.split("/").filter(Boolean);
        if (bits[0] === "app" || bits[0] === "desk") bits.shift();
        if (bits.length) frappe.set_route.apply(frappe, bits);
      }
    });
    return a;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inlineMd(value) {
    var codes = [];
    var s = String(value || "").replace(/`([^`]+)`/g, function (_m, code) {
      codes.push(code);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    s = s.replace(/\[([^\]<]+)\]\((https?:\/\/[^)\s]+)\)/g, function (_m, label, url) {
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, function (_m, index) {
      return "<code>" + codes[Number(index)] + "</code>";
    });
  }

  function listKind(line) {
    if (/^\s*\d+[.)]\s+/.test(line || "")) return "ol";
    if (/^\s*[-*]\s+/.test(line || "")) return "ul";
    return "";
  }

  function listItemText(line) {
    return String(line || "").replace(/^\s*(?:[-*]|\d+[.)])\s+/, "");
  }

  function readList(lines, i, kind) {
    var items = [];
    while (i < lines.length) {
      var probe = i;
      while (probe < lines.length && !String(lines[probe]).trim()) probe += 1;
      if (probe >= lines.length) {
        i = probe;
        break;
      }
      var line = lines[probe];
      var kindNow = listKind(line);
      if (kindNow === "ul" && kind === "ol" && items.length) {
        var nested = readList(lines, probe, "ul");
        items[items.length - 1] = items[items.length - 1].replace(/<\/li>$/, nested.html + "</li>");
        i = nested.i;
        continue;
      }
      if (kindNow !== kind) break;
      i = probe + 1;
      var html = "<li>" + inlineMd(escapeHtml(listItemText(line)));
      while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !listKind(lines[i])) {
        html += "<br>" + inlineMd(escapeHtml(String(lines[i]).trim()));
        i += 1;
      }
      html += "</li>";
      items.push(html);
    }
    return { html: "<" + kind + ">" + items.join("") + "</" + kind + ">", i: i };
  }

  function renderMarkdown(text) {
    var lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    var out = [];
    var para = [];
    var i = 0;
    function flushPara() {
      if (!para.length) return;
      out.push("<p>" + inlineMd(escapeHtml(para.join("\n")).replace(/\n/g, "<br>")) + "</p>");
      para = [];
    }
    while (i < lines.length) {
      var line = lines[i];
      if (/^```/.test(line)) {
        flushPara();
        var buf = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          buf.push(escapeHtml(lines[i]));
          i += 1;
        }
        if (i < lines.length) i += 1;
        out.push("<pre><code>" + buf.join("\n") + "</code></pre>");
        continue;
      }
      if (!String(line).trim()) {
        flushPara();
        i += 1;
        continue;
      }
      var heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (heading) {
        flushPara();
        var level = heading[1].length;
        out.push("<h" + level + ">" + inlineMd(escapeHtml(heading[2])) + "</h" + level + ">");
        i += 1;
        continue;
      }
      var kind = listKind(line);
      if (kind) {
        flushPara();
        var list = readList(lines, i, kind);
        out.push(list.html);
        i = list.i;
        continue;
      }
      para.push(line);
      i += 1;
    }
    flushPara();
    return out.join("");
  }

  function appendMsg(role, content, extra) {
    var body = document.getElementById("erp-ai-body");
    if (!body) return;
    var empty = body.querySelector(".erp-ai-empty");
    if (empty) empty.remove();
    var wrap = el("div", "erp-ai-msg " + role);
    if (extra && extra.thinking) wrap.appendChild(extra.thinking);
    var filesInText = parseFileLinks(content || "");
    var parsed = parseOpenLinks(filesInText.text || "");
    var bubble = el("div", "bubble");
    if (role === "assistant" && !(extra && extra.plain)) {
      bubble.classList.add("erp-ai-md");
      bubble.innerHTML = renderMarkdown(parsed.text);
    } else {
      bubble.textContent = parsed.text;
    }
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
    appendFileButtons(wrap, filesInText.files.concat((extra && extra.files) || []));
    if (extra && extra.ack) wrap.appendChild(renderAck(extra.ack));
    body.appendChild(wrap);
    body.scrollTop = body.scrollHeight;
    return wrap;
  }

  function parseFileLinks(content) {
    var files = [];
    var text = String(content || "").replace(
      /\[\[file:(\/private\/files\/[^\]|\s]+)\|([^\]]+)\]\]/g,
      function (_m, url, label) {
        files.push({ url: url, label: label });
        return "";
      }
    );
    return { text: text.replace(/\n+$/, "").trim(), files: files };
  }

  function appendFileButtons(parent, files) {
    var seen = {};
    (files || []).forEach(function (file) {
      if (!file || !file.url || String(file.url).indexOf("/private/files/") !== 0) return;
      if (seen[file.url]) return;
      seen[file.url] = 1;
      var link = document.createElement("a");
      link.className = "erp-ai-open-link";
      link.href = file.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = file.label || file.url;
      parent.appendChild(link);
    });
  }

  function thinkingBlock(steps, ms) {
    var det = el("details", "erp-ai-thinking");
    det.id = "erp-ai-thinking-live";
    det.open = true;
    var sum = el("summary");
    sum.textContent = ms
      ? t("thoughtFor").replace("{0}", String(Math.max(1, Math.round(ms / 1000))))
      : t("thinking");
    det.appendChild(sum);
    var ol = el("ol");
    var unique = [];
    var seen = {};
    (steps || []).forEach(function (s) {
      if (!s) return;
      if (s.id && seen[s.id]) {
        unique[seen[s.id] - 1] = s;
        return;
      }
      unique.push(s);
      if (s.id) seen[s.id] = unique.length;
    });
    unique.forEach(function (s) {
      var li = el("li");
      li.dataset.status = s.status || "";
      var label = (state.lang === "ar" ? s.label_ar : s.label_en) || s.tool || "";
      li.appendChild(textNode("div", "erp-ai-step-label", label));
      var detail = state.lang === "ar" ? s.detail_ar || s.detail : s.detail || s.detail_ar;
      if (detail) li.appendChild(textNode("div", "erp-ai-step-detail", detail));
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
    box.appendChild(textNode("strong", "", t("ackTitle")));
    box.appendChild(textNode("div", "", (pending && pending.summary) || ""));
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
          files: (res && res.files) || [],
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

  function uploadFile(file) {
    var body = new FormData();
    body.append("file", file);
    return fetch("/api/method/erpnext_ai_assistant.api.chat.upload_attachment", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Frappe-CSRF-Token": csrf(), Accept: "application/json" },
      body: body,
    }).then(function (r) {
      return r.json().then(function (j) {
        if (j.exc || (r.status >= 400 && j.message == null)) {
          throw new Error(j.exc_type || t("error"));
        }
        return j.message != null ? j.message : j;
      });
    });
  }

  function downloadTemplate(doctype) {
    call("erpnext_ai_assistant.api.chat.blank_import_template", { doctype: doctype }).then(function (res) {
      var blob = new Blob([res.csv || ""], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = res.filename || doctype + ".csv";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  function renderImportReview(review) {
    var box = el("div", "erp-ai-import");
    (review.templates || []).forEach(function (item) {
      var line = textNode(
        "div",
        "",
        item.doctype + " — " + Math.round((item.score || 0) * 100) + "%"
      );
      box.appendChild(line);
      var btn = el("button", "", t("template") + " " + item.doctype);
      btn.type = "button";
      btn.addEventListener("click", function () {
        downloadTemplate(item.doctype);
      });
      box.appendChild(btn);
    });
    return box;
  }

  function onSend() {
    var ta = document.getElementById("erp-ai-input");
    if (!ta) return;
    var msg = (ta.value || "").trim();
    var files = state.files.slice();
    if (!msg && !files.length) return;
    if (hasArabic(msg)) state.lang = "ar";
    ta.value = "";
    state.files = [];
    appendMsg("user", msg || files.map(function (file) { return file.name; }).join(", "));
    state.steps = [];
    state.thinkingMs = 0;
    var started = Date.now();
    var think = thinkingBlock(state.steps, 0);
    var asstWrap = appendMsg("assistant", t("loading"), { thinking: think });
    var uploads = Promise.all(files.map(uploadFile));
    uploads
      .then(function (uploaded) {
        var notes = [];
        var images = [];
        var reviews = [];
        var tableUrl = "";
        (uploaded || []).forEach(function (item) {
          if (!item) return;
          if (item.kind === "image") images.push(item);
          if (item.kind === "table" && item.file_url) tableUrl = item.file_url;
          if (item.review_text) notes.push(item.review_text);
          if (item.excerpt) notes.push(item.excerpt);
          if (item.review) reviews.push(item.review);
        });
        var full = [msg].concat(notes).filter(Boolean).join("\n\n");
        return call("erpnext_ai_assistant.api.chat.run", {
          message: full || msg || "Review the attached file.",
          route: location.pathname,
          chat_id: state.chatId || "",
          attachments: JSON.stringify(images),
          file_url: tableUrl,
        }).then(function (res) {
          res._reviews = reviews;
          return res;
        });
      })
      .then(function (res) {
        state.chatId = res.chat_id || state.chatId;
        state.steps = res.steps || state.steps;
        state.thinkingMs = Date.now() - started;
        if (asstWrap && asstWrap.parentNode) asstWrap.parentNode.removeChild(asstWrap);
        if (res.persona && typeof res.persona === "object") {
          state.persona = res.persona;
          applyPersonaLabel();
        }
        var bubble = appendMsg("assistant", res.message || "", {
          plain: !!res.next_ask,
          thinking: thinkingBlock(state.steps, state.thinkingMs),
          charts: res.charts || [],
          files: res.files || [],
          ack: res.pending_action
            ? {
                pending_action: res.pending_action,
                summary: res.pending_summary || res.message || "",
              }
            : null,
        });
        (res._reviews || []).forEach(function (review) {
          if (bubble) bubble.appendChild(renderImportReview(review));
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
    call("erpnext_ai_assistant.api.chat.bootstrap", { route: location.pathname || "" })
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

  function personaLine() {
    var persona = state.persona || (state.boot && state.boot.persona) || null;
    if (persona && typeof persona === "object") {
      var label =
        state.lang === "ar"
          ? persona.panel_label_ar || persona.panel_label
          : persona.panel_label || persona.panel_label_ar;
      if (label) return label;
    }
    var branding = (state.boot && state.boot.branding) || {};
    return branding.subtitle || t("subtitle");
  }

  function applyPersonaLabel() {
    var node = document.querySelector("#erp-ai-root .erp-ai-persona");
    if (node) node.textContent = personaLine();
  }

  function watchRoute() {
    var last = location.pathname;
    setInterval(function () {
      if (location.pathname === last) return;
      last = location.pathname;
      call("erpnext_ai_assistant.api.chat.bootstrap", { route: last }).then(function (boot) {
        if (!boot) return;
        state.boot = boot;
        if (boot.persona) state.persona = boot.persona;
        applyPersonaLabel();
      });
    }, 1000);
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
    watchRoute();
  }

  start();
})();
