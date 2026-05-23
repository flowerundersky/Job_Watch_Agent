from src.analyzer import AnalyzerSettings, LLMAnalyzer, ModelBackendSettings, OpenAICompatibleAnalyzer
from src.models import JobPosting


def test_analyzer_matches_by_keyword_and_company() -> None:
    analyzer = LLMAnalyzer(
        AnalyzerSettings(
            keywords=["Python", "LLM"],
            companies=["Example Co"],
            min_score=2.0,
        )
    )
    job = JobPosting(
        title="Python Engineer",
        company="Example Co",
        location="Shanghai",
        description="Build LLM powered internal tooling",
    )

    result = analyzer.analyze([job])[0]

    assert result.matched is True
    assert result.score >= 2.0
    assert any("company matched" in reason for reason in result.reasons)


def test_analyzer_rejects_unrelated_job() -> None:
    analyzer = LLMAnalyzer(AnalyzerSettings(keywords=["Python"], companies=[], min_score=1.0))
    job = JobPosting(title="HR Specialist", company="Example Co", description="Recruitment operations")

    result = analyzer.analyze([job])[0]

    assert result.matched is False
    assert result.score == 0.0


def test_openai_compatible_backend_parses_json_response(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"matched": true, "score": 2.5, "reasons": ["keyword matched: Python", "company matched: Example Co"]}'
                        }
                    }
                ]
            }

    captured = {}

    def fake_post(url, headers, json, timeout):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.analyzer.requests.post", fake_post)

    analyzer = OpenAICompatibleAnalyzer(
        AnalyzerSettings(keywords=["Python"], companies=["Example Co"], min_score=1.0),
        ModelBackendSettings(
            backend="openai_compatible",
            api_base_url="https://proxy.example.com/v1",
            api_key="test-token",
            model="qwen-plus",
            timeout_seconds=12,
            temperature=0.1,
            max_tokens=256,
        ),
    )
    job = JobPosting(title="Python Engineer", company="Example Co", location="Shanghai", description="Build tools")

    result = analyzer.analyze([job])[0]

    assert captured["url"] == "https://proxy.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["json"]["model"] == "qwen-plus"
    assert captured["timeout"] == 12
    assert result.matched is True
    assert result.score == 2.5
    assert "Python" in " ".join(result.reasons)
