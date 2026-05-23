from src.cleaner import deduplicate_jobs, normalize_whitespace
from src.models import JobPosting


def test_normalize_whitespace_compacts_gaps() -> None:
    assert normalize_whitespace("  Python\n  Engineer  ") == "Python Engineer"


def test_deduplicate_jobs_keeps_first_unique_item() -> None:
    jobs = [
        JobPosting(title="Python Engineer", company="Example Co", location="Shanghai", url="https://example.com/jobs/1"),
        JobPosting(title="Python Engineer", company="Example Co", location="Shanghai", url="https://example.com/jobs/1"),
        JobPosting(title="Data Analyst", company="Example Co", location="Beijing", url="https://example.com/jobs/2"),
    ]

    unique_jobs = deduplicate_jobs(jobs)

    assert len(unique_jobs) == 2
    assert unique_jobs[0].title == "Python Engineer"
    assert unique_jobs[1].title == "Data Analyst"
