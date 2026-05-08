from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader

from agentrt.adapters.base import CampaignResult

IncludeTraces = Literal["all", "failures", "none"]

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class ReportBuilder:
    """Generates reports from a CampaignResult in JSON, Markdown, or HTML format."""

    def __init__(
        self,
        campaign: CampaignResult,
        include_traces: IncludeTraces = "failures",
        severity_threshold: str = "medium",
    ) -> None:
        self._campaign = campaign
        self._include_traces = include_traces
        self._severity_threshold = severity_threshold

    def build_json(self) -> str:
        """Return full CampaignResult as indented JSON string."""
        return self._campaign.model_dump_json(indent=2)

    def _render(self, template_name: str) -> str:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,
        )
        tmpl = env.get_template(template_name)
        findings = [r for r in self._campaign.results if r.verdict.success]
        if self._include_traces == "all":
            traces = list(self._campaign.results)
        elif self._include_traces == "failures":
            traces = [r for r in self._campaign.results if not r.verdict.success]
        else:  # "none"
            traces = []
        return tmpl.render(
            campaign=self._campaign,
            findings=findings,
            traces=traces,
        )

    def build_markdown(self) -> str:
        """Render the Markdown report using the Jinja2 template."""
        return self._render("report.md.j2")

    def build_html(self) -> str:
        """Render the HTML report using the Jinja2 template."""
        return self._render("report.html.j2")

    def write(self, fmt: str, output_dir: Path) -> Path:
        """Write the report to output_dir/{run_id}.{ext}. Returns the written path."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            content = self.build_json()
            ext = "json"
        elif fmt == "markdown":
            content = self.build_markdown()
            ext = "md"
        elif fmt == "html":
            content = self.build_html()
            ext = "html"
        else:
            raise ValueError(f"Unknown report format: {fmt!r}. Choose json, markdown, or html.")
        path = output_dir / f"{self._campaign.run_id}.{ext}"
        path.write_text(content, encoding="utf-8")
        return path
