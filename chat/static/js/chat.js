const API_URL = "http://localhost:5005/api";

const checkpointInstructions = {
    "intake": "Confirm the project goal, deadline, target user, and definition of done are correct.",
    "forge-flow": "Confirm the workspace map, local state, and verification commands match the project.",
    "gsd": "Review the proposed phases and make sure each phase has a clear success criterion.",
    "execution": "Confirm generated files, validation results, repairs, and delivery artifacts are present.",
    "socraticode": "Confirm semantic search is needed for this project before indexing or querying a codebase.",
    "axon": "Confirm structural analysis is needed before any refactor or dependency-sensitive change.",
    "verification": "Run the displayed check or local server step, then mark whether it passed.",
    "handoff": "Confirm the final summary includes shipped work, verification, and the next action."
};

const helpContent = {
    "forge-harness": {
        title: "Forge Harness",
        body: "Each project is a self-contained workspace. Start with the project goal, then let the protocol cards plan, execute, verify, and hand off the work."
    },
    "forge-brain": {
        title: "Forge Brain",
        body: "This is the selected local model used by the planning agent. You can switch to any available supported model."
    },
    "settings": {
        title: "Settings",
        body: "Use Settings to import installed Ollama models, register a model for provisioning, view the model route, or inspect meaningful harness errors."
    },
    "forge-engine": {
        title: "Forge Engine",
        body: "Forge Engine shows local readiness: hardware, Ollama state, model tools, project protocols, and whether subagents are practical on this machine."
    },
    "forge-intelligence": {
        title: "Forge Intelligence",
        body: "This lane shows which Gemma models are available or safe for the current system. Unsupported options stay disabled with a reason."
    },
    "new-session": {
        title: "New Project",
        body: "Describe the project as clearly as possible. Include deadline, constraints, what done looks like, and whether files already exist."
    },
    "project-directory": {
        title: "Project Directory",
        body: "Choose No for a new workspace. You can leave the path blank or enter a desired new location for Project Execution to create. Choose Yes only for a directory that already exists."
    },
    "human-verify": {
        title: "Human Verify",
        body: "When enabled, Gemma Forge pauses after card work and gives you verification steps. When disabled, it runs the active cards without manual checkpoints."
    },
    "protocol-cards": {
        title: "Protocol Cards",
        body: "Cards are the work harness. Full Forge runs active cards in order; Forge Section runs one card. Unneeded protocols move out of the main stack."
    },
    "session-list": {
        title: "Projects",
        body: "Active projects are current work. Archive moves a project out of the active list without deleting files. X permanently deletes the selected project record and artifacts."
    }
};

let workspace = null;
let currentSessionId = null;
let selectedModel = "";
let sessionsCache = {};
let linkMode = false;
let selectedSessionLinks = new Set();
let pinnedHelpKey = null;
let helpHideTimer = null;

const defaultCards = [
    {
        id: "intake",
        title: "Intake",
        skill: "Project Brief",
        status: "active",
        summary: "Capture project goal, constraints, deadline, and acceptance criteria."
    },
    {
        id: "forge-flow",
        title: "Forge Flow",
        skill: "forge-flow",
        status: "active",
        summary: "Orient on state, verify workspace readiness, and protect user work."
    },
    {
        id: "gsd",
        title: "GSD Planning",
        skill: "gsd",
        status: "active",
        summary: "Break the project into phases with success criteria and verification."
    },
    {
        id: "execution",
        title: "Project Execution",
        skill: "materializer",
        status: "active",
        summary: "Create planned files, validate, repair, retest, and deliver artifacts."
    },
    {
        id: "socraticode",
        title: "SocratiCode",
        skill: "semantic code search",
        status: "conditional",
        summary: "Use for codebase mapping, feature discovery, and concept search."
    },
    {
        id: "axon",
        title: "Axon",
        skill: "structural analysis",
        status: "conditional",
        summary: "Use before refactors, impact checks, and dead-code review."
    },
    {
        id: "verification",
        title: "Verification",
        skill: "checkpoint protocol",
        status: "active",
        summary: "Pause for human verification or continue by section setting."
    },
    {
        id: "handoff",
        title: "Handoff",
        skill: "project memory",
        status: "active",
        summary: "Capture what shipped, what was verified, and what comes next."
    }
];

const cardOrder = ["intake", "forge-flow", "gsd", "execution", "socraticode", "axon", "verification", "handoff"];
const skippedStatuses = new Set(["inactive", "pending"]);
const planRunnableStatuses = new Set(["active", "conditional", "needs-attention"]);

let currentCards = defaultCards;
let planRunning = false;
let planPaused = false;

function directoryModeIsExisting() {
    return document.querySelector('input[name="project-directory-mode"]:checked')?.value === "yes";
}

function updateDirectoryModeNote() {
    const existing = directoryModeIsExisting();
    const input = document.getElementById("project-directory-input");
    const note = document.getElementById("project-directory-note");
    if (!input || !note) {
        return;
    }

    input.placeholder = existing
        ? "/Users/webot/Projects/existing-project"
        : "/Users/webot/Projects/new-project";
    note.textContent = existing
        ? "Existing directory: this path must already exist. Forge Flow orients on it before any implementation work."
        : "No directory yet: leave blank for Forge to create a workspace automatically, or enter a desired new path and Project Execution will create it.";
}

async function loadWorkspace() {
    try {
        updateDirectoryModeNote();
        const res = await fetch(`${API_URL}/workspace/status`);
        workspace = await res.json();
        renderWorkspace(workspace);
        await importInstalledModels(false);
        renderWorkflowCards(defaultCards);
        await fetchSessions();
        showApp();
    } catch (error) {
        document.querySelector(".setup-panel p").textContent = "Workspace scan failed. Check that the local server is running.";
    }
}

