"""Task 3 mode-aware LWR/FD evaluator (organizer V1 contract)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from task1.baseline_task1_historical_mean import files, stable_mask

HERE = Path(__file__).resolve().parent.parent.parent
DEFAULT_RELEASE = HERE / "data_public" / "kaggle_release"
REGIMES = ("R1", "R2", "R3")
PHYS_COLUMNS = {"panel","timestamp","link_id","mask_regime","speed_kmh","flow_vph",
                "density_vpkm","inflow_vph","outflow_vph","on_ramp_flow_vph",
                "off_ramp_flow_vph","on_ramp_valid","off_ramp_valid","accumulation_N"}

def state_for_regime(panel: str, panel_dir: Path, split: str, regime: str, state_panel: pd.DataFrame):
    """Reconstruct the complete eligible state using the submitted masked cells."""
    pieces=[]; missing=0
    sr=state_panel[state_panel.mask_regime==regime][["timestamp","station_id","link_id","speed_kmh","flow_vph"]].copy()
    sr.timestamp=pd.to_datetime(sr.timestamp,utc=True); sr.station_id=sr.station_id.astype(str); sr.link_id=sr.link_id.astype(str)
    for path in files(panel_dir, split):
        f=pd.read_parquet(path, columns=["date","timestamp","station_id","link_id","speed_kmh","flow_vph","is_score_eligible"])
        f.station_id=f.station_id.astype(str); f.link_id=f.link_id.astype(str); raw=f.timestamp.astype(str); f.timestamp=pd.to_datetime(f.timestamp,utc=True)
        elig=f.is_score_eligible.astype(bool).to_numpy(); f=f.loc[elig].copy(); target=stable_mask(panel,regime,f.date,raw[elig],f.link_id)
        base=f[["timestamp","station_id","link_id","speed_kmh","flow_vph"]].rename(columns={"speed_kmh":"true_speed","flow_vph":"true_flow"})
        keys=["timestamp","station_id","link_id"]; pred=f.loc[target,keys].merge(sr,on=keys,how="left",validate="one_to_one"); missing += int(pred.speed_kmh.isna().sum()+pred.flow_vph.isna().sum()); pred["is_target"]=True
        base=base.merge(pred[keys+['speed_kmh','flow_vph','is_target']],on=keys,how='left'); it=base.is_target.fillna(False).to_numpy()
        base["speed_kmh"]=np.where(it,base.speed_kmh,base.true_speed); base["flow_vph"]=np.where(it,base.flow_vph,base.true_flow); pieces.append(base[["timestamp","link_id","speed_kmh","flow_vph"]])
    if not pieces: return pd.DataFrame(columns=["timestamp","link_id","speed_kmh","flow_vph"]),missing
    full=pd.concat(pieces,ignore_index=True); return full.groupby(["timestamp","link_id"],as_index=False).mean(numeric_only=True),missing

def read_csv_checked(path: Path, required: set[str], name: str, dedup_keys=None):
    if not path.exists(): raise FileNotFoundError(f"{name} file not found: {path}")
    d = pd.read_csv(path)
    miss = sorted(required - set(d.columns))
    if miss: raise ValueError(f"{name} is missing required columns: {miss}")
    d = d.copy(); d["panel"] = d.panel.astype(str); d["link_id"] = d.link_id.astype(str)
    d["mask_regime"] = d.mask_regime.astype(str)
    d["timestamp"] = pd.to_datetime(d.timestamp, utc=True, errors="coerce")
    if d.timestamp.isna().any(): raise ValueError(f"{name} contains unparseable timestamps")
    if dedup_keys:
        n = int(d.duplicated(dedup_keys).sum())
        if n: raise ValueError(f"{name} contains {n} duplicate keys over {dedup_keys}")
    return d

def network_parameters(panel_dir: Path):
    n = pd.read_csv(panel_dir / "network" / "links.csv")
    n.link_id = n.link_id.astype(str); n = n.drop_duplicates("link_id")
    keep = ["link_id","length_km","free_speed_kmh","capacity_vph","lanes"]
    out = n[keep].copy()
    for c, default in (("length_km",1.0),("free_speed_kmh",100.0)):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(default)
    out["lanes"] = pd.to_numeric(out["lanes"], errors="coerce").fillna(1.0).clip(lower=1.0)
    out.capacity_vph = pd.to_numeric(out.capacity_vph, errors="coerce")
    lanes = pd.to_numeric(n.get("lanes", pd.Series(4.0, index=n.index)), errors="coerce").fillna(4.0)
    lane_fallback = pd.Series(1800.0 * lanes.to_numpy(), index=n.index)
    lane_fallback.index = out.index
    out.capacity_vph = out.capacity_vph.fillna(lane_fallback)
    fd = panel_dir / "network" / "fd_parameters.csv"
    if fd.exists():
        f = pd.read_csv(fd); f.link_id = f.link_id.astype(str)
        out = out.merge(f.groupby("link_id", as_index=False)[["critical_density","k_jam"]].mean(), on="link_id", how="left")
    else: out["critical_density"] = np.nan; out["k_jam"] = np.nan
    out["critical_density"] = out.critical_density.fillna(out.capacity_vph / out.free_speed_kmh.clip(lower=1))
    out["k_jam"] = out.k_jam.fillna(2 * out.critical_density)
    return out

def score_panel(panel, d, release, mode_cfg, regime):
    x = d[(d.panel == panel) & (d.mask_regime == regime)].copy()
    if x.empty: return {"level":"panel_regime","panel":panel,"regime":regime,"S_physics":0.0,"n_rows":0}
    p = network_parameters(release / "corridors" / panel).set_index("link_id")
    x = x.join(p, on="link_id", rsuffix="_net")
    num = ["speed_kmh","flow_vph","density_vpkm","inflow_vph","outflow_vph","on_ramp_flow_vph","off_ramp_flow_vph","on_ramp_valid","off_ramp_valid","accumulation_N"]
    for c in num: x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=num + ["length_km","free_speed_kmh","capacity_vph","critical_density","k_jam"])
    if x.empty: return {"level":"panel_regime","panel":panel,"regime":regime,"S_physics":0.0,"n_rows":0}
    # FD is evaluated on submitted sensored state rows.
    # FD is evaluated in per-lane units. Conservation below remains in total
    # flow/vehicle units. The released PeMS flow and density fields are total
    # link quantities, so only this FD branch divides by lane count.
    lanes = x.lanes.clip(lower=1.0)
    q_lane = x.flow_vph / lanes
    k_lane = x.density_vpkm / lanes
    cap_lane = x.capacity_vph / lanes
    kcrit_lane = x.critical_density / lanes
    kjam_lane = x.k_jam / lanes
    q_fd = np.where(k_lane <= kcrit_lane, x.free_speed_kmh*k_lane,
                    (cap_lane/np.maximum(kjam_lane-kcrit_lane,1e-9))*np.maximum(kjam_lane-k_lane,0))
    s_fd = float(max(0.0, 1.0 - np.abs(q_lane-q_fd).sum()/(np.abs(q_lane).sum()+1e-9)))
    mode = str(mode_cfg["panels"][panel]["mode"])
    # Link/time conservation. Mode C excludes links with attached ramps.
    topo_path = release / "corridors" / panel / "network" / "lwr_mainline_topology.csv"
    topo = pd.read_csv(topo_path, dtype=str) if topo_path.exists() else pd.DataFrame()
    ramp_mainline_links = set()
    if not topo.empty and "on_ramp_link_ids" in topo.columns:
        ramp_mainline_links.update(topo.loc[topo.on_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"].astype(str))
    if not topo.empty and "off_ramp_link_ids" in topo.columns:
        ramp_mainline_links.update(topo.loc[topo.off_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"].astype(str))
    if mode == "C" and ramp_mainline_links:
        # Mode C scores only mainline links with no attached ramp. The ramp
        # IDs themselves are not the scored mainline link IDs.
        x = x[~x.link_id.isin(ramp_mainline_links)].copy()
    # The public Task 3 universe contains detector/sensored links, while the
    # released topology also contains latent mainline links between detectors.
    # A conservation residual is not identifiable at a sensor link when one
    # of its internal mainline neighbours is absent from the submission.  The
    # old evaluator silently replaced that missing neighbour with the current
    # link's own flow, which manufactured a large LWR error.  Score only
    # observable transitions; external connector links are legitimate
    # boundaries and are not treated as missing evidence.
    if not topo.empty and "link_id" in topo.columns:
        topo_ids = set(topo.link_id.astype(str))
        submitted_ids = set(x.link_id.astype(str))
        observable_by_link = {}
        for row in topo.itertuples(index=False):
            incoming = {v.strip() for v in str(getattr(row, "incoming_link_ids", "")).split(";") if v.strip()}
            outgoing = {v.strip() for v in str(getattr(row, "outgoing_link_ids", "")).split(";") if v.strip()}
            observable_by_link[str(row.link_id)] = (
                (incoming & topo_ids).issubset(submitted_ids)
                and (outgoing & topo_ids).issubset(submitted_ids)
            )
        x = x[x.link_id.astype(str).map(observable_by_link).fillna(False)].copy()
    x = x.sort_values(["link_id","timestamp"])
    # Use the forward interval N(t+dt)-N(t), matching the baseline builder
    # and the conservation equation evaluated at the interval start.
    x["dN"] = x.groupby("link_id").accumulation_N.shift(-1) - x.accumulation_N
    x["dt"] = (x.groupby("link_id").timestamp.shift(-1) - x.timestamp).dt.total_seconds()/3600.0
    x = x[(x.dt > 0) & (x.dt <= 5.1/60.0)].copy()
    if mode in ("A", "B"):
        # Attached-ramp transitions are scoreable only when the corresponding
        # released ramp cells are valid. Structural no-ramp links carry 1.
        x = x[(x.on_ramp_valid >= 0.5) & (x.off_ramp_valid >= 0.5)].copy()
    if x.empty: s_lwr = 0.0; e_lwr = 1.0
    else:
        rhs = x.dt * (x.inflow_vph + x.on_ramp_flow_vph - x.outflow_vph - x.off_ramp_flow_vph)
        resid = (x.dN-rhs).abs(); e_lwr = float(resid.sum()/(rhs.abs().sum()+1e-9)); s_lwr = max(0.0,1.0-min(1.0,e_lwr))
    s_phys = (s_fd + 2*s_lwr)/3.0
    return {"level":"panel_regime","panel":panel,"regime":regime,"mode":mode,"n_rows":int(len(x)),"S_FD":s_fd,"S_LWR":s_lwr,"E_LWR":e_lwr,"S_physics":s_phys}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--physics-submission",type=Path,required=True); ap.add_argument("--state-submission",type=Path,help="retained for pipeline compatibility; state fields are carried in the physics submission"); ap.add_argument("--release-root",type=Path,default=DEFAULT_RELEASE); ap.add_argument("--output",type=Path,default=HERE/"reports"/"task3_eval_validation.csv"); ap.add_argument("--panel",action="append")
    a=ap.parse_args(); d=read_csv_checked(a.physics_submission.resolve(),PHYS_COLUMNS,"Task 3 physics submission",["panel","timestamp","link_id","mask_regime"])
    cfg=json.loads((HERE/"config"/"task3_lwr_modes.json").read_text(encoding="utf-8")); manifest=json.loads((HERE/"config"/"corridors.json").read_text(encoding="utf-8")); panels=[p["corridor_id"] for p in manifest["panels"]]
    if a.panel: panels=[p for p in panels if p in set(a.panel)]
    rows=[]
    for panel in panels:
        print(f"[Task3 LWR/FD evaluator] {panel}",flush=True)
        rows += [score_panel(panel,d,a.release_root.resolve(),cfg,r) for r in REGIMES]
    detail=pd.DataFrame(rows); panel_mean=detail.groupby("panel",as_index=False).agg(S_physics=("S_physics","mean"),n_rows=("n_rows","sum")); overall=float(panel_mean.S_physics.mean()) if len(panel_mean) else 0.0
    out=pd.concat([detail,pd.DataFrame([{"level":"overall","panel":"ALL","regime":"macro_mean","S_physics":overall,"n_rows":int(detail.n_rows.sum())}])],ignore_index=True); a.output.parent.mkdir(parents=True,exist_ok=True); out.to_csv(a.output,index=False); print(f"Wrote {a.output}"); print(f"Overall S_physics = {overall:.6f}")
if __name__ == "__main__": main()
