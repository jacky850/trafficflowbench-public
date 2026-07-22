"""Small public helpers used by the Task 2 baseline."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def thresholds(panel_dir: Path, links: pd.DataFrame) -> tuple[dict[str, float], str]:
    """Return released queue speed cutoffs with a network-speed fallback."""
    fallback = pd.to_numeric(links["free_speed_kmh"], errors="coerce").fillna(105.0) * 0.60
    values = dict(zip(links["link_id"].astype(str), fallback.astype(float)))
    fd = panel_dir / "network" / "fd_parameters.csv"
    if fd.exists():
        frame = pd.read_csv(fd)
        if "v_cut" in frame.columns:
            for row in frame.dropna(subset=["link_id", "v_cut"]).itertuples(index=False):
                values[str(row.link_id)] = float(row.v_cut)
            return values, "released_fd_parameters_with_network_fallback"
    return values, "0.6_times_network_free_speed_fallback"
