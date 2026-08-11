import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import analyze, create_server


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


if __name__ == "__main__":
    unittest.main()
