const pathInput = document.getElementById("path-input");
const tabNameInput = document.getElementById("tab-name-input");
const statusLabel = document.getElementById("status-label");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const availableList = document.getElementById("available-list");
const chainList = document.getElementById("chain-list");
const repeatInput = document.getElementById("repeat-input");
const logConsole = document.getElementById("log-console");
const browseModal = document.getElementById("browse-modal");
const browseClose = document.getElementById("browse-close");
const browseList = document.getElementById("browse-list");
const browseUp = document.getElementById("browse-up");
const browseParent = document.getElementById("browse-parent");
const previewToggle = document.getElementById("preview-toggle");
const previewImg = document.getElementById("preview-img");
const previewMode = document.getElementById("preview-mode");
const previewLive = document.getElementById("preview-live");
const previewStrip = document.getElementById("preview-strip");
const stripList = document.getElementById("strip-list");
const previewEmpty = document.getElementById("preview-empty");

const createRoutineBtn = document.getElementById("create-routine-btn");
const routineEditorModal = document.getElementById("routine-editor-modal");
const routineEditorClose = document.getElementById("routine-editor-close");
const routineEditorTitle = document.getElementById("routine-editor-title");
const routineNameInput = document.getElementById("routine-name");
const routineSteps = document.getElementById("routine-steps");
const routineRecoverSteps = document.getElementById("routine-recover-steps");
const routineEditorError = document.getElementById("routine-editor-error");
const addStepBtn = document.getElementById("add-step-btn");
const addRecoverStepBtn = document.getElementById("add-recover-step-btn");
const routineSaveBtn = document.getElementById("routine-save-btn");
const cfgGamePathInput = document.getElementById("cfg-game-path");
const cfgTabNameInput = document.getElementById("cfg-tab-name");
const cfgBrowseBtn = document.getElementById("cfg-browse-btn");
const windowOptions = document.getElementById("window-options");
const CONFIG_FIELDS = [
    { id: "cfg-game-path", key: "game_path", type: "string" },
    { id: "cfg-tab-name", key: "tab_name", type: "string" },
    { id: "cfg-delay", key: "delay", type: "float" },
    { id: "cfg-max-step-retry", key: "max_step_retry", type: "int" },
    { id: "cfg-timeout", key: "timeout", type: "float" },
    { id: "cfg-max-recover", key: "max_recover", type: "int" },
];

let ws = null;
let currentBrowsePath = "";
let availableRoutines = [];
let routineLabels = {};
let currentBrowseCallback = null;
let activeChain = [];
let isActive = false;
let editingFilename = null;
let routineEditorState = newRoutineState();
let previewEnabled = false;
let previewFramePending = false;
let snapshotRows = new Map();

function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        if (data.type === "log") {
            appendLog(data.line);
        } else if (data.type === "state") {
            updateState(data.state);
        } else if (data.type === "frame") {
            if (previewEnabled && !previewFramePending) {
                previewFramePending = true;
                requestAnimationFrame(() => {
                    previewFramePending = false;
                    handleFrame(data);
                });
            }
        } else if (data.type === "preview_clear") {
            snapshotRows.clear();
            renderStrip();
        } else if (data.type === "config") {
            updateActiveTarget(data.active_target);
        }
    };
    ws.onclose = () => {
        setTimeout(connect, 2000);
    };
}

function handleFrame(data) {
    if (previewMode.value === "live") {
        previewImg.src = "data:image/jpeg;base64," + data.jpeg;
        return;
    }
    const idx = data.step_index;
    if (idx === null || idx === undefined) {
        return;
    }
    snapshotRows.set(idx, data);
    renderStrip();
}

