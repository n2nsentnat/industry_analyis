from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from industry_analysis.company_analysis.application.dto import EnrichRunConfig
from industry_analysis.company_analysis.application.paths import enriched_relpath
from industry_analysis.company_analysis.application.ports import BlobStore, JsonObjectLlmPort
from industry_analysis.company_analysis.domain.models import CompanyAggregate, CompanyEnrichment, CompanyEnrichmentRecord


def _build_user_prompt(aggregate: CompanyAggregate) -> str:
    titles = "\n".join(f"- {t}" for t in aggregate.sample_titles[:20])
    cats = ", ".join(dict.fromkeys(aggregate.category_labels))
    desc = (aggregate.sample_description or "").strip()
    desc = desc[:6000]
    return (
        "You are analyzing hiring demand to infer what a company likely does, where it probably uses UI, "
        "where AI could help (automation, core business improvement, net-new AI products), and where AI "
        "should be avoided.\n\n"
        "Return ONLY valid JSON with EXACTLY these keys:\n"
        '- "Name" (string)\n'
        '- "Industry" (array of strings)\n'
        '- "current_use_of_AI" (string)\n'
        '- "possible_use_of_AI" (string)\n'
        '- "avoid_AI_use" (string)\n\n'
        "Be concrete and conservative where evidence is weak.\n\n"
        f"Company display name: {aggregate.display_name}\n"
        f"Job categories seen in ads: {cats}\n"
        f"Sample job titles:\n{titles}\n\n"
        f"Sample job description snippet:\n{desc}\n"
    )


class EnrichOrchestrator:
    def __init__(
        self,
        *,
        config: EnrichRunConfig,
        store: BlobStore,
        llm: JsonObjectLlmPort,
    ) -> None:
        self._config = config
        self._store = store
        self._llm = llm

    async def run(
        self,
        *,
        provider_id: str,
        country: str,
        companies: dict[str, CompanyAggregate],
        limit: int | None = None,
        force: bool = False,
    ) -> None:
        sem = asyncio.Semaphore(self._config.enrich_concurrency)

        keys = list(companies.keys())
        keys.sort()
        if limit is not None:
            keys = keys[:limit]

        async def one(key: str) -> None:
            aggregate = companies[key]
            rel = enriched_relpath(provider_id, country, aggregate.company_key)
            if not force and await self._store.exists(rel):
                return
            async with sem:
                user_prompt = _build_user_prompt(aggregate)
                obj = await self._llm.generate_company_profile_json(user_prompt)
                enrichment = CompanyEnrichment.model_validate(obj)
                record = CompanyEnrichmentRecord(
                    enrichment=enrichment,
                    source={
                        "provider_id": provider_id,
                        "country": country,
                        "company_key": aggregate.company_key,
                        "generated_at": datetime.now(UTC).isoformat(),
                        "model": self._config.model_label,
                    },
                )
                await self._store.write_json(rel, record.model_dump(mode="json"))

        await asyncio.gather(*(one(k) for k in keys))