function showApp() {
    document.getElementById("setup-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
}

function renderWorkspace(data) {
    const summary = document.getElementById("environment-summary");
    const system = data.system;
    const tools = data.tools;

    summary.innerHTML = "";
    summary.appendChild(fact("CPU", `${system.cpuCount || "Unknown"} cores`));
    summary.appendChild(fact("Memory", system.memoryGb ? `${system.memoryGb} GB` : "Unknown"));
    summary.appendChild(fact("Disk free", system.diskFreeGb ? `${system.diskFreeGb} GB` : "Unknown"));
    summary.appendChild(fact("Ollama", data.ollama.installed ? "Installed" : "Needs install", data.ollama.installed ? "ready" : "warning"));
    summary.appendChild(fact("Ollama service", data.ollama.running ? "Running" : "Will start", data.ollama.running ? "ready" : "warning"));
    summary.appendChild(fact("llama.cpp", tools.llamaCppReady ? "Ready" : "Missing", tools.llamaCppReady ? "ready" : "warning"));
    summary.appendChild(fact("HF token", tools.hfTokenReady ? "Ready" : "Missing", tools.hfTokenReady ? "ready" : "warning"));
    summary.appendChild(fact("Forge Flow", tools.forgeFlowReady ? "Ready" : "Missing", tools.forgeFlowReady ? "ready" : "error"));
    summary.appendChild(fact("GSD", tools.gsdReady ? "Ready" : "Missing", tools.gsdReady ? "ready" : "error"));
    summary.appendChild(fact("SocratiCode install", tools.socraticodeInstalled ? "Installed" : "Needs setup", tools.socraticodeInstalled ? "ready" : "error"));
    summary.appendChild(fact("SocratiCode MCP", tools.socraticodeMcpReady ? "Search ready" : "Degraded", tools.socraticodeMcpReady ? "ready" : "error"));
    summary.appendChild(fact("Qdrant", tools.socraticodeQdrantRunning ? "Running" : (tools.socraticodeDockerReady ? "Will start" : "Docker needed"), tools.socraticodeQdrantRunning ? "ready" : "warning"));
    summary.appendChild(fact("Axon CLI", tools.axonExecutable ? "Installed" : "Needs setup", tools.axonExecutable ? "ready" : "error"));
    summary.appendChild(fact("Axon index", tools.axonProjectReady ? "Indexed" : (tools.axonExecutable ? "Needs index" : "Unavailable"), tools.axonProjectReady ? "ready" : "warning"));
    summary.appendChild(fact("Subagents", String(data.agentCapacity.maxParallelSubagents), data.agentCapacity.maxParallelSubagents ? "ready" : "warning"));

    document.getElementById("ollama-plan").textContent = data.ollama.plan;
    renderModels(data.modelOptions);
}

async function importInstalledModels(writeRegistry = true) {
    try {
        const endpoint = writeRegistry ? "models/import" : "models";
        const options = writeRegistry ? { method: "POST" } : {};
        const res = await fetch(`${API_URL}/${endpoint}`, options);
        const payload = await res.json();
        renderModelSelector(payload);
        await refreshModelRouteStatus();
        if (writeRegistry) {
            document.getElementById("model-registry-status").textContent = "Installed Ollama models were imported into models.json.";
        }
    } catch (error) {
        document.getElementById("model-registry-status").textContent = "Model import failed. Confirm Ollama is running.";
    }
}

function renderModelSelector(payload) {
    const select = document.getElementById("active-model-select");
    const defaultModel = normalizeModelName(payload.defaultModel || payload.recommendedModel || selectedModel);
    const names = new Set([defaultModel]);
    const registryModels = payload.registry?.models || [];
    const detectedModels = payload.detected || [];

    registryModels.forEach(model => {
        if (model.name) names.add(model.name);
        if (model.model) names.add(model.model);
    });
    detectedModels.forEach(model => {
        if (model.name) names.add(model.name);
        if (model.model) names.add(model.model);
    });

    if (selectedModel) {
        names.add(selectedModel);
    }

    select.innerHTML = "";
    Array.from(new Set(Array.from(names).map(normalizeModelName).filter(Boolean))).sort().forEach(name => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
    setSelectedModel(selectedModel || defaultModel, false);
}

async function refreshModelRouteStatus() {
    const status = document.getElementById("model-route-status");
    if (!status) {
        return;
    }

    try {
        const res = await fetch(`${API_URL}/model/route`);
        const payload = await res.json();
        const last = payload.lastCall;
        const lastText = last
            ? `Last harness model call: ${last.model} (${last.source}).`
            : "No model call recorded yet.";
        status.textContent = `Selected model: ${selectedModel || payload.defaultModel}. ${lastText}`;
    } catch (error) {
        status.textContent = "Model route status unavailable.";
    }
}

async function loadErrorLog() {
    const panel = document.getElementById("error-log-panel");
    const output = document.getElementById("error-log-output");
    panel.classList.remove("hidden");
    output.textContent = "Loading errors.";

    try {
        const res = await fetch(`${API_URL}/errors`);
        const payload = await res.json();
        if (!payload.events.length) {
            output.textContent = `No meaningful errors recorded.\nLog path: ${payload.path}`;
            return;
        }

        output.textContent = payload.events.map(event => {
            const lines = [
                `[${event.time || "unknown time"}] ${event.source || "harness"}`,
                event.message || "Error recorded."
            ];
            if (event.errorType || event.error) {
                lines.push(`${event.errorType || "Error"}: ${event.error || ""}`);
            }
            if (event.statusCode) {
                lines.push(`Status: ${event.statusCode}`);
            }
            if (event.extra) {
                lines.push(`Context: ${JSON.stringify(event.extra)}`);
            }
            return lines.join("\n");
        }).join("\n\n");
    } catch (error) {
        output.textContent = "Could not load the error log.";
    }
}

function normalizeModelName(name) {
    const value = String(name || "").trim();
    return value.endsWith(":latest") ? value.replace(":latest", "") : value;
}

function setSelectedModel(model, persist = false) {
    const normalized = normalizeModelName(model);
    if (!normalized) {
        return;
    }

    selectedModel = normalized;
    const select = document.getElementById("active-model-select");
    if (select) {
        const hasOption = Array.from(select.options).some(option => option.value === selectedModel);
        if (!hasOption) {
            const option = document.createElement("option");
            option.value = selectedModel;
            option.textContent = selectedModel;
            select.appendChild(option);
        }
        select.value = selectedModel;
    }
    updateModelCardSelection();
    if (persist) {
        persistSelectedModel();
    }
}

async function persistSelectedModel() {
    if (!currentSessionId || !selectedModel) {
        return;
    }

    try {
        const res = await fetch(`${API_URL}/sessions/${currentSessionId}/model`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: selectedModel })
        });
        const data = await res.json();
        if (data.session) {
            sessionsCache[currentSessionId] = data.session;
        }
    } catch (error) {
        document.getElementById("model-registry-status").textContent = "Model selection will apply to the next request, but could not be saved to this project yet.";
    }
}

function updateModelCardSelection() {
    document.querySelectorAll("#model-options input[data-model]").forEach(input => {
        input.checked = normalizeModelName(input.dataset.model) === selectedModel;
    });
}

function fact(label, value, state = "neutral") {
    const item = document.createElement("div");
    item.className = `fact state-${state}`;
    item.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    return item;
}

function renderModels(models) {
    const list = document.getElementById("model-options");
    list.innerHTML = "";

    models.forEach(model => {
        const card = document.createElement("div");
        const recommended = model.recommended ? "recommended" : "";
        const disabled = model.supported ? "" : "disabled";
        const installed = model.installed ? "Installed locally" : "Will be provisioned";
        card.className = `model-card ${recommended} ${disabled}`;

        if (!selectedModel && model.selected) {
            setSelectedModel(model.ollamaName, false);
        }

        const checked = normalizeModelName(model.ollamaName) === selectedModel ? "checked" : "";
        const disabledAttr = model.supported ? "" : "disabled";
        const reason = model.supported ? installed : model.disabledReason;
        const badge = model.recommended ? "Recommended default" : "Optional model";

        card.innerHTML = `
            <label>
                <input type="radio" name="forge-model-card" data-model="${model.ollamaName}" ${checked} ${disabledAttr}>
                <span>
                    <strong>${model.label}</strong>
                    <small>${model.description}</small>
                    <em>${badge}</em>
                    <em>${reason}</em>
                </span>
            </label>
        `;

        const input = card.querySelector("input");
        input.addEventListener("change", () => {
            if (input.checked) {
                setSelectedModel(input.dataset.model, true);
                refreshModelRouteStatus();
            }
        });
        list.appendChild(card);
    });
    updateModelCardSelection();
}

async function fetchSessions() {
    try {
        const res = await fetch(`${API_URL}/sessions`, { headers: { "Content-Type": "application/json" }});
        const sessions = await res.json();
        sessionsCache = sessions;
        renderSessionsList(sessions);
    } catch (error) {
        console.error("Failed to fetch sessions:", error);
    }
}

