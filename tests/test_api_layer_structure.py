from __future__ import annotations

import unittest
from pathlib import Path


class ApiLayerStructureTests(unittest.TestCase):
    def test_api_py_line_budget_and_router_mount_only(self) -> None:
        api_path = Path("agora/api.py")
        text = api_path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        self.assertLessEqual(line_count, 350)
        self.assertNotIn("@app.post", text)
        self.assertNotIn("@app.get", text)
        self.assertIn("app.include_router(sessions_router)", text)
        self.assertIn("app.include_router(workflows_router)", text)
        self.assertIn("app.include_router(admin_router)", text)
        self.assertIn("app.include_router(internal_router)", text)

    def test_routes_contain_router_defs(self) -> None:
        for p in [
            Path("agora/routes/sessions.py"),
            Path("agora/routes/workflows.py"),
            Path("agora/routes/internal.py"),
            Path("agora/routes/admin.py"),
        ]:
            text = p.read_text(encoding="utf-8")
            self.assertIn("APIRouter", text)
            self.assertIn("router = APIRouter()", text)


if __name__ == "__main__":
    unittest.main()
