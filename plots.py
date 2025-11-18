"""
Plot helpers for simulation outputs
Generates line plots for R_sys vs time and Sw2 load vs time across schemes.
"""
import matplotlib.pyplot as plt
import os


def plot_Rsys_all(results_dict, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    plt.figure(figsize=(10, 6))
    for scheme_id, res in results_dict.items():
        t = res["times"]
        R = res["R_sys"]
        plt.plot(t, R, label=f"Scheme {scheme_id}")
    plt.xlabel("Time (hours)")
    plt.ylabel("System Reliability R_sys")
    plt.legend()
    plt.grid(True)
    p = os.path.join(outdir, "Rsys_all_schemes.png")
    plt.savefig(p)
    plt.close()
    return p


def plot_Sw2_load_all(results_dict, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    plt.figure(figsize=(10, 6))
    for scheme_id, res in results_dict.items():
        t = res["times"]
        L = res["loads"]["Sw2"]
        plt.plot(t, L, label=f"Scheme {scheme_id}")
    plt.xlabel("Time (hours)")
    plt.ylabel("Load of Sw2")
    plt.legend()
    plt.grid(True)
    p = os.path.join(outdir, "Sw2_load_all_schemes.png")
    plt.savefig(p)
    plt.close()
    return p


def save_scheme_csv(res, scheme_id, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    import csv

    times = res["times"]
    header = ["time"] + [f"load_{sw}" for sw in sorted(res["loads"].keys())] + ["R_sys"]
    path = os.path.join(outdir, f"scheme_{scheme_id}_timeseries.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, t in enumerate(times):
            row = [int(t)]
            for sw in sorted(res["loads"].keys()):
                row.append(f"{res["loads"][sw][i]:.6f}")
            row.append(f"{res["R_sys"][i]:.9f}")
            writer.writerow(row)
    return path


if __name__ == "__main__":
    print("Plot module")