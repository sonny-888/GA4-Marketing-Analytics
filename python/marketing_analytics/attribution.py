"""Data-driven multi-touch attribution with a first-order Markov chain (removal effect).

Each customer journey is a sequence of channels that ends in either a conversion or a null
(no conversion). We model the journeys as an absorbing Markov chain:

    start -> channel_1 -> ... -> channel_k -> {conversion | null}

A channel's *removal effect* is the relative drop in P(start ~> conversion) when every
transition into that channel is redirected to null. Removal effects are normalised to sum to 1
and used to split total conversions and revenue across channels.

Uncertainty comes from a bootstrap over journeys (multinomial resampling of path counts).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

START, CONVERSION, NULL = "(start)", "(conversion)", "(null)"


@dataclass
class MarkovResult:
    channels: list[str]
    conversion_probability: float
    removal_effects: dict[str, float]
    shares: dict[str, float]


def _states(paths) -> tuple[list[str], list[str]]:
    channels = sorted({c for p in paths for c in p})
    return channels, [START, *channels, CONVERSION, NULL]


def _transition_index(paths: list[tuple[str, ...]], converted: np.ndarray, states: list[str]):
    """Precompute every (path, from->to) transition once, as flat indices into an S x S matrix.

    Returns (path_idx, pair_idx) so weighted counts for any weights vector are a single bincount;
    this keeps the bootstrap fast.
    """
    idx = {s: i for i, s in enumerate(states)}
    S = len(states)
    path_idx, pair_idx = [], []
    for k, (path, conv) in enumerate(zip(paths, converted)):
        if len(path) == 0:
            continue
        seq = [START, *path, CONVERSION if conv else NULL]
        for a, b in zip(seq[:-1], seq[1:]):
            path_idx.append(k)
            pair_idx.append(idx[a] * S + idx[b])
    return np.asarray(path_idx), np.asarray(pair_idx)


def _counts(path_idx: np.ndarray, pair_idx: np.ndarray, weights: np.ndarray, n_states: int) -> np.ndarray:
    flat = np.bincount(pair_idx, weights=weights[path_idx], minlength=n_states * n_states)
    return flat.reshape(n_states, n_states)


def _conversion_probability(counts: np.ndarray, states: list[str], removed: str | None = None) -> float:
    """P(absorbing in conversion | start), optionally with one channel removed (redirected to null)."""
    counts = counts.copy()
    idx = {s: i for i, s in enumerate(states)}
    if removed is not None:
        r = idx[removed]
        counts[:, idx[NULL]] += counts[:, r]
        counts[:, r] = 0
        counts[r, :] = 0

    transient = [i for i, s in enumerate(states) if s not in (CONVERSION, NULL)]
    row_sums = counts[transient].sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        probs = np.where(row_sums > 0, counts[transient] / row_sums, 0.0)

    Q = probs[:, transient]                      # transient -> transient
    R = probs[:, [idx[CONVERSION]]]              # transient -> conversion
    # Absorption probabilities B = (I - Q)^-1 R ; unreachable/dead states have zero rows and stay 0.
    B = np.linalg.solve(np.eye(len(transient)) - Q, R)
    return float(B[transient.index(idx[START]), 0])


def _fit_from_counts(counts: np.ndarray, channels: list[str], states: list[str]) -> MarkovResult:
    base = _conversion_probability(counts, states)
    removal = {
        c: (base - _conversion_probability(counts, states, removed=c)) / base if base > 0 else 0.0
        for c in channels
    }
    total = sum(max(v, 0.0) for v in removal.values())
    shares = {c: (max(v, 0.0) / total if total > 0 else 0.0) for c, v in removal.items()}
    return MarkovResult(channels, base, removal, shares)


def markov_attribution(paths: list[tuple[str, ...]], converted, weights=None) -> MarkovResult:
    """Fit the Markov model on journeys and return removal effects and normalised channel shares.

    paths      : list of channel sequences, e.g. [("Organic Search", "Direct"), ...]
    converted  : bool per path
    weights    : number of journeys represented by each path (default 1)
    """
    converted = np.asarray(converted, dtype=bool)
    weights = np.ones(len(paths)) if weights is None else np.asarray(weights, dtype=float)
    channels, states = _states(paths)
    path_idx, pair_idx = _transition_index(paths, converted, states)
    return _fit_from_counts(_counts(path_idx, pair_idx, weights, len(states)), channels, states)


def bootstrap_markov(paths, converted, weights, n_boot: int = 200, seed: int = 42) -> pd.DataFrame:
    """Bootstrap channel shares by resampling journeys. Returns one row per (iteration, channel)."""
    rng = np.random.default_rng(seed)
    converted = np.asarray(converted, dtype=bool)
    weights = np.asarray(weights, dtype=float)
    channels, states = _states(paths)
    path_idx, pair_idx = _transition_index(paths, converted, states)
    n, p = int(weights.sum()), weights / weights.sum()
    rows = []
    for b in range(n_boot):
        w = rng.multinomial(n, p).astype(float)
        res = _fit_from_counts(_counts(path_idx, pair_idx, w, len(states)), channels, states)
        rows += [{"iteration": b, "channel": c, "share": s} for c, s in res.shares.items()]
    return pd.DataFrame(rows)


def attribute(paths_df: pd.DataFrame, n_boot: int = 200, seed: int = 42) -> pd.DataFrame:
    """End-to-end: aggregated journeys -> channel-level Markov attribution with 95% bootstrap CIs.

    paths_df columns: path (list/tuple of channels), converted (bool), journeys (int), revenue_usd (float)
    """
    # The bootstrap resamples by row position, so fix the row order: the warehouse doesn't guarantee one,
    # and without this the same data and seed could give slightly different intervals on each rebuild.
    paths_df = (paths_df.assign(_key=paths_df["path"].map(" > ".join))
                .sort_values(["_key", "converted"], kind="stable").drop(columns="_key").reset_index(drop=True))
    paths = [tuple(p) for p in paths_df["path"]]
    converted = paths_df["converted"].to_numpy(dtype=bool)
    weights = paths_df["journeys"].to_numpy(dtype=float)

    fit = markov_attribution(paths, converted, weights)
    boot = bootstrap_markov(paths, converted, weights, n_boot=n_boot, seed=seed)
    ci = boot.groupby("channel")["share"].quantile([0.025, 0.975]).unstack()

    total_conv = float(weights[converted].sum())
    total_rev = float(paths_df.loc[paths_df["converted"], "revenue_usd"].sum())
    out = pd.DataFrame({
        "channel": fit.channels,
        "removal_effect": [fit.removal_effects[c] for c in fit.channels],
        "share": [fit.shares[c] for c in fit.channels],
        "share_ci_low": [ci.loc[c, 0.025] if c in ci.index else np.nan for c in fit.channels],
        "share_ci_high": [ci.loc[c, 0.975] if c in ci.index else np.nan for c in fit.channels],
    })
    out["conversions"] = out["share"] * total_conv
    out["revenue_usd"] = out["share"] * total_rev
    out["baseline_conversion_probability"] = fit.conversion_probability
    return out.sort_values("share", ascending=False).reset_index(drop=True)
