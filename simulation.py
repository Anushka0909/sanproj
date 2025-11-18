"""
Simulation engine (Section 6)
Runs mission time 0..2500 hours, increases Sw2 load, checks threshold, triggers redistribution per scheme.
"""
from copy import deepcopy
from san_topology import SANTopology
import aftm_model as aftm
from load_redistribution import proportional_redistribute_sources_full, proportional_redistribute_sources_per_paper
from mitigation_schemes import MitigationScheme
from reliability_bdd import system_reliability
import math
import csv
import os


class Simulation:
    def __init__(self, topo=None, alpha=1.0, beta=1.0, mission_time=2500):
        self.topo = topo or SANTopology()
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.mission_time = int(mission_time)

    def _compute_all_reliabilities(self, t, loads):
        """Return dict of reliabilities for Sw1..Sw5, Sr1,Sr2, Sa1,Sa2 at time t"""
        reli = {}
        # switches via AFTM
        for sw in self.topo.switches:
            L = loads.get(sw, 0.0)
            base_lam = self.topo.base_lambda.get(sw, 0.0)
            reli[sw] = aftm.reliability_R(t, L, base_lam, alpha=self.alpha)

        # servers and arrays exponential with constant lambda
        lam_sa = self.topo.server_array_lambda
        reli["Sr1"] = math.exp(-lam_sa * t)
        reli["Sr2"] = math.exp(-lam_sa * t)
        reli["Sa1"] = math.exp(-lam_sa * t)
        reli["Sa2"] = math.exp(-lam_sa * t)

        return reli

    def run_scheme_and_print(self, scheme_id, s_dynamic=5.0):
        """
        Run a single scheme and print the required tables/values exactly as requested.

        For static schemes (1,2) we perform three sequential redistributions at the first trigger time (t=1000).
        For dynamic schemes (3,4) we use s_dynamic decrement (default 5) to obtain three triggers.
        """
        scheme = MitigationScheme(scheme_id, initial_threshold=50.0, s=s_dynamic, top_k=3)
        topo = self.topo.copy()
        topo.reset_loads()

        # track number of redistributions performed
        redis_count = 0

        # storage for IRs
        IR_list = []

        # we'll iterate time until we have 3 redistributions or reach mission_time
        t = 0
        # ensure loads start as L0 except Sw2 which is absolute L_sw2(t)=0.05*t
        loads = deepcopy(topo.L0)

        # Records for formatted output
        records = []

        # Function to perform one redistribution at current time t
        def perform_redistribution(current_t, threshold, loads_dict):
            nonlocal redis_count
            # compute reliabilities before
            reli_before = self._compute_all_reliabilities(current_t, loads_dict)
            # SAN reliability before
            R_before = system_reliability(reli_before)

            # select sources (Φ) whose full loads will be redistributed
            # pass the upcoming redistribution index so selection can be deterministic per redistribution
            upcoming_index = redis_count + 1
            sources = scheme.select_sources(loads_dict, {k: reli_before[k] for k in topo.switches}, "Sw2", topo.switches, redis_index=upcoming_index)
            # perform redistribution per-paper: per-source Nk (switch neighbors only)
            # neighbors as specified in Figure 1 mesh (switch-to-switch neighbors only):
            neighbors_map = {
                "Sw1": ["Sw4"],
                "Sw2": ["Sw4", "Sw5"],
                "Sw3": ["Sw5"],
                "Sw4": ["Sw1", "Sw2"],
                "Sw5": ["Sw2", "Sw3"],
            }
            # Sw2 must be redistributed excess-only: pass current threshold
            new_loads = proportional_redistribute_sources_per_paper(loads_dict, topo.degrees, sources, neighbors_map, beta=self.beta, sw2_threshold=current_threshold)

            # compute reliabilities after (same t)
            reli_after = self._compute_all_reliabilities(current_t, new_loads)
            R_after = system_reliability(reli_after)

            # compute IR
            BR = R_before
            AR = R_after
            IR = (AR - BR) / BR if BR != 0 else float('inf')

            redis_count += 1

            # store record
            rec = {
                "t": current_t,
                "threshold": threshold,
                "loads_before": {sw: loads_dict.get(sw, 0.0) for sw in [f"Sw{i}" for i in range(1, 6)]},
                "loads_after": {sw: new_loads.get(sw, 0.0) for sw in [f"Sw{i}" for i in range(1, 6)]},
                "reli_before": reli_before,
                "reli_after": reli_after,
                "R_before": R_before,
                "R_after": R_after,
                "IR": IR,
            }
            records.append(rec)
            IR_list.append(IR)
            return new_loads

        # Main loop: 1-hour steps, incremental Sw2 load ΔL_sw2 = 0.05 * (t - t_prev)
        t_prev = 0
        while t <= self.mission_time and redis_count < 3:
            # increase time by 1 hour
            # incremental load added to Sw2 per Eq.(10)
            delta = 0.05 * (t - t_prev)
            loads["Sw2"] = loads.get("Sw2", 0.0) + delta
            t_prev = t

            current_threshold = scheme.threshold()

            if loads["Sw2"] >= current_threshold:
                if scheme_id in (1, 2):
                    # static schemes: perform three sequential redistributions at this t
                    while redis_count < 3:
                        loads = perform_redistribution(t, current_threshold, loads)
                    break
                else:
                    loads = perform_redistribution(t, current_threshold, loads)
                    scheme.apply_after_trigger()
            t += 1

        # After finishing redistributions, pretty-print one mini-table per redistribution
        n = len(records)
        print(f"Scheme {scheme_id} - Results (mini-tables per redistribution)")

        if n == 0:
            print("No redistributions were performed for this scheme.")
            print("===============================\n")
            return {"IRs": IR_list, "IR_avg": 0.0, "redistributions": redis_count}

        comps = ["Sr1", "Sr2", "Sa1", "Sa2"] + [f"Sw{i}" for i in range(1, 6)]

        for idx, rec in enumerate(records, start=1):
            print(f"\n----- Redistribution {idx} at t={rec['t']} (threshold={rec['threshold']}) -----")

            # Loads mini-table with headers
            print("Loads:")
            print(f"{'Switch':<6} | {'Before':>12} | {'After':>12}")
            print('-' * 36)
            for sw in [f"Sw{i}" for i in range(1, 6)]:
                b = rec['loads_before'][sw]
                a = rec['loads_after'][sw]
                print(f"{sw:<6} | {b:12.6f} | {a:12.6f}")

            # Component reliabilities mini-table with headers
            print("\nComponent reliabilities:")
            print(f"{'Component':<8} | {'Before':>12} | {'After':>12}")
            print('-' * 38)
            for comp in comps:
                rb = rec['reli_before'][comp]
                ra = rec['reli_after'][comp]
                # choose formatting: fixed 6 decimals for typical values, scientific for very small
                def fmt(x):
                    if abs(x) < 1e-6:
                        return f"{x:.6e}"
                    else:
                        return f"{x:.6f}"

                print(f"{comp:<8} | {fmt(rb):>12} | {fmt(ra):>12}")

            # SAN reliability and IR with headers
            print("\nSAN reliability:")
            def fmtR(x):
                if x < 1e-6:
                    return f"{x:.6e}"
                else:
                    return f"{x:.6f}"

            print(f"{'R_before':<10}: {fmtR(rec['R_before'])}")
            print(f"{'R_after':<10}: {fmtR(rec['R_after'])}")
            print(f"IR_{idx:<7}: {rec['IR']:.6e}")
            print('-' * 40)

        IR_avg = sum(IR_list) / len(IR_list) if len(IR_list) > 0 else 0.0
        print(f"\nScheme {scheme_id} - IRs = {[f'{x:.12e}' for x in IR_list]}")
        print(f"Scheme {scheme_id} - IR_average = {IR_avg:.12e}")
        print("===============================\n")

        # Export records to CSV for this scheme
        try:
            export_results_to_csv(records, scheme_id)
        except Exception as e:
            print(f"Warning: failed to export CSV for scheme {scheme_id}: {e}")

        return {"IRs": IR_list, "IR_avg": IR_avg, "redistributions": redis_count}


