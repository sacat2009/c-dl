const form = document.querySelector("#downloadForm");
const urlInput = document.querySelector("#url");
const modeInput = document.querySelector("#mode");
const qualityInput = document.querySelector("#quality");
const pasteButton = document.querySelector("#pasteButton");
const chooseFolder = document.querySelector("#chooseFolder");
const downloadDir = document.querySelector("#downloadDir");
const message = document.querySelector("#message");
const infoCard = document.querySelector("#infoCard");
const progressBar = document.querySelector("#progressBar");
const phase = document.querySelector("#phase");
const percent = document.querySelector("#percent");
const speed = document.querySelector("#speed");
const logs = document.querySelector("#logs");
const jobQueue = document.querySelector("#jobQueue");
const refreshDownloads = document.querySelector("#refreshDownloads");
const downloadList = document.querySelector("#downloadList");
const downloadStats = document.querySelector("#downloadStats");
const themeToggle = document.querySelector("#themeToggle");
const choiceGroups = document.querySelectorAll(".choice-group");
const qualityGroup = document.querySelector('.choice-group[data-choice="quality"]');
const qualityLegend = document.querySelector("#qualityLegend");

let activeJob = "";
let pollTimer = 0;
let analyzeTimer = 0;
let lastAnalyzedUrl = "";
let videoQuality = "best";
let audioQuality = "192";
const jobIds = [];
const jobStates = new Map();

const videoQualityOptions = [
  ["best", "最佳可用"],
  ["1080", "最高 1080p"],
  ["720", "最高 720p"],
  ["small", "小檔案 480p"],
];

const audioQualityOptions = [
  ["320", "320 kbps"],
  ["192", "192 kbps"],
  ["128", "128 kbps"],
];

function applyTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  localStorage.setItem("cdl-theme", nextTheme);
}

function initTheme() {
  const forced = new URLSearchParams(window.location.search).get("theme");
  const saved = localStorage.getItem("cdl-theme");
  applyTheme(forced || saved || "dark");
}

function initChoices() {
  choiceGroups.forEach((group) => {
    const target = document.querySelector(`#${group.dataset.choice}`);
    group.addEventListener("click", (event) => {
      const option = event.target.closest(".choice-option");
      if (!option || !target) return;
      const name = group.dataset.choice;
      if (name === "mode") {
        setChoiceValue("mode", option.dataset.value);
        renderQualityChoices();
        saveSetting("mode", option.dataset.value).catch((error) => setMessage(error.message, "error"));
        return;
      }
      if (name === "quality" && modeInput.value === "audio") {
        audioQuality = option.dataset.value;
        setChoiceValue("quality", audioQuality);
        saveSetting("audio_quality", audioQuality).catch((error) => setMessage(error.message, "error"));
        return;
      }
      if (name === "quality") {
        videoQuality = option.dataset.value;
        setChoiceValue("quality", videoQuality);
        saveSetting("quality", videoQuality).catch((error) => setMessage(error.message, "error"));
      }
    });
  });
}

function setChoiceValue(name, value) {
  const target = document.querySelector(`#${name}`);
  const group = document.querySelector(`.choice-group[data-choice="${name}"]`);
  if (!target || !group) return;
  target.value = value;
  group.querySelectorAll(".choice-option").forEach((item) => {
    item.classList.toggle("active", item.dataset.value === value);
  });
}

function renderQualityChoices() {
  if (!qualityGroup) return;
  const isAudio = modeInput.value === "audio";
  const options = isAudio ? audioQualityOptions : videoQualityOptions;
  qualityLegend.textContent = isAudio ? "音質" : "畫質";
  qualityGroup.innerHTML = options.map(([value, label]) => `
    <button class="choice-option" type="button" data-value="${value}">${label}</button>
  `).join("");
  setChoiceValue("quality", isAudio ? audioQuality : videoQuality);
}

function initWindowControls() {
  document.querySelector("#minimizeWindow")?.addEventListener("click", () => window.cdl?.minimize?.());
  document.querySelector("#maximizeWindow")?.addEventListener("click", () => window.cdl?.maximize?.());
  document.querySelector("#closeWindow")?.addEventListener("click", () => window.cdl?.close?.());
}

function setMessage(text, type = "") {
  message.textContent = text;
  message.className = `message ${type}`.trim();
}

async function api(path, payload, method = "POST") {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (payload) options.body = JSON.stringify(payload);
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "操作失敗。");
  }
  return data;
}

