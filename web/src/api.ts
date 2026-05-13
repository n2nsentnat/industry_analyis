export type Category = { tag: string; insight_count: number };

export type IndustryAgg = {
  industry: string;
  companies: number;
  mean_current_ai: number;
  mean_ai_upgrade: number;
  mean_avoid_signal: number;
  adoption_index: number;
  upgrade_pressure: number;
};

export type CompanyRow = {
  company_key: string;
  category_dir: string;
  Name: string;
  Industry: string[];
  current_use_preview: string;
  possible_use_preview: string;
};

export async function fetchCategories(): Promise<Category[]> {
  const r = await fetch("/api/job-intel/categories");
  if (!r.ok) throw new Error(`categories HTTP ${r.status}`);
  return (await r.json()) as Category[];
}

export async function fetchAggregates(
  category: string | null,
  topN: number,
): Promise<{ data: IndustryAgg[] }> {
  const q = new URLSearchParams({ top_n: String(topN) });
  if (category) q.set("category", category);
  const r = await fetch(`/api/job-intel/aggregates?${q}`);
  if (!r.ok) throw new Error(`aggregates HTTP ${r.status}`);
  return (await r.json()) as { data: IndustryAgg[] };
}

export async function fetchCompanies(category: string | null, limit: number): Promise<CompanyRow[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (category) q.set("category", category);
  const r = await fetch(`/api/job-intel/companies?${q}`);
  if (!r.ok) throw new Error(`companies HTTP ${r.status}`);
  const body = (await r.json()) as { data: CompanyRow[] };
  return body.data;
}
