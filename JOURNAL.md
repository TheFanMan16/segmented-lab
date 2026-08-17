# Journal

Appended every session. The **"what blocked me and what unblocked it"** line is
the point of this file — it is the learning artifact, not a status log.

Rule for the week: look things up only when blocked, and only the specific thing
blocking you. Then write it down here.

---

## Template — copy this

```
## YYYY-MM-DD — Day N
Goal:
What I actually did:
What blocked me and what unblocked it:      <- the important one
What surprised me:
Could I explain today's work cold? (y/n)
```

---

## 2026-08-11 — Day 0

**Goal:** Repo, agent, receiver, policy design and documentation complete before
the VMs exist, so build nights are spent on the network rather than on Python.

**What I actually did:**
- Wrote the device agent and the cloud receiver, and tested them end-to-end over
  loopback TLS against a self-issued CA before any VM existed.
- Wrote the firewall policy with justifications, plus `verify-policy.sh` to
  assert it from both segments.
- Computed bandwidth predictions analytically so the capture has something to be
  compared against rather than just reported.
- Wrote `docs/` — packet walkthroughs, failure modes, design decisions.

**What blocked me and what unblocked it:**
The receiver invented a gap that never happened. Sequence tracking lived in
memory, so restarting the receiver reset `highest_seq` to 0, and the next
heartbeat — seq 4 — looked like it had skipped 1 through 3. `/stats` reported
`missing: 3` on a run where nothing was lost.

Unblocked by making the receiver replay its own append-only log on startup
rather than adding a second state file. The log already contained everything
needed. The general lesson is worth keeping: **a metric that fabricates failures
is worse than no metric**, because the whole purpose of the gap counter is to
substantiate "we lost nothing," and one that cries wolf on restart cannot do
that job.

Second, smaller one: failure classification returned `connect-other` where it
should have said `connect-refused`, because I matched on the Linux error string
and was testing on Windows. Caught only because the label was wrong in the test
output — which is an argument for classifying failures explicitly instead of
printing exceptions, since a stack trace would have looked fine.

**What surprised me:**
How lopsided the overhead is. A 102-byte status update costs ~780 bytes on the
wire with a reused connection and ~3.8 KB without one. I expected maybe 2x. It's
closer to 8x, and 37x if you rebuild TLS each time. The bandwidth total is
trivial at 50 devices — the *ratio* is the finding, and it explains product
decisions I'd previously just accepted as convention.

**Could I explain today's work cold? (y/n)** y for the agent, the spool/replay
logic and the overhead arithmetic. Not yet for the state table walkthrough —
that one needs to be done against a real capture, not read about.

**Next:** VMs. Adapter order before first boot, interfaces assigned manually.
