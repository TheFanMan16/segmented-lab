# Bandwidth

**Method note.** Every figure below exists twice: a **predicted** value derived
analytically from the protocol and the agent's fixed payload, and a **measured**
value taken from `captures/phonehome-tls.pcap`. Predictions were computed before
capture, deliberately — comparing the two is more informative than reporting
either alone, and a large delta is a finding worth chasing rather than an
embarrassment.

Measured columns are filled in from `analyze-pcap.sh`, which produces them
reproducibly instead of by clicking around Wireshark.

Status: predictions complete; measured column pending lab run.

---

## Where the predictions come from

The agent sends a fixed-shape payload, so its serialized size is deterministic:

```json
{"device_id": "cam-01", "seq": 8640, "timestamp": 1786481090.993466, "status": "healthy", "events": 0}
```

That is **102 bytes** (Python's `json.dumps` default separators include a space
after `:` and `,`; `seq` reaches four digits at 8,640 heartbeats, one day at a
10-second interval).

Request headers emitted by `requests` add **214 bytes**:

```
POST /heartbeat HTTP/1.1 · Host · User-Agent · Accept-Encoding · Accept
Connection: keep-alive · Content-Length · Content-Type: application/json
```

Response body is **62 bytes** (verified against the running receiver in a
loopback harness, not yet in the segmented lab), plus roughly 150 bytes of
Werkzeug response headers.

Framing added per record and segment:

| Layer | Overhead | Why |
|---|---|---|
| TLS 1.3 record | +22 B | 5 B header, 1 B content type, 16 B AEAD tag |
| TCP + IPv4 | +52 B | 20 B IP, 20 B TCP, ~12 B timestamp option |

## Per heartbeat

| Metric | Predicted | Measured | Notes |
|---|---|---|---|
| JSON payload | 102 B | | the only part carrying meaning |
| HTTP request, total app data | 316 B | | 214 B headers + 102 B body |
| HTTP response, total app data | ~212 B | | 62 B body + ~150 B headers |
| **On the wire, connection reused** | **~780 B** | | both directions, incl. TLS framing, TCP headers, ACKs |
| **On the wire, new connection** | **~3.8 KB** | | adds TCP + TLS 1.3 handshake with an RSA-2048 cert |

Capture both cases: run the agent normally, then with `--no-reuse`. That flag
exists specifically to make this measurable.

## Per device

| Interval | Heartbeats | Predicted, reused | Predicted, new conn | Measured |
|---|---|---|---|---|
| Hour | 360 | ~281 KB | ~1.37 MB | |
| Day | 8,640 | ~6.7 MB | ~32.8 MB | |

## Fleet arithmetic — 50 devices, 100 Mbps uplink

```
  heartbeats/hour/device        = 3600 / 10        =     360
  devices                       =                        50
  heartbeats/hour (fleet)       = 360 × 50         =  18,000

  reused:      18,000 × 780 B   = 14.0 MB/hour → 14.0e6 × 8 / 3600 ≈  31 kbps
  new conn:    18,000 × 3.8 KB  = 68.4 MB/hour → 68.4e6 × 8 / 3600 ≈ 152 kbps
```

| Scenario | Fleet bytes/hr | Sustained | % of 100 Mbps |
|---|---|---|---|
| Connection reused | ~14.0 MB | ~31 kbps | ~0.03% |
| New handshake each time | ~68.4 MB | ~152 kbps | ~0.15% |

**Read this result honestly.** The absolute bandwidth is negligible — a fleet of
50 cameras sending status is a rounding error on a 100 Mbps uplink either way.
That is the correct thing to tell a customer, and it is reassuring rather than
impressive.

The interesting number is the ratio, not the total.

## Overhead ratio — the actual insight

| | Bytes (predicted) | Share of wire |
|---|---|---|
| JSON payload | 102 B | **~13%** reused / **~2.7%** new connection |
| HTTP framing | ~364 B | |
| TLS record + handshake | +22 B/record, ~3 KB handshake | |
| TCP/IP headers | 52 B/segment | |

**Roughly 87% of steady-state traffic is envelope, and about 97% if the
connection is not reused.** A 102-byte status update costs ~780 bytes to
deliver, or ~3.8 KB if you rebuild the TLS session each time.

That is the finding worth presenting, because it explains real product
decisions: it is why fleets keep connections alive, batch multiple updates into
one request, and use compact binary encodings instead of pretty-printed JSON.
At 50 devices none of that matters. At 50,000 it is the whole design.

## Caveats

State these when presenting the numbers — an extrapolation nobody can challenge
is one nobody should trust:

- 10-second interval chosen for demo convenience; real devices report far less
  often, which reduces totals and *increases* the relative handshake cost.
- One device measured, fifty extrapolated. No per-device variance.
- Status heartbeats only — no video, no firmware updates, no configuration
  pulls, which in a real deployment dominate everything measured here.
- Steady state only. The reconnect storm after a fleet-wide outage is the
  genuine peak, and it is not captured by this arithmetic.
- Predictions assume TLS 1.3 with a single RSA-2048 server certificate. A longer
  chain or a different key type moves the handshake figure.
