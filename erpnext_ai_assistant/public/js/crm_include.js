/* Thin CRM/host include — loads The ERPNext-AI-Assistant assets on Overlay Pages. */
(function () {
  if (window.__erpAiCrmInclude) return;
  window.__erpAiCrmInclude = 1;

  var VER = "ai10";

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
  if (!document.querySelector('script[data-erp-ai-js]')) {
    add("script", {
      src: "/assets/erpnext_ai_assistant/js/erpnext_ai_assistant.bundle.js?v=" + VER,
      id: "erpnext-ai-assistant-js",
      "data-erp-ai-js": "1",
      defer: "defer",
    });
  }
})();
