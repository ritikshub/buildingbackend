---
name: checklist-blast-radius-review
description: Run this against one service, in a room, with the architecture diagram open.
phase: 11
lesson: 09
---

# Blast Radius Review — a working checklist

Run this against one service, in a room, with the architecture diagram open. Budget 90 minutes.
Output is a filled-in table and a list of dated actions, not a document. Rule for the whole
exercise: **every answer is a percentage, and "we have redundancy" is not a percentage.**

---

## 1. Inventory the failure domains

For each row, name the specific component and write the fraction of customers who lose service
when it fails. Measure or derive it — do not estimate.

| # | Failure domain | Component in OUR system | Blast radius | Contained by |
|---|---|---|---|---|
| 1 | Host | | | |
| 2 | Rack | | | |
| 3 | Availability Zone | | | |
| 4 | Region | | | |
| 5 | Provider | | | |
| 6 | Global config push | | | |
| 7 | Deploy pipeline | | | |
| 8 | Schema migration | | | |
| 9 | Feature-flag service | | | |
| 10 | Shared cache entry | | | |
| 11 | Shared database | | | |
| 12 | DNS provider | | | |
| 13 | Certificate authority | | | |
| 14 | A single poison tenant | | | |

Rows 6–14 are the ones that cause the outages. If rows 3–5 are filled in and 6–14 are blank,
the review is not finished.

**Red flag:** any row with a 100% blast radius whose "contained by" cell says "monitoring",
"alerting", "on-call" or "runbook". None of those change a blast radius — they change a
detection time.

---

## 2. Correlated-failure audit

Naive availability math assumes independence. Compute what you actually have.

```text
P(system down) = c*p + (1 - c*p) * ((1-c)*p)^n

  p = per-instance unavailability      (1 - your measured instance availability)
  c = fraction of downtime that is COMMON CAUSE
  n = number of replicas / zones
```

Reference values at `p = 0.001` (99.9% per instance):

| `c` | 2 instances | nines | 3 instances | nines | ceiling |
|---|---|---|---|---|---|
| 0.000 | 99.9999000% | 6.00 | 99.9999999% | 9.00 | none |
| 0.010 | 99.9989020% | 4.96 | 99.9989999% | 5.00 | 5.00 |
| 0.100 | 99.9899190% | 4.00 | 99.9899999% | 4.00 | 4.00 |
| 0.500 | 99.9499750% | 3.30 | 99.9500000% | 3.30 | 3.30 |

**Estimating `c`:** take the last 8 incidents and count how many hit more than one AZ at once.
That ratio is your `c`, and it is always higher than anyone guesses. **The rule:** the ceiling is
`1 - c*p`. If your SLO needs more nines than that, replication cannot get you there — reduce `c`
by removing shared components, or change the SLO.

---

## 3. Shuffle sharding — implementation checklist

Only applies to multi-tenant request paths where one tenant's traffic can degrade a worker.

- [ ] Subset is a **pure function of tenant id** — no database, no cache, no stored assignment.
- [ ] Hash is **stable across processes**. Use `hashlib.sha256`, never Python's `hash()`
      (randomised per process by `PYTHONHASHSEED` — it re-shards everyone on restart).
- [ ] Worker list is **sorted before shuffling**, so discovery order cannot change assignments.
- [ ] `k >= 2`. At `k = 1` there is no failover target and this is fixed sharding with extra steps.
- [ ] Client **retries a different member of the subset** on timeout or error. Without this,
      shuffle sharding is measurably *worse* than a fixed shard: same `k/N` error volume,
      spread over ~4.6x more tenants.
- [ ] Retry is **budgeted** (a percentage of traffic, not a per-request count) and the
      operation is **idempotent** or carries an idempotency key.
- [ ] Balancing **within** the subset is power-of-two-choices, not round-robin, and failed
      members are marked unhealthy **locally** for a bounded window.
- [ ] Fleet membership changes move **only affected tenants** (rendezvous / consistent hashing),
      not everyone.
- [ ] A **re-shuffle mechanism** exists (override map or a shuffle epoch in the hash input),
      and override entries carry **expiry dates**. A list that only grows is a second,
      undocumented placement system.

### Choosing `k` (N = 100 workers)

| `k` | `C(100,k)` | P(full overlap) | Reach `k/N` | Pick when |
|---|---|---|---|---|
| 2 | 4,950 | 2.020e-04 | 2.0% | Many small tenants, no burst requirement |
| 3 | 161,700 | 6.184e-06 | 3.0% | Sensible default at thousands of tenants |
| 4 | 3,921,225 | 2.550e-07 | 4.0% | Route 53's choice for name servers |
| 5 | 75,287,520 | 1.328e-08 | 5.0% | Collisions vanish, reach still small |
| 8 | 186,087,894,300 | 5.374e-12 | 8.0% | Tenants need real burst headroom |

