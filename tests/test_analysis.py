import base64
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app import Handler, analyze, create_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_socket_bytes(sock, length):
    chunks = []
    while sum(map(len, chunks)) < length:
        chunk = sock.recv(length - sum(map(len, chunks)))
        if not chunk:
            raise RuntimeError("Chromium DevTools connection closed unexpectedly")
        chunks.append(chunk)
    return b"".join(chunks)


def send_websocket_frame(sock, payload, opcode=1):
    mask = os.urandom(4)
    masked_payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    length = len(payload)
    if length < 126:
        header = bytes([0x80 | opcode, 0x80 | length])
    elif length <= 0xFFFF:
        header = bytes([0x80 | opcode, 0xFE]) + struct.pack("!H", length)
    else:
        header = bytes([0x80 | opcode, 0xFF]) + struct.pack("!Q", length)
    sock.sendall(header + mask + masked_payload)


def read_websocket_message(sock):
    first, second = read_socket_bytes(sock, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_socket_bytes(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_socket_bytes(sock, 8))[0]
    mask = read_socket_bytes(sock, 4) if second & 0x80 else None
    payload = read_socket_bytes(sock, length)
    if mask:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    if opcode == 9:
        send_websocket_frame(sock, payload, opcode=10)
        return read_websocket_message(sock)
    if opcode == 8:
        raise RuntimeError("Chromium DevTools connection closed")
    if opcode != 1:
        return read_websocket_message(sock)
    return json.loads(payload)


def connect_to_cdp(websocket_url):
    parsed = urlsplit(websocket_url)
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {parsed.path}{f'?{parsed.query}' if parsed.query else ''} HTTP/1.1\r\n"
        f"Host: {parsed.hostname}:{parsed.port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    try:
        sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"Chromium DevTools websocket handshake failed: {response!r}")
        return sock
    except Exception:
        sock.close()
        raise

BROWSER_SETUP = """
<script>
window.__testRequests = [];
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  if (init.method === "POST" && String(input).endsWith("/api/analyze")) {
    try {
      window.__testRequests.push(JSON.parse(init.body));
    } catch (error) {
      window.__testRequests.push({ invalidBody: String(init.body) });
    }
  }
  return nativeFetch(input, init);
};

const waitFor = (predicate) => new Promise((resolve, reject) => {
  const deadline = Date.now() + 5000;
  const poll = () => {
    let result;
    try {
      result = predicate();
    } catch (error) {
      reject(error);
      return;
    }
    if (result) {
      resolve(result);
    } else if (Date.now() >= deadline) {
      reject(new Error("Timed out waiting for browser state"));
    } else {
      setTimeout(poll, 25);
    }
  };
  poll();
});

const visible = (selector) => document.querySelector(selector).textContent.replace(/\\s/g, " ").trim();
const issues = () => Array.from(document.querySelectorAll("#issues li"), (item) => ({
  level: item.className,
  text: item.textContent.replace(/\\s/g, " ").trim(),
}));
const publish = (attribute, value) => {
  document.documentElement.setAttribute(
    attribute,
    btoa(unescape(encodeURIComponent(JSON.stringify(value))))
  );
};
</script>
"""

BROWSER_EXERCISE = """
<script>
let stage = "boot";
const compact = (selector) => visible(selector).replace(/\\s(?=\\d)/g, "");

(async () => {
  try {
    await waitFor(() =>
      document.querySelector('select[name="case"]') &&
      document.querySelector('select[name="cooler"]') &&
      document.querySelector('select[name="disk"]') &&
      visible("#total") !== "-"
    );
    const caseField = document.querySelector('select[name="case"]');
    const coolerField = document.querySelector('select[name="cooler"]');
    const diskField = document.querySelector('select[name="disk"]');
    const budgetField = document.querySelector("#budget");
    window.__testRequests.length = 0;

    stage = "compatible disk request";
    diskField.value = "nvme-1tb";
    diskField.dispatchEvent(new Event("input", { bubbles: true }));
    const compatibleDiskRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.disk === "nvme-1tb" &&
      request.budget === 5500
    ));
    await waitFor(() => visible("#status") === "Zestaw jest kompatybilny" &&
      issues().some((issue) =>
        issue.level === "info" &&
        issue.text.includes("NVMe") &&
        issue.text.toLowerCase().includes("dysk")
      )
    );
    const compatibleStatus = visible("#status");
    const compatibleIssues = issues();

    stage = "cooler request";
    coolerField.value = "fortis-5";
    coolerField.dispatchEvent(new Event("input", { bubbles: true }));
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.cooler === "fortis-5" &&
      request.selection.disk === "nvme-1tb" &&
      request.budget === 5500
    ));

    stage = "case request";
    caseField.value = "atx-airflow";
    caseField.dispatchEvent(new Event("input", { bubbles: true }));
    const caseRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.case === "atx-airflow" &&
      request.selection.disk === "nvme-1tb" &&
      request.budget === 5500
    ));

    stage = "budget request";
    budgetField.value = "5000";
    budgetField.dispatchEvent(new Event("input", { bubbles: true }));
    const budgetRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.case === "atx-airflow" &&
      request.selection.disk === "nvme-1tb" &&
      request.budget === 5000
    ));
    stage = "visible totals";
    await waitFor(() => compact("#total") === "6202 zł" && compact("#remaining") === "-1202 zł");
    const compatibleTotal = visible("#total");
    const compatibleRemaining = visible("#remaining");

    stage = "incompatible disk request";
    diskField.value = "sata-1tb";
    diskField.dispatchEvent(new Event("input", { bubbles: true }));
    const incompatibleDiskRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.disk === "sata-1tb" &&
      request.budget === 5000
    ));
    await waitFor(() => visible("#status") === "Zestaw wymaga zmian" &&
      issues().some((issue) =>
        issue.level === "blocking" &&
        issue.text.includes("SATA") &&
        issue.text.toLowerCase().includes("nie obsługuje")
      )
    );

    publish("data-browser-test", {
      caseOptions: Array.from(caseField.options, (option) => option.value),
      coolerOptions: Array.from(coolerField.options, (option) => option.value),
      diskOptions: Array.from(diskField.options, (option) => option.value),
      diskLabels: Array.from(diskField.options, (option) => option.textContent),
      compatibleDiskRequest,
      incompatibleDiskRequest,
      caseRequest,
      budgetRequest,
      compatibleStatus,
      compatibleIssues,
      compatibleTotal,
      compatibleRemaining,
      total: visible("#total"),
      remaining: visible("#remaining"),
      status: document.querySelector("#status").textContent,
      issues: issues(),
      mobileLayout: window.matchMedia("(max-width: 760px)").matches,
    });
  } catch (error) {
    const total = document.querySelector("#total")?.textContent;
    const remaining = document.querySelector("#remaining")?.textContent;
    publish("data-browser-test-error", `${stage}: total=${total}, remaining=${remaining}: ${error.stack || error}`);
  }
})();
</script>
"""

