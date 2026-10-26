frappe.ui.form.on("ERP AI Settings", {
  refresh(frm) {
    frm.add_custom_button(__("Rebuild RDF"), () => {
      frm.call("rebuild_rdf").then((r) => frappe.msgprint(__("RDF rebuilt: {0}", [JSON.stringify(r.message)])));
    });
    frm.add_custom_button(__("Reindex RAG"), () => {
      frm.call("reindex_rag").then(() => frappe.msgprint(__("RAG reindexed")));
    });
  },
});
