# Deck outline — 10 minutes

_(Day 7 afternoon.)_

The lab is not the output. This is. Ten minutes, then rehearse it out loud
**five times** — not four, and not silently in your head. The parts you built
fastest this week are the parts you are most likely to fumble out loud, so
rehearse those first.

---

## Slide plan

| # | Slide | Time | Content |
|---|---|---|---|
| 1 | The problem | 1:00 | A customer's security team is asked to open inbound ports for cameras. They say no, correctly. Deployment stalls. |
| 2 | Architecture | 1:30 | The topology diagram. Two segments, one firewall, one direction of travel. |
| 3 | The claim | 0:30 | Full cloud management, zero inbound rules. State it plainly before proving it. |
| 4 | Demo / capture walkthrough | 3:00 | The heartbeat working, then the state table entry that permits the response. |
| 5 | Segmentation proof | 1:00 | Camera cannot reach corporate. Show the blocked packet in the live log. |
| 6 | Measurements | 1:30 | Bytes per heartbeat, per fleet, and the overhead ratio. |
| 7 | What broke | 1:30 | The failure matrix — lead with clock skew. |
| 8 | What I'd do differently | 0:30 | Honest, short, specific. |

## Slide 4 — the demo

Record a backup capture walkthrough even if you plan to demo live. A live demo
that fails in front of an audience costs more than a recording that works.

Point at, in order:
1. The agent's output on `cam-01` — a heartbeat succeeding.
2. The receiver's log on the host — the same `seq` arriving.
3. The state table entry in OPNsense, live.
4. The WAN rules page — **empty**.

The fourth one is the punchline. Let it sit for a second.

## Slide 7 — what broke

Lead with **clock skew**, not blocked ports. Everyone in the room has blocked a
port. Far fewer have diagnosed a fleet that went dark simultaneously because
certificate validation started failing everywhere at once.

The follow-up question is always "how would the customer know?" — have the
answer from the detection section of the failure matrix ready.

## Anticipated questions

Answers are written out in full in
[`../docs/design-decisions.md`](../docs/design-decisions.md) — read them, then
say them in your own words. Reciting them verbatim is worse than paraphrasing
badly, because the follow-up question exposes it immediately.

- "Why not just use a VPN?"
- "What if the cloud is down?"
- "How is this different from a port forward with an ACL?"
- "You used internal networks, not VLANs — does that change the conclusion?"
- "What happens on a dual-stack network?"
- "How would you scale this to 500 devices instead of 50?"
- "What would you do differently?"

The strongest move on the VLAN question is to volunteer the limitation before
being asked. Saying "these are internal networks, not tagged VLANs, and here is
exactly what that does and doesn't prove" reads as judgment. Being caught on it
reads as overstatement.

## The rule

If you cannot explain it out loud without notes, you have not learned it. Apply
that hardest to whatever you built fastest.

- [ ] Rehearsal 1
- [ ] Rehearsal 2
- [ ] Rehearsal 3
- [ ] Rehearsal 4
- [ ] Rehearsal 5
