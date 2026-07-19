"""
How a Computer Runs a Program — see the process you're running inside.
Lesson: phases/00-foundations/03-how-a-computer-runs-a-program/docs/en.md

Your Python script is itself a running process: the OS loaded the python binary
from disk into RAM, and the CPU is executing your instructions one at a time.
Run: python runs_a_program.py
"""

import os
import sys


def main() -> None:
    # A process: this script is running with its own process id (PID).
    print("running inside PID:", os.getpid())
    print("the program executing my code:", sys.executable)  # python binary on disk

    # Data in RAM (`total`) + instructions the CPU fetches and executes (the loop).
    total = 0
    for i in range(1, 6):
        total += i                     # one tiny instruction, executed 5 times
    print("CPU stepped through a loop, computed:", total)     # 15

    # RAM is volatile: `total` exists only while this process runs. When the
    # process exits, the OS reclaims its memory and the value is gone. To keep
    # it, you must write it to disk — that's the next lesson.


if __name__ == "__main__":
    main()
