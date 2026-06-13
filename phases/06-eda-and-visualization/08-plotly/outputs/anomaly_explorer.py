from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly
import plotly.graph_objects as go
import plotly.io as pio

PLATFORMS = ["web", "ios", "android"]
COLORS = {"web": "#2563eb", "ios": "#059669", "android": "#dc2626"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path).drop_duplicates("user_id").copy()
    frame = frame[frame["observed_days"].eq(7)]
    frame = frame[pd.to_numeric(frame["onboarding_seconds"], errors="coerce").ge(0)]
    return frame


def build_figure(frame: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for platform in PLATFORMS:
        part = frame[frame["platform"].eq(platform)]
        customdata = part[
            ["user_id", "app_version", "cohort_week", "acquisition_channel", "activated_7d"]
        ].to_numpy()
        figure.add_trace(
            go.Scatter(
                x=part["sessions_7d"],
                y=part["onboarding_seconds"],
                mode="markers",
                name=platform,
                marker={"color": COLORS[platform], "size": 9, "opacity": 0.7},
                customdata=customdata,
                hovertemplate=(
                    "user=%{customdata[0]}<br>"
                    "platform=" + platform + "<br>"
                    "version=%{customdata[1]}<br>"
                    "cohort=%{customdata[2]}<br>"
                    "channel=%{customdata[3]}<br>"
                    "activated=%{customdata[4]}<br>"
                    "sessions=%{x}<br>"
                    "onboarding=%{y}s<extra></extra>"
                ),
            )
        )
    buttons = [
        {
            "label": "Все платформы",
            "method": "update",
            "args": [{"visible": [True] * len(PLATFORMS)}],
        }
    ]
    for selected in PLATFORMS:
        buttons.append(
            {
                "label": selected,
                "method": "update",
                "args": [{"visible": [platform == selected for platform in PLATFORMS]}],
            }
        )
    figure.update_layout(
        title="Drill-down в длительность onboarding",
        xaxis_title="sessions_7d",
        yaxis_title="onboarding_seconds",
        template="plotly_white",
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 1.0, "y": 1.18}],
        legend_title="platform",
    )
    return figure


def export_explorer(input_path: Path, output_dir: Path) -> dict[str, Any]:
    frame = load_frame(input_path)
    figure = build_figure(frame)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "anomaly-explorer.html"
    json_path = output_dir / "anomaly-explorer.plotly.json"
    figure.write_html(
        html_path,
        include_plotlyjs=True,
        full_html=True,
        auto_open=False,
        config={"displaylogo": False, "responsive": True},
    )
    pio.write_json(figure, json_path, pretty=True, remove_uids=True)
    report = {
        "version": "1.0.0",
        "library": f"plotly {plotly.__version__}",
        "source_rows": len(frame),
        "traces": len(figure.data),
        "trace_names": [trace.name for trace in figure.data],
        "hover_fields": [
            "user_id",
            "platform",
            "app_version",
            "cohort_week",
            "acquisition_channel",
            "activated_7d",
            "sessions_7d",
            "onboarding_seconds",
        ],
        "drill_down": "platform dropdown",
        "dash_required": False,
        "files": {
            html_path.name: {
                "bytes": html_path.stat().st_size,
                "sha256": sha256_file(html_path),
            },
            json_path.name: {
                "bytes": json_path.stat().st_size,
                "sha256": sha256_file(json_path),
            },
        },
    }
    (output_dir / "interactive-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standalone Plotly explorer")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = export_explorer(args.input, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
