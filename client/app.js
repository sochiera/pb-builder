const labels = { cpu: "Procesor", motherboard: "Płyta główna", case: "Obudowa", cooler: "Chłodzenie", ram: "Pamięć RAM", gpu: "Karta graficzna", psu: "Zasilacz" };
let catalog = {};
let analysisVersion = 0;

function money(value) { return `${value.toLocaleString("pl-PL")} zł`; }

function selection() {
  return Object.fromEntries(Object.entries(labels).map(([category]) => [
    category,
    document.querySelector(`[name="${category}"]`).value,
  ]));
}

function renderCatalog() {
  const fields = document.querySelector("#component-fields");
  fields.innerHTML = Object.entries(labels).map(([category, label]) => `
    <label>${label}<select name="${category}">${catalog[category].map((part, index) =>
      `<option value="${part.id}" ${index === 0 ? "selected" : ""}>${part.name} | ${money(part.price)}</option>`).join("")}</select></label>`).join("");
}

async function refresh() {
  const version = ++analysisVersion;
  const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selection: selection(), budget: Number(document.querySelector("#budget").value) }) });
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
  document.querySelector("#builder").addEventListener("input", refresh);
  refresh();
}

boot();
