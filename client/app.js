const labels = { cpu: "Procesor", motherboard: "Płyta główna", case: "Obudowa", cooler: "Chłodzenie", disk: "Dysk", ram: "Pamięć RAM", gpu: "Karta graficzna", psu: "Zasilacz" };
const categoryFields = Object.entries(labels);
const storageKey = "pc-builder-configuration";
let catalog = {};
let analysisVersion = 0;

function money(value) { return `${String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} zł`; }

function selection() {
  return Object.fromEntries(categoryFields.map(([category]) => [
    category,
    document.querySelector(`[name="${category}"]`).value,
  ]));
}

function configuration() {
  return {
    selection: selection(),
    budget: Number(document.querySelector("#budget").value),
  };
}

function saveConfiguration() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(configuration()));
  } catch {
    // Storage may be unavailable, but the form should remain usable.
  }
}

function restoreConfiguration() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(storageKey));
  } catch {
    return;
  }
  if (!saved || typeof saved !== "object") return;

  categoryFields.forEach(([category]) => {
    const value = saved.selection?.[category];
    const field = document.querySelector(`[name="${category}"]`);
    if (typeof value === "string" && Array.from(field.options).some((option) => option.value === value)) {
      field.value = value;
    }
  });
  if (Number.isFinite(saved.budget)) {
    document.querySelector("#budget").value = String(saved.budget);
  }
}

function selectedPart(category) {
  const field = document.querySelector(`[name="${category}"]`);
  return catalog[category].find((part) => part.id === field.value);
}

function renderCatalog() {
  const fields = document.querySelector("#component-fields");
  fields.innerHTML = categoryFields.map(([category, label]) => `
    <div class="component-field">
      <label>${label}<select name="${category}">${catalog[category].map((part, index) =>
        `<option value="${part.id}" ${index === 0 ? "selected" : ""}>${part.name} | ${money(part.price)}</option>`).join("")}</select></label>
      <a class="offer-link" data-offer-link="${category}" target="_blank" rel="noopener noreferrer">Oferta x-kom</a>
    </div>`).join("");
}

function updateOfferLinks() {
  categoryFields.forEach(([category, label]) => {
    const part = selectedPart(category);
    const link = document.querySelector(`[data-offer-link="${category}"]`);
    link.href = part.offerUrl;
    link.textContent = `Otwórz ofertę x-kom: ${part.name}`;
    link.setAttribute("aria-label", `Oferta x-kom: ${label} ${part.name}`);
  });
}

async function refresh() {
  const version = ++analysisVersion;
  const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(configuration()) });
  const report = await response.json();
  if (version !== analysisVersion) return;
  const status = document.querySelector("#status");
  status.textContent = report.isCompatible ? "Zestaw jest kompatybilny" : "Zestaw wymaga zmian";
  document.querySelector("#status-dot").className = report.isCompatible ? "ok" : "blocked";
  document.querySelector("#total").textContent = money(report.total);
  document.querySelector("#remaining").textContent = money(report.remainingBudget);
  document.querySelector("#power").textContent = `${report.power} W`;
  document.querySelector("#recommended").textContent = `${report.recommendedPower} W`;
  document.querySelector("#issues").innerHTML = report.issues.map((issue) => `<li class="${issue.level}"><b>${issue.level === "blocking" ? "Blokuje" : issue.level === "warning" ? "Uwaga" : "Info"}</b>${issue.message}</li>`).join("") || "<li class=info><b>Info</b>Dodaj części, aby zobaczyć analizę.</li>";
}

async function boot() {
  catalog = await fetch("/api/catalog").then((response) => response.json());
  renderCatalog();
  restoreConfiguration();
  updateOfferLinks();
  document.querySelector("#builder").addEventListener("input", () => {
    updateOfferLinks();
    saveConfiguration();
    refresh();
  });
  refresh();
}

boot();
