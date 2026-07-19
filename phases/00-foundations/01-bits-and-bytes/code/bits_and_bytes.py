"""
Bits & Bytes — see the binary and hex behind ordinary numbers.
Lesson: phases/00-foundations/01-bits-and-bytes/docs/en.md

A tiny, dependency-free tour: convert between decimal, binary, and hex, and show
that a byte holds 0–255. Run: python bits_and_bytes.py
"""


def show(n: int) -> None:
    # bin()/hex() return strings prefixed with 0b / 0x.
    print(f"{n:>3}  ->  binary {bin(n)[2:]:>8}   hex {hex(n)[2:].upper():>2}")


def main() -> None:
    print("decimal -> binary / hex")
    for n in (0, 1, 2, 3, 4, 8, 11, 255):
        show(n)

    print("\nreading values back:")
    print("  binary '1011' as a number:", int("1011", 2))   # 11
    print("  hex    'FF'   as a number:", int("FF", 16))     # 255

    print("\none byte's range:")
    print("  smallest:", 0)
    print("  largest :", 255, "(that's 2**8 - 1)")
    assert 2 ** 8 == 256                                     # 256 patterns, 0..255

    print("\na colour is just three bytes (R, G, B):")
    r, g, b = 0x00, 0xFF, 0x00                               # #00FF00 = pure green
    print(f"  #00FF00  ->  red={r}  green={g}  blue={b}")


if __name__ == "__main__":
    main()
