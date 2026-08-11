import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app import create_app
from services.data_cleaner import DataCleaner
from services.groq_service import GroqService


class RouteAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_root_route_redirects_to_login_for_unauthenticated_users(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertIn(response.status_code, (302, 307))
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_dashboard_and_secondary_routes_require_authentication(self):
        for path in ["/dashboard", "/analytics", "/chat"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertIn(response.status_code, (302, 307), msg=f"{path} should redirect to login")

    def test_dataset_diagnostics_include_missing_and_duplicates(self):
        df = pd.DataFrame({
            "sales": [100, 100, None, 300],
            "profit": [10, None, 20, 30],
            "region": ["A", "A", "B", None],
        })
        diag = DataCleaner.get_diagnostics(df)
        self.assertEqual(diag["row_count"], 4)
        self.assertEqual(diag["col_count"], 3)
        self.assertEqual(diag["duplicate_count"], 0)
        self.assertEqual(diag["missing_value_total"], 3)
        self.assertEqual(diag["missing_by_column"]["sales"]["count"], 1)
        self.assertAlmostEqual(diag["missing_by_column"]["profit"]["pct"], 25.0)

    def test_chart_and_relationship_parsing(self):
        service = GroqService()
        df = pd.DataFrame({
            "sales": [10, 20, 30, 40],
            "profit": [2, 4, 6, 8],
            "category": ["A", "A", "B", "B"],
        })
        spec = service._parse_chart_request("Show a scatter plot of sales vs profit with tooltips", df)
        self.assertEqual(spec["chart_type"], "scatter")
        self.assertTrue(spec["interactive"])
        rel = service._build_relationship_summary(df)
        self.assertIn("sales", rel["relationship_summary"]["pairs"][0]["left"])
        self.assertIn("profit", rel["relationship_summary"]["pairs"][0]["right"])
        self.assertEqual(rel["chart_type"], "heatmap_plotly")
        self.assertIsNotNone(rel["chart_data"])

        heatmap_spec = service._parse_chart_request("Show me relation of columns with each other", df)
        self.assertEqual(heatmap_spec["chart_type"], "heatmap_plotly")

        local = service._try_local_analysis(df, "Show correlation between columns")
        self.assertEqual(local["chart_type"], "heatmap_plotly")


    def test_selective_cleaning_respects_options(self):
        df = pd.DataFrame({
            "Column Name": ["  hello  ", "WORLD"],
            "value": ["1", "2"],
        })
        cleaned = DataCleaner.clean_data(df, {
            "header_formatting": False,
            "text_formatting": False,
            "type_correction": False,
            "parse_dates": False,
            "control_chars": False,
        })
        self.assertIn("Column Name", cleaned.columns)
        self.assertEqual(cleaned.iloc[0]["Column Name"], "  hello  ")

        cleaned_all = DataCleaner.clean_data(df, {
            "header_formatting": True,
            "text_formatting": True,
            "type_correction": True,
            "parse_dates": False,
            "control_chars": True,
        })
        self.assertIn("column_name", cleaned_all.columns)

    def test_groq_rate_limit_triggers_gemini_fallback(self):
        service = GroqService()
        service.client = MagicMock()

        class FakeRateLimitError(Exception):
            status_code = 429

        groq_code = (
            "def analyze(df):\n"
            "    return {'answer': 'from gemini', 'chart_type': None, "
            "'chart_title': None, 'chart_data': None, 'chart_image_base64': None}"
        )

        with patch.object(service, "_call_groq_with_retries", side_effect=FakeRateLimitError("rate_limit_exceeded")), \
             patch.object(service, "_call_gemini", return_value=f"```python\n{groq_code}\n```") as gemini_mock:
            df = pd.DataFrame({"sales": [1, 2, 3]})
            result = service.query_data(df, "Summarize sales")

        gemini_mock.assert_called_once()
        self.assertEqual(result["answer"], "from gemini")

    def test_both_providers_fail_returns_useful_local_answer(self):
        service = GroqService()
        service.client = MagicMock()

        with patch.object(service, "_call_groq_with_retries", side_effect=Exception("server down")), \
             patch.object(service, "_call_gemini", side_effect=Exception("gemini down")), \
             patch.object(service, "_try_direct_llm_answer", return_value=None):
            df = pd.DataFrame({"sales": [1, 2, 3]})
            result = service.query_data(df, "Summarize sales")

        self.assertNotIn("temporarily busy", result["answer"].lower())
        self.assertNotIn("server down", result["answer"])
        self.assertNotIn("gemini down", result["answer"])
        self.assertIn("rows", result["answer"].lower())

    def test_local_roll_number_lookup(self):
        service = GroqService()
        df = pd.DataFrame({
            "Name": ["Shayan Ahmed", "Ali Khan", "Sara Ali"],
            "Roll No": ["101", "102", "103"],
        })
        with patch.object(service, "_generate_llm_response", side_effect=RuntimeError("offline")):
            result = service.query_data(df, "Roll No of Shayan Ahmed")

        self.assertIn("101", result["answer"])
        self.assertNotIn("temporarily busy", result["answer"].lower())

    def test_oauth_finalize_skips_otp(self):
        from routes.auth import _finalize_oauth_session

        with self.app.test_request_context():
            from flask import session
            session["otp_purpose"] = "account login"
            session["oauth_otp_verified"] = False
            pending = {
                "email": "oauth@example.com",
                "full_name": "OAuth User",
                "picture": "",
                "auth_provider": "google",
                "user_id": "123",
            }
            session["oauth_pending"] = pending
            _finalize_oauth_session(pending)
            self.assertEqual(session.get("email"), "oauth@example.com")
            self.assertIsNone(session.get("otp_purpose"))
            self.assertIsNone(session.get("oauth_pending"))

    def test_oauth_finalize_route_goes_to_dashboard(self):
        with self.client.session_transaction() as sess:
            sess["oauth_pending"] = {
                "email": "oauth@example.com",
                "full_name": "OAuth User",
                "picture": "",
                "auth_provider": "google",
                "user_id": "123",
            }
            sess["oauth_otp_verified"] = False
            sess["oauth_requires_otp"] = True

        response = self.client.post("/oauth-finalize", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/data/dashboard", response.headers.get("Location", ""))


    def test_local_duplicate_analysis_fallback(self):
        service = GroqService()
        df = pd.DataFrame({"a": [1, 1, 2, 3]})
        result = service._try_local_analysis(df, "How many exact duplicate rows are present?")
        self.assertIsNotNone(result)
        self.assertIn("duplicate", result["answer"].lower())
        self.assertEqual(result["chart_data"]["values"][1], 1)


if __name__ == "__main__":
    unittest.main()
