/* Thin CRM/host include — loads The ERPNext-AI-Assistant assets on Overlay Pages. */
(function () {
  if (window.__erpAiCrmInclude) return;
  window.__erpAiCrmInclude = 1;

  // Same order as PANEL_FILES in hooks.py. The version comes from this file's own URL, if the host adds one.
  var FILES = ["core", "desk_compat", "render", "charts", "card", "panel"];
  var self = document.currentScript;
  var tagged = self && /[?&]v=([^&#]+)/.exec(self.src || "");
  var VER = tagged ? tagged[1] : new Date().toISOString().slice(0, 10);

  function add(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs).forEach(function (k) {
      el.setAttribute(k, attrs[k]);
    });
    document.head.appendChild(el);
    return el;
  }

  if (!document.querySelector('link[data-erp-ai-css]')) {
    add("link", {
      rel: "stylesheet",
      href: "/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=" + VER,
      "data-erp-ai-css": "1",
    });
  }
  // Desk may already have loaded the panel through app_include_js.
  if (!document.querySelector('script[data-erp-ai-js]') && !(window.erpAi && window.erpAi.loaded_core)) {
    FILES.forEach(function (name) {
      var script = add("script", {
        src: "/assets/erpnext_ai_assistant/js/assistant/" + name + ".js?v=" + VER,
        "data-erp-ai-js": name,
      });
      // Inserted scripts ignore defer; async=false keeps them running in this order.
      script.async = false;
    });
  }
})();