function renderStrip() {
    stripList.innerHTML = "";
    if (snapshotRows.size === 0) {
        previewEmpty.classList.remove("hidden");
        return;
    }
    previewEmpty.classList.add("hidden");
    const indices = Array.from(snapshotRows.keys()).sort((a, b) => a - b);
    for (const idx of indices) {
        const row = snapshotRows.get(idx);
        const div = document.createElement("div");
        div.className = "strip-row";
        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + row.jpeg;
        img.alt = "step " + idx;
        const meta = document.createElement("div");
        meta.className = "strip-meta";
        const label = row.step_label || "step";
        const conf = row.confidence != null ? row.confidence.toFixed(2) : "-";
        const ts = row.timestamp ? new Date(row.timestamp * 1000).toLocaleTimeString() : "-";
        meta.textContent = `step ${idx} · ${label} · ${conf} · ${ts}`;
        div.appendChild(img);
        div.appendChild(meta);
        stripList.appendChild(div);
    }
}

function appendLog(line) {
    logConsole.textContent += line + "\n";
    logConsole.scrollTop = logConsole.scrollHeight;
}

function updateState(state) {
    statusLabel.textContent = state;
    statusLabel.className = "status-" + state.toLowerCase();

    isActive = state === "RUNNING" || state === "PAUSED";
    startBtn.disabled = isActive;
    stopBtn.disabled = !isActive;
    setControlsEnabled(!isActive);
}

function setControlsEnabled(enabled) {
    pathInput.disabled = !enabled;
    tabNameInput.disabled = !enabled;
    repeatInput.disabled = !enabled;
    availableList.querySelectorAll("button").forEach((b) => (b.disabled = !enabled));
    chainList.querySelectorAll("button").forEach((b) => (b.disabled = !enabled));
}

function updateActiveTarget(target) {
    if (!target) {
        pathInput.value = "";
        tabNameInput.value = "";
        return;
    }
    pathInput.value = target.game_path || "";
    tabNameInput.value = target.tab_name || "";
}

async function fetchState() {
    const res = await fetch("/api/state");
    const data = await res.json();
    updateState(data.state);
    updateActiveTarget(data.active_target);
}

async function loadPreviewState() {
    try {
        const res = await fetch("/api/preview");
        const data = await res.json();
        previewEnabled = Boolean(data.enabled);
        previewToggle.checked = previewEnabled;
        if (data.mode === "live" || data.mode === "snapshot") {
            previewMode.value = data.mode;
        }
        updatePreviewView();
    } catch (e) {
        appendLog("Failed to load preview state: " + e.message);
    }
}

async function applyPreviewSettings() {
    previewEnabled = previewToggle.checked;
    updatePreviewView();
    if (!previewEnabled) {
        previewImg.src = "";
        snapshotRows.clear();
        renderStrip();
    }
    try {
        await fetch("/api/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: previewEnabled, mode: previewMode.value }),
        });
    } catch (e) {
        appendLog("Failed to set preview: " + e.message);
    }
}

function updatePreviewView() {
    const isLive = previewMode.value === "live";
    previewLive.classList.toggle("hidden", !(previewEnabled && isLive));
    previewStrip.classList.toggle("hidden", !(previewEnabled && !isLive));
    if (!previewEnabled) {
        previewLive.classList.add("hidden");
        previewStrip.classList.add("hidden");
    }
}

async function loadConfig() {
    const res = await fetch("/api/config");
    const data = await res.json();
    activeChain = Array.isArray(data.routines) ? data.routines : [];
    if (data.repeat !== undefined) {
        repeatInput.value = String(data.repeat);
    }
    renderChain();
}

async function loadRoutines() {
    const res = await fetch("/api/routines");
    const data = await res.json();
    availableRoutines = data.routines || [];
    routineLabels = data.labels || {};
    renderAvailable();
    if (Array.isArray(data.chain)) {
        activeChain = data.chain;
    }
    if (data.repeat !== undefined) {
        repeatInput.value = String(data.repeat);
    }
    renderChain();
}

