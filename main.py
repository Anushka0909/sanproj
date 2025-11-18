"""
Main script: run all four schemes, save outputs, generate plots, print final tables
"""
import os

from simulation import Simulation
"""Main runner: run the four schemes and print the requested outputs."""

from simulation import Simulation


def main():
    sim = Simulation()
    for scheme_id in (1, 2, 3, 4):
        print(f"Running Scheme {scheme_id}...")
        sim.run_scheme_and_print(scheme_id, s_dynamic=5.0)


if __name__ == "__main__":
    main()