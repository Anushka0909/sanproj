"""
BDD reliability model (Section 5)
Compute system reliability based on switch reliabilities and the fault expression:
Path failure = (Sw1 AND Sw2 AND Sw3) OR (Sw3 AND Sw4 AND Sw5)
System reliability R_sys = 1 - P(path failure)

Assumptions:
- Servers and Storage arrays are assumed to be highly reliable / available (no explicit failure rates provided in the request).
- Switch failures are independent.
"""

import math


def system_reliability(switch_reliabilities):
    """
    Compute system reliability based on full component reliabilities.

    Input: full_reliabilities: dict with keys: 'Sw1'..'Sw5','Sr1','Sr2','Sa1','Sa2'
    Each value is reliability R (probability component is UP at current time).

    The fault tree is implemented exactly as described in the paper:
    SAN_Failure = Server_Failure OR StorageArray_Failure OR Path_Failure

    Server_Failure:
      Sr1_down = Sr1_basic_down OR (Sw5_down AND Sw4_down)
      Sr2_down = Sr2_basic_down OR (Sw3_down AND Sw5_down)
      Server_Failure = Sr1_down AND Sr2_down

    StorageArray_Failure:
      Sa1_down = Sa1_basic_down OR (Sw5_down AND Sw2_down)
      Sa2_down = Sa2_basic_down OR (Sw3_down AND Sw2_down)
      StorageArray_Failure = Sa1_down AND Sa2_down

    Path_Failure:
      Path_Failure = (Sw1_down AND Sw2_down AND Sw3_down) AND (Sw3_down AND Sw4_down AND Sw5_down)

    To compute exact probability, enumerate all basic-state combinations (2^9) and sum probabilities
    where SAN_Failure is true.
    """
    # Expect keys
    keys = [f"Sw{i}" for i in range(1, 6)] + ["Sr1", "Sr2", "Sa1", "Sa2"]
    for k in keys:
        if k not in switch_reliabilities:
            raise KeyError(f"Missing reliability for {k}")

    # For each basic component, down probability = 1 - R
    p_down = {k: 1.0 - switch_reliabilities[k] for k in keys}
    p_up = {k: switch_reliabilities[k] for k in keys}

    # Enumerate all 2^9 combinations
    comp_list = keys
    n = len(comp_list)
    P_failure = 0.0
    # iterate integers 0..2^n-1 where bit=1 means component is DOWN
    for mask in range(0, 1 << n):
        prob = 1.0
        state_down = {}
        for i, comp in enumerate(comp_list):
            if (mask >> i) & 1:
                prob *= p_down[comp]
                state_down[comp] = True
            else:
                prob *= p_up[comp]
                state_down[comp] = False

        if prob == 0.0:
            continue

        # Evaluate fault tree boolean with this state
        Sw = {f: state_down[f] for f in [f"Sw{i}" for i in range(1, 6)]}
        Sr = {"Sr1": state_down["Sr1"], "Sr2": state_down["Sr2"]}
        Sa = {"Sa1": state_down["Sa1"], "Sa2": state_down["Sa2"]}

        # Derived events
        Sr1_down = Sr["Sr1"] or (Sw["Sw5"] and Sw["Sw4"])
        Sr2_down = Sr["Sr2"] or (Sw["Sw3"] and Sw["Sw5"])
        Server_Failure = Sr1_down and Sr2_down

        Sa1_down = Sa["Sa1"] or (Sw["Sw5"] and Sw["Sw2"])
        Sa2_down = Sa["Sa2"] or (Sw["Sw3"] and Sw["Sw2"])
        Storage_Failure = Sa1_down and Sa2_down

        Path_Failure = (Sw["Sw1"] and Sw["Sw2"] and Sw["Sw3"]) and (Sw["Sw3"] and Sw["Sw4"] and Sw["Sw5"]) 

        SAN_Failure = Server_Failure or Storage_Failure or Path_Failure

        if SAN_Failure:
            P_failure += prob

    # system reliability
    R_sys = max(0.0, min(1.0, 1.0 - P_failure))
    return R_sys


if __name__ == "__main__":
    # example: all switches reliability 0.999
    reliab = {f"Sw{i}": 0.999 for i in range(1, 6)}
    print("R_sys=", system_reliability(reliab))