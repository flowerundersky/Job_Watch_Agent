from src.comparator import compare_job_snapshots
from src.models import JobPosting


def test_compare_job_snapshots_detects_new_changed_and_removed() -> None:
    previous_jobs = [
        JobPosting(
            title="Python Engineer",
            company="Example Co",
            location="Shanghai",
            url="https://example.com/jobs/1",
            description="Build tools",
        ),
        JobPosting(
            title="Data Analyst",
            company="Example Co",
            location="Beijing",
            url="https://example.com/jobs/2",
        ),
    ]
    current_jobs = [
        JobPosting(
            title="Python Engineer",
            company="Example Co",
            location="Shanghai",
            url="https://example.com/jobs/1",
            description="Build internal tools and dashboards",
        ),
        JobPosting(
            title="ML Engineer",
            company="Example Co",
            location="Shanghai",
            url="https://example.com/jobs/3",
        ),
    ]

    delta = compare_job_snapshots(previous_jobs, current_jobs)

    assert [job.title for job in delta.new_jobs] == ["ML Engineer"]
    assert [job.title for job in delta.changed_jobs] == ["Python Engineer"]
    assert [job.title for job in delta.removed_jobs] == ["Data Analyst"]
    assert delta.total_changes == 3
