"""Task 3 mode-aware LWR/FD evaluator (organizer V1 contract)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
# Make the sibling task packages importable when this file is run as a script,
# so no PYTHONPATH is needed.
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

from task1.baseline_task1_historical_mean import files, regime_of_dates, stable_mask

HERE = Path(__file__).resolve().parent.parent.parent
DEFAULT_RELEASE = HERE / "data_public" / "kaggle_release"
REGIMES = ("R1", "R2", "R3")
PHYS_COLUMNS = {"panel","timestamp","link_id","mask_regime","speed_kmh","flow_vph",
                "density_vpkm","inflow_vph","outflow_vph","on_ramp_flow_vph",
                "off_ramp_flow_vph","on_ramp_valid","off_ramp_valid","accumulation_N"}
# Zero flow at zero density lies exactly on the fundamental diagram, so a cell
# claiming an empty road is perfectly self-consistent and vanishes from a ratio
# normalized by submitted flow. Claiming empty roads used to raise S_FD. The
# lowest flow anywhere in the withheld data is 347 vph, on corridors busy around
# the clock, so a panel reporting a fifth of its submitted cells below 50 vph is
# not modelling traffic and forfeits S_FD.
EMPTY_FLOOR_VPH = 50.0
EMPTY_SHARE = 0.20

def published_targets(panel_dir: Path, panel: str, split: str, regime: str) -> set[tuple]:
    """The cells the release actually asks about, read from the published template.

    Not recomputed from stable_mask. The hash draws a slightly larger set than
    the release publishes, because a cell that falls inside a released Task 2
    window is dropped from the Task 1 targets: those windows hand out raw
    observations, so a target inside one would be an answer in plain sight.
    Deriving the target set from the hash here treated those cells as
    unanswered, dropped them from the physics field, and scored Task 3 on a
    field the participant was never asked to produce.
    """
    template = panel_dir.parent.parent / "task1" / panel / split / "sample_submission_state.csv"
    if not template.exists():
        raise FileNotFoundError(f"Task 1 template not found, needed for the Task 3 target set: {template}")
    t = pd.read_csv(template, usecols=["timestamp", "station_id", "link_id", "mask_regime"], dtype=str)
    t = t[t.mask_regime == regime]
    return set(zip(pd.to_datetime(t.timestamp, utc=True), t.station_id, t.link_id))


def state_for_regime(panel: str, panel_dir: Path, split: str, regime: str, state_panel: pd.DataFrame):
    """Reconstruct the complete eligible state using the submitted masked cells."""
    pieces=[]; missing=0
    targets = published_targets(panel_dir, panel, split, regime)
    sr=state_panel[state_panel.mask_regime==regime][["timestamp","station_id","link_id","speed_kmh","flow_vph"]].copy()
    sr.timestamp=pd.to_datetime(sr.timestamp,utc=True); sr.station_id=sr.station_id.astype(str); sr.link_id=sr.link_id.astype(str)
    for path in files(panel_dir, split):
        f=pd.read_parquet(path, columns=["date","timestamp","station_id","link_id","speed_kmh","flow_vph","is_score_eligible"])
        # Each day belongs to one regime and is published only in that view, so
        # a regime is reconstructed from its own days. Without this the other
        # two thirds of the split would contribute unmasked truth to the
        # conservation check and hand out physics the participant never
        # estimated.
        f=f.loc[regime_of_dates(panel, f.date.astype(str))==regime]
        if f.empty: continue
        f.station_id=f.station_id.astype(str); f.link_id=f.link_id.astype(str); raw=f.timestamp.astype(str); f.timestamp=pd.to_datetime(f.timestamp,utc=True)
        elig=f.is_score_eligible.astype(bool).to_numpy(); f=f.loc[elig].copy()
        target=np.fromiter((k in targets for k in zip(f.timestamp,f.station_id,f.link_id)),dtype=bool,count=len(f))
        base=f[["timestamp","station_id","link_id","speed_kmh","flow_vph"]].rename(columns={"speed_kmh":"true_speed","flow_vph":"true_flow"})
        keys=["timestamp","station_id","link_id"]; pred=f.loc[target,keys].merge(sr,on=keys,how="left",validate="one_to_one"); missing += int(pred.speed_kmh.isna().sum()+pred.flow_vph.isna().sum()); pred["is_target"]=True
        base=base.merge(pred[keys+['speed_kmh','flow_vph','is_target']],on=keys,how='left'); it=base.is_target.astype('boolean').fillna(False).to_numpy(dtype=bool)
        base["speed_kmh"]=np.where(it,base.speed_kmh,base.true_speed); base["flow_vph"]=np.where(it,base.flow_vph,base.true_flow); base["is_target"]=it.astype(float); pieces.append(base[["timestamp","link_id","speed_kmh","flow_vph","is_target"]])
    if not pieces: return pd.DataFrame(columns=["timestamp","link_id","speed_kmh","flow_vph","is_target"]),missing
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
    """Per-link triangular FD parameters, taken from one source at a time.

    This used to read lanes/free_speed/capacity from links.csv and only
    critical_density/k_jam from fd_parameters.csv. The two describe different
    worlds. links.csv comes from an OpenStreetMap extract: free_speed is a flat
    105.0 default on every non-placeholder link in all ten panels, and capacity
    is the formula lanes*2000 over map lane tags that disagree with the detector
    station metadata on 461 of 993 rows. fd_parameters.csv is measured -
    free_speed is the q0.99 of observed speed, capacity the q0.999 of observed
    flow, and critical_density is capacity/free_speed by construction.

    Mixing them broke the triangle the scorer then evaluates. On the 856 links
    Task 3 actually scores, v_f * k_crit differed from capacity on 851, by a
    median of 25-37%: the scorer read v_f = 105.0 where the detectors measure
    113-117.5, and capacity 8000-12000 where they measure 6324-9378.

    fd_parameters is now authoritative for all five parameters wherever it
    covers a link. It is keyed by station and several stations can share a link,
    so capacity and free_speed are averaged over the link's stations and
    critical_density is recomputed from the averages - averaging it separately
    would reintroduce the same inconsistency, since mean(v_f) * mean(k_crit) is
    not mean(capacity). length_km has no counterpart there and stays with
    links.csv; it never enters the FD or conservation maths, only the dropna
    guard below.
    """
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
        have = [c for c in ("free_speed_kmh","capacity_vph","lanes","k_jam") if c in f.columns]
        m = f.groupby("link_id", as_index=False)[have].mean()
        out = out.merge(m, on="link_id", how="left", suffixes=("", "_fd"))
        for c in ("free_speed_kmh","capacity_vph","lanes"):
            if f"{c}_fd" in out.columns:
                out[c] = out[f"{c}_fd"].fillna(out[c])
                out = out.drop(columns=[f"{c}_fd"])
        if "k_jam" not in out.columns:
            out["k_jam"] = np.nan
        # Recomputed, never averaged: this is what keeps v_f * k_crit == capacity.
        out["critical_density"] = out.capacity_vph / out.free_speed_kmh.clip(lower=1)
    else:
        out["critical_density"] = out.capacity_vph / out.free_speed_kmh.clip(lower=1)
        out["k_jam"] = np.nan
    # A link with no measured jam density falls back to 100 veh/km/lane, the
    # assumption the released diagrams already use, rather than 2*k_crit - that
    # older fallback forced cap/(k_jam-k_crit) to equal the free-flow speed,
    # putting jam waves at 105 km/h instead of the 15-20 a freeway shows.
    out["k_jam"] = out.k_jam.fillna(100.0 * out.lanes.clip(lower=1.0))
    out["k_jam"] = np.maximum(out.k_jam, out.critical_density * 1.05)
    return out

DT_H = 5.0 / 60.0

def load_ramp_flows(panel_dir: Path, split: str = "validation") -> pd.DataFrame:
    """Aggregate valid released ramp observations to attached mainline links.

    The ramp root follows the split being scored. It used to be pinned to
    "validation", which silently returned no ramp flows whenever a train-split
    release was scored - every attached-ramp link then looked ramp-free.
    """
    amap_path = panel_dir / "network" / "ramp_attachment_map.csv"
    ramp_root = panel_dir / split / "ramp_states"
    cols = ["timestamp", "link_id", "on_ramp_flow_vph", "off_ramp_flow_vph", "on_ramp_valid", "off_ramp_valid"]
    if not amap_path.exists() or not ramp_root.exists():
        return pd.DataFrame(columns=cols)
    amap = pd.read_csv(amap_path, dtype=str).rename(columns={"nearest_mainline_link_id": "link_id"})
    amap["ramp_link_id"] = amap.ramp_link_id.astype(str); amap["link_id"] = amap.link_id.astype(str)
    pieces = []
    for path in sorted(ramp_root.glob("**/*.parquet")):
        f = pd.read_parquet(path, columns=["timestamp","ramp_link_id","ramp_type","flow_vph","pct_observed","is_score_eligible"])
        f["ramp_link_id"] = f.ramp_link_id.astype(str)
        f["timestamp"] = pd.to_datetime(f.timestamp, utc=True)
        f["flow_vph"] = pd.to_numeric(f.flow_vph, errors="coerce")
        f["pct_observed"] = pd.to_numeric(f.pct_observed, errors="coerce")
        f = f[f.is_score_eligible.astype(bool) & (f.pct_observed >= 75) & f.flow_vph.notna()]
        if f.empty: continue
        f = f.merge(amap[["ramp_link_id", "link_id"]], on="ramp_link_id", how="inner")
        is_on = f.ramp_type.astype(str).str.upper().isin(["OR", "ON"])
        is_off = f.ramp_type.astype(str).str.upper().isin(["FR", "OFF"])
        f["on_ramp_flow_vph"] = np.where(is_on, f.flow_vph, 0.0)
        f["off_ramp_flow_vph"] = np.where(is_off, f.flow_vph, 0.0)
        f["on_ramp_valid"] = is_on.astype(int); f["off_ramp_valid"] = is_off.astype(int)
        pieces.append(f[cols])
    if not pieces: return pd.DataFrame(columns=cols)
    return (pd.concat(pieces, ignore_index=True).groupby(["timestamp","link_id"], as_index=False)
            .agg(on_ramp_flow_vph=("on_ramp_flow_vph","sum"), off_ramp_flow_vph=("off_ramp_flow_vph","sum"),
                 on_ramp_valid=("on_ramp_valid","max"), off_ramp_valid=("off_ramp_valid","max")))

def topology_boundary_flows(state: pd.DataFrame, panel_dir: Path) -> pd.DataFrame:
    """Mainline boundary flows implied by the released topology and the state."""
    topo_path = panel_dir / "network" / "lwr_mainline_topology.csv"
    if not topo_path.exists():
        return pd.DataFrame(columns=["timestamp", "link_id", "inflow_vph", "outflow_vph"])
    topo = pd.read_csv(topo_path, dtype=str)
    topo["link_id"] = topo.link_id.astype(str)
    topo = topo.drop_duplicates("link_id").set_index("link_id")
    pivot = state.pivot_table(index="timestamp", columns="link_id", values="flow_vph", aggfunc="mean")
    known = set(pivot.columns.astype(str)); rows = []
    for link in state.link_id.astype(str).drop_duplicates():
        if link not in pivot.columns: continue
        if link in topo.index:
            incoming = [x for x in str(topo.loc[link].get("incoming_link_ids", "")).split(";") if x in known]
            outgoing = [x for x in str(topo.loc[link].get("outgoing_link_ids", "")).split(";") if x in known]
        else:
            incoming, outgoing = [], []
        inflow = pivot[incoming].sum(axis=1) if incoming else pivot[link]
        outflow = pivot[outgoing].sum(axis=1) if outgoing else pivot[link]
        rows.append(pd.DataFrame({"timestamp": pivot.index, "link_id": link,
                                  "inflow_vph": inflow.to_numpy(), "outflow_vph": outflow.to_numpy()}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["timestamp","link_id","inflow_vph","outflow_vph"])

def link_order(panel_dir: Path, split: str = "validation") -> list[str]:
    files_ = sorted((panel_dir / split / "mainline_states").glob("**/*.parquet"))
    if not files_: return []
    first = pd.read_parquet(files_[0], columns=["link_id", "milepost"]).drop_duplicates("link_id").copy()
    first["link_id"] = first.link_id.astype(str)
    first["milepost"] = pd.to_numeric(first.milepost, errors="coerce")
    return first.sort_values(["milepost", "link_id"]).link_id.tolist()

def load_boundary_flux(path: Path | None, panel: str) -> pd.DataFrame:
    """Organizer boundary flows for one panel, keyed by timestamp and link.

    These are organizer-held and never published. They are projected onto the
    released observations, so a participant who reproduces what was published
    satisfies the conservation identity exactly. Deriving them instead from the
    topology and the participant's own flows cannot work at this resolution:
    the conservation signal is 0.75% of the accumulated total, while a
    topology-derived flux misses the simulated one by about 0.22%, a third of
    the signal, which put even the exact truth at S_LWR 0.0.
    """
    cols = ["timestamp", "link_id", "inflow_vph", "outflow_vph"]
    if path is None:
        return pd.DataFrame(columns=cols)
    f = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    missing = set(cols) - set(f.columns) - {"timestamp", "link_id"}
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    if "panel" in f.columns:
        f = f[f.panel.astype(str) == panel]
    f = f.copy()
    f["timestamp"] = pd.to_datetime(f.timestamp, utc=True)
    f["link_id"] = f.link_id.astype(str)
    return f[cols].drop_duplicates(["timestamp", "link_id"])

def derive_physics(panel: str, release: Path, split: str, state_panel: pd.DataFrame,
                   regime: str, order=None, params=None, ramp_flows=None, boundary_flux=None):
    """Derive the Task 3 physics frame from the participant's own Task 1 answer.

    Task 3 asks whether the speeds and flows a participant produced in Task 1
    are physically possible, so it must score those very numbers. Nothing here
    is submitted independently: density is q/v, accumulation is k*L, mainline
    boundary flows come from the released topology applied to the participant's
    own flows, and ramp flows are the released observations. That leaves the
    physics score with no free parameters a participant could tune against it -
    the only way to move it is to change the Task 1 answer, which Task 1 then
    scores on its own terms.
    """
    panel_dir = release / "corridors" / panel
    if params is None: params = network_parameters(panel_dir).set_index("link_id")
    if order is None: order = link_order(panel_dir, split)
    if ramp_flows is None: ramp_flows = load_ramp_flows(panel_dir, split)

    state, missing = state_for_regime(panel, panel_dir, split, regime, state_panel)
    if state.empty:
        return pd.DataFrame(columns=sorted(PHYS_COLUMNS)), missing
    state = state.merge(params.reset_index(), on="link_id", how="left")
    state["speed_kmh"] = pd.to_numeric(state.speed_kmh, errors="coerce")
    state["flow_vph"] = pd.to_numeric(state.flow_vph, errors="coerce")
    state = state.dropna(subset=["speed_kmh","flow_vph","length_km","capacity_vph","critical_density","k_jam"])
    if state.empty:
        return pd.DataFrame(columns=sorted(PHYS_COLUMNS)), missing
    # Density and accumulation are identities, not estimates: k = q/v, N = k*L.
    state["density_vpkm"] = state.flow_vph / state.speed_kmh.clip(lower=1.0)
    state["accumulation_N"] = state.density_vpkm * state.length_km

    rank = {link: i for i, link in enumerate(order)}
    state["_rank"] = state.link_id.map(rank).fillna(len(rank)).astype(int)
    state = state.sort_values(["timestamp", "_rank", "link_id"])
    if not ramp_flows.empty:
        state = state.merge(ramp_flows, on=["timestamp", "link_id"], how="left")
    for c in ("on_ramp_flow_vph", "off_ramp_flow_vph"):
        if c not in state: state[c] = 0.0
        state[c] = pd.to_numeric(state[c], errors="coerce").fillna(0.0)
    for c in ("on_ramp_valid", "off_ramp_valid"):
        if c not in state: state[c] = False
        state[c] = pd.to_numeric(state[c], errors="coerce").fillna(0).astype(bool)
    # Zero is a valid structural value for a link with no ramp of that type;
    # an attached ramp is valid only when the released cell is >=75% observed.
    topo_path = panel_dir / "network" / "lwr_mainline_topology.csv"
    if topo_path.exists():
        topo = pd.read_csv(topo_path, dtype=str); topo["link_id"] = topo.link_id.astype(str)
        on_attached = set(topo.loc[topo.on_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"])
        off_attached = set(topo.loc[topo.off_ramp_link_ids.fillna("").astype(str).str.len() > 0, "link_id"])
        state["on_ramp_valid"] = state.on_ramp_valid | ~state.link_id.isin(on_attached)
        state["off_ramp_valid"] = state.off_ramp_valid | ~state.link_id.isin(off_attached)

    # Boundary flows are organizer data, never the participant's. Where the
    # organizer publishes none, fall back to the
    # topology applied to the submitted flows, which is what that release has
    # always used.
    if boundary_flux is not None and not boundary_flux.empty:
        boundaries = boundary_flux
    else:
        boundaries = topology_boundary_flows(state, panel_dir)
    state = state.drop(columns=["inflow_vph", "outflow_vph"], errors="ignore")
    state = state.merge(boundaries, on=["timestamp", "link_id"], how="left")
    state["inflow_vph"] = state.inflow_vph.fillna(state.flow_vph)
    state["outflow_vph"] = state.outflow_vph.fillna(state.flow_vph)

    out = pd.DataFrame({
        "panel": panel, "timestamp": state.timestamp, "link_id": state.link_id.astype(str),
        "mask_regime": regime, "speed_kmh": state.speed_kmh, "flow_vph": state.flow_vph,
        "density_vpkm": state.density_vpkm, "inflow_vph": state.inflow_vph,
        "outflow_vph": state.outflow_vph, "on_ramp_flow_vph": state.on_ramp_flow_vph,
        "off_ramp_flow_vph": state.off_ramp_flow_vph,
        "on_ramp_valid": state.on_ramp_valid.astype(int),
        "off_ramp_valid": state.off_ramp_valid.astype(int),
        "accumulation_N": state.accumulation_N,
        # Which cells the participant supplied, so the empty-road guard below
        # looks only at submitted values and never at released observations.
        "is_target": state.is_target if "is_target" in state else 0.0,
    })
    return out, missing

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
    # flow/vehicle units. The released flow and density fields are total
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
    submitted = pd.to_numeric(x.is_target, errors="coerce").fillna(0.0).to_numpy() > 0.5 if "is_target" in x else np.zeros(len(x), bool)
    if submitted.any() and float((x.flow_vph.to_numpy()[submitted] < EMPTY_FLOOR_VPH).mean()) > EMPTY_SHARE:
        s_fd = 0.0
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
    ap=argparse.ArgumentParser()
    ap.add_argument("--state-submission",type=Path,
                    help="the participant's Task 1 submission; Task 3 is scored on these speeds and flows")
    ap.add_argument("--physics-submission",type=Path,
                    help="legacy pre-anchoring path: a self-contained Task 3 physics CSV. "
                         "Kept for internal pipelines only; not a participant submission route")
    ap.add_argument("--split",choices=["validation","train","private"],default="validation")
    ap.add_argument("--boundary-flux",type=Path,
                    help="organizer-held boundary flows (organizer_truth/task3/physics_truth.parquet). "
                         "Never published; without it the topology fallback is used")
    ap.add_argument("--release-root",type=Path,default=DEFAULT_RELEASE); ap.add_argument("--output",type=Path,default=HERE/"reports"/"task3_eval_validation.csv"); ap.add_argument("--panel",action="append"); ap.add_argument("--modes-config",type=Path,help="coverage-mode table to score against; defaults to config/task3_lwr_modes.json")
    a=ap.parse_args()
    if bool(a.state_submission) == bool(a.physics_submission):
        ap.error("pass exactly one of --state-submission (anchored, the participant route) "
                 "or --physics-submission (legacy)")
    # The mode table is organizer-fixed and identical for every participant. It
    # must be the table derived from the release actually being scored, so a
    # synthetic staging root can override the repository default.
    modes_path = a.modes_config.resolve() if a.modes_config else HERE/"config"/"task3_lwr_modes.json"
    cfg=json.loads(modes_path.read_text(encoding="utf-8")); manifest=json.loads((HERE/"config"/"corridors.json").read_text(encoding="utf-8")); panels=[p["corridor_id"] for p in manifest["panels"]]
    if a.panel: panels=[p for p in panels if p in set(a.panel)]
    release=a.release_root.resolve()
    state=None
    if a.state_submission:
        state=read_csv_checked(a.state_submission.resolve(),
                               {"panel","timestamp","station_id","link_id","mask_regime","speed_kmh","flow_vph"},
                               "Task 1 state submission")
    else:
        d=read_csv_checked(a.physics_submission.resolve(),PHYS_COLUMNS,"Task 3 physics submission",
                           ["panel","timestamp","link_id","mask_regime"])
    rows=[]; total_missing=0
    for panel in panels:
        print(f"[Task3 LWR/FD evaluator] {panel}",flush=True)
        if state is not None:
            panel_dir=release/"corridors"/panel
            params=network_parameters(panel_dir).set_index("link_id")
            order=link_order(panel_dir,a.split); ramps=load_ramp_flows(panel_dir,a.split)
            flux=load_boundary_flux(a.boundary_flux.resolve() if a.boundary_flux else None, panel)
            sp=state[state.panel==panel]
            frames=[]
            for r in REGIMES:
                f,missing=derive_physics(panel,release,a.split,sp,r,order,params,ramps,flux)
                total_missing+=missing; frames.append(f)
                if missing: print(f"  {r}: Task 1 submission is missing {missing:,} target values",flush=True)
            d=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=sorted(PHYS_COLUMNS))
        rows += [score_panel(panel,d,release,cfg,r) for r in REGIMES]
    if total_missing: print(f"WARNING: {total_missing:,} Task 1 target values were missing and could not be scored",flush=True)
    detail=pd.DataFrame(rows); panel_mean=detail.groupby("panel",as_index=False).agg(S_physics=("S_physics","mean"),n_rows=("n_rows","sum")); overall=float(panel_mean.S_physics.mean()) if len(panel_mean) else 0.0
    out=pd.concat([detail,pd.DataFrame([{"level":"overall","panel":"ALL","regime":"macro_mean","S_physics":overall,"n_rows":int(detail.n_rows.sum())}])],ignore_index=True); a.output.parent.mkdir(parents=True,exist_ok=True); out.to_csv(a.output,index=False); print(f"Wrote {a.output}"); print(f"Overall S_physics = {overall:.6f}")
if __name__ == "__main__": main()