async function saveSetting(key, value) {
  if (!["mode", "quality", "audio_quality"].includes(key)) return;
  await api("/api/settings", { [key]: value });
}

function isLikelyUrl(value) {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function secondsToText(value) {
  if (!value) return "未知長度";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  if (hours) return `${hours} 小時 ${minutes} 分 ${seconds} 秒`;
  return `${minutes} 分 ${seconds} 秒`;
}

function renderInfo(info) {
  const thumbnailUrl = safeHttpUrl(info.thumbnail);
  const thumbnail = thumbnailUrl
    ? `<img src="${escapeHtml(thumbnailUrl)}" alt="">`
    : `<div class="empty">沒有縮圖</div>`;
  const playlistLine = info.playlist_count
    ? `<p>播放清單：${Number(info.playlist_count).toLocaleString("zh-Hant")} 部影片</p>`
    : "";
  infoCard.innerHTML = `
    <p class="section-title">連結資訊</p>
    <div class="video-info">
      ${thumbnail}
      <div>
        <h2>${escapeHtml(info.title)}</h2>
        <p>來源：${escapeHtml(info.uploader)}</p>
        <p>長度：${secondsToText(info.duration)}</p>
        ${playlistLine}
        <p>解析器：${escapeHtml(info.extractor || "yt-dlp")}</p>
      </div>
    </div>
  `;
}

function safeHttpUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["http:", "https:"].includes(url.protocol) ? url.toString() : "";
  } catch {
    return "";
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function payload() {
  return {
    url: urlInput.value.trim(),
    mode: modeInput.value,
    quality: modeInput.value === "audio" ? audioQuality : videoQuality,
  };
}

async function loadSettings() {
  const data = await api("/api/settings", null, "GET");
  downloadDir.value = data.settings.download_dir || "";
  videoQuality = ["best", "1080", "720", "small"].includes(data.settings.quality) ? data.settings.quality : "best";
  audioQuality = ["128", "192", "320"].includes(String(data.settings.audio_quality)) ? String(data.settings.audio_quality) : "192";
  setChoiceValue("mode", data.settings.mode || "video");
  renderQualityChoices();
}

async function chooseDownloadFolder() {
  try {
    let selected = "";
    if (window.cdl?.selectDownloadFolder) {
      selected = await window.cdl.selectDownloadFolder(downloadDir.value);
    } else {
      selected = prompt("請輸入下載資料夾路徑", downloadDir.value) || "";
    }
    if (!selected) return;
    const data = await api("/api/settings", { download_dir: selected });
    downloadDir.value = data.settings.download_dir;
    setMessage("下載位置已更新。", "ok");
    await loadDownloads();
  } catch (error) {
    setMessage(error.message, "error");
  }
}

async function autoAnalyze(force = false) {
  const url = urlInput.value.trim();
  if (!isLikelyUrl(url)) return;
  if (!force && url === lastAnalyzedUrl) return;
  lastAnalyzedUrl = url;
  try {
    setMessage("正在讀取連結...");
    const data = await api("/api/info", payload());
    renderInfo(data.info);
    setMessage("連結已讀取。", "ok");
  } catch (error) {
    setMessage(error.message, "error");
  }
}

function scheduleAnalyze(force = false) {
  clearTimeout(analyzeTimer);
  analyzeTimer = setTimeout(() => autoAnalyze(force), 650);
}

function updateProgress(job) {
  const value = Number(job.progress || 0);
  progressBar.style.width = `${Math.max(0, Math.min(100, value))}%`;
  phase.textContent = job.phase || "處理中";
  percent.textContent = `${value.toFixed(value % 1 ? 1 : 0)}%`;
  const details = [job.downloaded && job.total ? `${job.downloaded} / ${job.total}` : "", job.speed, job.eta ? `剩餘 ${job.eta}` : ""]
    .filter(Boolean)
    .join(" · ");
  speed.textContent = details;
  logs.textContent = (job.logs || []).join("\n");
  logs.scrollTop = logs.scrollHeight;
}

function jobStatusText(job) {
  if (job.status === "finished") return "完成";
  if (job.status === "error") return "失敗";
  if (job.status === "processing") return "處理";
  if (job.status === "downloading") return `${Number(job.progress || 0).toFixed(0)}%`;
  return job.phase || "等待";
}

function renderQueue() {
  if (!jobIds.length) {
    jobQueue.innerHTML = "";
    return;
  }
  jobQueue.innerHTML = `
    <div class="queue-title">下載佇列</div>
    ${jobIds.slice().reverse().map((id) => {
      const job = jobStates.get(id) || { id, status: "queued", phase: "排隊中", progress: 0 };
      const title = job.title || job.filename?.split(/[\\/]/).pop() || `工作 ${id}`;
      const active = id === activeJob ? " active" : "";
      const state = job.status === "error" ? " error" : job.status === "finished" ? " done" : "";
      return `
        <button class="queue-item${active}${state}" type="button" data-job-id="${id}">
          <span>${escapeHtml(title)}</span>
          <strong>${escapeHtml(jobStatusText(job))}</strong>
        </button>
      `;
    }).join("")}
  `;
}

async function fetchJob(id) {
  const response = await fetch(`/api/job?id=${encodeURIComponent(id)}`);
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "讀取進度失敗。");
  jobStates.set(id, data.job);
  if (id === activeJob) updateProgress(data.job);
  return data.job;
}

