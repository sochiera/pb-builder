import json
from pathlib import Path
import subprocess
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import analyze, create_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    def test_accepts_case_that_supports_motherboard_form_factor(self):
        report = analyze({
            "cpu": "r5-7600",
            "motherboard": "b650m",
            "ram": "ddr5-32",
            "gpu": "rtx-5060",
            "psu": "650w",
            "case": "m-atx-compact",
        })

        self.assertTrue(report["isCompatible"])
        self.assertFalse(any(
            issue["level"] == "blocking" and "format" in issue["message"].lower()
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
        })

        self.assertEqual(report["total"], 4404)


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

    def test_serves_client_assets_only(self):
        with urlopen(f"{self.base_url}/") as response:
            page = response.read().decode()
        self.assertIn("inteligentny konfigurator PC", page)

        for path in ("/app.py", "/tests/test_analysis.py", "/docs/PROJECT.md"):
            with self.assertRaises(HTTPError) as error:
                urlopen(f"{self.base_url}{path}")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

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


if __name__ == "__main__":
    unittest.main()
