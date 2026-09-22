const sourceText = document.getElementById("sourceText");
const language = document.getElementById("language");
const translateBtn = document.getElementById("translateBtn");
const output = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");


async function downloadPdf({ text, targetLanguage, title, subject, grade, reviewed }) {
  const res = await fetch("/api/export-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_language: targetLanguage, title, subject, grade, reviewed: !!reviewed }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map(x => x.msg).join(", ") : (d || "Could not create the PDF."));
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/i);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : "translation.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}


libraryDownloadPdfBtn.addEventListener("click", async () => {
  if (!libraryItem) return;

  try {
    await downloadPdf({
      text: libraryTranslatedText.value,
      targetLanguage: libraryItem.target_language,
      title: libraryDetailTitle.value.trim() || "Translated curriculum",
      subject: libraryItem.subject || "",
      grade: libraryItem.grade || "",
      reviewed: false,
    });
    showNotice("PDF downloaded.");
  } catch (err) {
    setLibraryError(err.message);
  }
});

downloadPdfBtn.addEventListener("click", async () => {
  const text = output.textContent.trim();
  if (!text || output.classList.contains("empty")) return;

  try {
    await downloadPdf({
      text,
      targetLanguage: language.value,
      title: saveTitle.value.trim() || "Translated curriculum",
      subject: subject.value.trim(),
      grade: grade.value.trim(),
      reviewed: false,
    });
    showNotice("PDF downloaded.");
  } catch (err) {
    showNotice(err.message, true);
  }
});
const downloadBtn = document.getElementById("downloadBtn");
const downloadPdfBtn = document.getElementById("downloadPdfBtn");
const saveBtn = document.getElementById("saveBtn");
const saveTitle = document.getElementById("saveTitle");
const charCount = document.getElementById("charCount");
const pdfInput = document.getElementById("pdfInput");
const imageInput = document.getElementById("imageInput");
const clearBtn = document.getElementById("clearBtn");
const translatePdfBtn = document.getElementById("translatePdfBtn");
let selectedPdfFile = null;
let currentSourceType = "text";
let savedResultId = null;
const fileStatus = document.getElementById("fileStatus");
const notice = document.getElementById("notice");
const loadingBar = document.getElementById("loadingBar");
const loadingLabel = document.getElementById("loadingLabel");
const health = document.getElementById("health");
const subject = document.getElementById("subject");
const grade = document.getElementById("grade");
const useGlossary = document.getElementById("useGlossary");

function updateCount() {
  charCount.textContent = sourceText.value.length.toLocaleString();
  charCount.style.color = sourceText.value.length > 30000 ? "#ff7b8a" : "";
}

function showNotice(message, error = false) {
  notice.textContent = message;
  notice.classList.remove("hidden");
  notice.style.color = error ? "#ff9ba7" : "";
}

function showFileStatus(message) {
  fileStatus.textContent = message;
  fileStatus.classList.remove("hidden");
}

function setLoading(active, message = "Working...") {
  if (!loadingBar) return;
  loadingBar.classList.toggle("hidden", !active);
  loadingBar.classList.toggle("running", active);
  if (loadingLabel) loadingLabel.textContent = message;
}

function setOutput(text) {
  output.classList.remove("empty");
  output.textContent = text;
  copyBtn.disabled = !text;
  downloadBtn.disabled = !text;
  saveBtn.disabled = !text || savedResultId !== null;
}

// Animate the completed backend response without changing its formatting.
function animateTyping(fullText, element) {
  return new Promise((resolve) => {
    element.className = "output";
    element.textContent = "";

    let index = 0;
    const charsPerFrame = 12;

    function reveal() {
      if (index >= fullText.length) {
        resolve();
        return;
      }

      element.textContent += fullText.slice(index, index + charsPerFrame);
      index += charsPerFrame;
      element.scrollTop = element.scrollHeight;
      requestAnimationFrame(reveal);
    }

    requestAnimationFrame(reveal);
  });
}

sourceText.addEventListener("input", updateCount);

clearBtn.addEventListener("click", () => {
  sourceText.value = "";
  output.className = "output empty";
  output.innerHTML = '<div class="empty-icon">文</div><h3>Your translation appears here</h3><p>Choose a language and press Translate.</p>';
  copyBtn.disabled = true;
  downloadBtn.disabled = true;
  downloadPdfBtn.disabled = true;
  fileStatus.classList.add("hidden");
  notice.classList.add("hidden");
  setLoading(false);
  pdfInput.value = "";
  imageInput.value = "";
  selectedPdfFile = null;
  currentSourceType = "text";
  savedResultId = null;
  saveBtn.disabled = true;
  saveTitle.value = "";
  translatePdfBtn.disabled = true;
  updateCount();
});

pdfInput.addEventListener("change", async () => {
  const file = pdfInput.files[0];
  if (!file) return;

  selectedPdfFile = file;
  currentSourceType = "pdf";
  savedResultId = null;
  saveBtn.disabled = true;
  translatePdfBtn.disabled = false;

  // Large PDFs are intended for the layout-preserving pipeline. Avoid
  // loading 50-200 MB of text into the browser textarea.
  const fileSizeMb = file.size / (1024 * 1024);
  if (fileSizeMb > 50) {
    showFileStatus(
      `${file.name} • ${fileSizeMb.toFixed(1)} MB • large-PDF mode ready`
    );
    showNotice(
      "Large PDF detected. Use “Translate PDF ↔ Keep Layout” — the translation brain will process it in batches."
    );
    return;
  }

  showFileStatus("Reading PDF...");
  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch("/api/extract-pdf", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not read PDF.");

    sourceText.value = data.text;
    updateCount();
    showFileStatus(
      data.truncated
        ? "PDF loaded. Text was trimmed to the 30,000 character demo limit."
        : `Loaded ${file.name} • ${data.characters.toLocaleString()} characters`
    );
    showNotice("PDF text extracted. Choose the mother tongue and translate.");
  } catch (err) {
    showFileStatus(err.message);
    showNotice(err.message, true);
  }
});


translatePdfBtn.addEventListener("click", async () => {
  if (!selectedPdfFile) {
    showNotice("Upload a PDF first.", true);
    return;
  }

  translatePdfBtn.disabled = true;
  const originalLabel = translatePdfBtn.textContent;
  translatePdfBtn.textContent = "Building PDF...";
  showFileStatus(
    "🧠 Translation brain active • splitting PDF into batches • automatic model fallback enabled"
  );
  setLoading(true, "🧠 Translation brain is working • batching, translating and rebuilding layout...");
  showNotice(
    "Translating PDF into " + language.value +
    " • multiple batches run concurrently • automatic fallback enabled..."
  );

  const form = new FormData();
  form.append("file", selectedPdfFile);
  form.append("target_language", language.value);
  form.append("subject", subject.value.trim());
  form.append("grade", grade.value.trim());
  form.append("use_glossary", useGlossary.checked ? "true" : "false");

  try {
    const res = await fetch("/api/translate-pdf", {
      method: "POST",
      body: form,
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Could not translate the PDF.");
    }

    setLoading(true, "Finishing PDF • assembling the translated document...");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/i);
    const filename = match ? match[1] : "translated-curriculum.pdf";

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);

    const glossaryUsed = res.headers.get("X-Glossary-Terms-Used");
    const pages = res.headers.get("X-PDF-Pages");
    const batches = res.headers.get("X-Translation-Batches");
    const workers = res.headers.get("X-Translation-Workers");

    setLoading(false);
    showNotice(
      "Translated PDF downloaded • " + language.value +
      " • layout preserved" +
      (pages ? " • " + pages + " pages" : "") +
      (batches ? " • " + batches + " AI batches" : "") +
      (workers ? " • " + workers + " workers" : "") +
      (glossaryUsed ? " • " + glossaryUsed + " glossary terms" : "")
    );
  } catch (err) {
    setLoading(false);
    showNotice(err.message, true);
  } finally {
    translatePdfBtn.disabled = !selectedPdfFile;
    translatePdfBtn.textContent = originalLabel;
  }
});


