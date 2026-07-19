"""
Data Link Layer — a learning Ethernet switch, simulated.

A switch turns a shared wire into private point-to-point links by learning which
MAC address lives behind which port. For every frame it (1) learns the source MAC
-> in-port, then (2) FORWARDS to the single port that owns the destination MAC, or
FLOODS to all other ports when the destination is unknown or is the broadcast
address. This is IEEE 802.1D transparent bridging, in a few lines of Python.

Docs: phases/01-networking-and-protocols/03-data-link-mac-frames-switching/docs/en.md
Spec: IEEE 802.3 (Ethernet); IEEE 802.1D (MAC learning / transparent bridging)

Run:
    python3 learning_switch.py
Feeds a scripted traffic trace through the switch, prints each decision, exits 0.
"""

BROADCAST = "ff:ff:ff:ff:ff:ff"

# Three hosts, each on its own switch port. Same OUI (00:1a:2b), different tails.
HOST_A = "00:1a:2b:00:00:0a"
HOST_B = "00:1a:2b:00:00:0b"
HOST_C = "00:1a:2b:00:00:0c"


class LearningSwitch:
    """A switch with a fixed set of ports and a MAC table it fills as it learns."""

    def __init__(self, ports):
        self.ports = list(ports)     # every port on the switch
        self.mac_table = {}          # MAC address -> port (the CAM table)

    def process(self, src_mac: str, dst_mac: str, in_port: int) -> None:
        # 1. LEARN: the source is reachable via the port this frame arrived on.
        newly_learned = self.mac_table.get(src_mac) != in_port
        self.mac_table[src_mac] = in_port

        # 2. DECIDE where the frame goes.
        if dst_mac == BROADCAST:
            action, where = "FLOOD", "broadcast address"
        elif dst_mac not in self.mac_table:
            action, where = "FLOOD", "destination not yet learned"
        else:
            action, where = "FORWARD", f"to port {self.mac_table[dst_mac]}"

        if action == "FLOOD":
            targets = [p for p in self.ports if p != in_port]
            where = f"{where} -> ports {targets}"

        learned = f"   [learned {src_mac} on port {in_port}]" if newly_learned else ""
        print(f"port {in_port}  {src_mac} -> {dst_mac}  {action:8} {where}{learned}")


def main() -> None:
    switch = LearningSwitch(ports=[1, 2, 3])

    # A scripted trace: (source MAC, destination MAC, the port it arrived on).
    trace = [
        (HOST_A, HOST_B, 1),        # B unknown -> FLOOD, and learn A is on port 1
        (HOST_B, HOST_A, 2),        # A already known -> FORWARD, and learn B on 2
        (HOST_A, HOST_B, 1),        # B now known -> FORWARD (no more flooding)
        (HOST_C, BROADCAST, 3),     # a broadcast (e.g. ARP) -> always FLOOD; learn C
        (HOST_A, HOST_C, 1),        # C known from its broadcast -> FORWARD
    ]

    print("Legend: FORWARD = sent out one port; FLOOD = copied to all other ports\n")
    for src_mac, dst_mac, in_port in trace:
        switch.process(src_mac, dst_mac, in_port)

    print("\nfinal MAC table (address -> port):")
    for mac, port in sorted(switch.mac_table.items()):
        print(f"  {mac} -> port {port}")

    # By the end the switch has learned all three hosts.
    assert switch.mac_table == {HOST_A: 1, HOST_B: 2, HOST_C: 3}


if __name__ == "__main__":
    main()
