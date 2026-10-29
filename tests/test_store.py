import tempfile
import unittest
from pathlib import Path

from findjob import db, store


class DedupKeyTest(unittest.TestCase):
    def test_normalizes_case_punctuation_and_company_suffix(self):
        self.assertEqual(
            store.dedup_key("Maarut Inc.", "RQ8 - Software Developer - Full Stack", "Toronto, ON"),
            "maarut|rq8 software developer full stack|toronto",
        )

    def test_same_job_from_different_sources_collides(self):
        self.assertEqual(
            store.dedup_key("VO2 Canada Ltd", "Back-end Web Developer", "Toronto, Ontario, Canada"),
            store.dedup_key("vo2 canada", "back-end web developer", "Toronto (ON)"),
        )

    def test_different_titles_do_not_collide(self):
        self.assertNotEqual(
            store.dedup_key("Maarut", "Software Developer", "Toronto, ON"),
            store.dedup_key("Maarut", "Senior Software Developer", "Toronto, ON"),
        )


def job(**overrides) -> store.Job:
    fields = dict(
        source="jobbank", source_id="50610364",
        url="https://www.jobbank.gc.ca/jobsearch/jobposting/50610364",
        title="Software Developer", company="Maarut", location="Toronto, ON",
        remote=False, posted_at="2026-10-29", description="Build things.",
    )
    return store.Job(**(fields | overrides))


class SaveTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "test.db"
        db.init_db(path)
        self.conn = db.connect(path)
        self.addCleanup(self.conn.close)

    def test_first_sighting_is_new_and_remembered(self):
        self.assertEqual(store.save(self.conn, job(), "ai-junior-dev"), "new")
        self.assertEqual(store.known_source_ids(self.conn, "jobbank"), {"50610364"})

    def test_same_posting_again_is_seen(self):
        store.save(self.conn, job(), "ai-junior-dev")
        self.assertEqual(store.save(self.conn, job(), "ai-junior-dev"), "seen")

    def test_same_job_from_another_source_is_dup(self):
        store.save(self.conn, job(), "ai-junior-dev")
        other = job(source="greenhouse", source_id="g-1", url="https://boards.greenhouse.io/maarut/jobs/1",
                    company="Maarut Inc.", location="Toronto, Ontario, Canada")
        self.assertEqual(store.save(self.conn, other, "ai-junior-dev"), "dup")
        self.assertEqual(store.known_source_ids(self.conn, "greenhouse"), {"g-1"})

    def test_different_job_same_company_is_new(self):
        store.save(self.conn, job(), "ai-junior-dev")
        other = job(source_id="50610370", url="https://www.jobbank.gc.ca/jobsearch/jobposting/50610370",
                    title="AI Developer")
        self.assertEqual(store.save(self.conn, other, "ai-junior-dev"), "new")


if __name__ == "__main__":
    unittest.main()
