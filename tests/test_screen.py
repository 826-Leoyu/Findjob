import datetime
import json
import tempfile
import unittest
from pathlib import Path

from findjob import db, store
from findjob.report import write_report
from findjob.screen import required_experience, screen, screen_pending

PROFILE = {
    "name": "ai-junior-dev",
    "keywords": ["junior developer", "Python", "React", "LLM"],
    "exclude": ["senior", "sr.", "lead", "staff engineer"],
    "max_experience_years": 2,
    "locations": ["Ontario"],
    "remote": True,
}


def job(title: str, description: str | None = "", location: str = "Toronto, ON", remote: int | None = None) -> dict:
    return {"title": title, "description": description, "location": location, "remote": remote}


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


class ExperienceTest(unittest.TestCase):
    """文本取自真实 JD 片段（Job Bank 描述已压平为一段）。"""

    def verdict(self, description: str):
        return screen(job("Software Developer", description), PROFILE)

    def test_jobbank_line_above_limit_is_skipped(self):
        verdict = self.verdict("Experience: 3 years to less than 5 years. Employment terms options: Day.")
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.reason, "experience: 3")

    def test_jobbank_line_at_limit_is_kept(self):
        self.assertTrue(self.verdict("Experience: 2 years to less than 3 years. Health benefits: Dental plan.").keep)

    def test_jobbank_five_years_or_more_is_skipped(self):
        self.assertEqual(self.verdict("Education: Earned doctorate degree. Experience: 5 years or more.").reason,
                         "experience: 5")

    def test_jobbank_no_experience_values_are_kept(self):
        self.assertTrue(self.verdict("Experience: No experience (will train). Employment terms options: Day.").keep)
        self.assertTrue(self.verdict("Experience: Experience an asset. Workplace information: Hybrid.").keep)

    def test_every_jobbank_value_maps_to_its_lower_bound(self):
        cases = {
            "No experience (will train)": 0, "Experience an asset": 0,
            "1 to less than 7 months": 0, "7 months to less than 1 year": 0,
            "1 year to less than 2 years": 1, "2 years to less than 3 years": 2,
            "3 years to less than 5 years": 3, "5 years or more": 5, "Ten or more years": 10,
        }
        for value, years in cases.items():
            with self.subTest(value=value):
                self.assertEqual(required_experience(f"Experience: {value}."), years)

    def test_free_text_n_plus_years(self):
        verdict = self.verdict("We are seeking a skilled Full Stack Software Developer with "
                               "5+ years of professional experience to design, develop, and maintain robust")
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.reason, "experience: 5")

    def test_free_text_n_years_or_more(self):
        self.assertEqual(self.verdict("Required Skills: Several years of software engineering experience "
                                      "(3 years or more).").reason, "experience: 3")

    def test_free_text_range_uses_lower_bound(self):
        self.assertEqual(self.verdict("• 3-5 years of experience with designing and implementing large "
                                      "enterprise networks.").reason, "experience: 3")
        self.assertTrue(self.verdict("Requirements * 1-2 years media coordinating experience in Agency "
                                     "or Client environment.").keep)

    def test_free_text_minimum_of_n_years(self):
        self.assertEqual(self.verdict("Minimum of 3 years of experience in Salesforce development toolset.").reason,
                         "experience: 3")

    def test_free_text_years_without_experience_word_nearby_is_ignored(self):
        self.assertTrue(self.verdict("It represents a multi-trillion-dollar market and a 20+ year megatrend "
                                     "in North America.").keep)

    def test_company_history_is_not_a_requirement(self):
        self.assertTrue(self.verdict("MenRes draws on over 70 years of combined property management and "
                                     "construction experience").keep)

    def test_experience_label_followed_by_skill_is_ignored(self):
        self.assertTrue(self.verdict("Equipment and machinery experience: Forklift").keep)

    def test_largest_requirement_wins(self):
        verdict = self.verdict("8+ years of professional experience in similar positions in an enterprise / "
                               "commercial environment. Deep understanding and 6+ years of practical experience "
                               "with tools, methodologies, and frameworks.")
        self.assertEqual(verdict.reason, "experience: 8")

    def test_exclude_reason_takes_precedence(self):
        verdict = screen(job("Senior Developer", "Experience: 5 years or more."), PROFILE)
        self.assertEqual(verdict.reason, "exclude: senior")


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
        self.assertEqual(screen(job("Python Developer", None), PROFILE).coarse_score, 2)


