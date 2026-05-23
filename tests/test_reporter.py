from pathlib import Path

from src.models import JobPosting, MatchResult
from src.reporter import generate_pdf_report


def test_generate_pdf_report_writes_pdf(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    matched_jobs = [
        MatchResult(
            job=JobPosting(title="Python Engineer", company="Example Co", location="Shanghai"),
            matched=True,
            score=2.0,
            reasons=["keyword matched: Python"],
        )
    ]
    changed_jobs = [JobPosting(title="ML Engineer", company="Example Co", location="Shanghai")]

    output_path = generate_pdf_report(
        path,
        title="Recruitment Monitor",
        summary_lines=["sources: 1", "total jobs: 2"],
        matched_jobs=matched_jobs,
        changed_jobs=changed_jobs,
    )

    assert output_path == path
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
