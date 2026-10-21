import unittest

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.routes import hub
from gateway_mcp.services.policy import GatewayActor

URL = "https://core.example.test/mcp"
USER = GatewayActor(subject="yandex:2", email="two@sibsensor.com", scopes=())
ADMIN = GatewayActor(subject="yandex:1", email="one@sibsensor.com", scopes=("access:admin",))


class HubPageTests(unittest.TestCase):
    def test_anonymous_sees_login_and_no_private_links(self):
        html = hub._page_html(actor=None, skills=0, agents=0, mcp_url=URL)
        self.assertIn('href="/auth/yandex/login?next=/"', html)
        self.assertIn(URL, html)
        self.assertNotIn('href="/me"', html)
        self.assertNotIn('href="/admin"', html)
        self.assertNotIn("навыков в ядре", html)

    def test_employee_sees_all_workplace_links_but_not_admin(self):
        html = hub._page_html(actor=USER, skills=4, agents=0, mcp_url=URL)
        for href in ("/me", "/skills/new", "/skills/submit-agent", "/my/skills", "/notifications", "/credentials"):
            self.assertIn(f'href="{href}"', html)
        self.assertIn("two@sibsensor.com", html)
        self.assertIn("<b>4</b><span>навыков в ядре", html)
        self.assertNotIn('href="/admin/users"', html)
        self.assertNotIn("агентов</span>", html)

    def test_admin_sees_management_block(self):
        html = hub._page_html(actor=ADMIN, skills=4, agents=2, mcp_url=URL)
        for href in ("/admin", "/admin/skill-requests", "/admin/users", "/admin/audit", "/admin/metrics"):
            self.assertIn(f'href="{href}"', html)
        self.assertIn("<b>2</b><span>агентов", html)

    def test_name_is_escaped(self):
        evil = GatewayActor(subject="yandex:3", email="<script>@sibsensor.com", scopes=())
        html = hub._page_html(actor=evil, skills=0, agents=0, mcp_url=URL)
        self.assertNotIn("<script>@", html)

    def test_page_has_no_inline_scripts(self):
        html = hub._page_html(actor=USER, skills=1, agents=0, mcp_url=URL)
        self.assertEqual(html.count("<script"), 1)
        self.assertIn('<script src="/static/hub.js" defer></script>', html)


if __name__ == "__main__":
    unittest.main()