function renderSessionsList(sessions) {
    const list = document.getElementById("sessions-list");
    list.innerHTML = "";

    const entries = Object.entries(sessions);
    const activeSessions = entries.filter(([, session]) => !isArchivedSession(session));
    const archivedSessions = entries.filter(([, session]) => isArchivedSession(session));

    renderSessionGroup(list, "Active", activeSessions, "No active projects yet.");
    renderSessionGroup(list, "Archived", archivedSessions, "No archived projects.");
}

function renderSessionGroup(list, label, entries, emptyText) {
    const group = document.createElement("section");
    group.className = `session-group session-group-${label.toLowerCase()}`;
    group.innerHTML = `<div class="session-group-title">${label}</div>`;

    if (!entries.length) {
        const empty = document.createElement("div");
        empty.className = "session-empty";
        empty.textContent = emptyText;
        group.appendChild(empty);
    } else {
        entries.forEach(([id, session]) => {
            group.appendChild(renderSessionRow(id, session));
        });
    }

    list.appendChild(group);
}

function renderSessionRow(id, session) {
    const archived = isArchivedSession(session);
    const state = getSessionState(id, session);
    const row = document.createElement("div");
    row.className = `session-row session-status-${state.name}${id === currentSessionId ? " selected" : ""}`;
    row.title = state.title;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "session-link-check";
    checkbox.checked = selectedSessionLinks.has(id);
    checkbox.disabled = !linkMode || Array.isArray(session) || archived;
    checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
            selectedSessionLinks.add(id);
        } else {
            selectedSessionLinks.delete(id);
        }
    });

    const sessionTitle = sessionTitleText(id, session);
    const button = document.createElement("button");
    button.className = "session-item";
    button.innerHTML = `
        <span class="session-title">${escapeHtml(sessionTitle)}</span>
        <span class="session-state-label">${state.label}</span>
    `;
    button.onclick = () => selectSession(id, session);

    const archiveButton = document.createElement("button");
    archiveButton.className = "session-archive-btn";
    archiveButton.type = "button";
    archiveButton.title = archived ? `Restore ${sessionTitle}` : `Archive ${sessionTitle}`;
    archiveButton.setAttribute("aria-label", archiveButton.title);
    archiveButton.textContent = archived ? "R" : "A";
    archiveButton.addEventListener("click", event => {
        event.stopPropagation();
        setSessionArchive(id, session, !archived);
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "session-delete-btn";
    deleteButton.type = "button";
    deleteButton.title = `Delete ${sessionTitle}`;
    deleteButton.setAttribute("aria-label", `Delete ${sessionTitle}`);
    deleteButton.textContent = "X";
    deleteButton.addEventListener("click", event => {
        event.stopPropagation();
        deleteSession(id, session);
    });

    row.appendChild(checkbox);
    row.appendChild(button);
    row.appendChild(archiveButton);
    row.appendChild(deleteButton);
    return row;
}

function isArchivedSession(session) {
    return !Array.isArray(session) && Boolean(session?.archivedAt);
}

function sessionTitleText(id, session) {
    if (Array.isArray(session)) {
        return id;
    }
    return session.project || id;
}

function currentSessionArchived() {
    const session = sessionsCache[currentSessionId];
    return isArchivedSession(session);
}

async function setSessionArchive(id, session, archived) {
    const output = document.getElementById("agent-output");
    const title = sessionTitleText(id, session);

    try {
        const res = await fetch(`${API_URL}/sessions/${encodeURIComponent(id)}/archive`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ archived })
        });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return;
        }

        selectedSessionLinks.delete(id);
        sessionsCache = data.sessions || {};
        if (currentSessionId === id) {
            if (archived) {
                planRunning = false;
                planPaused = false;
            }
            renderSessionMessages(data.session.messages || []);
            renderWorkflowCards(data.session.cards || defaultCards);
            setPlanStatus(archived ? "Project archived. Restore it before running work." : "Project restored. Full Forge can run active cards.");
        }

        renderSessionsList(sessionsCache);
        output.textContent = archived ? `Archived project "${title}".` : `Restored project "${title}".`;
    } catch (error) {
        output.textContent = "Archive action failed. Confirm the harness server is running.";
    }
}