function renderAvailable() {
    availableList.innerHTML = "";
    for (const name of availableRoutines) {
        const row = document.createElement("div");
        row.className = "chain-item";
        row.innerHTML = `<span>${escapeHtml(routineLabels[name] ?? name)}</span>`;
        const controls = document.createElement("span");
        controls.className = "chain-controls";

        const addBtn = document.createElement("button");
        addBtn.textContent = "+";
        addBtn.title = "Add to chain";
        addBtn.disabled = isActive;
        addBtn.addEventListener("click", () => addToChain(name));

        const editBtn = document.createElement("button");
        editBtn.textContent = "Edit";
        editBtn.title = "Edit routine";
        editBtn.disabled = isActive;
        editBtn.addEventListener("click", () => openRoutineEditor(name));

        const deleteBtn = document.createElement("button");
        deleteBtn.textContent = "Delete";
        deleteBtn.title = "Delete routine";
        deleteBtn.className = "icon-danger";
        deleteBtn.disabled = isActive;
        deleteBtn.addEventListener("click", () => deleteRoutine(name));

        controls.appendChild(addBtn);
        controls.appendChild(editBtn);
        controls.appendChild(deleteBtn);
        row.appendChild(controls);
        availableList.appendChild(row);
    }
}

function renderChain() {
    chainList.innerHTML = "";
    activeChain.forEach((name, idx) => {
        const row = document.createElement("div");
        row.className = "chain-item";
        row.innerHTML = `<span>${idx + 1}. ${escapeHtml(routineLabels[name] ?? name)}</span>`;
        const controls = document.createElement("span");
        controls.className = "chain-controls";

        const upBtn = document.createElement("button");
        upBtn.textContent = "↑";
        upBtn.disabled = isActive || idx === 0;
        upBtn.addEventListener("click", () => moveChainItem(idx, -1));

        const downBtn = document.createElement("button");
        downBtn.textContent = "↓";
        downBtn.disabled = isActive || idx === activeChain.length - 1;
        downBtn.addEventListener("click", () => moveChainItem(idx, 1));

        const removeBtn = document.createElement("button");
        removeBtn.textContent = "×";
        removeBtn.disabled = isActive;
        removeBtn.addEventListener("click", () => removeFromChain(idx));

        controls.appendChild(upBtn);
        controls.appendChild(downBtn);
        controls.appendChild(removeBtn);
        row.appendChild(controls);
        chainList.appendChild(row);
    });
}

function addToChain(name) {
    activeChain.push(name);
    renderChain();
    saveConfig();
}

function removeFromChain(idx) {
    activeChain.splice(idx, 1);
    renderChain();
    saveConfig();
}

function moveChainItem(idx, delta) {
    const newIdx = idx + delta;
    if (newIdx < 0 || newIdx >= activeChain.length) {
        return;
    }
    const temp = activeChain[idx];
    activeChain[idx] = activeChain[newIdx];
    activeChain[newIdx] = temp;
    renderChain();
    saveConfig();
}

async function saveConfig() {
    const repeat = Math.max(1, parseInt(repeatInput.value, 10) || 1);
    await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            routines: activeChain,
            repeat: repeat,
        }),
    });
}

startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    await saveConfig();
    await fetch("/api/start", { method: "POST" });
});

stopBtn.addEventListener("click", async () => {
    await fetch("/api/stop", { method: "POST" });
});

repeatInput.addEventListener("change", () => {
    renderChain();
    saveConfig();
});

cfgBrowseBtn.addEventListener("click", () => {
    browseModal.classList.remove("hidden");
    navigateBrowse("");
});

browseClose.addEventListener("click", () => {
    browseModal.classList.add("hidden");
});

browseModal.addEventListener("click", (e) => {
    if (e.target === browseModal) {
        browseModal.classList.add("hidden");
    }
});

browseUp.addEventListener("click", async (e) => {
    e.preventDefault();
    const res = await fetch(`/api/browse?path=${encodeURIComponent(currentBrowsePath)}`);
    const data = await res.json();
    if (data.parent !== null && data.parent !== "") {
        navigateBrowse(data.parent);
    } else {
        navigateBrowse("");
    }
});

