const ui = {
  state: null,
  plan: null,
  api: null,
  initialized: false
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;"
  }[char]));
}

function showToast(message, error = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.className = "toast", 3500);
}

function setText(id, value) {
  $(id).textContent = value ?? "";
}

function setBusy(button, busy, busyText = "Working...") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function formatPath(value) {
  return String(value || "").replaceAll("\\", "/");
}

function addMessage(sender, text, user = false, citations = []) {
  const card = document.createElement("article");
  card.className = `message${user ? " user" : ""}`;
  const head = document.createElement("div");
  head.className = "message-head";
  head.textContent = sender;
  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text || "";
  card.append(head, body);
  if (citations && citations.length) {
    const sources = document.createElement("div");
    sources.className = "sources";
    sources.append(document.createTextNode("Sources: "));
    citations.forEach((source, index) => {
      const button = document.createElement("button");
      button.textContent = `[${index + 1}] ${source.file_path || "source"}`;
      button.onclick = () => ui.api.open_path(source.file_path);
      sources.append(button);
    });
    card.append(sources);
  }
  $("chat-messages").append(card);
  $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
}

function renderRecent(recent) {
  const target = $("recent-vaults");
  target.replaceChildren();
  if (!recent || !recent.length) {
    target.innerHTML = '<span class="muted">No recent vaults.</span>';
    return;
  }
  recent.forEach((vault) => {
    const button = document.createElement("button");
    button.className = "recent-item";
    button.textContent = vault.absolute_path || vault.display_name || "Vault";
    button.onclick = () => openVault(button.textContent);
    target.append(button);
  });
}

function renderState(state) {
  ui.state = state;
  if (!state.open) {
    $("welcome").classList.remove("hidden");
    $("app").classList.add("hidden");
    renderRecent(state.recent || []);
    setText("welcome-status", "");
    return;
  }
  $("welcome").classList.add("hidden");
  $("app").classList.remove("hidden");
  setText("vault-name", state.vault.name);
  setText("vault-path", state.vault.path);
  setText("vault-stats", `${state.files} files · ${state.cached_passages} cached passages`);
  const status = $("llm-status");
  status.textContent = state.llm_online ? `${state.model} online` : `${state.model} offline`;
  status.classList.toggle("offline", !state.llm_online);
  const scope = $("scope-select");
  const current = state.scope || "";
  scope.replaceChildren(new Option("Entire vault", ""));
  (state.scopes || []).forEach((value) => scope.add(new Option(value, value)));
  scope.value = current;
  loadSettings();
  loadDatasets();
}

async function openVault(path) {
  if (!path) return;
  setText("welcome-status", "Opening vault...");
  try {
    await runJob("open_vault", { path }, (result) => {
      renderState(result);
      addMessage("Context Vault", `Opened ${result.vault.name}. The active evidence scope is ${result.scope || "the entire vault"}.`);
    });
  } catch (error) {
    setText("welcome-status", error.message);
  }
}

async function selectFolder() {
  try {
    const path = await ui.api.select_folder();
    if (path) await openVault(path);
  } catch (error) {
    setText("welcome-status", error.message);
  }
}

async function runJob(action, payload, onDone, onProgress) {
  const response = await ui.api.start_job(action, payload || {});
  const jobId = response.job_id;
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await ui.api.job_status(jobId);
        if (onProgress && status.message) onProgress(status.message);
        if (status.status === "done") {
          window.clearInterval(timer);
          if (onDone) onDone(status.result);
          resolve(status.result);
        } else if (status.status === "error" || status.status === "missing") {
          window.clearInterval(timer);
          const error = new Error(status.error || "Job failed");
          showToast(error.message, true);
          reject(error);
        }
      } catch (error) {
        window.clearInterval(timer);
        showToast(error.message, true);
        reject(error);
      }
    };
    const timer = window.setInterval(poll, 250);
    poll();
  });
}

