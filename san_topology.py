"""
SAN Topology module
Defines nodes, adjacency, switch degrees, initial loads L0 and base failure rates lambda
Topology is constructed to satisfy switch degrees from the paper and include 2 servers and 2 storage arrays.
"""
from copy import deepcopy

class SANTopology:
    def __init__(self):
        # Nodes
        self.servers = ["Sr1", "Sr2"]
        self.storages = ["Sa1", "Sa2"]
        self.switches = [f"Sw{i}" for i in range(1, 6)]

        # Adjacency list (undirected)
        # Server-to-switch
        # Sr1: [Sw1, Sw2]
        # Sr2: [Sw4, Sw5]
        # Storage arrays
        # Sa1: [Sw1, Sw2, Sw4]
        # Sa2: [Sw3, Sw5]
        # Switch-to-switch mesh (undirected)
        # Sw1: [Sw2, Sw4, Sw5]
        # Sw2: [Sw1, Sw4, Sw5, Sw3]
        # Sw3: [Sw2, Sw5, Sw4]
        # Sw4: [Sw1, Sw2, Sw5, Sw3]
        # Sw5: [Sw1, Sw2, Sw3, Sw4]
        self.adj = {
            "Sr1": ["Sw4", "Sw5"],
            "Sr2": ["Sw3", "Sw5"],
            "Sa1": ["Sw1", "Sw2"],
            "Sa2": ["Sw2", "Sw3"],
            "Sw1": ["Sa1", "Sw2", "Sw4", "Sw5"],
            "Sw2": ["Sa1", "Sa2", "Sw1", "Sw3", "Sw4", "Sw5"],
            "Sw3": ["Sr2", "Sa2", "Sw2", "Sw4", "Sw5"],
            "Sw4": ["Sr1", "Sw1", "Sw2", "Sw3", "Sw5"],
            "Sw5": ["Sr2", "Sw1", "Sw2", "Sw3", "Sw4"],
        }

        # Validate degrees: only count switch-to-switch
        self.degrees = {
            "Sw1": 3,
            "Sw2": 4,
            "Sw3": 3,
            "Sw4": 4,
            "Sw5": 4,
        }

        # Initial loads L0 and base failure rates lambda (from Table 2)
        # Sw1: λ=3.0e-6,  L0=15
        # Sw2: λ=5.0e-6,  L0=50
        # Sw3: λ=3.0e-5,  L0=5
        # Sw4: λ=3.0e-6,  L0=1
        # Sw5: λ=3.5e-6,  L0=8
        self.L0 = {
            "Sw1": 15.0,
            "Sw2": 50.0,
            "Sw3": 5.0,
            "Sw4": 1.0,
            "Sw5": 8.0,
        }

        self.base_lambda = {
            "Sw1": 3.0e-6,
            "Sw2": 5.0e-6,
            "Sw3": 3.0e-5,
            "Sw4": 3.0e-6,
            "Sw5": 3.5e-6,
        }

        # Server and storage arrays have specified constant failure rate (Section 5)
        self.server_array_lambda = 4.756469781e-11

        # Current loads initialized to L0
        self.loads = deepcopy(self.L0)

    def reset_loads(self):
        from copy import deepcopy
        self.loads = deepcopy(self.L0)

    def get_switches(self):
        return list(self.switches)

    def degree(self, switch):
        return self.degrees.get(switch, 0)

    def neighbors(self, node):
        return list(self.adj.get(node, []))

    def copy(self):
        return deepcopy(self)


if __name__ == "__main__":
    topo = SANTopology()
    print("Switch degrees:", topo.degrees)
    print("Adjacency sample:", topo.adj["Sw1"])