CITIES = ["Windsor, ON", "Toronto, ON"]


class LocationTest(unittest.TestCase):
    def verdict(self, location: str, remote: int | None = None, title: str = "Software Developer",
                description: str = "", remote_profile: bool = True, **profile):
        return screen(job(title, description, location, remote), PROFILE | {"remote": remote_profile} | profile)

    def test_province_profile_keeps_cities_in_that_province(self):
        for location in ("Hamilton, ON", "Ottawa, ON", "Toronto, ON"):
            with self.subTest(location=location):
                self.assertTrue(self.verdict(location).keep)

    def test_province_profile_skips_out_of_province_onsite_job(self):
        verdict = self.verdict("Montreal, QC", remote=0)
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.reason, "location: Montreal")

    def test_city_profile_keeps_configured_cities(self):
        for location in ("Windsor, ON", "toronto, on"):
            with self.subTest(location=location):
                self.assertTrue(self.verdict(location, locations=CITIES).keep)

    def test_city_profile_skips_other_cities(self):
        for location, city in (("Hamilton, ON", "Hamilton"), ("Leamington, ON", "Leamington")):
            with self.subTest(location=location):
                verdict = self.verdict(location, remote=0, locations=CITIES)
                self.assertFalse(verdict.keep)
                self.assertEqual(verdict.reason, f"location: {city}")

    def test_toronto_boroughs_count_as_toronto(self):
        for borough in ("North York", "Scarborough", "Etobicoke", "East York", "York"):
            with self.subTest(borough=borough):
                self.assertTrue(self.verdict(f"{borough}, ON", locations=CITIES).keep)

    def test_remote_job_elsewhere_is_kept_when_profile_accepts_remote(self):
        self.assertTrue(self.verdict("Halifax, NS", remote=1).keep)

    def test_remote_job_elsewhere_is_skipped_when_profile_rejects_remote(self):
        verdict = self.verdict("Halifax, NS", remote=1, remote_profile=False)
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.reason, "location: Halifax")

    def test_explicit_remote_wording_counts_as_remote_when_field_is_empty(self):
        cases = [
            dict(title="Junior Developer - Fully Remote"),
            dict(description="This is a 100% remote role open to candidates across Canada."),
            dict(description="This is a remote position."),
        ]
        for case in cases:
            with self.subTest(**case):
                self.assertTrue(self.verdict("Montréal, QC", **case).keep)

    def test_remote_wording_is_ignored_when_field_says_not_remote(self):
        self.assertFalse(self.verdict("Montréal, QC", remote=0, title="Fully Remote Developer").keep)

    def test_vague_remote_mention_does_not_count(self):
        verdict = self.verdict("Montréal, QC", description="Hybrid: 3 days in office, some remote work.")
        self.assertEqual(verdict.reason, "location: Montréal")

    def test_unknown_location_is_kept_and_flagged(self):
        for location in ("Various locations", "", None, "Somewhere, XX"):
            with self.subTest(location=location):
                verdict = self.verdict(location, remote=0, locations=CITIES)
                self.assertTrue(verdict.keep)
                self.assertEqual(verdict.flags, ["location_unknown"])


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

    def history(self, job_id: int) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT status, note FROM status_history WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        return [tuple(r) for r in rows]

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
        self.assertEqual(len(screen_pending(self.conn, self.profiles).results), 2)
        self.assertEqual(screen_pending(self.conn, self.profiles).results, [])

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
        run = screen_pending(self.conn, self.profiles)
        path = write_report(run.results, self.tmp / "reports", datetime.date(2026, 10, 29))
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

    def test_daily_report_counts_experience_filter(self):
        self.add("14", "Python Developer", "Experience: 5 years or more. Employment terms options: Day.")
        self.add("15", "Python Developer II", "Experience: 2 years to less than 3 years.")
        run = screen_pending(self.conn, self.profiles)
        text = write_report(run.results, self.tmp / "reports", datetime.date(2026, 10, 30)).read_text(encoding="utf-8")
        self.assertIn("保留 1", text)
        self.assertIn("experience: 5：1", text)

    def test_same_day_report_is_overwritten(self):
        self.add("10", "Junior Developer")
        day = datetime.date(2026, 10, 29)
        write_report(screen_pending(self.conn, self.profiles).results, self.tmp / "reports", day)
        path = write_report(screen_pending(self.conn, self.profiles).results, self.tmp / "reports", day)
        self.assertNotIn("Junior Developer", path.read_text(encoding="utf-8"))
        self.assertIn("处理 0", path.read_text(encoding="utf-8"))

    def test_rescreen_restores_job_kept_by_looser_profile(self):
        job_id = self.add("20", "Senior Python Developer")
        screen_pending(self.conn, self.profiles)
        looser = {"ai-junior-dev": PROFILE | {"exclude": []}}
        screen_pending(self.conn, looser, rescreen=True)
        self.assertEqual(self.job_row(job_id)["status"], "new")
        self.assertEqual(self.history(job_id)[-1][0], "new")
        self.assertEqual(len(self.history(job_id)), 3)

    def test_rescreen_skips_job_excluded_by_stricter_profile(self):
        job_id = self.add("21", "Python Developer")
        screen_pending(self.conn, self.profiles)
        stricter = {"ai-junior-dev": PROFILE | {"exclude": ["python"]}}
        screen_pending(self.conn, stricter, rescreen=True)
        self.assertEqual(self.job_row(job_id)["status"], "skipped")
        self.assertEqual(self.history(job_id)[-1], ("skipped", "exclude: python"))

    def test_rescreen_unchanged_job_updates_score_without_history(self):
        job_id = self.add("22", "Python Developer", "React")
        screen_pending(self.conn, self.profiles)
        rescored = {"ai-junior-dev": PROFILE | {"keywords": ["Python"]}}
        screen_pending(self.conn, rescored, rescreen=True)
        row = self.job_row(job_id)
        self.assertEqual((row["status"], row["coarse_score"]), ("new", 2))
        self.assertEqual(self.history(job_id), [("new", None)])

    def test_rescreen_leaves_other_statuses_alone(self):
        job_id = self.add("23", "Senior Python Developer")
        self.conn.execute("UPDATE jobs SET status = 'scored' WHERE id = ?", (job_id,))
        run = screen_pending(self.conn, self.profiles, rescreen=True)
        self.assertEqual(run.results, [])
        row = self.job_row(job_id)
        self.assertEqual((row["status"], row["coarse_score"]), ("scored", None))

    def test_only_given_profile_is_processed(self):
        other = PROFILE | {"name": "other"}
        mine = self.add("24", "Python Developer")
        theirs = self.add("25", "Python Developer II", profile="other")
        run = screen_pending(self.conn, self.profiles | {"other": other}, only_profile="other")
        self.assertEqual([job["id"] for job, _ in run.results], [theirs])
        self.assertIsNone(self.job_row(mine)["coarse_score"])

    def test_location_filter_end_to_end(self):
        hamilton = self.add("30", "Python Developer", location="Hamilton, ON", remote=None)
        inferred = self.add("31", "Python Developer - Fully Remote", location="Halifax, NS", remote=None)
        various = self.add("32", "Junior Developer", location="Various locations")
        self.add("33", "Python Developer II", location="Montréal, QC")
        profiles = {"ai-junior-dev": PROFILE | {"locations": CITIES}}
        run = screen_pending(self.conn, profiles)
        self.assertEqual(self.job_row(hamilton)["status"], "skipped")
        self.assertEqual(self.history(hamilton)[-1], ("skipped", "location: Hamilton"))
        self.assertEqual(self.job_row(inferred)["status"], "new")
        self.assertIsNone(self.job_row(inferred)["remote"])
        self.assertEqual(json.loads(self.job_row(various)["flags"]), ["location_unknown"])
        text = write_report(run.results, self.tmp / "reports", datetime.date(2026, 10, 30)).read_text(encoding="utf-8")
        self.assertNotIn("Hamilton", text.partition("## 统计")[0])
        self.assertIn("标记 location_unknown", text)
        self.assertIn("location: Hamilton：1", text)
        self.assertIn("location: Montréal：1", text)

    def test_job_whose_profile_is_unavailable_is_skipped_and_counted(self):
        job_id = self.add("26", "Python Developer", profile="retired")
        self.add("27", "Python Developer II", profile="retired")
        run = screen_pending(self.conn, self.profiles)
        self.assertEqual(run.results, [])
        self.assertEqual(run.unmatched, {"retired": 2})
        self.assertIsNone(self.job_row(job_id)["coarse_score"])


if __name__ == "__main__":
    unittest.main()
