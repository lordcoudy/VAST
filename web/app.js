const state = {
  config: null,
  analytics: null,
  jobs: [],
  detail: null,
  activeRunId: "",
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function pathGet(root, path) {
  return path.split(".").reduce((node, part) => (node == null ? undefined : node[part]), root);
}

function pathSet(root, path, value) {
  const parts = path.split(".");
  let node = root;
  for (let i = 0; i < parts.length - 1; i += 1) {
    if (node[parts[i]] === undefined || node[parts[i]] === null) node[parts[i]] = {};
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

function setStatus(message, kind = "") {
  const pill = $("status-pill");
  pill.textContent = message;
  pill.className = `status-pill ${kind}`.trim();
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(node._timer);
  node._timer = window.setTimeout(() => {
    node.hidden = true;
  }, 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      throw new Error(text);
    }
  }
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("project-path").textContent = state.config.paths.experiments.replace(/\/configs\/experiments\.yaml$/, "");
}

async function loadAnalytics() {
  state.analytics = await api("/api/analytics");
  if (!state.activeRunId && state.analytics.latest_run) state.activeRunId = state.analytics.latest_run.run_id;
}

async function loadJobs() {
  const payload = await api("/api/runs");
  state.jobs = payload.jobs || [];
}

async function loadDetail(runId) {
  state.detail = runId ? await api(`/api/analytics/${encodeURIComponent(runId)}`) : null;
}

async function refreshAll() {
  try {
    setStatus("Refreshing");
    await loadConfig();
    await loadAnalytics();
    await loadJobs();
    if (state.activeRunId) await loadDetail(state.activeRunId);
    renderAll();
    setStatus("Ready", "ok");
  } catch (error) {
    setStatus("Error", "error");
    toast(error.message);
  }
}

function sectionTitle(title, subtitle = "", action = "") {
  return `
    <div class="section-title">
      <div>
        <h2>${escapeHtml(title)}</h2>
        ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
      </div>
      <div>${action}</div>
    </div>
  `;
}

function metric(label, value, sub = "", accent = "") {
  return `
    <div class="metric">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value" style="${accent ? `color:${accent}` : ""}">${escapeHtml(value)}</div>
      ${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ""}
    </div>
  `;
}

function keyValueTable(rows) {
  return `
    <div class="table-wrap">
      <table>
        <tbody>
          ${rows.map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value ?? "-")}</td></tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderDashboard() {
  const analytics = state.analytics || {};
  const kpis = analytics.kpis || {};
  const latest = analytics.latest_run || {};
  const experiments = state.config?.configs?.experiments || {};
  const hardware = experiments.hardware_target || {};
  const protocol = experiments.protocol || {};
  $("tab-dashboard").innerHTML = `
    ${sectionTitle("Operational Dashboard", latest.run_id ? `Latest run: ${latest.run_id}` : "No summaries found")}
    <div class="grid kpi">
      ${metric("Runs Indexed", formatNumber(kpis.run_count, 0), "summary.csv files")}
      ${metric("Completed Rows", formatNumber(kpis.completed_rows, 0), "completed run rows")}
      ${metric("Avg Throughput", `${formatNumber(kpis.avg_throughput_fps)} fps`, "completed rows", "#2563eb")}
      ${metric("Avg p95 Latency", `${formatNumber(kpis.avg_latency_p95_ms)} ms`, "completed rows", "#0f766e")}
      ${metric("Avg SLO Violation", `${formatNumber(kpis.avg_slo_violation_rate_percent)}%`, "completed rows", "#b45309")}
    </div>
    <div class="grid two">
      <div class="panel">
        <h3>Hardware Target</h3>
        ${keyValueTable([
          ["GPU", hardware.gpu_model],
          ["CPU", hardware.cpu_model],
          ["RAM GB", hardware.ram_gb],
          ["Deadline s", hardware.deadline_s],
        ])}
      </div>
      <div class="panel">
        <h3>Protocol</h3>
        ${keyValueTable([
          ["Repeats", protocol.repeats],
          ["Warmup s", protocol.warmup_s],
          ["Measurement s", protocol.measurement_s],
          ["Metric interval s", protocol.metric_interval_s],
          ["Custom metric interval s", protocol.custom_cpp_cuda_qt_metric_interval_s],
        ])}
      </div>
    </div>
    <div class="chart-row">
      <div class="panel"><h3>Throughput by System</h3><canvas id="dash-throughput"></canvas></div>
      <div class="panel"><h3>SLO Violation by Scenario</h3><canvas id="dash-slo"></canvas></div>
    </div>
  `;
  const aggregates = analytics.aggregates || [];
  drawGroupedMeanBar("dash-throughput", aggregates, "system", "throughput_fps_mean", "#2563eb");
  drawGroupedMeanBar("dash-slo", aggregates, "scenario", "slo_violation_rate_percent_mean", "#b45309");
}

function inputField(kind, path, label, type = "text") {
  const data = state.config.configs[kind];
  const value = pathGet(data, path);
  return `
    <label>${escapeHtml(label)}
      <input data-bind-kind="${kind}" data-bind-path="${path}" type="${type}" value="${escapeHtml(value ?? "")}">
    </label>
  `;
}

function rawEditor(kind, label) {
  return `
    <div class="panel">
      <div class="section-title">
        <div><h3>${escapeHtml(label)}</h3></div>
        <div>
          <button data-save-kind="${kind}" type="button">Save Typed</button>
          <button data-save-raw="${kind}" type="button">Apply Raw</button>
        </div>
      </div>
      <textarea id="raw-${kind}" spellcheck="false">${escapeHtml(state.config.raw[kind] || "")}</textarea>
    </div>
  `;
}

function renderSettings() {
  const experiments = state.config.configs.experiments;
  const datasets = state.config.configs.datasets;
  const hosts = state.config.configs.hosts;
  const scenarioCards = Object.entries(experiments.scenarios || {}).map(([key, scenario]) => {
    const workload = scenario.workload || {};
    const density = workload.object_density || {};
    const network = scenario.network || {};
    return `
      <div class="item-card">
        <h3>${escapeHtml(key)}</h3>
        <div class="form-grid">
          ${workload.streams !== undefined ? inputField("experiments", `scenarios.${key}.workload.streams`, "Streams", "number") : ""}
          ${density.min !== undefined ? inputField("experiments", `scenarios.${key}.workload.object_density.min`, "Min objects", "number") : ""}
          ${density.max !== undefined ? inputField("experiments", `scenarios.${key}.workload.object_density.max`, "Max objects", "number") : ""}
          ${network.latency_ms !== undefined ? inputField("experiments", `scenarios.${key}.network.latency_ms`, "Latency ms", "number") : ""}
          ${network.packet_loss_percent !== undefined ? inputField("experiments", `scenarios.${key}.network.packet_loss_percent`, "Packet loss %", "number") : ""}
        </div>
        <p class="mono">${escapeHtml((scenario.pipeline || []).join(" -> "))}</p>
      </div>
    `;
  }).join("");

  $("tab-settings").innerHTML = `
    ${sectionTitle("Settings", "Typed controls cover common fields; raw YAML covers the full surface.")}
    <div class="split">
      <div>
        <div class="panel">
          <h3>Protocol</h3>
          <div class="form-grid">
            ${inputField("experiments", "protocol.repeats", "Repeats", "number")}
            ${inputField("experiments", "protocol.warmup_s", "Warmup s", "number")}
            ${inputField("experiments", "protocol.measurement_s", "Measurement s", "number")}
            ${inputField("experiments", "protocol.metric_interval_s", "Metric interval s", "number")}
            ${inputField("experiments", "protocol.custom_cpp_cuda_qt_metric_interval_s", "Custom metric interval s", "number")}
          </div>
        </div>
        <div class="panel">
          <h3>Hardware Target</h3>
          <div class="form-grid">
            ${inputField("experiments", "hardware_target.gpu_model", "GPU model")}
            ${inputField("experiments", "hardware_target.cpu_model", "CPU model")}
            ${inputField("experiments", "hardware_target.ram_gb", "RAM GB", "number")}
            ${inputField("experiments", "hardware_target.deadline_s", "Deadline s", "number")}
          </div>
        </div>
        <div class="panel">
          <h3>Transport</h3>
          <div class="form-grid">
            ${inputField("experiments", "transport.kind", "Kind")}
            ${inputField("experiments", "transport.max_clock_offset_ms", "Max clock offset ms", "number")}
            ${inputField("experiments", "transport.startup_grace_s", "Startup grace s", "number")}
            ${inputField("experiments", "transport.stream_port_stride", "Stream port stride", "number")}
          </div>
        </div>
        <div class="panel">
          <h3>Scenarios</h3>
          <div class="grid">${scenarioCards}</div>
        </div>
      </div>
      <div>
        ${rawEditor("experiments", "Experiments YAML")}
        ${rawEditor("datasets", "Datasets YAML")}
        ${rawEditor("hosts", "Hosts YAML")}
      </div>
    </div>
    <div class="grid two">
      <div class="panel">
        <h3>Datasets</h3>
        <div class="grid">
          ${Object.entries(datasets.datasets || {}).map(([key, dataset]) => `
            <div class="item-card">
              <h3>${escapeHtml(key)}</h3>
              <p>${escapeHtml(dataset.description || "")}</p>
              <span class="badge ${dataset.publishable ? "green" : "amber"}">${dataset.publishable ? "publishable" : "diagnostic"}</span>
              <p>${escapeHtml((dataset.streams || []).length)} streams at ${escapeHtml(dataset.fps || "-")} fps</p>
            </div>
          `).join("")}
        </div>
      </div>
      <div class="panel">
        <h3>Hosts</h3>
        <div class="grid">
          ${(hosts.hosts || []).map((host) => `
            <div class="item-card">
              <h3>${escapeHtml(host.name)}</h3>
              <p class="mono">${escapeHtml(host.user ? `${host.user}@${host.address}:${host.port || 22}` : `${host.address}:${host.port || 22}`)}</p>
              <p>${escapeHtml((host.roles || []).join(", "))}</p>
            </div>
          `).join("") || `<div class="empty">No hosts configured.</div>`}
        </div>
      </div>
    </div>
  `;
  attachSettingsHandlers();
}

function attachSettingsHandlers() {
  document.querySelectorAll("[data-bind-kind]").forEach((input) => {
    input.addEventListener("input", () => {
      let value = input.value;
      if (input.type === "number") value = value === "" ? "" : Number(value);
      pathSet(state.config.configs[input.dataset.bindKind], input.dataset.bindPath, value);
    });
  });
  document.querySelectorAll("[data-save-kind]").forEach((button) => {
    button.addEventListener("click", () => saveConfig(button.dataset.saveKind, { data: state.config.configs[button.dataset.saveKind] }));
  });
  document.querySelectorAll("[data-save-raw]").forEach((button) => {
    button.addEventListener("click", () => saveConfig(button.dataset.saveRaw, { yaml: $(`raw-${button.dataset.saveRaw}`).value }));
  });
}

async function saveConfig(kind, payload) {
  try {
    const saved = await api(`/api/config/${kind}`, { method: "PUT", body: JSON.stringify(payload) });
    state.config.configs[kind] = saved.data;
    state.config.raw[kind] = saved.yaml;
    toast(`${kind} saved; backup ${saved.backup}`);
    renderSettings();
  } catch (error) {
    toast(error.message);
  }
}

function selectField(id, label, values, selected) {
  return `
    <label>${escapeHtml(label)}
      <select id="${id}">
        ${values.map((value) => `<option value="${escapeHtml(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(value)}</option>`).join("")}
      </select>
    </label>
  `;
}

function textField(id, label, type, value) {
  return `
    <label>${escapeHtml(label)}
      <input id="${id}" type="${type}" value="${escapeHtml(value)}">
    </label>
  `;
}

function checkList(name, items, checkAll) {
  return `
    <div class="checkbox-list">
      ${items.map(([key, label], index) => `
        <label class="check-row">
          <input name="${name}" type="checkbox" value="${escapeHtml(key)}" ${checkAll || index === 0 ? "checked" : ""}>
          <span><strong>${escapeHtml(key)}</strong><br><span class="sub">${escapeHtml(label)}</span></span>
        </label>
      `).join("")}
    </div>
  `;
}

function renderPlanner() {
  const selectors = state.config.selectors;
  const defaultPolicy = selectors.policies.includes("static_hybrid") ? "static_hybrid" : selectors.policies[0];
  const defaultDataset = (state.config.configs.experiments.benchmark || {}).default_dataset || {};
  $("tab-planner").innerHTML = `
    ${sectionTitle("Run Planner", "Preview the resolved command before launching experiments.")}
    <div class="grid two">
      <div class="panel">
        <div class="form-grid">
          ${selectField("run-mode", "Mode", selectors.modes, "benchmark")}
          ${selectField("run-dataset", "Dataset", selectors.datasets.map((d) => d.key), defaultDataset.benchmark || selectors.datasets[0]?.key || "")}
          ${selectField("run-policy", "Policy", selectors.policies, defaultPolicy)}
          ${selectField("run-kind", "Run kind", selectors.run_kinds, "auto")}
          ${textField("run-repeats", "Repeats", "number", "1")}
          ${textField("run-warmup", "Warmup s", "number", "0")}
          ${textField("run-measurement", "Measurement s", "number", "30")}
          ${textField("run-output-root", "Output root", "text", "runs")}
          ${textField("run-hosts-config", "Hosts config", "text", "configs/hosts.yaml")}
          ${textField("run-single-host", "Single-server host", "text", "127.0.0.1")}
          ${textField("run-single-port", "Single-server port", "number", "22")}
          ${textField("run-single-user", "Single-server user", "text", "")}
          ${textField("run-seed", "Seed", "number", "")}
          ${textField("run-resume", "Resume run root", "text", "")}
        </div>
        <h3>Systems</h3>
        ${checkList("run-system", selectors.systems.map((item) => [item.key, item.label]), true)}
        <h3>Scenarios</h3>
        ${checkList("run-scenario", selectors.scenarios.map((item) => [item.key, item.description || item.key]), false)}
        <label>Environment overrides
          <textarea id="run-env" spellcheck="false" placeholder="STARTUP_GRACE_S=180"></textarea>
        </label>
        <div class="toolbar">
          <button id="dry-run" type="button">Dry Run Plan</button>
          <button id="start-run" class="primary" type="button">Start Run</button>
          <button id="validate-config" type="button">Validate</button>
        </div>
      </div>
      <div class="panel">
        <h3>Plan Output</h3>
        <pre id="plan-output" class="log">No plan yet.</pre>
      </div>
    </div>
  `;
  $("dry-run").addEventListener("click", dryRunPlan);
  $("start-run").addEventListener("click", startRun);
  $("validate-config").addEventListener("click", validateRun);
}

function selectedValues(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((node) => node.value);
}

function valueOrNull(id) {
  const value = $(id).value.trim();
  return value === "" ? null : value;
}

function runPayload() {
  return {
    mode: $("run-mode").value,
    dataset: $("run-dataset").value,
    policy: $("run-policy").value,
    run_kind: $("run-kind").value,
    systems: selectedValues("run-system"),
    scenarios: selectedValues("run-scenario"),
    repeats: valueOrNull("run-repeats"),
    warmup: valueOrNull("run-warmup"),
    measurement: valueOrNull("run-measurement"),
    output_root: $("run-output-root").value,
    hosts_config: $("run-hosts-config").value,
    single_server_host: $("run-single-host").value,
    single_server_port: valueOrNull("run-single-port"),
    single_server_user: $("run-single-user").value,
    seed: valueOrNull("run-seed"),
    resume_run_root: $("run-resume").value,
    env_overrides: $("run-env").value,
  };
}

async function dryRunPlan() {
  try {
    const payload = await api("/api/runs/dry-run", { method: "POST", body: JSON.stringify(runPayload()) });
    $("plan-output").textContent = [`$ ${payload.command.join(" ")}`, "", payload.stdout || "", payload.stderr ? `stderr:\n${payload.stderr}` : ""].join("\n");
    toast(payload.ok ? "Dry run complete" : "Dry run failed");
  } catch (error) {
    $("plan-output").textContent = error.message;
    toast(error.message);
  }
}

async function validateRun() {
  try {
    const payload = await api("/api/validate", { method: "POST", body: JSON.stringify(runPayload()) });
    toast(payload.message || "Configuration is valid");
  } catch (error) {
    toast(error.message);
  }
}

async function startRun() {
  try {
    const job = await api("/api/runs", { method: "POST", body: JSON.stringify(runPayload()) });
    $("plan-output").textContent = `Started job ${job.id}\n$ ${job.command.join(" ")}`;
    await loadJobs();
    renderJobs();
    toast(`Started job ${job.id}`);
  } catch (error) {
    toast(error.message);
  }
}

function renderJobs() {
  $("tab-jobs").innerHTML = `
    ${sectionTitle("Jobs", `${state.jobs.length} GUI-launched jobs`, `<button id="refresh-jobs" type="button">Refresh</button>`)}
    <div class="grid">
      ${state.jobs.map((job) => jobCard(job)).join("") || `<div class="empty">No GUI-launched jobs.</div>`}
    </div>
  `;
  $("refresh-jobs")?.addEventListener("click", async () => {
    await loadJobs();
    renderJobs();
  });
  document.querySelectorAll("[data-stop-job]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/runs/${encodeURIComponent(button.dataset.stopJob)}/stop`, { method: "POST", body: "{}" });
        await loadJobs();
        renderJobs();
      } catch (error) {
        toast(error.message);
      }
    });
  });
}

