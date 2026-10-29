import datetime
import json
import tempfile
import unittest
from pathlib import Path

from findjob import db, store
from findjob.report import write_report
from findjob.screen import screen, screen_pending

PROFILE = {
    "name": "ai-junior-dev",
    "keywords": ["junior developer", "Python", "React", "LLM"],
    "exclude": ["senior", "sr.", "lead", "staff engineer"],
}


def job(title: str, description: str = "") -> dict:
    return {"title": title, "description": description}


class ExcludeTest(unittest.TestCase):
    def test_title_with_exclude_word_is_skipped(self):
        verdict = screen(job("Senior Software Developer"), PROFILE)
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.reason, "exclude: senior")

    def test_exclude_word_only_in_description_is_kept(self):
        verdict = screen(job("Software Developer", "You will report to a senior engineer."), PROFILE)
        self.assertTrue(verdict.keep)
        self.assertIsNone(verdict.reason)

    def test_whole_word_only(self):
        self.assertTrue(screen(job("Leading-edge Developer"), PROFILE).keep)
        self.assertTrue(screen(job("Leading Developer"), PROFILE).keep)

    def test_punctuated_word_matches_as_written(self):
        verdict = screen(job("Sr. Developer"), PROFILE)
        self.assertEqual(verdict.reason, "exclude: sr.")

    def test_multi_word_exclude(self):
        self.assertEqual(screen(job("Staff Engineer, Platform"), PROFILE).reason, "exclude: staff engineer")

    def test_skipped_job_still_gets_coarse_score(self):
        verdict = screen(job("Senior Python Developer", "React"), PROFILE)
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.coarse_score, 3)


class CoarseScoreTest(unittest.TestCase):
    def test_title_hit_scores_two_description_only_hit_scores_one(self):
        verdict = screen(job("Junior Developer (Python)", "Python, React and LLM tooling."), PROFILE)
        # junior developer: 标题 2；Python: 标题 2（JD 不再加分）；React: JD 1；LLM: JD 1
        self.assertEqual(verdict.coarse_score, 6)

    def test_keyword_counted_once_however_often_it_appears(self):
        self.assertEqual(screen(job("Developer", "React React React"), PROFILE).coarse_score, 1)

    def test_keyword_match_is_whole_word_and_case_insensitive(self):
        self.assertEqual(screen(job("developer", "reactive python"), PROFILE).coarse_score, 1)

    def test_no_keyword_hit_is_kept_with_zero(self):
        verdict = screen(job("Data Analyst", "Excel"), PROFILE)
        self.assertTrue(verdict.keep)
        self.assertEqual(verdict.coarse_score, 0)
        self.assertEqual(verdict.flags, [])

    def test_missing_description(self):
        self.assertEqual(screen({"title": "Python Developer", "description": None}, PROFILE).coarse_score, 2)


class ScreenPendingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        path = self.tmp / "test.db"
        db.init_db(path)
        self.conn = db.connect(path)
        self.addCleanup(self.conn.close)
        self.profiles = {"ai-junior-dev": PROFILE}

    def add(self, source_id: str, title: str, description: str = "", profile: str = "ai-junior-dev",
            **overrides) -> int:
        fields = dict(
            source="jobbank", source_id=source_id,
            url=f"https://www.jobbank.gc.ca/jobsearch/jobposting/{source_id}",
            title=title, company="Maarut", location="Toronto, ON",
            remote=False, posted_at="2026-10-29", description=description,
        )
        store.save(self.conn, store.Job(**(fields | overrides)), profile)
        return self.conn.execute("SELECT id FROM jobs WHERE source_id = ?", (source_id,)).fetchone()["id"]

    def job_row(self, job_id: int):
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def test_excluded_job_is_skipped_with_history(self):
        job_id = self.add("1", "Senior Python Developer")
        screen_pending(self.conn, self.profiles)
        row = self.job_row(job_id)
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["coarse_score"], 2)
        self.assertEqual(json.loads(row["flags"]), [])
        history = self.conn.execute(
            "SELECT status, note FROM status_history WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        self.assertEqual([tuple(h) for h in history], [("new", None), ("skipped", "exclude: senior")])

    def test_kept_job_stays_new_with_score(self):
        job_id = self.add("2", "Junior Developer", "React")
        screen_pending(self.conn, self.profiles)
        row = self.job_row(job_id)
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["coarse_score"], 3)
        self.assertEqual(json.loads(row["flags"]), [])

    def test_second_run_does_not_reprocess(self):
        self.add("1", "Senior Python Developer")
        self.add("2", "Junior Developer")
        self.assertEqual(len(screen_pending(self.conn, self.profiles)), 2)
        self.assertEqual(screen_pending(self.conn, self.profiles), [])

    def test_uses_profile_recorded_on_job(self):
        other = PROFILE | {"name": "other", "keywords": ["Excel"], "exclude": []}
        job_id = self.add("3", "Senior Excel Analyst", profile="other")
        screen_pending(self.conn, self.profiles | {"other": other})
        row = self.job_row(job_id)
        self.assertEqual((row["status"], row["coarse_score"]), ("new", 2))

    def test_daily_report(self):
        self.add("10", "Junior Developer", "React", remote=True)
        self.add("11", "Python Developer")
        self.add("12", "Senior Python Developer")
        self.add("13", "Sr. Developer")
        results = screen_pending(self.conn, self.profiles)
        path = write_report(results, self.tmp / "reports", datetime.date(2026, 10, 29))
        self.assertEqual(path, self.tmp / "reports" / "2026-10-29.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Junior Developer", text)
        self.assertIn("https://www.jobbank.gc.ca/jobsearch/jobposting/10", text)
        self.assertIn("远程", text)
        self.assertLess(text.index("Junior Developer"), text.index("Python Developer"))  # 粗分 3 在 2 之前
        self.assertNotIn("Senior Python Developer", text)
        self.assertNotIn("Sr. Developer", text)
        self.assertIn("处理 4", text)
        self.assertIn("保留 2", text)
        self.assertIn("exclude: senior：1", text)
        self.assertIn("exclude: sr.：1", text)

    def test_same_day_report_is_overwritten(self):
        self.add("10", "Junior Developer")
        day = datetime.date(2026, 10, 29)
        write_report(screen_pending(self.conn, self.profiles), self.tmp / "reports", day)
        path = write_report(screen_pending(self.conn, self.profiles), self.tmp / "reports", day)
        self.assertNotIn("Junior Developer", path.read_text(encoding="utf-8"))
        self.assertIn("处理 0", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
