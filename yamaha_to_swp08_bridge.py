#!/usr/bin/env python3
"""
Yamaha QL5 → SW-P-08 bridge for Cerebrum.

This script:
- Connects to a Yamaha mixer via the RCP protocol (TCP/49280)
- Polls fader open/closed state for all input channels
- Exposes a router-style SW-P-08 interface for Cerebrum

Router model (per-channel tally bus):
- Sources (inputs):
    0 = NC
    1..N = channel tally sources (one per Yamaha input channel)
- Destinations (outputs) 0..N-1:
    Each destination represents a "tally output" for the corresponding channel.
    When a channel is OPEN, we route source (channel index + 1) to that dest.
    When CLOSED, we route NC (0).

From Cerebrum's point of view, you get an N×N+1 router where each output
encodes the tally state of a single channel in a familiar way.
"""

import argparse
import threading
import time
from typing import Optional

from yamaha_cerebrum_client import YamahaRcpClient
from swp08_server import SWP08Server, RouterState


QL5_INPUT_CHANNELS = 40


def build_router_state(router_name: str, channels: int) -> RouterState:
    """
    Create a RouterState where:
    - num_outputs = number of Yamaha input channels (destinations)
    - num_sources = 1 (NC) + N channel sources
    """
    return RouterState(
        node_id="yamaha",
        node_name=router_name,
        num_outputs=channels,
        num_sources=1 + channels,  # 0 = NC, 1..N = per-channel tally sources
    )


def poll_yamaha_and_update_router(
    client: YamahaRcpClient,
    router_state: RouterState,
    poll_interval: float,
    channels: int,
) -> None:
    """
    Poll Yamaha fader state and update RouterState in a loop.
    """
    reconnect_backoff = 2.0
    max_backoff = 30.0

    while True:
        if client.sock is None:
            ok, msg = client.connect()
            print(msg, flush=True)
            if not ok:
                time.sleep(reconnect_backoff)
                reconnect_backoff = min(max_backoff, reconnect_backoff * 1.5)
                continue
            reconnect_backoff = 2.0

        for ch in range(channels):
            state = client.get_fader_open_state(ch)
            # Source index: 0 = NC, 1..N = channels 1..N
            source = (ch + 1) if state else 0
            router_state.set_crosspoint(ch, source)
            time.sleep(0.01)  # small delay per channel to avoid hammering mixer

        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Yamaha QL5 → SW-P-08 bridge for Cerebrum")
    parser.add_argument("--yamaha-ip", required=True, help="Yamaha mixer IP address")
    parser.add_argument(
        "--swp08-port",
        type=int,
        default=2000,
        help="TCP port to listen for SW-P-08 (Cerebrum connects here)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds between full mixer scans",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=QL5_INPUT_CHANNELS,
        help="Number of input channels to expose (destinations)",
    )
    parser.add_argument(
        "--router-name",
        default="YamahaQL",
        help="Name used in SW-P-08 mnemonics",
    )

    args = parser.parse_args()

    client = YamahaRcpClient(args.yamaha_ip)
    # Connect once up-front so we can fetch labels before starting SW-P-08
    ok, msg = client.connect()
    print(msg, flush=True)

    router_state = build_router_state(args.router_name, args.channels)

    # Fetch channel labels from Yamaha (best-effort). If unavailable, fall back to CH n.
    labels = []
    for ch in range(args.channels):
        label = client.get_channel_label_name(ch) if ok else None
        if not label:
            label = f"CH {ch + 1}"
        labels.append(label)
    router_state.dest_labels = labels

    server = SWP08Server(host="0.0.0.0", port=args.swp08_port, router_state=router_state)

    poll_thread = threading.Thread(
        target=poll_yamaha_and_update_router,
        args=(client, router_state, args.poll_interval, args.channels),
        daemon=True,
    )
    poll_thread.start()

    try:
        server.start()
    except KeyboardInterrupt:
        print("Shutting down SW-P-08 bridge...", flush=True)
    finally:
        server.stop()
        client.close()


if __name__ == "__main__":
    main()