function jobCard(job) {
  const badgeClass = job.status === "running" ? "amber" : job.status === "completed" ? "green" : "red";
  return `
    <div class="panel">
      <div class="section-title">
        <div>
          <h3>${escapeHtml(job.kind)} ${escapeHtml(job.id)}</h3>
          <p class="mono">${escapeHtml(job.command.join(" "))}</p>
        </div>
        <div class="toolbar">
          <span class="badge ${badgeClass}">${escapeHtml(job.status)}</span>
          ${job.status === "running" ? `<button class="danger" data-stop-job="${escapeHtml(job.id)}" type="button">Stop</button>` : ""}
        </div>
      </div>
      ${keyValueTable([
        ["Started", job.started_at],
        ["Ended", job.ended_at || "-"],
        ["Exit code", job.exit_code ?? "-"],
        ["Summary", job.summary_path || "-"],
      ])}
      <div class="grid two">
        <div><h3>stdout</h3><pre class="log">${escapeHtml(job.stdout_tail || "")}</pre></div>
        <div><h3>stderr</h3><pre class="log">${escapeHtml(job.stderr_tail || "")}</pre></div>
      </div>
    </div>
  `;
}

function filterSelect(id, label, values) {
  const unique = Array.from(new Set(values.filter(Boolean))).sort();
  return `
    <label>${escapeHtml(label)}
      <select id="${id}">
        <option value="">All</option>
        ${unique.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderStatistics() {
  const rows = state.analytics?.summary_rows || [];
  $("tab-statistics").innerHTML = `
    ${sectionTitle("Statistics", `${rows.length} recent summary rows`)}
    <div class="toolbar">
      ${filterSelect("stat-system", "System", rows.map((row) => row.system))}
      ${filterSelect("stat-scenario", "Scenario", rows.map((row) => row.scenario))}
      ${filterSelect("stat-policy", "Policy", rows.map((row) => row.policy))}
      <button id="apply-stat-filter" type="button">Apply</button>
    </div>
    <div id="stats-table"></div>
  `;
  $("apply-stat-filter").addEventListener("click", drawStatsTable);
  drawStatsTable();
}

function drawStatsTable() {
  const rows = (state.analytics?.summary_rows || []).filter((row) => {
    const system = $("stat-system").value;
    const scenario = $("stat-scenario").value;
    const policy = $("stat-policy").value;
    return (!system || row.system === system) && (!scenario || row.scenario === scenario) && (!policy || row.policy === policy);
  });
  $("stats-table").innerHTML = table(rows.slice(-500).reverse(), [
    "run_id", "status", "scenario", "system", "policy", "dataset", "throughput_fps", "latency_p95_ms", "latency_p99_ms", "slo_violation_rate_percent", "frames",
  ]);
}

function table(rows, columns) {
  if (!rows.length) return `<div class="empty">No rows.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "-")}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderInfographics() {
  const experiments = state.config.configs.experiments;
  const datasets = state.config.configs.datasets.datasets || {};
  const hosts = state.config.configs.hosts.hosts || [];
  const firstScenarioKey = Object.keys(experiments.scenarios || {})[0] || "";
  const firstDatasetKey = Object.keys(datasets)[0] || "";
  $("tab-infographics").innerHTML = `
    ${sectionTitle("Infographics", "Pipeline, topology, dataset, and target views")}
    <div class="grid two">
      <div class="panel">
        <div class="toolbar">${selectField("info-scenario", "Scenario", Object.keys(experiments.scenarios || {}), firstScenarioKey)}</div>
        <div id="pipeline-graphic"></div>
      </div>
      <div class="panel">
        <h3>Host Role Topology</h3>
        <div id="host-graphic"></div>
      </div>
    </div>
    <div class="grid two">
      <div class="panel">
        <div class="toolbar">${selectField("info-dataset", "Dataset", Object.keys(datasets), firstDatasetKey)}</div>
        <div id="dataset-cards"></div>
      </div>
      <div class="panel">
        <h3>Hardware Target</h3>
        ${keyValueTable(Object.entries(experiments.hardware_target || {}))}
      </div>
    </div>
  `;
  $("info-scenario").addEventListener("change", drawPipeline);
  $("info-dataset").addEventListener("change", drawDatasetCards);
  drawPipeline();
  drawHosts(hosts);
  drawDatasetCards();
}

