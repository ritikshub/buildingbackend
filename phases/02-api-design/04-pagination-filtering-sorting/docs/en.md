# Pagination, Filtering & Sorting

> Never return an unbounded collection. And the offset-vs-cursor choice matters more than any other decision in your collection endpoints.

**Type:** Build
**Languages:** Python
**Prerequisites:** [URLs, Verbs & Status Codes](../02-urls-verbs-status-codes/)
**Time:** ~75 minutes

## The Problem

Every collection endpoint eventually needs filtering, sorting, and paging. There's
no standard — only widely shared conventions — and one wrong default (an unbounded
list, or offset pagination on a hot feed) takes down a mobile client, a serializer,
and your database's memory in one request. Consistency across endpoints is the
feature.

## The Concept

### Query parameter conventions

Apply these **identically on every collection endpoint**:

- **Filtering** — one param per filterable field, named exactly like the response
  field: `GET /orders?status=pending&customer_id=cus_8xkP2m`. Ranges need a
  convention: suffix style (`created_after`/`created_before`) or Stripe's bracket
  style (`created[gte]`). Pick one, document it.
- **Sorting** — a single `sort` param; leading `-` = descending; comma-separated
  tiebreakers: `?sort=-created_at,total_amount`. **Whitelist sortable fields** —
  sorting by an unindexed column is a self-inflicted denial of service.
- **Sparse fieldsets** — `?fields=id,status,total_amount` cuts payload and
  serialization cost.
- **Free-text search** — a `q` param, distinct from exact-match filters. `q` implies
  fuzzy/full-text; filters imply exact predicates. Keeping them separate keeps both
  implementable.

Unknown filter values should **fail loudly (`400`)**, not silently return the
unfiltered collection — a typo like `?staus=pending` returning *everything* is a
classic data-leak shape.

### Pagination: offset vs cursor

**Offset/limit** — a window by position: `?limit=20&offset=40` → `LIMIT 20 OFFSET 40`.

- *Pros:* trivial; supports "jump to page 12" and "showing 41–60 of 1,834"; totals
  come naturally.
- *Cons, and they're structural:* (1) **deep offsets are slow** — `OFFSET 100000`
  forces the DB to produce and discard 100,000 rows before returning 20; cost grows
  linearly with depth. (2) **Unstable under concurrent writes** — offsets address
  *positions*, not rows. An insert at the top shifts everything down: the last row of
  page 1 reappears as the first row of page 2 (duplicate), or a delete makes a row
  silently vanish (skip). For a batch job syncing "all orders," that's data corruption.

**Cursor/keyset** — "rows after this row," identified by the last row's sort-key values:

```sql
-- descending order: fetch rows strictly "before" the cursor row
SELECT * FROM orders
WHERE (created_at, id) < ('2026-07-10T12:00:00Z', 'ord_7hQ2df')
ORDER BY created_at DESC, id DESC
LIMIT 21;   -- one extra row to compute has_more
```

- The sort key **must be unique and immutable** — that's why `id` is appended as a
  tiebreaker; a collision at a page boundary skips or repeats rows.
- The row-value comparison uses a composite index `(created_at DESC, id DESC)` as a
  direct **seek**: constant cost regardless of depth. Page 5,000 costs the same as page 1.
- Fetching `limit + 1` sets `has_more` and mints the next cursor without a count query.
- **Stable under concurrent writes**: the cursor pins a position in *key space*, not
  row-number space.

The cursor is opaque to the client — conventionally base64-encoded JSON of the last
row's sort keys. Response: `{"data": [...], "has_more": true, "next_cursor": "..."}`.
*Cons:* no "jump to page N," no cheap total, and a cursor couples to its sort order
(reject a mismatched one with `400`).

### Decision guide

| Dimension | Offset/limit | Cursor/keyset |
|---|---|---|
| Effort | Trivial | Moderate |
| Deep-page performance | Degrades linearly | Constant |
| Stability under writes | Duplicates/skips | Stable |
| "Jump to page N" / total | Yes | No (or expensive) |
| Best for | Small admin tables | Feeds, syncs, anything large or hot |

**Default to cursor** for anything client-facing or growing; keep offset for small
internal admin lists where "page 3 of 9" is a real requirement. GitHub uses
`page`/`per_page` + a `Link` header; Stripe uses `starting_after` + `has_more`.

## Build It

