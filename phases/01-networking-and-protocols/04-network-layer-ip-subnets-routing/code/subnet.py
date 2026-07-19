"""
Network Layer — subnet math, by hand and cross-checked with the stdlib.

Given an IPv4 address and a CIDR prefix, compute the network address, broadcast
address, first/last usable host, host count, and netmask. Each value is derived
twice: once with raw integer bit-math (AND with the mask) and once with the
standard-library `ipaddress` module, then the two are asserted equal.

Docs: phases/01-networking-and-protocols/04-network-layer-ip-subnets-routing/docs/en.md
Spec: RFC 791 (IPv4), RFC 4291 (IPv6 addressing), RFC 1918 (private ranges)

Run:
    python subnet.py
Prints each field for a few example subnets and exits 0.
"""

import ipaddress

ALL_ONES = 0xFFFFFFFF  # 32 bits set — the widest an IPv4 address can be


def ip_to_int(dotted: str) -> int:
    """Turn '192.168.1.10' into a single 32-bit integer."""
    a, b, c, d = (int(part) for part in dotted.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def int_to_ip(value: int) -> str:
    """Turn a 32-bit integer back into dotted-decimal notation."""
    return f"{(value >> 24) & 0xFF}.{(value >> 16) & 0xFF}.{(value >> 8) & 0xFF}.{value & 0xFF}"


def subnet_by_hand(dotted: str, prefix: int) -> dict:
    """Compute every subnet field from first principles with bit-math."""
    ip = ip_to_int(dotted)

    # The netmask is `prefix` ones followed by (32 - prefix) zeros. Shifting a
    # full 32-bit mask left by the host-bit count zeroes the host portion.
    netmask = (ALL_ONES << (32 - prefix)) & ALL_ONES if prefix else 0

    # Network address: keep the network bits, zero the host bits (AND the mask).
    network = ip & netmask
    # Broadcast: set every host bit to 1 (OR the inverted mask).
    broadcast = network | (~netmask & ALL_ONES)

    # A /31 (2 addresses) and /32 (1 address) have no room for the two reserved
    # addresses, so they carry no "usable host" range in the classic sense.
    total = 1 << (32 - prefix)
    if total >= 4:
        usable = total - 2                 # subtract network + broadcast
        first_host = network + 1
        last_host = broadcast - 1
    else:
        usable = total if prefix == 32 else 2   # /32 host, /31 point-to-point pair
        first_host = network
        last_host = broadcast

    return {
        "netmask": int_to_ip(netmask),
        "network": int_to_ip(network),
        "broadcast": int_to_ip(broadcast),
        "first_host": int_to_ip(first_host),
        "last_host": int_to_ip(last_host),
        "usable_hosts": usable,
    }


def subnet_by_stdlib(dotted: str, prefix: int) -> dict:
    """Compute the same fields with `ipaddress` as an independent cross-check."""
    net = ipaddress.ip_network(f"{dotted}/{prefix}", strict=False)
    hosts = list(net.hosts())  # excludes network + broadcast for prefixes <= 30
    if hosts:
        first_host, last_host, usable = str(hosts[0]), str(hosts[-1]), len(hosts)
    else:
        first_host = last_host = str(net.network_address)
        usable = net.num_addresses
    return {
        "netmask": str(net.netmask),
        "network": str(net.network_address),
        "broadcast": str(net.broadcast_address),
        "first_host": first_host,
        "last_host": last_host,
        "usable_hosts": usable,
    }


def is_private(dotted: str) -> bool:
    """True if the address is in an RFC 1918 private range (10/8, 172.16/12, 192.168/16)."""
    return ipaddress.ip_address(dotted).is_private


def report(dotted: str, prefix: int) -> None:
    by_hand = subnet_by_hand(dotted, prefix)
    by_lib = subnet_by_stdlib(dotted, prefix)
    assert by_hand == by_lib, f"bit-math disagrees with ipaddress: {by_hand} != {by_lib}"

    print(f"{dotted}/{prefix}   (private: {is_private(dotted)})")
    print(f"  netmask ............. {by_hand['netmask']}")
    print(f"  network address ..... {by_hand['network']}")
    print(f"  broadcast address ... {by_hand['broadcast']}")
    print(f"  first usable host ... {by_hand['first_host']}")
    print(f"  last usable host .... {by_hand['last_host']}")
    print(f"  usable host count ... {by_hand['usable_hosts']}  (2^(32-{prefix}) - 2)")
    print("  bit-math == ipaddress: OK")
    print()


def main() -> None:
    # A /24 home network, a /26 quarter of it, and a /30 point-to-point link.
    report("192.168.1.10", 24)
    report("192.168.1.130", 26)
    report("10.0.0.1", 30)


if __name__ == "__main__":
    main()