async function deleteSession(id, session) {
    const output = document.getElementById("agent-output");
    const title = sessionTitleText(id, session);
    const confirmed = window.confirm(`Delete project "${title}"? This removes only this project record and artifacts.`);
    if (!confirmed) {
        return;
    }

    try {
        const res = await fetch(`${API_URL}/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return;
        }

        selectedSessionLinks.delete(id);
        sessionsCache = data.sessions || {};
        if (currentSessionId === id) {
            currentSessionId = null;
            planRunning = false;
            planPaused = false;
            document.getElementById("project-input").value = "";
            document.getElementById("project-directory-input").value = "";
            document.querySelector('input[name="project-directory-mode"][value="no"]').checked = true;
            updateDirectoryModeNote();
            renderSessionMessages([]);
            renderWorkflowCards(defaultCards);
            setPlanStatus("Start a project to run active cards.");
        }

        renderSessionsList(sessionsCache);
        output.textContent = `Deleted project "${title}".`;
    } catch (error) {
        output.textContent = "Project delete failed. Confirm the harness server is running.";
    }
}

function getSessionState(id, session) {
    if (Array.isArray(session)) {
        return { name: "legacy", label: "Legacy", title: "Legacy chat record" };
    }

    if (isArchivedSession(session)) {
        return { name: "archived", label: "Archive", title: "Project is archived" };
    }

    if (id === currentSessionId && planRunning && !planPaused) {
        return { name: "running", label: "Running", title: "Gemma Forge is running this project" };
    }

    const cards = session.cards || [];
    const statuses = new Set(cards.map(card => card.status));

    if (statuses.has("needs-attention") || statuses.has("stopped") || statuses.has("error")) {
        return { name: "stopped", label: "Stopped", title: "Project stopped or needs attention" };
    }

    if (statuses.has("awaiting-human")) {
        return { name: "review", label: "Review", title: "Project is waiting for human verification" };
    }

    if (statuses.has("active") || statuses.has("conditional") || statuses.has("pending")) {
        return { name: "active", label: "Active", title: "Project has active or pending protocol work" };
    }

    if (cards.length && cards.every(card => card.status === "complete")) {
        return { name: "complete", label: "Done", title: "Project completed all active protocol cards" };
    }

    return { name: "idle", label: "Idle", title: "Project is idle" };
}

function selectSession(id, session) {
    currentSessionId = id;
    planRunning = false;
    planPaused = false;
    renderSessionsList(sessionsCache);
    const output = document.getElementById("agent-output");
    if (Array.isArray(session)) {
        output.textContent = "Legacy chat record selected. Start a new project plan for the work harness.";
        renderSessionMessages([]);
        return;
    }

    document.getElementById("project-input").value = session.project || "";
    const hasDirectory = session.projectMode === "existing-directory";
    document.querySelector(`input[name="project-directory-mode"][value="${hasDirectory ? "yes" : "no"}"]`).checked = true;
    const directoryInput = document.getElementById("project-directory-input");
    directoryInput.value = session.projectDirectory || "";
    updateDirectoryModeNote();
    setSelectedModel(session.model || selectedModel, false);
    const messages = session.messages || [];
    const latest = messages[messages.length - 1];
    output.textContent = isArchivedSession(session) ? "Archived project loaded. Restore it before running work." : (latest ? latest.content : "Project loaded.");
    renderSessionMessages(messages);
    renderWorkflowCards(session.cards || defaultCards);
    setPlanStatus(isArchivedSession(session) ? "Project archived. Restore it before running work." : "Project loaded. Full Forge will execute active protocol cards in order.");
}

function renderSessionMessages(messages) {
    const container = document.getElementById("session-messages");
    container.innerHTML = "";
    messages.forEach(message => {
        const item = document.createElement("div");
        item.className = `session-message ${message.role}`;
        item.innerHTML = `<strong>${message.role}</strong><p>${escapeHtml(message.content || "")}</p>`;
        container.appendChild(item);
    });
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderResearchPasses(research) {
    if (!research) {
        return "";
    }

    const statusText = research.used
        ? `${research.used} of ${research.maxPasses} research passes used`
        : `0 of ${research.maxPasses || 0} research passes used`;
    const items = Array.isArray(research.items) ? research.items : [];
    const notes = items.map(item => `
        <div class="review-note">
            <strong>Pass ${escapeHtml(item.pass)}: ${escapeHtml(item.topic)}</strong>
            <p>${escapeHtml(item.note)}</p>
        </div>
    `).join("");

    return `
        <div class="card-research">
            <div class="review-heading">
                <span>Research Passes</span>
                <em>${escapeHtml(statusText)}</em>
            </div>
            <p>${escapeHtml(research.reason || research.policy || "")}</p>
            ${notes}
            ${research.artifact ? `<small>Artifact: ${escapeHtml(research.artifact)}</small>` : ""}
        </div>
    `;
}

function renderExtraReview(review) {
    if (!review || review.required === false) {
        return "";
    }

    const passed = review.passed !== false;
    const findings = Array.isArray(review.findings) ? review.findings : [];
    const fixes = Array.isArray(review.fixesNeeded) ? review.fixesNeeded : [];
    const findingList = findings.length
        ? `<ul>${findings.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : "";
    const fixList = fixes.length
        ? `<ul>${fixes.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : "";

    return `
        <div class="card-extra-review ${passed ? "passed" : "failed"}">
            <div class="review-heading">
                <span>Small-model extra review</span>
                <em>${passed ? "Passed" : "Needs attention"}</em>
            </div>
            <p>${escapeHtml(review.summary || review.reason || "")}</p>
            ${findingList}
            ${fixList}
            ${review.artifact ? `<small>Artifact: ${escapeHtml(review.artifact)}</small>` : ""}
        </div>
    `;
}

function renderPostReviewRepairs(repairs, artifact) {
    if (!Array.isArray(repairs) || repairs.length === 0) {
        return "";
    }

    const repairList = repairs.map(repair => `
        <div class="review-note">
            <strong>Attempt ${escapeHtml(repair.attempt)}: ${escapeHtml(repair.card)}</strong>
            <p>${escapeHtml(repair.action || "")}</p>
        </div>
    `).join("");

    return `
        <div class="card-post-review">
            <div class="review-heading">
                <span>Post-review patch</span>
                <em>${repairs.length} attempt${repairs.length === 1 ? "" : "s"}</em>
            </div>
            ${repairList}
            ${artifact ? `<small>Artifact: ${escapeHtml(artifact)}</small>` : ""}
        </div>
    `;
}

function renderToolExecution(toolExecution) {
    if (!toolExecution) {
        return "";
    }

    const status = toolExecution.status || "unknown";
    const needsAttention = Boolean(toolExecution.requiresAttention);
    const commands = toolExecution.commands && typeof toolExecution.commands === "object"
        ? Object.entries(toolExecution.commands).map(([name, value]) => {
            const text = typeof value === "string"
                ? value
                : `${value?.returncode ?? "n/a"}${value?.skipped ? " skipped" : ""}`;
            return `<li>${escapeHtml(name)}: ${escapeHtml(text)}</li>`;
        }).join("")
        : "";

    return `
        <div class="card-post-review">
            <div class="review-heading">
                <span>${escapeHtml(toolExecution.tool || "Tool")} status</span>
                <em>${escapeHtml(status)}${needsAttention ? " - needs attention" : ""}</em>
            </div>
            <p>${escapeHtml(toolExecution.reason || "")}</p>
            ${commands ? `<ul>${commands}</ul>` : ""}
        </div>
    `;
}

function renderWorkflowCards(cards) {
    const container = document.getElementById("workflow-cards");
    currentCards = Array.isArray(cards) ? cards : defaultCards;
    container.innerHTML = "";

    const visibleCards = sortCards(currentCards.filter(card => !skippedStatuses.has(card.status)));
    const skippedCards = sortCards(currentCards.filter(card => skippedStatuses.has(card.status)));

    if (!visibleCards.length) {
        container.innerHTML = `<div class="empty-card">No active protocol cards yet.</div>`;
    }

    visibleCards.forEach(card => {
        const lastRun = card.lastRun || null;
        const checkpointOpen = lastRun && card.status === "awaiting-human";
        const globalHumanVerify = document.getElementById("global-human-verify").checked;
        const archived = currentSessionArchived();
        const runDisabled = archived || card.status === "complete" || card.status === "awaiting-human";
        const section = document.createElement("section");
        section.className = `workflow-card ${card.status}`;
        section.dataset.cardId = card.id;
        section.innerHTML = `
            <div class="card-topline">
                <div>
                    <span class="card-status">${displayStatus(card.status)}</span>
                    <h3>${escapeHtml(card.title)}</h3>
                </div>
                <label class="verify-toggle">
                    <input type="checkbox" data-mode="${card.id}" ${globalHumanVerify ? "checked" : ""}>
                    <span>Human verify</span>
                </label>
            </div>
            <p>${escapeHtml(card.summary)}</p>
            <div class="card-action-row">
                <button class="section-run-btn" ${runDisabled ? "disabled" : ""}>${archived ? "Archived" : runButtonLabel(card)}</button>
                <div class="skill-pill">${escapeHtml(card.skill)}</div>
            </div>
            <div class="card-result ${lastRun ? "" : "hidden"}">
                <strong>${lastRun ? escapeHtml(lastRun.summary) : ""}</strong>
                <pre>${lastRun ? escapeHtml(lastRun.details || "") : ""}</pre>
                <small>${lastRun?.artifact ? `Artifact: ${escapeHtml(lastRun.artifact)}` : ""}</small>
                ${lastRun ? renderResearchPasses(lastRun.researchPasses) : ""}
                ${lastRun ? renderToolExecution(lastRun.toolExecution) : ""}
                ${lastRun ? renderPostReviewRepairs(lastRun.postReviewRepairs, lastRun.postReviewRepairArtifact) : ""}
                ${lastRun ? renderExtraReview(lastRun.extraReview) : ""}
            </div>
            <div class="checkpoint ${checkpointOpen ? "" : "hidden"}">
                <strong>Checkpoint</strong>
                <p>${lastRun?.checkpoint ? escapeHtml(lastRun.checkpoint) : checkpointInstructions[card.id] || "Verify this section before continuing."}</p>
                <div class="checkpoint-actions">
                    <button data-action="verified">Verified</button>
                    <button data-action="not-verified">Not Verified</button>
                    <button data-action="help">Help</button>
                </div>
                <div class="checkpoint-dialog hidden"></div>
            </div>
        `;

        const toggle = section.querySelector(`[data-mode="${card.id}"]`);
        const checkpoint = section.querySelector(".checkpoint");
        const runButton = section.querySelector(".section-run-btn");
        const dialog = section.querySelector(".checkpoint-dialog");

        toggle.addEventListener("change", () => {
            if (toggle.checked) {
                dialog.classList.remove("hidden");
                checkpoint.classList.remove("hidden");
                dialog.textContent = "What must be true for this checkpoint to count as verified?";
            } else {
                dialog.classList.add("hidden");
                dialog.textContent = "";
                if (card.status !== "awaiting-human") {
                    checkpoint.classList.add("hidden");
                }
            }
        });

        runButton.addEventListener("click", () => runCardSection(card.id, { humanVerify: toggle.checked }));

        section.querySelectorAll("[data-action]").forEach(button => {
            button.addEventListener("click", () => handleCheckpoint(button.dataset.action, card.id));
        });

        container.appendChild(section);
    });

    renderSkippedCards(skippedCards);
    refreshRunPlanButton();
}

function renderSkippedCards(cards) {
    const panel = document.getElementById("skipped-protocols");
    const container = document.getElementById("skipped-cards");
    if (!panel || !container) {
        return;
    }

    container.innerHTML = "";
    panel.classList.toggle("hidden", cards.length === 0);

    cards.forEach(card => {
        const item = document.createElement("div");
        item.className = "skipped-card";
        item.innerHTML = `
            <div>
                <strong>${escapeHtml(card.title)}</strong>
                <span>${displayStatus(card.status)}</span>
            </div>
            <p>${escapeHtml(card.summary)}</p>
        `;
        container.appendChild(item);
    });
}

function sortCards(cards) {
    return [...cards].sort((left, right) => {
        return cardOrder.indexOf(left.id) - cardOrder.indexOf(right.id);
    });
}

function displayStatus(status) {
    const labels = {
        active: "Active now",
        conditional: "Available if needed",
        complete: "Completed",
        "awaiting-human": "Waiting verification",
        "needs-attention": "Needs attention",
        inactive: "Skipped",
        pending: "Pending workspace",
    };
    return labels[status] || status;
}

function runButtonLabel(card) {
    if (card.status === "complete") {
        return "Complete";
    }
    if (card.status === "awaiting-human") {
        return "Awaiting verification";
    }
    if (card.status === "needs-attention") {
        return "Resolve section";
    }
    return "Forge Section";
}

function setPlanStatus(message) {
    const status = document.getElementById("plan-run-status");
    if (status) {
        status.textContent = message;
    }
}

function setAllHumanVerify(checked) {
    document.querySelectorAll(".workflow-card .verify-toggle input").forEach(input => {
        input.checked = checked;
    });
}

function cardHumanVerify(cardId) {
    const toggle = document.querySelector(`.workflow-card[data-card-id="${cardId}"] .verify-toggle input`);
    return toggle?.checked ?? document.getElementById("global-human-verify").checked;
}

function refreshRunPlanButton() {
    const button = document.getElementById("run-plan-btn");
    if (!button) {
        return;
    }

    button.disabled = !currentSessionId || currentSessionArchived() || (planRunning && !planPaused);
    button.textContent = "Full Forge";
}

function nextRunnableCard() {
    return sortCards(currentCards).find(card => planRunnableStatuses.has(card.status));
}

function awaitingHumanCard() {
    return sortCards(currentCards).find(card => card.status === "awaiting-human");
}

async function runCardSection(cardId, options = {}) {
    const output = document.getElementById("agent-output");
    if (!currentSessionId) {
        output.textContent = "Start or select a project before running a Gemma Forge card.";
        return null;
    }

    if (currentSessionArchived()) {
        output.textContent = "Restore this archived project before running Forge work.";
        return null;
    }

    const section = document.querySelector(`.workflow-card[data-card-id="${cardId}"]`);
    const toggle = section?.querySelector(`[data-mode="${cardId}"]`);
    const runButton = section?.querySelector(".section-run-btn");
    const humanVerify = options.humanVerify ?? toggle?.checked ?? document.getElementById("global-human-verify").checked;

    if (runButton) {
        runButton.disabled = true;
        runButton.textContent = "Running";
    }
    section?.classList.add("running");
    output.textContent = `Gemma Forge is running ${cardId}.`;

    try {
        const res = await fetch(`${API_URL}/sessions/${currentSessionId}/cards/${cardId}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                model: selectedModel,
                humanVerify,
                note: options.note || ""
            })
        });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return data;
        }

        const result = data.result;
        output.textContent = `${result.title}: ${result.summary}`;
        await refreshModelRouteStatus();
        renderSessionMessages(data.session.messages || []);
        if (data.session?.cards) {
            renderWorkflowCards(data.session.cards);
        }

        await fetchSessions();
        return data;
    } catch (error) {
        output.textContent = "Card action failed. Confirm the harness server and local model are running.";
        if (runButton) {
            runButton.textContent = "Forge Section";
        }
        return null;
    } finally {
        section?.classList.remove("running");
        if (runButton && runButton.textContent !== "Complete" && runButton.textContent !== "Awaiting verification") {
            runButton.disabled = false;
        }
        refreshRunPlanButton();
    }
}