function navigate(page) {
  document.querySelectorAll(".page").forEach((item) => item.classList.toggle("active", item.id === `page-${page}`));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === page));
  const label = document.querySelector(`.nav-item[data-page="${page}"]`);
  setText("page-title", label ? label.textContent : page);
  if (page === "audit") loadAudit();
  if (page === "generate") loadDatasets();
}

async function sendChat(query) {
  query = query.trim();
  if (!query) return;
  addMessage("You", query, true);
  $("chat-input").value = "";
  const button = document.querySelector("#chat-form button");
  setBusy(button, true, "Working...");
  try {
    await runJob("ask", { query }, (result) => {
      const label = ui.state?.model || "Context Vault";
      addMessage(label, result.content || result.answer || JSON.stringify(result), false, result.citations || []);
      if (result.result_type === "organisation_plan" && result.data?.plan) {
        ui.plan = result.data.plan;
        showToast("Organisation plan is ready in the Organise view.");
      }
    });
  } finally {
    setBusy(button, false);
  }
}

async function performSearch(event) {
  event.preventDefault();
  const query = $("search-input").value.trim();
  if (!query) return;
  setText("search-status", "Searching the active scope...");
  $("search-results").replaceChildren();
  try {
    const results = await runJob("search", { query });
    setText("search-status", `${results.length} result${results.length === 1 ? "" : "s"}`);
    if (!results.length) {
      $("search-results").innerHTML = '<div class="result-card">No matching files found in this scope.</div>';
      return;
    }
    results.forEach((result) => {
      const card = document.createElement("article");
      card.className = "result-card";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = result.filename || result.relative_path;
      const path = document.createElement("span");
      path.textContent = `${formatPath(result.relative_path)} · score ${Number(result.score || 0).toFixed(2)}`;
      const snippet = document.createElement("p");
      snippet.textContent = result.snippet || "";
      content.append(title, path, snippet);
      const open = document.createElement("button");
      open.className = "secondary";
      open.textContent = "Open";
      open.onclick = () => ui.api.open_path(result.relative_path);
      card.append(content, open);
      $("search-results").append(card);
    });
  } catch (error) {
    setText("search-status", error.message);
  }
}

function organisationRules() {
  const grouping = $("organisation-grouping").value;
  const semantic = grouping === "subject" || grouping === "custom";
  return {
    strategy: semantic ? "semantic" : "deterministic",
    primary_grouping: grouping,
    custom_parameter: grouping === "custom" ? $("custom-rule").value.trim() : null,
    max_depth: Number($("organisation-depth").value),
    preserve_existing: $("preserve-existing").checked
  };
}

async function previewOrganisation() {
  const button = $("preview-organisation");
  setBusy(button, true, "Planning...");
  setText("organisation-status", "Analysing files in the active scope...");
  try {
    ui.plan = await runJob("organise_preview", { rules: organisationRules() });
    renderOrganisationPlan(ui.plan);
    setText("organisation-status", "Review the plan before applying it.");
  } finally {
    setBusy(button, false);
  }
}

function renderOrganisationPlan(plan) {
  const operations = plan?.operations || [];
  const directories = plan?.directories_to_create || [];
  $("organisation-summary").classList.remove("hidden");
  setText("organisation-summary", `${operations.length} files to move · ${directories.length} directories to create${plan?.warnings?.length ? ` · ${plan.warnings.length} warning(s)` : ""}`);
  const wrapper = $("organisation-plan");
  wrapper.replaceChildren();
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Source</th><th>Destination</th><th>Reason</th></tr></thead>";
  const body = document.createElement("tbody");
  operations.forEach((operation) => {
    const row = document.createElement("tr");
    [operation.source, operation.destination, operation.reason].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value || "";
      row.append(cell);
    });
    body.append(row);
  });
  table.append(body);
  wrapper.append(table);
  $("apply-organisation").classList.toggle("hidden", !operations.length);
}

