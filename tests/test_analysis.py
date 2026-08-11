import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from functools import partial
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Handler, analyze, create_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
</script>
"""

BROWSER_EXERCISE = """
<script>
let stage = "boot";
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
const compact = (selector) => visible(selector).replace(/\\s(?=\\d)/g, "");
const publish = (attribute, value) => {
  document.documentElement.setAttribute(
    attribute,
    btoa(unescape(encodeURIComponent(JSON.stringify(value))))
  );
};

(async () => {
  try {
    await waitFor(() =>
      document.querySelector('select[name="case"]') &&
      document.querySelector('select[name="cooler"]') &&
      visible("#total") !== "-"
    );
    const caseField = document.querySelector('select[name="case"]');
    const coolerField = document.querySelector('select[name="cooler"]');
    const budgetField = document.querySelector("#budget");
    window.__testRequests.length = 0;

    stage = "cooler request";
    coolerField.value = "fortis-5";
    coolerField.dispatchEvent(new Event("input", { bubbles: true }));
    await waitFor(() => window.__testRequests.find((request) =>
      request.selection && request.selection.cooler === "fortis-5" && request.budget === 5500
    ));

    stage = "case request";
    caseField.value = "atx-airflow";
    caseField.dispatchEvent(new Event("input", { bubbles: true }));
    const caseRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection && request.selection.case === "atx-airflow" && request.budget === 5500
    ));

    stage = "budget request";
    budgetField.value = "5000";
    budgetField.dispatchEvent(new Event("input", { bubbles: true }));
    const budgetRequest = await waitFor(() => window.__testRequests.find((request) =>
      request.selection && request.selection.case === "atx-airflow" && request.budget === 5000
    ));
    stage = "visible totals";
    await waitFor(() => compact("#total") === "5903 zł" && compact("#remaining") === "-903 zł");

    publish("data-browser-test", {
      caseOptions: Array.from(caseField.options, (option) => option.value),
      coolerOptions: Array.from(coolerField.options, (option) => option.value),
      caseRequest,
      budgetRequest,
      total: visible("#total"),
      remaining: visible("#remaining"),
      status: document.querySelector("#status").textContent,
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


class BrowserTestHandler(Handler):
    def do_GET(self):
        if self.path == "/__browser_test__":
            page = (PROJECT_ROOT / "client" / "index.html").read_text()
            page = page.replace(
                '  <script src="app.js"></script>',
                f"{BROWSER_SETUP}  <script src=\"app.js\"></script>{BROWSER_EXERCISE}",
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

    def test_accepts_case_that_supports_motherboard_form_factor(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
            "cooler": "fortis-5",
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

    def test_client_updates_analysis_and_formats_totals_in_browser(self):
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
                result = subprocess.run(
                    [
                        browser,
                        "--headless=new",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                        "--window-size=600,800",
                        "--virtual-time-budget=10000",
                        f"--user-data-dir={profile}",
                        "--dump-dom",
                        f"http://127.0.0.1:{browser_server.server_port}/__browser_test__",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
        finally:
            browser_server.shutdown()
            browser_server.server_close()
            browser_thread.join()

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
        self.assertTrue(browser_report["mobileLayout"])
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
            },
        )
        for actual, expected in ((browser_report["total"], "5903"), (browser_report["remaining"], "-903")):
            parts = actual.split()
            self.assertEqual(parts[-1], "zł")
            self.assertEqual("".join(parts[:-1]), expected)
        self.assertEqual(browser_report["status"], "Zestaw jest kompatybilny")

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
