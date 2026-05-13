import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Category, CompanyRow, IndustryAgg } from "./api";
import { fetchAggregates, fetchCategories, fetchCompanies } from "./api";

function shortLabel(s: string, max = 36): string {
  const t = s.trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

function toVerticalChart(rows: IndustryAgg[], valueKey: keyof IndustryAgg, take = 18) {
  const sorted = [...rows].sort((a, b) => Number(b[valueKey]) - Number(a[valueKey])).slice(0, take);
  return sorted.reverse().map((r) => ({
    label: shortLabel(r.industry),
    value: Number(r[valueKey]),
  }));
}

function IndustryBar({
  title,
  subtitle,
  rows,
  valueKey,
}: {
  title: string;
  subtitle: string;
  rows: IndustryAgg[];
  valueKey: keyof IndustryAgg;
}) {
  const data = useMemo(() => toVerticalChart(rows, valueKey), [rows, valueKey]);
  if (!data.length) {
    return (
      <div className="card">
        <h2>{title}</h2>
        <p className="sub">{subtitle}</p>
        <p>No rows.</p>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="sub">{subtitle}</p>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart layout="vertical" data={data} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="label" width={150} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => v.toFixed(3)} />
          <Bar dataKey="value" fill="#2c5282" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function App() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [category, setCategory] = useState<string>("");
  const [aggregates, setAggregates] = useState<IndustryAgg[]>([]);
  const [companies, setCompanies] = useState<CompanyRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cat = category || null;
      const [cats, aggBody, comps] = await Promise.all([
        fetchCategories(),
        fetchAggregates(cat, 40),
        fetchCompanies(cat, 50),
      ]);
      setCategories(cats);
      setAggregates(aggBody.data);
      setCompanies(comps);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="app">
      <header>
        <h1>Job intel — industry &amp; AI signals</h1>
        <p>
          Charts use the same heuristics as <span className="mono">job-intel analyze</span> (keyword + length scores on
          LLM text). Not ground-truth adoption metrics.
        </p>
      </header>

      <div className="toolbar">
        <label htmlFor="cat">Category</label>
        <select
          id="cat"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Category filter"
        >
          <option value="">All categories (+ legacy enriched)</option>
          {categories.map((c) => (
            <option key={c.tag} value={c.tag}>
              {c.tag} ({c.insight_count} insights)
            </option>
          ))}
        </select>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error ? <div className="err">{error}</div> : null}

      <div className="grid">
        <IndustryBar
          title="Inferred current AI use (by industry)"
          subtitle="Higher → more AI-related language in current_use_of_AI"
          rows={aggregates}
          valueKey="mean_current_ai"
        />
        <IndustryBar
          title="AI upgrade / opportunity (by industry)"
          subtitle="Scores on possible_use_of_AI"
          rows={aggregates}
          valueKey="mean_ai_upgrade"
        />
        <IndustryBar
          title="Adoption index"
          subtitle="current signal − 0.2 × avoid signal"
          rows={aggregates}
          valueKey="adoption_index"
        />
        <IndustryBar
          title="Company count (by industry label)"
          subtitle="Distinct employers; multi-label firms count in each industry"
          rows={aggregates}
          valueKey="companies"
        />
      </div>

      <div className="card" style={{ marginTop: "1.25rem" }}>
        <h2>Sample companies</h2>
        <p className="sub">Truncated previews; full JSON remains on disk.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Industry</th>
                <th>Current AI (preview)</th>
                <th>Possible AI (preview)</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((c) => (
                <tr key={`${c.category_dir}/${c.company_key}`}>
                  <td>{c.Name}</td>
                  <td className="mono">{c.Industry.join(", ")}</td>
                  <td>{c.current_use_preview}</td>
                  <td>{c.possible_use_preview}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p style={{ marginTop: "1.5rem", fontSize: "0.85rem", color: "#718096" }}>
        Run <span className="mono">uv run api</span> then <span className="mono">cd web &amp;&amp; npm run dev</span>.
        Production: <span className="mono">npm run build</span> and open <span className="mono">http://127.0.0.1:8000/ui/</span>
      </p>
    </div>
  );
}