async function navigateBrowse(path) {
    currentBrowsePath = path;
    const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
    const data = await res.json();

    browseParent.style.display = data.parent === null || data.parent === "" ? "none" : "";

    let html = "";
    for (const dir of data.dirs) {
        const full = path ? path + "/" + dir : dir;
        html += `<a href="#" class="browse-item dir" data-path="${escapeHtml(full)}">${escapeHtml(dir)}</a>`;
    }
    for (const exe of data.exes) {
        const full = path ? path + "/" + exe : exe;
        html += `<a href="#" class="browse-item exe" data-path="${escapeHtml(full)}">${escapeHtml(exe)}</a>`;
    }
    for (const img of (data.images || [])) {
        const full = path ? path + "/" + img : img;
        const url = `/api/image?path=${encodeURIComponent(full)}`;
        html += `<a href="#" class="browse-card" data-path="${escapeHtml(full)}">
            <img src="${url}" alt="" class="browse-thumb">
            <span class="browse-filename">${escapeHtml(img)}</span>
        </a>`;
    }
    browseList.innerHTML = html;

    browseList.querySelectorAll(".dir").forEach((el) => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            navigateBrowse(el.dataset.path);
        });
    });

    browseList.querySelectorAll(".exe").forEach((el) => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            cfgGamePathInput.value = el.dataset.path;
            browseModal.classList.add("hidden");
        });
    });

    browseList.querySelectorAll(".browse-card").forEach((el) => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            if (currentBrowseCallback) {
                currentBrowseCallback(el.dataset.path);
                currentBrowseCallback = null;
            }
            browseModal.classList.add("hidden");
        });
    });
}