`code/pagination.py` implements both against the same in-memory collection so you can
watch the difference. Offset re-reads by *position*; cursor seeks by *key*:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 710" width="100%" style="max-width:880px" role="img" aria-label="Offset versus cursor pagination, drawn in two parts. Part one is cost, drawn to scale. The offset query, LIMIT 20 OFFSET 40, makes the database produce and discard rows 1 to 40, a run of forty cells that is twice as long as the twenty cells it finally returns as rows 41 to 60: forty rows of work to return twenty. At OFFSET 100000 it produces and discards 100,000 rows to return 20, so cost grows linearly with depth. The cursor query, WHERE (created_at, id) &lt; :cursor, uses the composite index on created_at descending and id descending as a single index seek straight to the cursor row; the whole forty-row region is drawn empty and dashed because the cursor never produces those rows, and it then reads the next 20. That is constant cost regardless of depth, so page 5,000 costs the same as page 1. Part two is correctness, and both sides start from the same five rows in positions 1 to 5: ord_05, ord_04, ord_03, ord_02, ord_01. Both return ord_05 and ord_04 as page 1. Then ord_06 is inserted at the top, one concurrent write, and every row shifts down one position. Offset asks for positions 3 and 4 again, but those positions now hold ord_04 and ord_03, so ord_04 comes back a second time: a duplicate, drawn in red. A delete shifts the other way and silently skips a row instead. For a batch job syncing all orders, that is data corruption. The cursor side instead pinned the last row's sort key, the created_at and id of ord_04, and that pin travels with the row when it moves, so page 2 is whatever sorts strictly after ord_04, namely ord_03 and ord_02, with no duplicate and no skip and has_more true. Three supporting details close the diagram: the sort key must be unique and immutable, which is why id is appended to created_at as a tiebreaker, since a collision at a page boundary skips or repeats rows; fetching limit plus one row sets has_more and mints the next cursor with no separate COUNT query; and the cursor is opaque, base64url of the last row's keys, with a mismatched sort order rejected as a 400. Cursor's own costs are no jump to page N and no cheap total. The verdict: default to cursor for anything client-facing or growing, and keep offset for small internal admin lists where page 3 of 9 and a cheap total are real requirements.">
  <defs>
    <marker id="p2l04a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l04a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p2l04a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Offset counts POSITIONS; cursor pins a KEY — that one difference is both the cost and the bug</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="16" y="48" font-size="11" fill="currentColor" font-weight="700">1 &#183; COST — the offset path pays for every row it skips; the cursor path seeks past them</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="16" y="56" width="868" height="94" rx="11" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.75"/>
    <rect x="16" y="158" width="868" height="94" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.75"/>
  </g>
  <text x="30" y="76" font-size="11" fill="#e0930f" font-weight="700">offset:&#8195;SELECT ... ORDER BY created_at DESC, id DESC&#8195;LIMIT 20 OFFSET 40</text>
  <rect x="30" y="88" width="400" height="20" rx="3" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f" stroke-width="1.4"/>
  <path d="M40 88 L40 108 M50 88 L50 108 M60 88 L60 108 M70 88 L70 108 M80 88 L80 108 M90 88 L90 108 M100 88 L100 108 M110 88 L110 108 M120 88 L120 108 M130 88 L130 108 M140 88 L140 108 M150 88 L150 108 M160 88 L160 108 M170 88 L170 108 M180 88 L180 108 M190 88 L190 108 M200 88 L200 108 M210 88 L210 108 M220 88 L220 108 M230 88 L230 108 M240 88 L240 108 M250 88 L250 108 M260 88 L260 108 M270 88 L270 108 M280 88 L280 108 M290 88 L290 108 M300 88 L300 108 M310 88 L310 108 M320 88 L320 108 M330 88 L330 108 M340 88 L340 108 M350 88 L350 108 M360 88 L360 108 M370 88 L370 108 M380 88 L380 108 M390 88 L390 108 M400 88 L400 108 M410 88 L410 108 M420 88 L420 108" stroke="#e0930f" stroke-opacity="0.45" stroke-width="0.8" fill="none"/>
  <rect x="456" y="88" width="200" height="20" rx="3" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.4"/>
  <path d="M466 88 L466 108 M476 88 L476 108 M486 88 L486 108 M496 88 L496 108 M506 88 L506 108 M516 88 L516 108 M526 88 L526 108 M536 88 L536 108 M546 88 L546 108 M556 88 L556 108 M566 88 L566 108 M576 88 L576 108 M586 88 L586 108 M596 88 L596 108 M606 88 L606 108 M616 88 L616 108 M626 88 L626 108 M636 88 L636 108 M646 88 L646 108" stroke="#e0930f" stroke-opacity="0.30" stroke-width="0.8" fill="none"/>
  <path d="M434 98 L450 98" fill="none" stroke="#e0930f" stroke-width="1.7" marker-end="url(#p2l04a-ara)"/>
  <text x="230" y="124" font-size="8.5" fill="#e0930f" text-anchor="middle" font-weight="700">produce + discard rows 1&#8211;40</text>
  <text x="556" y="124" font-size="8.5" fill="#e0930f" text-anchor="middle" font-weight="700">then return rows 41&#8211;60</text>
  <text x="670" y="94" font-size="8" fill="#e0930f" font-weight="700">40 rows of work</text>
  <text x="670" y="106" font-size="8" fill="currentColor" opacity="0.8">to return 20 rows</text>
  <text x="30" y="140" font-size="8.5" fill="currentColor" opacity="0.9">OFFSET 100000 &#8594; the DB produces and discards 100,000 rows before returning 20 — cost grows linearly with depth.</text>
  <text x="30" y="178" font-size="11" fill="#0fa07f" font-weight="700">cursor:&#8195;WHERE (created_at, id) &lt; :cursor&#8195;ORDER BY created_at DESC, id DESC&#8195;LIMIT 21&#8195;-- 20 + 1</text>
  <rect x="30" y="190" width="400" height="20" rx="3" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.2" stroke-dasharray="5 4"/>
  <rect x="456" y="190" width="200" height="20" rx="3" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="1.4"/>
  <path d="M466 190 L466 210 M476 190 L476 210 M486 190 L486 210 M496 190 L496 210 M506 190 L506 210 M516 190 L516 210 M526 190 L526 210 M536 190 L536 210 M546 190 L546 210 M556 190 L556 210 M566 190 L566 210 M576 190 L576 210 M586 190 L586 210 M596 190 L596 210 M606 190 L606 210 M616 190 L616 210 M626 190 L626 210 M636 190 L636 210 M646 190 L646 210" stroke="#0fa07f" stroke-opacity="0.45" stroke-width="0.8" fill="none"/>
  <path d="M36 200 L450 200" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p2l04a-arg)"/>
  <circle cx="36" cy="200" r="3" fill="#0fa07f"/>
  <text x="230" y="226" font-size="8.5" fill="#0fa07f" text-anchor="middle" font-weight="700">index seek straight to the cursor row</text>
  <text x="556" y="226" font-size="8.5" fill="#0fa07f" text-anchor="middle" font-weight="700">read the next 20</text>
  <text x="670" y="196" font-size="8" fill="#0fa07f" font-weight="700">0 rows discarded</text>
  <text x="670" y="208" font-size="8" fill="currentColor" opacity="0.8">for the same 20 rows</text>
  <text x="30" y="242" font-size="8.5" fill="currentColor" opacity="0.9">The composite index (created_at DESC, id DESC) makes it one seek &#8594; constant cost at any depth: page 5,000 costs what page 1 costs.</text>
  <text x="16" y="278" font-size="11" fill="currentColor" font-weight="700">2 &#183; CORRECTNESS — one concurrent insert, applied to both paths</text>
  <text x="884" y="278" font-size="9" fill="#3553ff" text-anchor="end" font-weight="700">client: ?limit=2&amp;offset=2&#8195;vs&#8195;?limit=2&amp;cursor=eyJ...</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="16" y="292" width="430" height="272" rx="11" fill="#e0930f" fill-opacity="0.05" stroke="#e0930f" stroke-opacity="0.75"/>
    <rect x="454" y="292" width="430" height="272" rx="11" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.75"/>
  </g>
  <text x="231" y="314" font-size="12" fill="#e0930f" text-anchor="middle" font-weight="700">OFFSET — a window over POSITIONS</text>
  <text x="231" y="332" font-size="8.5" fill="currentColor" text-anchor="middle">page1 (offset 0): ['ord_05', 'ord_04']&#8195;&#183;&#8195;total: 5</text>
  <rect x="28" y="346" width="130" height="32" rx="7" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="2"/>
  <text x="32" y="343" font-size="7" fill="#e0930f" font-weight="700">page 1</text>
  <rect x="32" y="350" width="58" height="24" rx="5" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="36" y="359" font-size="6.5" fill="currentColor" opacity="0.45">1</text>
  <text x="61" y="368" font-size="9" fill="#e0930f" text-anchor="middle" font-weight="700">ord_05</text>
  <rect x="96" y="350" width="58" height="24" rx="5" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="100" y="359" font-size="6.5" fill="currentColor" opacity="0.45">2</text>
  <text x="125" y="368" font-size="9" fill="#e0930f" text-anchor="middle" font-weight="700">ord_04</text>
  <rect x="160" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="164" y="359" font-size="6.5" fill="currentColor" opacity="0.45">3</text>
  <text x="189" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_03</text>
  <rect x="224" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="228" y="359" font-size="6.5" fill="currentColor" opacity="0.45">4</text>
  <text x="253" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_02</text>
  <rect x="288" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="292" y="359" font-size="6.5" fill="currentColor" opacity="0.45">5</text>
  <text x="317" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_01</text>
  <rect x="352" y="350" width="58" height="24" rx="5" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1.2" stroke-dasharray="4 4"/>
  <text x="231" y="392" font-size="8" fill="#e0930f" text-anchor="middle">the window is a fixed POSITION — first 1&#8211;2, then 3&#8211;4</text>
  <text x="669" y="314" font-size="12" fill="#0fa07f" text-anchor="middle" font-weight="700">CURSOR — a pin in KEY SPACE</text>
  <text x="669" y="332" font-size="8.5" fill="currentColor" text-anchor="middle">page1: ['ord_05', 'ord_04']&#8195;&#183;&#8195;next_cursor: eyJjcmVhdGVkX2F0Ijoi...</text>
  <rect x="466" y="346" width="130" height="32" rx="7" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="2"/>
  <text x="470" y="343" font-size="7" fill="#0fa07f" font-weight="700">page 1</text>
  <rect x="470" y="350" width="58" height="24" rx="5" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="474" y="359" font-size="6.5" fill="currentColor" opacity="0.45">1</text>
  <text x="499" y="368" font-size="9" fill="#0fa07f" text-anchor="middle" font-weight="700">ord_05</text>
  <rect x="534" y="350" width="58" height="24" rx="5" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="538" y="359" font-size="6.5" fill="currentColor" opacity="0.45">2</text>
  <text x="563" y="368" font-size="9" fill="#0fa07f" text-anchor="middle" font-weight="700">ord_04</text>
  <rect x="598" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="602" y="359" font-size="6.5" fill="currentColor" opacity="0.45">3</text>
  <text x="627" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_03</text>
  <rect x="662" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="666" y="359" font-size="6.5" fill="currentColor" opacity="0.45">4</text>
  <text x="691" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_02</text>
  <rect x="726" y="350" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="730" y="359" font-size="6.5" fill="currentColor" opacity="0.45">5</text>
  <text x="755" y="368" font-size="9" fill="currentColor" text-anchor="middle">ord_01</text>
  <rect x="790" y="350" width="58" height="24" rx="5" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1.2" stroke-dasharray="4 4"/>
  <path d="M596 341 L596 382" stroke="#0fa07f" stroke-width="3" stroke-linecap="round" fill="none"/>
  <circle cx="596" cy="341" r="4.2" fill="#0fa07f"/>
  <text x="669" y="392" font-size="8" fill="#0fa07f" text-anchor="middle">cursor = the LAST ROW'S KEY: (created_at, id) of ord_04</text>
  <rect x="16" y="400" width="868" height="22" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.30" stroke-width="1.2"/>
  <text x="450" y="415" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">ord_06 is inserted at the top of the list — one concurrent write, and every row below shifts down one position</text>
  <rect x="156" y="434" width="130" height="32" rx="7" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="2"/>
  <text x="160" y="431" font-size="7" fill="#e0930f" font-weight="700">page 2</text>
  <rect x="32" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="36" y="447" font-size="6.5" fill="currentColor" opacity="0.45">1</text>
  <text x="61" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_06</text>
  <rect x="96" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="100" y="447" font-size="6.5" fill="currentColor" opacity="0.45">2</text>
  <text x="125" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_05</text>
  <rect x="160" y="438" width="58" height="24" rx="5" fill="#d64545" fill-opacity="0.22" stroke="#d64545" stroke-opacity="1" stroke-width="1.4"/>
  <text x="164" y="447" font-size="6.5" fill="currentColor" opacity="0.45">3</text>
  <text x="189" y="456" font-size="9" fill="#d64545" text-anchor="middle" font-weight="700">ord_04</text>
  <rect x="224" y="438" width="58" height="24" rx="5" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="228" y="447" font-size="6.5" fill="currentColor" opacity="0.45">4</text>
  <text x="253" y="456" font-size="9" fill="#e0930f" text-anchor="middle" font-weight="700">ord_03</text>
  <rect x="288" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="292" y="447" font-size="6.5" fill="currentColor" opacity="0.45">5</text>
  <text x="317" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_02</text>
  <rect x="352" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="356" y="447" font-size="6.5" fill="currentColor" opacity="0.45">6</text>
  <text x="381" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_01</text>
  <text x="231" y="480" font-size="8" fill="#e0930f" text-anchor="middle">same positions 3&#8211;4 — but the rows underneath moved</text>
  <text x="231" y="498" font-size="8.5" fill="currentColor" text-anchor="middle">page2 (offset 2): [<tspan fill="#d64545" font-weight="700">'ord_04'</tspan>, 'ord_03']</text>
  <text x="231" y="516" font-size="9.5" fill="#d64545" text-anchor="middle" font-weight="700">ord_04 already appeared on page 1 — DUPLICATE</text>
  <text x="231" y="532" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.85">(a delete shifts the other way and a row is silently SKIPPED)</text>
  <text x="231" y="548" font-size="8.5" fill="#d64545" text-anchor="middle">For a batch job syncing "all orders," that's data corruption.</text>
  <rect x="658" y="434" width="130" height="32" rx="7" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="2"/>
  <text x="672" y="431" font-size="7" fill="#0fa07f" font-weight="700">page 2</text>
  <rect x="470" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="474" y="447" font-size="6.5" fill="currentColor" opacity="0.45">1</text>
  <text x="499" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_06</text>
  <rect x="534" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="538" y="447" font-size="6.5" fill="currentColor" opacity="0.45">2</text>
  <text x="563" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_05</text>
  <rect x="598" y="438" width="58" height="24" rx="5" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.5" stroke-width="1.4" stroke-dasharray="3 3"/>
  <text x="602" y="447" font-size="6.5" fill="currentColor" opacity="0.45">3</text>
  <text x="627" y="456" font-size="9" fill="#0fa07f" text-anchor="middle">ord_04</text>
  <rect x="662" y="438" width="58" height="24" rx="5" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="666" y="447" font-size="6.5" fill="currentColor" opacity="0.45">4</text>
  <text x="691" y="456" font-size="9" fill="#0fa07f" text-anchor="middle" font-weight="700">ord_03</text>
  <rect x="726" y="438" width="58" height="24" rx="5" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f" stroke-opacity="0.9" stroke-width="1.4"/>
  <text x="730" y="447" font-size="6.5" fill="currentColor" opacity="0.45">5</text>
  <text x="755" y="456" font-size="9" fill="#0fa07f" text-anchor="middle" font-weight="700">ord_02</text>
  <rect x="790" y="438" width="58" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
  <text x="794" y="447" font-size="6.5" fill="currentColor" opacity="0.45">6</text>
  <text x="819" y="456" font-size="9" fill="currentColor" text-anchor="middle">ord_01</text>
  <path d="M658 429 L658 470" stroke="#0fa07f" stroke-width="3" stroke-linecap="round" fill="none"/>
  <circle cx="658" cy="429" r="4.2" fill="#0fa07f"/>
  <text x="669" y="480" font-size="8" fill="#0fa07f" text-anchor="middle">the pin travelled WITH ord_04 — page 2 is what sorts after it</text>
  <text x="669" y="498" font-size="8.5" fill="currentColor" text-anchor="middle">page2: ['ord_03', 'ord_02']&#8195;&#183;&#8195;has_more: True</text>
  <text x="669" y="516" font-size="9.5" fill="#0fa07f" text-anchor="middle" font-weight="700">no duplicate, no skip — ord_06 is simply not in this page</text>
  <text x="669" y="532" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.85">the cursor pins a position in KEY space, not row-number space</text>
  <text x="669" y="548" font-size="8.5" fill="#e0930f" text-anchor="middle">Costs: no "jump to page N", no cheap total.</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.4">
    <rect x="16" y="578" width="280" height="62" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35"/>
    <rect x="304" y="578" width="280" height="62" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35"/>
    <rect x="592" y="578" width="292" height="62" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35"/>
  </g>
  <text x="156" y="596" font-size="9.5" fill="currentColor" text-anchor="middle" font-weight="700">SORT KEY: unique + immutable</text>
  <text x="156" y="613" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.9">(created_at, id) — id is the tiebreaker</text>
  <text x="156" y="628" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.8">a collision at a boundary skips or repeats</text>
  <text x="444" y="596" font-size="9.5" fill="currentColor" text-anchor="middle" font-weight="700">FETCH limit + 1 ROWS</text>
  <text x="444" y="613" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.9">the extra row sets has_more and mints</text>
  <text x="444" y="628" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.8">the next cursor — no COUNT query needed</text>
  <text x="738" y="596" font-size="9.5" fill="currentColor" text-anchor="middle" font-weight="700">THE CURSOR IS OPAQUE</text>
  <text x="738" y="613" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.9">base64url of the last row's sort keys —</text>
  <text x="738" y="628" font-size="8" fill="currentColor" text-anchor="middle" opacity="0.8">clients echo it back; a mismatched sort &#8594; 400</text>
  </g>
  <text x="450" y="662" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Default to cursor for anything client-facing or growing: constant cost at any depth, and stable under writes.</text>
  <text x="450" y="680" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Keep offset for small internal admin lists where "page 3 of 9" and a cheap total are real requirements.</text>
  <text x="450" y="700" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">A page-size cap can hide the cost problem; nothing hides the correctness one — a duplicated row is a data bug, not a slow query.</text>