def export_results_to_csv(results, scheme_id):
    """
    Write CSV file `results_scheme<scheme_id>.csv` with one row per redistribution.

    Columns:
    - Redistribution_Index, t_trigger, Threshold,
    - Sw1_before..Sw5_before, Sw1_after..Sw5_after, R_before, R_after, IR
    """
    if not isinstance(results, list):
        raise ValueError("results must be a list of redistribution records")

    filename = f"results_scheme{int(scheme_id)}.csv"
    fieldnames = [
        "Redistribution_Index",
        "t_trigger",
        "Threshold",
        "Sw1_before",
        "Sw2_before",
        "Sw3_before",
        "Sw4_before",
        "Sw5_before",
        "Sw1_after",
        "Sw2_after",
        "Sw3_after",
        "Sw4_after",
        "Sw5_after",
        "R_before",
        "R_after",
        "IR",
    ]

    # Ensure output directory exists (use current working dir)
    out_path = os.path.join(os.getcwd(), filename)
    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, rec in enumerate(results, start=1):
            row = {
                "Redistribution_Index": i,
                "t_trigger": rec.get("t", ""),
                "Threshold": rec.get("threshold", ""),
                "Sw1_before": rec.get("loads_before", {}).get("Sw1", ""),
                "Sw2_before": rec.get("loads_before", {}).get("Sw2", ""),
                "Sw3_before": rec.get("loads_before", {}).get("Sw3", ""),
                "Sw4_before": rec.get("loads_before", {}).get("Sw4", ""),
                "Sw5_before": rec.get("loads_before", {}).get("Sw5", ""),
                "Sw1_after": rec.get("loads_after", {}).get("Sw1", ""),
                "Sw2_after": rec.get("loads_after", {}).get("Sw2", ""),
                "Sw3_after": rec.get("loads_after", {}).get("Sw3", ""),
                "Sw4_after": rec.get("loads_after", {}).get("Sw4", ""),
                "Sw5_after": rec.get("loads_after", {}).get("Sw5", ""),
                "R_before": rec.get("R_before", ""),
                "R_after": rec.get("R_after", ""),
                "IR": rec.get("IR", ""),
            }
            writer.writerow(row)

    print(f"Wrote CSV: {out_path}")


if __name__ == "__main__":
    sim = Simulation()
    # Run all schemes 1..4 using s=5 for dynamic schemes
    for sid in (1, 2, 3, 4):
        sim.run_scheme_and_print(sid, s_dynamic=5.0)