async function runPlan() {
    const output = document.getElementById("agent-output");
    if (!currentSessionId) {
        output.textContent = "Start or select a project before running a plan.";
        setPlanStatus("Start a project to run active cards.");
        return;
    }

    if (currentSessionArchived()) {
        output.textContent = "Restore this archived project before running Full Forge.";
        setPlanStatus("Project archived. Restore it before running work.");
        return;
    }

    if (planRunning && !planPaused) {
        return;
    }

    planRunning = true;
    planPaused = false;
    renderSessionsList(sessionsCache);
    refreshRunPlanButton();

    while (planRunning) {
        const waiting = awaitingHumanCard();
        if (waiting) {
            planPaused = true;
            setPlanStatus(`Paused for ${waiting.title}. Mark the checkpoint Verified to continue.`);
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }

        const next = nextRunnableCard();
        if (!next) {
            planRunning = false;
            planPaused = false;
            setPlanStatus("Plan run complete. Active protocol cards are done.");
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }

        setPlanStatus(`Running ${next.title}.`);
        const shouldVerify = cardHumanVerify(next.id);
        const data = await runCardSection(next.id, { humanVerify: shouldVerify });
        if (!data || data.error) {
            planRunning = false;
            planPaused = false;
            setPlanStatus("Plan run stopped. Resolve the visible issue before continuing.");
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }

        const updatedCard = (data.session?.cards || currentCards).find(card => card.id === next.id);
        if (updatedCard?.status === "needs-attention") {
            planRunning = false;
            planPaused = false;
            setPlanStatus(`${updatedCard.title} needs attention before Full Forge can continue.`);
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }
        if (shouldVerify && updatedCard?.status === "awaiting-human") {
            planPaused = true;
            setPlanStatus(`Paused for ${updatedCard.title}. Mark Verified to continue.`);
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }
    }
}

