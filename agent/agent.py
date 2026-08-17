#!/usr/bin/env python3
"""Device agent for the segmented network lab.

Simulates a cloud-managed device (an IP camera) sitting on an isolated network
segment. It initiates every connection outbound, authenticates the cloud
endpoint against a lab-issued CA, and does not lose status records when the
network fails.

Design notes
------------

*Sequence numbers are monotonic and persisted across restarts.* This is what
makes "no heartbeats were lost" a checkable claim rather than an assertion —
the receiver flags any gap in the sequence it observes. A counter that resets on
reboot would hide exactly the failure we care about.

*Failures are classified, not just caught.* A blocked port and a blocked
resolver both look like "the device is offline" to a user, but they are
different failures with different fixes and very different detection times. The
failure matrix in `measurements/` depends on being able to tell them apart, so
the agent names the failure mode instead of printing a stack trace.

*The payload is a fixed shape.* Field order and types do not vary, so byte
counts are comparable across runs and the bandwidth arithmetic in
`measurements/bandwidth.md` holds.

*There is no way to disable certificate verification.* Deliberate. A device
that can be talked out of validating its server is a device that can be
man-in-the-middled on any hostile network, and "just turn off verify" is how
that ships. If the trust chain is wrong, the agent fails loudly and the error
tells you which part is wrong.

Usage
-----
    python3 agent.py                        # run until interrupted
    python3 agent.py --once                 # one heartbeat; exit status reflects result
    python3 agent.py --no-reuse             # new TCP+TLS connection per heartbeat
    python3 agent.py --interval 5 --verbose

Every option also reads from the environment (LAB_ENDPOINT, LAB_CA, and so on)
so the systemd unit in provisioning/ can configure it without editing this file.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import sys
import time
from pathlib import Path

import requests
import requests.exceptions as rex

DEFAULT_ENDPOINT = os.environ.get(
    "LAB_ENDPOINT", "https://cloud.lab.local:8443/heartbeat"
)
DEFAULT_CA = os.environ.get("LAB_CA", "/etc/ssl/lab/ca.crt")
DEFAULT_INTERVAL = float(os.environ.get("LAB_INTERVAL", "10"))
DEFAULT_STATE_DIR = Path(os.environ.get("LAB_STATE_DIR", "/var/lib/segmented-lab"))
DEFAULT_TIMEOUT = float(os.environ.get("LAB_TIMEOUT", "10"))

BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0
FLUSH_BATCH = 200

_running = True


def _stop(signum, _frame):
    global _running
    _running = False
    log("shutdown", f"caught {signal.Signals(signum).name}, finishing current cycle")


def log(kind: str, message: str) -> None:
    """One line per event, timestamped, greppable.

    Format is stable on purpose: the failure matrix quotes these lines directly
    and `measurements/break.sh` greps them.
    """
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [{kind}] {message}", flush=True)


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------

def classify(exc: BaseException) -> str:
    """Map an exception to a short, stable failure label.

    These labels are the row keys in measurements/failure-matrix.md. Scenario 2
    (DNS blocked) and scenario 1 (egress blocked) must not collapse into the
    same string, or the matrix says nothing.
    """
    text = str(exc)

    if isinstance(exc, rex.SSLError):
        if "certificate is not yet valid" in text:
            return "tls-cert-not-yet-valid"
        if "certificate has expired" in text:
            return "tls-cert-expired"
        if "unable to get local issuer" in text or "self-signed" in text:
            return "tls-untrusted-issuer"
        if "Hostname mismatch" in text or "doesn't match" in text:
            return "tls-hostname-mismatch"
        return "tls-other"

    if isinstance(exc, rex.ConnectTimeout):
        return "connect-timeout"
    if isinstance(exc, rex.ReadTimeout):
        return "read-timeout"

    if isinstance(exc, rex.ConnectionError):
        if (
            "Name or service not known" in text
            or "Temporary failure in name resolution" in text
            or "gaierror" in text
            or "nodename nor servname" in text
        ):
            return "dns-resolution"
        # Second form is Windows; the lab runs Linux but the agent is also run
        # on the host during bring-up, and a mode label that silently degrades
        # to "connect-other" on one platform makes the failure matrix wrong.
        if "Connection refused" in text or "actively refused" in text:
            return "connect-refused"
        if "Network is unreachable" in text:
            return "network-unreachable"
        if "No route to host" in text:
            return "no-route"
        return "connect-other"

    if isinstance(exc, rex.HTTPError):
        return "http-error"
    return f"unknown:{type(exc).__name__}"


# --------------------------------------------------------------------------
# Durable state: sequence number and the outage spool
# --------------------------------------------------------------------------

class Store:
    """Sequence counter and failed-heartbeat spool, both on disk.

    The spool is JSON Lines so it can be appended to without rewriting, read
    back in order, and inspected with `wc -l` while an outage is in progress.
    """

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.state_path = state_dir / "state.json"
        self.spool_path = state_dir / "spool.jsonl"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            fallback = Path.home() / ".segmented-lab"
            fallback.mkdir(parents=True, exist_ok=True)
            log("warn", f"{state_dir} not writable, using {fallback}")
            self.dir = fallback
            self.state_path = fallback / "state.json"
            self.spool_path = fallback / "spool.jsonl"

    def next_seq(self) -> int:
        seq = 0
        if self.state_path.exists():
            try:
                seq = int(json.loads(self.state_path.read_text()).get("seq", 0))
            except (ValueError, OSError):
                log("warn", "state file unreadable, restarting sequence at 1")
        seq += 1
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seq": seq}))
        tmp.replace(self.state_path)  # atomic: a crash mid-write cannot corrupt it
        return seq

    def spool(self, payload: dict) -> int:
        with self.spool_path.open("a") as fh:
            fh.write(json.dumps(payload) + "\n")
        return self.depth()

    def depth(self) -> int:
        if not self.spool_path.exists():
            return 0
        with self.spool_path.open() as fh:
            return sum(1 for _ in fh)

    def read_spool(self) -> list[dict]:
        if not self.spool_path.exists():
            return []
        out = []
        with self.spool_path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        log("warn", "dropping corrupt spool line")
        return out

    def rewrite_spool(self, remaining: list[dict]) -> None:
        tmp = self.spool_path.with_suffix(".tmp")
        with tmp.open("w") as fh:
            for item in remaining:
                fh.write(json.dumps(item) + "\n")
        tmp.replace(self.spool_path)


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

class Cloud:
    def __init__(self, endpoint: str, ca: str, timeout: float, reuse: bool):
        self.endpoint = endpoint
        self.ca = ca
        self.timeout = timeout
        self.reuse = reuse
        self.session = requests.Session() if reuse else None

    def post(self, payload: dict) -> tuple[int, int]:
        """Send one heartbeat. Returns (status_code, response_bytes).

        Raises on any failure; the caller classifies it.
        """
        caller = self.session or requests
        r = caller.post(
            self.endpoint, json=payload, timeout=self.timeout, verify=self.ca
        )
        r.raise_for_status()
        return r.status_code, len(r.content)


def build_payload(device_id: str, seq: int) -> dict:
    """Fixed shape, ~99 bytes serialized. See docs/ for the byte-level breakdown."""
    return {
        "device_id": device_id,
        "seq": seq,
        "timestamp": round(time.time(), 6),
        "status": "healthy",
        "events": 0,
    }


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def run(args) -> int:
    device_id = args.device_id or socket.gethostname()
    store = Store(Path(args.state_dir))
    cloud = Cloud(args.endpoint, args.ca, args.timeout, reuse=not args.no_reuse)

    if not Path(args.ca).exists():
        log("fatal", f"CA bundle not found at {args.ca} — see provisioning/setup.md")
        return 2

    log(
        "start",
        f"device={device_id} endpoint={args.endpoint} interval={args.interval}s "
        f"reuse={not args.no_reuse} spool_depth={store.depth()}",
    )

    failures = 0
    last_label = None

    while _running:
        seq = store.next_seq()
        payload = build_payload(device_id, seq)

        try:
            # Drain the backlog first so the receiver sees an unbroken sequence.
            # Oldest-first: a gap-free record of an outage is the whole point.
            flushed = flush_spool(cloud, store)
            if flushed:
                log("flush", f"delivered {flushed} buffered heartbeat(s)")

            status, nbytes = cloud.post(payload)
            if failures:
                log("recovered", f"after {failures} consecutive failure(s)")
            failures = 0
            last_label = None
            log("ok", f"seq={seq} status={status} resp_bytes={nbytes}")

        except Exception as exc:  # noqa: BLE001 - deliberately broad; classify() names it
            failures += 1
            label = classify(exc)
            depth = store.spool(payload)
            if label != last_label:
                # Full detail on the first occurrence, then just the label, so a
                # long outage does not bury the transition in repeated text.
                log("fail", f"seq={seq} mode={label} detail={exc}")
                last_label = label
            else:
                log("fail", f"seq={seq} mode={label} (repeat #{failures})")
            log("buffered", f"seq={seq} spool_depth={depth}")

            if args.once:
                return 1

            delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (failures - 1)))
            delay *= 0.8 + 0.4 * random.random()  # jitter: 50 devices must not sync up
            log("backoff", f"sleeping {delay:.1f}s before retry")
            sleep_interruptible(delay)
            continue

        if args.once:
            return 0
        sleep_interruptible(args.interval)

    log("stop", f"exiting cleanly, spool_depth={store.depth()}")
    return 0


def flush_spool(cloud: Cloud, store: Store) -> int:
    """Deliver buffered heartbeats oldest-first.

    Stops at the first failure and keeps the undelivered remainder, so a flush
    that dies halfway through does not drop the tail. Bounded per cycle: after a
    long outage we would otherwise block the current heartbeat behind thousands
    of replays.
    """
    backlog = store.read_spool()
    if not backlog:
        return 0

    sent = 0
    for item in backlog[:FLUSH_BATCH]:
        try:
            cloud.post(item)
            sent += 1
        except Exception:  # noqa: BLE001 - the caller's next cycle will classify it
            break

    store.rewrite_spool(backlog[sent:])
    return sent


def sleep_interruptible(seconds: float) -> None:
    """Sleep in slices so SIGTERM is honoured promptly."""
    deadline = time.monotonic() + seconds
    while _running and time.monotonic() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Segmented lab device agent")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--ca", default=DEFAULT_CA, help="CA bundle used to verify the server")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument("--device-id", default=os.environ.get("LAB_DEVICE_ID"))
    p.add_argument("--once", action="store_true", help="send one heartbeat and exit")
    p.add_argument(
        "--no-reuse",
        action="store_true",
        help="new TCP+TLS connection per heartbeat (use this to measure handshake cost)",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        sys.exit(run(parse_args()))
    except KeyboardInterrupt:
        sys.exit(0)
