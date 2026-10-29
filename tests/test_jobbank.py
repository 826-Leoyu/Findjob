import unittest
from pathlib import Path

from findjob import jobbank

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParseSearchTest(unittest.TestCase):
    def setUp(self):
        self.listings = jobbank.parse_search(fixture("jobbank_search.html"))

    def test_extracts_every_result(self):
        self.assertEqual([l.source_id for l in self.listings], ["50610364", "50609755", "50608622"])

    def test_listing_fields(self):
        first = self.listings[0]
        self.assertEqual(first.url, "https://www.jobbank.gc.ca/jobsearch/jobposting/50610364")
        self.assertEqual(first.title, "software developer")
        self.assertEqual(first.company, "Maarut")
        self.assertEqual(first.location, "Toronto, ON")
        self.assertEqual(first.posted_at, "2026-10-29")
        self.assertEqual(first.origin, "Talent.com")
        self.assertIsNone(first.workplace)

    def test_workplace_tag(self):
        self.assertEqual(self.listings[1].workplace, "Hybrid")
        self.assertEqual(self.listings[1].origin, "indeed.com")


class ParsePostingTest(unittest.TestCase):
    def test_reposted_from_other_site(self):
        posting = jobbank.parse_posting(fixture("jobbank_posting_external.html"))
        self.assertEqual(posting.original_title, "RQ8 - Software Developer - Full Stack - Senior")
        self.assertIn("FHIR Subscription and SubscriptionTopic", posting.description)
        self.assertNotIn("<", posting.description)
        self.assertTrue(posting.external_url.startswith(
            "https://ca.talent.com/redirect?id=643726690237030375&source="))
        self.assertIsNone(posting.workplace)

    def test_native_job_bank_posting(self):
        posting = jobbank.parse_posting(fixture("jobbank_posting_native.html"))
        self.assertEqual(posting.original_title, "back-end Web developer")
        self.assertIn("Experience: 5 years or more", posting.description)
        self.assertEqual(posting.workplace, "Hybrid")
        self.assertIsNone(posting.external_url)


class PlanSearchesTest(unittest.TestCase):
    COORDS = {
        "Windsor, ON": (42.317, -83.035),
        "Toronto, ON": (43.653, -79.383),
        "Mississauga, ON": (43.589, -79.644),  # 离多伦多约 22 km
        "Whitby, ON": (43.877, -78.942),       # 离多伦多约 43 km
        "Oshawa, ON": (43.897, -78.866),       # 离惠特比约 7 km
    }

    def test_merges_cities_within_radius_in_listed_order(self):
        self.assertEqual(
            jobbank.plan_searches(list(self.COORDS), self.COORDS),
            ["Windsor, ON", "Toronto, ON", "Whitby, ON"],
        )

    def test_skips_locations_without_coordinates(self):
        self.assertEqual(jobbank.plan_searches(["Atlantis, ON", "Windsor, ON"], self.COORDS), ["Windsor, ON"])


class SplitLocationsTest(unittest.TestCase):
    def test_province_by_name_or_code(self):
        self.assertEqual(jobbank.split_locations(["Ontario", "bc"]), (["ON", "BC"], []))

    def test_cities_inside_a_listed_province_are_dropped(self):
        self.assertEqual(
            jobbank.split_locations(["Windsor, ON", "Ontario", "Montreal, QC"]),
            (["ON"], ["Montreal, QC"]),
        )

    def test_cities_only(self):
        self.assertEqual(jobbank.split_locations(["Windsor, ON", "Toronto, ON"]), ([], ["Windsor, ON", "Toronto, ON"]))


if __name__ == "__main__":
    unittest.main()
