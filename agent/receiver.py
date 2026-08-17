#!/usr/bin/env python3
"""Cloud-side receiver for the segmented network lab.

Runs on the host machine, which sits outside the firewall — so from the camera's
point of view this genuinely is "the cloud": reachable only by traversing the
OPNsense WAN interface outbound.

Owning both ends is the point. A public test endpoint makes the server side a
black box, adds an internet dependency, and gives you nothing to debug when TLS
breaks. Here, a certificate failure is a failure you caused and can explain.

What it does beyond echoing back
--------------------------------

*Gap detection.* Tracks the last sequence number seen per device and reports any
hole. This is the mechanism behind the Day 6 claim: cut the network for two
minutes, restore it, and if the receiver reports zero gaps then the agent's
spool-and-flush actually worked. Without this the claim is unfalsifiable.

*Lag measurement.* Records `received_at - timestamp` for every heartbeat. During
normal operation this is milliseconds. After an outage, the flushed backlog
arrives with lag up to the length of the outage — which is what a recovery looks
like in data, and it makes a much better slide than "it seemed fine."

*A durable log.* Every accepted heartbeat is appended to JSON Lines so the run
can be analysed after the fact instead of scrolled back through.

Usage
-----
    pip install -r requirements.txt
    python3 receiver.py --cert server.crt --key server.key

    curl --cacert ca.crt https://cloud.lab.local:8443/stats
"""
from __future__ import annotations

import argparse
import datetime
import json
import threading
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

_lock = threading.Lock()
_devices: dict[str, dict] = {}
_log_path: Path | None = None
_started = datetime.datetime.now(datetime.timezone.utc)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _device_state(device_id: str) -> dict:
    return _devices.setdefault(
        device_id,
        {
            "device_id": device_id,
            "received": 0,
            "last_seq": 0,
            "highest_seq": 0,
            "gaps": [],          # [start, end] inclusive ranges never received
            "duplicates": 0,
            "out_of_order": 0,
            "max_lag_s": 0.0,
            "first_seen": None,
            "last_seen": None,
        },
    )


def _record(payload: dict, received_at: datetime.datetime) -> dict:
    """Update per-device state. Caller holds the lock."""
    device_id = str(payload.get("device_id", "unknown"))
    seq = int(payload.get("seq", 0))
    state = _device_state(device_id)

    lag = 0.0
    ts = payload.get("timestamp")
    if isinstance(ts, (int, float)):
        lag = max(0.0, received_at.timestamp() - float(ts))

    expected = state["highest_seq"] + 1
    if seq > expected:
        # Hole. Recorded rather than counted so the deck can say which records
        # were lost, not just how many.
        state["gaps"].append([expected, seq - 1])
    elif seq <= state["highest_seq"]:
        # Arrived after a higher sequence number already did. A spool flush
        # replays in order, so this means a genuine reordering or a replay.
        if any(seq >= g[0] and seq <= g[1] for g in state["gaps"]):
            state["gaps"] = _close_gap(state["gaps"], seq)
            state["out_of_order"] += 1
        else:
            state["duplicates"] += 1

    state["highest_seq"] = max(state["highest_seq"], seq)
    state["last_seq"] = seq
    state["received"] += 1
    state["max_lag_s"] = round(max(state["max_lag_s"], lag), 3)
    state["last_seen"] = received_at.isoformat()
    if state["first_seen"] is None:
        state["first_seen"] = received_at.isoformat()

    return {"lag": lag, "state": state}


def _close_gap(gaps: list[list[int]], seq: int) -> list[list[int]]:
    """Remove seq from the recorded gaps, splitting a range if it lands inside."""
    out = []
    for start, end in gaps:
        if seq < start or seq > end:
            out.append([start, end])
            continue
        if start <= seq - 1:
            out.append([start, seq - 1])
        if seq + 1 <= end:
            out.append([seq + 1, end])
    return out


@app.post("/heartbeat")
def heartbeat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "device_id" not in payload:
        return jsonify({"ack": False, "error": "malformed payload"}), 400

    received_at = _now()
    with _lock:
        result = _record(payload, received_at)
        state = result["state"]
        open_gaps = sum(e - s + 1 for s, e in state["gaps"])

        if _log_path is not None:
            record = dict(payload)
            record["received_at"] = received_at.isoformat()
            record["lag_s"] = round(result["lag"], 3)
            with _log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")

    flag = ""
    if result["lag"] > 30:
        flag = f"  LATE(+{result['lag']:.0f}s)"      # a flushed backlog record
    if open_gaps:
        flag += f"  GAPS({open_gaps})"

    print(
        f"{received_at.astimezone():%H:%M:%S}  {payload['device_id']:<10}"
        f"  seq={payload.get('seq'):<6} status={payload.get('status')}{flag}",
        flush=True,
    )

    return jsonify({"ack": True, "server_time": received_at.isoformat()})


@app.get("/stats")
def stats():
    """Machine-readable summary. This is the evidence for 'we lost nothing'."""
    with _lock:
        devices = []
        for state in _devices.values():
            entry = dict(state)
            entry["missing"] = sum(e - s + 1 for s, e in state["gaps"])
            entry["delivery_ratio"] = (
                round(state["received"] / state["highest_seq"], 4)
                if state["highest_seq"]
                else None
            )
            devices.append(entry)
    return jsonify(
        {
            "server_started": _started.isoformat(),
            "uptime_s": round((_now() - _started).total_seconds(), 1),
            "devices": devices,
        }
    )


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


def replay(log_path: Path) -> int:
    """Rebuild per-device state from the log written by previous runs.

    Without this, restarting the receiver resets `highest_seq` to 0, and the
    next heartbeat to arrive looks like it skipped every sequence number before
    it — the receiver reports a large gap that never happened. Since the whole
    point of the gap counter is to substantiate "we lost nothing", a counter
    that fabricates losses on restart is worse than none.

    The log is append-only and already contains everything needed, so replaying
    it is enough; no separate state file.
    """
    if not log_path.exists():
        return 0
    replayed = 0
    with log_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                received_at = datetime.datetime.fromisoformat(record["received_at"])
            except (ValueError, KeyError):
                continue
            _record(record, received_at)
            replayed += 1
    return replayed


def main() -> None:
    global _log_path

    p = argparse.ArgumentParser(description="Segmented lab cloud receiver")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--cert", default="server.crt")
    p.add_argument("--key", default="server.key")
    p.add_argument(
        "--log",
        default="received.jsonl",
        help="JSON Lines log of every accepted heartbeat ('' to disable)",
    )
    p.add_argument(
        "--no-replay",
        action="store_true",
        help="start with empty state instead of rebuilding from --log",
    )
    args = p.parse_args()

    for path in (args.cert, args.key):
        if not Path(path).exists():
            raise SystemExit(
                f"{path} not found — run provisioning/make-certs.sh in this directory first"
            )

    if args.log:
        _log_path = Path(args.log)
        if not args.no_replay:
            n = replay(_log_path)
            if n:
                seen = {d: s["highest_seq"] for d, s in _devices.items()}
                print(f"replayed {n} heartbeat(s) from {args.log}; highest seq {seen}")

    print(f"receiver listening on https://{args.host}:{args.port}")
    print(f"  cert     {args.cert}")
    print(f"  log      {args.log or '(disabled)'}")
    print(f"  stats    https://cloud.lab.local:{args.port}/stats\n")

    app.run(
        host=args.host,
        port=args.port,
        ssl_context=(args.cert, args.key),
        threaded=True,
    )


if __name__ == "__main__":
    main()
