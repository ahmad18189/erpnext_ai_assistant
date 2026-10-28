/* The ERPNext-AI-Assistant panel: mounting, the shell, messages, sending, and Desk hooks. Loaded last. */
(function () {
  // One panel per page, even if a host includes the files twice (Desk hooks + crm_include.js).
  if (window.__erpAiAssistantBooted) return;
  window.__erpAiAssistantBooted = 1;
  var A = (window.erpAi = window.erpAi || {});
  var appendFileButtons = A.appendFileButtons, call = A.call, csrf = A.csrf, el = A.el, hasArabic = A.hasArabic, openRecordButton = A.openRecordButton, parseChartMarkers = A.parseChartMarkers, parseFileLinks = A.parseFileLinks, parseOpenLinks = A.parseOpenLinks, pathMatches = A.pathMatches, renderAck = A.renderAck, renderChart = A.renderChart, state = A.state, t = A.t, textNode = A.textNode;

  var EXPAND_ICON =
    '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M4 9V4h5v2H6v3H4zm10-5h5v5h-2V6h-3V4zM4 15h2v3h3v2H4v-5zm13 3v-3h2v5h-5v-2h3z"/></svg>';
  var SHRINK_ICON =
    '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M9 4v3H6v2h5V4H9zm4 0v5h5V7h-3V4h-2zM4 13v2h3v3h2v-5H4zm9 0v5h2v-3h3v-2h-5z"/></svg>';
  function ensureAssets() {
    if (!document.querySelector('link[data-erp-ai-css]')) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=" + (A.version || "dev");
      link.setAttribute("data-erp-ai-css", "1");
      document.head.appendChild(link);
    }
  }

  function mount() {
    ensureAssets();
    if (!document.getElementById("erp-ai-fab")) mountFab();
    if (!document.getElementById("erp-ai-root")) {
      var root = el("div", "erp-ai-root erp-ai-closed");
      root.id = "erp-ai-root";
      root.setAttribute("dir", "rtl");
      root.setAttribute("lang", state.lang);
      document.body.appendChild(root);
    }
    render();
    if (!state.watching) {
      state.watching = true;
      watchDom();
      subscribeRealtime();
    }
  }

  function mountFab() {
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
  }

  function watchDom() {
    var pending = false;
    var obs = new MutationObserver(function () {
      if (pending || (document.getElementById("erp-ai-root") && document.getElementById("erp-ai-fab"))) return;
      pending = true;
      setTimeout(function () {
        pending = false;
        mount();
      }, 50);
    });
    // Desk replaces page content, not body's direct children; watching body's children is enough.
    obs.observe(document.body, { childList: true });
  }

  function subscribeRealtime() {
    try {
      if (!(window.frappe && frappe.realtime && frappe.realtime.on)) return;
      frappe.realtime.on("erp_ai_thinking", function (data) {
        // Steps go to every tab of this user; keep only those for the message this tab is waiting on.
        if (!data || !state.requestId || data.request_id !== state.requestId) return;
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

    var oldInput = document.getElementById("erp-ai-input");
    if (oldInput) state.draft = oldInput.value;
    var oldBody = document.getElementById("erp-ai-body");
    var scroll = oldBody ? oldBody.scrollTop : 0;
    var log = chatLog();
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
    var sizeBtn = el("button", "erp-ai-size");
    sizeBtn.innerHTML = state.expanded ? SHRINK_ICON : EXPAND_ICON; // fixed icon markup, no data
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
      sizeBtn.innerHTML = state.expanded ? SHRINK_ICON : EXPAND_ICON; // fixed icon markup, no data
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

    var cheat = log.querySelector(".erp-ai-cheat");
    if (cheat && cheat.getAttribute("lang") !== state.lang) {
      var fresh = el("div");
      renderCheatSheet(fresh);
      log.replaceChild(fresh.firstChild, cheat);
    }
    body.appendChild(log);

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
    ta.value = state.draft || "";
    composer.appendChild(ta);
    composer.appendChild(row);
    root.appendChild(composer);
    body.scrollTop = scroll;
  }

  // The conversation lives in one element that survives shell rebuilds (language, files, tabs).
  function chatLog() {
    if (!state.log) {
      state.log = el("div", "erp-ai-log");
      renderCheatSheet(state.log);
    }
    return state.log;
  }

  function bodyChat() {
    forgetRequest();
    state.log = null;
    render();
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
    box.setAttribute("lang", state.lang);
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
  function appendMsg(role, content, extra) {
    var body = document.getElementById("erp-ai-body");
    var log = chatLog();
    var empty = log.querySelector(".erp-ai-empty");
    if (empty) empty.remove();
    var wrap = el("div", "erp-ai-msg " + role);
    if (extra && extra.thinking) wrap.appendChild(extra.thinking);
    var chartsInText = parseChartMarkers(content || "");
    var filesInText = parseFileLinks(chartsInText.text || "");
    var parsed = parseOpenLinks(filesInText.text || "");
    var bubble = el("div", "bubble");
    if (role === "assistant" && !(extra && extra.plain)) {
      bubble.classList.add("erp-ai-md");
      bubble.appendChild(A.renderMarkdown(parsed.text));
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
    var seenCharts = {};
    chartsInText.charts.concat((extra && extra.charts) || []).forEach(function (c) {
      if (!c) return;
      var key = (c.title || "") + "|" + (c.type || "");
      if (seenCharts[key]) return;
      seenCharts[key] = 1;
      wrap.appendChild(renderChart(c));
    });
    appendFileButtons(wrap, filesInText.files.concat((extra && extra.files) || []));
    if (extra && extra.ack) wrap.appendChild(renderAck(extra.ack));
    log.appendChild(wrap);
    if (body) body.scrollTop = body.scrollHeight;
    return wrap;
  }
  // Only the block for the message being answered carries the live id; finished answers keep theirs plain,
  // otherwise live steps for a second question would update the first answer's block.
  function thinkingBlock(steps, ms, live) {
    var det = el("details", "erp-ai-thinking");
    if (live) det.id = "erp-ai-thinking-live";
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
    var next = thinkingBlock(state.steps, state.thinkingMs, true);
    parent.replaceChild(next, live);
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
    if (!ta || state.busy) return;
    var msg = (ta.value || "").trim();
    var files = state.files.slice();
    if (!msg && !files.length) return;
    if (hasArabic(msg)) state.lang = "ar";
    ta.value = "";
    state.draft = "";
    state.files = [];
    appendMsg("user", msg || files.map(function (file) { return file.name; }).join(", "));
    state.steps = [];
    state.thinkingMs = 0;
    state.requestId = "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    var requestId = state.requestId;
    state.busy = true;
    var started = Date.now();
    var think = thinkingBlock(state.steps, 0, true);
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
          request_id: state.requestId,
          attachments: JSON.stringify(images),
          file_url: tableUrl,
        }).then(function (res) {
          res._reviews = reviews;
          return res;
        });
      })
      .then(function (res) {
        state.busy = false;
        if (state.requestId !== requestId) return; // the user started a new chat or opened another one
        state.chatId = res.chat_id || state.chatId;
        state.steps = res.steps || state.steps;
        state.thinkingMs = Date.now() - started;
        if (asstWrap && asstWrap.parentNode) asstWrap.parentNode.removeChild(asstWrap);
        if (res.persona && typeof res.persona === "object") {
          state.persona = res.persona;
          applyPersonaLabel();
        }
        var shown = res.pending_action ? String(res.message || "").split("\n\n")[0] : res.message || "";
        var bubble = appendMsg("assistant", shown, {
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
        state.busy = false;
        if (state.requestId !== requestId) return;
        if (asstWrap && asstWrap.parentNode) asstWrap.parentNode.removeChild(asstWrap);
        appendMsg("assistant", t("error") + (err && err.message ? " (" + err.message + ")" : ""));
      });
  }

  // Leaving the current chat drops whatever reply is still on its way.
  function forgetRequest() {
    state.requestId = null;
    state.busy = false;
    state.steps = [];
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
          forgetRequest();
          state.chatId = r.name;
          state.tab = "chat";
          state.log = el("div", "erp-ai-log");
          render();
          call("erpnext_ai_assistant.api.chat.get_chat_messages", { chat_id: r.name }).then(function (msgs) {
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

  var bootByRoute = {};

  function onRouteChange() {
    var path = location.pathname;
    if (path === state.lastRoute) return;
    state.lastRoute = path;
    var apply = function (boot) {
      if (!boot) return;
      if (!boot._at) boot._at = Date.now();
      bootByRoute[path] = boot;
      state.boot = boot;
      if (boot.persona) state.persona = boot.persona;
      applyPersonaLabel();
    };
    var cached = bootByRoute[path];
    if (cached && Date.now() - cached._at < 60000) {
      apply(cached);
      return;
    }
    call("erpnext_ai_assistant.api.chat.bootstrap", { route: path }).then(apply);
  }

  function watchRoute() {
    state.lastRoute = location.pathname;
    if (window.frappe && frappe.router && typeof frappe.router.on === "function") {
      frappe.router.on("change", onRouteChange);
      return;
    }
    // Pages outside Desk (e.g. a host app) have no Frappe router.
    window.addEventListener("popstate", onRouteChange);
    setInterval(onRouteChange, 3000);
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

  A.ensureAssets = ensureAssets;
  A.mount = mount;
  A.watchDom = watchDom;
  A.subscribeRealtime = subscribeRealtime;
  A.render = render;
  A.bodyChat = bodyChat;
  A.cheatLines = cheatLines;
  A.renderCheatSheet = renderCheatSheet;
  A.renderMemoryForm = renderMemoryForm;
  A.loadMemoryPanel = loadMemoryPanel;
  A.appendMsg = appendMsg;
  A.thinkingBlock = thinkingBlock;
  A.updateThinkingLive = updateThinkingLive;
  A.uploadFile = uploadFile;
  A.downloadTemplate = downloadTemplate;
  A.renderImportReview = renderImportReview;
  A.onSend = onSend;
  A.loadHistory = loadHistory;
  A.bootAndMaybeMount = bootAndMaybeMount;
  A.whenCsrfReady = whenCsrfReady;
  A.personaLine = personaLine;
  A.applyPersonaLabel = applyPersonaLabel;
  A.watchRoute = watchRoute;
  A.start = start;
})();