</svg>
```

The demo fetches page 1, inserts **one new row at the top** (a concurrent write),
then fetches page 2. Because offsets address positions, everything shifts down by one
and a row from page 1 reappears on page 2:

```console
$ python pagination.py
=== offset pagination: a row inserted between pages DUPLICATES ===
  page1 (offset 0): ['ord_05', 'ord_04']  total: 5
  --- ord_06 inserted at the top (a concurrent write) ---
  page2 (offset 2): ['ord_04', 'ord_03']   <-- ord_04 already appeared on page1 (duplicate)

=== cursor pagination: same insert, STABLE ===
  page1: ['ord_05', 'ord_04']  next_cursor: eyJjcmVhdGVkX2F0Ijoi...
  --- ord_06 inserted at the top (a concurrent write) ---
  page2: ['ord_03', 'ord_02']   <-- no duplicate, no skip; has_more: True
```

Three details carry the whole technique:

- The **sort key is unique and immutable** — `(created_at, id)` — so a strict
  comparison (`< cursor`) never lands *on* a boundary row and skips or repeats it.
- Fetch **`limit + 1`** rows: the extra one both sets `has_more` and mints the next
  cursor, with no separate `COUNT` query.
- The cursor is **opaque** — base64url of the last row's keys. Clients treat it as a
  token; the meaning stays server-side.

And the sort whitelist is the filter chapter's lesson made executable — an unknown
field is a `400`, never a silent full-table sort:

```python
if field not in SORTABLE:
    raise ValueError("400 cannot sort by {!r}".format(field))
```

## Use It

Declare and validate params explicitly in FastAPI rather than accepting a free-form
dict — the validation *is* the whitelist:

```python
from typing import Literal
from fastapi import Query

@router.get("/orders")
async def list_orders(
    status: Literal["pending", "confirmed", "cancelled"] | None = None,
    customer_id: str | None = None,
    sort: str = Query("-created_at", pattern=r"^-?(created_at|total_amount)(,-?(created_at|total_amount))*$"),
    limit: int = Query(20, ge=1, le=100),
):
    ...
```

The `pattern` on `sort` and the `Literal` on `status` reject unknown fields at the
edge; `le=100` caps how much a client can demand in one page.

## Key takeaways

- Never return an unbounded collection; cap `limit`.
- Filters named like response fields; `sort=-field`; `fields=` sparse; `q=` for text —
  **identical on every endpoint**, unknown params rejected loudly.
- **Offset** degrades linearly and duplicates/skips under writes; **cursor/keyset**
  (composite seek + opaque cursor) is constant-cost and stable — default to it.