imageInput.addEventListener("change", async () => {
  const file = imageInput.files[0];
  if (!file) return;

  selectedPdfFile = null;
  currentSourceType = "image";
  savedResultId = null;
  saveBtn.disabled = true;
  translatePdfBtn.disabled = true;
  showFileStatus("AI is reading the page...");
  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch("/api/extract-image", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not read image.");

    sourceText.value = data.text;
    updateCount();
    showFileStatus(`Scanned ${file.name} • ${data.characters.toLocaleString()} characters`);
    showNotice("Image text extracted with AI. Review it before translating.");
  } catch (err) {
    showFileStatus(err.message);
    showNotice(err.message, true);
  }
});

sourceText.addEventListener("input", () => {
  currentSourceType = "text";
  savedResultId = null;
  if (saveBtn) saveBtn.disabled = true;
  updateGlossaryAutoGenerateState();
});

translateBtn.addEventListener("click", async () => {
  const text = sourceText.value.trim();
  savedResultId = null;
  if (saveBtn) saveBtn.disabled = true;

  if (!text) {
    showNotice("Add curriculum text, upload a PDF, or scan a page first.", true);
    return;
  }

  if (text.length > 30000) {
    showNotice("Please keep the curriculum under 30,000 characters for this demo.", true);
    return;
  }

  translateBtn.disabled = true;
  const labelSpan = translateBtn.querySelector("span");
  const originalLabel = labelSpan ? labelSpan.textContent : translateBtn.textContent;

  if (labelSpan) labelSpan.textContent = "Translating...";
  else translateBtn.textContent = "Translating...";

  setLoading(true, `Translating into ${language.value}...`);
  showNotice(`Translating into ${language.value}...`);
  output.className = "output";
  output.textContent = "AI is translating...";
  copyBtn.disabled = true;
  downloadBtn.disabled = true;
  downloadPdfBtn.disabled = true;

  const form = new FormData();
  form.append("text", text);
  form.append("target_language", language.value);
  form.append("subject", subject.value.trim());
  form.append("grade", grade.value.trim());
  form.append("use_glossary", useGlossary.checked ? "true" : "false");

  try {
    const res = await fetch("/api/translate", { method: "POST", body: form });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw new Error(data.detail || "Translation failed.");
    }

    if (!data.text) {
      throw new Error("The AI returned an empty translation.");
    }

    setLoading(true, "Translation received • displaying result...");
    await animateTyping(data.text, output);

    setLoading(false);
    const glossaryMissing = Array.isArray(data.glossary_missing) ? data.glossary_missing : [];
    const glossaryTermsUsed = Array.isArray(data.glossary_terms_used) ? data.glossary_terms_used : [];
    let message = `Translation complete • ${language.value}`;
    if (glossaryTermsUsed.length) {
      message += " • glossary used: " + glossaryTermsUsed.join(", ");
    } else if (useGlossary.checked) {
      message += " • no glossary terms matched this text";
    }
    if (glossaryMissing.length) {
      message += " • not applied by AI: " + glossaryMissing.join(", ");
    }
    showNotice(message, glossaryMissing.length > 0);
    copyBtn.disabled = false;
    downloadBtn.disabled = false;
  downloadPdfBtn.disabled = false;
    saveBtn.disabled = false;
    savedResultId = null;
    saveTitle.value = text.slice(0, 60).trim() || "Untitled teaching material";
    showNotice(`Translation complete • ${language.value}`);
  } catch (err) {
    setLoading(false);
    output.className = "output empty";
    output.innerHTML = '<div class="empty-icon">!</div><h3>Translation failed</h3><p></p>';
    output.querySelector("p").textContent = err.message;
    showNotice(err.message, true);
  } finally {
    translateBtn.disabled = false;
    if (labelSpan) labelSpan.textContent = originalLabel;
    else translateBtn.textContent = originalLabel;
  }
});


