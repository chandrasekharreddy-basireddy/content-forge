/* Content Forge landing page logic.
 *
 * Three jobs: check the API is alive, post the text, render the answer.
 * No framework, no build step. Open the page and read it.
 */

// Change this to your deployed FastAPI URL. Locally, the API serves this page
// from the same origin, so an empty string works.
const API_BASE = "";

const form = document.getElementById("demo-form");
const source = document.getElementById("source");
const count = document.getElementById("count");
const statusLine = document.getElementById("status");
const resultBox = document.getElementById("result");
const runButton = document.getElementById("run");
const translateBox = document.getElementById("translate");
const languageSelect = document.getElementById("language");

const LABELS = {
  summary: "Summary",
  quiz: "Quiz",
  flashcards: "Flashcards",
  report: "Report",
  slides: "Slide outline",
};

/* --- small helpers ------------------------------------------------------ */

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function chosenOutputs() {
  return [...document.querySelectorAll('input[name="outputs"]:checked')].map(
    (box) => box.value
  );
}

/* --- health and stats --------------------------------------------------- */

async function loadHealth() {
  const health = document.getElementById("health");
  try {
    const response = await fetch(`${API_BASE}/api/health`);
    const data = await response.json();
    health.textContent = data.has_key
      ? `Server ready · model ${data.model}`
      : "Server up, but no API key is configured — the demo will not run.";
  } catch (error) {
    health.textContent = "The API is not reachable. Start it with: uvicorn api:app";
  }
}

async function loadStats() {
  const box = document.getElementById("stats");
  try {
    const response = await fetch(`${API_BASE}/api/stats`);
    const data = await response.json();
    if (!data.runs) {
      box.textContent = "No runs logged yet.";
      return;
    }
    box.textContent =
      `${data.runs} runs logged · ${data.outputs} outputs produced · ` +
      `average critic score ${data.avg_score}/5 · ₹${data.cost_inr} spent`;
  } catch (error) {
    box.textContent = "";
  }
}

/* --- rendering ---------------------------------------------------------- */

function scoreBadge(item) {
  const flagged = item.status !== "ok";
  const label = item.score ? `${item.score}/5` : item.status;
  return `<span class="score${flagged ? " flagged" : ""}">${escapeHtml(label)}</span>`;
}

function renderSummary(obj) {
  const bullets = (obj.bullets || [])
    .map((bullet) => `<li>${escapeHtml(bullet)}</li>`)
    .join("");
  const terms = (obj.key_terms || []).map(escapeHtml).join(", ");
  return `
    <p>${escapeHtml(obj.summary || "")}</p>
    <ul>${bullets}</ul>
    ${terms ? `<p><small>Key terms: ${terms}</small></p>` : ""}
  `;
}

function renderQuiz(obj) {
  return (obj.questions || [])
    .map((question, index) => {
      const options = (question.options || [])
        .map((option, position) => {
          const correct = position === question.answer_index ? " correct" : "";
          return `<div class="quiz-option${correct}">${escapeHtml(option)}</div>`;
        })
        .join("");
      return `
        <div class="quiz-question">
          <strong>Q${index + 1}. ${escapeHtml(question.question || "")}</strong>
          ${options}
          <div class="quiz-option"><em>${escapeHtml(question.explanation || "")}</em></div>
        </div>
      `;
    })
    .join("");
}

function renderFlashcards(obj) {
  const cards = (obj.cards || [])
    .map(
      (card) => `
      <div class="flashcard">
        <b>${escapeHtml(card.front || "")}</b>
        <span>${escapeHtml(card.back || "")}</span>
      </div>`
    )
    .join("");
  return `<div class="flashcard-grid">${cards}</div>`;
}

function renderReport(obj) {
  const sections = (obj.sections || [])
    .map(
      (section) => `
      <h4>${escapeHtml(section.heading || "")}</h4>
      <p>${escapeHtml(section.body || "")}</p>`
    )
    .join("");
  return `<h4>${escapeHtml(obj.title || "")}</h4>${sections}`;
}

function renderSlides(obj) {
  return (obj.slides || [])
    .map((slide, index) => {
      const bullets = (slide.bullets || [])
        .map((bullet) => `<li>${escapeHtml(bullet)}</li>`)
        .join("");
      return `
        <div class="quiz-question">
          <strong>${index + 1}. ${escapeHtml(slide.title || "")}</strong>
          <ul>${bullets}</ul>
          ${slide.notes ? `<small>${escapeHtml(slide.notes)}</small>` : ""}
        </div>
      `;
    })
    .join("");
}

const RENDERERS = {
  summary: renderSummary,
  quiz: renderQuiz,
  flashcards: renderFlashcards,
  report: renderReport,
  slides: renderSlides,
};

function renderResults(data) {
  resultBox.innerHTML = "";

  Object.entries(data.outputs).forEach(([name, item]) => {
    const card = document.createElement("article");
    card.className = "card";
    const renderer = RENDERERS[name] || (() => "<p>No preview for this output.</p>");
    const body = item.object ? renderer(item.object) : "<p>This output failed.</p>";
    card.innerHTML = `
      <header>
        <h3>${escapeHtml(LABELS[name] || name)}</h3>
        ${scoreBadge(item)}
      </header>
      ${body}
    `;
    resultBox.appendChild(card);
  });

  if (data.translation && data.translation.status === "ok") {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <header><h3>Translation · ${escapeHtml(data.translation.language)}</h3></header>
      <p>${escapeHtml(data.translation.text)}</p>
    `;
    resultBox.appendChild(card);
  }

  const footer = document.createElement("p");
  footer.className = "status";
  footer.textContent =
    `Run ${data.id} · ${data.status} · ${(data.duration_ms / 1000).toFixed(1)}s · ` +
    `₹${data.cost_inr}`;
  resultBox.appendChild(footer);
}

/* --- the request -------------------------------------------------------- */

async function transform(event) {
  event.preventDefault();

  const text = source.value.trim();
  const outputs = chosenOutputs();

  if (text.length < 200) {
    setStatus("Paste at least 200 characters — the model needs something to read.", true);
    return;
  }
  if (outputs.length === 0) {
    setStatus("Choose at least one output.", true);
    return;
  }
  if (outputs.length > 3) {
    setStatus("The demo produces at most three outputs per request.", true);
    return;
  }

  runButton.disabled = true;
  resultBox.innerHTML = "";
  setStatus("Reading the document, then writing… this takes 20–60 seconds.");

  try {
    const response = await fetch(`${API_BASE}/api/transform`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        outputs,
        translate_to: translateBox.checked ? languageSelect.value : null,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      setStatus(data.detail || "The server refused the request.", true);
      return;
    }

    setStatus(`Done in ${(data.duration_ms / 1000).toFixed(1)}s.`);
    renderResults(data);
    loadStats();
  } catch (error) {
    setStatus("Could not reach the API. Is uvicorn running?", true);
  } finally {
    runButton.disabled = false;
  }
}

/* --- wiring ------------------------------------------------------------- */

source.addEventListener("input", () => {
  count.textContent = source.value.length;
});

translateBox.addEventListener("change", () => {
  languageSelect.disabled = !translateBox.checked;
});

form.addEventListener("submit", transform);

loadHealth();
loadStats();
