import unittest

from app import create_app


class RouteAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_root_route_renders_main_app_without_redirecting_to_login(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("AnalystGPT", response.get_data(as_text=True))

    def test_dashboard_and_secondary_routes_render(self):
        for path in ["/dashboard", "/analytics", "/chat"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 200, msg=f"{path} should render")
                self.assertIn("AnalystGPT", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
