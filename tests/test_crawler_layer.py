from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.crawler import crawl_company_pages, load_company_candidates_from_selection
from src.models import CompanyCandidate
from src.prompt import build_channel_status_messages, build_latest_date_messages


SELECTION_PATHS = (
    Path("output/result_output/job_watch_selection.json"),
    Path("output/test_output/test_relay_connect.json"),
)
OUTPUT_PATH = Path("output/test_output/test_crawler_layer.json")


@pytest.mark.integration
def test_crawler_can_crawl_selected_company_pages() -> None:
    selection_path, candidates = _load_candidates_from_selection_paths()
    if selection_path is None:
        pytest.skip("Run the selection stage first to generate crawlable company candidates")

    selection_payload = json.loads(selection_path.read_text(encoding="utf-8"))
    selection_section = selection_payload.get("selection") if isinstance(selection_payload, dict) else {}
    job_role = str(selection_payload.get("job_role", "")) if isinstance(selection_payload, dict) else ""
    top_x = int(selection_payload.get("top_x", len(candidates))) if isinstance(selection_payload, dict) else len(candidates)

    crawl_limit = int(os.getenv("JOB_WATCH_CRAWLER_TEST_LIMIT", "30"))
    selected_candidates = candidates[: max(1, crawl_limit)]
    pages = crawl_company_pages(
        selected_candidates,
        timeout_seconds=int(os.getenv("JOB_WATCH_CRAWLER_TIMEOUT_SECONDS", "15")),
        max_crawl_chars=int(os.getenv("JOB_WATCH_CRAWLER_MAX_CHARS", "12000")),
        max_links_per_page=int(os.getenv("JOB_WATCH_CRAWLER_MAX_LINKS", "20")),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "selection_source": str(selection_path),
                "job_role": job_role,
                "top_x": top_x,
                "selected_companies": [
                    {
                        "rank": candidate.rank,
                        "name": candidate.name,
                        "recruitment_url": candidate.recruitment_url,
                    }
                    for candidate in selected_candidates
                ],
                "crawled_pages": [
                    {
                        "company": page.company,
                        "page_url": page.page_url,
                        "site_type": page.site_type,
                        "channel_status": page.channel_status,
                        "date_candidates": page.date_candidates[:1],
                        "error": page.error,
                    }
                    for page in pages
                ],
                "latest_date_request": build_latest_date_messages(
                    job_role,
                    selected_candidates[0].name if selected_candidates else "",
                    pages[0].page_url if pages else "",
                    pages[0].title if pages else "",
                    pages[0].text if pages else "",
                    pages[0].links if pages else [],
                ),
                "channel_status_request": build_channel_status_messages(
                    job_role,
                    selected_candidates[0].name if selected_candidates else "",
                    pages[0].page_url if pages else "",
                    pages[0].title if pages else "",
                    pages[0].text if pages else "",
                    pages[0].links if pages else [],
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert len(pages) == len(selected_candidates)
    assert all(page.company.strip() for page in pages)
    assert all(page.recruitment_url.strip() for page in pages)
    assert any(_has_useful_crawl_result(page) for page in pages), "all selected company pages failed to crawl"


def _load_candidates_from_selection_paths() -> tuple[Path | None, list[CompanyCandidate]]:
    for path in SELECTION_PATHS:
        if not path.exists():
            continue
        candidates = load_company_candidates_from_selection(path)
        if candidates:
            return path, candidates
    return None, []


def _has_useful_crawl_result(page: object) -> bool:
    return bool(
        not getattr(page, "error")
        and (
            getattr(page, "title")
            or getattr(page, "text")
            or getattr(page, "links")
            or getattr(page, "date_candidates")
        )
    )
