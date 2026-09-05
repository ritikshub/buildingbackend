#!/usr/bin/env python3
"""
Authorization models — RBAC, ABAC, and ReBAC — behind one can() interface, plus
the object-level check that stops the IDOR.

Companion to docs/en.md (Phase 07, Lesson 09). What it makes concrete:

  * RBAC: users -> roles -> permissions. Simple, fast, coarse.
  * ABAC: the decision is a boolean over attributes of subject/resource/action/
    context (department, business hours, ...). Fine-grained, context-aware.
  * ReBAC: relationship tuples form a graph; "can X do Y on Z" = find a path
    (the Google Zanzibar model behind OpenFGA / SpiceDB), incl. group rewrite.
  * The IDOR is an ENFORCEMENT bug: passing the route check ("is an editor") is
    not enough — you must authorize the OBJECT ("owns/shared this document").
  * Deny by default: no matching allow means denied.

Stdlib only:  python3 authorization.py
"""

from __future__ import annotations


# ── RBAC ─────────────────────────────────────────────────────────────────────

USER_ROLES = {"alice": {"editor"}, "bob": {"viewer"}, "carol": {"billing"}}
ROLE_PERMS = {
    "editor": {"doc.read", "doc.write"},
    "viewer": {"doc.read"},
    "billing": {"billing.refund", "doc.read"},
}


def rbac_can(user: str, perm: str) -> bool:
    return any(perm in ROLE_PERMS.get(r, set()) for r in USER_ROLES.get(user, set()))


# ── ABAC ─────────────────────────────────────────────────────────────────────

def abac_can(subject: dict, action: str, resource: dict, ctx: dict) -> bool:
    return (subject["dept"] == resource["dept"]                 # same department
            and action in resource["allowed_actions"]
            and 9 <= ctx["hour"] < 18)                          # business hours only


# ── ReBAC (relationship graph, Zanzibar-style) ───────────────────────────────

# (object, relation, subject)
TUPLES = {
    ("doc:42", "editor", "group:eng"),
    ("group:eng", "member", "user:alice"),
    ("doc:7", "owner", "user:alice"),
}


def _member_of(principal: str, group: str, seen=frozenset()) -> bool:
    if group in seen:
        return False
    for (o, rel, sub) in TUPLES:
        if o == group and rel == "member":
            if sub == principal or _member_of(principal, sub, seen | {group}):
                return True
    return False


def rebac_can(principal: str, relation: str, obj: str) -> bool:
    for (o, rel, sub) in TUPLES:
        if o == obj and rel == relation:
            if sub == principal:                               # direct relationship
                return True
            if sub.startswith("group:") and _member_of(principal, sub):   # userset rewrite
                return True
    return False


# ── Object-level authorization (the IDOR fix) ────────────────────────────────

DOCUMENTS = {
    7: {"owner": "alice", "shared_with": set()},
    42: {"owner": "bob", "shared_with": set()},
}


def object_can_access(user: str, doc_id: int) -> bool:
    doc = DOCUMENTS[doc_id]
    return user == doc["owner"] or user in doc["shared_with"]   # authorize the OBJECT


def get_document(user: str, doc_id: int) -> str:
    if not rbac_can(user, "doc.read"):          # route-level: may this user read documents at all?
        return "403 forbidden (route)"
    if not object_can_access(user, doc_id):     # object-level: may they read THIS document?
        return "403 forbidden"
    return "200 ok"


# ── Demos ────────────────────────────────────────────────────────────────────

def demo_rbac() -> None:
    print("== 1 · RBAC: ROLES GROUP PERMISSIONS ==")
    print(f"  alice roles={{editor}}  can doc.write? {rbac_can('alice', 'doc.write')}   "
          f"can billing.refund? {rbac_can('alice', 'billing.refund')}")
    print(f"  carol roles={{billing}} can billing.refund? {rbac_can('carol', 'billing.refund')}   "
          f"can doc.write? {rbac_can('carol', 'doc.write')}")


def demo_abac() -> None:
    print("\n== 2 · ABAC: A POLICY OVER ATTRIBUTES (context-aware) ==")
    eng_user = {"dept": "eng"}
    eng_doc = {"dept": "eng", "allowed_actions": {"read", "write"}}
    sales_doc = {"dept": "sales", "allowed_actions": {"read"}}
    print(f"  eng user, eng doc, 11:00  read -> {'allow' if abac_can(eng_user,'read',eng_doc,{'hour':11}) else 'deny'}")
    print(f"  eng user, eng doc, 22:00  read -> {'allow' if abac_can(eng_user,'read',eng_doc,{'hour':22}) else 'deny'}   (outside business hours)")
    print(f"  eng user, sales doc, 11:00 read -> {'allow' if abac_can(eng_user,'read',sales_doc,{'hour':11}) else 'deny'}  (different department)")


def demo_rebac() -> None:
    print("\n== 3 · ReBAC: RELATIONSHIPS AS A GRAPH (Zanzibar-style) ==")
    print("  tuples: doc:42 editor group:eng ; group:eng member user:alice")
    print(f"  alice editor of doc:42?  {rebac_can('user:alice', 'editor', 'doc:42')}    (via group membership)")
    print(f"  bob   editor of doc:42?  {rebac_can('user:bob', 'editor', 'doc:42')}   (no relationship path)")


def demo_idor() -> None:
    print("\n== 4 · OBJECT-LEVEL CHECK STOPS THE IDOR ==")
    print("  alice is a valid editor (route check passes)")
    print(f"  GET /documents/42 (owner=bob) -> {get_document('alice', 42)}   ✓ object check denies")
    print(f"  GET /documents/7  (owner=alice) -> {get_document('alice', 7)}")


def demo_deny_default() -> None:
    print("\n== 5 · DENY BY DEFAULT ==")
    print(f"  unknown action 'doc.publish' with no matching policy -> "
          f"{'allow' if rbac_can('alice', 'doc.publish') else 'deny'}   ✓")


def main() -> None:
    demo_rbac()
    demo_abac()
    demo_rebac()
    demo_idor()
    demo_deny_default()


if __name__ == "__main__":
    main()
