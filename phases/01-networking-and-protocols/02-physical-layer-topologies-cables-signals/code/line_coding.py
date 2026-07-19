"""
Physical Layer — encode bits as signal levels: NRZ vs Manchester line coding.

The physical layer turns 1s and 0s into a physical signal (a voltage on copper).
This shows two ways to do it for the bit string "10110": NRZ (Non-Return-to-Zero),
which just holds a level for the whole bit, and Manchester, which forces a
transition in the MIDDLE of every bit so the receiver can recover the clock from
the signal itself (self-clocking). We print the levels and a simple waveform.

Docs: phases/01-networking-and-protocols/02-physical-layer-topologies-cables-signals/docs/en.md
Spec: Manchester convention per IEEE 802.3 (0 = high->low, 1 = low->high at mid-bit).

Run:
    python3 line_coding.py
Encodes the bit string both ways, prints levels + waveforms, exits 0.
"""

from __future__ import annotations

HIGH = +1
LOW = -1

BITS = "10110"


def nrz_l(bits):
    """NRZ-L: level held constant for the whole bit. 1 -> HIGH, 0 -> LOW.

    Returns two half-bit samples per bit so it lines up with Manchester, but
    both halves are the SAME level: there is no mid-bit transition.
    """
    samples = []
    for bit in bits:
        level = HIGH if bit == "1" else LOW
        samples.append((level, level))
    return samples


def manchester(bits):
    """Manchester (IEEE 802.3): a transition at the MIDDLE of each bit.

    0 -> high in the first half, low in the second (a falling edge mid-bit).
    1 -> low in the first half, high in the second (a rising edge mid-bit).
    The guaranteed mid-bit edge is what makes the code self-clocking.
    """
    samples = []
    for bit in bits:
        if bit == "1":
            samples.append((LOW, HIGH))   # rising edge at mid-bit
        else:
            samples.append((HIGH, LOW))   # falling edge at mid-bit
    return samples


def level_str(samples):
    """Flatten half-bit samples to a '+1/-1' sequence string."""
    flat = [lvl for pair in samples for lvl in pair]
    return " ".join(f"{v:+d}" for v in flat)


def waveform(samples):
    """A two-char-per-half-bit signal trace: HIGH is an overline, LOW an underscore."""
    trace = ""
    for first, second in samples:
        trace += "‾‾" if first == HIGH else "__"
        trace += "‾‾" if second == HIGH else "__"
    return trace


def mid_bit_transition(pair):
    first, second = pair
    if first == second:
        return "none  (NOT self-clocking)"
    return "rising (low->high)" if second == HIGH else "falling (high->low)"


def main():
    print(f"Bit string to encode: {BITS}")
    print(f"  ({len(BITS)} bits; each drawn as two half-bit samples below)\n")

    nrz = nrz_l(BITS)
    man = manchester(BITS)

    print("NRZ-L (Non-Return-to-Zero, Level)")
    print(f"  levels ...  {level_str(nrz)}")
    print(f"  waveform .. {waveform(nrz)}")
    print()

    print("Manchester (IEEE 802.3 convention)")
    print(f"  levels ...  {level_str(man)}")
    print(f"  waveform .. {waveform(man)}")
    print()

    print("Per-bit mid-bit transition (why Manchester self-clocks):")
    print(f"  {'bit':>4} | {'NRZ-L':<26} | Manchester")
    for bit, n_pair, m_pair in zip(BITS, nrz, man):
        print(f"  {bit:>4} | {mid_bit_transition(n_pair):<26} | {mid_bit_transition(m_pair)}")
    print()

    print("Takeaway: NRZ is compact but a long run of identical bits has no")
    print("transitions, so the receiver's clock can drift. Manchester guarantees")
    print("one transition per bit (at the cost of ~2x the signal bandwidth): the")
    print("bit rate is half the baud rate. That is the clock-vs-bandwidth trade.")


if __name__ == "__main__":
    main()
