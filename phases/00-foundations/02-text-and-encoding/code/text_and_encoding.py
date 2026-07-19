"""
Text & Encoding — how bytes become letters (and back).
Lesson: phases/00-foundations/02-text-and-encoding/docs/en.md

Shows ASCII code points, UTF-8 encoding of text into bytes, why character count
differs from byte count, and what a wrong decoding (mojibake) looks like.
Run: python text_and_encoding.py
"""


def main() -> None:
    # 1. A character IS a number: its code point.
    print("code points:")
    print("  ord('H') =", ord("H"))              # 72
    print("  chr(72)  =", chr(72))               # H
    print("  'a' - 'A' =", ord("a") - ord("A"))  # 32  (case is 32 apart)
    print("  '7' - '0' =", ord("7") - ord("0"))  # 7   (digits are contiguous)

    # 2. Text -> bytes via UTF-8. Character count is not byte count.
    print("\ntext -> UTF-8 bytes:")
    for s in ["Hi", "café", "€", "😀"]:
        b = s.encode("utf-8")
        print(f"  {s!r:>7}: {len(s)} char(s), {len(b)} byte(s) -> {b}")

    # 3. Bytes -> text. You MUST decode with the same encoding that wrote them.
    b = "café".encode("utf-8")                    # b'caf\xc3\xa9'
    print("\nsame bytes, two readings:")
    print("  decode utf-8  (right):", b.decode("utf-8"))
    print("  decode latin-1 (wrong):", b.decode("latin-1"))  # mojibake


if __name__ == "__main__":
    main()
