"""
Load redistribution helpers implementing proportional rule (Equations 4-9)
Π_j = (degree_j^β) / Σ_{m∈N_k} degree_m^β
ΔL_jk = L_k * Π_j

We provide a simultaneous redistribution function `proportional_redistribute_sources_full`
which takes a set of sources Φ and redistributes each source's full load L_k across its
neighborhood N_k (including k). This follows the paper exactly: for each source k,
all j ∈ N_k receive ΔL_jk = L_k * Π_j and the source's original L_k is removed before
adding the Δ's (so the source keeps ΔL_kk but not its original L_k separately).
"""

def proportional_redistribute_sources_full(loads, degrees, sources, neighbors_map, beta=1.0):
    """
    Simultaneously redistribute the full load of each source in `sources`.

    - `loads`: dict of current loads (pre-redistribution), used as the snapshot L_k values.
    - `degrees`: dict mapping node -> degree used to compute Π (degree^beta).
    - `sources`: iterable of source node names (Φ).
    - `neighbors_map`: dict mapping node -> list of neighbor node names (not including self).
    - `beta`: exponent for degree weighting (default 1.0).

    Returns a new loads dict after redistribution.
    """
    # snapshot of pre-redistribution loads
    L_before = {k: float(v) for k, v in loads.items()}

    # prepare delta accumulator
    delta_total = {n: 0.0 for n in loads.keys()}

    # compute per-source deltas using L_before (simultaneous application)
    for k in sources:
        if k not in L_before:
            continue
        Lk = float(L_before.get(k, 0.0))
        if Lk <= 0.0:
            continue

        # Nk includes k itself plus its neighbors (ensure unique order)
        neigh = list(neighbors_map.get(k, [])) if neighbors_map is not None else []
        Nk = list(dict.fromkeys([k] + neigh))

        # compute denominator over Nk
        denom = 0.0
        for m in Nk:
            denom += float(degrees.get(m, 0) ** beta)

        if denom <= 0.0:
            # evenly split among Nk
            for j in Nk:
                delta_total[j] = delta_total.get(j, 0.0) + Lk / len(Nk)
        else:
            for j in Nk:
                w = float(degrees.get(j, 0) ** beta) / denom
                delta_total[j] = delta_total.get(j, 0.0) + Lk * w

    # apply deltas: remove each source's original full load, then add accumulated deltas
    new_loads = {n: float(v) for n, v in L_before.items()}
    for k in sources:
        if k in new_loads:
            new_loads[k] = new_loads.get(k, 0.0) - float(L_before.get(k, 0.0))

    for j, d in delta_total.items():
        new_loads[j] = new_loads.get(j, 0.0) + float(d)

    return new_loads


def proportional_redistribute_sources_per_paper(loads, degrees, sources, neighbors_map, beta=1.0, sw2_threshold=None):
    """
    Redistribution following the paper rules with per-source Nk and Sw2 excess-only.

    - For each source k in `sources`:
      - Nk = {k} ∪ neighbors_map[k] (neighbors_map lists neighbor switches only)
      - Π_j computed with degrees over Nk
      - If k == 'Sw2' and sw2_threshold is not None: amount_k = max(0, Lk - sw2_threshold)
        and Sw2 will be reduced by amount_k (so Sw2_after = threshold).
      - Otherwise amount_k = Lk (full-load redistributed for other sources).
      - ΔL_jk = amount_k * Π_j for all j in Nk

    Redistribution is simultaneous: use L_before snapshot for all Lk and apply all deltas
    together. Returns new loads dict.
    """
    L_before = {k: float(v) for k, v in loads.items()}
    delta_total = {n: 0.0 for n in loads.keys()}

    for k in sources:
        if k not in L_before:
            continue
        Lk = float(L_before.get(k, 0.0))
        if Lk <= 0.0:
            continue

        # Nk = k plus its neighbor switches (neighbors_map expected to contain only switch neighbors)
        neigh = list(neighbors_map.get(k, [])) if neighbors_map is not None else []
        Nk = list(dict.fromkeys([k] + neigh))

        # compute denominator over Nk
        denom = 0.0
        for m in Nk:
            denom += float(degrees.get(m, 0) ** beta)

        # determine amount to redistribute for this source
        if k == "Sw2" and sw2_threshold is not None:
            amount_k = max(0.0, Lk - float(sw2_threshold))
        else:
            amount_k = Lk

        if amount_k <= 0.0:
            continue

        if denom <= 0.0:
            for j in Nk:
                delta_total[j] = delta_total.get(j, 0.0) + amount_k / len(Nk)
        else:
            for j in Nk:
                w = float(degrees.get(j, 0) ** beta) / denom
                delta_total[j] = delta_total.get(j, 0.0) + amount_k * w

    # apply deltas: subtract amount_k from each source (only the redistributed amount)
    new_loads = {n: float(v) for n, v in L_before.items()}
    for k in sources:
        if k not in L_before:
            continue
        Lk = float(L_before.get(k, 0.0))
        if k == "Sw2" and sw2_threshold is not None:
            amount_k = max(0.0, Lk - float(sw2_threshold))
        else:
            amount_k = Lk
        new_loads[k] = new_loads.get(k, 0.0) - float(amount_k)

    for j, d in delta_total.items():
        new_loads[j] = new_loads.get(j, 0.0) + float(d)

    return new_loads


if __name__ == "__main__":
    loads = {"Sw1": 10, "Sw2": 60, "Sw3": 5}
    degrees = {"Sw1": 3, "Sw2": 4, "Sw3": 3}
    neighbors = {"Sw1": ["Sw2"], "Sw2": ["Sw1", "Sw3"], "Sw3": ["Sw2"]}
    print(proportional_redistribute_sources_full(loads, degrees, ["Sw2"], neighbors, beta=1))