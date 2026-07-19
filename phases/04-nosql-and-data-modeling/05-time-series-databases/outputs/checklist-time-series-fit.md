---
name: checklist-time-series-fit
description: A checklist for deciding whether a time-series database fits a workload, keeping series cardinality under control, and designing retention and downsampling tiers before the firehose fills your disk
phase: 04
lesson: 05
---

# Time-Series Fit, Cardinality & Retention Checklist

Run this before you point a metrics/IoT/events firehose at a database — and again before you go
to production, because the two mistakes that sink a TSDB (runaway cardinality, no retention plan)
are invisible until the data volume makes them fatal.

## Step 0 — Is this actually a time-series workload?

- [ ] The data is **timestamped points** you **append and never update** (a reading at 10:00:01 is
      a permanent historical fact).
- [ ] You read data in **time ranges**, almost always **aggregated** (avg/min/max/percentile per
      minute or hour), not single points by exact timestamp.
- [ ] Recent data is **hot**, old data is **cold**, ancient data is **dropped on a schedule**.
- [ ] The volume is high enough that a relational table's index maintenance and `DELETE`-based
      retention would hurt (otherwise: just use Postgres — see Lesson 1).

If you need to **update** points, enforce **constraints**, or **join** across series row-by-row,
that's a relational job — keep it in Postgres (or reach for TimescaleDB to get both).

## Step 1 — Control cardinality (the #1 way to kill a TSDB)

Cardinality = number of distinct series = the product of each tag/label's distinct values.

- [ ] Every **tag/label** is a **low-cardinality dimension you group or filter by**: `host`,
      `region`, `status_code`, `data_center`.
- [ ] **No** unbounded-cardinality value is a tag: not `user_id`, `request_id`, `trace_id`,
      `session_id`, `email`, or a raw URL/path. Each unique value becomes its own series.
- [ ] You've estimated the series count: multiply the distinct values of every tag together. If it's
      in the millions and climbing, redesign the tags *now*.
- [ ] High-cardinality identifiers that you still need go in a **field/value** (or a different store,
      like logs/traces), never in the series identity.

## Step 2 — Design retention and rollups BEFORE ingesting

Raw high-frequency data fills any disk. Decide the tiers up front and let the database enforce them.

- [ ] Set a **raw retention** window (e.g. keep raw 1s points for 7 days).
- [ ] Define **rollups / downsampling / continuous aggregates** (e.g. 1-minute averages, 1-hour
      min/max) that your dashboards read instead of raw points.
- [ ] Set a **rollup retention** per tier (e.g. 1-minute rollups for 90 days, 1-hour rollups for 2
      years).
- [ ] Confirm retention is a **whole-chunk drop** (O(chunks)), not a row-by-row `DELETE` — that's
      the operational win you came for.

## Step 3 — Pick the tool for the operational model

- [ ] Infrastructure metrics, pull-based scraping, alerting → **Prometheus** (+ PromQL, +
      Alertmanager). Watch label cardinality religiously.
- [ ] Application/IoT metrics and events, push-based, long retention → **InfluxDB** (line protocol,
      retention policies, continuous queries).
- [ ] Already on Postgres and want SQL + joins + transactions alongside time-series →
      **TimescaleDB** (hypertables, native compression, continuous aggregates, retention policies).
      Often the right answer — no second system to operate (Lesson 8).

## Traps to avoid

- [ ] **Cardinality explosion:** a single high-cardinality label multiplies series into the millions
      and OOMs the database. The most common TSDB outage there is.
- [ ] **No retention policy:** the firehose fills the disk; ingest stalls. Set it before day one.
- [ ] **Querying raw when a rollup would do:** a "last 90 days" dashboard scanning billions of raw
      points. Read the continuous aggregate instead.
- [ ] **Using it as a general database:** trying to `UPDATE` points, enforce uniqueness, or join
      series row-by-row. Wrong tool — keep that in the relational store.

## Decision shortcut

> Append-only timestamped points, read in aggregated ranges, old data dropped → TSDB.
> Keep tags low-cardinality (never user_id) → bound the series count.
> Decide raw + rollup retention tiers up front → let the DB enforce them.
> Already on Postgres? TimescaleDB gives you all of it without a second system.
