# Authorization: RBAC, ABAC & ReBAC

> Eight lessons established *who* the caller is. This one answers the other half of the phase's opening question — *what are they allowed to do?* — and it's where the very first bug in this phase, the IDOR, actually lives. Authorization is a decision, `(subject, action, resource) → allow | deny`, and the difference between a secure system and a breach is whether that decision is made **consistently, on every access, and at the object level**. You'll build the three models the industry runs on — **RBAC** (roles), **ABAC** (attributes), and **ReBAC** (relationships, the Google Zanzibar model behind modern fine-grained authorization) — and learn where the check must live so it can't be skipped.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Authentication, Authorization & the Security Mindset](../01-authn-authz-and-the-security-mindset/) · [JWT & Token Auth from Scratch](../06-jwt-and-token-auth/)
**Time:** ~80 minutes

## The Problem

Your app has authenticated users. Now the real question arrives on every single request: *is this specific user allowed to do this specific thing to this specific object?* Can Alice **read** document 42? Can Bob **delete** it? Can a support agent **refund** this payment but not that one?

The way this usually starts — and the way it usually breaks — is scattered inline checks:

```python
@app.get("/documents/{doc_id}")
def get_document(doc_id, user):
    if user.role != "admin" and user.role != "editor":   # a check, sprinkled in the handler
        raise Forbidden()
    return db.documents.get(doc_id)                        # ...but WHOSE document?
```

Two things are wrong, and both are extremely common. First, the check is about the user's **role**, not about **this document** — so any editor can read *every* document, including ones that aren't theirs. Change `doc_id` in the URL and you read someone else's data: the **IDOR** from [Lesson 1](../01-authn-authz-and-the-security-mindset/), which is just **broken object-level authorization**, and it sits at the very top of the OWASP Top 10 ([Lesson 11](../11-injection-and-owasp-top-10/)). Second, this logic is copy-pasted across dozens of handlers, so the day someone adds a new endpoint and forgets the check — or gets the role list subtly wrong — there's a hole, and nobody can answer the auditor's question "who can access document 42?" because the answer is smeared across the codebase.

As the app grows it gets worse. Roles multiply (`admin`, `editor`, `billing_admin`, `read_only_auditor`, `contractor_editor_except_billing`), exceptions pile up ("editors can edit, *except* contractors, *except* on documents marked confidential, *except* their own"), and you get **role explosion** — dozens of near-duplicate roles that no one fully understands. The scattered `if` statements become unmaintainable and unauditable.

The fix is to stop treating authorization as ad-hoc conditionals and start treating it as what it is: **a decision, computed by a model, enforced in one place, on every access.** This lesson builds the decision, the three dominant models for computing it, and the enforcement discipline that keeps the IDOR from ever existing.

## The Concept

### Authorization is a decision, separated from enforcement

