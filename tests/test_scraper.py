from src.scraper import extract_jobs_from_html


def test_extract_jobs_from_html_parses_job_cards() -> None:
    html = """
    <html>
      <body>
        <article class="job-card" data-title="Python Engineer" data-company="Example Co" data-location="Shanghai">
          <h2>Python Engineer</h2>
          <div class="company">Example Co</div>
          <div class="location">Shanghai</div>
          <a href="/jobs/1">View</a>
        </article>
      </body>
    </html>
    """

    jobs = extract_jobs_from_html(html, "https://example.com/careers")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Python Engineer"
    assert job.company == "Example Co"
    assert job.location == "Shanghai"
    assert job.url == "https://example.com/jobs/1"
    assert job.source == "https://example.com/careers"