async function handleCheckpoint(action, cardId) {
    const section = document.querySelector(`.workflow-card[data-card-id="${cardId}"]`);
    const dialog = section?.querySelector(".checkpoint-dialog");
    if (!dialog) {
        return;
    }

    dialog.classList.remove("hidden");

    if (action === "verified") {
        const data = await updateCheckpointStatus(cardId, "verified");
        if (!data) {
            return;
        }
        if (data.card?.status === "needs-attention") {
            planRunning = false;
            planPaused = false;
            setPlanStatus("Small-model review still flags this card. Use Resolve or override manually.");
            renderSessionsList(sessionsCache);
            refreshRunPlanButton();
            return;
        }
        // Always continue the chain on a successful Verified click. The
        // previous behaviour gated on `planRunning || planPaused`, but those
        // flags get cleared when runPlan exits at a needs-attention pause,
        // so the chain never resumed after the user explicitly approved a
        // card. The user clicking Verified always means "approve + advance".
        setPlanStatus("Checkpoint verified. Continuing to the next active card.");
        planPaused = false;
        planRunning = false;
        renderSessionsList(sessionsCache);
        window.setTimeout(() => runPlan(), 80);
        return;
    }

    if (action === "not-verified") {
        dialog.innerHTML = `
            <label>What failed?</label>
            <textarea placeholder="Describe what did not verify. The agent will use this to resolve the section before continuing."></textarea>
            <button class="secondary-action">Resolve issue</button>
        `;
        const textarea = dialog.querySelector("textarea");
        const button = dialog.querySelector("button");
        button.addEventListener("click", async () => {
            planPaused = true;
            renderSessionsList(sessionsCache);
            const note = textarea.value.trim();
            const data = await updateCheckpointStatus(cardId, "not-verified", note);
            if (!data) {
                return;
            }
            setPlanStatus("Checkpoint marked Not Verified. Rerunning this section with the issue note.");
            const rerun = await runCardSection(cardId, { humanVerify: true, note });
            if (!rerun || rerun.error) {
                // runCardSection already surfaced the error; leave the chain
                // paused so the user can decide.
                return;
            }
            const updatedCard = (rerun.session?.cards || currentCards).find(card => card.id === cardId);
            if (updatedCard?.status === "needs-attention") {
                planRunning = false;
                planPaused = false;
                setPlanStatus(`${updatedCard.title} still needs attention. Use Resolve again or fix manually.`);
                renderSessionsList(sessionsCache);
                refreshRunPlanButton();
                return;
            }
            if (updatedCard?.status === "awaiting-human") {
                // The rerun re-tripped human verify. Leave the chain paused
                // so the user can mark Verified (which will continue) or
                // Resolve again.
                planRunning = false;
                planPaused = true;
                setPlanStatus(`${updatedCard.title} re-ran and is awaiting your verification.`);
                renderSessionsList(sessionsCache);
                refreshRunPlanButton();
                return;
            }
            // Always continue the chain after a successful Resolve. The
            // previous gating on `wasChaining` (= planRunning || planPaused)
            // failed because runPlan clears both flags when it exits at the
            // needs-attention pause that brought the user here in the first
            // place. Resolve clicked = "fix and advance"; restart runPlan
            // unconditionally and let it find the next runnable card (often
            // handoff after a verification fix).
            planPaused = false;
            planRunning = false;
            setPlanStatus("Issue resolved. Continuing to the next active card.");
            renderSessionsList(sessionsCache);
            window.setTimeout(() => runPlan(), 80);
        });
        return;
    }

    dialog.innerHTML = `
        <p>Do you need help with the instructions?</p>
        <textarea placeholder="Tell the agent which part is unclear."></textarea>
        <button class="secondary-action">Get help</button>
    `;
    const textarea = dialog.querySelector("textarea");
    const button = dialog.querySelector("button");
    button.addEventListener("click", () => requestCheckpointHelp(cardId, textarea.value.trim()));
}

async function updateCheckpointStatus(cardId, status, note = "") {
    const output = document.getElementById("agent-output");
    try {
        const res = await fetch(`${API_URL}/sessions/${currentSessionId}/cards/${cardId}/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status, note, model: selectedModel })
        });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return null;
        }
        renderWorkflowCards(data.session.cards || currentCards);
        renderSessionMessages(data.session.messages || []);
        await fetchSessions();
        output.textContent = data.card?.status === "needs-attention"
            ? "Small-model review found an issue before completion."
            : (status === "verified" ? "Checkpoint verified." : "Checkpoint needs attention.");
        return data;
    } catch (error) {
        output.textContent = "Checkpoint update failed. Confirm the harness server is running.";
        return null;
    }
}

async function requestCheckpointHelp(cardId, note) {
    const message = [
        `Help with checkpoint instructions for ${cardId}.`,
        note ? `User question: ${note}` : "Explain exactly how to verify this checkpoint.",
    ].join("\n");
    const input = document.getElementById("session-message-input");
    input.value = message;
    await sendSessionMessage();
}

async function startPlanning() {
    const input = document.getElementById("project-input");
    const project = input.value.trim();
    const output = document.getElementById("agent-output");
    const humanVerify = document.getElementById("global-human-verify").checked;
    const hasProjectDirectory = directoryModeIsExisting();
    const projectDirectory = document.getElementById("project-directory-input").value.trim();

    if (!project) {
        output.textContent = "What project are we planning?";
        input.focus();
        return;
    }

    if (hasProjectDirectory && !projectDirectory) {
        output.textContent = "Add the project directory path or switch to a new project seed.";
        document.getElementById("project-directory-input").focus();
        return;
    }

    output.textContent = "Planning agent is mapping the project and activating protocol cards.";

    try {
        const createRes = await fetch(`${API_URL}/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project, model: selectedModel, hasProjectDirectory, projectDirectory })
        });
        const created = await createRes.json();
        if (created.error) {
            output.textContent = created.error;
            document.getElementById("project-directory-input").focus();
            return;
        }
        currentSessionId = created.session_id;
        renderSessionMessages(created.session.messages || []);

        const planRes = await fetch(`${API_URL}/plan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentSessionId,
                project,
                model: selectedModel,
                checkpointMode: humanVerify ? "human verification" : "auto run"
            })
        });
        const data = await planRes.json();
        output.textContent = data.reply || "Plan created.";
        await refreshModelRouteStatus();
        renderWorkflowCards(data.cards || defaultCards);
        setAllHumanVerify(humanVerify);
        if (data.reply) {
            renderSessionMessages([...(created.session.messages || []), { role: "agent", content: data.reply }]);
        }
        await fetchSessions();
        if (humanVerify) {
            setPlanStatus("Plan ready. Full Forge will pause at each human checkpoint.");
        } else {
            setPlanStatus("Auto-run enabled. Running active protocol cards.");
            await runPlan();
        }
    } catch (error) {
        output.textContent = "Planning failed. Confirm Ollama and the local server are running.";
    }
}

async function sendSessionMessage() {
    const input = document.getElementById("session-message-input");
    const output = document.getElementById("agent-output");
    const message = input.value.trim();

    if (!currentSessionId) {
        output.textContent = "Start or select a project first.";
        return;
    }

    if (!message) {
        input.focus();
        return;
    }

    input.value = "";
    output.textContent = "Agent is working inside this project.";

    try {
        const res = await fetch(`${API_URL}/sessions/${currentSessionId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, model: selectedModel })
        });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return;
        }
        output.textContent = data.reply || "Agent response saved to this project.";
        await refreshModelRouteStatus();
        renderSessionMessages(data.session.messages || []);
        await fetchSessions();
    } catch (error) {
        output.textContent = "Agent request failed. Confirm Ollama and the local harness server are running.";
    }
}

async function provisionModel() {
    const repoId = document.getElementById("download-repo-input").value.trim();
    const ollamaName = document.getElementById("download-name-input").value.trim() || selectedModel;
    const createInterface = document.getElementById("create-interface-check").checked;
    const downloadOnly = document.getElementById("download-only-check").checked;
    const status = document.getElementById("provision-status");

    status.textContent = "Checking model installation state.";

    try {
        const res = await fetch(`${API_URL}/models/provision`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ repoId, ollamaName, createInterface, downloadOnly })
        });
        const data = await res.json();
        status.textContent = data.message || "Model status updated.";
        renderModelSelector({ registry: data.registry, detected: workspace?.ollama?.models || [], defaultModel: selectedModel });
        if (data.session_id) {
            await fetchSessions();
            selectSession(data.session_id, sessionsCache[data.session_id]);
        }
    } catch (error) {
        status.textContent = "Provision request failed.";
    }
}

