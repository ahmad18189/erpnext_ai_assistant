/* The ERPNext-AI-Assistant panel: Desk paths and record links for Frappe v15 (/app) and v16 (/desk). */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_desk_compat) return; // loaded twice (Desk hooks + crm_include.js): keep the first
  A.loaded_desk_compat = 1;
  var state = A.state, t = A.t, el = A.el;

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
      if (pat === "/desk" && raw.indexOf("/app") === 0) return true;
      return false;
    }
    var appRoutes = (state.boot && state.boot.app_routes) || [];
    if (appRoutes.some(function (row) { return hit(row && row.route); })) return true;
    if (!pages || !pages.length) {
      return hit("/desk") || hit("/app");
    }
    return pages.some(function (p) {
      return p && p.enabled && hit(p.path_pattern || "");
    });
  }
  function safeLocalPath(path) {
    if (!path || typeof path !== "string") return "";
    if (path.indexOf("://") !== -1 || path.indexOf("//") === 0 || path.indexOf("\\") !== -1) return "";
    if (path.charAt(0) !== "/") return "";
    if (path.indexOf("/desk/") === 0) return path;
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
      if (window.frappe && frappe.set_route && path.indexOf("/desk/") === 0) {
        ev.preventDefault();
        var bits = path.split("/").filter(Boolean);
        frappe.set_route.apply(frappe, bits);
      }
    });
    return a;
  }

  A.normalizeDeskPath = normalizeDeskPath;
  A.pathMatches = pathMatches;
  A.safeLocalPath = safeLocalPath;
  A.openRecordButton = openRecordButton;
})();