BROWSER_COOLER_EXERCISE = """
<script>
let stage = "boot";

(async () => {
  try {
    await waitFor(() =>
      document.querySelector('select[name="cpu"]') &&
      document.querySelector('select[name="cooler"]') &&
      document.querySelector('select[name="disk"]') &&
      visible("#total") !== "-"
    );
    const cpuField = document.querySelector('select[name="cpu"]');
    const coolerField = document.querySelector('select[name="cooler"]');
    window.__testRequests.length = 0;

    stage = "keyboard access";
    coolerField.focus();
    const keyboardReady = coolerField.tagName === "SELECT" &&
      coolerField.tabIndex >= 0 &&
      document.activeElement === coolerField;
    if (!keyboardReady) throw new Error("cooler select did not accept keyboard focus");
    document.documentElement.setAttribute("data-keyboard-ready", "cooler");

    stage = "cooler change";
    await waitFor(() => coolerField.value === "alpine-23");
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.cooler === "alpine-23" &&
      request.selection.disk === "nvme-1tb"
    ));
    await waitFor(() => visible("#status") === "Zestaw wymaga zmian" &&
      issues().some((issue) =>
        issue.level === "blocking" &&
        issue.text.includes("AM5") &&
        issue.text.toLowerCase().includes("podstawk")
      )
    );

    stage = "compatible cooler";
    document.documentElement.setAttribute("data-keyboard-ready", "restore");
    await waitFor(() => coolerField.value === "fortis-5");
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.cooler === "fortis-5" &&
      request.selection.disk === "nvme-1tb"
    ));

    stage = "cpu change";
    cpuField.value = "r7-7800x3d";
    cpuField.dispatchEvent(new Event("input", { bubbles: true }));
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.cpu === "r7-7800x3d" &&
      request.selection.cooler === "fortis-5" &&
      request.selection.disk === "nvme-1tb"
    ));

    stage = "restore compatible profile";
    cpuField.value = "r5-7600";
    cpuField.dispatchEvent(new Event("input", { bubbles: true }));
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.cpu === "r5-7600" &&
      request.selection.cooler === "fortis-5" &&
      request.selection.disk === "nvme-1tb"
    ));
    await waitFor(() => visible("#status") === "Zestaw jest kompatybilny");

    publish("data-cooler-browser-test", {
      coolerOptions: Array.from(coolerField.options, (option) => option.value),
      keyboardReady,
      mobileLayout: window.matchMedia("(max-width: 760px)").matches,
      issues: issues(),
      status: visible("#status"),
    });
  } catch (error) {
    publish("data-cooler-browser-test-error", `${stage}: ${error.stack || error}`);
  }
})();
</script>
"""

