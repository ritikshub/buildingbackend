# Time-Series Databases

> Metrics, sensor readings, traces, financial ticks — timestamped points arriving by the billion, written once and never changed, always queried by time range. A general database drowns in them; a time-series database is the store shaped for exactly this one data pattern. Its power comes from three tricks — bucket by time, compress the timestamps to a bit each, XOR the values — that a store *not* built for time can't play.

**Type:** Build
**Languages:** Python
**Prerequisites:** [When Not to Use SQL](../01-when-not-to-use-sql/), [Wide-Column Stores](../04-wide-column-stores/), [How Data Lives on Disk: Pages, Heaps & the Buffer Pool](../../03-relational-databases/08-storage-pages-and-heaps/), [Durability: Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/)
**Time:** ~75 minutes

## The Problem

You're running 10,000 servers, and every one reports its CPU usage, memory, disk, and a hundred
other numbers once a second. That's a million data points per second, forever, and next quarter
it's two million. Reach for the relational table you know — `metrics(ts, host, metric, value)` —
and every property that made Postgres great in Phase 3 now works against you:

- **The index is the wrong shape and it never stops growing.** A B-tree index on `(host, metric,
  ts)` has to be maintained on every one of those million inserts per second (Phase 3, Lesson 9),
  and the tree gets deeper and slower as it fills with a firehose that never ebbs.
- **You never update a point, but you pay for the machinery that lets you.** MVCC, row versions,
  vacuum (Phase 3, Lesson 12) all exist to make in-place updates safe. Time-series data is
  *append-only* — a reading at 10:00:01 is a historical fact that will never change — so every one
  of those guarantees is overhead you don't use.
- **Deleting old data is agony.** You want to keep 30 days and drop the rest. `DELETE FROM metrics
  WHERE ts < now() - interval '30 days'` on a table this size scans and tombstones millions of
  rows, bloating the table and hammering the very disk you need for ingest.
- **The storage bill is absurd.** Each point is a tiny number, but stored as a full row — timestamp,
  keys, value, row header, index entries — it costs dozens of bytes. Multiply by a trillion points
  and you're buying racks of disk to hold numbers that barely differ from their neighbors.

Every one of these pains has the same root: a relational database is a *general* tool that assumes
your data can be updated, related, and queried any which way. Time-series data is the opposite —
it has an unusually rigid, predictable shape, and a **time-series database (TSDB)** is what you get
when you design a store to *exploit* that shape instead of ignoring it. In this lesson you'll build
one: time-bucketed chunks, the delta-of-delta timestamp trick, and the XOR value compression that
lets a real TSDB store a point in barely more than one byte. Then you'll meet Prometheus, InfluxDB,
and TimescaleDB and see your Build-It running under all three.

## The Concept

### What makes time-series data special

A **time series** is a sequence of `(timestamp, value)` points belonging to one identity — one
metric on one host, one sensor, one stock symbol. Pin down exactly how it differs from the general
data a relational database expects, because every design choice below falls out of these
properties:

- **Append-only and time-ordered.** New points arrive at the end, roughly in timestamp order. You
  essentially never update or delete an individual old point. (Contrast a `users` table, updated
  constantly.)
- **Written once, read in ranges.** You almost never fetch a single point by exact timestamp. You
  ask for a *range* — "CPU for web1, last 6 hours" — and usually *aggregated*: "average per minute,"
  "99th percentile per 5 minutes." Raw points are rarely the final answer; a summary is.
- **Recent is hot, old is cold, ancient is gone.** Today's data is queried constantly; last month's
  rarely; last year's is dropped on a schedule (**retention**).
- **Values barely change between neighbors.** CPU was 50.2%, then 50.3%, then 50.1%. Consecutive
  values are highly correlated — which, as you'll see, is a gift to compression.
- **The volume is enormous and relentless.** The whole reason the category exists is scale: this is
  Pressure 3 from Lesson 1 (write throughput a single primary can't absorb), specialized for the one
  data shape that produces the most writes of all.

### The data model: series, tags, and points

Every TSDB shares the same mental model, even when the syntax differs:

```text
   measurement + tags     →  identifies the SERIES        cpu.usage{host=web1, region=eu}
        timestamp         →  when                          1700000090
        value(s)          →  what                          52.8
```

- A **measurement** is the name of the thing being measured (`cpu.usage`, `temperature`).
- **Tags** (Prometheus calls them **labels**) are key-value pairs that, together with the
  measurement, name one specific **series**. `cpu.usage{host=web1}` and `cpu.usage{host=web2}` are
  two different series.
- A **point** is a `(timestamp, value)` pair within a series.

One number decides whether a TSDB thrives or falls over: **cardinality** — the total count of
distinct series, which is the product of how many distinct values each tag can take. Ten thousand
hosts × fifty metrics = 500,000 series: fine. But put a *high-cardinality* value in a tag — a
`user_id`, a `request_id`, an email — and cardinality explodes into the millions or billions, one
series per value, and the database dies. **This is the number-one way people destroy a TSDB in
production**, so it's worth stating as a rule now: tags are for low-cardinality dimensions you
group and filter by; never for unique identifiers.

### Trick 1 — Bucket by time, and make retention free

The first design choice is the same append-only, immutable-chunk idea you've now met twice (the
Bitcask log in Lesson 2, the LSM-tree SSTables in Lesson 4), specialized for time: **partition each
series into chunks by time window** — say, one chunk per hour or two-hour block. New writes only
ever touch the *newest* chunk; every older chunk is sealed, immutable, and compressed hard.