function drawPipeline() {
  const key = $("info-scenario").value;
  const scenario = state.config.configs.experiments.scenarios[key] || {};
  const stages = scenario.pipeline || [];
  const placement = scenario.placement?.stages || {};
  const width = Math.max(720, stages.length * 160);
  const nodes = stages.map((stage, index) => {
    const x = 60 + index * 150;
    const role = placement[stage] || "local";
    return `
      <rect x="${x}" y="95" width="120" height="58" rx="8" fill="#ffffff" stroke="#0f766e"></rect>
      <text x="${x + 60}" y="119" text-anchor="middle" font-size="13" font-weight="700">${escapeHtml(stage)}</text>
      <text x="${x + 60}" y="140" text-anchor="middle" font-size="12" fill="#617073">${escapeHtml(role)}</text>
      ${index < stages.length - 1 ? `<line x1="${x + 120}" y1="124" x2="${x + 150}" y2="124" stroke="#2563eb" stroke-width="2"></line><polygon points="${x + 150},124 ${x + 140},118 ${x + 140},130" fill="#2563eb"></polygon>` : ""}
    `;
  }).join("");
  $("pipeline-graphic").innerHTML = `
    <svg class="infographic" viewBox="0 0 ${width} 250" role="img">
      <text x="24" y="34" font-size="16" font-weight="700">${escapeHtml(key)}</text>
      <text x="24" y="58" font-size="12" fill="#617073">${escapeHtml(scenario.description || "")}</text>
      ${nodes || `<text x="24" y="120" fill="#617073">No pipeline stages.</text>`}
    </svg>
  `;
}