downloadBtn.addEventListener("click", () => {
  const text = output.textContent.trim();
  if (!text || output.classList.contains("empty")) return;

  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeLanguage = language.value.toLowerCase().replace(/[^a-z0-9]+/g, "-");

  link.href = url;
  link.download = `curriculum-${safeLanguage}-translation.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);

  showNotice("Translation downloaded.");
});

copyBtn.addEventListener("click", async () => {
  const text = output.textContent.trim();
  if (!text) return;

  try {
    await navigator.clipboard.writeText(text);
    showNotice("Translation copied to clipboard.");
  } catch {
    showNotice("Could not copy the translation.", true);
  }
});

fetch("/api/health")
  .then(r => r.json())
  .then(data => {
    const models = Array.isArray(data.models) ? data.models.join(" → ") : "Gemini";
    if (data.gemini_configured === false) {
      health.textContent = "● Gemini API key not configured";
      showNotice(data.message || "Add GEMINI_API_KEY to .env before translating.", true);
    } else {
      health.textContent = `● API ready • ${models}`;
    }
  })
  .catch(() => {
    health.textContent = "● Start the FastAPI server";
  });

updateCount();


// Library + Teacher/Admin dashboard
const tabs = document.querySelectorAll(".tab-btn");
const translateView = document.getElementById("translateView");
const libraryView = document.getElementById("libraryView");
const dashboardView = document.getElementById("dashboardView");
const glossaryView = document.getElementById("glossaryView");

const libraryError = document.getElementById("libraryError");
const libraryListView = document.getElementById("libraryListView");
const libraryDetailView = document.getElementById("libraryDetailView");
const libraryItems = document.getElementById("libraryItems");
const libraryEmpty = document.getElementById("libraryEmpty");
const librarySearch = document.getElementById("librarySearch");
const librarySearchBtn = document.getElementById("librarySearchBtn");
const libraryLanguage = document.getElementById("libraryLanguage");
const librarySubject = document.getElementById("librarySubject");
const libraryGrade = document.getElementById("libraryGrade");
const libraryPrev = document.getElementById("libraryPrev");
const libraryNext = document.getElementById("libraryNext");
const libraryPageLabel = document.getElementById("libraryPageLabel");
const libraryBackBtn = document.getElementById("libraryBackBtn");
const libraryDetailTitle = document.getElementById("libraryDetailTitle");
const libraryDetailInfo = document.getElementById("libraryDetailInfo");
const libraryOriginalText = document.getElementById("libraryOriginalText");
const libraryTranslatedText = document.getElementById("libraryTranslatedText");
const librarySaveBtn = document.getElementById("librarySaveBtn");
const libraryCopyBtn = document.getElementById("libraryCopyBtn");
const libraryDownloadBtn = document.getElementById("libraryDownloadBtn");
const libraryDownloadPdfBtn = document.getElementById("libraryDownloadPdfBtn");
const libraryDeleteBtn = document.getElementById("libraryDeleteBtn");
const libraryLoadBtn = document.getElementById("libraryLoadBtn");

const adminLogin = document.getElementById("adminLogin");
const adminPassword = document.getElementById("adminPassword");
const loginBtn = document.getElementById("loginBtn");
const adminError = document.getElementById("adminError");
const dashboardContent = document.getElementById("dashboardContent");
const dashboardActions = document.getElementById("dashboardActions");
const dashboardError = document.getElementById("dashboardError");
const daysSelect = document.getElementById("daysSelect");
const csvBtn = document.getElementById("csvBtn");
const logoutBtn = document.getElementById("logoutBtn");
const eventLanguage = document.getElementById("eventLanguage");
const eventSource = document.getElementById("eventSource");
const eventSuccess = document.getElementById("eventSuccess");
const eventsBody = document.getElementById("eventsBody");
const emptyEvents = document.getElementById("emptyEvents");
const prevPage = document.getElementById("prevPage");
const nextPage = document.getElementById("nextPage");
const pageLabel = document.getElementById("pageLabel");
const eventMeta = document.getElementById("eventMeta");
const sourceBreakdown = document.getElementById("sourceBreakdown");

let adminPasswordMemory = "";
let adminPage = 1;
let languageChart = null;
let dailyChart = null;
let libraryPage = 1;
let libraryTotalPages = 0;
let libraryItem = null;

function setDashboardError(message) {
  dashboardError.textContent = message;
  dashboardError.classList.toggle("hidden", !message);
}

function setLibraryError(message) {
  libraryError.textContent = message;
  libraryError.classList.toggle("hidden", !message);
}

function adminHeaders() {
  return { "X-Admin-Password": adminPasswordMemory };
}

function showTab(id) {
  tabs.forEach(tab => tab.classList.toggle("active", tab.dataset.tab === id));
  translateView.classList.toggle("hidden", id !== "translateView");
  libraryView.classList.toggle("hidden", id !== "libraryView");
  dashboardView.classList.toggle("hidden", id !== "dashboardView");
  glossaryView.classList.toggle("hidden", id !== "glossaryView");

  if (id === "glossaryView") loadGlossary();

  if (id === "libraryView") {
    loadLibraryFilters();
    if (!libraryItem) loadLibrary();
  }
  if (id === "dashboardView" && adminPasswordMemory) loadDashboard();
}

tabs.forEach(tab => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function destroyCharts() {
  if (languageChart) { languageChart.destroy(); languageChart = null; }
  if (dailyChart) { dailyChart.destroy(); dailyChart = null; }
}

function renderCharts(stats) {
  if (!window.Chart) {
    setDashboardError("Dashboard charts could not load. Please check your internet connection and refresh.");
    return;
  }
  destroyCharts();
  languageChart = new Chart(document.getElementById("languageChart"), {
    type: "bar",
    data: {
      labels: (stats.by_target_language || []).map(x => x.label),
      datasets: [{ label: "Translations", data: (stats.by_target_language || []).map(x => x.count), borderWidth: 0, borderRadius: 6 }]
    },
    options: { responsive: true, maintainAspectRatio: false, indexAxis: "y", plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { color: "#7d88a3", precision: 0 }, grid: { color: "rgba(255,255,255,.05)" } },
        y: { ticks: { color: "#c4cce0" }, grid: { display: false } } } }
  });
  dailyChart = new Chart(document.getElementById("dailyChart"), {
    type: "line",
    data: {
      labels: (stats.daily || []).map(x => x.date),
      datasets: [{ label: "Translations", data: (stats.daily || []).map(x => x.count), tension: .25, fill: false, borderWidth: 2, pointRadius: 2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#7d88a3", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,.05)" } },
        y: { beginAtZero: true, ticks: { color: "#7d88a3", precision: 0 }, grid: { color: "rgba(255,255,255,.05)" } } } }
  });
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));
}

function renderPillBreakdown(container, items, emptyMessage = "No data yet") {
  if (!items.length) {
    container.textContent = emptyMessage;
    container.classList.add("empty-dashboard");
    return;
  }
  container.classList.remove("empty-dashboard");
  container.replaceChildren();
  items.forEach(item => {
    const pill = document.createElement("div");
    pill.className = "source-pill";
    const label = document.createElement("span");
    label.textContent = item.label;
    const count = document.createElement("strong");
    count.textContent = formatNumber(item.count);
    pill.append(label, count);
    container.appendChild(pill);
  });
}

function renderSourceBreakdown(items) {
  renderPillBreakdown(sourceBreakdown, items, "No translations yet");
}

async function fetchStats() {
  const res = await fetch("/api/admin/stats?days=" + encodeURIComponent(daysSelect.value), { headers: adminHeaders() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Could not load dashboard statistics.");
  return data;
}

async function loadDashboard() {
  if (!adminPasswordMemory) return;
  setDashboardError("");
  try {
    const stats = await fetchStats();
    document.getElementById("statTotal").textContent = formatNumber(stats.total_translations);
    document.getElementById("statSuccess").textContent = stats.success_rate + "%";
    document.getElementById("statChars").textContent = formatNumber(stats.total_characters);
    document.getElementById("statAvg").textContent = formatNumber(Math.round(stats.average_duration_ms)) + " ms";

    const savedCard = document.getElementById("statSavedCard");
    const savedValue = document.getElementById("statSaved");
    if (savedCard && savedValue) {
      savedCard.classList.toggle("hidden", stats.translations === undefined);
      if (stats.translations !== undefined) savedValue.textContent = formatNumber(stats.translations);
    }

    renderCharts(stats);
    renderSourceBreakdown(stats.by_source_type || []);

    const glossaryCount = document.getElementById("statGlossary");
    if (glossaryCount) glossaryCount.textContent = formatNumber(stats.glossary_terms);

    const glossaryLanguageBreakdown = document.getElementById("glossaryLanguageBreakdown");
    if (glossaryLanguageBreakdown) {
      renderPillBreakdown(glossaryLanguageBreakdown, stats.glossary_by_language || [], "No glossary terms yet");
    }

    const currentLanguage = eventLanguage.value;
    eventLanguage.innerHTML = '<option value="">All languages</option>' +
      (stats.by_target_language || []).map(x => '<option value="' + escapeHtml(x.label) + '">' + escapeHtml(x.label) + '</option>').join("");
    if ([...eventLanguage.options].some(o => o.value === currentLanguage)) eventLanguage.value = currentLanguage;
    await loadEvents();
  } catch (err) {
    setDashboardError(err.message);
  }
}

async function loadEvents() {
  const params = new URLSearchParams({
    page: adminPage, page_size: 25, language: eventLanguage.value,
    source_type: eventSource.value, success: eventSuccess.value
  });
  const res = await fetch("/api/admin/events?" + params.toString(), { headers: adminHeaders() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    setDashboardError(data.detail || "Could not load recent events.");
    return;
  }
  eventsBody.replaceChildren();
  emptyEvents.classList.toggle("hidden", data.events.length !== 0);
  data.events.forEach(event => {
    const tr = document.createElement("tr");
    const cells = [
      new Date(event.created_at).toLocaleString(),
      event.source_type,
      event.target_language,
      event.subject || "—",
      event.grade || "—",
      formatNumber(event.characters),
      event.model || "—",
      formatNumber(event.duration_ms) + " ms",
      event.success ? "Success" : "Failed"
    ];
    cells.forEach((value, index) => {
      const td = document.createElement("td");
      td.textContent = value;
      if (index === cells.length - 1) td.className = event.success ? "status-ok" : "status-fail";
      tr.appendChild(td);
    });
    eventsBody.appendChild(tr);
  });
  const totalPages = data.total_pages || 0;
  pageLabel.textContent = totalPages ? "Page " + data.page + " of " + totalPages : "No pages";
  prevPage.disabled = data.page <= 1;
  nextPage.disabled = !totalPages || data.page >= totalPages;
  eventMeta.textContent = data.total ? formatNumber(data.total) + " logged event" + (data.total === 1 ? "" : "s") : "No translations yet";
}

async function libraryRequest(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Library request failed.");
  return data;
}

function fillSelect(select, values, label) {
  const current = select.value;
  select.replaceChildren();
  const first = document.createElement("option");
  first.value = "";
  first.textContent = label;
  select.appendChild(first);
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if (values.includes(current)) select.value = current;
}

async function loadLibraryFilters() {
  try {
    const data = await libraryRequest("/api/library/filters");
    fillSelect(libraryLanguage, data.languages || [], "All languages");
    fillSelect(librarySubject, data.subjects || [], "All subjects");
    fillSelect(libraryGrade, data.grades || [], "All grades");
  } catch (err) {
    setLibraryError(err.message);
  }
}

function createLibraryCard(item) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "library-card";
  card.addEventListener("click", () => openLibraryItem(item.id));

  const top = document.createElement("div");
  top.className = "library-card-top";
  const title = document.createElement("h3");
  title.textContent = item.title;
  const date = document.createElement("time");
  date.textContent = new Date(item.updated_at || item.created_at).toLocaleDateString();
  top.append(title, date);

  const meta = document.createElement("div");
  meta.className = "library-meta";
  [item.target_language, item.subject || "No subject", item.grade || "No grade", item.source_type].forEach(value => {
    const span = document.createElement("span");
    span.textContent = value;
    meta.appendChild(span);
  });

  const preview = document.createElement("p");
  preview.textContent = item.preview || "No translated preview available.";
  card.append(top, meta, preview);
  return card;
}

async function loadLibrary() {
  setLibraryError("");
  try {
    const params = new URLSearchParams({
      page: libraryPage,
      page_size: 12,
      q: librarySearch.value.trim(),
      language: libraryLanguage.value,
      subject: librarySubject.value,
      grade: libraryGrade.value
    });
    const data = await libraryRequest("/api/library?" + params.toString());
    libraryItems.replaceChildren();
    libraryEmpty.classList.toggle("hidden", data.items.length !== 0);
    data.items.forEach(item => libraryItems.appendChild(createLibraryCard(item)));
    libraryTotalPages = data.total_pages || 0;
    libraryPageLabel.textContent = libraryTotalPages ? "Page " + data.page + " of " + libraryTotalPages : "No pages";
    libraryPrev.disabled = data.page <= 1;
    libraryNext.disabled = !libraryTotalPages || data.page >= libraryTotalPages;
  } catch (err) {
    setLibraryError(err.message);
  }
}

async function openLibraryItem(id) {
  setLibraryError("");
  try {
    const item = await libraryRequest("/api/library/" + encodeURIComponent(id));
    libraryItem = item;
    libraryListView.classList.add("hidden");
    libraryDetailView.classList.remove("hidden");
    libraryDetailTitle.value = item.title;
    libraryDetailInfo.textContent = [item.target_language, item.subject || "No subject", item.grade || "No grade", item.source_type].join(" • ");
    libraryOriginalText.textContent = item.original_text;
    libraryTranslatedText.value = item.translated_text;
  } catch (err) {
    setLibraryError(err.message);
  }
}

function showLibraryList() {
  libraryItem = null;
  libraryDetailView.classList.add("hidden");
  libraryListView.classList.remove("hidden");
  loadLibrary();
}

librarySearchBtn.addEventListener("click", () => { libraryPage = 1; loadLibrary(); });
librarySearch.addEventListener("keydown", event => {
  if (event.key === "Enter") { libraryPage = 1; loadLibrary(); }
});
[libraryLanguage, librarySubject, libraryGrade].forEach(select => {
  select.addEventListener("change", () => { libraryPage = 1; loadLibrary(); });
});
libraryPrev.addEventListener("click", () => {
  if (libraryPage > 1) { libraryPage -= 1; loadLibrary(); }
});
libraryNext.addEventListener("click", () => {
  if (libraryPage < libraryTotalPages) { libraryPage += 1; loadLibrary(); }
});
libraryBackBtn.addEventListener("click", showLibraryList);

librarySaveBtn.addEventListener("click", async () => {
  if (!libraryItem) return;
  librarySaveBtn.disabled = true;
  setLibraryError("");
  try {
    const updated = await libraryRequest("/api/library/" + libraryItem.id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: libraryDetailTitle.value.trim(),
        translated_text: libraryTranslatedText.value
      })
    });
    libraryItem = updated;
    libraryDetailTitle.value = updated.title;
    libraryDetailInfo.textContent = [updated.target_language, updated.subject || "No subject", updated.grade || "No grade", updated.source_type].join(" • ");
    libraryTranslatedText.value = updated.translated_text;
    setLibraryError("");
    showNotice('Saved changes to "' + updated.title + '".');
  } catch (err) {
    setLibraryError(err.message);
  } finally {
    librarySaveBtn.disabled = false;
  }
});

libraryCopyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(libraryTranslatedText.value);
    showNotice("Translated material copied to clipboard.");
  } catch {
    setLibraryError("Could not copy the translated material.");
  }
});

libraryDownloadBtn.addEventListener("click", () => {
  if (!libraryItem) return;
  const blob = new Blob([libraryTranslatedText.value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = (libraryItem.title || "teaching-material").replace(/[^a-z0-9_-]+/gi, "-") + ".txt";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});

libraryDeleteBtn.addEventListener("click", async () => {
  if (!libraryItem) return;
  if (!window.confirm('Delete "' + libraryItem.title + '"? This cannot be undone.')) return;
  try {
    await libraryRequest("/api/library/" + libraryItem.id, { method: "DELETE" });
    showNotice("Saved material deleted.");
    showLibraryList();
  } catch (err) {
    setLibraryError(err.message);
  }
});

libraryLoadBtn.addEventListener("click", () => {
  if (!libraryItem) return;
  sourceText.value = libraryItem.original_text;
  language.value = libraryItem.target_language;
  subject.value = libraryItem.subject || "";
  grade.value = libraryItem.grade || "";
  currentSourceType = libraryItem.source_type;
  savedResultId = null;
  saveTitle.value = libraryItem.title;
  output.className = "output";
  output.textContent = libraryItem.translated_text;
  copyBtn.disabled = false;
  downloadBtn.disabled = false;
  downloadPdfBtn.disabled = false;
  saveBtn.disabled = false;
  syncGlossaryLanguages();
resetGlossaryForm();
showTab("translateView");
  showNotice('Loaded "' + libraryItem.title + '" into Translate.');
  updateCount();
});

saveBtn.addEventListener("click", async () => {
  const translatedText = output.textContent.trim();
  const originalText = sourceText.value.trim();
  if (!translatedText || !originalText || savedResultId !== null) return;

  const title = saveTitle.value.trim() || originalText.slice(0, 60).trim();
  if (!title) {
    showNotice("Add a title before saving.", true);
    return;
  }

  saveBtn.disabled = true;
  try {
    const saved = await libraryRequest("/api/library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        subject: subject.value.trim(),
        grade: grade.value.trim(),
        target_language: language.value,
        source_type: currentSourceType,
        original_text: originalText,
        translated_text: translatedText
      })
    });
    savedResultId = saved.id;
    saveTitle.value = saved.title;
    showNotice('Saved "' + saved.title + '" to Library.');
  } catch (err) {
    saveBtn.disabled = false;
    showNotice(err.message, true);
  }
});


// Translation glossary
const glossaryLanguageFilter = document.getElementById("glossaryLanguageFilter");
const glossarySubjectFilter = document.getElementById("glossarySubjectFilter");
const glossarySearch = document.getElementById("glossarySearch");
const glossarySearchBtn = document.getElementById("glossarySearchBtn");
const glossaryBody = document.getElementById("glossaryBody");
const glossaryEmpty = document.getElementById("glossaryEmpty");
const glossaryPrev = document.getElementById("glossaryPrev");
const glossaryNext = document.getElementById("glossaryNext");
const glossaryPageLabel = document.getElementById("glossaryPageLabel");
const glossaryForm = document.getElementById("glossaryForm");
const glossaryEditId = document.getElementById("glossaryEditId");
const glossaryFormTitle = document.getElementById("glossaryFormTitle");
const glossarySource = document.getElementById("glossarySource");
const glossaryTargetLanguage = document.getElementById("glossaryTargetLanguage");
const glossaryTranslated = document.getElementById("glossaryTranslated");
const glossarySubjectInput = document.getElementById("glossarySubject");
const glossarySaveBtn = document.getElementById("glossarySaveBtn");
const glossaryCancelBtn = document.getElementById("glossaryCancelBtn");
const glossarySuggestBtn = document.getElementById("glossarySuggestBtn");
const quickAddGlossaryBtn = document.getElementById("quickAddGlossaryBtn");
const glossaryAutoGenerateBtn = document.getElementById("glossaryAutoGenerateBtn");
const glossarySuggestStatus = document.getElementById("glossarySuggestStatus");
const glossarySuggestions = document.getElementById("glossarySuggestions");
const glossarySaveSelectedBtn = document.getElementById("glossarySaveSelectedBtn");

let glossaryLoadedItems = [];

let glossaryPage = 1;
let glossaryTotalPages = 0;

function syncGlossaryLanguages() {
  const languages = [...language.options].map(option => ({
    value: option.value,
    label: option.textContent,
  }));
  const currentLanguage = language.value;
  const currentGlossaryLanguage = glossaryTargetLanguage.value;

  glossaryTargetLanguage.replaceChildren();
  languages.forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    glossaryTargetLanguage.appendChild(option);
  });

  glossaryLanguageFilter.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "All languages";
  glossaryLanguageFilter.appendChild(allOption);
  languages.forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    glossaryLanguageFilter.appendChild(option);
  });

  glossaryTargetLanguage.value = languages.some(item => item.value === currentGlossaryLanguage)
    ? currentGlossaryLanguage
    : currentLanguage;
  glossaryLanguageFilter.value = "";
}

async function glossaryRequest(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => item && item.msg).filter(Boolean).join(", ")
      : data.detail;
    throw new Error(detail || "Glossary request failed.");
  }
  return data;
}

function setGlossaryError(message) {
  const el = document.getElementById("glossaryError");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("hidden", !message);
}

function languageLabel(value) {
  const opt = [...language.options].find(o => o.value === value);
  return opt ? opt.textContent : value;
}

function renderGlossaryRows(items) {
  glossaryBody.replaceChildren();
  glossaryEmpty.classList.toggle("hidden", items.length !== 0);
  items.forEach(item => {
    const tr = document.createElement("tr");
    [item.source_term, languageLabel(item.target_language), item.translated_term, item.subject || "—"].forEach(value => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    const actions = document.createElement("td");
    actions.className = "glossary-actions-cell";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "glossary-small-btn";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => startGlossaryEdit(item));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "glossary-small-btn danger-btn";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteGlossary(item.id));
    actions.append(edit, remove);
    tr.appendChild(actions);
    glossaryBody.appendChild(tr);
  });
}

function filterGlossaryRows() {
  const query = glossarySearch.value.trim().toLowerCase();
  const filtered = !query ? glossaryLoadedItems : glossaryLoadedItems.filter(item =>
    item.source_term.toLowerCase().includes(query) ||
    item.translated_term.toLowerCase().includes(query)
  );
  renderGlossaryRows(filtered);
}

function loadGlossarySubjects(items) {
  const current = glossarySubjectFilter.value;
  glossarySubjectFilter.innerHTML = '<option value="">All subjects</option>';
  const values = [...new Set(items.map(item => item.subject).filter(Boolean))].sort((a,b) => a.localeCompare(b));
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    glossarySubjectFilter.appendChild(option);
  });
  if (values.includes(current)) glossarySubjectFilter.value = current;
}

async function loadGlossary() {
  setGlossaryError("");
  try {
    const params = new URLSearchParams({
      language: glossaryLanguageFilter.value,
      subject: glossarySubjectFilter.value
    });
    const data = await glossaryRequest("/api/glossary?" + params.toString());
    const items = data.items || [];
    glossaryLoadedItems = items;
    filterGlossaryRows();
    glossaryTotalPages = 1;
    glossaryPageLabel.textContent = items.length ? "Page 1 of 1" : "No pages";
    glossaryPrev.disabled = true;
    glossaryNext.disabled = true;

    const allData = await glossaryRequest("/api/glossary");
    loadGlossarySubjects(allData.items || []);
  } catch (err) {
    setGlossaryError(err.message);
  }
}

function resetGlossaryForm() {
  glossaryEditId.value = "";
  glossarySource.value = "";
  glossaryTranslated.value = "";
  glossarySubjectInput.value = "";
  glossaryFormTitle.textContent = "Add term";
  glossarySaveBtn.textContent = "Add term →";
  glossaryTargetLanguage.value = language.value;
  glossaryCancelBtn.classList.add("hidden");
}

function startGlossaryEdit(item) {
  glossaryEditId.value = item.id;
  glossarySource.value = item.source_term;
  glossaryTargetLanguage.value = item.target_language;
  glossaryTranslated.value = item.translated_term;
  glossarySubjectInput.value = item.subject || "";
  glossaryFormTitle.textContent = "Edit term";
  glossarySaveBtn.textContent = "Save changes →";
  glossaryCancelBtn.classList.remove("hidden");
  glossarySource.focus();
}

async function deleteGlossary(id) {
  if (!window.confirm("Delete this glossary term?")) return;
  try {
    await glossaryRequest("/api/glossary/" + id, { method: "DELETE" });
    await loadGlossary();
    showNotice("Glossary term deleted.");
  } catch (err) {
    setGlossaryError(err.message);
  }
}

glossaryForm.addEventListener("submit", async event => {
  event.preventDefault();
  setGlossaryError("");
  const sourceTerm = glossarySource.value.trim();
  const targetLanguage = glossaryTargetLanguage.value.trim();
  const translatedTerm = glossaryTranslated.value.trim();
  if (!sourceTerm || !translatedTerm || !targetLanguage) {
    setGlossaryError("Source term, translated term, and target language are required.");
    return;
  }
  glossarySaveBtn.disabled = true;
  try {
    const payload = {
      source_term: sourceTerm,
      target_language: targetLanguage,
      translated_term: translatedTerm,
      subject: glossarySubjectInput.value.trim(),
    };
    const id = glossaryEditId.value;
    const data = id
      ? await glossaryRequest("/api/glossary/" + id, { method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) })
      : await glossaryRequest("/api/glossary", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
    resetGlossaryForm();
    await loadGlossary();
    showNotice(id ? "Glossary term updated." : "Glossary term added.");
  } catch (err) {
    setGlossaryError(err.message);
  } finally {
    glossarySaveBtn.disabled = false;
  }
});

function setGlossarySuggestStatus(message, error = false) {
  glossarySuggestStatus.textContent = message;
  glossarySuggestStatus.classList.remove("hidden");
  glossarySuggestStatus.classList.toggle("warning", error);
}

function updateGlossaryAutoGenerateState() {
  if (!glossaryAutoGenerateBtn) return;
  glossaryAutoGenerateBtn.disabled = !sourceText.value.trim() || !language.value;
}

function renderGlossarySuggestions(items) {
  glossarySuggestions.replaceChildren();

  if (!items.length) {
    glossarySuggestions.classList.add("hidden");
    glossarySaveSelectedBtn.classList.add("hidden");
    setGlossarySuggestStatus("No new glossary terms were suggested for this language and subject.");
    return;
  }

  items.forEach(item => {
    const row = document.createElement("div");
    row.className = "glossary-suggestion-row";
    Object.assign(row.style, {
      display: "grid",
      gridTemplateColumns: "24px minmax(0, 1fr) 24px minmax(0, 1fr)",
      gap: "8px",
      alignItems: "center",
      padding: "10px",
      marginTop: "8px",
      border: "1px solid rgba(255,255,255,.07)",
      borderRadius: "12px",
      background: "rgba(255,255,255,.025)"
    });

    const checkWrap = document.createElement("label");
    checkWrap.style.display = "grid";
    checkWrap.style.placeItems = "center";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.style.width = "16px";
    checkbox.style.height = "16px";
    checkbox.style.accentColor = "#7564ff";

    checkWrap.appendChild(checkbox);

    const source = document.createElement("input");
    source.type = "text";
    source.className = "glossary-edit-input";
    source.value = item.source_term || "";
    source.maxLength = 200;
    source.placeholder = "Source term";

    const arrow = document.createElement("span");
    arrow.textContent = "→";
    arrow.style.textAlign = "center";
    arrow.style.color = "#7564ff";
    arrow.style.fontWeight = "800";

    const translated = document.createElement("input");
    translated.type = "text";
    translated.className = "glossary-edit-input";
    translated.value = item.translated_term || "";
    translated.maxLength = 200;
    translated.placeholder = "Translated term";

    row.append(checkWrap, source, arrow, translated);
    glossarySuggestions.appendChild(row);
  });

  glossarySuggestions.classList.remove("hidden");
  glossarySaveSelectedBtn.classList.remove("hidden");
  setGlossarySuggestStatus(
    items.length + " suggestion" + (items.length === 1 ? "" : "s") +
    " found. Review the terms before saving."
  );
}

glossaryAutoGenerateBtn.addEventListener("click", async () => {
  const text = sourceText.value.trim();

  if (!text) {
    setGlossarySuggestStatus("Add curriculum text first.", true);
    return;
  }

  if (text.length > 30000) {
    setGlossarySuggestStatus("Keep the curriculum under 30,000 characters.", true);
    return;
  }

  glossaryAutoGenerateBtn.disabled = true;
  glossarySaveSelectedBtn.classList.add("hidden");
  glossarySuggestions.classList.add("hidden");
  setGlossarySuggestStatus("Gemini is finding technical and subject-specific terms...");

  try {
    const data = await glossaryRequest("/api/glossary/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        target_language: language.value,
        subject: subject.value.trim(),
      }),
    });

    renderGlossarySuggestions(data.suggestions || []);
  } catch (err) {
    setGlossarySuggestStatus(err.message, true);
    glossarySuggestions.classList.add("hidden");
    glossarySaveSelectedBtn.classList.add("hidden");
  } finally {
    updateGlossaryAutoGenerateState();
  }
});

glossarySaveSelectedBtn.addEventListener("click", async () => {
  const rows = [...glossarySuggestions.querySelectorAll(".glossary-suggestion-row")];
  const selected = rows.map(row => ({
    row,
    checked: row.querySelector('input[type="checkbox"]')?.checked,
    sourceTerm: row.querySelectorAll('input[type="text"]')[0]?.value.trim(),
    translatedTerm: row.querySelectorAll('input[type="text"]')[1]?.value.trim(),
  })).filter(item => item.checked && item.sourceTerm && item.translatedTerm);

  if (!selected.length) {
    setGlossarySuggestStatus("Select at least one complete glossary term.", true);
    return;
  }

  glossarySaveSelectedBtn.disabled = true;
  setGlossarySuggestStatus("Saving selected glossary terms...");

  let saved = 0;
  let duplicates = 0;
  let failed = 0;

  for (const item of selected) {
    try {
      await glossaryRequest("/api/glossary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_term: item.sourceTerm,
          target_language: glossaryTargetLanguage.value,
          translated_term: item.translatedTerm,
          subject: glossarySubjectInput.value.trim(),
        }),
      });
      saved += 1;
      const checkbox = item.row.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.checked = false;
    } catch (err) {
      if (/already exists/i.test(err.message) || /409/.test(err.message)) {
        duplicates += 1;
        const checkbox = item.row.querySelector('input[type="checkbox"]');
        if (checkbox) checkbox.checked = false;
      } else {
        failed += 1;
      }
    }
  }

  glossarySaveSelectedBtn.disabled = false;
  await loadGlossary();

  const parts = [];
  if (saved) parts.push(saved + " saved");
  if (duplicates) parts.push(duplicates + " duplicate" + (duplicates === 1 ? "" : "s") + " skipped");
  if (failed) parts.push(failed + " failed");

  setGlossarySuggestStatus(
    parts.length ? parts.join(" • ") : "Nothing was saved.",
    failed > 0
  );
});
language.addEventListener("change", () => {
  if (!glossaryEditId.value) glossaryTargetLanguage.value = language.value;
  updateGlossaryAutoGenerateState();
});
glossaryCancelBtn.addEventListener("click", resetGlossaryForm);
glossarySearchBtn.addEventListener("click", filterGlossaryRows);
glossarySearch.addEventListener("input", filterGlossaryRows);
glossarySearch.addEventListener("keydown", event => { if (event.key === "Enter") filterGlossaryRows(); });
[glossaryLanguageFilter, glossarySubjectFilter].forEach(select => select.addEventListener("change", loadGlossary));

quickAddGlossaryBtn.addEventListener("click", async () => {
  const selectedText = sourceText.value.slice(sourceText.selectionStart, sourceText.selectionEnd).trim();
  if (!selectedText) {
    showNotice("Select text in the curriculum input first.", true);
    return;
  }
  syncGlossaryLanguages();
  resetGlossaryForm();
  glossarySource.value = selectedText;
  glossaryTargetLanguage.value = language.value;
  glossarySubjectInput.value = subject.value.trim();
  showTab("glossaryView");
  glossarySource.focus();
});

// Admin login
loginBtn.addEventListener("click", async () => {
  const password = adminPassword.value;
  if (!password) {
    adminError.textContent = "Enter the admin password.";
    adminError.classList.remove("hidden");
    return;
  }
  loginBtn.disabled = true;
  adminError.classList.add("hidden");
  try {
    const res = await fetch("/api/admin/login", { method: "POST", headers: { "X-Admin-Password": password } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Admin login failed.");
    adminPasswordMemory = password;
    adminPassword.value = "";
    adminLogin.classList.add("hidden");
    dashboardContent.classList.remove("hidden");
    dashboardActions.classList.remove("hidden");
    adminPage = 1;
    await loadDashboard();
  } catch (err) {
    adminError.textContent = err.message;
    adminError.classList.remove("hidden");
  } finally {
    loginBtn.disabled = false;
  }
});

adminPassword.addEventListener("keydown", event => {
  if (event.key === "Enter") loginBtn.click();
});
daysSelect.addEventListener("change", () => { adminPage = 1; loadDashboard(); });
[eventLanguage, eventSource, eventSuccess].forEach(filter => filter.addEventListener("change", () => { adminPage = 1; loadEvents(); }));
prevPage.addEventListener("click", () => { if (adminPage > 1) { adminPage -= 1; loadEvents(); } });
nextPage.addEventListener("click", () => { adminPage += 1; loadEvents(); });

csvBtn.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/admin/export/events.csv", { headers: adminHeaders() });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Could not export the event log.");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "translation-events.csv";
    link.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    setDashboardError(err.message);
  }
});

logoutBtn.addEventListener("click", () => {
  adminPasswordMemory = "";
  adminPage = 1;
  destroyCharts();
  dashboardContent.classList.add("hidden");
  dashboardActions.classList.add("hidden");
  adminLogin.classList.remove("hidden");
  adminError.classList.add("hidden");
  setDashboardError("");
});

syncGlossaryLanguages();
updateGlossaryAutoGenerateState();
showTab("translateView");