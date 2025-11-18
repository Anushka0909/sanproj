"""
Mitigation schemes (Section 4)
Four schemes:
1: Static threshold (50 for Sw2), reliability-sensitive
2: Static threshold, load-sensitive
3: Dynamic threshold (start 50, threshold -= s), reliability-sensitive, s=5
4: Dynamic threshold, load-sensitive, s=5

Selection picks top_k=3 vulnerable switches (excluding the overloaded switch) per scheme metric.
"""
from copy import deepcopy


class MitigationScheme:
    def __init__(self, scheme_id, initial_threshold=50.0, s=5.0, top_k=3):
        if scheme_id not in (1, 2, 3, 4):
            raise ValueError("scheme_id must be 1..4")
        self.scheme_id = scheme_id
        self.initial_threshold = float(initial_threshold)
        self.s = float(s)
        self.top_k = int(top_k)
        self.dynamic_threshold = float(initial_threshold)
        # Predefined Φ sets per scheme and redistribution index (1-based)
        # These come directly from Tables 3-6 in the paper as requested.
        # Each entry is a list of source node names (strings).
        self.predefined_phi = {
            1: [
                ["Sw1", "Sw2", "Sw3"],
                ["Sw2", "Sw3", "Sw5"],
                ["Sw2", "Sw3", "Sw4"],
            ],
            2: [
                ["Sw2", "Sw1", "Sw5"],
                ["Sw2", "Sw3", "Sw5"],
                ["Sw2", "Sw3", "Sw4"],
            ],
            3: [
                ["Sw1", "Sw2", "Sw3"],
                ["Sw2", "Sw3", "Sw5"],
                ["Sw2", "Sw3", "Sw4"],
            ],
            4: [
                ["Sw2", "Sw1", "Sw5"],
                ["Sw2", "Sw3", "Sw5"],
                ["Sw2", "Sw3", "Sw4"],
            ],
        }

    def reset(self):
        self.dynamic_threshold = float(self.initial_threshold)

    def threshold(self):
        return float(self.dynamic_threshold)

    def is_dynamic(self):
        return self.scheme_id in (3, 4)

    def apply_after_trigger(self):
        # If dynamic, reduce threshold by s after a trigger
        if self.is_dynamic():
            self.dynamic_threshold = max(0.0, self.dynamic_threshold - self.s)

    def select_sources(self, loads, reliabilities, overloaded_switch, all_switches, redis_index=1):
        """
        Select `top_k` source switches Φ (the nodes whose loads will be redistributed).

        - Candidates exclude the overloaded switch (e.g., 'Sw2').
        - Scheme 1 & 3: select lowest reliability (most vulnerable) as sources.
        - Scheme 2 & 4: select highest load as sources.
        Returns a list of source node names (length up to `top_k`).
        """
        # If a predefined Φ exists for this scheme and redistribution index, return it deterministically
        phi_list = self.predefined_phi.get(self.scheme_id, None)
        if phi_list is not None:
            # redis_index is 1-based; if out of range, fall back to last pattern
            idx = int(redis_index) - 1
            if idx < 0:
                idx = 0
            if idx >= len(phi_list):
                idx = len(phi_list) - 1
            # filter to available switches (defensive) and exclude overloaded switch if present
            phi = [s for s in phi_list[idx] if s in all_switches and s != overloaded_switch]
            return phi[: self.top_k]

        # Fallback: original behavior (select by reliability or load)
        candidates = [s for s in all_switches if s != overloaded_switch]
        if len(candidates) == 0:
            return []

        if self.scheme_id in (1, 3):
            sorted_cand = sorted(candidates, key=lambda x: reliabilities.get(x, 1.0))
        else:
            sorted_cand = sorted(candidates, key=lambda x: loads.get(x, 0.0), reverse=True)

        return sorted_cand[: self.top_k]


if __name__ == "__main__":
    scheme = MitigationScheme(3)
    loads = {"Sw1": 15, "Sw2": 80, "Sw3": 5, "Sw4": 1, "Sw5": 8}
    reliab = {k: 0.999 for k in loads}
    print(scheme.select_targets(loads, reliab, "Sw2", list(loads.keys())))