from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from src.models import JobPosting, MatchResult


def _write_line(canvas: Canvas, text: str, x: float, y: float, line_height: float) -> float:
    canvas.drawString(x, y, text)
    return y - line_height


def generate_pdf_report(
    path: Path,
    *,
    title: str,
    summary_lines: Iterable[str],
    matched_jobs: Iterable[MatchResult],
    changed_jobs: Iterable[JobPosting],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(path), pagesize=A4)
    width, height = A4
    left = 42
    y = height - 48
    line_height = 16

    canvas.setTitle(title)
    canvas.setFont("Helvetica-Bold", 16)
    y = _write_line(canvas, title, left, y, line_height * 1.4)
    canvas.setFont("Helvetica", 11)
    y -= 8

    for line in summary_lines:
        y = _write_line(canvas, str(line), left, y, line_height)
        if y < 72:
            canvas.showPage()
            canvas.setFont("Helvetica", 11)
            y = height - 48

    y -= 8
    canvas.setFont("Helvetica-Bold", 13)
    y = _write_line(canvas, "Matched Jobs", left, y, line_height)
    canvas.setFont("Helvetica", 10)
    for result in matched_jobs:
        job = result.job
        y = _write_line(canvas, f"- {job.title} | {job.company} | score={result.score:.1f}", left, y, line_height)
        if result.reasons:
            y = _write_line(canvas, f"  reasons: {', '.join(result.reasons)}", left + 14, y, line_height)
        if y < 72:
            canvas.showPage()
            canvas.setFont("Helvetica", 10)
            y = height - 48

    y -= 8
    canvas.setFont("Helvetica-Bold", 13)
    y = _write_line(canvas, "Changed Jobs", left, y, line_height)
    canvas.setFont("Helvetica", 10)
    for job in changed_jobs:
        y = _write_line(canvas, f"- {job.title} | {job.company} | {job.location}", left, y, line_height)
        if y < 72:
            canvas.showPage()
            canvas.setFont("Helvetica", 10)
            y = height - 48

    canvas.save()
    return path
