"""
Networking from the Shell — ip addr, ip route, ss, a port check, a DNS
lookup and a three-packet tcpdump, rebuilt from /proc, /sys and sockets.

Every network tool on the box reads a kernel table or opens a socket. This
script does both: interfaces from /sys/class/net, routes from /proc/net/route
(hex, little-endian, decoded), listening and established sockets from
/proc/net/tcp the way ss does, a TCP connect that distinguishes "refused"
from "timed out" from "no route", a resolver lookup through the same libc
path curl uses, the two errors every server engineer meets (EADDRINUSE and
ECONNREFUSED) produced on purpose, and, on Linux as root, three packets
captured off the loopback interface with an AF_PACKET socket and their
Ethernet, IP and TCP headers decoded by hand. Self-terminating.

Docs: phases/01-linux-and-the-command-line/14-networking-from-the-shell/docs/en.md
Spec: Linux man-pages proc(5) (/proc/net/tcp, /proc/net/route), packet(7),
      ip(7), tcp(7), getaddrinfo(3); RFC 791 (IP header), RFC 9293 (TCP header)

Run:
    python netshell.py
"""

import errno
import os
import socket
import struct
import sys
import threading
import time

LINUX = os.path.exists("/proc/net/tcp")


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}", flush=True)


# ─── ip addr: /sys/class/net ─────────────────────────────────────────────────
def interfaces():
    out = []
    for name in sorted(os.listdir("/sys/class/net")):
        base = f"/sys/class/net/{name}"
        def rd(f):
            try:
                return open(f"{base}/{f}").read().strip()
            except OSError:
                return "?"
        out.append((name, rd("address"), rd("mtu"), rd("operstate")))
    return out


def ipv4_addresses():
    """The addresses per interface: ask the kernel through a UDP socket trick per interface."""
    addrs = {}
    try:
        for line in open("/proc/net/fib_trie"):
            pass
    except OSError:
        pass
    # portable enough: connect a UDP socket to a public address to learn the outbound source IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("203.0.113.1", 9))
        addrs["outbound"] = s.getsockname()[0]
    except OSError as e:
        addrs["outbound"] = f"no route ({e.strerror})"
    finally:
        s.close()
    return addrs


# ─── ip route: /proc/net/route ───────────────────────────────────────────────
def hex_ip(h):
    return socket.inet_ntoa(struct.pack("<I", int(h, 16)))    # little-endian hex -> dotted quad


def routes():
    out = []
    for line in open("/proc/net/route").readlines()[1:]:
        f = line.split()
        iface, dest, gw, flags, mask = f[0], f[1], f[2], int(f[3], 16), f[7]
        out.append((hex_ip(dest), hex_ip(mask), hex_ip(gw), iface, flags))
    return out


# ─── ss: /proc/net/tcp ───────────────────────────────────────────────────────
STATES = {"01": "ESTAB", "02": "SYN-SENT", "03": "SYN-RECV", "04": "FIN-WAIT-1", "05": "FIN-WAIT-2",
          "06": "TIME-WAIT", "07": "CLOSE", "08": "CLOSE-WAIT", "09": "LAST-ACK", "0A": "LISTEN", "0B": "CLOSING"}


def hex_addr(s):
    ip, port = s.split(":")
    return f"{hex_ip(ip)}:{int(port, 16)}"


def ss():
    rows = []
    for line in open("/proc/net/tcp").readlines()[1:]:
        f = line.split()
        rows.append((STATES.get(f[3], f[3]), hex_addr(f[1]), hex_addr(f[2]), int(f[4].split(":")[1], 16), int(f[4].split(":")[0], 16), f[9]))
    return rows