async function applyOrganisation() {
  if (!ui.plan) return;
  if (!window.confirm(`Apply ${ui.plan.operations?.length || 0} verified file moves?`)) return;
  setText("organisation-status", "Applying hash-verified operations...");
  try {
    const result = await runJob("organise_apply", { plan: ui.plan });
    showToast(`Applied ${result.length} operation(s).`);
    ui.plan = null;
    $("apply-organisation").classList.add("hidden");
    renderOrganisationPlan({ operations: [], directories_to_create: [] });
    setText("organisation-status", "Organisation complete.");
    await refreshState();
  } catch (error) {
    setText("organisation-status", error.message);
  }
}

function renderDuplicateGroup(title, groups) {
  const section = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>File</th><th>Path</th><th>Details</th></tr></thead>";
  const body = document.createElement("tbody");
  (groups || []).forEach((group) => {
    (group.files || []).forEach((file) => {
      const row = document.createElement("tr");
      [file.filename, file.relative_path, group.hash || group.reason || ""].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value || "";
        row.append(cell);
      });
      body.append(row);
    });
  });
  if (!body.children.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="3">None found.</td>';
    body.append(row);
  }
  table.append(body);
  section.append(table);
  return section;
}

async function detectDuplicates() {
  const button = $("detect-duplicates");
  setBusy(button, true, "Scanning...");
  setText("duplicates-status", "Checking the active scope...");
  try {
    const result = await runJob("duplicates", {});
    const target = $("duplicates-content");
    target.replaceChildren(renderDuplicateGroup("Exact duplicates", result.exact), renderDuplicateGroup("Probable versions", result.versions));
    setText("duplicates-status", "Detection complete.");
  } finally {
    setBusy(button, false);
  }
}

async function loadDatasets() {
  if (!ui.api || !ui.state?.open) return;
  try {
    const datasets = await ui.api.datasets();
    const select = $("dataset-select");
    select.replaceChildren(new Option(datasets.length ? "Select a dataset" : "No datasets found", ""));
    datasets.forEach((path) => select.add(new Option(path, path)));
  } catch (error) {
    showToast(error.message, true);
  }
}

async function generateAsset() {
  const button = $("generate-asset");
  setBusy(button, true, "Generating...");
  setText("generation-status", "Building scoped evidence and generating the artifact...");
  try {
    const result = await runJob("generate", {
      asset_type: $("asset-type").value,
      topic: $("asset-topic").value,
      count: Number($("asset-count").value)
    });
    renderOutput(result, "Artifact generated");
    setText("generation-status", "Artifact generated successfully.");
  } finally {
    setBusy(button, false);
  }
}

async function generateChart() {
  const path = $("dataset-select").value;
  if (!path) {
    showToast("Select a dataset first.", true);
    return;
  }
  const button = $("generate-chart");
  setBusy(button, true, "Plotting...");
  try {
    const result = await runJob("chart", { relative_path: path, chart_type: $("chart-type").value, title: $("chart-title").value });
    renderOutput(result, "Chart generated");
    setText("generation-status", "Chart generated successfully.");
  } finally {
    setBusy(button, false);
  }
}

function renderOutput(value, title) {
  const target = $("generation-output");
  target.replaceChildren();
  const heading = document.createElement("strong");
  heading.textContent = title;
  const content = document.createElement("pre");
  content.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  target.append(heading, content);
}

async function loadAudit() {
  if (!ui.state?.open) return;
  try {
    const rows = await ui.api.audit();
    const wrapper = $("audit-table");
    wrapper.replaceChildren();
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>Time</th><th>Operation</th><th>Source</th><th>Destination</th><th>Status</th><th></th></tr></thead>";
    const body = document.createElement("tbody");
    rows.forEach((operation) => {
      const row = document.createElement("tr");
      [operation.timestamp, operation.operation_type, operation.source_path, operation.destination_path || "-", operation.status].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value || "";
        row.append(cell);
      });
      const action = document.createElement("td");
      const button = document.createElement("button");
      button.className = "secondary";
      button.textContent = "Undo";
      button.onclick = async () => {
        if (!window.confirm("Undo this operation?")) return;
        await ui.api.undo_operation(operation.operation_id);
        loadAudit();
      };
      action.append(button);
      row.append(action);
      body.append(row);
    });
    table.append(body);
    wrapper.append(table);
    setText("audit-status", `${rows.length} operation(s)`);
  } catch (error) {
    setText("audit-status", error.message);
  }
}

