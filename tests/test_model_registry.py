from __future__ import annotations

import unittest

from agora.model_registry import load_model_family_map, resolve_model_identity


class ModelRegistryTests(unittest.TestCase):
    def test_resolve_model_identity(self) -> None:
        mapping = load_model_family_map("config/model_family_map.yaml")
        m = resolve_model_identity("claude-3-7-sonnet", mapping)
        self.assertEqual(m.family, "claude")
        self.assertEqual(m.version, "3.7")

    def test_unknown_model_raises(self) -> None:
        mapping = load_model_family_map("config/model_family_map.yaml")
        with self.assertRaises(KeyError):
            resolve_model_identity("missing-model", mapping)


if __name__ == "__main__":
    unittest.main()