function drawHosts(hosts) {
  const rows = hosts.length ? hosts : [{ name: "localhost", address: "127.0.0.1", roles: ["local"] }];
  const body = rows.map((host, index) => {
    const y = 70 + index * 70;
    return `
      <rect x="34" y="${y}" width="220" height="50" rx="8" fill="#ffffff" stroke="#d7dddc"></rect>
      <text x="48" y="${y + 20}" font-size="13" font-weight="700">${escapeHtml(host.name)}</text>
      <text x="48" y="${y + 40}" font-size="12" fill="#617073">${escapeHtml(host.address)}</text>
      <text x="304" y="${y + 30}" font-size="13">${escapeHtml((host.roles || []).join(", "))}</text>
      <line x1="254" y1="${y + 25}" x2="292" y2="${y + 25}" stroke="#2563eb" stroke-width="2"></line>
    `;
  }).join("");
  $("host-graphic").innerHTML = `<svg class="infographic" viewBox="0 0 760 ${Math.max(240, rows.length * 78 + 60)}">${body}</svg>`;
}

function drawDatasetCards() {
  const key = $("info-dataset").value;
  const dataset = state.config.configs.datasets.datasets[key] || {};
  $("dataset-cards").innerHTML = `
    <div class="grid">
      ${(dataset.streams || []).map((stream, index) => `
        <div class="item-card">
          <h3>Stream ${index + 1}</h3>
          <p class="mono">${escapeHtml(stream.path)}</p>
          <p class="mono">${escapeHtml(stream.sha256 || "no checksum")}</p>
        </div>
      `).join("") || `<div class="empty">No streams.</div>`}
    </div>
  `;
}