async function lockSelectedSessions() {
    const output = document.getElementById("agent-output");
    const sessionIds = Array.from(selectedSessionLinks);
    if (sessionIds.length < 2) {
        output.textContent = "Select at least two projects to link.";
        return;
    }

    try {
        const res = await fetch(`${API_URL}/sessions/link`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_ids: sessionIds })
        });
        const data = await res.json();
        if (data.error) {
            output.textContent = data.error;
            return;
        }
        output.textContent = `Projects linked through ${data.bridgeId}. Bridge files were created in the project data folder.`;
        selectedSessionLinks.clear();
        linkMode = false;
        document.getElementById("lock-sessions-btn").classList.add("hidden");
        await fetchSessions();
    } catch (error) {
        output.textContent = "Project linking failed.";
    }
}

function initializeHelp() {
    document.querySelectorAll(".help-trigger").forEach(button => {
        const help = helpContent[button.dataset.helpKey];
        if (!help) {
            return;
        }

        button.title = `${help.title}: ${help.body}`;
        button.addEventListener("mouseenter", () => showHelp(button, false));
        button.addEventListener("focus", () => showHelp(button, false));
        button.addEventListener("mouseleave", () => scheduleHelpHide(button.dataset.helpKey));
        button.addEventListener("blur", () => scheduleHelpHide(button.dataset.helpKey));
        button.addEventListener("click", event => {
            event.stopPropagation();
            const key = button.dataset.helpKey;
            if (pinnedHelpKey === key) {
                hideHelp();
            } else {
                showHelp(button, true);
            }
        });
    });

    const popover = document.getElementById("help-popover");
    popover.addEventListener("mouseenter", () => clearTimeout(helpHideTimer));
    popover.addEventListener("mouseleave", () => {
        if (!pinnedHelpKey) {
            hideHelp();
        }
    });
    document.addEventListener("click", event => {
        if (!event.target.closest(".help-trigger") && !event.target.closest("#help-popover")) {
            hideHelp();
        }
    });
    window.addEventListener("resize", hideHelp);
    window.addEventListener("scroll", () => {
        if (!pinnedHelpKey) {
            hideHelp();
        }
    }, true);
}

function showHelp(anchor, pinned) {
    const key = anchor.dataset.helpKey;
    const help = helpContent[key];
    const popover = document.getElementById("help-popover");
    if (!help || !popover) {
        return;
    }

    clearTimeout(helpHideTimer);
    pinnedHelpKey = pinned ? key : pinnedHelpKey;
    popover.classList.toggle("pinned", pinnedHelpKey === key);
    popover.innerHTML = `
        <strong>${escapeHtml(help.title)}</strong>
        <p>${escapeHtml(help.body)}</p>
    `;
    popover.classList.remove("hidden");
    positionHelp(anchor, popover);
}

function positionHelp(anchor, popover) {
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 32);
    popover.style.width = `${width}px`;
    const left = Math.min(window.innerWidth - width - 16, Math.max(16, rect.left));
    const top = rect.bottom + 10;
    const finalTop = top + popover.offsetHeight > window.innerHeight - 16
        ? Math.max(16, rect.top - popover.offsetHeight - 10)
        : top;
    popover.style.left = `${left}px`;
    popover.style.top = `${finalTop}px`;
}

function scheduleHelpHide(key) {
    clearTimeout(helpHideTimer);
    if (pinnedHelpKey === key) {
        return;
    }
    helpHideTimer = window.setTimeout(hideHelp, 180);
}

function hideHelp() {
    const popover = document.getElementById("help-popover");
    clearTimeout(helpHideTimer);
    pinnedHelpKey = null;
    if (popover) {
        popover.classList.add("hidden");
        popover.classList.remove("pinned");
    }
}

initializeHelp();

document.getElementById("start-planning-btn").addEventListener("click", startPlanning);
document.getElementById("send-session-message-btn").addEventListener("click", sendSessionMessage);
document.getElementById("import-models-btn").addEventListener("click", () => importInstalledModels(true));
document.getElementById("provision-model-btn").addEventListener("click", provisionModel);
document.getElementById("run-plan-btn").addEventListener("click", runPlan);
// Legacy <select id="active-model-select"> was replaced by the pill UI.
// Guarded in case a custom template still mounts the old element.
{
    const legacyModelSelect = document.getElementById("active-model-select");
    if (legacyModelSelect) {
        legacyModelSelect.addEventListener("change", event => {
            setSelectedModel(event.target.value, true);
            refreshModelRouteStatus();
        });
    }
}
document.getElementById("global-human-verify").addEventListener("change", event => {
    setAllHumanVerify(event.target.checked);
    setPlanStatus(event.target.checked ? "Human verification enabled for visible cards." : "Auto-run enabled for visible cards.");
});
document.querySelectorAll('input[name="project-directory-mode"]').forEach(input => {
    input.addEventListener("change", updateDirectoryModeNote);
});
document.getElementById("settings-toggle-btn").addEventListener("click", () => {
    document.getElementById("settings-panel").classList.toggle("hidden");
});
document.getElementById("view-error-log-btn").addEventListener("click", loadErrorLog);
document.getElementById("close-error-log-btn").addEventListener("click", () => {
    document.getElementById("error-log-panel").classList.add("hidden");
});
document.querySelectorAll("[data-collapse-target]").forEach(button => {
    button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.collapseTarget);
        if (!target) {
            return;
        }

        const expanded = button.getAttribute("aria-expanded") === "true";
        const nextExpanded = !expanded;
        target.classList.toggle("collapsed", expanded);
        button.setAttribute("aria-expanded", String(nextExpanded));
        button.textContent = nextExpanded ? "-" : "+";
        const action = nextExpanded ? "Collapse" : "Expand";
        const targetName = button.getAttribute("aria-label")?.replace(/^(Collapse|Expand)\s+/, "") || "panel";
        button.setAttribute("aria-label", `${action} ${targetName}`);
        button.title = `${action} ${targetName}`;
    });
});
document.getElementById("link-sessions-btn").addEventListener("click", async () => {
    linkMode = !linkMode;
    document.getElementById("lock-sessions-btn").classList.toggle("hidden", !linkMode);
    await fetchSessions();
});
document.getElementById("lock-sessions-btn").addEventListener("click", lockSelectedSessions);
document.getElementById("new-session-btn").addEventListener("click", () => {
    currentSessionId = null;
    planRunning = false;
    planPaused = false;
    renderSessionsList(sessionsCache);
    document.getElementById("project-input").value = "";
    document.getElementById("project-directory-input").value = "";
    document.querySelector('input[name="project-directory-mode"][value="no"]').checked = true;
    updateDirectoryModeNote();
    document.getElementById("agent-output").textContent = "What project are we planning?";
    renderSessionMessages([]);
    renderWorkflowCards(defaultCards);
    setPlanStatus("Start a project to run active cards.");
});

// ============================================================
// V3 — Auto-collapse the Start panel on first project-input keystroke
// ============================================================

