# API Versioning Strategies

> A version is a promise to code you can't see or update. The best versioning strategy is the one that lets you almost never bump the version.

**Type:** Learn
**Languages:** —
**Prerequisites:** [REST Principles & Resource Modeling](../01-rest-principles-resource-modeling/)
**Time:** ~45 minutes

## The Problem

You version because you'll eventually need a breaking change. But *where* you put
the version (path? header? media type?) has real consequences for caching,
debuggability, and ops — and most teams over-engineer this while under-investing in
the discipline that actually matters: additive, backward-compatible evolution.

## The Concept

### Four mainstream strategies

1. **URI path** — `/v1/orders`. Used by Stripe and Twilio (date-based path segments).
2. **Query parameter** — `?version=2`. Easy to add, easy to forget.
3. **Custom request header** — `Stripe-Version: 2024-06-20`, `X-GitHub-Api-Version:
   2022-11-28` (date-based; omitting it defaults to a pinned date).
4. **Accept media type** — `Accept: application/vnd.github.v3+json`. The "purest"
   HTTP answer (the version selects a representation) and the most awkward to use.

| Strategy | Visible in logs | Cacheable by default | Ergonomics |
|---|---|---|---|
| URI path `/v1/` | Yes — greppable | Yes (distinct URLs) | Excellent; works in a browser |
| Query `?version=` | Easy to omit | Mostly | Defaults are footguns |
| Custom header | No | Needs `Vary` | Header plumbing everywhere |
| Accept media type | No | Needs `Vary: Accept` | Worst — verbose, fiddly |

**Pragmatic recommendation:** put a coarse major version in the **path** (`/v1/`),
plan to *never* increment it, and absorb evolution through additive changes. URL
versions are debuggable (a pasted URL in a bug report tells you everything), route
cleanly at the gateway, and cache with zero `Vary` gymnastics. Stripe-style date
headers are superb *if* you'll build the machinery (internal transforms between
adjacent versions so old pinned clients keep working). Most teams aren't Stripe —
one `/v1/` plus discipline beats an elaborate scheme nobody maintains. Version the
*whole surface*, not individual endpoints.

### Backward compatibility: what "breaking" means

The rules follow from one question: *can a client built yesterday still work today?*

| Change | Breaking? |
|---|---|
| Add a new optional field to a response | No (if clients read tolerantly) |
| Add a new optional request param/field | No |
| Add a new endpoint | No |
| Add a new value to a response enum | **Gray zone** — breaks clients that switch exhaustively |
| Remove or rename a field | **Yes** |
| Change a field's type or meaning/units | **Yes** |
| Make an optional request field required | **Yes** |
| Tighten validation | **Yes** |
| Change a success code, error `code`, or default sort order | **Yes** |

**Additive-only evolution.** Within a version, only add: new optional fields, new
endpoints, new enum members (declared as open sets from day one). Everything on the
"yes" list waits for `/v2/` — which you should almost never need.

**Never repurpose a field.** If `discount` meant "percent" and you now need "minor
units," don't change the meaning in place — clients can't detect a semantic change,
the payload still parses, and it surfaces as silently wrong prices. Add
`discount_amount`, deprecate `discount`, serve both.

