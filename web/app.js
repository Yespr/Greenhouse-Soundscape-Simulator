const soundsTable = document.querySelector("#soundsTable");
const uploadForm = document.querySelector("#uploadForm");
const uploadError = document.querySelector("#uploadError");
const fileInput = document.querySelector("#fileInput");
const fileName = document.querySelector("#fileName");
const engineStatus = document.querySelector("#engineStatus");
const modeSelect = document.querySelector("#modeSelect");
const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const refreshButton = document.querySelector("#refreshButton");
const saveAllButton = document.querySelector("#saveAllButton");
const saveStatus = document.querySelector("#saveStatus");
const allowedUploadExtensions = [".mp3", ".wav", ".ogg"];

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(path, {
    headers: isFormData ? options.headers || {} : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(formatApiError(text) || `${response.status} ${response.statusText}`);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function formatApiError(text) {
  if (!text) return "";
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
  } catch {
    return text;
  }
  return text;
}

function renderEngine(state) {
  const profile = state.active_profile ? `, ${state.active_profile}` : "";
  engineStatus.textContent = `${state.running ? "Running" : "Stopped"} - ${state.mode}${profile}`;
  modeSelect.value = state.mode;
}

function select(value, options) {
  return options
    .map((option) => `<option value="${option}" ${option === value ? "selected" : ""}>${option}</option>`)
    .join("");
}

function percentControl(field, value, disabled = false) {
  const safeValue = Math.max(0, Math.min(100, Number(value)));
  return `
    <div class="percent-control">
      <input data-field="${field}" type="range" min="0" max="100" step="1" value="${safeValue}" ${disabled ? "disabled" : ""}>
      <span class="percent-value" data-percent-value>${safeValue}%</span>
    </div>
  `;
}

function renderSounds(sounds) {
  if (!sounds.length) {
    soundsTable.innerHTML = `
      <tr>
        <td colspan="8" class="empty-state">No sounds configured yet. Upload an audio file to begin.</td>
      </tr>
    `;
    return;
  }

  soundsTable.innerHTML = sounds.map(renderSoundRows).join("");
}

function renderSoundRows(sound) {
  return `
    <tr class="sound-row" data-id="${sound.id}">
      <td><input data-field="enabled" type="checkbox" ${sound.enabled ? "checked" : ""}></td>
      <td class="sound-name">${escapeHtml(sound.name)}</td>
      <td class="path-cell">${escapeHtml(sound.file_path)}</td>
      <td><select data-field="profile">${select(sound.profile, ["day", "evening", "both"])}</select></td>
      <td><select data-field="type">${select(sound.type, ["loop", "random"])}</select></td>
      <td>${percentControl("volume", sound.volume)}</td>
      <td><button type="button" data-action="toggle-advanced" class="secondary">Settings</button></td>
      <td class="actions">
        <button type="button" data-action="test" class="secondary">Test</button>
        <button type="button" data-action="delete" class="danger">Delete</button>
      </td>
    </tr>
    <tr class="advanced-row is-hidden" data-advanced-for="${sound.id}">
      <td colspan="8">
        <div class="advanced-grid">
          <label>
            Min interval
            <input data-field="min_interval_seconds" type="number" min="0" step="1" value="${sound.min_interval_seconds}">
          </label>
          <label>
            Max interval
            <input data-field="max_interval_seconds" type="number" min="0" step="1" value="${sound.max_interval_seconds}">
          </label>
          <label>
            Fade in
            <input data-field="fade_in_seconds" type="number" min="0" step="0.1" value="${sound.fade_in_seconds}">
          </label>
          <label>
            Fade out
            <input data-field="fade_out_seconds" type="number" min="0" step="0.1" value="${sound.fade_out_seconds}">
          </label>
          <label>
            Probability %
            <input data-field="probability" type="number" min="0" max="100" step="1" value="${sound.probability}">
          </label>
          <label>
            Repeat min
            <input data-field="repeat_count_min" type="number" min="1" step="1" value="${sound.repeat_count_min}">
          </label>
          <label>
            Repeat max
            <input data-field="repeat_count_max" type="number" min="1" step="1" value="${sound.repeat_count_max}">
          </label>
          <label>
            Repeat gap
            <input data-field="repeat_gap_seconds" type="number" min="0" step="0.1" value="${sound.repeat_gap_seconds}">
          </label>
          <p class="advanced-help">Repeats are useful for frogs, birds, insects, chirps, geckos, etc.</p>
        </div>
      </td>
    </tr>
  `;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char];
  });
}