BROWSER_DISK_EXERCISE = """
<script>
let stage = "boot";

(async () => {
  try {
    await waitFor(() =>
      document.querySelector('select[name="disk"]') &&
      visible("#status") === "Zestaw jest kompatybilny" &&
      visible("#total") !== "-"
    );
    const diskField = document.querySelector('select[name="disk"]');
    const workspace = document.querySelector(".workspace");
    window.__testRequests.length = 0;
    const compatibleIssues = issues();
    const compatibleStatus = visible("#status");
    const mobileDisplay = getComputedStyle(workspace).display;
    const mobileColumns = getComputedStyle(workspace).gridTemplateColumns.trim().split(/\\s+/).length;

    stage = "keyboard access";
    diskField.focus();
    const keyboardReady = diskField.tagName === "SELECT" &&
      diskField.tabIndex >= 0 &&
      document.activeElement === diskField;
    if (!keyboardReady) throw new Error("disk select did not accept keyboard focus");
    document.documentElement.setAttribute("data-keyboard-ready", "disk");

    stage = "disk change";
    await waitFor(() => diskField.value === "sata-1tb");
    const incompatibleRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection &&
      request.selection.disk === "sata-1tb"
    ));
    await waitFor(() => visible("#status") === "Zestaw wymaga zmian" &&
      issues().some((issue) =>
        issue.level === "blocking" &&
        issue.text.includes("SATA") &&
        issue.text.toLowerCase().includes("nie obsługuje")
      )
    );

    publish("data-disk-browser-test", {
      compatibleIssues,
      compatibleStatus,
      diskOptions: Array.from(diskField.options, (option) => option.value),
      diskValue: diskField.value,
      incompatibleRequest,
      issues: issues(),
      keyboardReady,
      mobileDisplay,
      mobileColumns,
      mobileLayout: window.matchMedia("(max-width: 760px)").matches,
      status: visible("#status"),
    });
  } catch (error) {
    publish("data-disk-browser-test-error", `${stage}: ${error.stack || error}`);
  }
})();
</script>
"""


BROWSER_PERSISTENCE_EXERCISE = """
<script>
const persistencePhase = new URLSearchParams(window.location.search).get("phase");
const persistenceProfiles = {
  seed: {
    selection: {
      cpu: "r7-7800x3d",
      motherboard: "b550",
      case: "atx-airflow",
      cooler: "alpine-23",
      disk: "sata-1tb",
      ram: "ddr4-32",
      gpu: "rtx-5060",
      psu: "550w",
    },
    budget: 4800,
  },
  changed: {
    selection: {
      cpu: "r5-7600",
      motherboard: "b650m",
      case: "m-atx-compact",
      cooler: "fortis-5",
      disk: "nvme-1tb",
      ram: "ddr5-32",
      gpu: "rtx-5070",
      psu: "650w",
    },
    budget: 7000,
  },
};

const persistenceState = () => ({
  selection: Object.fromEntries(Array.from(
    document.querySelectorAll("#component-fields select"),
    (field) => [field.name, field.value],
  )),
  budget: Number(document.querySelector("#budget").value),
});

const analysisRequestForState = () => {
  const state = persistenceState();
  return window.__testRequests.find((request) =>
    request.selection &&
    request.budget === state.budget &&
    Object.entries(state.selection).every(([name, value]) => request.selection[name] === value)
  );
};

const setPersistenceField = (name, value) => {
  const field = name === "budget"
    ? document.querySelector("#budget")
    : document.querySelector(`[name="${name}"]`);
  field.value = String(value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
};

(async () => {
  let stage = "boot";
  try {
    await waitFor(() =>
      document.querySelector('select[name="cpu"]') &&
      document.querySelector('select[name="psu"]') &&
      document.querySelector("#budget") &&
      document.querySelector("#total") &&
      visible("#total") !== "-"
    );

    const profile = persistenceProfiles[persistencePhase];
    if (profile) {
      stage = `${persistencePhase} input`;
      Object.entries(profile.selection).forEach(([name, value]) => setPersistenceField(name, value));
      setPersistenceField("budget", profile.budget);
      await waitFor(() => {
        const state = persistenceState();
        return state.budget === profile.budget &&
          Object.entries(profile.selection).every(([name, value]) => state.selection[name] === value);
      });
    } else {
      stage = "restore";
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const analysisRequest = await waitFor(() => analysisRequestForState());

    publish("data-persistence-test", {
      phase: persistencePhase,
      ...persistenceState(),
      analysisRequest,
      total: visible("#total"),
      status: visible("#status"),
    });
  } catch (error) {
    publish("data-persistence-test-error", `${stage}: ${error.stack || error}`);
  }
})();
</script>
"""


class BrowserTestHandler(Handler):
    def do_GET(self):
        exercises = {
            "/__browser_test__": BROWSER_EXERCISE,
            "/__cooler_test__": BROWSER_COOLER_EXERCISE,
            "/__disk_test__": BROWSER_DISK_EXERCISE,
            "/__persistence_test__": BROWSER_PERSISTENCE_EXERCISE,
        }
        exercise = exercises.get(urlsplit(self.path).path)
        if exercise is not None:
            page = (PROJECT_ROOT / "client" / "index.html").read_text()
            page = page.replace(
                '  <script src="app.js"></script>',
                f"{BROWSER_SETUP}  <script src=\"app.js\"></script>{exercise}",
            )
            encoded = page.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        super().do_GET()


