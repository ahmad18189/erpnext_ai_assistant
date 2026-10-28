/* The ERPNext-AI-Assistant panel: the approval card. Calls into panel.js at run time (A.appendMsg). */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_card) return; // loaded twice (Desk hooks + crm_include.js): keep the first
  A.loaded_card = 1;
  var state = A.state, t = A.t, el = A.el, textNode = A.textNode, call = A.call;

  function renderAck(pending) {
    var box = el("div", "erp-ai-ack");
    box.appendChild(textNode("strong", "", t("ackTitle")));
    box.appendChild(textNode("div", "erp-ai-ack-summary", (pending && pending.summary) || ""));
    var lab = el("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(" " + t("ackCheck")));
    box.appendChild(lab);
    var row = el("div", "erp-ai-composer-row");
    var ok = el("button", "primary", t("approve"));
    var no = el("button", "", t("reject"));
    ok.disabled = true;
    cb.addEventListener("change", function () {
      ok.disabled = !cb.checked;
    });
    // One decision per card: lock both buttons while it runs, and after it lands.
    function settle(text, done) {
      ok.disabled = no.disabled = cb.disabled = !!done;
      if (done) box.classList.add("erp-ai-ack-done");
      if (text) A.appendMsg("assistant", text, {});
    }
    ok.addEventListener("click", function () {
      if (!cb.checked) return;
      ok.disabled = no.disabled = true;
      call("erpnext_ai_assistant.api.chat.approve_action", {
        pending_action: pending.pending_action,
        acknowledgment_text: t("ackCheck"),
        acknowledged: 1,
      })
        .then(function (res) {
          settle("", true);
          A.appendMsg("assistant", (res && res.message) || t("created"), {
            link: res && res.link,
            files: (res && res.files) || [],
          });
        })
        .catch(function (err) {
          settle(t("approveFailed") + ((err && err.message) || t("error")), false);
          ok.disabled = !cb.checked;
          no.disabled = false;
        });
    });
    no.addEventListener("click", function () {
      ok.disabled = no.disabled = true;
      call("erpnext_ai_assistant.api.chat.reject_action", {
        pending_action: pending.pending_action,
      })
        .then(function () {
          settle(t("rejected"), true);
        })
        .catch(function (err) {
          settle((err && err.message) || t("error"), false);
          ok.disabled = !cb.checked;
          no.disabled = false;
        });
    });
    row.appendChild(no);
    row.appendChild(ok);
    box.appendChild(row);
    return box;
  }

  A.renderAck = renderAck;
})();
