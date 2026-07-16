const pathInput = document.getElementById("path-input");
const statusLabel = document.getElementById("status-label");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const browseBtn = document.getElementById("browse-btn");
const availableList = document.getElementById("available-list");
const chainList = document.getElementById("chain-list");
const repeatInput = document.getElementById("repeat-input");
const logConsole = document.getElementById("log-console");
const browseModal = document.getElementById("browse-modal");
const browseClose = document.getElementById("browse-close");
const browseList = document.getElementById("browse-list");
const browseUp = document.getElementById("browse-up");
const browseParent = document.getElementById("browse-parent");

let ws = null;
let currentBrowsePath = "";
let availableRoutines = [];
let activeChain = [];
let isActive = false;

function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        if (data.type === "log") {
            appendLog(data.line);
        } else if (data.type === "state") {
            updateState(data.state);
        }
    };
    ws.onclose = () => {
        setTimeout(connect, 2000);
    };
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
    repeatInput.disabled = !enabled;
    availableList.querySelectorAll("button").forEach((b) => (b.disabled = !enabled));
    chainList.querySelectorAll("button").forEach((b) => (b.disabled = !enabled));
}

async function fetchState() {
    const res = await fetch("/api/state");
    const data = await res.json();
    updateState(data.state);
    if (data.game_path) {
        pathInput.value = data.game_path;
    }
}

async function loadConfig() {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (data.game_path) {
        pathInput.value = data.game_path;
    }
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
        row.innerHTML = `<span>${escapeHtml(name)}</span>`;
        const addBtn = document.createElement("button");
        addBtn.textContent = "+";
        addBtn.disabled = isActive;
        addBtn.addEventListener("click", () => addToChain(name));
        row.appendChild(addBtn);
        availableList.appendChild(row);
    }
}

function renderChain() {
    chainList.innerHTML = "";
    activeChain.forEach((name, idx) => {
        const row = document.createElement("div");
        row.className = "chain-item";
        row.innerHTML = `<span>${idx + 1}. ${escapeHtml(name)}</span>`;
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
            game_path: pathInput.value.trim(),
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

pathInput.addEventListener("change", saveConfig);

repeatInput.addEventListener("change", () => {
    renderChain();
    saveConfig();
});

browseBtn.addEventListener("click", () => {
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
            pathInput.value = el.dataset.path;
            saveConfig();
            browseModal.classList.add("hidden");
        });
    });
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

connect();
loadConfig();
loadRoutines();
fetchState();