function renderAnalytics() {
  const runs = state.analytics?.runs || [];
  $("tab-analytics").innerHTML = `
    ${sectionTitle("Analytics", "Interactive run-level charts")}
    <div class="toolbar">
      ${selectField("analytics-run", "Run", runs.map((run) => run.run_id), state.activeRunId)}
      <button id="load-run-detail" type="button">Load Run Detail</button>
    </div>
    <div class="chart-row">
      <div class="panel"><h3>Throughput by Scenario/System</h3><canvas id="chart-throughput"></canvas></div>
      <div class="panel"><h3>Latency Percentiles</h3><canvas id="chart-latency"></canvas></div>
      <div class="panel"><h3>SLO Heatmap</h3><canvas id="chart-slo"></canvas></div>
      <div class="panel"><h3>CPU/GPU Utilization</h3><canvas id="chart-metrics"></canvas></div>
    </div>
    <div class="grid two">
      <div class="panel"><h3>Stage Timing</h3><div id="stage-table"></div></div>
      <div class="panel"><h3>Network Metrics</h3><div id="network-table"></div></div>
    </div>
  `;
  $("load-run-detail").addEventListener("click", async () => {
    state.activeRunId = $("analytics-run").value;
    await loadDetail(state.activeRunId);
    renderAnalytics();
  });
  const aggregates = state.analytics?.aggregates || [];
  drawGroupedMeanBar("chart-throughput", aggregates, (row) => `${row.scenario}/${row.system}`, "throughput_fps_mean", "#2563eb");
  drawMultiLatency("chart-latency", aggregates);
  drawHeatmap("chart-slo", aggregates, "scenario", "system", "slo_violation_rate_percent_mean");
  drawMetricLines("chart-metrics", state.detail?.system_metrics?.series || []);
  $("stage-table").innerHTML = table((state.detail?.stage_stats || []).slice(0, 200), ["stage", "role", "resource", "events", "duration_ms_mean", "duration_ms_p95", "queue_depth_mean", "path"]);
  $("network-table").innerHTML = table((state.detail?.network_metrics || []).slice(0, 200), ["source_role", "target_role", "latency_ms", "jitter_ms", "packet_loss_percent", "bandwidth_mbps", "clock_offset_ms", "status"]);
}