async function loadSettings() {
  if (!ui.api) return;
  const settings = await ui.api.settings();
  $("setting-url").value = settings.ollama_base_url;
  $("setting-model").value = settings.ollama_model;
  $("setting-temperature").value = settings.temperature;
  $("setting-candidates").value = settings.retrieval_max_candidates;
  $("setting-generated").value = settings.generated_output_folder;
}

async function saveSettings() {
  const values = {
    ollama_base_url: $("setting-url").value,
    ollama_model: $("setting-model").value,
    temperature: $("setting-temperature").value,
    retrieval_max_candidates: $("setting-candidates").value,
    generated_output_folder: $("setting-generated").value
  };
  try {
    await ui.api.save_settings(values);
    setText("settings-status", "Settings saved.");
    await refreshState();
  } catch (error) {
    setText("settings-status", error.message);
  }
}

async function refreshState() {
  renderState(await ui.api.boot());
}

function bindEvents() {
  $("select-folder").onclick = selectFolder;
  $("change-vault").onclick = () => { renderState({ open: false, recent: [] }); selectFolder(); };
  $("prepare-vault").onclick = async () => {
    const button = $("prepare-vault");
    setBusy(button, true, "Preparing...");
    try {
      await runJob("prepare", {}, () => refreshState(), (message) => setText("prepare-status", message));
      setText("prepare-status", "Preparation complete.");
    } finally {
      setBusy(button, false);
    }
  };
  document.querySelectorAll(".nav-item").forEach((button) => button.onclick = () => navigate(button.dataset.page));
  $("scope-select").onchange = async (event) => renderState(await ui.api.set_scope(event.target.value));
  $("chat-form").onsubmit = (event) => { event.preventDefault(); sendChat($("chat-input").value); };
  document.querySelectorAll(".quick-actions button").forEach((button) => button.onclick = () => sendChat(button.dataset.query));
  $("search-form").onsubmit = performSearch;
  $("organisation-grouping").onchange = (event) => $("custom-rule-wrap").classList.toggle("hidden", event.target.value !== "custom");
  $("preview-organisation").onclick = previewOrganisation;
  $("apply-organisation").onclick = applyOrganisation;
  $("detect-duplicates").onclick = detectDuplicates;
  $("generate-asset").onclick = generateAsset;
  $("generate-chart").onclick = generateChart;
  $("refresh-audit").onclick = loadAudit;
  $("undo-last-batch").onclick = async () => {
    if (!window.confirm("Undo the last batch?")) return;
    await ui.api.undo_last_batch();
    loadAudit();
  };
  $("save-settings").onclick = saveSettings;
  $("refresh-models").onclick = async () => {
    try {
      const models = await ui.api.installed_models($("setting-url").value);
      setText("settings-status", models.length ? `Installed: ${models.join(", ")}` : "No installed models found.");
    } catch (error) {
      setText("settings-status", error.message);
    }
  };
  $("test-ollama").onclick = async () => {
    try {
      const models = await ui.api.installed_models($("setting-url").value);
      setText("settings-status", `Connected. ${models.length} model(s) available.`);
    } catch (error) {
      setText("settings-status", error.message);
    }
  };
}

async function initialize() {
  if (ui.initialized || !window.pywebview) return;
  ui.initialized = true;
  ui.api = window.pywebview.api;
  bindEvents();
  try {
    renderState(await ui.api.boot());
  } catch (error) {
    setText("welcome-status", error.message);
  }
}

window.addEventListener("pywebviewready", initialize);
