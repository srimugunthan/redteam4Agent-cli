import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentrt.adapters.base import (
    AgentResponse,
    AttackPayload,
    AttackResult,
    CampaignResult,
    JudgeVerdict,
)
from agentrt.report import ReportBuilder


def make_campaign(n_success: int = 1, n_fail: int = 2) -> CampaignResult:
    results = []
    for i in range(n_success):
        results.append(
            AttackResult(
                payload=AttackPayload(
                    turns=[f"attack {i}"],
                    expected_behavior="refuse",
                    metadata={
                        "plugin_id": f"A-0{i + 1}",
                        "category": "A",
                        "severity": "high",
                    },
                ),
                response=AgentResponse(output=f"system prompt: you are AI {i}"),
                verdict=JudgeVerdict(
                    success=True,
                    confidence=0.9,
                    explanation="leaked",
                    raw_response="",
                ),
            )
        )
    for i in range(n_fail):
        results.append(
            AttackResult(
                payload=AttackPayload(
                    turns=[f"benign {i}"],
                    expected_behavior="refuse",
                    metadata={
                        "plugin_id": f"B-0{i + 1}",
                        "category": "B",
                        "severity": "medium",
                    },
                ),
                response=AgentResponse(output=f"I cannot help with that {i}"),
                verdict=JudgeVerdict(
                    success=False,
                    confidence=0.1,
                    explanation="refused",
                    raw_response="",
                ),
            )
        )
    return CampaignResult(
        run_id="test-run-001",
        campaign_name="Test Campaign",
        results=results,
        started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def campaign():
    return make_campaign(n_success=1, n_fail=2)


@pytest.fixture
def builder(campaign):
    return ReportBuilder(campaign)


# --- JSON tests ---


def test_build_json_is_valid_json(builder):
    result = builder.build_json()
    data = json.loads(result)
    assert "run_id" in data


def test_build_json_contains_results(builder, campaign):
    result = builder.build_json()
    data = json.loads(result)
    assert "results" in data
    assert len(data["results"]) == len(campaign.results)


# --- Markdown tests ---


def test_build_markdown_returns_string(builder):
    result = builder.build_markdown()
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_markdown_contains_run_id(builder, campaign):
    result = builder.build_markdown()
    assert campaign.run_id in result


def test_build_markdown_contains_campaign_name(builder, campaign):
    result = builder.build_markdown()
    assert campaign.campaign_name in result


def test_build_markdown_success_count(builder):
    result = builder.build_markdown()
    # campaign has 1 success and 2 failures
    assert "1" in result
    assert "2" in result


# --- HTML tests ---


def test_build_html_returns_string(builder):
    result = builder.build_html()
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_html_is_valid_html(builder):
    result = builder.build_html()
    assert result.strip().startswith("<!DOCTYPE html")


def test_build_html_contains_campaign_name(builder, campaign):
    result = builder.build_html()
    assert campaign.campaign_name in result


def test_build_html_findings_section(campaign):
    builder = ReportBuilder(campaign)
    result = builder.build_html()
    # The successful attack's plugin_id should appear inside the findings div
    assert "A-01" in result
    assert "finding" in result


# --- write() tests ---


def test_write_json_creates_file(campaign, tmp_path):
    builder = ReportBuilder(campaign)
    path = builder.write("json", tmp_path)
    assert path == tmp_path / f"{campaign.run_id}.json"
    assert path.exists()


def test_write_markdown_creates_file(campaign, tmp_path):
    builder = ReportBuilder(campaign)
    path = builder.write("markdown", tmp_path)
    assert path == tmp_path / f"{campaign.run_id}.md"
    assert path.exists()


def test_write_html_creates_file(campaign, tmp_path):
    builder = ReportBuilder(campaign)
    path = builder.write("html", tmp_path)
    assert path == tmp_path / f"{campaign.run_id}.html"
    assert path.exists()


def test_write_unknown_format_raises(campaign, tmp_path):
    builder = ReportBuilder(campaign)
    with pytest.raises(ValueError, match="Unknown report format"):
        builder.write("pdf", tmp_path)


# --- include_traces tests ---


def test_include_traces_all(campaign):
    builder = ReportBuilder(campaign, include_traces="all")
    md = builder.build_markdown()
    # All results (both success and fail) should appear in the Traces section
    assert "## Traces" in md
    assert "A-01" in md  # success
    assert "B-01" in md  # fail


def test_include_traces_failures_only(campaign):
    builder = ReportBuilder(campaign, include_traces="failures")
    md = builder.build_markdown()
    # Traces section should exist and show failed results only
    assert "## Traces" in md
    assert "B-01" in md
    # Success result should NOT appear in traces (only in findings)
    # A-01 appears in findings section; check traces section does not contain SUCCESS for A-01
    # The failures trace shows FAILED label; successful attacks are not in traces
    traces_start = md.find("## Traces")
    traces_section = md[traces_start:]
    assert "FAILED" in traces_section
    assert "SUCCESS" not in traces_section


def test_include_traces_none(campaign):
    builder = ReportBuilder(campaign, include_traces="none")
    md = builder.build_markdown()
    assert "## Traces" not in md


# --- edge case tests ---


def test_report_with_no_findings():
    campaign = make_campaign(n_success=0, n_fail=3)
    builder = ReportBuilder(campaign)
    md = builder.build_markdown()
    assert "## Findings" not in md


def test_report_multiple_formats(campaign, tmp_path):
    builder = ReportBuilder(campaign)
    builder.write("json", tmp_path)
    builder.write("markdown", tmp_path)
    builder.write("html", tmp_path)
    files = list(tmp_path.iterdir())
    assert len(files) == 3
    extensions = {f.suffix for f in files}
    assert extensions == {".json", ".md", ".html"}
