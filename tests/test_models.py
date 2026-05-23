from src.models import JobPosting


def test_job_posting_serialization_roundtrip() -> None:
    job = JobPosting(
        title="Python Engineer",
        company="Example Co",
        location="Shanghai",
        url="https://example.com/jobs/1",
        source="https://example.com/careers",
        posted_at="2026-05-23",
        description="Build internal tools",
    )

    payload = job.to_dict()
    restored = JobPosting.from_dict(payload)

    assert restored == job
    assert job.stable_key() == ("example co", "python engineer", "shanghai")
    assert job.content_signature()