Every authorization question has the same shape — a **subject** (who), an **action** (what verb), a **resource** (on what), and often **context** (when, from where) — and produces one bit: **allow or deny**. The single most important structural idea is to **separate the code that *enforces* the decision from the code that *makes* it**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="100%" style="max-width:880px" role="img" aria-label="Authorization decision architecture. An authenticated request reaches the Policy Enforcement Point in the application, which intercepts every access, gathers the subject, action, resource, and context, and asks the Policy Decision Point. The decision point evaluates the policy against the model — roles, attributes, or relationships — and returns allow or deny. On allow the request proceeds; on deny it returns 403. The key ideas: every access goes through the enforcement point, the decision is made in one place, and the default is deny.">
  <defs>
    <marker id="l9d-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Separate enforcement (where) from decision (what) — deny by default</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8" font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="24" y="88" width="130" height="60" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="250" y="76" width="220" height="84" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="560" y="76" width="220" height="84" rx="11" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M154 118 L 246 118" marker-end="url(#l9d-ar)"/>
    <path d="M470 108 L 556 108" marker-end="url(#l9d-ar)"/>
    <path d="M556 132 L 474 132" marker-end="url(#l9d-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="89" y="112" font-size="10" text-anchor="middle">request</text>
    <text x="89" y="128" font-size="8.5" text-anchor="middle" opacity="0.7">(authenticated)</text>
    <text x="360" y="98" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">PEP — Enforcement</text>
    <text x="360" y="116" font-size="8.5" text-anchor="middle">intercepts EVERY access</text>
    <text x="360" y="130" font-size="8.5" text-anchor="middle">gathers subject, action,</text>
    <text x="360" y="144" font-size="8.5" text-anchor="middle">resource, context → asks ↓</text>
    <text x="670" y="98" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">PDP — Decision</text>
    <text x="670" y="116" font-size="8.5" text-anchor="middle">evaluates the policy against</text>
    <text x="670" y="130" font-size="8.5" text-anchor="middle">the model (roles / attributes</text>
    <text x="670" y="144" font-size="8.5" text-anchor="middle">/ relationships)</text>
    <text x="513" y="102" font-size="8" text-anchor="middle" opacity="0.7">(s,a,r,ctx)</text>
    <text x="513" y="150" font-size="8" text-anchor="middle" opacity="0.7">allow/deny</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="360" y="196" font-size="10" text-anchor="middle">allow → request proceeds  ·  deny → 403</text>
    <rect x="150" y="216" width="600" height="60" rx="9" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.6"/>
    <text x="450" y="238" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">Three invariants</text>
    <text x="450" y="256" font-size="9.5" text-anchor="middle">① every access goes through the PEP   ② one place makes the decision (auditable, changeable)</text>
    <text x="450" y="270" font-size="9.5" text-anchor="middle">③ the default is DENY — access requires an explicit allow, never the absence of a deny</text>
  </g>
</svg>
```

The vocabulary is **PEP** (Policy Enforcement Point — the code in your app that intercepts a request and enforces the verdict) and **PDP** (Policy Decision Point — the logic that computes allow/deny from a model). Separating them is what makes authorization *auditable* (one place to ask "who can do what"), *changeable* (update policy without touching every handler), and *complete* (one choke point every request passes through). And the default must be **deny**: a resource is inaccessible unless a policy explicitly grants access — the fail-closed principle from [Lesson 1](../01-authn-authz-and-the-security-mindset/), applied to every object.

### ACLs and RBAC: the first two models

The simplest model is an **ACL** (Access Control List): each resource carries a list of who may do what (`document 42: {alice: [read, write], bob: [read]}`). It's precise but doesn't scale — with thousands of users and millions of objects you're managing billions of entries by hand, and "give all engineers read access" means editing every document.

**RBAC** (Role-Based Access Control) fixes the scale problem with a layer of indirection: users are assigned **roles**, roles are granted **permissions**, and you check whether any of a user's roles has the needed permission. Grant a permission to the `editor` role once and every editor has it; onboard a new engineer by giving them a role, not a thousand ACL entries. RBAC is the workhorse of authorization — simple, fast, easy to reason about — and it's the right default for coarse-grained access ("admins can access the admin panel").

Its limit is exactly its strength: roles are **coarse**. The moment requirements depend on *the specific object* or *context* — "editors can edit **their own** documents," "refunds allowed only **during business hours**," "read access **only to your own department's** records" — a role can't express it, and teams respond by minting ever-more-specific roles (`editor_of_team_A_confidential`), which is **role explosion**. When your rules mention attributes of the resource or the relationship between subject and object, you've outgrown pure RBAC.

### ABAC and ReBAC: attributes and relationships

Two models pick up where RBAC stops, and modern systems increasingly use them alongside it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" role="img" aria-label="Three authorization models. RBAC: a user has roles, roles have permissions; you check if any role grants the permission — simple and coarse. ABAC: a policy is a boolean expression over attributes of the subject, resource, action, and context, for example allow if subject.department equals resource.department and the time is business hours — fine-grained and context-aware. ReBAC: relationships form a graph, for example user alice is a member of group eng which is an editor of doc 42, and the question 'is alice an editor of doc 42' is answered by finding a path — this is the Google Zanzibar model for fine-grained, scalable authorization.">
  <defs>
    <marker id="l9m-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="22" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three models — roles, attributes, relationships</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="284" height="284" rx="12" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="308" y="42" width="284" height="284" rx="12" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.8"/>
    <rect x="600" y="42" width="284" height="284" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="158" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">RBAC · roles</text>
    <text x="158" y="112" font-size="10" text-anchor="middle">Alice</text>
    <text x="158" y="160" font-size="10" text-anchor="middle">role: Editor</text>
    <text x="158" y="208" font-size="9" text-anchor="middle">perms: {doc.read,</text>
    <text x="158" y="222" font-size="9" text-anchor="middle">doc.write}</text>
    <text x="158" y="272" font-size="8.5" text-anchor="middle" opacity="0.78">simple, fast, COARSE</text>
    <text x="158" y="290" font-size="8.5" text-anchor="middle" opacity="0.78">"can't say WHOSE doc"</text>
    <text x="158" y="308" font-size="8" text-anchor="middle" opacity="0.6">→ role explosion at the edges</text>

    <text x="450" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">ABAC · attributes</text>
    <text x="450" y="104" font-size="9" text-anchor="middle">allow if</text>
    <text x="450" y="126" font-size="8.5" text-anchor="middle">subject.dept ==</text>
    <text x="450" y="140" font-size="8.5" text-anchor="middle">resource.dept</text>
    <text x="450" y="162" font-size="8.5" text-anchor="middle">AND action in resource.allowed</text>
    <text x="450" y="184" font-size="8.5" text-anchor="middle">AND ctx.time in business_hours</text>
    <text x="450" y="272" font-size="8.5" text-anchor="middle" opacity="0.78">fine-grained, CONTEXT-aware</text>
    <text x="450" y="290" font-size="8.5" text-anchor="middle" opacity="0.78">policy = boolean over attributes</text>
    <text x="450" y="308" font-size="8" text-anchor="middle" opacity="0.6">→ can get hard to reason about</text>

    <text x="742" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">ReBAC · relationships</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" font-size="9">
    <g fill="none" stroke="#0fa07f" stroke-width="1.5">
      <path d="M690 108 L 690 150" marker-end="url(#l9m-ar)"/>
      <path d="M690 176 L 690 218" marker-end="url(#l9m-ar)"/>
    </g>
    <text x="742" y="104" text-anchor="middle">user:alice</text>
    <text x="700" y="132" text-anchor="start" opacity="0.7">member</text>
    <text x="742" y="172" text-anchor="middle">group:eng</text>
    <text x="700" y="200" text-anchor="start" opacity="0.7">editor</text>
    <text x="742" y="240" text-anchor="middle">doc:42</text>
    <text x="742" y="272" text-anchor="middle" opacity="0.78">"alice editor of doc:42?"</text>
    <text x="742" y="288" text-anchor="middle" opacity="0.78">= find a PATH in the graph</text>
    <text x="742" y="306" text-anchor="middle" opacity="0.6">→ Google Zanzibar / OpenFGA</text>
  </g>
</svg>
```

**ABAC** (Attribute-Based Access Control) makes the decision a **boolean expression over attributes** — of the subject (`department`, `clearance`), the resource (`owner`, `sensitivity`), the action, and the context (`time`, `ip`, `mfa_present`). A policy like *allow if `subject.department == resource.department` and it's business hours* expresses rules RBAC can't, and it's how you get context-aware and fine-grained control. The cost is complexity: a tangle of attribute rules can become hard to reason about and audit ("is there any combination that grants access I didn't intend?").

**ReBAC** (Relationship-Based Access Control) models permissions as a **graph of relationships** and answers a request by finding a path: *alice is a `member` of `group:eng`, which is an `editor` of `doc:42`, therefore alice can edit `doc:42`.* This is exactly how you naturally describe sharing ("owner," "shared with," "member of the parent folder"), and it's the model **Google's Zanzibar** paper (2019) introduced to authorize Docs, Drive, YouTube, and Calendar at planetary scale. Its open implementations — **OpenFGA**, **SpiceDB**, **Ory Keto** — are one of the biggest current shifts in authorization, because ReBAC elegantly handles the hierarchical, shared-object permissions (folders, groups, org charts) that make RBAC and ABAC awkward. Most real systems end up **combining** models: RBAC for coarse role gates, ABAC for contextual conditions, ReBAC for object sharing and hierarchy.

### The enforcement discipline: where the IDOR is prevented

Choosing a model is half the job; the other half is enforcing it so the check is never skipped, which is where broken access control actually happens. The failure has a precise shape — checking the **route** but not the **object**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="100%" style="max-width:880px" role="img" aria-label="Route-level versus object-level authorization. A request GET /documents/42 from alice passes the route-level check because alice is a logged-in editor allowed to call the endpoint. But the object-level check asks whether alice may access document 42 specifically, and document 42 is owned by bob, so it must be denied. Checking only the route while forgetting the object is the IDOR / broken object-level authorization bug. The rule: authorize the object, not just the route, on every access, deny by default.">
  <defs>
    <marker id="l9e-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Authorize the OBJECT, not just the route — this is where the IDOR lives</text>
  <text x="450" y="54" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12" fill="currentColor">alice (logged-in editor) →  GET /documents/42</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="80" y="82" width="330" height="120" rx="11" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="490" y="82" width="330" height="120" rx="11" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
    </g>
    <text x="245" y="106" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">① ROUTE-LEVEL CHECK</text>
    <text x="245" y="130" font-size="9.5" text-anchor="middle" fill="currentColor">"may alice call GET /documents/:id?"</text>
    <text x="245" y="150" font-size="9.5" text-anchor="middle" fill="currentColor">she's a logged-in editor → YES</text>
    <text x="245" y="178" font-size="9" text-anchor="middle" fill="#0fa07f">passes ✓ (necessary, not sufficient)</text>

    <text x="655" y="106" font-size="11.5" font-weight="700" text-anchor="middle" fill="#d64545">② OBJECT-LEVEL CHECK</text>
    <text x="655" y="130" font-size="9.5" text-anchor="middle" fill="currentColor">"may alice access document 42?"</text>
    <text x="655" y="150" font-size="9.5" text-anchor="middle" fill="currentColor">doc 42 owner = bob → NO</text>
    <text x="655" y="178" font-size="9" text-anchor="middle" fill="#d64545">MUST deny → 403 (often skipped = IDOR)</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M410 142 L 486 142" marker-end="url(#l9e-ar)"/>
  </g>
  <text x="450" y="240" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.92" font-weight="700">Passing the route check but skipping the object check is Broken Object-Level Authorization — OWASP API #1.</text>
  <text x="450" y="264" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.88">Enforce on the server (never trust a client-supplied role or owner), at every access (complete mediation),</text>
  <text x="450" y="282" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.88">deny by default, and check the specific object — not just that the user is "an editor."</text>
</svg>
```

Four enforcement rules turn a model into a secure system. **Deny by default** — no matching allow means denied. **Check every access** (complete mediation) — not once at load and then trusted; every read and write re-checks. **Enforce on the server** — never trust a role, owner, or permission the client sent; recompute from server-side state (the client controls its own request, [Lesson 1](../01-authn-authz-and-the-security-mindset/)). And **authorize the object, not just the route** — passing "may this user call this endpoint" is necessary but not sufficient; you must also check "may this user act on *this* object," which is precisely the check whose absence is the IDOR.

## Build It

Standard library only — dicts, sets, and a small graph — to implement all three models behind one `can(subject, action, resource)` interface, then show the object-level check that stops the IDOR and the deny-by-default that stops everything unspecified.

RBAC is a two-hop lookup; ABAC is a policy function over attributes; ReBAC is a graph walk:

```python
# RBAC — users -> roles -> permissions
def rbac_can(user, perm, *, user_roles, role_perms) -> bool:
    return any(perm in role_perms.get(r, set()) for r in user_roles.get(user, set()))

# ABAC — a policy is a predicate over attributes of subject/resource/action/context
def abac_can(subject, action, resource, ctx) -> bool:
    return (subject["dept"] == resource["dept"]                 # same department
            and action in resource["allowed_actions"]
            and 9 <= ctx["hour"] < 18)                          # business hours only

# ReBAC — relationship tuples form a graph; "can" = is there a path with the right relations
def rebac_can(user, relation, obj, tuples) -> bool:
    # tuples: set of (object, relation, subject) e.g. ("doc:42","editor","group:eng")
    #         and ("group:eng","member","user:alice")
    def reaches(target_rel, target_obj, principal, seen=frozenset()):
        for (o, rel, s) in tuples:
            if o != target_obj:
                continue
            if s == principal and rel == target_rel:
                return True
            # userset rewrite: editor of a group's members; a group can be an editor
            if s.startswith("group:") and (s, "member", principal) in tuples and rel == target_rel:
                return True
        return False
    return reaches(relation, obj, user)
```

The full script — RBAC, an ABAC policy, a small ReBAC graph with group-membership rewrite, the object-level IDOR check, and deny-by-default — is in [`code/authorization.py`](code/authorization.py). Run it:

```console
$ python3 authorization.py
== 1 · RBAC: ROLES GROUP PERMISSIONS ==
  alice roles={editor}  can doc.write? True   can billing.refund? False
  carol roles={billing} can billing.refund? True   can doc.write? False

== 2 · ABAC: A POLICY OVER ATTRIBUTES (context-aware) ==
  eng user, eng doc, 11:00  read -> allow
  eng user, eng doc, 22:00  read -> deny   (outside business hours)
  eng user, sales doc, 11:00 read -> deny  (different department)

== 3 · ReBAC: RELATIONSHIPS AS A GRAPH (Zanzibar-style) ==
  tuples: doc:42 editor group:eng ; group:eng member user:alice
  alice editor of doc:42?  True    (via group membership)
  bob   editor of doc:42?  False   (no relationship path)

== 4 · OBJECT-LEVEL CHECK STOPS THE IDOR ==
  alice is a valid editor (route check passes)
  GET /documents/42 (owner=bob) -> 403 forbidden   ✓ object check denies
  GET /documents/7  (owner=alice) -> 200 ok

== 5 · DENY BY DEFAULT ==
  unknown action 'doc.publish' with no matching policy -> deny   ✓
```

**Sections 1–3** show the same question answered three ways: a role lookup, an attribute policy that denies at 22:00 and across departments, and a graph walk that grants alice access *through her group* while denying bob who has no path. **Section 4** is the whole lesson's point — alice passes the route check (she's an editor) but is denied document 42 because she doesn't own it, and *is* allowed document 7 because she does; that object-level check is the IDOR fix. **Section 5** shows deny-by-default catching an action no policy mentions.

## Use It

For coarse RBAC, frameworks and libraries have you covered — Django's permissions, Spring Security's roles, or **Casbin** (Python/Go/Node), which implements RBAC and ABAC from a policy file. But the strategic move in modern systems is to **externalize the decision into a policy engine**, so authorization logic lives in one auditable place instead of scattered across services — the PEP/PDP split made real:

- **OPA** (Open Policy Agent) with its **Rego** language is the CNCF-standard general policy engine: your service sends `(subject, action, resource, context)` as JSON and OPA returns allow/deny from centrally-managed policy. Great for ABAC and RBAC across many services.
- **Cedar** (AWS, behind Amazon Verified Permissions) is a purpose-built authorization language with readable policies and analyzability — you can *prove* properties about who can access what.
- **OpenFGA** / **SpiceDB** / **Ory Keto** are open-source **Zanzibar** implementations for **ReBAC**: you write relationship tuples and a schema, and ask `check(user, relation, object)` — the right tool for sharing, folders, groups, and org hierarchies.

A minimal ReBAC model reads almost like the graph you built — for example, in OpenFGA's schema, `define viewer: [user] or editor` says "an editor is also a viewer," and `define editor: [user] or member from parent` says "editing a folder cascades to its documents." The rules that carry across every tool: **deny by default**, **check on every access at the object level** (this alone prevents the most common serious API vulnerability), **enforce on the server from trusted state**, **centralize the decision** so it's auditable and changeable, and **log authorization decisions** so you can answer "who accessed X, and were they allowed?" after the fact. Pick RBAC for simple role gates, add ABAC when context and attributes matter, and reach for ReBAC (Zanzibar) when your permissions are really about relationships between users and objects — and expect to combine them.

## Think about it

1. The handler in *The Problem* checks `user.role in {"admin","editor"}` and then returns `db.documents.get(doc_id)`. Write, in words, the exact additional check it needs, and explain why the role check alone is not just insufficient but *misleading* about what's protected.
2. Your company keeps adding roles: `editor`, `editor_contractor`, `editor_contractor_non_confidential`, `editor_eu_only`. Name the anti-pattern, diagnose which model would express these rules more cleanly, and give the policy for one of them in that model.
3. RBAC, ABAC, and ReBAC can each answer "can alice edit doc 42?" For a document-sharing product (owners, "shared with," folders that grant access to everything inside), argue which model fits best and why the other two get awkward.
4. Why is it a security requirement to make the authorization decision from *server-side* state rather than from claims in the request (even a signed JWT that says `role: admin`)? Give a scenario where trusting the token's role is exactly wrong.
5. "Deny by default" and "check every access" sound obvious, yet broken access control is the #1 web/API vulnerability. Give two concrete reasons these fail in real codebases despite everyone agreeing with them, and one structural change (not more discipline) that helps.

## Key takeaways

- **Authorization is a decision** — `(subject, action, resource, context) → allow | deny` — and the key structural move is to **separate enforcement (PEP) from the decision (PDP)**, so the logic is centralized, auditable, changeable, and applied at one choke point every request passes through. The default is always **deny**.
- **RBAC** groups permissions under **roles** — simple, fast, the right default for coarse access — but roles are coarse, so object- and context-specific rules cause **role explosion**.
- **ABAC** makes the decision a **boolean over attributes** (subject, resource, action, context), giving fine-grained, context-aware control (department, time, sensitivity) at the cost of complexity.
- **ReBAC** models permissions as a **graph of relationships** and answers by finding a path (`alice → member → group → editor → doc`). It's the **Google Zanzibar** model (OpenFGA, SpiceDB) and the natural fit for sharing, folders, groups, and hierarchies. Real systems **combine** all three.
- **The IDOR lives in enforcement, not the model.** Checking the **route** ("may you call this endpoint") is necessary but not sufficient; you must **authorize the object** ("may you act on *this* record"). Skipping it is Broken Object-Level Authorization — the top API vulnerability.
- **Enforcement discipline:** deny by default, **check every access** (complete mediation), **enforce on the server** from trusted state (never a client-supplied role/owner), and **externalize + log** decisions (OPA/Rego, Cedar, OpenFGA) so authorization is one auditable place, not scattered `if` statements.

Next: [The Browser Trust Boundary: CORS, CSRF & XSS](../10-browser-trust-boundary-cors-csrf-xss/) — you now know who the caller is and what they may do; next you defend the one client you can't control, the browser, whose habit of automatically attaching cookies and running any script on your page creates a class of attacks your server has to actively defend against.
