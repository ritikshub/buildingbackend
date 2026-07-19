"""
The CPU — a tiny fetch-decode-execute simulator.
Lesson: phases/00-foundations/05-the-cpu/docs/en.md

A CPU repeats one loop: fetch the next instruction, decode it, execute it. This
mini "CPU" runs a small program of (op, args) instructions against registers.
Run: python mini_cpu.py
"""


def run(program, trace=True):
    regs = {"A": 0, "B": 0}
    pc = 0                                   # program counter: the next instruction
    while pc < len(program):
        op, *args = program[pc]              # FETCH
        if trace:
            print(f"  pc={pc}  fetch {op} {args}")
        # DECODE + EXECUTE
        if op == "SET":
            regs[args[0]] = args[1]
        elif op == "ADD":
            regs[args[0]] += regs[args[1]]
        elif op == "PRINT":
            print(f"     -> {args[0]} = {regs[args[0]]}")
        else:
            raise ValueError(f"unknown instruction: {op}")
        pc += 1                              # advance to the next instruction
    return regs


def main() -> None:
    program = [
        ("SET", "A", 5),
        ("SET", "B", 6),
        ("ADD", "A", "B"),       # A = A + B
        ("PRINT", "A"),          # 11
    ]
    print("Running a 4-instruction program on the mini CPU:")
    regs = run(program)
    assert regs["A"] == 11
    print("final registers:", regs)


if __name__ == "__main__":
    main()
