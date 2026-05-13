"""Matplotlib charts for industry-level insight aggregates."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

_mpl_cfg = Path(tempfile.gettempdir()) / "job_intel_mpl_config"
_mpl_cfg.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_cfg))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _short_labels(series: pd.Series, max_len: int = 42) -> list[str]:
    out: list[str] = []
    for x in series.astype(str):
        x = x.strip()
        if len(x) > max_len:
            x = x[: max_len - 1] + "…"
        out.append(x)
    return out


def _barh_chart(
    df: pd.DataFrame,
    *,
    value_col: str,
    title: str,
    xlabel: str,
    out_path: Path,
    top_n: int,
) -> None:
    if df.empty or value_col not in df.columns:
        return
    plot_df = df.nlargest(top_n, value_col).sort_values(value_col, ascending=True)
    if plot_df.empty:
        return
    labels = _short_labels(plot_df["industry"])
    fig, ax = plt.subplots(figsize=(10, max(4.0, 0.35 * len(plot_df))))
    ax.barh(labels, plot_df[value_col].astype(float), color="#2c5282")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel(xlabel)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def write_industry_report_charts(agg: pd.DataFrame, out_dir: Path, *, top_n: int = 15) -> list[Path]:
    """
    Write PNGs: current-AI signal, upgrade signal, adoption index, company volume.
    Returns paths written.
    """
    written: list[Path] = []
    if agg.empty:
        return written

    charts: list[tuple[str, str, str, str]] = [
        (
            "mean_current_ai",
            "Industry vs inferred current AI use (heuristic)",
            "Mean keyword / length score (higher → more AI-related language in current_use_of_AI)",
            "industry_current_ai_usage.png",
        ),
        (
            "mean_ai_upgrade",
            "Industry vs inferred AI upgrade opportunity",
            "Mean score on possible_use_of_AI text",
            "industry_ai_upgrade_opportunity.png",
        ),
        (
            "adoption_index",
            "Industry adoption index (current AI signal, avoid-penalized)",
            "mean_current_ai − 0.2 × mean_avoid_signal",
            "industry_ai_adoption_index.png",
        ),
        (
            "companies",
            "Companies per industry (row explosion: multi-industry firms count in each)",
            "Distinct company_key per industry label",
            "industry_company_counts.png",
        ),
        (
            "upgrade_pressure",
            "Industry AI upgrade pressure (opportunity vs current baseline)",
            "mean_ai_upgrade − 0.15 × mean_current_ai",
            "industry_ai_upgrade_pressure.png",
        ),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    full_csv = out_dir / "industry_aggregate_full.csv"
    agg.to_csv(full_csv, index=False)
    written.append(full_csv)

    for col, title, xlabel, fname in charts:
        path = out_dir / fname
        _barh_chart(agg, value_col=col, title=title, xlabel=xlabel, out_path=path, top_n=top_n)
        if path.is_file():
            written.append(path)

    # Ranked table: "top adopter" style
    top_adopters = agg.nlargest(top_n, "mean_current_ai")[
        ["industry", "companies", "mean_current_ai", "mean_ai_upgrade", "adoption_index"]
    ]
    csv_path = out_dir / "industry_top_by_current_ai.csv"
    top_adopters.to_csv(csv_path, index=False)
    written.append(csv_path)
    return written