async function pollJobs() {
  if (!jobIds.length) return;
  const jobs = await Promise.all(jobIds.map((id) => fetchJob(id).catch((error) => ({ id, status: "error", phase: "讀取失敗", error: error.message }))));
  renderQueue();
  const running = jobs.some((job) => !["finished", "error"].includes(job.status));
  if (!running) {
    clearInterval(pollTimer);
    await loadDownloads();
  }
}

async function loadDownloads() {
  const response = await fetch("/api/downloads");
  const data = await response.json();
  if (!data.ok) return;
  downloadStats.textContent = `累積下載 ${Number(data.download_count || 0).toLocaleString("zh-Hant")} 次`;
  if (!data.items.length) {
    downloadList.innerHTML = `<div class="empty">目前沒有下載檔案。</div>`;
    return;
  }
  downloadList.innerHTML = data.items.map((item) => `
    <div class="download-item">
      <div>
        <button class="file-link" type="button" data-open-file="${escapeHtml(item.name)}">${escapeHtml(item.name)}</button>
      </div>
      <span>${escapeHtml(item.size)}</span>
    </div>
  `).join("");
}

downloadList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-open-file]");
  if (!button) return;
  event.preventDefault();
  try {
    await api("/api/open-file", { name: button.dataset.openFile });
    setMessage("已用系統預設程式開啟檔案。", "ok");
  } catch (error) {
    setMessage(error.message, "error");
  }
});

pasteButton.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      urlInput.value = text.trim();
      scheduleAnalyze(true);
    }
  } catch {
    setMessage("無法讀取剪貼簿，請手動貼上。", "error");
  }
});

urlInput.addEventListener("input", () => scheduleAnalyze(false));
urlInput.addEventListener("change", () => scheduleAnalyze(true));
chooseFolder.addEventListener("click", chooseDownloadFolder);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    if (!isLikelyUrl(urlInput.value)) {
      setMessage("請先貼上完整連結。", "error");
      return;
    }
    setMessage("正在建立下載工作...");
    progressBar.style.width = "0%";
    phase.textContent = "排隊中";
    percent.textContent = "0%";
    speed.textContent = "";
    logs.textContent = "";
    const data = await api("/api/download", payload());
    activeJob = data.job_id;
    jobIds.push(data.job_id);
    jobStates.set(data.job_id, { id: data.job_id, status: "queued", phase: "排隊中", progress: 0 });
    renderQueue();
    setMessage("已加入下載佇列，可以直接貼下一個連結。", "ok");
    urlInput.value = "";
    lastAnalyzedUrl = "";
    infoCard.innerHTML = `<p class="section-title">連結資訊</p><div class="empty">貼上連結後會自動讀取。</div>`;
    clearInterval(pollTimer);
    pollTimer = setInterval(() => pollJobs().catch((error) => setMessage(error.message, "error")), 900);
    await pollJobs();
  } catch (error) {
    setMessage(error.message, "error");
  }
});

jobQueue.addEventListener("click", (event) => {
  const item = event.target.closest(".queue-item");
  if (!item) return;
  activeJob = item.dataset.jobId;
  const job = jobStates.get(activeJob);
  if (job) updateProgress(job);
  renderQueue();
});

refreshDownloads.addEventListener("click", loadDownloads);
themeToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme;
  applyTheme(current === "dark" ? "light" : "dark");
});

initTheme();
initChoices();
initWindowControls();
loadSettings().catch((error) => setMessage(error.message, "error"));
loadDownloads();
