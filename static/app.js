const pathInput = document.getElementById("path-input");
const statusLabel = document.getElementById("status-label");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const browseBtn = document.getElementById("browse-btn");
const logConsole = document.getElementById("log-console");
const browseModal = document.getElementById("browse-modal");
const browseClose = document.getElementById("browse-close");
const browseList = document.getElementById("browse-list");
const browseUp = document.getElementById("browse-up");
const browseTitle = document.getElementById("browse-title");
const browseParent = document.getElementById("browse-parent");

let ws = null;
let currentBrowsePath = "";

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

    const active = state === "RUNNING" || state === "PAUSED";
    startBtn.disabled = active;
    stopBtn.disabled = !active;
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
}

async function saveConfig() {
    await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_path: pathInput.value.trim() }),
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

    browseList.querySelectorAll(".dir").forEach(el => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            navigateBrowse(el.dataset.path);
        });
    });

    browseList.querySelectorAll(".exe").forEach(el => {
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
fetchState();