function renderTools() {
  $("tab-tools").innerHTML = `
    ${sectionTitle("Build / Setup", "Command previews and explicit local tool jobs")}
    <div class="grid two">
      <div class="panel">
        <h3>CMake</h3>
        <label class="check-row"><input id="cmake-native" type="checkbox" checked>Native GStreamer probe</label>
        <label class="check-row"><input id="cmake-plugin" type="checkbox" checked>GStreamer custom plugin</label>
        <label class="check-row"><input id="cmake-cuda" type="checkbox" checked>Custom CUDA + Qt app</label>
        <label>Build target<input id="cmake-target" value=""></label>
        <div class="toolbar">
          <button data-tool-preview="cmake_configure" type="button">Preview Configure</button>
          <button data-tool-start="cmake_configure" type="button">Run Configure</button>
          <button data-tool-preview="cmake_build" type="button">Preview Build</button>
          <button data-tool-start="cmake_build" type="button">Run Build</button>
        </div>
      </div>
      <div class="panel">
        <h3>Utilities</h3>
        <div class="toolbar">
          <button data-tool-preview="check_system" type="button">Preview Check System</button>
          <button data-tool-start="check_system" type="button">Run Check System</button>
          <button data-tool-preview="analyze" type="button">Preview Analyze</button>
          <button data-tool-start="analyze" type="button">Run Analyze</button>
          <button data-tool-preview="prepare_assets" type="button">Preview Assets</button>
          <button data-tool-start="prepare_assets" type="button">Run Assets</button>
        </div>
        <label>Environment overrides<textarea id="tool-env" spellcheck="false"></textarea></label>
      </div>
      <div class="panel">
        <h3>Setup Script Preview</h3>
        <div class="form-grid">
          ${["INSTALL_DOCKER", "INSTALL_GPU_STACK", "INSTALL_OPENVINO", "INSTALL_DEEPSTREAM", "INSTALL_SAVANT", "PREPARE_ASSETS"].map((key) => `
            <label>${key}<select data-setup-flag="${key}"><option value="">default</option><option value="0">0</option><option value="1">1</option></select></label>
          `).join("")}
        </div>
        <pre id="setup-preview" class="log"></pre>
      </div>
      <div class="panel">
        <h3>Tool Output</h3>
        <pre id="tool-output" class="log">No tool command yet.</pre>
      </div>
    </div>
  `;
  document.querySelectorAll("[data-tool-preview]").forEach((button) => button.addEventListener("click", () => previewTool(button.dataset.toolPreview)));
  document.querySelectorAll("[data-tool-start]").forEach((button) => button.addEventListener("click", () => startTool(button.dataset.toolStart)));
  document.querySelectorAll("[data-setup-flag]").forEach((input) => input.addEventListener("change", drawSetupPreview));
  drawSetupPreview();
}

