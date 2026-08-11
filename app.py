#!/usr/bin/env python3
from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from pathlib import Path
from urllib.parse import urlparse

CLIENT_DIR = Path(__file__).parent / "client"

CATALOG = {
    "cpu": [
        {"id": "r5-7600", "name": "AMD Ryzen 5 7600", "price": 829, "socket": "AM5", "power": 88, "tier": 3},
        {"id": "r7-7800x3d", "name": "AMD Ryzen 7 7800X3D", "price": 1599, "socket": "AM5", "power": 120, "tier": 5},
    ],
    "motherboard": [
        {"id": "b650m", "name": "MSI B650M Gaming Plus WiFi", "price": 639, "socket": "AM5", "ram": "DDR5", "formFactor": "Micro-ATX", "power": 45},
        {"id": "b550", "name": "ASUS TUF Gaming B550-Plus", "price": 589, "socket": "AM4", "ram": "DDR4", "formFactor": "ATX", "power": 40},
    ],
    "case": [
        {"id": "m-atx-compact", "name": "Cooler Master Q300L V2", "price": 249, "supportedFormFactors": ["Micro-ATX", "Mini-ITX"]},
        {"id": "atx-airflow", "name": "Endorfy Ventum 500 Air", "price": 329, "supportedFormFactors": ["ATX", "Micro-ATX", "Mini-ITX"]},
    ],
    "ram": [
        {"id": "ddr5-32", "name": "Kingston Fury 32 GB (2x16) DDR5-6000", "price": 519, "type": "DDR5", "modules": 2, "power": 10},
        {"id": "ddr4-32", "name": "Corsair Vengeance 32 GB (2x16) DDR4-3600", "price": 299, "type": "DDR4", "modules": 2, "power": 10},
    ],
    "gpu": [
        {"id": "rtx-5070", "name": "Gigabyte RTX 5070 Windforce OC 12 GB", "price": 2899, "power": 250, "tier": 5, "connectors": 2},
        {"id": "rtx-5060", "name": "ASUS Dual RTX 5060 8 GB", "price": 1699, "power": 145, "tier": 3, "connectors": 1},
    ],
    "psu": [
        {"id": "650w", "name": "be quiet! Pure Power 12 M 650 W", "price": 469, "watts": 650, "pcie": 2},
        {"id": "550w", "name": "Corsair CX550 550 W", "price": 319, "watts": 550, "pcie": 1},
    ],
}

CATEGORY_LABELS = {
    "cpu": "procesor",
    "motherboard": "płyta główna",
    "case": "obudowa",
    "ram": "pamięć RAM",
    "gpu": "karta graficzna",
    "psu": "zasilacz",
}


def selected_parts(selection: dict[str, str]) -> dict[str, dict]:
    parts = {}
    for category, product_id in selection.items():
        catalog = CATALOG.get(category, [])
        product = next((item for item in catalog if item["id"] == product_id), None)
        if product:
            parts[category] = product
    return parts


def analyze(selection: dict[str, str], budget: int | None = None) -> dict:
    parts = selected_parts(selection)
    issues = []

    def issue(level: str, message: str) -> None:
        issues.append({"level": level, "message": message})

    for category, label in CATEGORY_LABELS.items():
        product_id = selection.get(category)
        if product_id is None:
            issue("blocking", f"Brakuje danych o kategorii: {label}.")
        elif category not in parts:
            issue("blocking", f"Nie rozpoznano wybranego produktu w kategorii: {label}.")
    for category in selection:
        if category not in CATALOG:
            issue("blocking", f"Nie rozpoznano kategorii komponentu: {category}.")

    cpu, board, ram = parts.get("cpu"), parts.get("motherboard"), parts.get("ram")
    gpu, psu, case = parts.get("gpu"), parts.get("psu"), parts.get("case")
    if cpu and board and cpu["socket"] != board["socket"]:
        issue("blocking", f"Procesor wymaga socketu {cpu['socket']}, a płyta ma {board['socket']}.")
    if board and ram and board["ram"] != ram["type"]:
        issue("blocking", f"Płyta obsługuje {board['ram']}, a wybrana pamięć to {ram['type']}.")
    if board and case:
        board_form_factor = board["formFactor"]
        supported_form_factors = case["supportedFormFactors"]
        if board_form_factor in supported_form_factors:
            issue("info", f"Obudowa obsługuje płytę główną w formacie {board_form_factor}.")
        else:
            issue("blocking", f"Obudowa nie mieści płyty głównej w formacie {board_form_factor}.")
    if ram and ram["modules"] == 1:
        issue("warning", "Jeden moduł RAM ogranicza pracę w dwóch kanałach pamięci.")
    if gpu and psu and psu["pcie"] < gpu["connectors"]:
        issue("blocking", "Zasilacz nie ma wystarczającej liczby złączy PCIe dla karty graficznej.")

    component_power = sum(part.get("power", 0) for part in parts.values())
    recommended_power = ceil(component_power * 1.35 / 50) * 50
    if psu and psu["watts"] < recommended_power:
        issue("warning", f"Szacowane zapotrzebowanie z zapasem to {recommended_power} W, a zasilacz ma {psu['watts']} W.")
    elif psu:
        issue("info", f"Zasilacz zapewnia zapas dla szacowanego zapotrzebowania {recommended_power} W.")
    if cpu and gpu and gpu["tier"] - cpu["tier"] >= 2:
        issue("warning", "Karta graficzna jest wyraźnie mocniejsza od procesora; w grach CPU może ograniczać jej wydajność.")

    total = sum(part["price"] for part in parts.values())
    if budget is not None and total > budget:
        issue("warning", f"Zestaw przekracza budżet o {total - budget} zł.")

    return {
        "issues": issues,
        "total": total,
        "power": component_power,
        "recommendedPower": recommended_power,
        "remainingBudget": None if budget is None else budget - total,
        "isCompatible": not any(item["level"] == "blocking" for item in issues),
    }


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/catalog":
            self.respond_json(CATALOG)
            return
        if path == "/api/analyze":
            self.respond_json(analyze({}))
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError
            selection = payload.get("selection", {})
            budget = payload.get("budget")
            if not isinstance(selection, dict) or (budget is not None and (isinstance(budget, bool) or not isinstance(budget, int))):
                raise ValueError
            self.respond_json(analyze(selection, budget))
        except (json.JSONDecodeError, TypeError, ValueError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Nieprawidlowe dane konfiguracji")

    def respond_json(self, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), partial(Handler, directory=str(CLIENT_DIR)))


if __name__ == "__main__":
    server = create_server()
    print("Demo: http://127.0.0.1:8000")
    server.serve_forever()