function soundPayload(row) {
  const id = row.dataset.id;
  const advancedRow = soundsTable.querySelector(`[data-advanced-for="${id}"]`);
  const payload = {};

  [row, advancedRow].forEach((source) => {
    source.querySelectorAll("[data-field]").forEach((input) => {
      if (input.disabled) return;
      const field = input.dataset.field;
      if (input.type === "checkbox") {
        payload[field] = input.checked;
      } else if (input.type === "number" || input.type === "range") {
        payload[field] = Number(input.value);
      } else {
        payload[field] = input.value;
      }
    });
  });

  return payload;
}

function validateUploadFile(file) {
  const fileName = file?.name || "";
  const extension = fileName.includes(".") ? fileName.slice(fileName.lastIndexOf(".")).toLowerCase() : "";
  return allowedUploadExtensions.includes(extension);
}

async function loadAll() {
  const [sounds, state] = await Promise.all([api("/api/sounds"), api("/api/engine")]);
  renderSounds(sounds);
  renderEngine(state);
  saveStatus.textContent = "";
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  uploadError.textContent = "";

  const form = new FormData(uploadForm);
  const file = form.get("file");

  if (!validateUploadFile(file)) {
    uploadError.textContent = "Invalid file type. Upload an .mp3, .wav, or .ogg file.";
    return;
  }

  try {
    await api("/api/sounds/upload", {
      method: "POST",
      body: form,
    });
    uploadForm.reset();
    fileName.textContent = "No file selected";
    await loadAll();
  } catch (error) {
    uploadError.textContent = error.message;
  }
});

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "No file selected";
});

soundsTable.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  const row = button.closest(".sound-row");
  if (!row) return;

  const id = row.dataset.id;
  const action = button.dataset.action;

  if (action === "toggle-advanced") {
    const advancedRow = soundsTable.querySelector(`[data-advanced-for="${id}"]`);
    advancedRow.classList.toggle("is-hidden");
    button.textContent = advancedRow.classList.contains("is-hidden") ? "Settings" : "Hide";
    return;
  }

  try {
    if (action === "test") {
      const result = await api(`/api/sounds/${id}/test`, { method: "POST" });
      button.textContent = result.repeat_count ? `Preview x${result.repeat_count}` : "Playing";
      window.setTimeout(() => {
        button.textContent = "Test";
      }, 1600);
      return;
    }

    if (action === "delete") {
      await api(`/api/sounds/${id}`, { method: "DELETE" });
    }

    await loadAll();
  } catch (error) {
    uploadError.textContent = error.message;
  }
});

soundsTable.addEventListener("change", async (event) => {
  if (!event.target.dataset.field) return;
  markUnsaved();
});

soundsTable.addEventListener("input", (event) => {
  if (event.target.type !== "range") return;
  const control = event.target.closest(".percent-control");
  const label = control?.querySelector("[data-percent-value]");
  if (label) {
    label.textContent = `${event.target.value}%`;
  }
  markUnsaved();
});

async function saveAllSounds() {
  const rows = [...soundsTable.querySelectorAll(".sound-row")];
  if (!rows.length) return;

  saveAllButton.disabled = true;
  saveStatus.textContent = "Saving...";

  try {
    await Promise.all(
      rows.map((row) =>
        api(`/api/sounds/${row.dataset.id}`, {
          method: "PUT",
          body: JSON.stringify(soundPayload(row)),
        })
      )
    );
    saveStatus.textContent = "Saved";
    await loadAll();
  } catch (error) {
    saveStatus.textContent = "";
    uploadError.textContent = error.message;
  } finally {
    saveAllButton.disabled = false;
  }
}

function markUnsaved() {
  saveStatus.textContent = "Unsaved changes";
}

modeSelect.addEventListener("change", async () => {
  const state = await api("/api/engine/mode", {
    method: "POST",
    body: JSON.stringify({ mode: modeSelect.value }),
  });
  renderEngine(state);
});

startButton.addEventListener("click", async () => {
  renderEngine(await api("/api/engine/start", { method: "POST" }));
});

stopButton.addEventListener("click", async () => {
  renderEngine(await api("/api/engine/stop", { method: "POST" }));
});

refreshButton.addEventListener("click", loadAll);
saveAllButton.addEventListener("click", saveAllSounds);

loadAll().catch((error) => {
  engineStatus.textContent = `Error: ${error.message}`;
});
