"""Root-only credential socket for systemd 247-249; never part of the agent API."""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
from pathlib import Path

from deployment.appliance_credentials import HostCredentials, protect_process

HOST_KEY = Path("/etc/kai-host-key/host.key")
WRAPPED_MASTER = Path("/etc/kai/credentials/provider-master.enc")
SOCKET = "/run/kai-credentials.sock"
LIBRARY = Path("/usr/local/lib/kai-credentials")
SOCKET_UNIT = "kai-credentials.socket"
SERVICE_UNIT = "kai-credentials@.service"


def serve(connection: socket.socket, credentials: HostCredentials) -> None:
    """Only PID 1/root may fetch a master; authentication completes before sending."""
    peer = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", peer)
    if uid != 0:
        raise ValueError("Only the system service manager may request credentials.")
    connection.sendall(credentials.master())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("provision", "serve"))
    args = parser.parse_args(argv)
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("The credential helper requires root.")
    protect_process()
    try:
        credentials = HostCredentials(HOST_KEY, WRAPPED_MASTER)
        if args.mode == "provision":
            credentials.provision()
        else:
            with socket.socket(fileno=os.dup(0)) as connection:
                serve(connection, credentials)
    except (OSError, ValueError):
        print(
            "Host credential authentication/delivery failed; original data kept.", file=sys.stderr
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