This one decision pays off three ways:

- **Writes stay fast forever.** They only append to the current chunk; the millions of old points
  are frozen and out of the write path. Ingest speed doesn't degrade as history grows.
- **Range queries skip almost everything.** "Last 6 hours" touches six chunks and ignores the other
  eight thousand — the database never even decompresses a chunk outside your time window.
- **Retention becomes a file delete.** Dropping "everything older than 30 days" means *deleting whole
  chunks* — an `O(number of chunks)` operation that frees disk instantly, with none of the
  row-by-row `DELETE`, tombstone, and vacuum pain the relational table suffered. This is the single
  biggest operational win, and it exists only because the data is partitioned by the same axis you
  expire it on.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 572" width="100%" style="max-width:880px" role="img" aria-label="The time-series data model and time bucketing. A measurement name plus a set of tags identifies one series: cpu.usage with tags host equals web1 and region equals eu. Changing any tag value, for example host equals web2, makes it a different series, so the total number of distinct series — the cardinality — is the product of each tag's distinct value counts. Ten thousand hosts times fifty metrics is five hundred thousand series, which is fine, but putting a user_id in a tag creates millions of series and kills the database. That series holds one ordered, append-only run of timestamp-and-value points: 1700000088 at 52.6, 1700000089 at 52.7, 1700000090 at 52.8, and so on, with new points arriving only at the end. Each point is routed to the chunk that owns its time window using base equals ts integer-divided by 3600 times 3600, giving one chunk per hour. The newest chunk, eleven o'clock to now, is open and is the only chunk writes ever touch, so ingest speed never degrades. Older chunks are sealed and immutable, compressed hard, and skipped entirely when a query range does not overlap them. The oldest chunk, past retention, is first rolled up into sixty one-minute averages and then dropped as one whole file — an order-of-chunks operation that frees 7,200 points instantly with nothing scanned — whereas a relational DELETE WHERE ts is older than thirty days scans and tombstones millions of rows, bloats the table, and fights the ingest disk. Rollups also give the classic tiered policy: raw points for 7 days, one-minute rollups for 90 days, one-hour rollups for 2 years.">
  <defs>
    <marker id="p4l5a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p4l5a-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">A series is measurement + tags; its points live in time buckets — so expiry is a file delete</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="42" width="520" height="98" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="552" y="42" width="332" height="98" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <text x="34" y="64" font-size="10.5" font-weight="700" fill="#7c5cff">1 · THE SERIES — the identity a run of points belongs to</text>
    <text x="276" y="94" text-anchor="middle" font-size="13.5" fill="currentColor"><tspan fill="#7c5cff" font-weight="700">cpu.usage</tspan><tspan>{host=web1, region=eu}</tspan></text>
    <g stroke-width="1.6" fill="none">
      <path d="M151 102 L223 102" stroke="#7c5cff"/>
      <path d="M226 102 L401 102" stroke="currentColor" stroke-opacity="0.4"/>
    </g>
    <text x="187" y="115" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">measurement</text>
    <text x="313" y="115" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">tags — dimensions you group by</text>
    <text x="276" y="132" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">cpu.usage{host=web2} is a DIFFERENT series — tags are part of the identity</text>

    <text x="568" y="62" font-size="10.5" font-weight="700" fill="#e0930f">CARDINALITY = distinct series</text>
    <text x="568" y="80" font-size="9" fill="currentColor" opacity="0.9">= product of each tag's value counts</text>
    <text x="568" y="99" font-size="9" fill="#0fa07f">10,000 hosts × 50 metrics = 500,000 ✓</text>
    <text x="568" y="117" font-size="9" fill="#d64545">user_id as a tag → millions ✗ it dies</text>
    <text x="568" y="132" font-size="8" fill="currentColor" opacity="0.72">tags are for dimensions, never for IDs</text>

    <text x="450" y="164" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">2 · The series holds one ordered, append-only run of (timestamp, value) points</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="75"  y="176" width="110" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="203" y="176" width="110" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="331" y="176" width="110" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="459" y="176" width="110" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="587" y="176" width="110" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="715" y="176" width="110" height="46" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-dasharray="5 4"/>
    </g>
    <g text-anchor="middle" font-size="9" fill="#3553ff">
      <text x="130" y="194">1700000088</text><text x="258" y="194">1700000089</text><text x="386" y="194">1700000090</text>
      <text x="514" y="194">1700000091</text><text x="642" y="194">1700000092</text><text x="770" y="194">1700000093</text>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">
      <text x="130" y="212">52.6</text><text x="258" y="212">52.7</text><text x="386" y="212">52.8</text>
      <text x="514" y="212">52.8</text><text x="642" y="212">52.9</text><text x="770" y="212">53.0</text>
    </g>
    <text x="66" y="194" text-anchor="end" font-size="8" fill="#3553ff">when →</text>
    <text x="66" y="212" text-anchor="end" font-size="8" fill="#0fa07f">what →</text>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M831 199 L872 199" marker-end="url(#p4l5a-arg)"/>
    </g>
    <text x="851" y="214" text-anchor="middle" font-size="7.5" fill="#0fa07f">append</text>
    <text x="450" y="240" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">time runs left → right; new points arrive only at the end — you never go back and update one</text>

    <text x="450" y="268" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">3 · Each point is routed to the chunk that owns its time window — base = (ts // 3600) * 3600</text>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M770 226 L783 276" marker-end="url(#p4l5a-arg)"/>
    </g>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16"  y="282" width="202" height="100" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="238" y="282" width="202" height="100" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="460" y="282" width="202" height="100" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="682" y="282" width="202" height="100" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#0fa07f" stroke-dasharray="6 4"/>
    </g>
    <g text-anchor="middle">
      <text x="117" y="304" font-size="11" font-weight="700" fill="#d64545">08:00 — 09:00</text>
      <text x="117" y="324" font-size="8.5" fill="currentColor">3,600 points, sealed</text>
      <text x="117" y="342" font-size="8.5" fill="#e0930f">rolled up to 60 × 1-min</text>
      <text x="117" y="361" font-size="9" font-weight="700" fill="#d64545">then DROPPED whole</text>
      <text x="117" y="376" font-size="7.5" fill="currentColor" opacity="0.75">one file delete, O(1)</text>

      <text x="339" y="304" font-size="11" font-weight="700" fill="#7c5cff">09:00 — 10:00</text>
      <text x="339" y="324" font-size="8.5" fill="currentColor">3,600 points</text>
      <text x="339" y="342" font-size="8.5" fill="currentColor">SEALED · immutable</text>
      <text x="339" y="361" font-size="8.5" fill="currentColor">compressed hard</text>
      <text x="339" y="376" font-size="7.5" fill="currentColor" opacity="0.75">never rewritten again</text>

      <text x="561" y="304" font-size="11" font-weight="700" fill="#7c5cff">10:00 — 11:00</text>
      <text x="561" y="324" font-size="8.5" fill="currentColor">3,600 points</text>
      <text x="561" y="342" font-size="8.5" fill="currentColor">SEALED · immutable</text>
      <text x="561" y="361" font-size="8.5" fill="currentColor">skipped unless your</text>
      <text x="561" y="376" font-size="8.5" fill="currentColor">range overlaps it</text>

      <text x="783" y="304" font-size="11" font-weight="700" fill="#0fa07f">11:00 — now</text>
      <text x="783" y="324" font-size="8.5" fill="currentColor">OPEN · being appended</text>
      <text x="783" y="342" font-size="8.5" fill="currentColor">the ONLY chunk writes</text>
      <text x="783" y="361" font-size="8.5" fill="currentColor">ever touch</text>
      <text x="783" y="376" font-size="7.5" fill="currentColor" opacity="0.75">so ingest never slows down</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="1.7">
      <path d="M117 384 L117 392" marker-end="url(#p4l5a-arr)"/>
    </g>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16"  y="396" width="430" height="106" rx="10" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.7"/>
      <rect x="470" y="396" width="414" height="106" rx="10" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.7"/>
    </g>
    <text x="34" y="418" font-size="10.5" font-weight="700" fill="#d64545">RETENTION — dropping everything older than 30 days</text>
    <text x="34" y="440" font-size="9" font-weight="700" fill="#0fa07f">TSDB ✓  del chunks[base] — an O(chunks) file delete;</text>
    <text x="34" y="456" font-size="8.5" fill="currentColor" opacity="0.85">2 chunks gone, 7,200 points freed, nothing scanned.</text>
    <text x="34" y="478" font-size="9" font-weight="700" fill="#d64545">Relational ✗  DELETE ... WHERE ts &lt; now() - 30 days</text>
    <text x="34" y="494" font-size="8.5" fill="currentColor" opacity="0.85">scans + tombstones millions of rows, bloats, fights ingest.</text>

    <text x="488" y="418" font-size="10.5" font-weight="700" fill="#e0930f">ROLLUP — before a chunk goes, keep its summary</text>
    <text x="488" y="440" font-size="9" fill="currentColor">10,800 raw points → 36 five-minute averages</text>
    <text x="488" y="456" font-size="8.5" fill="currentColor" opacity="0.85">— which is all a dashboard ever plots</text>
    <text x="488" y="478" font-size="9" font-weight="700" fill="#e0930f">raw 7d → 1-min rollups 90d → 1-hour rollups 2y</text>
    <text x="488" y="494" font-size="8.5" fill="currentColor" opacity="0.85">precision where it's fresh, a cheap summary where it's old</text>
  </g>
  <text x="450" y="524" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Partition by the same axis you expire on, and retention becomes one file delete instead of a billion-row DELETE.</text>
  <text x="450" y="542" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Sealed chunks never change, so they can be compressed hard once, rolled up once, and then only ever read.</text>
  <text x="450" y="560" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Cardinality is the one number that kills a TSDB: a unique ID in a tag means one whole series per value.</text>
</svg>
```

### Trick 2 — Compress the timestamps to (almost) one bit each

Here is where a TSDB pulls dramatically ahead of a general store, and it starts with the timestamps.
Points arrive at a near-constant interval — every second, every 10 seconds — so the *gaps between
them* (the **deltas**) are nearly identical. **Delta-of-delta encoding** stores the *change in the
delta*, which for a perfectly regular stream is **zero**:

```text
timestamps:      10:00:00   10:00:01   10:00:02   10:00:03   10:00:05
deltas (Δ):                +1         +1         +1         +2
delta-of-delta:                        0          0         +1     ← store THIS
```

A run of zeros is the easiest thing in the world to compress: write a single `0` bit for each
on-schedule point, and spend a few extra bits only when the interval jitters. A million perfectly
regular timestamps collapse to about a million bits — ~125 KB instead of the 8 MB they'd take as raw
64-bit integers.

### Trick 3 — XOR the values

The values get the same treatment, exploiting that neighbors barely differ. A floating-point number
is 64 bits — a sign, an exponent, and a mantissa (Phase 0, Lesson 1). Two nearby values like `50.2`
and `50.3` share their sign, their exponent, and most of their high mantissa bits, so if you **XOR**
one against the previous, the result is mostly **zeros** — a long run of leading zeros, a long run
of trailing zeros, and only a few "meaningful" bits stuck in the middle:

```text
50.2  = 0x4049199999999... 
50.3  = 0x4049266666666...
XOR   = 0x00003FFFFFFF...   ← store only the middle run of meaningful bits
```

Store just that middle window — its position (leading-zero count) and its bits — and when the next
value's window fits inside the previous one, reuse the position for free. When the value doesn't
change at all (common for gauges that sit still), the XOR is zero and you write a single `0` bit.

Trick 2 (delta-of-delta timestamps) and Trick 3 (XOR values) together are the compression scheme
from Facebook's **Gorilla** paper (Pelkonen et al., VLDB 2015), which reported an average of about
**1.37 bytes per point** — down from 16. That's not a general-purpose zip algorithm; it's a scheme
that *knows* the data is a time series and squeezes it on that knowledge. It's the reason a TSDB
holds a year of metrics on the disk a relational table would fill in a month. You're about to build
it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 622" width="100%" style="max-width:880px" role="img" aria-label="The two Gorilla compression tricks worked out on real numbers. Trick 2, timestamps: five points arrive at 10:00:00, 10:00:01, 10:00:02, 10:00:03 and 10:00:05. The gaps between them, the deltas, are plus one, plus one, plus one, plus two. The change in the gap, the delta-of-delta, is plus one, then zero, then zero, then plus one. The first timestamp costs 32 bits as an offset into the chunk; a delta-of-delta of zero — the on-schedule common case — costs a single 0 bit; a jitter costs a two-bit prefix 10 plus seven bits, that is nine bits. A variable-length prefix code spends more bits the bigger the jump: 0 for on schedule, 10 plus 7 for plus or minus 64, 110 plus 9 for plus or minus 256, 1110 plus 12 for plus or minus 2048, and 1111 plus 32 for anything. A million perfectly regular timestamps therefore collapse to about a million bits, roughly 125 kilobytes, instead of the 8 megabytes they would take as raw 64-bit integers. Trick 3, values: 50.2 is 0x4049199999999 and 50.3 is 0x4049266666666, sharing their sign, their exponent and most of their high mantissa bits, so the XOR of the two is 0x00003FFFFFFF — a long run of leading zeros, a short meaningful window in the middle, and a long run of trailing zeros. Only the middle window is stored: six bits for the leading-zero count, seven bits for its length, then the bits themselves. Two shortcuts make it cheaper still — if the next XOR's window fits inside the previous one, a single control bit reuses the position for free, and if the value did not change at all the XOR is zero and one 0 bit is written. The codec is lossless, not an approximation. The payoff in bytes per point: a raw row costs 16 bytes, the build in this lesson reaches 2.57 bytes per point or 6.2 times smaller, and Gorilla in production reaches about 1.37 bytes per point, roughly ten times smaller.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Both streams are almost all redundancy — delta-of-delta the timestamps, XOR the values</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="16" y="40" width="868" height="218" rx="11" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.55" stroke-width="1.8" fill-rule="evenodd"/>
    <text x="34" y="62" font-size="11.5" font-weight="700" fill="#3553ff">TRICK 2 · TIMESTAMPS</text>
    <text x="188" y="62" font-size="9" fill="currentColor" opacity="0.85">points arrive on a near-constant interval → the gap between them repeats</text>

    <rect x="460" y="130" width="250" height="66" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.6"/>

    <g text-anchor="end" font-size="8.5" fill="currentColor" opacity="0.8">
      <text x="170" y="92">raw timestamp</text>
      <text x="170" y="118">delta Δ (the gap)</text>
      <text x="170" y="146">delta-of-delta</text>
      <text x="170" y="174">bits on disk</text>
      <text x="170" y="190">written as</text>
    </g>

    <g text-anchor="middle" font-size="10" fill="#3553ff">
      <text x="250" y="92">10:00:00</text><text x="385" y="92">10:00:01</text><text x="520" y="92">10:00:02</text>
      <text x="655" y="92">10:00:03</text><text x="790" y="92">10:00:05</text>
    </g>
    <g text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">
      <text x="250" y="118">—</text><text x="385" y="118">+1</text><text x="520" y="118">+1</text>
      <text x="655" y="118">+1</text><text x="790" y="118">+2</text>
    </g>
    <g text-anchor="middle" font-size="11" font-weight="700">
      <text x="250" y="146" fill="currentColor" opacity="0.6">—</text>
      <text x="385" y="146" fill="#e0930f">+1</text>
      <text x="520" y="146" fill="#0fa07f">0</text>
      <text x="655" y="146" fill="#0fa07f">0</text>
      <text x="790" y="146" fill="#e0930f">+1</text>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="700">
      <text x="250" y="174" fill="currentColor" opacity="0.7">32 bits</text>
      <text x="385" y="174" fill="#e0930f">9 bits</text>
      <text x="520" y="174" fill="#0fa07f">1 bit</text>
      <text x="655" y="174" fill="#0fa07f">1 bit</text>
      <text x="790" y="174" fill="#e0930f">9 bits</text>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">
      <text x="250" y="190">offset in chunk</text>
      <text x="385" y="190">10 0000001</text>
      <text x="520" y="190">0</text>
      <text x="655" y="190">0</text>
      <text x="790" y="190">10 0000001</text>
    </g>
    <text x="585" y="211" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">on schedule → dod = 0 → ONE bit</text>

    <text x="34" y="230" font-size="8.5" fill="currentColor" opacity="0.85">prefix code:  0 → on schedule (1 bit) · 10+7 → ±64 · 110+9 → ±256 · 1110+12 → ±2048 · 1111+32 → any jump</text>
    <text x="34" y="249" font-size="9" font-weight="700" fill="#3553ff">A million perfectly regular timestamps ≈ a million bits = ~125 KB — vs 8 MB as raw 64-bit integers.</text>

    <rect x="16" y="270" width="868" height="176" rx="11" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.8"/>
    <text x="34" y="292" font-size="11.5" font-weight="700" fill="#0fa07f">TRICK 3 · VALUES</text>
    <text x="160" y="292" font-size="9" fill="currentColor" opacity="0.85">50.2 then 50.3 share their sign, exponent and most mantissa bits → the XOR is nearly all zeros</text>

    <text x="44" y="318" font-size="8.5" fill="currentColor" opacity="0.7">prev</text>
    <text x="100" y="318" font-size="10" fill="currentColor">50.2  = 0x4049199999999...</text>
    <text x="44" y="338" font-size="8.5" fill="currentColor" opacity="0.7">next</text>
    <text x="100" y="338" font-size="10" fill="currentColor">50.3  = 0x4049266666666...</text>
    <path d="M96 346 L360 346" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2" fill="none"/>
    <text x="100" y="364" font-size="10" font-weight="700" fill="#0fa07f">XOR   = 0x00003FFFFFFF...</text>

    <g fill="none" stroke-width="1.5">
      <rect x="400" y="306" width="132" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="532" y="306" width="176" height="26" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2"/>
      <rect x="708" y="306" width="162" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.35"/>
    </g>
    <text x="262" y="364" font-size="8" fill="currentColor" opacity="0.7">all 64 bits →</text>
    <text x="466" y="323" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">0000 … 0000</text>
    <text x="620" y="323" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">1011 … 0110</text>
    <text x="789" y="323" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">0000 … 0000</text>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">
      <text x="466" y="346">leading zeros</text>
      <text x="466" y="358">store the COUNT (6 bits)</text>
      <text x="789" y="346">trailing zeros</text>
      <text x="789" y="358">dropped entirely</text>
    </g>
    <text x="620" y="346" text-anchor="middle" font-size="8" font-weight="700" fill="#0fa07f">the only bits that changed</text>
    <text x="620" y="358" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">store length (7 bits) + these bits</text>

    <text x="34" y="386" font-size="9" font-weight="700" fill="#0fa07f">SHORTCUT 1 · the next XOR's window fits inside this one → 1 control bit, reuse the position for free</text>
    <text x="34" y="405" font-size="9" font-weight="700" fill="#0fa07f">SHORTCUT 2 · the value didn't change at all → XOR = 0 → write a single 0 bit (gauges that sit still)</text>
    <text x="34" y="430" font-size="9" fill="currentColor" opacity="0.85">Nothing is discarded: decoding replays the same state machine in reverse, so the codec is LOSSLESS, not an approximation.</text>

    <rect x="16" y="458" width="868" height="106" rx="11" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1.8"/>
    <text x="34" y="480" font-size="11.5" font-weight="700" fill="#7c5cff">THE PAYOFF · bytes per point</text>
    <g fill="none" stroke-width="1.4">
      <rect x="262" y="488" width="420" height="16" rx="4" fill="#7f7f7f" fill-opacity="0.18" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="262" y="512" width="67"  height="16" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="262" y="536" width="36"  height="16" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
    </g>
    <g text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">
      <text x="250" y="500">a raw row (8 + 8 bytes)</text>
      <text x="250" y="524">the build in this lesson</text>
      <text x="250" y="548">Gorilla, in production</text>
    </g>
    <text x="694" y="500" font-size="9" fill="currentColor" opacity="0.85">16.00 bytes/point</text>
    <text x="341" y="524" font-size="9" font-weight="700" fill="#7c5cff">2.57 bytes/point — 6.2× smaller (smooth synthetic data)</text>
    <text x="310" y="548" font-size="9" font-weight="700" fill="#7c5cff">~1.37 bytes/point — ≈10× smaller (real metrics repeat far more)</text>
  </g>
  <text x="450" y="588" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Both tricks work for one reason: a time series is nearly all redundancy — regular gaps, and neighbours that barely move.</text>
  <text x="450" y="606" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">That's why this beats a general-purpose zip: the codec KNOWS the data is a time series, so it stores only the surprises.</text>
  <text x="450" y="620" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" fill="currentColor" opacity="0.7">(Gorilla — Pelkonen et al., VLDB 2015 — the scheme behind Prometheus's on-disk blocks and InfluxDB's engine.)</text>
</svg>
```

### Trick 4 — Downsample and roll up

The last trick answers "read in ranges, usually aggregated." Nobody plots a million raw points on a
dashboard; they plot one average per minute. **Downsampling** (also called **rollups** or
**continuous aggregates**) precomputes those summaries — 1-minute, 1-hour averages/min/max — so a
"last 90 days" query reads a few thousand rollup rows instead of scanning billions of raw points.
Combined with retention, this gives the classic tiered policy: keep **raw** points for 7 days,
**1-minute** rollups for 90 days, **1-hour** rollups for 2 years. Precision where it's fresh and
useful; a cheap summary where it's old.

## Build It

Let's build a TSDB with all four tricks: time-bucketed chunks, delta-of-delta timestamps, XOR value
compression, range queries that skip out-of-range chunks, downsampling, and `O(1)` retention.
Standard library only — `struct` to get at a float's raw bits, and a tiny bit-level reader/writer,
because a TSDB packs data to the *bit*, not the byte.

First the bit I/O, since everything below writes fractional bytes:

```python
class BitWriter:
    """Append individual bits; flush to bytes at the end (last byte zero-padded)."""
    def __init__(self):
        self.buf = bytearray()
        self._cur = 0            # the partial byte being filled, MSB-first
        self._nbits = 0          # how many bits of _cur are used (0..7)

    def write_bit(self, bit):
        self._cur = (self._cur << 1) | (bit & 1)
        self._nbits += 1
        if self._nbits == 8:
            self.buf.append(self._cur)
            self._cur, self._nbits = 0, 0

    def write_bits(self, value, count):
        for i in range(count - 1, -1, -1):       # most-significant bit first
            self.write_bit((value >> i) & 1)
```

The timestamp codec is the delta-of-delta scheme: one `0` bit for the on-schedule common case, and a
variable-length prefix (`10`, `110`, `1110`, `1111`) that spends more bits the bigger the jitter:

```python
def _encode_dod(w, dod):
    if dod == 0:
        w.write_bit(0)                                         # '0'    — on schedule, one bit
    elif -64 <= dod <= 63:
        w.write_bits(0b10, 2);  w.write_bits(dod & 0x7F, 7)    # '10'   + 7 bits
    elif -256 <= dod <= 255:
        w.write_bits(0b110, 3); w.write_bits(dod & 0x1FF, 9)   # '110'  + 9 bits
    elif -2048 <= dod <= 2047:
        w.write_bits(0b1110, 4); w.write_bits(dod & 0xFFF, 12) # '1110' + 12 bits
    else:
        w.write_bits(0b1111, 4); w.write_bits(dod & 0xFFFFFFFF, 32)  # '1111' + 32 bits
```

The value codec XORs against the previous value and stores only the meaningful middle window,
reusing the previous window's position when it fits:

```python
def _encode_xor(w, xor, prev_lz, prev_tz):
    if xor == 0:
        w.write_bit(0)                        # value unchanged -> one bit
        return prev_lz, prev_tz
    w.write_bit(1)
    lz, tz = _leading_zeros(xor), _trailing_zeros(xor)
    if prev_lz is not None and lz >= prev_lz and tz >= prev_tz:
        w.write_bit(0)                        # the window fits the previous one — reuse it
        length = 64 - prev_lz - prev_tz
        w.write_bits((xor >> prev_tz) & ((1 << length) - 1), length)
        return prev_lz, prev_tz
    w.write_bit(1)                            # declare a new window: position + length + bits
    length = 64 - lz - tz
    w.write_bits(lz, 6); w.write_bits(length, 7); w.write_bits(xor >> tz, length)
    return lz, tz
```

A **chunk** holds one time bucket's points as a single compressed bitstream: the first point is
stored in full (a base for everything after), and each later point is encoded as its delta-of-delta
timestamp plus its XORed value. Decoding replays the same state machine in reverse:

```python
class CompressedChunk:
    def append(self, ts, value):
        w, bits = self._w, _float_bits(value)
        if self.count == 0:
            w.write_bits(ts - self.base_ts, 32)      # first timestamp: offset into the bucket
            w.write_bits(bits, 64)                    # first value: full 64 bits
            self._prev_ts, self._prev_delta = ts, 0
        else:
            delta = ts - self._prev_ts
            _encode_dod(w, delta - self._prev_delta)  # the delta-of-delta
            self._prev_ts, self._prev_delta = ts, delta
            self._prev_lz, self._prev_tz = _encode_xor(
                w, bits ^ self._prev_bits, self._prev_lz, self._prev_tz)
        self._prev_bits = bits
        self.count += 1
```

The database itself maps each series to its time-bucketed chunks. `query` decodes only the chunks
that overlap the requested range; `downsample` groups the decoded points into fixed time buckets;
`drop_before` deletes whole chunks:

```python
class TimeSeriesDB:
    def insert(self, name, ts, value):
        chunks = self.series.setdefault(name, {})
        base = (ts // self.chunk_seconds) * self.chunk_seconds   # which time bucket
        chunk = chunks.get(base) or chunks.setdefault(base, CompressedChunk(base))
        chunk.append(ts, value)

    def query(self, name, start, end):
        out = []
        for base in sorted(self.series.get(name, {})):
            if base + self.chunk_seconds <= start or base >= end:
                continue                             # whole chunk out of range -> never decoded
            out.extend((ts, v) for ts, v in self.series[name][base].points()
                       if start <= ts < end)
        return out

    def drop_before(self, name, cutoff_ts):          # retention: O(chunks), not O(rows)
        chunks = self.series.get(name, {})
        dead = [b for b in chunks if b + self.chunk_seconds <= cutoff_ts]
        for b in dead:
            del chunks[b]
        return len(dead)
```

Running `python tsdb.py` ingests 3 hours of one-per-second CPU readings, proves the compression is
lossless, then exercises range query, downsampling, and retention:

```console
$ python tsdb.py
== INGEST ==
  ingested 10800 points (cpu.usage{host=web1}) into 3 hourly chunks
  round-trip check: decoded points identical to input  ✓

== COMPRESSION (delta-of-delta timestamps + XOR values) ==
  uncompressed:   172800 bytes  (16 bytes/point)
  compressed:      27786 bytes  (2.57 bytes/point)
  ratio:        6.2x smaller

== RANGE QUERY: a 60-second window, only its chunk is decoded ==
  points in [START+90, START+150): 60
  first: ts=START+90, value=52.8
  last:  ts=START+149, value=50.9

== DOWNSAMPLE: raw 1s points -> 5-minute average buckets ==
  10800 raw points -> 36 five-minute buckets
    bucket START+    0s  avg=52.75

== RETENTION: drop whole chunks older than a cutoff ==
  chunks before: 3  ->  dropped 2 old chunk(s)  ->  1 left
  remaining points: 3600  (dropping a chunk is O(1), no DELETE scan)
```

Read the numbers. The **round-trip check** decodes every one of the 10,800 points and asserts they
equal the input — the compression is *lossless*, not a lossy approximation. **6.2× smaller** on
smoothly-varying synthetic data (real production metrics, which repeat far more, hit Gorilla's ~10×);
the timestamps, all one second apart, cost about one bit each. The **range query** for a 60-second
window returned exactly 60 points and only ever decoded the single chunk that overlapped it. The
**downsample** turned 10,800 raw points into 36 five-minute averages — that's what a dashboard
actually reads. And **retention** dropped two whole hourly chunks in one `O(1)` operation, freeing
7,200 points' worth of disk without scanning or tombstoning a single row. Every pain from *The
Problem* is gone — because the store is built around the data's shape.

## Use It

You'll rarely write your own TSDB, but you'll run one, and the Build-It maps directly onto the three
you're most likely to meet.

**Prometheus** is the de-facto standard for infrastructure metrics. It *pulls* metrics by scraping
an HTTP endpoint on each target, stores them in its own on-disk TSDB (2-hour blocks — your chunks —
with delta-of-delta timestamps and XOR values — your codecs, straight from the Gorilla lineage), and
queries with **PromQL**. Its data model is exactly measurement + labels + value:

```text
# A Prometheus time series: metric name + labels identify it; PromQL queries by range.
cpu_usage_percent{host="web1", region="eu"}   52.8

rate(http_requests_total[5m])                  # per-second rate over a 5-minute window
avg_over_time(cpu_usage_percent[1h])           # your downsample(), as a query
```

The single most important operational rule lives here: **never put an unbounded-cardinality value in
a label.** A `user_id` or `request_id` label spawns one series per value and is the classic way to
take Prometheus down — the cardinality lesson, made real.

**InfluxDB** is purpose-built for metrics, events, and IoT, and speaks a compact line protocol that
is the series model on the wire — tags before the space, fields after:

```text
# InfluxDB line protocol:  measurement,tag=... field=...  timestamp
cpu.usage,host=web1,region=eu value=52.8 1700000090000000000
```

Its **retention policies** and **continuous queries** are your `drop_before` and `downsample`,
declared as configuration: keep raw data 7 days, auto-roll it into 1-hour averages, keep those 2
years. Same tiering you built, run by the database on a schedule.

**TimescaleDB** is the senior-engineer plot twist, and it's Lesson 1's "the line has moved" made
concrete. It's a Postgres *extension*: a **hypertable** looks like an ordinary SQL table but is
automatically partitioned into time chunks under the hood, with native compression and **continuous
aggregates** (materialized rollups). You get delta-of-delta/columnar compression and automatic
retention — *inside the Postgres you already run*, with full SQL, joins to your relational tables,
and transactions:

```sql
-- A hypertable: a normal-looking table, transparently chunked by time under the hood.
CREATE TABLE metrics (ts timestamptz, host text, value double precision);
SELECT create_hypertable('metrics', 'ts');
SELECT add_retention_policy('metrics', INTERVAL '30 days');   -- your drop_before(), scheduled

-- A continuous aggregate: your downsample(), maintained automatically.
SELECT time_bucket('5 minutes', ts) AS bucket, host, avg(value)
FROM metrics GROUP BY bucket, host;
```

Three hard-won lessons that separate people who run a TSDB well from people who get paged by one:

- **Cardinality is the enemy — guard the tags.** Every design decision comes back to keeping the
  number of series bounded. Put dimensions you group by (`host`, `region`, `status`) in tags; keep
  unique identifiers (`user_id`, `trace_id`, raw URLs) *out* of them. A single high-cardinality tag
  can multiply your series count by a million and OOM the database.
- **Decide retention and rollups before you ingest, not after.** Raw high-frequency data is a
  firehose that will fill any disk. Pick the tiers up front — how long you keep raw, what you roll it
  into, how long you keep the rollups — and let the database enforce them. Retrofitting downsampling
  onto a table that's already drowning is far harder.
- **It's append-only by design — don't fight it.** A TSDB is superb at "write points, read ranges,
  aggregate" and deliberately bad at what a relational database is for: updating individual points,
  enforcing constraints, joining across series. Keep those in Postgres. When you catch yourself
  wanting to `UPDATE` a metric or join two series row-by-row, you're using the wrong tool — or you
  want TimescaleDB, so the relational half is right there.

## Key takeaways

- A **time-series database** is built to exploit the rigid shape of timestamped data:
  **append-only**, **time-ordered**, **written once and read in aggregated ranges**, **recent-hot /
  old-dropped**, and **enormous**. It's Pressure 3 (write throughput) specialized for the shape that
  produces the most writes.
- The model is **measurement + tags → series**, plus `(timestamp, value)` **points**. The metric
  that makes or breaks it is **cardinality** (distinct series = product of tag-value counts) — never
  put a high-cardinality value like a `user_id` in a tag.
- **Time-bucketed chunks** keep ingest fast, let range queries skip everything outside the window,
  and make **retention** a whole-chunk delete (`O(chunks)`) instead of a row-by-row `DELETE` that
  bloats the table.
- **Delta-of-delta** timestamp encoding turns a regular interval into ~one bit per point, and
  **XOR** value compression stores only the few bits that change between neighbors — the **Gorilla**
  scheme (~1.37 bytes/point), a *lossless* codec that works only because it knows the data is a time
  series.
- In production: **Prometheus** (pull-based infra metrics, PromQL), **InfluxDB** (line protocol,
  retention policies, continuous queries), and **TimescaleDB** (time-series *inside* Postgres —
  hypertables, compression, continuous aggregates, with SQL and transactions kept). Match the tool
  to the shape, and keep updates, constraints, and joins in the relational store.

Next: [Graph Databases](../06-graph-databases/) — the last NoSQL family, for data where the
*connections between* records matter more than the records themselves, and where each relationship
becomes a pointer you follow in `O(1)` instead of a join you pay for again on every hop.
