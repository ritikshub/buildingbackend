"""
Files & the Filesystem — a file is just named bytes on disk.
Lesson: phases/00-foundations/04-files-and-the-filesystem/docs/en.md

Writes bytes to a file, reads them back, shows metadata (size), and proves a
"text file" is the same bytes read as text. Cleans up after itself.
Run: python files.py
"""

from pathlib import Path


def main() -> None:
    path = Path("hello.txt")

    # Open, write bytes, close — all in one call. Survives after this process exits.
    path.write_text("hi there\n", encoding="utf-8")

    # Metadata: the filesystem tracks facts *about* the file.
    print("exists? ", path.exists())
    print("name:   ", path.name)
    print("size:   ", path.stat().st_size, "bytes")     # 9: 'hi there' (8) + newline (1)

    # The same file, two readings — as text, and as the raw bytes underneath.
    print("as text: ", repr(path.read_text(encoding="utf-8")))
    print("as bytes:", path.read_bytes())                # b'hi there\n'

    # Clean up so we leave no file behind.
    path.unlink()
    print("deleted, exists now?", path.exists())


if __name__ == "__main__":
    main()
