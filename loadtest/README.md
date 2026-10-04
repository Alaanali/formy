# Load and scalability testing

```bash
make bootstrap          # containers, keys, migrations, seeded survey
make run-load           # REQUIRED: throttles raised for a single-IP generator
make worker             # in another shell, for exports
make load-headless      # fixed profile, HTML report, exits non-zero on breach
```

`make run` will not do: the per-IP throttles reject most of the burst and
the run fails for the wrong reason.

`make load` opens the Locust web UI instead, at <http://localhost:8089>.

The run needs no arguments: it finds the published version itself. Override
with `--version-id` if you have several.

## Why the throttles are raised

A load test comes from one address, so the per-IP rate limits that protect
the real deployment would cap the generator rather than the application.
`make run-load` raises them; nothing else does.

## What the thresholds assert

A load test that only prints numbers gets skimmed, so the run fails on
breach. The budgets encode the two claims the architecture makes:

| Request | Budget (p95) | The claim it tests |
|---|---|---|
| `GET results` | 500 ms | analytics are maintained incrementally, so dashboard latency does not grow with responses collected |
| `PATCH autosave` | 400 ms | the hot write path does not degrade as the answer table grows |
| `POST start submission` | 400 ms | |
| `POST submit` | 800 ms | validation, encryption and rollup folding stay within budget |

Plus an overall failure ratio under 1%.

## Measured

Single dev server (`runserver`, one process), one Postgres container, 40
concurrent users for 60 seconds, on a developer laptop:

```
3800+ requests, 0 failures, ~76 req/s
789 submissions started, 788 completed

                          samples    p50     p95
POST start submission         789    4ms     37ms
GET  submission state         789   43ms     50ms
PATCH autosave               1862   47ms     65ms
POST submit                   788   47ms     61ms
GET  results                  177   13ms     22ms
GET  submission list           57   44ms    110ms
```

`GET results` is the row that matters. It was polled throughout while 788
responses were written, and stayed at 13ms median — it reads pre-aggregated
rows and never touches the answer table. If that number starts tracking
write volume, the rollups have stopped being maintained incrementally.

`GET submission list` is the slowest read by a wide margin, and that is
expected: it is unpaginated and sorted, so its cost grows directly with
responses collected. It has the loosest budget here for that reason, and
pagination is the fix before this reaches real volume.

### On reading these numbers honestly

An earlier version of this file quoted `GET results` at 64ms p95 from 16
samples. locust computes a percentile as `int(n * percent)`, so at n=16 the
"p95" is simply the slowest request — a cold start, not a steady state. The
scenario now paces the staff profile at a fixed rate and the run refuses to
pass on fewer than 40 samples for any budgeted request, so a number this
file quotes is a measurement rather than an outlier.

Absolute throughput means little: this is `runserver`, single-process,
against a database on the same machine. The *shape* — flat read latency
under sustained writes, zero failures — is what transfers.

## What else to watch

- **Autosave p95 drifting upward over a long run.** Index bloat on the
  answer table. `fillfactor = 80` and the heap-only-tuple path exist to
  delay it; table partitioning by survey_version is the next step.
- **Database connections.** Past roughly a hundred concurrent workers this
  is the first wall, and PgBouncer in transaction mode is the answer.
- **Schema reads.** They barely register here because the version is
  immutable and cached; in production a CDN should absorb them entirely.
