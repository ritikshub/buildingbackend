"""
HTTP in Depth — a status-code classifier built by hand.

Every HTTP response opens with a status line: HTTP/1.1 <code> <reason>. The first
digit of the three-digit code names the family (1-5); the whole code names the
specific condition. This maps a code to its family and meaning and prints worked
examples, so the numbers stop being magic.

Docs: phases/01-networking-and-protocols/08-http-in-depth/docs/en.md
Spec: RFC 9110 §15 (HTTP status codes)

Run:
    python3 status_codes.py
Prints each example's family and meaning, then exits 0.
"""

# The five families, keyed by the leading digit (RFC 9110 §15).
FAMILIES = {
    1: ("Informational", "Request received, continuing — an interim response."),
    2: ("Success", "The request was received, understood, and accepted."),
    3: ("Redirection", "Further action is needed to complete the request."),
    4: ("Client Error", "The request is faulty — the caller must fix it."),
    5: ("Server Error", "The server failed to fulfil an apparently valid request."),
}

# A few canonical codes worth knowing by name (RFC 9110 §15).
MEANINGS = {
    100: "Continue",
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def classify(code: int):
    """Return (family_name, family_blurb, code_meaning) for a status code."""
    if not 100 <= code <= 599:
        raise ValueError(f"{code} is not a valid HTTP status code (100-599)")
    family_digit = code // 100
    family_name, family_blurb = FAMILIES[family_digit]
    meaning = MEANINGS.get(code, "(no canonical name — vendor or extension code)")
    return family_name, family_blurb, meaning


def report(code: int) -> None:
    family_name, family_blurb, meaning = classify(code)
    print(f"{code} {meaning}")
    print(f"  family .... {code // 100}xx {family_name}")
    print(f"  means ..... {family_blurb}")


def main() -> None:
    # One worked example drawn from each family, plus a couple more.
    for code in (100, 200, 201, 204, 301, 304, 404, 429, 500, 503):
        report(code)
        print()

    # The classifier works on any code, even ones without a canonical name.
    print("Unknown-but-valid code still classifies by its first digit:")
    report(418)  # a real code (RFC 9110 does not define 418; some servers send it)


if __name__ == "__main__":
    main()
