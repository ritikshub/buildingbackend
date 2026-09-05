"""
SSH — what it replaced, built in sixty lines so the reason for every part of
SSH is visible: a remote shell over a plain TCP socket, with a password sent
in clear text, no host identity, and no integrity.

The server listens, asks for a password, and then runs whatever lines the
client sends through /bin/sh, returning the output. The client connects and
relays your commands. It works. It is also exactly what rsh and telnet were,
and the script sniffs its own traffic on loopback (Linux, root) to show the
password and every command passing by in the clear. Every SSH feature in the
lesson answers one of the four problems this program has. Self-terminating;
binds 127.0.0.1 only.

Docs: phases/01-linux-and-the-command-line/17-ssh-keys-tunnels-and-rsync/docs/en.md
Spec: RFC 4251 (SSH architecture: the problems), RFC 4252 (authentication),
      RFC 4253 (transport: host keys, key exchange), RFC 4254 (connection:
      channels, port forwarding). The plaintext protocol here is deliberately
      the pre-SSH design of telnet (RFC 854) and rsh.

Run:
    python plainshell.py
"""

import os
import socket
import struct
import subprocess
import sys
import threading
import time

PASSWORD = "hunter2"
PORT = 2323


def server(ready):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT)); srv.listen(1)
    ready.set()
    conn, peer = srv.accept()
    f = conn.makefile("rwb", buffering=0)
    f.write(b"password: ")
    if f.readline().strip() != PASSWORD.encode():                  # problem 1: the password crosses the wire as-is
        f.write(b"denied\n"); conn.close(); srv.close(); return
    f.write(b"ok. type commands; 'exit' to leave\n")
    for line in f:                                                 # problem 2: every command and result, readable
        cmd = line.decode().strip()
        if cmd == "exit":
            break
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True)   # problem 4: no channels, no forwarding, one stream
        f.write((out.stdout + out.stderr).encode() + b"<end>\n")
    conn.close(); srv.close()


def client(commands):
    """Connect, send the password, run each command, collect the answers."""
    time.sleep(0.1)
    c = socket.create_connection(("127.0.0.1", PORT))            # problem 3: nothing proves this is the server we meant
    f = c.makefile("rwb", buffering=0)
    f.read(len(b"password: "))
    f.write(PASSWORD.encode() + b"\n")
    print("   client:", f.readline().decode().strip())
    for cmd in commands:
        f.write(cmd.encode() + b"\n")
        out = b""
        for line in f:
            if line == b"<end>\n":
                break
            out += line
        print(f"   client: $ {cmd}\n" + "".join("   client: " + l + "\n" for l in out.decode().splitlines()), end="")
    f.write(b"exit\n"); c.close()


def sniff(port, stop, seen):
    """AF_PACKET on loopback: print every TCP payload to or from `port` as text (Linux, root)."""
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    raw.bind(("lo", 0)); raw.settimeout(0.2)
    while not stop.is_set():
        try:
            frame, meta = raw.recvfrom(65535)
        except socket.timeout:
            continue
        if meta[2] == 4 or struct.unpack("!H", frame[12:14])[0] != 0x0800:
            continue
        ip = frame[14:]; ihl = (ip[0] & 0x0F) * 4
        if ip[9] != 6:
            continue
        tcp = ip[ihl:]
        sport, dport = struct.unpack("!HH", tcp[:4])
        if port not in (sport, dport):
            continue
        payload = tcp[(tcp[12] >> 4) * 4:]
        if payload:
            direction = "client -> server" if dport == port else "server -> client"
            seen.append((direction, payload.decode(errors="replace")))
    raw.close()


if __name__ == "__main__":
    print("=== a remote shell over plain TCP: it works, and that is the problem")
    can_sniff = os.path.exists("/proc/net/tcp") and os.geteuid() == 0
    ready, stop, seen = threading.Event(), threading.Event(), []
    if can_sniff:
        t_sniff = threading.Thread(target=sniff, args=(PORT, stop, seen)); t_sniff.start()
    t_srv = threading.Thread(target=server, args=(ready,)); t_srv.start()
    ready.wait()
    client(["id", "cat /etc/hostname", "echo the database password is s3cr3t"])
    t_srv.join()
    if can_sniff:
        time.sleep(0.3); stop.set(); t_sniff.join()
        print("\n=== the same session, read off the wire by a third party on the path (tcpdump -A would show this)")
        for direction, text in seen:
            for line in text.splitlines():
                print(f"   [{direction}] {line}")
    else:
        print("\n   (sniffing needs Linux and root; in the sandbox this section prints every byte, password included)")
    print("""
=== the four problems, and the SSH feature that answers each
   1 · the password crossed in clear text          -> SSH encrypts everything after a key exchange (RFC 4253); and keys replace passwords (RFC 4252)
   2 · every command and result was readable       -> the same encryption, plus a MAC so nothing can be altered in flight
   3 · nothing proved the server was the real one  -> host keys and known_hosts: the server signs the exchange, the client remembers its key
   4 · one stream: no files, no tunnels, no agent  -> channels (RFC 4254): sessions, scp/sftp, -L/-R port forwards and agent forwarding on one connection""")