def pid_for_socket_inode(inode):
    """ss -p: scan every process's descriptors for socket:[inode]."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}") == f"socket:[{inode}]":
                    return int(pid)
        except OSError:
            continue
    return None


# ─── nc -zv: a connect with a verdict ────────────────────────────────────────
def port_check(host, port, timeout=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.perf_counter()
    try:
        s.connect((host, port))
        return f"open ({(time.perf_counter() - t0) * 1000:.1f} ms to handshake)"
    except ConnectionRefusedError:
        return "closed: connection refused (a host answered with RST: nothing is listening there)"
    except socket.timeout:
        return "filtered: timed out (no answer at all: a firewall dropped it, or the host is down)"
    except OSError as e:
        return f"{errno.errorcode.get(e.errno, e.errno)}: {e.strerror} (routing or address problem, before any packet)"
    finally:
        s.close()


# ─── tcpdump: AF_PACKET, three packets, decoded ──────────────────────────────
def sniff(port, count=3, timeout=3.0):
    """Capture `count` TCP packets to or from `port` on the loopback and decode the headers."""
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))   # every protocol
    raw.bind(("lo", 0))
    raw.settimeout(timeout)
    seen = []
    deadline = time.time() + timeout
    while len(seen) < count and time.time() < deadline:
        try:
            frame, meta = raw.recvfrom(65535)
        except socket.timeout:
            break
        if meta[2] == 4:                                        # PACKET_OUTGOING: on loopback every packet is
            continue                                            # seen twice (leaving and arriving); keep one
        eth_type = struct.unpack("!H", frame[12:14])[0]
        if eth_type != 0x0800:
            continue                                            # not IPv4
        ip = frame[14:]
        ihl = (ip[0] & 0x0F) * 4
        proto = ip[9]
        if proto != 6:
            continue                                            # not TCP
        src, dst = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])
        tcp = ip[ihl:]
        sport, dport, seq, ack, off_flags = struct.unpack("!HHIIH", tcp[:14])
        if port not in (sport, dport):
            continue
        flags = off_flags & 0x01FF
        names = [n for bit, n in ((0x02, "SYN"), (0x10, "ACK"), (0x08, "PSH"), (0x01, "FIN"), (0x04, "RST")) if flags & bit]
        data_off = (off_flags >> 12) * 4
        payload = len(ip) - ihl - data_off
        seen.append(f"{src}:{sport} -> {dst}:{dport}  [{','.join(names)}]  seq={seq}  ack={ack}  len={payload}")
    raw.close()
    return seen


if __name__ == "__main__":
    banner("1 · ip addr: the interfaces, from /sys/class/net")
    if LINUX:
        for name, mac, mtu, state in interfaces():
            print(f"   {name:8} mac {mac:18} mtu {mtu:>5}  state {state}")
    else:
        print("   (/sys/class/net is Linux only; macOS: ifconfig or networksetup -listallhardwareports)")
    print(f"   outbound source address (what a packet to the internet would carry): {ipv4_addresses()['outbound']}")

    banner("2 · ip route: the routing table, decoded from /proc/net/route")
    if LINUX:
        print(f"   {'destination':16} {'mask':16} {'gateway':16} iface")
        for dest, mask, gw, iface, flags in routes():
            label = "default" if dest == "0.0.0.0" else dest
            print(f"   {label:16} {mask:16} {gw if gw != '0.0.0.0' else 'on-link':16} {iface}")
        print("   a packet takes the most specific matching row; 'default' is where everything else goes (the gateway)")
    else:
        print("   (/proc/net/route is Linux only; macOS: netstat -rn)")

    banner("3 · ss -tlnp: sockets from /proc/net/tcp, with the owning PID found through /proc/*/fd")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)
    port = srv.getsockname()[1]
    print(f"   (this script is listening on 127.0.0.1:{port} so there is something to find)")
    if LINUX:
        print(f"   {'state':10} {'local':22} {'peer':22} {'rq':>3} {'sq':>3}  pid")
        for state, local, peer, rq, sq, inode in ss():
            if state in ("LISTEN", "ESTAB"):
                pid = pid_for_socket_inode(inode)
                print(f"   {state:10} {local:22} {peer:22} {rq:>3} {sq:>3}  {pid or '-'}{'  <- ours' if pid == os.getpid() else ''}")
        print("   Recv-Q on a LISTEN socket = connections waiting to be accept()ed; Send-Q = the backlog capacity")
    else:
        print("   (macOS: lsof -iTCP -sTCP:LISTEN -P, or netstat -an)")

    banner("4 · nc -zv: three answers a port can give, produced on purpose")
    print(f"   127.0.0.1:{port} (we listen)      -> {port_check('127.0.0.1', port)}")
    print(f"   127.0.0.1:1 (nobody listens)      -> {port_check('127.0.0.1', 1)}")
    print(f"   203.0.113.1:80 (a black hole)     -> {port_check('203.0.113.1', 80, timeout=1.0)}")
    print("   refused = a host is there and said no; timed out = nothing said anything; those are different problems")

    banner("5 · EADDRINUSE and ECONNREFUSED: the two errors every server engineer meets")
    second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        second.bind(("127.0.0.1", port))
    except OSError as e:
        print(f"   bind(127.0.0.1:{port}) while we already listen -> errno {e.errno} {errno.errorcode[e.errno]}: {e.strerror}")
    second.close()
    print("   the previous copy of a server, or a TIME-WAIT socket without SO_REUSEADDR, gives the same message")
    srv.close()
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1)
    except OSError as e:
        print(f"   connect(127.0.0.1:{port}) after we closed  -> errno {e.errno} {errno.errorcode[e.errno]}: {e.strerror}")

    banner("6 · dig, the short way: getaddrinfo, the same call curl and Python use")
    for host in ("localhost", "deb.debian.org"):
        t0 = time.perf_counter()
        try:
            addrs = sorted({a[4][0] for a in socket.getaddrinfo(host, 80, proto=socket.IPPROTO_TCP)})
            print(f"   {host:18} -> {', '.join(addrs[:4])}  ({(time.perf_counter() - t0) * 1000:.1f} ms)")
        except socket.gaierror as e:
            print(f"   {host:18} -> {e}")
    print("   the order: /etc/nsswitch.conf decides; /etc/hosts first, then the resolvers in /etc/resolv.conf, over UDP port 53")

    banner("7 · tcpdump -i lo: three packets of a real handshake, decoded from an AF_PACKET socket")
    if LINUX and os.geteuid() == 0:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0)); srv.listen(8)
        p = srv.getsockname()[1]
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("pkts", sniff(p, count=3)))
        t.start(); time.sleep(0.2)
        c = socket.create_connection(("127.0.0.1", p)); c.sendall(b"hi"); c.close()
        conn, _ = srv.accept(); conn.close(); srv.close()
        t.join()
        for line in result.get("pkts", []):
            print("   " + line)
        print("   SYN, SYN-ACK, ACK: lesson 05 of Phase 2, seen on the wire. tcpdump prints exactly these fields")
    else:
        print("   (needs Linux and root: raw AF_PACKET sockets. In the sandbox you are root; on a server, sudo tcpdump)")
