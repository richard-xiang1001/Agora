from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agora.memory_store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_query_priority_and_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td), model_family_map_path="config/model_family_map.yaml")
            now = datetime.now(timezone.utc)

            store.upsert_profile(
                model_id="claude-3-7-sonnet",
                task_type="code_review",
                summary="A",
                ttl_days=10,
                confidence_score=0.9,
                now=now,
            )
            store.upsert_profile(
                model_id="claude-3-7-sonnet",
                task_type="research",
                summary="B",
                ttl_days=10,
                confidence_score=0.8,
                now=now,
            )

            q1 = store.query(model_version="3.7", task_type="code_review")
            self.assertEqual(q1.priority, "active_same_version_same_task")
            self.assertIsNotNone(q1.profile)
            self.assertEqual(q1.profile.task_type, "code_review")

            # Advance beyond expires_at to stale state.
            changed = store.apply_ttl_transitions(now=now + timedelta(days=11))
            self.assertGreaterEqual(changed, 1)
            q2 = store.query(model_version="3.7", task_type="planning")
            self.assertEqual(q2.priority, "stale_same_version")
            self.assertIsNotNone(q2.profile)
            self.assertEqual(q2.profile.state, "stale")

            # Advance further to expired state.
            store.apply_ttl_transitions(now=now + timedelta(days=30))
            q3 = store.query(model_version="3.7", task_type="planning")
            self.assertEqual(q3.priority, "none")
            self.assertIsNone(q3.profile)

    def test_model_version_change_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td), model_family_map_path="config/model_family_map.yaml")
            now = datetime.now(timezone.utc)
            store.upsert_profile(
                model_id="claude-3-7-sonnet",
                task_type="code_review",
                summary="A",
                ttl_days=30,
                confidence_score=0.9,
                now=now,
            )
            changed = store.on_model_version_change("3.7", now=now + timedelta(days=1))
            self.assertEqual(changed, 1)
            q = store.query(model_version="3.7", task_type="code_review")
            self.assertEqual(q.priority, "stale_same_version")

    def test_build_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td), model_family_map_path="config/model_family_map.yaml")
            now = datetime.now(timezone.utc)
            store.upsert_profile(
                model_id="claude-3-7-sonnet",
                task_type="code_review",
                summary="A",
                ttl_days=30,
                confidence_score=0.9,
                now=now,
            )
            idx = store.build_index()
            self.assertIn("3.7", idx)
            self.assertIn("code_review", idx["3.7"])
            self.assertEqual(len(idx["3.7"]["code_review"]), 1)


if __name__ == "__main__":
    unittest.main()
