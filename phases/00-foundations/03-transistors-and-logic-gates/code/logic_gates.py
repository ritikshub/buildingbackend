"""
Transistors & Logic Gates — build arithmetic out of pure logic.
Lesson: phases/00-foundations/03-transistors-and-logic-gates/docs/en.md

Define the basic gates, build an adder from ONLY AND/OR/NOT, and add real
numbers with it — the same idea a CPU implements in transistors.
Run: python logic_gates.py
"""


def NOT(a):    return 1 - a
def AND(a, b): return 1 if (a and b) else 0
def OR(a, b):  return 1 if (a or b) else 0
def XOR(a, b): return AND(OR(a, b), NOT(AND(a, b)))   # built from AND/OR/NOT only


def half_adder(a, b):
    return XOR(a, b), AND(a, b)                        # (sum, carry)


def full_adder(a, b, carry_in):
    s1, c1 = half_adder(a, b)
    s, c2 = half_adder(s1, carry_in)
    return s, OR(c1, c2)                               # (sum, carry_out)


def add(x, y, width=8):
    """Add two numbers bit by bit, using only the gates above."""
    result, carry = 0, 0
    for i in range(width):
        s, carry = full_adder((x >> i) & 1, (y >> i) & 1, carry)
        result |= s << i
    return result


def main() -> None:
    print("XOR truth table (sum of two bits):")
    for a in (0, 1):
        for b in (0, 1):
            print(f"  {a} XOR {b} = {XOR(a, b)}   (carry {AND(a, b)})")

    print("\nAdding numbers with gates only:")
    for x, y in [(5, 6), (15, 1), (100, 28)]:
        got = add(x, y)
        print(f"  {x} + {y} = {got}", "OK" if got == x + y else "WRONG")


if __name__ == "__main__":
    main()
