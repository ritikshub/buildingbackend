---
name: checklist-plan-review-and-state-hygiene
description: Approve an infrastructure plan without deleting a database — how to read the four verbs and the destroy count, the guards that stop a cascade, state backend and locking rules, environment blast radius, scheduled drift detection, and the secrets that live in state whatever you marked sensitive.
phase: 10
lesson: 06
---

# Reviewing a plan & owning the state — pre-apply checklist

Sections 1 and 2 run on every change. Sections 3–7 are set-up you do once per repository
and per environment, and re-check whenever someone joins or an environment is added.
Every item exists because skipping it has caused a real outage.

Keep the model in front of you: **three states, not two.** Desired (your declaration),
recorded (the state file), actual (the cloud). The state file is a **cache of reality**,
and every strange story in this field is that cache being wrong.

## 1 · Before you generate a plan

- [ ] Every resource id is written as a **reference**, never a pasted literal.
      `subnet_id = aws_subnet.app_a.id` is simultaneously the value, the dependency edge,
      and the reason a replacement propagates correctly. A pasted `"subnet-0a1b2c"` deletes
      the edge and the ordering guarantee with it — the tool will happily try to create the
      server before the subnet exists.
- [ ] A resource **rename** is accompanied by a `moved` block. Renaming a block changes its
      address, and the tool reads that as "the old one is gone, a new one is wanted" —
      destroy plus create. A `moved` block rewrites the mapping and produces a plan with no
      changes at all. This is the single most common way a refactor destroys a database.
- [ ] Adopting an existing resource uses `import`, and the plan after the import is read
      carefully: if the declaration does not exactly match imported reality, the first apply
      is a modification, and occasionally a replacement.
- [ ] `ignore_changes` is used only where **another system legitimately owns** the attribute
      (an autoscaler owning `desired_capacity`, a deploy pipeline owning the image). Used to
      silence a drift you do not want to think about, it converts drift from something you
      can detect into something you have chosen not to see.
- [ ] The plan is written to a **file** (`plan -out=tfplan`) and the apply consumes that
      file. A bare `apply` computes a *new* plan at apply time, which may differ from the one
      your colleague reviewed ten minutes ago. The reviewed artifact and the executed
      artifact must be the same bytes.

## 2 · Reading the plan — in this order

The plan output **is** the review artifact. Post it on the pull request. The reviewer's
job is not "does this code look right" but "is this list of operations the list we
intended".

```text
+   create           new object, new id            data: none to lose
~   update in place  mutable attribute changed     data: SURVIVES, id unchanged
-/+ replace          IMMUTABLE attribute changed   data: GONE, new id
-   destroy          in state, not in declaration  data: GONE
```

- [ ] **Read the destroy count first.** `Plan: 6 to add, 1 to change, 6 to destroy` on a
      seven-resource stack is not six new things — a replace counts once in each column, so
      that is a full rebuild.
- [ ] **Read every `# forces replacement` line.** That comment names the immutable attribute
      that turned an edit into a destroy. It is the one line that distinguishes a rename
      from a resize from a rebuild.
- [ ] **Treat `(known after apply)` as a change, not as decoration.** It means the value does
      not exist yet, so any attribute consuming it is by definition changing — and if that
      attribute is immutable you have just been recruited into the cascade.
- [ ] **Trace the cascade to its end.** A replacement propagates through every immutable
      reference and stops only at a **mutable** attribute. Measured here: one edit to the
      network's CIDR replaced 6 of 7 resources, and 5 of them were edited by nobody; the load
      balancer escaped only because its target list is mutable and could absorb the new ids
      as a single update.
- [ ] **Check whether any stateful resource is in the destroy or replace list.** Databases,
      object stores, disks, anything holding data anyone would miss. Any non-zero destroy
      count on a stateful resource requires a second approver, in writing.
- [ ] **Check the diff line count against the change you intended.** A one-line
      configuration diff producing a sixty-line plan is the exact shape of scene two.
- [ ] Confirm the plan you are approving refreshed against **the environment you think it
      did**. A mis-set workspace or a stale `AWS_PROFILE` points production credentials at a
      staging intention.

## 3 · Guards, in the order you reach for them

- [ ] **`prevent_destroy` on every stateful resource.** Databases, buckets, volumes,
      snapshots. It refuses the plan **as a whole** — not partially, not the rest of it —
      which is deliberate: letting five replacements through and skipping only the database
      leaves servers in a network that no longer exists. Measured: with the guard on, the
      6-of-7 cascade applied *nothing*, and the 100 GB database was still `db-18b8ff`
      afterwards.
- [ ] Removing a `prevent_destroy` is **itself a reviewed change**, with the reason in the
      commit message.
- [ ] **`create_before_destroy` on anything that serves traffic.** It flips a replacement's
      order — build the new object, repoint references, then remove the old — cutting a
      modelled zero-capacity window from ~25 s to 0 s. Know the price: both objects exist at
      once (double capacity for the duration) and it fails outright if any immutable
      attribute must be globally unique.
- [ ] **Policy as code reads the plan before a human does.** `terraform show -json` into
      conftest/OPA, Sentinel or Checkov, with a rule like "no plan may destroy an
      `aws_db_instance` without an approved exception". A machine never gets tired on line 34
      of 60.
- [ ] No `apply -auto-approve` on a path that can reach production without a policy gate in
      front of it.

## 4 · The state backend

Non-negotiable above one person.

- [ ] **Remote.** On a laptop the state file is invisible to everyone else and one disk
      failure from gone — and the cloud keeps running, unmanaged, with no way to rebuild the
      mapping.