**Tolerant readers** (Postel's law): clients must ignore unknown response fields, so
servers can add fields freely. A client model set to `extra="forbid"` turns every
harmless server addition into an outage.

### Deprecation flow

1. **Announce** in docs/changelog with a migration path and date.
2. **Signal on the wire**: the `Deprecation` header (RFC 9745) and `Sunset` header
   (RFC 8594) so telemetry-driven consumers notice.
3. **Measure** usage of the deprecated surface per consumer.
4. **Nudge** stragglers directly.
5. **Remove** only at a major-version boundary, after the sunset date, when usage is
   ~zero. Until then, removal is an outage you chose to inflict.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 770" width="100%" style="max-width:880px" role="img" aria-label="The five-step deprecation flow, drawn as a cycle rather than a countdown. Step 1, announce the deprecation in docs and changelog with a migration path and a date. Step 2, signal it on the wire: every response from the deprecated surface carries Deprecation: true, defined by RFC 9745, and Sunset: Sat, 31 Oct 2026 23:59:59 GMT, defined by RFC 8594, so a well-behaved client and your own dashboards can see the clock ticking before anything breaks. Steps 3 and 4 sit inside a dashed repeating loop: step 3 measures usage of the deprecated surface broken down per consumer, and step 4 nudges the stragglers directly, using the names the telemetry gave you. The loop then reaches a decision diamond asking whether usage is near zero AND the sunset date has passed, both conditions, never either one alone. On the no branch the arrow travels back around to step 3 and the loop runs again. On the yes branch the arrow leaves the loop to step 5, remove, and only at a major-version boundary from v1 to v2. A side panel warns that removing before both conditions hold is not a deprecation but an outage you chose to inflict: the sunset date alone is not permission, usage near zero is. A band at the bottom gives the discipline that means you almost never run this flow at all: put one coarse major version in the path and plan never to increment it; evolve additively with new optional fields, new endpoints and new enum members declared as open sets from day one; never repurpose a field, since changing what discount means from percent to minor units still parses and surfaces as silently wrong prices, so add discount_amount and deprecate discount instead; and write tolerant readers, because a client model set to extra forbid turns every harmless server addition into an outage.">
  <defs>
    <marker id="p2l05a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l05a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p2l05a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The deprecation loop: you remove when the telemetry says so, not when the calendar does</text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.9">
      <rect x="110" y="44" width="340" height="52" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="110" y="122" width="340" height="54" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="560" y="98" width="320" height="118" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.75"/>
      <rect x="560" y="228" width="320" height="100" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-opacity="0.8"/>
      <rect x="560" y="344" width="320" height="100" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.8"/>
      <rect x="20" y="212" width="520" height="254" rx="14" fill="#e0930f" fill-opacity="0.05" stroke="#e0930f" stroke-opacity="0.85" stroke-width="2" stroke-dasharray="7 6"/>
      <rect x="44" y="248" width="214" height="74" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
      <rect x="302" y="248" width="214" height="74" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
      <path d="M280 340 L420 388 L280 436 L140 388 Z" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="90" y="494" width="380" height="52" rx="10" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>

    <g fill="none" stroke-width="1.6">
      <circle cx="132" cy="70" r="10" stroke="#e0930f"/>
      <circle cx="132" cy="149" r="10" stroke="#e0930f"/>
      <circle cx="66" cy="272" r="9.5" stroke="#e0930f"/>
      <circle cx="324" cy="272" r="9.5" stroke="#e0930f"/>
      <circle cx="112" cy="520" r="10" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700">
      <text x="132" y="73.5" fill="#e0930f">1</text>
      <text x="132" y="152.5" fill="#e0930f">2</text>
      <text x="66" y="275.5" fill="#e0930f">3</text>
      <text x="324" y="275.5" fill="#e0930f">4</text>
      <text x="112" y="523.5" fill="#0fa07f">5</text>
    </g>

    <text x="152" y="64" font-size="12" font-weight="700" fill="#e0930f">ANNOUNCE</text>
    <text x="152" y="82" font-size="9" fill="currentColor">in docs + changelog, with a migration path and a date</text>

    <text x="152" y="144" font-size="12" font-weight="700" fill="#e0930f">SIGNAL ON THE WIRE</text>
    <text x="152" y="162" font-size="9" fill="currentColor">Deprecation + Sunset headers on the response</text>

    <text x="574" y="120" font-size="8.5" fill="currentColor" opacity="0.8">what every response from the old surface carries</text>
    <text x="574" y="144" font-size="11" font-weight="700" fill="#e0930f">Deprecation: true</text>
    <text x="868" y="144" font-size="7.5" text-anchor="end" fill="currentColor" opacity="0.65">RFC 9745</text>
    <text x="574" y="166" font-size="9.5" font-weight="700" fill="#e0930f">Sunset: Sat, 31 Oct 2026 23:59:59 GMT</text>
    <text x="868" y="166" font-size="7.5" text-anchor="end" fill="currentColor" opacity="0.65">RFC 8594</text>
    <text x="574" y="184" font-size="8.5" fill="currentColor" opacity="0.85">a well-behaved client — and your own</text>
    <text x="574" y="197" font-size="8.5" fill="currentColor" opacity="0.85">dashboards — see the clock ticking here,</text>
    <text x="574" y="210" font-size="8.5" fill="currentColor" opacity="0.85">long before anything breaks</text>

    <text x="574" y="250" font-size="10.5" font-weight="700" fill="#3553ff">3 · WHAT YOU ACTUALLY MEASURE</text>
    <text x="574" y="270" font-size="8.5" fill="currentColor">calls to the deprecated surface, counted</text>
    <text x="574" y="284" font-size="8.5" fill="currentColor">per consumer — that list IS the list of</text>
    <text x="574" y="298" font-size="8.5" fill="currentColor">people to nudge in step 4, and the</text>
    <text x="574" y="312" font-size="8.5" fill="currentColor">number that has to reach ~0 to exit.</text>

    <text x="574" y="366" font-size="10.5" font-weight="700" fill="#d64545">REMOVE BEFORE BOTH ARE TRUE</text>
    <text x="574" y="386" font-size="8.5" fill="currentColor">and you did not ship a deprecation —</text>
    <text x="574" y="400" font-size="8.5" fill="currentColor">you shipped an outage you chose to</text>
    <text x="574" y="414" font-size="8.5" fill="currentColor">inflict. The sunset date alone is not</text>
    <text x="574" y="428" font-size="8.5" fill="currentColor">permission to delete; usage ~0 is.</text>

    <text x="524" y="234" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">REPEAT UNTIL THE TELEMETRY SAYS SO — NOT THE CALENDAR</text>

    <text x="84" y="276" font-size="11.5" font-weight="700" fill="#e0930f">MEASURE</text>
    <text x="60" y="296" font-size="8.5" fill="currentColor">usage of the deprecated surface</text>
    <text x="60" y="310" font-size="8.5" fill="currentColor">broken down per <tspan fill="#3553ff" font-weight="700">consumer</tspan></text>

    <text x="342" y="276" font-size="11.5" font-weight="700" fill="#e0930f">NUDGE</text>
    <text x="318" y="296" font-size="8.5" fill="currentColor">contact the stragglers directly —</text>
    <text x="318" y="310" font-size="8.5" fill="currentColor">the names the telemetry gave you</text>

    <text x="280" y="380" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">usage ~0</text>
    <text x="280" y="398" font-size="9.5" text-anchor="middle" fill="currentColor">AND past the sunset date?</text>
    <text x="280" y="416" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.8">both — not either</text>

    <text x="132" y="514" font-size="12" font-weight="700" fill="#0fa07f">REMOVE</text>
    <text x="132" y="532" font-size="9" fill="currentColor">only at a major-version boundary: <tspan fill="#7c5cff" font-weight="700">/v1/ → /v2/</tspan></text>

    <g fill="none" stroke="#e0930f" stroke-width="1.8" stroke-linejoin="round">
      <path d="M280 96 L280 118" marker-end="url(#p2l05a-arm)"/>
      <path d="M450 150 L556 150" marker-end="url(#p2l05a-arm)"/>
      <path d="M280 176 L280 196 L151 196 L151 244" marker-end="url(#p2l05a-arm)"/>
      <path d="M258 285 L298 285" marker-end="url(#p2l05a-arm)"/>
      <path d="M409 322 L409 381" marker-end="url(#p2l05a-arm)"/>
      <path d="M140 388 L90 388 L90 326" marker-end="url(#p2l05a-arm)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M280 436 L280 490" marker-end="url(#p2l05a-arg)"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.3" stroke-dasharray="4 4" stroke-opacity="0.65">
      <path d="M424 388 L556 388"/>
    </g>

    <text x="503" y="143" font-size="8" text-anchor="middle" fill="#e0930f">on every response</text>
    <text x="114" y="380" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">no</text>
    <text x="114" y="404" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.8">still in use</text>
    <text x="298" y="452" font-size="9.5" font-weight="700" fill="#0fa07f">yes</text>
    <text x="298" y="482" font-size="8" fill="currentColor" opacity="0.8">both are true</text>

    <text x="450" y="570" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">The discipline underneath: do this well and you almost never have to run the flow above.</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="20" y="584" width="206" height="132" rx="9" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-opacity="0.8"/>
      <rect x="238" y="584" width="206" height="132" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-opacity="0.8"/>
      <rect x="456" y="584" width="206" height="132" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.8"/>
      <rect x="674" y="584" width="206" height="132" rx="9" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-opacity="0.8"/>
    </g>

    <g text-anchor="middle">
      <text x="123" y="606" font-size="10" font-weight="700" fill="#7c5cff">COARSE /v1/ IN THE PATH</text>
      <text x="123" y="626" font-size="8.5" fill="currentColor">one major version for the WHOLE</text>
      <text x="123" y="640" font-size="8.5" fill="currentColor">surface, not per endpoint</text>
      <text x="123" y="654" font-size="8.5" fill="currentColor">greppable in logs, cacheable,</text>
      <text x="123" y="668" font-size="8.5" fill="currentColor">no Vary gymnastics</text>
      <text x="123" y="692" font-size="9" font-weight="700" fill="#7c5cff">plan to NEVER increment it</text>

      <text x="341" y="606" font-size="10" font-weight="700" fill="#0fa07f">EVOLVE ADDITIVELY</text>
      <text x="341" y="626" font-size="8.5" fill="currentColor">new optional response fields</text>
      <text x="341" y="640" font-size="8.5" fill="currentColor">new optional request fields</text>
      <text x="341" y="654" font-size="8.5" fill="currentColor">new endpoints</text>
      <text x="341" y="668" font-size="8.5" fill="currentColor">new enum members, declared as</text>
      <text x="341" y="682" font-size="8.5" fill="currentColor">OPEN SETS from day one</text>
      <text x="341" y="704" font-size="9" font-weight="700" fill="#0fa07f">none of these breaks a client</text>

      <text x="559" y="606" font-size="10" font-weight="700" fill="#d64545">NEVER REPURPOSE A FIELD</text>
      <text x="559" y="626" font-size="8.5" fill="currentColor">discount meant "percent"; you</text>
      <text x="559" y="640" font-size="8.5" fill="currentColor">now need "minor units"</text>
      <text x="559" y="654" font-size="8.5" fill="currentColor">add discount_amount and</text>
      <text x="559" y="668" font-size="8.5" fill="currentColor">deprecate discount — serve both</text>
      <text x="559" y="690" font-size="8.5" fill="#d64545">changing meaning in place still</text>
      <text x="559" y="704" font-size="8.5" fill="#d64545">parses → silently wrong prices</text>

      <text x="777" y="606" font-size="10" font-weight="700" fill="#3553ff">TOLERANT READERS</text>
      <text x="777" y="622" font-size="8" fill="currentColor" opacity="0.7">(Postel's law)</text>
      <text x="777" y="642" font-size="8.5" fill="currentColor">a client must IGNORE unknown</text>
      <text x="777" y="656" font-size="8.5" fill="currentColor">response fields — that is what</text>
      <text x="777" y="670" font-size="8.5" fill="currentColor">lets the server add them freely</text>
      <text x="777" y="690" font-size="8.5" fill="#3553ff">a model set to extra="forbid"</text>
      <text x="777" y="704" font-size="8.5" fill="#3553ff">makes every addition an outage</text>
    </g>
  </g>

  <text x="450" y="740" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Steps 3 and 4 are a cycle, not a countdown: every turn re-measures, so the exit is a fact about usage.</text>
  <text x="450" y="758" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">The Deprecation and Sunset headers are what make that fact measurable — the clock is on the wire before anything breaks.</text>
</svg>
```

The loop between *measure* and *nudge* is the whole discipline: you don't remove on a
calendar, you remove when the telemetry says almost nobody is still calling the old
surface. The headers make that measurable — `Deprecation: true` and
`Sunset: Sat, 31 Oct 2026 23:59:59 GMT` on the response let a well-behaved client (and
your own dashboards) see the clock ticking before anything breaks.

## Key takeaways

- Version with a coarse **`/v1/` path** and evolve **additively** so you almost never
  need `/v2/`.
- Header/date schemes (Stripe, GitHub) are excellent but demand serious machinery.
- Additive-only; **never repurpose a field**; clients read **tolerantly**.
- Deprecate with `Deprecation` + `Sunset` headers and usage telemetry before removing.
