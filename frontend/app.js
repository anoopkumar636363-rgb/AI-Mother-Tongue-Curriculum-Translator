const sourceText = document.getElementById("sourceText");
const language = document.getElementById("language");
const translateBtn = document.getElementById("translateBtn");
const output = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");
const charCount = document.getElementById("charCount");
const pdfInput = document.getElementById("pdfInput");
const imageInput = document.getElementById("imageInput");
const clearBtn = document.getElementById("clearBtn");
const fileStatus = document.getElementById("fileStatus");
const notice = document.getElementById("notice");
const health = document.getElementById("health");

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

function setOutput(text) {
  output.classList.remove("empty");
  output.textContent = text;
  copyBtn.disabled = !text;
}

// Animate the completed backend response without changing its formatting.
function animateTyping(fullText, element, delay = 8) {
  return new Promise((resolve) => {
    element.className = "output";
    element.textContent = "";

    let index = 0;

    const interval = setInterval(() => {
      if (index < fullText.length) {
        element.textContent += fullText[index];
        element.scrollTop = element.scrollHeight;
        index++;
      } else {
        clearInterval(interval);
        resolve();
      }
    }, delay);
  });
}

sourceText.addEventListener("input", updateCount);

clearBtn.addEventListener("click", () => {
  sourceText.value = "";
  output.className = "output empty";
  output.innerHTML = '<div class="empty-icon">文</div><h3>Your translation appears here</h3><p>Choose a language and press Translate.</p>';
  copyBtn.disabled = true;
  fileStatus.classList.add("hidden");
  notice.classList.add("hidden");
  pdfInput.value = "";
  imageInput.value = "";
  updateCount();
});

pdfInput.addEventListener("change", async () => {
  const file = pdfInput.files[0];
  if (!file) return;

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

imageInput.addEventListener("change", async () => {
  const file = imageInput.files[0];
  if (!file) return;

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

translateBtn.addEventListener("click", async () => {
  const text = sourceText.value.trim();

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
  if (labelSpan) {
    labelSpan.textContent = "Translating...";
  } else {
    translateBtn.textContent = "Translating...";
  }

  showNotice(`Translating into ${language.value}...`);
  output.className = "output";
  output.textContent = "AI is translating the curriculum...";
  copyBtn.disabled = true;

  const form = new FormData();
  form.append("text", text);
  form.append("target_language", language.value);

  try {
    const res = await fetch("/api/translate", {
      method: "POST",
      body: form
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "Translation failed.");
    }

    await animateTyping(data.translated_text, output, 8);

    copyBtn.disabled = !data.translated_text;
    showNotice(`Translation complete • ${data.target_language}`);
  } catch (err) {
    output.className = "output empty";
    output.innerHTML = '<div class="empty-icon">!</div><h3>Translation failed</h3><p></p>';
    output.querySelector("p").textContent = err.message;
    showNotice(err.message, true);
  } finally {
    translateBtn.disabled = false;

    if (labelSpan) {
      labelSpan.textContent = originalLabel;
    } else {
      translateBtn.textContent = originalLabel;
    }
  }
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
    health.textContent = `● API ready • ${models}`;
  })
  .catch(() => {
    health.textContent = "● Start the FastAPI server";
  });

updateCount();
