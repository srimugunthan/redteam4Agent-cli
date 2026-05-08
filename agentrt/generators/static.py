from __future__ import annotations

import json
from typing import TYPE_CHECKING, List

from jinja2 import Template

from agentrt.adapters.base import AttackPayload
from agentrt.generators.base import ProbeGenerator

if TYPE_CHECKING:
    from agentrt.attacks.base import AttackContext, AttackPlugin


class StaticProbeGenerator(ProbeGenerator):
    """Generate probes from plugin seed queries or Jinja2 templates without LLM calls."""

    async def generate(
        self,
        plugin: "AttackPlugin",
        context: "AttackContext",
    ) -> List[AttackPayload]:
        expected_behavior = getattr(plugin, "name", "") or ""
        metadata_base = {"plugin_id": plugin.id, "generator": "static"}

        # Case 1: template + dataset
        if plugin.probe_template and plugin.dataset_path:
            template = Template(plugin.probe_template)
            payloads: List[AttackPayload] = []
            with open(plugin.dataset_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    rendered = template.render(**row)
                    payloads.append(
                        AttackPayload(
                            turns=[rendered],
                            expected_behavior=expected_behavior,
                            metadata=dict(metadata_base),
                        )
                    )
            return payloads

        # Case 2: template only, no dataset
        if plugin.probe_template:
            template = Template(plugin.probe_template)
            rendered = template.render()
            return [
                AttackPayload(
                    turns=[rendered],
                    expected_behavior=expected_behavior,
                    metadata=dict(metadata_base),
                )
            ]

        # Case 3: no template — one payload per seed query
        return [
            AttackPayload(
                turns=[query],
                expected_behavior=expected_behavior,
                metadata=dict(metadata_base),
            )
            for query in plugin.seed_queries
        ]