class AnalysisTest(unittest.TestCase):
    def test_detects_socket_and_memory_conflicts(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b550",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
        }, 5000)

        messages = [issue["message"] for issue in report["issues"]]
        self.assertFalse(report["isCompatible"])
        self.assertTrue(any("socketu AM5" in message for message in messages))
        self.assertTrue(any("DDR4" in message for message in messages))

    def test_detects_insufficient_pcie_connectors(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5070",
            "psu": "550w",
        })

        self.assertFalse(report["isCompatible"])
        self.assertTrue(any(
            issue["level"] == "blocking" and "złączy PCIe" in issue["message"]
            for issue in report["issues"]
        ))

    def test_rounds_recommended_power_up_to_next_50_watts(self):
        report = analyze({
            "cpu": "r7-7800x3d",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5070",
            "psu": "650w",
        })

        self.assertEqual(report["power"], 425)
        self.assertEqual(report["recommendedPower"], 600)

    def test_calculates_total_and_remaining_budget(self):
        report = analyze({"cpu": "r5-7600", "gpu": "rtx-5060"}, 3000)

        self.assertEqual(report["total"], 2528)
        self.assertEqual(report["remainingBudget"], 472)

    def test_blocks_missing_or_unknown_product_data(self):
        empty_report = analyze({})
        unknown_report = analyze({
            "cpu": "unknown-cpu",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
        })

        self.assertFalse(empty_report["isCompatible"])
        self.assertFalse(unknown_report["isCompatible"])
        self.assertTrue(any(issue["level"] == "blocking" for issue in empty_report["issues"]))
        self.assertTrue(any("Nie rozpoznano" in issue["message"] for issue in unknown_report["issues"]))

    def test_blocks_configuration_without_case(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
        })

        self.assertTrue(any(
            issue["level"] == "blocking" and "obudowa" in issue["message"].lower()
            for issue in report["issues"]
        ))
        self.assertFalse(report["isCompatible"])

    def test_blocks_configuration_with_unknown_case(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "unknown-case",
        })

        self.assertTrue(any(
            issue["level"] == "blocking" and "obudowa" in issue["message"].lower()
            for issue in report["issues"]
        ))
        self.assertFalse(report["isCompatible"])

    def test_blocks_configuration_without_or_with_unknown_cooler(self):
        base_selection = {
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
        }

        for label, cooler in (("missing", None), ("unknown", "unknown-cooler")):
            with self.subTest(cooler=label):
                selection = dict(base_selection)
                if cooler is not None:
                    selection["cooler"] = cooler

                report = analyze(selection)

                self.assertFalse(report["isCompatible"])
                self.assertTrue(any(
                    issue["level"] == "blocking"
                    and "chłodzenie" in issue["message"].lower()
                    for issue in report["issues"]
                ))

    def test_blocks_configuration_without_or_with_unknown_disk(self):
        base_selection = {
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
        }

        for label, disk in (
            ("missing", None),
            ("unknown", "unknown-disk"),
            ("unsupported", "r5-7600"),
        ):
            with self.subTest(disk=label):
                selection = dict(base_selection)
                if disk is not None:
                    selection["disk"] = disk

                report = analyze(selection)

                self.assertFalse(report["isCompatible"])
                self.assertTrue(any(
                    issue["level"] == "blocking"
                    and "dysk" in issue["message"].lower()
                    for issue in report["issues"]
                ))

    def test_accepts_case_that_supports_motherboard_form_factor(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
            "disk": "nvme-1tb",
        })

        self.assertTrue(report["isCompatible"])
        self.assertFalse(any(
            issue["level"] == "blocking" and "format" in issue["message"].lower()
            for issue in report["issues"]
        ))
        self.assertTrue(any(
            issue["level"] == "info"
            and "Micro-ATX" in issue["message"]
            and "obudowa" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_rejects_cooler_that_does_not_support_cpu_socket(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "alpine-23",
        })

        self.assertFalse(report["isCompatible"])
        self.assertTrue(any(
            issue["level"] == "blocking"
            and "chłodzenie" in issue["message"].lower()
            and "AM5" in issue["message"]
            and "podstawk" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_accepts_disk_that_supports_motherboard_interface(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
            "disk": "nvme-1tb",
        })

        self.assertTrue(report["isCompatible"])
        self.assertFalse(any(
            issue["level"] == "blocking"
            and "dysk" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_accepts_sata_disk_on_b550(self):
        report = analyze({
            "motherboard": "b550",
            "disk": "sata-1tb",
        })

        self.assertTrue(any(
            issue["level"] == "info"
            and "SATA" in issue["message"]
            and "dysk" in issue["message"].lower()
            for issue in report["issues"]
        ))
        self.assertFalse(any(
            issue["level"] == "blocking"
            and "dysk" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_rejects_disk_that_does_not_support_motherboard_interface(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
            "disk": "sata-1tb",
        })

        self.assertFalse(report["isCompatible"])
        self.assertTrue(any(
            issue["level"] == "blocking"
            and "dysk" in issue["message"].lower()
            and "interfejsu" in issue["message"].lower()
            and "SATA" in issue["message"]
            and "nie obsługuje" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_rejects_case_that_does_not_support_motherboard_form_factor(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b550",
            "ram": "ddr4-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
        })

        self.assertFalse(report["isCompatible"])
        self.assertTrue(any(
            issue["level"] == "blocking"
            and "ATX" in issue["message"]
            and "obudowa" in issue["message"].lower()
            for issue in report["issues"]
        ))

    def test_includes_case_price_in_total(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
        }, 5000)

        self.assertEqual(report["total"], 4404)
        self.assertEqual(report["remainingBudget"], 596)

    def test_includes_cooler_price_in_total_and_budget(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
        }, 5000)

        self.assertEqual(report["total"], 4623)
        self.assertEqual(report["remainingBudget"], 377)

    def test_includes_disk_price_in_total_and_budget(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
            "disk": "nvme-1tb",
        }, 5000)

        self.assertEqual(report["total"], 4922)
        self.assertEqual(report["remainingBudget"], 78)


class MakefileTest(unittest.TestCase):
    def test_hardware_profile_passes_with_required_case(self):
        result = subprocess.run(
            ["make", "hardware"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hardware profile passed", result.stdout)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def read_asset(self, path):
        with urlopen(f"{self.base_url}{path}") as response:
            return response.read().decode()

    def test_serves_client_assets_only(self):
        page = self.read_asset("/")
        self.assertIn("inteligentny konfigurator PC", page)

        for path in ("/app.py", "/tests/test_analysis.py", "/docs/PROJECT.md"):
            with self.assertRaises(HTTPError) as error:
                urlopen(f"{self.base_url}{path}")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def run_browser_page(self, path, keyboard_steps=(), result_attribute="data-cooler-browser-test"):
        browser = shutil.which("chromium-browser") or shutil.which("chromium")
        if browser is None:
            self.skipTest("headless Chromium is not installed")

        browser_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(BrowserTestHandler, directory=str(PROJECT_ROOT / "client")),
        )
        browser_thread = threading.Thread(target=browser_server.serve_forever)
        browser_thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="pb-builder-browser-") as profile:
                command = [
                    browser,
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--window-size=600,800",
                    f"--user-data-dir={profile}",
                    f"http://127.0.0.1:{browser_server.server_port}{path}",
                ]
                if not keyboard_steps:
                    return subprocess.run(
                        [*command, "--virtual-time-budget=10000", "--dump-dom"],
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )

                debug_socket = socket.socket()
                debug_socket.bind(("127.0.0.1", 0))
                debug_port = debug_socket.getsockname()[1]
                debug_socket.close()
                process = subprocess.Popen(
                    [
                        *command,
                        f"--remote-debugging-port={debug_port}",
                        "--remote-allow-origins=*",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                cdp_socket = None
                command_id = 0

                def cdp_call(method, params=None, session_id=None):
                    nonlocal command_id
                    command_id += 1
                    message = {"id": command_id, "method": method}
                    if params is not None:
                        message["params"] = params
                    if session_id is not None:
                        message["sessionId"] = session_id
                    send_websocket_frame(cdp_socket, json.dumps(message).encode())
                    while True:
                        response = read_websocket_message(cdp_socket)
                        if response.get("id") == command_id:
                            if "error" in response:
                                raise RuntimeError(response["error"])
                            return response["result"]

                try:
                    deadline = time.monotonic() + 10
                    target = None
                    while target is None and time.monotonic() < deadline:
                        try:
                            with urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=1) as response:
                                targets = json.loads(response.read().decode())
                        except OSError:
                            targets = []
                        target = next((candidate for candidate in targets
                                       if candidate["type"] == "page"
                                       and path in candidate["url"]
                                       and candidate.get("webSocketDebuggerUrl")), None)
                        if target is None:
                            time.sleep(0.025)
                    if target is None:
                        raise TimeoutError("Chromium page target did not start")

                    cdp_socket = connect_to_cdp(target["webSocketDebuggerUrl"])
                    session_id = cdp_call("Target.attachToTarget", {
                        "targetId": target["id"],
                        "flatten": True,
                    })["sessionId"]

                    def evaluate(expression):
                        result = cdp_call(
                            "Runtime.evaluate",
                            {"expression": expression, "returnByValue": True},
                            session_id,
                        )
                        if "exceptionDetails" in result:
                            raise RuntimeError(result["exceptionDetails"])
                        return result["result"].get("value")

                    def wait_for(expression):
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            if evaluate(expression):
                                return
                            time.sleep(0.025)
                        raise TimeoutError(f"Timed out waiting for {expression}")

                    key_codes = {"ArrowDown": 40, "ArrowUp": 38}
                    for keyboard_step in keyboard_steps:
                        marker, key, *target = keyboard_step
                        wait_for(f"document.documentElement.getAttribute('data-keyboard-ready') === {json.dumps(marker)}")
                        key_code = key_codes[key]
                        repetitions = 1
                        if target:
                            if len(target) != 1:
                                raise ValueError("keyboard target must contain one option value")
                            selector = json.dumps(f'select[name="{marker}"]')
                            value = json.dumps(target[0])
                            repetitions = evaluate(
                                f"(() => {{"
                                f"const field = document.querySelector({selector});"
                                f"const options = Array.from(field.options);"
                                f"const current = options.findIndex((option) => option.value === field.value);"
                                f"const desired = options.findIndex((option) => option.value === {value});"
                                f"if (current < 0 || desired < 0 || options.length === 0) return -1;"
                                f"return (desired - current + options.length) % options.length || options.length;"
                                f"}})()"
                            )
                            if repetitions < 1:
                                raise ValueError(f"keyboard target {target[0]!r} is not reachable")
                        for _ in range(repetitions):
                            for event_type in ("keyDown", "keyUp"):
                                cdp_call("Input.dispatchKeyEvent", {
                                    "type": event_type,
                                    "key": key,
                                    "code": key,
                                    "windowsVirtualKeyCode": key_code,
                                    "nativeVirtualKeyCode": key_code,
                                }, session_id)

                    wait_for(
                        f"document.documentElement.hasAttribute({json.dumps(result_attribute)}) || "
                        f"document.documentElement.hasAttribute({json.dumps(result_attribute + '-error')})"
                    )
                    dom = evaluate("document.documentElement.outerHTML")
                    result = subprocess.CompletedProcess(command, 0, dom, "")
                except Exception as error:
                    result = subprocess.CompletedProcess(command, 1, "", str(error))
                finally:
                    if cdp_socket is not None:
                        cdp_socket.close()
                    process.terminate()
                    try:
                        _, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        _, stderr = process.communicate()
                    if stderr:
                        result.stderr = f"{result.stderr}\n{stderr.decode(errors='replace')}".strip()
                return result
        finally:
            browser_server.shutdown()
            browser_server.server_close()
            browser_thread.join()

    def run_browser_persistence_pages(self):
        browser = shutil.which("chromium-browser") or shutil.which("chromium")
        if browser is None:
            self.skipTest("headless Chromium is not installed")

        browser_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(BrowserTestHandler, directory=str(PROJECT_ROOT / "client")),
        )
        browser_thread = threading.Thread(target=browser_server.serve_forever)
        browser_thread.start()
        try:
            def run_phase(profile, phase):
                command = [
                    browser,
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--window-size=600,800",
                    f"--user-data-dir={profile}",
                    f"http://127.0.0.1:{browser_server.server_port}/__persistence_test__?phase={phase}",
                    "--virtual-time-budget=10000",
                    "--dump-dom",
                ]
                return subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

            with (
                tempfile.TemporaryDirectory(prefix="pb-builder-persistence-") as profile,
                tempfile.TemporaryDirectory(prefix="pb-builder-fresh-") as fresh_profile,
            ):
                results = {
                    phase: run_phase(profile, phase)
                    for phase in ("seed", "restore-initial", "changed", "restore-latest")
                }
                results["fresh"] = run_phase(fresh_profile, "fresh")
                return results
        finally:
            browser_server.shutdown()
            browser_server.server_close()
            browser_thread.join()

    def read_persistence_state(self, result, phase):
        self.assertEqual(result.returncode, 0, result.stderr)
        error_match = re.search(r'data-persistence-test-error="([^"]+)"', result.stdout)
        if error_match:
            error = base64.b64decode(error_match.group(1)).decode()
            self.fail(f"persistence browser behavior test failed during {phase}: {error}")

        result_match = re.search(r'data-persistence-test="([^"]+)"', result.stdout)
        self.assertIsNotNone(
            result_match,
            f"persistence browser behavior test produced no result during {phase}:\n"
            f"{result.stderr}\n{result.stdout}",
        )
        state = json.loads(base64.b64decode(result_match.group(1)).decode())
        self.assertEqual(state["phase"], phase)
        return state

    def test_client_updates_analysis_and_formats_totals_in_browser(self):
        result = self.run_browser_page("/__browser_test__")

        self.assertEqual(result.returncode, 0, result.stderr)
        error_match = re.search(r'data-browser-test-error="([^"]+)"', result.stdout)
        if error_match:
            error = base64.b64decode(error_match.group(1)).decode()
            self.fail(f"browser behavior test failed: {error}")

        result_match = re.search(r'data-browser-test="([^"]+)"', result.stdout)
        self.assertIsNotNone(
            result_match,
            f"browser behavior test produced no result:\n{result.stderr}\n{result.stdout}",
        )
        browser_report = json.loads(base64.b64decode(result_match.group(1)).decode())

        self.assertIn("atx-airflow", browser_report["caseOptions"])
        self.assertIn("fortis-5", browser_report["coolerOptions"])
        self.assertIn("nvme-1tb", browser_report["diskOptions"])
        self.assertIn("sata-1tb", browser_report["diskOptions"])
        self.assertTrue(any("299" in label for label in browser_report["diskLabels"]))
        self.assertTrue(browser_report["mobileLayout"])
        self.assertEqual(
            browser_report["compatibleDiskRequest"]["selection"]["disk"],
            "nvme-1tb",
        )
        self.assertEqual(
            browser_report["incompatibleDiskRequest"]["selection"]["disk"],
            "sata-1tb",
        )
        self.assertEqual(browser_report["caseRequest"]["budget"], 5500)
        self.assertEqual(browser_report["budgetRequest"]["budget"], 5000)
        self.assertEqual(
            browser_report["budgetRequest"]["selection"],
            {
                "cpu": "r5-7600",
                "motherboard": "b650m",
                "case": "atx-airflow",
                "cooler": "fortis-5",
                "ram": "ddr5-32",
                "gpu": "rtx-5070",
                "psu": "650w",
                "disk": "nvme-1tb",
            },
        )
        self.assertEqual(browser_report["compatibleStatus"], "Zestaw jest kompatybilny")
        self.assertTrue(any(
            issue["level"] == "info"
            and "NVMe" in issue["text"]
            and "dysk" in issue["text"].lower()
            for issue in browser_report["compatibleIssues"]
        ))
        for actual, expected in (
            (browser_report["compatibleTotal"], "6202"),
            (browser_report["compatibleRemaining"], "-1202"),
            (browser_report["total"], "6232"),
            (browser_report["remaining"], "-1232"),
        ):
            parts = actual.split()
            self.assertEqual(parts[-1], "zł")
            self.assertEqual("".join(parts[:-1]), expected)
        self.assertEqual(browser_report["status"], "Zestaw wymaga zmian")
        self.assertTrue(any(
            issue["level"] == "blocking"
            and "SATA" in issue["text"]
            and "nie obsługuje" in issue["text"].lower()
            for issue in browser_report["issues"]
        ))

    def test_cooler_selection_refreshes_analysis_and_explains_socket_in_browser(self):
        result = self.run_browser_page(
            "/__cooler_test__",
            (("cooler", "ArrowDown"), ("restore", "ArrowUp")),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        error_match = re.search(r'data-cooler-browser-test-error="([^"]+)"', result.stdout)
        if error_match:
            error = base64.b64decode(error_match.group(1)).decode()
            self.fail(f"browser behavior test failed: {error}")

        result_match = re.search(r'data-cooler-browser-test="([^"]+)"', result.stdout)
        self.assertIsNotNone(
            result_match,
            f"browser behavior test produced no result:\n{result.stderr}\n{result.stdout}",
        )
        browser_report = json.loads(base64.b64decode(result_match.group(1)).decode())

        self.assertIn("fortis-5", browser_report["coolerOptions"])
        self.assertTrue(browser_report["keyboardReady"])
        self.assertTrue(browser_report["mobileLayout"])
        self.assertEqual(browser_report["status"], "Zestaw jest kompatybilny")
        self.assertTrue(any(
            issue["level"] == "info"
            and "chłodzenie" in issue["text"].lower()
            and "AM5" in issue["text"]
            and "podstawk" in issue["text"].lower()
            for issue in browser_report["issues"]
        ), "compatible cooler result must explain CPU socket support")

    def test_disk_selection_works_with_keyboard_and_explains_interface_in_browser(self):
        result = self.run_browser_page(
            "/__disk_test__",
            (("disk", "ArrowDown", "sata-1tb"),),
            "data-disk-browser-test",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        error_match = re.search(r'data-disk-browser-test-error="([^"]+)"', result.stdout)
        if error_match:
            error = base64.b64decode(error_match.group(1)).decode()
            self.fail(f"browser behavior test failed: {error}")

        result_match = re.search(r'data-disk-browser-test="([^"]+)"', result.stdout)
        self.assertIsNotNone(
            result_match,
            f"browser behavior test produced no result:\n{result.stderr}\n{result.stdout}",
        )
        browser_report = json.loads(base64.b64decode(result_match.group(1)).decode())

        self.assertIn("nvme-1tb", browser_report["diskOptions"])
        self.assertIn("sata-1tb", browser_report["diskOptions"])
        self.assertTrue(browser_report["keyboardReady"])
        self.assertTrue(browser_report["mobileLayout"])
        self.assertEqual(browser_report["mobileDisplay"], "grid")
        self.assertEqual(browser_report["mobileColumns"], 1)
        self.assertEqual(browser_report["compatibleStatus"], "Zestaw jest kompatybilny")
        self.assertTrue(any(
            issue["level"] == "info"
            and "NVMe" in issue["text"]
            and "dysk" in issue["text"].lower()
            for issue in browser_report["compatibleIssues"]
        ))
        self.assertEqual(browser_report["diskValue"], "sata-1tb")
        self.assertEqual(
            browser_report["incompatibleRequest"]["selection"]["disk"],
            "sata-1tb",
        )
        self.assertEqual(browser_report["status"], "Zestaw wymaga zmian")
        self.assertTrue(any(
            issue["level"] == "blocking"
            and "SATA" in issue["text"]
            and "nie obsługuje" in issue["text"].lower()
            for issue in browser_report["issues"]
        ))

    def test_selection_and_budget_survive_reopen_and_restore_latest_state(self):
        results = self.run_browser_persistence_pages()
        states = {
            phase: self.read_persistence_state(result, phase)
            for phase, result in results.items()
        }
        fresh = {
            "selection": {
                "cpu": "r5-7600",
                "motherboard": "b650m",
                "case": "m-atx-compact",
                "cooler": "fortis-5",
                "disk": "nvme-1tb",
                "ram": "ddr5-32",
                "gpu": "rtx-5070",
                "psu": "650w",
            },
            "budget": 5500,
        }
        initial = {
            "selection": {
                "cpu": "r7-7800x3d",
                "motherboard": "b550",
                "case": "atx-airflow",
                "cooler": "alpine-23",
                "disk": "sata-1tb",
                "ram": "ddr4-32",
                "gpu": "rtx-5060",
                "psu": "550w",
            },
            "budget": 4800,
        }
        latest = {
            "selection": {
                "cpu": "r5-7600",
                "motherboard": "b650m",
                "case": "m-atx-compact",
                "cooler": "fortis-5",
                "disk": "nvme-1tb",
                "ram": "ddr5-32",
                "gpu": "rtx-5070",
                "psu": "650w",
            },
            "budget": 7000,
        }

        self.assertEqual(
            {"selection": states["fresh"]["selection"], "budget": states["fresh"]["budget"]},
            fresh,
            "a fresh browser profile must start with the default configuration",
        )
        self.assertNotEqual(states["fresh"]["total"], "-", "fresh form must produce an analysis")

        for label, phase, expected, message in (
            (
                "initial state",
                "restore-initial",
                initial,
                "reopening the browser must restore every selected component and the budget",
            ),
            (
                "latest state",
                "restore-latest",
                latest,
                "reopening the browser must restore the latest changed component set and budget",
            ),
        ):
            with self.subTest(state=label):
                self.assertEqual(
                    {"selection": states[phase]["selection"], "budget": states[phase]["budget"]},
                    expected,
                    message,
                )
                self.assertEqual(
                    {
                        "selection": states[phase]["analysisRequest"]["selection"],
                        "budget": states[phase]["analysisRequest"]["budget"],
                    },
                    expected,
                    "reopening the browser must analyze the restored selection and budget",
                )

    def test_rejects_json_with_invalid_structure(self):
        request = Request(
            f"{self.base_url}/api/analyze",
            data=b"null",
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as error:
            urlopen(request)

        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_catalog_exposes_case_and_board_form_facts(self):
        with urlopen(f"{self.base_url}/api/catalog") as response:
            catalog = json.loads(response.read().decode())

        self.assertIn("case", catalog)
        self.assertTrue(catalog["case"])
        self.assertTrue(any(
            item["id"] == "b650m" and item.get("formFactor") == "Micro-ATX"
            for item in catalog["motherboard"]
        ))
        self.assertTrue(any(
            item["id"] == "m-atx-compact" and "Micro-ATX" in item.get("supportedFormFactors", [])
            for item in catalog["case"]
        ))

    def test_catalog_exposes_coolers_and_supported_socket_facts(self):
        with urlopen(f"{self.base_url}/api/catalog") as response:
            catalog = json.loads(response.read().decode())

        self.assertIn("cooler", catalog)
        self.assertTrue(catalog["cooler"])
        self.assertTrue(all(
            isinstance(item.get("supportedSockets"), list) and item["supportedSockets"]
            for item in catalog["cooler"]
        ))
        self.assertTrue(any(
            "AM5" in item["supportedSockets"]
            for item in catalog["cooler"]
        ))

    def test_catalog_exposes_disks_and_supported_storage_interface_facts(self):
        with urlopen(f"{self.base_url}/api/catalog") as response:
            catalog = json.loads(response.read().decode())

        self.assertIn("disk", catalog)
        self.assertTrue(catalog["disk"])
        self.assertTrue(all(
            isinstance(item.get("interface"), str) and item["interface"]
            for item in catalog["disk"]
        ))
        self.assertTrue(catalog["motherboard"])
        self.assertTrue(all(
            isinstance(item.get("supportedStorageInterfaces"), list)
            and item["supportedStorageInterfaces"]
            for item in catalog["motherboard"]
        ))
        self.assertTrue(any(
            item["id"] == "nvme-1tb" and item["interface"] == "NVMe"
            for item in catalog["disk"]
        ))
        self.assertTrue(any(
            item["id"] == "b650m"
            and isinstance(item.get("supportedStorageInterfaces"), list)
            and "NVMe" in item["supportedStorageInterfaces"]
            for item in catalog["motherboard"]
        ))

    def test_accepts_cooler_that_supports_cpu_socket(self):
        with urlopen(f"{self.base_url}/api/catalog") as response:
            catalog = json.loads(response.read().decode())

        am5_coolers = [
            item for item in catalog.get("cooler", [])
            if "AM5" in item.get("supportedSockets", [])
        ]
        self.assertTrue(am5_coolers)

        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": am5_coolers[0]["id"],
            "disk": "nvme-1tb",
        })

        self.assertTrue(report["isCompatible"])
        self.assertFalse(any(
            issue["level"] == "blocking"
            and "chłod" in issue["message"].lower()
            and "podstawk" in issue["message"].lower()
            for issue in report["issues"]
        ))


if __name__ == "__main__":
    unittest.main()