function toolPayload(tool) {
  const payload = { tool, env_overrides: $("tool-env")?.value || "" };
  if (tool === "cmake_configure") {
    payload.cmake_options = {
      VAST_BUILD_NATIVE_GST_PROBE: $("cmake-native").checked,
      VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN: $("cmake-plugin").checked,
      VAST_BUILD_CUSTOM_CUDA_QT: $("cmake-cuda").checked,
    };
  }
  if (tool === "cmake_build") payload.target = $("cmake-target").value;
  return payload;
}

async function previewTool(tool) {
  try {
    const payload = await api("/api/tools/preview", { method: "POST", body: JSON.stringify(toolPayload(tool)) });
    $("tool-output").textContent = `$ ${payload.command.join(" ")}`;
  } catch (error) {
    toast(error.message);
  }
}

async function startTool(tool) {
  try {
    const job = await api("/api/tools", { method: "POST", body: JSON.stringify(toolPayload(tool)) });
    $("tool-output").textContent = `Started job ${job.id}\n$ ${job.command.join(" ")}`;
    await loadJobs();
    renderJobs();
  } catch (error) {
    toast(error.message);
  }
}

function drawSetupPreview() {
  const env = Array.from(document.querySelectorAll("[data-setup-flag]"))
    .filter((node) => node.value)
    .map((node) => `${node.dataset.setupFlag}=${node.value}`)
    .join(" ");
  $("setup-preview").textContent = `${env ? `${env} ` : ""}python3 scripts/setup_target.py`;
}

function prepareCanvas(id) {
  const canvas = $(id);
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, Math.floor(rect.width * dpr));
  canvas.height = Math.max(260, Math.floor(280 * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, 280);
  ctx.font = "12px Inter, sans-serif";
  return { ctx, width: rect.width, height: 280 };
}

function drawGroupedMeanBar(id, rows, keyField, valueField, color) {
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { ctx, width, height } = prepared;
  const getter = typeof keyField === "function" ? keyField : (row) => row[keyField];
  const groups = new Map();
  rows.forEach((row) => {
    const key = getter(row) || "-";
    const value = Number(row[valueField]);
    if (!Number.isFinite(value)) return;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(value);
  });
  const data = Array.from(groups.entries()).map(([key, values]) => [key, values.reduce((a, b) => a + b, 0) / values.length]).slice(0, 16);
  if (!data.length) return drawEmpty(ctx, width, height);
  const max = Math.max(...data.map(([, value]) => value), 1);
  const left = 48;
  const bottom = 48;
  const barW = Math.max(12, (width - left - 20) / data.length - 8);
  ctx.strokeStyle = "#d7dddc";
  ctx.beginPath();
  ctx.moveTo(left, 20);
  ctx.lineTo(left, height - bottom);
  ctx.lineTo(width - 12, height - bottom);
  ctx.stroke();
  data.forEach(([label, value], index) => {
    const h = (value / max) * (height - bottom - 34);
    const x = left + 8 + index * (barW + 8);
    const y = height - bottom - h;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, barW, h);
    ctx.fillStyle = "#1d2528";
    ctx.save();
    ctx.translate(x + barW / 2, height - 32);
    ctx.rotate(-0.55);
    ctx.fillText(String(label).slice(0, 18), 0, 0);
    ctx.restore();
  });
  ctx.fillStyle = "#617073";
  ctx.fillText(formatNumber(max), 8, 24);
}

