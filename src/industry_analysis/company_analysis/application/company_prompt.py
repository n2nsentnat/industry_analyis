"""Prompt text shared by fetch (insights) and standalone enrich."""

from industry_analysis.company_analysis.domain.models import CompanyAggregate


def build_company_enrichment_prompt(aggregate: CompanyAggregate) -> str:
    titles = "\n".join(f"- {t}" for t in aggregate.sample_titles[:20])
    cats = ", ".join(dict.fromkeys(aggregate.category_labels))
    desc = (aggregate.sample_description or "").strip()
    desc = desc[:6000]
    return (
        "You are analyzing hiring demand to infer what a company likely does, where it probably uses UI, "
        "where AI could help (automation, core business improvement, net-new AI products), and where AI "
        "should be avoided.\n\n"
        "The API enforces this shape; use only these keys (exact spelling, including case).\n\n"
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
