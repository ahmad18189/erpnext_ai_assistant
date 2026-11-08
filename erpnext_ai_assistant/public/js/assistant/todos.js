/* Tasks tab: quick to-dos, alarms, a countdown, and a stopwatch. Loaded before panel.js. */
(function () {
  var A = (window.erpAi = window.erpAi || {});
  if (A.loaded_todos) return;
  A.loaded_todos = 1;

  var el = A.el, textNode = A.textNode, call = A.call, t = A.t, state = A.state;
  var audioCtx = null;
  var announced = {};
  var polling = false;
  var watchStarted = false;
  var tickHandle = null;
  var timer = { running: false, paused: false, left: 5 * 60 * 1000, endsAt: 0, done: false, minutes: 5, seconds: 0 };
  var watch = { running: false, elapsed: 0, startedAt: 0, laps: [] };
  A.taskAlarms = [];

  function unlockAudio() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    try {
      if (!audioCtx) audioCtx = new Ctx();
      if (audioCtx.state === "suspended" && audioCtx.resume) audioCtx.resume();
    } catch (e) {}
  }

  function playAlarm() {
    unlockAudio();
    if (!audioCtx) return;
    var run = function () {
      var now = audioCtx.currentTime;
      [0, 0.22, 0.44].forEach(function (offset, index) {
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.value = index === 1 ? 880 : 660;
        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.exponentialRampToValueAtTime(0.18, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.18);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now + offset);
        osc.stop(now + offset + 0.2);
      });
    };
    if (audioCtx.state === "suspended" && audioCtx.resume) {
      audioCtx.resume().then(run).catch(function () {});
      return;
    }
    run();
  }

  function pad(n) {
    n = Math.max(0, Math.floor(n));
    return (n < 10 ? "0" : "") + n;
  }

  function formatMs(ms) {
    var total = Math.max(0, Math.ceil(ms / 1000));
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    var seconds = total % 60;
    if (hours) return hours + ":" + pad(minutes) + ":" + pad(seconds);
    return pad(minutes) + ":" + pad(seconds);
  }

  function toServer(value) {
    if (!value) return "";
    var text = String(value).replace("T", " ");
    if (text.length === 16) text += ":00";
    return text.slice(0, 19);
  }

  function toLocal(value) {
    if (!value) return "";
    return String(value).replace(" ", "T").slice(0, 16);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function button(label, cls) {
    var node = el("button", cls || "", label);
    node.type = "button";
    return node;
  }

  function ensureTick() {
    if (tickHandle) return;
    tickHandle = setInterval(function () {
      var now = Date.now();
      if (timer.running) {
        timer.left = timer.endsAt - now;
        if (timer.left <= 0) {
          timer.running = false;
          timer.paused = false;
          timer.left = 0;
          timer.done = true;
          playAlarm();
          state.open = true;
          state.tab = "tasks";
          if (A.render) A.render();
        } else {
          paintTimer();
        }
      }
      if (watch.running) {
        watch.elapsed = now - watch.startedAt;
        paintWatch();
      }
    }, 250);
  }

  function paintTimer() {
    var node = document.getElementById("erp-ai-timer-readout");
    if (!node) return;
    node.textContent = timer.done && !timer.running && timer.left <= 0 ? t("timerDone") : formatMs(timer.left);
  }

  function paintWatch() {
    var node = document.getElementById("erp-ai-watch-readout");
    if (node) node.textContent = formatMs(watch.running ? Date.now() - watch.startedAt : watch.elapsed);
    var laps = document.getElementById("erp-ai-watch-laps");
    if (!laps) return;
    clear(laps);
    watch.laps.slice(0, 8).forEach(function (lap, index) {
      laps.appendChild(textNode("div", "erp-ai-lap", index + 1 + "  " + formatMs(lap)));
    });
  }

  function setStatus(message) {
    var node = document.getElementById("erp-ai-task-status");
    if (node) node.textContent = message || "";
  }

  function loadList() {
    var list = document.getElementById("erp-ai-task-list");
    if (!list) return;
    call("erpnext_ai_assistant.api.todos.list_my_todos", { status: "Open" })
      .then(function (res) {
        var host = document.getElementById("erp-ai-task-list");
        if (!host) return;
        clear(host);
        var items = (res && res.items) || [];
        if (!items.length) {
          host.appendChild(textNode("div", "erp-ai-empty", t("taskEmpty")));
          return;
        }
        items.forEach(function (item) {
          host.appendChild(taskRow(item));
        });
      })
      .catch(function (err) {
        var host = document.getElementById("erp-ai-task-list");
        if (!host) return;
        clear(host);
        host.appendChild(textNode("div", "erp-ai-empty", (err && err.message) || t("error")));
      });
  }

  function taskRow(item) {
    var row = el("div", "erp-ai-task");
    row.appendChild(textNode("div", "erp-ai-task-title", item.description || ""));
    var meta = [];
    if (item.date) meta.push(t("taskDue") + " " + item.date);
    if (item.alarm_enabled && item.alarm_at) meta.push(t("taskAlarmOn") + " " + String(item.alarm_at).slice(0, 16));
    if (meta.length) row.appendChild(textNode("div", "erp-ai-task-meta", meta.join(" · ")));
    var actions = el("div", "erp-ai-task-actions");
    var done = button(t("taskDone"), "erp-ai-task-btn");
    done.addEventListener("click", function () {
      unlockAudio();
      call("erpnext_ai_assistant.api.todos.update_my_todo", { name: item.name, status: "Closed" })
        .then(loadList)
        .catch(function (err) {
          setStatus((err && err.message) || t("error"));
        });
    });
    actions.appendChild(done);
    [5, 10, 15].forEach(function (minutes) {
      var snooze = button(t("taskSnooze" + minutes), "erp-ai-task-btn");
      snooze.addEventListener("click", function () {
        unlockAudio();
        call("erpnext_ai_assistant.api.todos.update_my_todo", { name: item.name, snooze_minutes: minutes })
          .then(function () {
            dropAlarm(item.name);
            loadList();
          })
          .catch(function (err) {
            setStatus((err && err.message) || t("error"));
          });
      });
      actions.appendChild(snooze);
    });
    row.appendChild(actions);
    var alarmRow = el("div", "erp-ai-task-alarm-edit");
    var alarmInput = el("input", "erp-ai-task-input");
    alarmInput.type = "datetime-local";
    alarmInput.value = item.alarm_enabled ? toLocal(item.alarm_at) : "";
    alarmInput.setAttribute("aria-label", t("taskAlarm"));
    var saveAlarm = button(t("taskAlarmOn"), "erp-ai-task-btn");
    saveAlarm.addEventListener("click", function () {
      unlockAudio();
      var args = { name: item.name };
      if (alarmInput.value) args.alarm_at = toServer(alarmInput.value);
      else args.clear_alarm = 1;
      call("erpnext_ai_assistant.api.todos.update_my_todo", args)
        .then(loadList)
        .catch(function (err) {
          setStatus((err && err.message) || t("error"));
        });
    });
    alarmRow.appendChild(alarmInput);
    alarmRow.appendChild(saveAlarm);
    row.appendChild(alarmRow);
    return row;
  }

  function dropAlarm(name) {
    A.taskAlarms = (A.taskAlarms || []).filter(function (item) {
      return item.name !== name;
    });
  }

  function renderBanner(wrap) {
    var items = A.taskAlarms || [];
    if (!items.length) return;
    var banner = el("div", "erp-ai-alarm-banner");
    banner.appendChild(textNode("strong", "", t("alarmTitle")));
    items.forEach(function (item) {
      var line = el("div", "erp-ai-alarm-line");
      line.appendChild(textNode("div", "erp-ai-task-title", item.description || ""));
      var actions = el("div", "erp-ai-task-actions");
      var dismiss = button(t("alarmDismiss"), "erp-ai-task-btn");
      dismiss.addEventListener("click", function () {
        unlockAudio();
        call("erpnext_ai_assistant.api.todos.update_my_todo", { name: item.name, alarm_fired: 1 })
          .then(function () {
            dropAlarm(item.name);
            if (A.render) A.render();
          })
          .catch(function (err) {
            setStatus((err && err.message) || t("error"));
          });
      });
      actions.appendChild(dismiss);
      [5, 10, 15].forEach(function (minutes) {
        var snooze = button(t("taskSnooze" + minutes), "erp-ai-task-btn");
        snooze.addEventListener("click", function () {
          unlockAudio();
          call("erpnext_ai_assistant.api.todos.update_my_todo", { name: item.name, snooze_minutes: minutes })
            .then(function () {
              dropAlarm(item.name);
              if (A.render) A.render();
            })
            .catch(function (err) {
              setStatus((err && err.message) || t("error"));
            });
        });
        actions.appendChild(snooze);
      });
      line.appendChild(actions);
      banner.appendChild(line);
    });
    wrap.appendChild(banner);
  }

  function renderTasks(body) {
    var wrap = el("div", "erp-ai-tasks");
    wrap.addEventListener("pointerdown", unlockAudio);
    renderBanner(wrap);

    var form = el("form", "erp-ai-task-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
    });
    form.appendChild(textNode("div", "erp-ai-task-label", t("taskAdd")));
    var desc = el("input", "erp-ai-task-input");
    desc.type = "text";
    desc.maxLength = 2000;
    desc.placeholder = t("taskPlaceholder");
    desc.setAttribute("aria-label", t("taskAdd"));
    var due = el("input", "erp-ai-task-input");
    due.type = "date";
    due.setAttribute("aria-label", t("taskDue"));
    var alarm = el("input", "erp-ai-task-input");
    alarm.type = "datetime-local";
    alarm.setAttribute("aria-label", t("taskAlarm"));
    var alarmToggle = el("label", "erp-ai-task-check");
    var alarmBox = el("input");
    alarmBox.type = "checkbox";
    alarmToggle.appendChild(alarmBox);
    alarmToggle.appendChild(textNode("span", "", t("taskAlarmOn")));
    var save = button(t("taskSave"), "erp-ai-task-btn primary");
    save.addEventListener("click", function () {
      unlockAudio();
      var text = (desc.value || "").trim();
      if (!text) {
        setStatus(t("taskNeedText"));
        return;
      }
      if (alarmBox.checked && !alarm.value) {
        setStatus(t("taskNeedAlarm"));
        return;
      }
      var args = { description: text };
      if (due.value) args.date = due.value;
      if (alarmBox.checked) args.alarm_at = toServer(alarm.value);
      setStatus(t("loading"));
      call("erpnext_ai_assistant.api.todos.create_my_todo", args)
        .then(function () {
          desc.value = "";
          due.value = "";
          alarm.value = "";
          alarmBox.checked = false;
          setStatus("");
          loadList();
        })
        .catch(function (err) {
          setStatus((err && err.message) || t("error"));
        });
    });
    form.appendChild(desc);
    var times = el("div", "erp-ai-task-times");
    times.appendChild(due);
    times.appendChild(alarm);
    form.appendChild(times);
    var saveRow = el("div", "erp-ai-task-actions");
    saveRow.appendChild(alarmToggle);
    saveRow.appendChild(save);
    form.appendChild(saveRow);
    wrap.appendChild(form);
    wrap.appendChild(textNode("div", "erp-ai-task-status", ""));
    var status = wrap.lastChild;
    status.id = "erp-ai-task-status";

    var list = el("div", "erp-ai-task-list");
    list.id = "erp-ai-task-list";
    list.appendChild(textNode("div", "erp-ai-empty", t("loading")));
    wrap.appendChild(list);

    wrap.appendChild(renderTimer());
    wrap.appendChild(renderWatch());
    wrap.appendChild(textNode("p", "erp-ai-task-hint", t("soundHint")));
    body.appendChild(wrap);
    loadList();
    paintTimer();
    paintWatch();
  }

  function renderTimer() {
    var box = el("section", "erp-ai-clock");
    box.appendChild(textNode("div", "erp-ai-task-label", t("timer")));
    var readout = textNode("div", "erp-ai-readout", formatMs(timer.left || (timer.minutes * 60 + timer.seconds) * 1000));
    readout.id = "erp-ai-timer-readout";
    box.appendChild(readout);
    var fields = el("div", "erp-ai-task-times");
    var minutes = el("input", "erp-ai-task-input erp-ai-num");
    minutes.type = "number";
    minutes.min = "0";
    minutes.max = "599";
    minutes.value = String(timer.minutes);
    minutes.setAttribute("aria-label", t("timerMin"));
    var seconds = el("input", "erp-ai-task-input erp-ai-num");
    seconds.type = "number";
    seconds.min = "0";
    seconds.max = "59";
    seconds.value = String(timer.seconds);
    seconds.setAttribute("aria-label", t("timerSec"));
    fields.appendChild(minutes);
    fields.appendChild(textNode("span", "erp-ai-unit", t("timerMin")));
    fields.appendChild(seconds);
    fields.appendChild(textNode("span", "erp-ai-unit", t("timerSec")));
    box.appendChild(fields);
    var actions = el("div", "erp-ai-task-actions");
    var start = button(timer.running ? t("timerPause") : t("timerStart"), "erp-ai-task-btn primary");
    start.addEventListener("click", function () {
      unlockAudio();
      ensureTick();
      if (timer.running) {
        timer.running = false;
        timer.paused = true;
        timer.left = Math.max(0, timer.endsAt - Date.now());
        start.textContent = t("timerStart");
        paintTimer();
        return;
      }
      var mins = Math.max(0, parseInt(minutes.value, 10) || 0);
      var secs = Math.max(0, Math.min(59, parseInt(seconds.value, 10) || 0));
      timer.minutes = mins;
      timer.seconds = secs;
      if (!timer.paused) timer.left = (mins * 60 + secs) * 1000;
      if (timer.left <= 0) return;
      timer.done = false;
      timer.paused = false;
      timer.running = true;
      timer.endsAt = Date.now() + timer.left;
      start.textContent = t("timerPause");
      paintTimer();
    });
    var reset = button(t("timerReset"), "erp-ai-task-btn");
    reset.addEventListener("click", function () {
      var mins = Math.max(0, parseInt(minutes.value, 10) || 0);
      var secs = Math.max(0, Math.min(59, parseInt(seconds.value, 10) || 0));
      timer.running = false;
      timer.paused = false;
      timer.done = false;
      timer.minutes = mins;
      timer.seconds = secs;
      timer.left = (mins * 60 + secs) * 1000;
      start.textContent = t("timerStart");
      paintTimer();
    });
    actions.appendChild(start);
    actions.appendChild(reset);
    box.appendChild(actions);
    return box;
  }

  function renderWatch() {
    var box = el("section", "erp-ai-clock");
    box.appendChild(textNode("div", "erp-ai-task-label", t("stopwatch")));
    var readout = textNode("div", "erp-ai-readout", formatMs(watch.elapsed));
    readout.id = "erp-ai-watch-readout";
    box.appendChild(readout);
    var actions = el("div", "erp-ai-task-actions");
    var start = button(watch.running ? t("swPause") : t("swStart"), "erp-ai-task-btn primary");
    start.addEventListener("click", function () {
      unlockAudio();
      ensureTick();
      if (watch.running) {
        watch.elapsed = Date.now() - watch.startedAt;
        watch.running = false;
        start.textContent = t("swStart");
      } else {
        watch.startedAt = Date.now() - watch.elapsed;
        watch.running = true;
        start.textContent = t("swPause");
      }
      paintWatch();
    });
    var lap = button(t("swLap"), "erp-ai-task-btn");
    lap.addEventListener("click", function () {
      if (!watch.running && !watch.elapsed) return;
      var stamp = watch.running ? Date.now() - watch.startedAt : watch.elapsed;
      watch.laps.unshift(stamp);
      paintWatch();
    });
    var reset = button(t("swReset"), "erp-ai-task-btn");
    reset.addEventListener("click", function () {
      watch.running = false;
      watch.elapsed = 0;
      watch.laps = [];
      start.textContent = t("swStart");
      paintWatch();
    });
    actions.appendChild(start);
    actions.appendChild(lap);
    actions.appendChild(reset);
    box.appendChild(actions);
    var laps = el("div", "erp-ai-laps");
    laps.id = "erp-ai-watch-laps";
    box.appendChild(laps);
    return box;
  }

  function showAlarms(items) {
    if (!items.length) return;
    playAlarm();
    A.taskAlarms = (A.taskAlarms || []).concat(items);
    state.open = true;
    state.tab = "tasks";
    if (!document.getElementById("erp-ai-root") && A.mount) A.mount();
    if (A.render) A.render();
  }

  function pollAlarms() {
    if (polling) return;
    if (state.boot && (state.boot.blocked || state.boot.allowed === false)) return;
    polling = true;
    call("erpnext_ai_assistant.api.todos.due_my_alarms", {})
      .then(function (res) {
        var fresh = [];
        ((res && res.items) || []).forEach(function (item) {
          var key = item.name + "|" + (item.alarm_at || "");
          if (announced[key]) return;
          announced[key] = 1;
          fresh.push(item);
        });
        showAlarms(fresh);
      })
      .catch(function () {})
      .then(function () {
        polling = false;
      });
  }

  function startAlarmWatcher() {
    if (watchStarted) return;
    if (state.boot && (state.boot.blocked || state.boot.allowed === false)) return;
    watchStarted = true;
    ensureTick();
    document.addEventListener("pointerdown", unlockAudio, { capture: true, once: true });
    pollAlarms();
    setInterval(pollAlarms, 20000);
  }

  A.renderTasks = renderTasks;
  A.startAlarmWatcher = startAlarmWatcher;
  A.playAlarm = playAlarm;
})();
