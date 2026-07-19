"""
Network Layer — longest-prefix-match routing, by hand and cross-checked.

A router picks the next hop by finding the most *specific* route that contains
the destination: the matching entry with the longest prefix wins, and the
default route 0.0.0.0/0 (prefix 0) is the fallback that matches everything. We
implement the match with raw bit-math and confirm it against `ipaddress`.

Docs: phases/01-networking-and-protocols/04-network-layer-ip-subnets-routing/docs/en.md
Spec: RFC 791 (IPv4), RFC 1812 §5.2.4 (forwarding: longest-match), RFC 4632 (CIDR)

Run:
    python routing_table.py
Routes several destinations against a sample table and exits 0.
"""

import ipaddress

ALL_ONES = 0xFFFFFFFF

# A sample forwarding table: (CIDR prefix, next hop). Order does NOT matter —
# longest-prefix match decides the winner, not table position.
ROUTING_TABLE = [
    ("0.0.0.0/0", "203.0.113.1  (default gateway — the internet)"),
    ("10.0.0.0/8", "10.0.0.1     (corporate backbone)"),
    ("10.1.0.0/16", "10.1.0.1     (branch office)"),
    ("10.1.2.0/24", "10.1.2.1     (engineering VLAN)"),
    ("192.168.1.0/24", "192.168.1.1  (home LAN)"),
]


def ip_to_int(dotted: str) -> int:
    a, b, c, d = (int(part) for part in dotted.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def parse_cidr(cidr: str):
    """Return (network_int, prefix, mask_int) for a 'network/prefix' string."""
    network, prefix_str = cidr.split("/")
    prefix = int(prefix_str)
    mask = (ALL_ONES << (32 - prefix)) & ALL_ONES if prefix else 0
    return ip_to_int(network) & mask, prefix, mask


def longest_prefix_match(dest: str, table):
    """Select the most-specific route whose network contains `dest`, or None."""
    dest_int = ip_to_int(dest)
    best = None
    best_prefix = -1
    for cidr, next_hop in table:
        network_int, prefix, mask = parse_cidr(cidr)
        # A route matches when the destination's network bits equal the route's.
        if (dest_int & mask) == network_int and prefix > best_prefix:
            best, best_prefix = (cidr, next_hop), prefix
    return best


def match_by_stdlib(dest: str, table):
    """Independent cross-check: pick the containing network with the longest prefix."""
    addr = ipaddress.ip_address(dest)
    winner = None
    for cidr, next_hop in table:
        net = ipaddress.ip_network(cidr)
        if addr in net and (winner is None or net.prefixlen > winner[0]):
            winner = (net.prefixlen, cidr, next_hop)
    return None if winner is None else (winner[1], winner[2])


def main() -> None:
    destinations = ["10.1.2.55", "10.1.9.9", "10.9.9.9", "192.168.1.50", "8.8.8.8"]
    print("Routing table (longest-prefix match wins):")
    for cidr, next_hop in ROUTING_TABLE:
        print(f"  {cidr:<16} -> {next_hop}")
    print()

    for dest in destinations:
        chosen = longest_prefix_match(dest, ROUTING_TABLE)
        assert chosen == match_by_stdlib(dest, ROUTING_TABLE), "bit-math disagrees with ipaddress"
        cidr, next_hop = chosen
        print(f"{dest:<14} matches {cidr:<16} -> {next_hop}")


if __name__ == "__main__":
    main()