- [ ] **Locking on.** Without it two applies that start seconds apart both read serial 41,
      both work, and both write serial 42; the second write erases the first's records and
      those resources are alive, billed, and referenced by no state file anywhere. **A remote
      backend without locking is more dangerous than a local state file**, because it invites
      the concurrency it cannot survive.
- [ ] **Object versioning on.** A corrupted or truncated write is recoverable if you can
      fetch the previous version and unrecoverable if you cannot.
- [ ] **Encrypted at rest, access-controlled like a password vault** (see section 7 for why).
- [ ] **Never committed.** Add it to `.gitignore` on the day you create the repository.
- [ ] **Never hand-edited.** Use `state mv`, `moved`, `import`, `state rm`. Hand-editing
      corrupts the mapping, and the corruption surfaces one apply later as an offer to
      recreate something that already exists.

## 5 · Environments and blast radius

- [ ] **One state file per environment, minimum.** If staging and production share state, a
      plan for one can propose changes to the other and every mistake is bought twice.
- [ ] **Split by rate of change as well.** The network that changes twice a year does not
      belong in the same state as the service that ships daily — a routine service change
      should never be able to produce a plan that touches the network.
- [ ] **Prefer separate directories to workspaces.** `envs/prod/` and `envs/staging/`, each
      a small root module calling shared modules, gives separate backends, separate
      credentials, and a diff between two files that says exactly how the environments
      differ. Workspaces diverge through `terraform.workspace` conditionals scattered
      through the configuration, and a mis-set workspace aims production credentials at a
      staging plan. Use workspaces for short-lived identical copies, which is what they are
      good at.
- [ ] **Modules, not copy-paste.** Three environments as three copies of the same 400 lines
      drift apart at three different rates.
- [ ] Provider versions are pinned (`~> 5.0`) so a provider release cannot change a plan you
      did not change.

## 6 · Drift

- [ ] **Nobody clicks in the console.** Read-only access for everyone, break-glass
      credentials that page when used, and every use followed by importing or reverting what
      was done. This is a social rule enforced with permissions, not a preference.
- [ ] **Drift detection runs on a schedule**, per environment, routed to the owning team:
      `terraform plan -refresh-only -detailed-exitcode` (exit 2 means drift). Nightly.
      Drift found within a day is a conversation; drift found after six months is an
      archaeology project, and it will be found by an unrelated apply at the worst moment.
- [ ] Every drift finding gets an explicit decision, recorded:
  - [ ] **Re-assert the declaration** — the default, and usually right. But understand that
        re-asserting can mean *replacing*: in this lesson the plan correcting four console
        edits also proposed to destroy a healthy, untouched `server.api_2`, because the
        subnet under it was coming back with a new id and `subnet_id` is immutable.
  - [ ] **Adopt reality** — the 02:40 change was correct. Put it in the declaration, in a
        pull request, with the reason in the commit message. Now it is reviewed after the
        fact instead of never.
  - [ ] What you must not do is leave it. Undetected drift compounds until someone inherits
        every accumulated correction at once.
- [ ] **Unmanaged resources are invisible, not safe.** A hand-made resource appears in no
      plan: not corrected, not deleted, not reported — just billed, and confusing to the next
      person. Reconcile the account against state periodically and `import` or delete what
      you find.
- [ ] Note that a failed apply is a drift source too: the run died halfway, some resources
      moved, some did not, and state may or may not have caught up. Re-plan before assuming
      anything.

## 7 · Secrets in state

- [ ] Everyone knows that **`sensitive = true` hides a value from CLI output and does not
      remove it from state.** Neither does anything else. The tool records every attribute of
      every resource as applied, because that is how it knows what changed — so a password
      passed to a resource is a password in the state file, in plaintext, permanently, in
      every historical version the backend has kept.
- [ ] **Best fix: the secret never enters state.** Store it in a secrets manager, put only
      the *reference* (an ARN, a path) in the configuration, and have the application fetch
      the value at runtime.
- [ ] The backend is encrypted, access-logged, and read-restricted to the people you would
      give a production password to.
- [ ] Anything that has ever passed through a state file that sat on a laptop, in a CI log,
      or in a loosely-permissioned bucket is **rotated**, not merely noted.

## 8 · Anti-patterns to grep for

- [ ] A hard-coded resource id where a reference belongs.
- [ ] A renamed resource block with no `moved` block in the same commit.
- [ ] `apply` with no `-out` plan file, or `-auto-approve` on a production path.
- [ ] A stateful resource with no `prevent_destroy`.
- [ ] `ignore_changes` on an attribute no other system owns.
- [ ] A remote backend block with no locking configured.
- [ ] `terraform.tfstate` tracked in git.
- [ ] One state file covering more than one environment.
- [ ] A `terraform.workspace` conditional deciding something load-bearing (instance counts,
      retention, replication).
- [ ] Any resource whose creation is documented only in a wiki page, a shell script, or
      somebody's memory. That is click-ops, and its defining property is not that it is
      manual — it is that **the system has no model of itself**, so there is nothing to
      review, nothing to diff, and no way to know what is load-bearing.

> ## Decision shortcuts
>
> **"Is this plan an edit or a rebuild?"** Look at the destroy count, not the line count.
> Non-zero destroy on anything stateful → stop and get a second reader.
>
> **"Why is this resource in the plan? I didn't touch it."** Follow its
> `(known after apply)` back up the graph. The cascade always has an origin, and it is
> always a single immutable attribute someone did edit.
>
> **"Would I be able to rebuild this environment if the state file vanished tonight?"**
> No → the state file is a production dependency and should be backed by the same care as
> a database.
>
> **"Where did this value come from — my code, the state file, or a human at 02:40?"**
> If you cannot tell in under a minute, you are not running drift detection.
