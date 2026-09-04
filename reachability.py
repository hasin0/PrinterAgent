"""
reachability.py
PrinterAgent - Printer reachability check (Windows-safe, low socket usage)

Distinguishes a genuinely OFFLINE printer from one that is ONLINE but has
SNMP disabled.

IMPORTANT (Windows fix):
  This version uses PLAIN synchronous sockets run in a thread executor,
  probed ONE PORT AT A TIME with immediate close. This avoids the
  "ValueError: too many file descriptors in select()" crash that occurs
  on Windows when too many async sockets are registered in the event
  loop's selector at once (Windows select() caps at 512 FDs).

  Because these sockets are opened+closed inside worker threads and are
  never registered with the asyncio selector, they add ZERO pressure to
  the event loop's FD set.

Ports probed (first hit wins, checked in order):
    9100  Raw print (JetDirect/RAW) - almost all network printers
    80    Web UI (HTTP)
"""

import socket
import asyncio

# Keep this SHORT - only the two ports virtually every printer exposes.
# Fewer ports = fewer sockets = safer on Windows.
REACHABILITY_PORTS = [9100, 80]
CONNECT_TIMEOUT = 1.0  # seconds per port


def _probe_sync(ip, ports, timeout):
    """
    Plain blocking socket probe, one port at a time.
    Each socket is fully closed before the next is tried, so at most ONE
    socket is open at any moment. Returns the first open port, or None.
    """
    for port in ports:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            return port
        except Exception:
            continue
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    return None


async def is_reachable(ip, ports=None, timeout=CONNECT_TIMEOUT):
    """
    Return (reachable: bool, open_port: int|None).

    Runs the blocking probe in the default thread executor so it never
    blocks the event loop and never adds sockets to the asyncio selector.
    """
    ports = ports or REACHABILITY_PORTS
    loop = asyncio.get_event_loop()
    open_port = await loop.run_in_executor(None, _probe_sync, ip, ports, timeout)
    return (open_port is not None), open_port


def is_reachable_sync(ip, ports=None, timeout=CONNECT_TIMEOUT):
    ports = ports or REACHABILITY_PORTS
    open_port = _probe_sync(ip, ports, timeout)
    return (open_port is not None), open_port


if __name__ == "__main__":
    import sys
    test_ip = sys.argv[1] if len(sys.argv) > 1 else "172.20.231.74"
    reachable, port = is_reachable_sync(test_ip)
    print(f"{test_ip}: reachable={reachable} open_port={port}")