function setupStartPanelAutoCollapse() {
    const panel = document.getElementById("start-panel");
    const body = document.getElementById("start-panel-body");
    const toggle = panel?.querySelector('[data-collapse-target="start-panel-body"]');
    const input = document.getElementById("project-input");
    if (!panel || !body || !input) return;

    function collapsePanel() {
        if (panel.classList.contains("is-collapsed")) return;
        panel.classList.add("is-collapsed");
        body.classList.add("hidden");
        if (toggle) {
            toggle.setAttribute("aria-expanded", "false");
            toggle.textContent = "+";
            toggle.title = "Expand Start panel";
            toggle.setAttribute("aria-label", "Expand Start panel");
        }
    }

    function expandPanel() {
        if (!panel.classList.contains("is-collapsed")) return;
        panel.classList.remove("is-collapsed");
        body.classList.remove("hidden");
        if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
            toggle.textContent = "-";
            toggle.title = "Collapse Start panel";
            toggle.setAttribute("aria-label", "Collapse Start panel");
        }
    }

    let collapsedOnce = false;
    input.addEventListener("input", () => {
        if (!collapsedOnce && input.value.trim().length > 0) {
            collapsedOnce = true;
            collapsePanel();
        }
    });

    if (toggle) {
        toggle.addEventListener("click", () => {
            if (panel.classList.contains("is-collapsed")) expandPanel();
            else collapsePanel();
        });
    }
}

// ============================================================
// V4 — Model pills (Primary + Fallback) with mutex selection
// ============================================================

let fallbackModel = "";

function getAvailableModelList() {
    // Pull from the registry payload last rendered. We mirror what
    // renderModels saw (data.modelOptions) into a module-level cache.
    return Array.isArray(modelOptionsCache) ? modelOptionsCache : [];
}

let modelOptionsCache = [];

function renderModelPills(payload) {
    const models = Array.isArray(payload) ? payload : (payload?.modelOptions || []);
    modelOptionsCache = models;
    const primaryHost = document.getElementById("primary-model-pills");
    const fallbackHost = document.getElementById("fallback-model-pills");
    if (!primaryHost || !fallbackHost) return;
    primaryHost.innerHTML = "";
    fallbackHost.innerHTML = "";

    const seen = new Set();
    const list = models.filter(m => {
        const key = (m.ollamaName || m.name || "").trim();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    });

    function makePill(model, kind) {
        const key = normalizeModelName(model.ollamaName || model.name || "");
        const installed = model.installed === undefined ? true : !!model.installed;
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "model-pill";
        pill.dataset.model = key;
        pill.dataset.kind = kind;

        const otherSelected = kind === "primary" ? fallbackModel : selectedModel;
        if (key === otherSelected) pill.classList.add("is-disabled");

        const isActive = (kind === "primary" ? key === selectedModel : key === fallbackModel);
        if (isActive) pill.classList.add("is-active");
        if (kind === "fallback" && isActive) pill.classList.add("is-fallback-active");

        const label = model.label || model.ollamaName || key;
        const meta = [];
        if (model.parameterSize) meta.push(model.parameterSize);
        if (model.family) meta.push(model.family);
        if (!installed) meta.push("not installed");
        const metaText = meta.length ? `<span class="model-pill-meta">${meta.join(" · ")}</span>` : "";
        pill.innerHTML = `<span>${escapeHtml(label)}</span>${metaText}`;

        pill.addEventListener("click", (e) => {
            e.preventDefault();
            if (pill.classList.contains("is-disabled")) return;
            if (kind === "primary") {
                selectedModel = (key === selectedModel) ? "" : key;
                setSelectedModel(selectedModel, true);
            } else {
                fallbackModel = (key === fallbackModel) ? "" : key;
                persistFallbackModel();
            }
            renderModelPills(modelOptionsCache);
            updateActiveModelPillDisplay();
        });
        return pill;
    }

    list.forEach(m => primaryHost.appendChild(makePill(m, "primary")));
    list.forEach(m => fallbackHost.appendChild(makePill(m, "fallback")));
    updateActiveModelPillDisplay();
}

function updateActiveModelPillDisplay() {
    const pill = document.getElementById("active-model-pill");
    if (!pill) return;
    if (selectedModel) {
        pill.textContent = fallbackModel
            ? `Forge Brain: ${selectedModel}  ·  fallback: ${fallbackModel}`
            : `Forge Brain: ${selectedModel}`;
    } else {
        pill.textContent = "Forge Brain: (pick one below)";
    }
}

async function persistFallbackModel() {
    if (!currentSessionId) return;
    try {
        await fetch(`${API_URL}/sessions/${currentSessionId}/model`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fallbackModel })
        });
    } catch (error) {
        console.warn("Could not persist fallback model:", error);
    }
}

// Hook the existing renderModels() so pills update whenever the model
// registry is refreshed.
const _originalRenderModels = renderModels;
renderModels = function patchedRenderModels(models) {
    _originalRenderModels(models);
    renderModelPills(models);
};

// ============================================================
// V6 — Activity stream terminal (SSE)
// ============================================================

function setupEventTerminal() {
    const terminal = document.getElementById("event-terminal");
    const stream = document.getElementById("event-terminal-stream");
    const toggle = document.getElementById("event-terminal-toggle");
    const clear = document.getElementById("event-terminal-clear");
    const statusEl = document.getElementById("event-terminal-status");
    if (!terminal || !stream || !toggle) return;

    const collapsedKey = "gforge.terminal.collapsed";
    const stored = localStorage.getItem(collapsedKey);
    const startCollapsed = stored === null ? true : stored === "1";
    terminal.classList.toggle("collapsed", startCollapsed);
    toggle.textContent = startCollapsed ? "Show" : "Hide";

    toggle.addEventListener("click", () => {
        const isCollapsed = terminal.classList.toggle("collapsed");
        toggle.textContent = isCollapsed ? "Show" : "Hide";
        localStorage.setItem(collapsedKey, isCollapsed ? "1" : "0");
        if (!isCollapsed) stream.scrollTop = stream.scrollHeight;
    });

    if (clear) clear.addEventListener("click", () => { stream.innerHTML = ""; });

    function appendEvent(evt) {
        const row = document.createElement("div");
        const kind = evt.kind || "info";
        row.className = `event-row kind-${kind}`;
        const time = new Date(evt.at || Date.now()).toLocaleTimeString();
        row.innerHTML =
            `<span class="ev-time">${escapeHtml(time)}</span>` +
            `<span class="ev-kind">${escapeHtml(kind)}</span>` +
            `<span class="ev-msg">${escapeHtml(evt.message || "")}</span>`;
        stream.appendChild(row);
        // Cap to ~400 rows so the DOM stays cheap.
        while (stream.children.length > 400) stream.removeChild(stream.firstChild);
        stream.scrollTop = stream.scrollHeight;
    }

    function setStatus(text, ok) {
        if (!statusEl) return;
        statusEl.textContent = text;
        terminal.classList.toggle("disconnected", !ok);
    }

    function connect() {
        let es;
        try {
            es = new EventSource(`${API_URL}/events/stream`);
        } catch (error) {
            setStatus("offline", false);
            return;
        }
        setStatus("connected", true);
        es.onmessage = (msg) => {
            try {
                const evt = JSON.parse(msg.data);
                appendEvent(evt);
            } catch (error) {
                console.warn("bad event payload", error);
            }
        };
        es.onerror = () => {
            setStatus("reconnecting", false);
            try { es.close(); } catch (e) { /* ignore */ }
            setTimeout(connect, 2000);
        };
    }

    connect();
}

window.addEventListener("load", () => {
    loadWorkspace();
    setupStartPanelAutoCollapse();
    setupEventTerminal();
});
