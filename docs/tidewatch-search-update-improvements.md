# TideWatch Improvements: Update Detection + Performance

## Update Detection Correctness + Traceability
- Add a structured decision trace per update (why/why-not) with fields like:
  - current_tag, latest_tag, scope, change_type, include_prereleases
  - suffix_match, digest_changed, registry, candidate_count, filtered_counts
- Distinguish tag-based vs digest-based updates (especially for "latest") via an update_kind enum.
- Persist scope blocking details (e.g., latest_major_tag) and the rationale so the UI can explain why an update is blocked.
- Record tag-pattern decisions (suffix/track) to prevent incorrect cross-track jumps.
- Surface prerelease filtering results (prerelease available but excluded).
- Flag registry anomalies (e.g., latest tag older than current) and avoid auto-approving on anomalies.
- Make from_tag/to_tag immutable after creation, or maintain a change audit trail.

## Performance + Scalability
- Use bounded concurrency for update checks, with per-registry rate limiting to avoid throttling.
- Cache tag lists per image+scope+include_prereleases during a run to avoid duplicate registry calls.
- Deduplicate checks by grouping containers with identical image+tag+scope+include_prereleases.
- Separate "fetch tags" from "decide update" to make caching and traceability consistent.
- Add a warm-cache background updater so user-triggered checks are mostly DB reads.
- Instrument timings and counters (registry call count, cache hit rate, per-container latency).

## Background Check + Live Progress (Recommended)
- Add an update check job model (queued/running/done/failed/canceled) with counters and timestamps.
- Replace the blocking /updates/check call with job creation + background worker.
- Expose SSE (or WS) stream for progress updates; fallback to polling job status.
- UI shows progress bar + container name + counts, then refreshes update list on completion.