async function refreshWindowSuggestions() {
    try {
        const res = await fetch("/api/windows");
        const data = await res.json();
        const windows = data.windows || [];
        windowOptions.innerHTML = windows
            .map((w) => `<option value="${escapeHtml(w.title)}"></option>`)
            .join("");
    } catch (e) {
        // ignore
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function newRoutineState() {
    return {
        name: "",
        config: { game_path: "", tab_name: "", delay: 0.5, max_step_retry: 15, timeout: 15.0, max_recover: 3 },
        steps: [],
        recover_steps: [],
    };
}

function newClickStep() {
    return {
        type: "click",
        threshold: 0.85,
        grayscale: true,
        ready_delay: 0.0,
        targets: [newClickTarget()],
    };
}

function newClickTarget() {
    return {
        template: "",
        action: "left_click",
        scrollValue: 0,
        offset_x: 0,
        offset_y: 0,
        stay_on_confirm: false,
        threshold: 0.85,
        grayscale: true,
    };
}

async function openRoutineEditor(name) {
    if (name) {
        const res = await fetch(`/api/plan/${encodeURIComponent(name)}`);
        if (!res.ok) {
            const data = await res.json();
            appendLog(`Failed to load plan ${name}: ${data.error || res.statusText}`);
            return;
        }
        routineEditorState = await res.json();
        editingFilename = name;
        if (!routineEditorState.config) {
            routineEditorState.config = newRoutineState().config;
        }
        if (!Array.isArray(routineEditorState.steps)) {
            routineEditorState.steps = [];
        }
        if (!Array.isArray(routineEditorState.recover_steps)) {
            routineEditorState.recover_steps = [];
        }
        routineEditorTitle.textContent = "Edit Routine";
    } else {
        routineEditorState = newRoutineState();
        routineEditorState.steps = [newClickStep()];
        editingFilename = null;
        routineEditorTitle.textContent = "Create Routine";
    }
    routineNameInput.value = routineEditorState.name || "";
    loadRoutineConfig();
    renderRoutineSteps();
    renderRoutineRecoverSteps();
    hideRoutineError();
    routineEditorModal.classList.remove("hidden");
}

function closeRoutineEditor() {
    routineEditorModal.classList.add("hidden");
    routineEditorState = newRoutineState();
    editingFilename = null;
}

function loadRoutineConfig() {
    for (const field of CONFIG_FIELDS) {
        const el = document.getElementById(field.id);
        const val = routineEditorState.config[field.key];
        el.value = val !== undefined && val !== null ? String(val) : "";
    }
}

cfgTabNameInput.addEventListener("focus", refreshWindowSuggestions);

function readRoutineConfig() {
    const cfg = {};
    for (const field of CONFIG_FIELDS) {
        const el = document.getElementById(field.id);
        let value = el.value.trim();
        if (field.type === "string") {
            cfg[field.key] = value;
            continue;
        }
        if (value === "") continue;
        if (field.type === "int") {
            const parsed = parseInt(value, 10);
            if (!isNaN(parsed)) cfg[field.key] = parsed;
        } else if (field.type === "float") {
            const parsed = parseFloat(value);
            if (!isNaN(parsed)) cfg[field.key] = parsed;
        }
    }
    return cfg;
}

function renderRoutineSteps() {
    routineSteps.innerHTML = "";
    routineEditorState.steps.forEach((step, idx) => {
        routineSteps.appendChild(renderStepCard(step, idx, "steps"));
    });
}

function renderRoutineRecoverSteps() {
    routineRecoverSteps.innerHTML = "";
    routineEditorState.recover_steps.forEach((step, idx) => {
        routineRecoverSteps.appendChild(renderStepCard(step, idx, "recover_steps"));
    });
}

function renderStepCard(step, idx, listKey) {
    const card = document.createElement("div");
    card.className = "step-card";

    const header = document.createElement("div");
    header.className = "step-header";
    header.innerHTML = `<span>Step ${idx + 1}</span>`;

    const upBtn = document.createElement("button");
    upBtn.textContent = "^";
    upBtn.disabled = idx === 0;
    upBtn.addEventListener("click", () => moveStep(listKey, idx, -1));

    const downBtn = document.createElement("button");
    downBtn.textContent = "v";
    downBtn.disabled = idx === routineEditorState[listKey].length - 1;
    downBtn.addEventListener("click", () => moveStep(listKey, idx, 1));

    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.className = "icon-danger";
    removeBtn.addEventListener("click", () => removeStep(listKey, idx));

    header.appendChild(upBtn);
    header.appendChild(downBtn);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "step-body";

    body.appendChild(renderClickFields(step));

    card.appendChild(body);
    return card;
}

function renderClickFields(step) {
    const container = document.createElement("div");
    container.className = "click-step-body";

    const topGrid = document.createElement("div");
    topGrid.className = "field-grid";
    topGrid.appendChild(makeInputCell("Ready delay", step.ready_delay, (v) => (step.ready_delay = v)));
    topGrid.appendChild(makeInputCell("Goto step if not found", step.goto_step_if_not_found, (v) => (step.goto_step_if_not_found = v)));
    topGrid.appendChild(makeInputCell("Threshold", step.threshold, (v) => (step.threshold = v)));
    topGrid.appendChild(makeCheckboxCell("Grayscale", step.grayscale, (v) => (step.grayscale = v)));
    topGrid.appendChild(makeInputCell("Label", step.label || "", (v) => (step.label = v || null)));
    container.appendChild(topGrid);

    const targetsTitle = document.createElement("div");
    targetsTitle.className = "targets-title";
    targetsTitle.textContent = "Targets";
    container.appendChild(targetsTitle);

    const targetsBox = document.createElement("div");
    targetsBox.className = "targets-box";
    (step.targets || []).forEach((target, ridx) => {
        targetsBox.appendChild(renderTargetRow(step, target, ridx));
    });
    container.appendChild(targetsBox);

    const addTargetBtn = document.createElement("button");
    addTargetBtn.textContent = "Add Target";
    addTargetBtn.className = "small-btn";
    addTargetBtn.addEventListener("click", () => {
        step.targets.push(newClickTarget());
        refreshEditor();
    });
    container.appendChild(addTargetBtn);

    return container;
}

function renderTargetRow(step, target, ridx) {
    const row = document.createElement("div");
    row.className = "target-row";

    const templateWrap = document.createElement("div");
    templateWrap.className = "labeled-field";
    const templateLabel = document.createElement("label");
    templateLabel.textContent = "Template";
    const templateInline = document.createElement("div");
    templateInline.className = "inline-input";
    const templateInput = document.createElement("input");
    templateInput.type = "text";
    templateInput.placeholder = "templates/...png";
    templateInput.value = target.template || "";
    templateInput.addEventListener("input", () => (target.template = templateInput.value));
    const browseImgBtn = document.createElement("button");
    browseImgBtn.textContent = "Browse";
    browseImgBtn.className = "small-btn";
    browseImgBtn.addEventListener("click", () => {
        currentBrowseCallback = (path) => {
            target.template = path;
            refreshEditor();
        };
        browseModal.classList.remove("hidden");
        navigateBrowse("templates");
    });
    templateInline.appendChild(templateInput);
    templateInline.appendChild(browseImgBtn);
    templateWrap.appendChild(templateLabel);
    templateWrap.appendChild(templateInline);

    const actionWrap = document.createElement("div");
    actionWrap.className = "labeled-field";
    const actionLabel = document.createElement("label");
    actionLabel.textContent = "Action";
    const action = document.createElement("select");
    action.innerHTML = `<option value="left_click">left_click</option><option value="continue">continue</option><option value="right_click">right_click</option>`;
    action.value = target.action || "left_click";
    action.addEventListener("change", () => (target.action = action.value));
    actionWrap.appendChild(actionLabel);
    actionWrap.appendChild(action);

    const scrollValue = makeLabeledMiniNumber("Scroll Value", target.scrollValue, (v) => (target.scrollValue = v));
    const offsetX = makeLabeledMiniNumber("Offset X", target.offset_x, (v) => (target.offset_x = v));
    const offsetY = makeLabeledMiniNumber("Offset Y", target.offset_y, (v) => (target.offset_y = v));
    const goto = makeLabeledMiniNumber("Goto", target.goto, (v) => (target.goto = v), true);
    goto.querySelector("input").placeholder = "go to step if found";
    const threshold = makeLabeledMiniNumber("Threshold", target.threshold, (v) => (target.threshold = v), true);

    const stay = document.createElement("label");
    stay.className = "mini-check labeled-check";
    stay.innerHTML = `<input type="checkbox" ${target.stay_on_confirm ? "checked" : ""}> stay`;
    stay.querySelector("input").addEventListener("change", (e) => (target.stay_on_confirm = e.target.checked));

    const grayscale = document.createElement("label");
    grayscale.className = "mini-check labeled-check";
    grayscale.innerHTML = `<input type="checkbox" ${target.grayscale !== false ? "checked" : ""}> gray`;
    grayscale.querySelector("input").addEventListener("change", (e) => (target.grayscale = e.target.checked));

    const label = makeLabeledInput("Label", target.label || "", (v) => (target.label = v || null));
    label.querySelector("input").placeholder = "label";

    const remove = document.createElement("button");
    remove.textContent = "Remove";
    remove.className = "icon-danger small-btn";
    remove.addEventListener("click", () => {
        step.targets.splice(ridx, 1);
        refreshEditor();
    });

    row.appendChild(templateWrap);
    row.appendChild(actionWrap);
    row.appendChild(scrollValue);
    row.appendChild(offsetX);
    row.appendChild(offsetY);
    row.appendChild(goto);
    row.appendChild(stay);
    row.appendChild(threshold);
    row.appendChild(grayscale);
    row.appendChild(label);
    row.appendChild(remove);
    return row;
}

function makeLabeledInput(labelText, value, setter) {
    const wrap = document.createElement("div");
    wrap.className = "labeled-field";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "text";
    input.value = value !== undefined && value !== null ? String(value) : "";
    input.addEventListener("input", () => setter(input.value));
    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
}

function makeLabeledMiniNumber(labelText, value, setter, nullable = false) {
    const wrap = document.createElement("div");
    wrap.className = "labeled-field";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = makeMiniNumberInput(value, setter, nullable);
    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
}

function makeInputCell(labelText, value, setter, nullableNumber = false) {
    const cell = document.createElement("div");
    cell.className = "field-cell";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "text";
    input.value = value !== undefined && value !== null ? String(value) : "";
    input.addEventListener("input", () => {
        const v = input.value.trim();
        if (v === "" && nullableNumber) {
            setter(null);
            return;
        }
        const parsed = parseFloat(v);
        setter(!isNaN(parsed) ? parsed : v);
    });
    cell.appendChild(label);
    cell.appendChild(input);
    return cell;
}

function makeCheckboxCell(labelText, value, setter) {
    const cell = document.createElement("div");
    cell.className = "field-cell";
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!value;
    input.addEventListener("change", () => setter(input.checked));
    label.appendChild(input);
    label.appendChild(document.createTextNode(" " + labelText));
    cell.appendChild(label);
    return cell;
}

function makeMiniNumberInput(value, setter, nullable = false) {
    const input = document.createElement("input");
    input.type = "number";
    input.className = "mini-number";
    if (value !== undefined && value !== null) input.value = String(value);
    input.addEventListener("input", () => {
        const v = input.value.trim();
        if (v === "" && nullable) {
            setter(null);
            return;
        }
        const parsed = parseFloat(v);
        setter(!isNaN(parsed) ? parsed : 0);
    });
    return input;
}

function moveStep(listKey, idx, delta) {
    const arr = routineEditorState[listKey];
    const newIdx = idx + delta;
    if (newIdx < 0 || newIdx >= arr.length) return;
    const temp = arr[idx];
    arr[idx] = arr[newIdx];
    arr[newIdx] = temp;
    refreshEditor();
}

function removeStep(listKey, idx) {
    routineEditorState[listKey].splice(idx, 1);
    refreshEditor();
}

function refreshEditor() {
    routineEditorState.config = readRoutineConfig();
    routineEditorState.name = routineNameInput.value.trim();
    renderRoutineSteps();
    renderRoutineRecoverSteps();
}

function showRoutineError(msg) {
    routineEditorError.textContent = msg;
    routineEditorError.classList.remove("hidden");
}

function hideRoutineError() {
    routineEditorError.textContent = "";
    routineEditorError.classList.add("hidden");
}

async function saveRoutine() {
    routineEditorState.name = routineNameInput.value.trim();
    routineEditorState.config = readRoutineConfig();
    if (!routineEditorState.name) {
        showRoutineError("Routine name is required.");
        return;
    }

    const body = {
        name: routineEditorState.name,
        config: routineEditorState.config,
        steps: routineEditorState.steps,
    };
    if (routineEditorState.recover_steps && routineEditorState.recover_steps.length) {
        body.recover_steps = routineEditorState.recover_steps;
    }

    const isEdit = editingFilename !== null;
    const url = isEdit
        ? `/api/plan/${encodeURIComponent(editingFilename)}`
        : "/api/plan";
    const method = isEdit ? "PUT" : "POST";
    const res = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
        showRoutineError(data.error || "Save failed");
        return;
    }
    appendLog(`Saved routine '${data.name}'`);
    closeRoutineEditor();
    loadRoutines();
}

async function deleteRoutine(name) {
    if (!confirm(`Delete routine '${name}'?`)) return;
    const res = await fetch(`/api/plan/${encodeURIComponent(name)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) {
        appendLog(`Failed to delete routine '${name}': ${data.error || res.statusText}`);
        return;
    }
    appendLog(`Deleted routine '${name}'`);
    if (activeChain.includes(name)) {
        activeChain = activeChain.filter((n) => n !== name);
        renderChain();
        saveConfig();
    }
    loadRoutines();
}

createRoutineBtn.addEventListener("click", () => openRoutineEditor(null));
routineEditorClose.addEventListener("click", closeRoutineEditor);
routineSaveBtn.addEventListener("click", saveRoutine);
addStepBtn.addEventListener("click", () => {
    routineEditorState.steps.push(newClickStep());
    refreshEditor();
});
addRecoverStepBtn.addEventListener("click", () => {
    routineEditorState.recover_steps.push(newClickStep());
    refreshEditor();
});
routineEditorModal.addEventListener("click", (e) => {
    if (e.target === routineEditorModal) closeRoutineEditor();
});

connect();
loadConfig();
loadRoutines();
fetchState();
loadPreviewState();

previewToggle.addEventListener("change", applyPreviewSettings);
previewMode.addEventListener("change", applyPreviewSettings);