function drawMultiLatency(id, rows) {
  const data = rows.slice(0, 20).map((row) => ({
    label: `${row.scenario}/${row.system}`,
    p50: Number(row.latency_p50_ms_mean),
    p95: Number(row.latency_p95_ms_mean),
    p99: Number(row.latency_p99_ms_mean),
  })).filter((row) => Number.isFinite(row.p95));
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { ctx, width, height } = prepared;
  if (!data.length) return drawEmpty(ctx, width, height);
  const max = Math.max(...data.flatMap((row) => [row.p50, row.p95, row.p99].filter(Number.isFinite)), 1);
  const colors = { p50: "#15803d", p95: "#2563eb", p99: "#b45309" };
  ["p50", "p95", "p99"].forEach((key, lineIndex) => {
    ctx.strokeStyle = colors[key];
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((row, index) => {
      const x = 44 + index * ((width - 70) / Math.max(1, data.length - 1));
      const y = height - 42 - (row[key] / max) * (height - 72);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      ctx.fillStyle = colors[key];
      ctx.fillRect(x - 2, y - 2, 4, 4);
    });
    ctx.stroke();
    ctx.fillStyle = colors[key];
    ctx.fillText(key, width - 70, 22 + lineIndex * 18);
  });
  ctx.fillStyle = "#617073";
  ctx.fillText(`${formatNumber(max)} ms`, 8, 24);
}

function drawHeatmap(id, rows, xField, yField, valueField) {
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { ctx, width, height } = prepared;
  const xs = Array.from(new Set(rows.map((row) => row[xField]).filter(Boolean))).slice(0, 8);
  const ys = Array.from(new Set(rows.map((row) => row[yField]).filter(Boolean))).slice(0, 8);
  if (!xs.length || !ys.length) return drawEmpty(ctx, width, height);
  const values = rows.map((row) => Number(row[valueField])).filter(Number.isFinite);
  const max = Math.max(...values, 1);
  const left = 110;
  const top = 30;
  const cellW = (width - left - 12) / xs.length;
  const cellH = (height - top - 34) / ys.length;
  ys.forEach((y, yi) => {
    ctx.fillStyle = "#1d2528";
    ctx.fillText(String(y).slice(0, 14), 8, top + yi * cellH + cellH / 2);
    xs.forEach((x, xi) => {
      const found = rows.find((row) => row[xField] === x && row[yField] === y);
      const value = found ? Number(found[valueField]) : 0;
      const alpha = Math.max(0.12, Math.min(0.85, value / max));
      ctx.fillStyle = `rgba(180, 83, 9, ${alpha})`;
      ctx.fillRect(left + xi * cellW, top + yi * cellH, cellW - 2, cellH - 2);
      ctx.fillStyle = "#111827";
      ctx.fillText(formatNumber(value, 1), left + xi * cellW + 6, top + yi * cellH + cellH / 2);
    });
  });
  xs.forEach((x, xi) => {
    ctx.save();
    ctx.translate(left + xi * cellW + 4, height - 12);
    ctx.rotate(-0.45);
    ctx.fillStyle = "#617073";
    ctx.fillText(String(x).slice(0, 14), 0, 0);
    ctx.restore();
  });
}

function drawMetricLines(id, rows) {
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { ctx, width, height } = prepared;
  const data = rows.filter((row) => row.timestamp_ms !== undefined).slice(-300);
  if (!data.length) return drawEmpty(ctx, width, height);
  drawLine(ctx, data, "cpu_total_percent", "#15803d", width, height, 100, "CPU");
  drawLine(ctx, data, "gpu_util_percent", "#2563eb", width, height, 100, "GPU", 18);
}

function drawLine(ctx, rows, field, color, width, height, max, label, offset = 0) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  rows.forEach((row, index) => {
    const value = Number(row[field]);
    if (!Number.isFinite(value)) return;
    const x = 42 + index * ((width - 62) / Math.max(1, rows.length - 1));
    const y = height - 38 - (value / max) * (height - 68);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fillText(label, width - 70, 22 + offset);
}

function drawEmpty(ctx, width, height) {
  ctx.fillStyle = "#617073";
  ctx.fillText("No data", width / 2 - 22, height / 2);
}

function renderAll() {
  if (!state.config || !state.analytics) return;
  renderDashboard();
  renderSettings();
  renderPlanner();
  renderJobs();
  renderStatistics();
  renderInfographics();
  renderAnalytics();
  renderTools();
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((node) => node.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      $(`tab-${button.dataset.tab}`).classList.add("active");
    });
  });
}

window.addEventListener("resize", () => {
  if (state.config && state.analytics) {
    renderDashboard();
    renderAnalytics();
  }
});

$("refresh-all").addEventListener("click", refreshAll);
initTabs();
refreshAll();
window.setInterval(async () => {
  try {
    await loadJobs();
    renderJobs();
  } catch (_error) {
    // Keep the UI usable if a transient refresh fails.
  }
}, 6000);