Sizing rules: pick the smallest `k` covering a tenant's p99 burst; require `1/C(N,k)` well below
`1/(tenants)^2`; `k/N` is the fraction of the fleet one tenant can damage, so large `k` trades
neighbour isolation for self-inflicted reach.

---

## 4. Cell sizing

Reference trade for a 24,000-tenant / 240,000 req/s fleet at 1,000 req/s per instance,
each cell provisioned at mean + 3 sigma plus one spare host:

| Cells | Tenants/cell | Instances | Capacity overhead | Deploy blast | Deploy time @20 min bake |
|---|---|---|---|---|---|
| 1 | 24,000 | 243 | 1.2% | 100.00% | 20 min |
| 4 | 6,000 | 248 | 3.3% | 25.00% | 80 min |
| 8 | 3,000 | 256 | 6.7% | 12.50% | 160 min |
| 24 | 1,000 | 288 | 20.0% | 4.17% | 480 min |
| 120 | 200 | 480 | 100.0% | 0.83% | 2400 min |

The knee is where overhead climbs faster than blast radius falls — around 24 cells here. Below
~4 instances per cell the spare host *is* the cell.

Cell rules:

- [ ] Everything on the request path is inside the cell. A cell that calls another cell is not a cell.
- [ ] The router does **no** database lookup, service call, or business logic. Static map, versioned,
      deployed like code, cached at every layer, readable from memory.
- [ ] Deploys go to **one cell first**, with a defined bake time and an automated rollback signal.
- [ ] Each cell has its own database. If it does not, the database is your real cell count.
- [ ] A documented, rehearsed procedure exists for moving a tenant between cells.
- [ ] Deploy time (cells x bake) is acceptable for a **hotfix**, or a documented emergency path
      skips waves and the risk is accepted in writing.

---

## 5. Static stability audit

For each item, the answer must be "no".

- [ ] Does serving a request require the control plane (any create/modify/discover API)?
- [ ] Does surviving an AZ loss require launching instances?
- [ ] Does surviving an AZ loss require a configuration change?
- [ ] Does the degraded/fallback path itself call a service that would be down?
- [ ] Does boot require fetching config from the network with no cached fallback?
- [ ] Does the shed / degrade path allocate, log per-request, or take a connection from the pool it protects?

Reference reaction budget when the answer is "yes" — measured for a 3-AZ fleet losing one zone:

```text
  60 s   metric aggregation window
+ 60 s   datapoints-to-alarm
+ 180 s  instance launch + boot + health check + LB registration
= 300 s  before the FIRST replacement serves a request
+ ramp   throttled, because the control plane is in the outage too

  measured: 450 s at 70% capacity, 11,250 requests lost
  pre-provisioned at 150% (50 per AZ): flat 100%, 0 lost, +43% hardware
```

Provisioning rule for N zones surviving one loss: **each zone carries `1/(N-1)` of peak demand** —
3 zones -> 50% each -> 150% total; 4 zones -> 33% each -> 133% total.

---

## 6. Verify, do not assume

```bash
# Are your replicas actually spread across zones? (a topology constraint you never
# set means the scheduler was free to put them all in one)
kubectl get pods -o custom-columns=\
'NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone'

# Envoy: zone-aware routing and the panic threshold that overrides it
#   min_cluster_size  - below this, zone-aware routing silently switches OFF
#   healthy_panic_threshold - below this % healthy, Envoy ignores health checks
#     and sprays to every host. A deliberate blast-radius trade in the other direction.
curl -s localhost:9901/config_dump | jq '.. | .zone_aware_lb_config? // empty'
curl -s localhost:9901/clusters | grep -E 'health_flags|zone'

# Certificate expiry is a fleet-wide failure domain. Track it as an SLO.
echo | openssl s_client -connect api.example.com:443 2>/dev/null \
  | openssl x509 -noout -enddate
```

---

## 7. Sign-off thresholds

Do not ship a multi-tenant service that fails any of these:

| Check | Threshold |
|---|---|
| Blast radius of one tenant's worst request | < 10% of tenants |
| Blast radius of one bad deploy | < 25% of tenants |
| Blast radius of one config push | < 25% of tenants |
| Effective `c` (multi-AZ incidents / total incidents) | documented, with the ceiling `1 - c*p` computed |
| Client failover to another subset member | implemented and load-tested |
| Survives losing 1 of N zones with no scaling action | yes |
| Tenant-to-cell move procedure | documented and rehearsed in the last 6 months |

Any row that fails gets a dated owner and a ticket, in the room, before anyone leaves.
