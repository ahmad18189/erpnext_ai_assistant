/* The ERPNext-AI-Assistant panel: turns assistant text into page elements. Never writes model or record text as HTML. */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_render) return; // loaded twice (Desk hooks + crm_include.js): keep the first
  A.loaded_render = 1;
  var state = A.state, t = A.t, el = A.el, textNode = A.textNode, safeLocalPath = A.safeLocalPath;

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
  function parseChartMarkers(content) {
    var charts = [];
    var text = String(content || "").replace(
      /\[\[chart:(bar|pie|line|kpi)\|([^|\]]+)\|([^\]]*)\]\]/g,
      function (_m, type, title, body) {
        var labels = [];
        var values = [];
        String(body || "").split(";").forEach(function (part) {
          var at = part.lastIndexOf("=");
          if (at < 1) return;
          labels.push(part.slice(0, at));
          values.push(parseFloat(part.slice(at + 1)) || 0);
        });
        charts.push({ type: type, title: title, labels: labels, values: values });
        return "";
      }
    );
    return { text: text, charts: charts };
  }
  function parseFileLinks(content) {
    var files = [];
    var text = String(content || "").replace(
      /\[\[\s*file:\s*(\/private\/files\/[^\]|\s]+)\s*\|\s*([^\]]+?)\s*\]\]/g,
      function (_m, url, label) {
        files.push({ url: url, label: label });
        return "";
      }
    );
    return { text: text.replace(/\n{3,}/g, "\n\n").replace(/\n+$/, "").trim(), files: files };
  }

  function fileLinkLabel(file) {
    var label = String((file && file.label) || "").trim();
    var kind = label || "File";
    if (/^(excel|csv|png|open image)$/i.test(kind) || kind === "فتح الصورة" || kind === "فتح Excel" || kind === "فتح CSV") {
      kind = label;
    }
    var name = String((file && file.url) || "").split("/").pop() || "";
    var open = state.lang === "ar" ? "فتح" : "Open";
    if (kind === "Excel" || kind === "CSV" || kind === "PNG") return open + " " + kind;
    return kind || open + " " + name;
  }

  function appendFileButtons(parent, files) {
    var seen = {};
    (files || []).forEach(function (file) {
      if (!file || !file.url || String(file.url).indexOf("/private/files/") !== 0) return;
      if (seen[file.url]) return;
      seen[file.url] = 1;
      var link = document.createElement("a");
      link.className = "erp-ai-file-link";
      link.href = file.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.setAttribute("download", "");
      var title = document.createElement("span");
      title.className = "erp-ai-file-title";
      title.textContent = fileLinkLabel(file);
      var path = document.createElement("span");
      path.className = "erp-ai-file-path";
      path.textContent = String(file.url).split("/").pop();
      link.appendChild(title);
      link.appendChild(path);
      parent.appendChild(link);
    });
  }

  // Inline marks: `code`, [label](url), **bold**, __bold__, *em*. Everything else stays plain text.
  var INLINE = /`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|(^|[\s(])\*([^*\n]+)\*/g;

  // Model text can carry links planted in record data. Only this site's own pages become links;
  // anything else stays visible as text so nobody is sent somewhere by a click.
  function linkOrText(label, url) {
    if (url.indexOf(window.location.origin + "/") !== 0) {
      return document.createTextNode(label + " (" + url + ")");
    }
    var a = textNode("a", "", label);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  function nested(tag, text) {
    var node = document.createElement(tag);
    appendInline(node, text);
    return node;
  }

  function appendInline(parent, text) {
    var s = String(text || "");
    var last = 0;
    var m;
    var re = new RegExp(INLINE.source, "g"); // own copy: nested calls must not share lastIndex
    while ((m = re.exec(s))) {
      var start = m.index + (m[6] !== undefined ? m[6].length : 0);
      if (start > last) parent.appendChild(document.createTextNode(s.slice(last, start)));
      if (m[1] !== undefined) parent.appendChild(textNode("code", "", m[1]));
      else if (m[2] !== undefined) parent.appendChild(linkOrText(m[2], m[3]));
      else if (m[4] !== undefined || m[5] !== undefined) parent.appendChild(nested("strong", m[4] !== undefined ? m[4] : m[5]));
      else parent.appendChild(nested("em", m[7]));
      last = re.lastIndex;
    }
    if (last < s.length) parent.appendChild(document.createTextNode(s.slice(last)));
  }

  function appendInlineLines(parent, text) {
    String(text || "").split("\n").forEach(function (line, index) {
      if (index) parent.appendChild(document.createElement("br"));
      appendInline(parent, line);
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
    var list = document.createElement(kind);
    var lastItem = null;
    while (i < lines.length) {
      var probe = i;
      while (probe < lines.length && !String(lines[probe]).trim()) probe += 1;
      if (probe >= lines.length) {
        i = probe;
        break;
      }
      var line = lines[probe];
      var kindNow = listKind(line);
      if (kindNow === "ul" && kind === "ol" && lastItem) {
        var nested = readList(lines, probe, "ul");
        lastItem.appendChild(nested.node);
        i = nested.i;
        continue;
      }
      if (kindNow !== kind) break;
      i = probe + 1;
      lastItem = document.createElement("li");
      appendInline(lastItem, listItemText(line));
      while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !listKind(lines[i])) {
        lastItem.appendChild(document.createElement("br"));
        appendInline(lastItem, String(lines[i]).trim());
        i += 1;
      }
      list.appendChild(lastItem);
    }
    return { node: list, i: i };
  }

  function isTableRow(line) {
    return /^\s*\|.+\|\s*$/.test(String(line || ""));
  }

  function isTableSep(line) {
    return /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(String(line || ""));
  }

  function splitRow(line) {
    return String(line || "")
      .replace(/^\s*\|/, "")
      .replace(/\|\s*$/, "")
      .split("|")
      .map(function (cell) {
        return cell.trim();
      });
  }

  function readTable(lines, i) {
    var header = splitRow(lines[i]);
    i += 2;
    var table = document.createElement("table");
    var headRow = table.createTHead().insertRow();
    header.forEach(function (cell) {
      var th = document.createElement("th");
      appendInline(th, cell);
      headRow.appendChild(th);
    });
    var body = table.createTBody();
    while (i < lines.length && isTableRow(lines[i]) && !isTableSep(lines[i])) {
      var row = splitRow(lines[i]);
      var tr = body.insertRow();
      header.forEach(function (_cell, index) {
        appendInline(tr.insertCell(), row[index] || "");
      });
      i += 1;
    }
    return { node: table, i: i };
  }

  // Markdown subset the assistant writes, built as DOM nodes (no innerHTML).
  function renderMarkdown(text) {
    text = String(text || "")
      .replace(/\[\[\s*file:\s*\/private\/files\/[^\]|]+\s*\|[^\]]+\]\]/g, "")
      .replace(/\[\[\s*chart:(?:bar|pie|line|kpi)\|[\s\S]*?\]\]/g, "");
    var lines = text.replace(/\r\n/g, "\n").split("\n");
    var out = document.createDocumentFragment();
    var para = [];
    var i = 0;
    function flushPara() {
      if (!para.length) return;
      var p = document.createElement("p");
      appendInlineLines(p, para.join("\n"));
      out.appendChild(p);
      para = [];
    }
    while (i < lines.length) {
      var line = lines[i];
      if (/^```/.test(line)) {
        flushPara();
        var buf = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          buf.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        var pre = document.createElement("pre");
        pre.appendChild(textNode("code", "", buf.join("\n")));
        out.appendChild(pre);
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
        var h = document.createElement("h" + heading[1].length);
        appendInline(h, heading[2]);
        out.appendChild(h);
        i += 1;
        continue;
      }
      if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flushPara();
        var table = readTable(lines, i);
        out.appendChild(table.node);
        i = table.i;
        continue;
      }
      var kind = listKind(line);
      if (kind) {
        flushPara();
        var list = readList(lines, i, kind);
        out.appendChild(list.node);
        i = list.i;
        continue;
      }
      para.push(line);
      i += 1;
    }
    flushPara();
    return out;
  }

  A.renderMarkdown = renderMarkdown;
  A.appendInline = appendInline;
  A.parseOpenLinks = parseOpenLinks;
  A.parseChartMarkers = parseChartMarkers;
  A.parseFileLinks = parseFileLinks;
  A.fileLinkLabel = fileLinkLabel;
  A.appendFileButtons = appendFileButtons;
})();
