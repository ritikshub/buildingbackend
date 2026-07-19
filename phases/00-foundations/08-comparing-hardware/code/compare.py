"""
Comparing Hardware — turn units into real time, and dodge the bits/bytes trap.
Lesson: phases/00-foundations/08-comparing-hardware/docs/en.md

Given a data size and a bandwidth, compute how long a transfer takes; convert
network bits to storage bytes; compare RAM vs SSD vs network for reading 1 GB.
Run: python compare.py
"""

GB = 1_000_000_000        # 1 gigabyte in bytes
MB = 1_000_000


def transfer_time(size_bytes: float, bytes_per_sec: float) -> float:
    return size_bytes / bytes_per_sec


def mbps_to_MBps(mbps: float) -> float:
    return mbps / 8       # 8 bits = 1 byte  (the classic trap)


def main() -> None:
    print("bits vs bytes:")
    print(f"  a 100 Mbps link = {mbps_to_MBps(100)} MB/s  (not 100 MB/s!)")
    print(f"  a   1 Gbps link = {mbps_to_MBps(1000)} MB/s")

    print("\ntime to read 1 GB, by source:")
    sources = {
        "RAM (~20 GB/s)":   20 * GB,
        "SSD (~500 MB/s)":  500 * MB,
        "100 Mbps network": mbps_to_MBps(100) * MB,   # bits -> bytes/s
    }
    for name, bw in sources.items():
        print(f"  {name:20} {transfer_time(GB, bw):8.2f} s")

    ram = transfer_time(GB, 20 * GB)
    net = transfer_time(GB, mbps_to_MBps(100) * MB)
    print(f"\nRAM is ~{net / ram:.0f}x faster than the 100 Mbps network for this read.")


if __name__ == "__main__":
    main()
