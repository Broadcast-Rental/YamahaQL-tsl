#!/usr/bin/env python3
"""
Minimal Yamaha QL/CL mixer client for use inside EVS Cerebrum Python macros.

This module does NOT depend on Flask or TSL. It only:
- Opens a TCP connection to the Yamaha mixer (RCP protocol, port 49280)
- Sends "get MIXER:Current/InCh/Fader/Level" commands
- Parses responses and returns simple Python values

You can import and call these functions from a Cerebrum macro once you know
how to expose Python code in your Cerebrum configuration.
"""

import socket
import time
from typing import Optional, Tuple

# Default Yamaha RCP port
YAMAHA_RCP_PORT = 49280


class YamahaRcpClient:
    """Lightweight synchronous client for Yamaha RCP protocol."""

    def __init__(self, ip: str, port: int = YAMAHA_RCP_PORT, timeout: float = 3.0) -> None:
        """
        Create a client instance.

        - ip: IP address of the Yamaha mixer
        - port: RCP TCP port (default 49280)
        - timeout: socket timeout in seconds
        """
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    # --- connection management -------------------------------------------------

    def connect(self) -> Tuple[bool, str]:
        """
        Open TCP connection to the mixer.

        Returns (success: bool, message: str) for easy use in Cerebrum logic.
        """
        self.close()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.ip, self.port))
            s.settimeout(self.timeout)
            self.sock = s
            return True, f"Connected to Yamaha mixer at {self.ip}:{self.port}"
        except Exception as e:
            self.sock = None
            return False, f"Failed to connect to Yamaha mixer at {self.ip}:{self.port} - {e}"

    def close(self) -> None:
        """Close the TCP connection if it is open."""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # --- low-level command helper ---------------------------------------------

    def _send_command(self, command: str) -> Optional[str]:
        """
        Send a single RCP command and return the first matching 'OK ... get ...'
        line as a decoded string, or None on error/timeout.
        """
        if self.sock is None:
            return None

        try:
            # Yamaha expects newline-terminated commands
            self.sock.sendall((command + "\n").encode("utf-8"))

            response = b""
            start = time.time()
            max_wait = self.timeout

            while time.time() - start < max_wait:
                try:
                    chunk = self.sock.recv(1024)
                except socket.timeout:
                    # No data yet; keep waiting until max_wait
                    continue

                if not chunk:
                    # Connection closed by mixer
                    self.close()
                    return None

                response += chunk
                lines = response.split(b"\n")
                for line in lines:
                    line = line.strip()
                    if line.startswith(b"OK") and b"get" in line:
                        return line.decode("utf-8", errors="ignore")

            return None
        except (ConnectionResetError, BrokenPipeError, OSError):
            # Connection problem; close and signal failure
            self.close()
            return None
        except Exception:
            return None

    # --- high-level helpers ---------------------------------------------------

    def get_fader_level_raw(self, channel_index_zero_based: int) -> Optional[int]:
        """
        Get the raw fader level value for a given input channel.

        - channel_index_zero_based: 0 for CH1, 1 for CH2, etc.
        Returns:
            int value from the mixer (e.g. -32768 == closed) or None on error.
        """
        cmd = f"get MIXER:Current/InCh/Fader/Level {channel_index_zero_based} 0"
        response = self._send_command(cmd)
        if not response or not response.startswith("OK"):
            return None

        parts = response.split()
        if len(parts) < 2:
            return None

        try:
            # Last token should be the numeric value
            return int(parts[-1])
        except ValueError:
            return None

    def get_fader_open_state(self, channel_index_zero_based: int) -> Optional[bool]:
        """
        Get a simple OPEN/CLOSED boolean for a given fader.

        - channel_index_zero_based: 0 for CH1, 1 for CH2, etc.
        Returns:
            True  -> fader is OPEN (any value != -32768)
            False -> fader is CLOSED (value == -32768)
            None  -> error/timeout.
        """
        level = self.get_fader_level_raw(channel_index_zero_based)
        if level is None:
            return None
        # From README: -32768 = CLOSED, anything else = OPEN
        return level != -32768

    def get_channel_label_name(self, channel_index_zero_based: int) -> Optional[str]:
        """
        Get the user label/name for a given input channel.

        Uses: get MIXER:Current/InCh/Label/Name {ch} 0
        Returns the label string without surrounding quotes, or None on error.
        """
        cmd = f"get MIXER:Current/InCh/Label/Name {channel_index_zero_based} 0"
        response = self._send_command(cmd)
        if not response or not response.startswith("OK"):
            return None

        # Yamaha typically returns something like:
        # OK get MIXER:Current/InCh/Label/Name 0 0 "My Label"
        first_quote = response.find('"')
        if first_quote != -1:
            last_quote = response.rfind('"')
            if last_quote > first_quote:
                return response[first_quote + 1:last_quote]

        parts = response.split()
        return parts[-1] if parts else None


# --- simple direct-use helpers -----------------------------------------------

def get_single_fader_open(ip: str, channel_number_one_based: int) -> Optional[bool]:
    """
    Convenience helper if you just want one channel state in a macro.

    - ip: mixer IP
    - channel_number_one_based: 1 for CH1, 2 for CH2, ...

    Example usage from a Cerebrum script (pseudo):
        state = get_single_fader_open("172.20.40.13", 1)
        # state is True / False / None
    """
    client = YamahaRcpClient(ip)
    ok, _ = client.connect()
    if not ok:
        return None
    try:
        return client.get_fader_open_state(channel_number_one_based - 1)
    finally:
        client.close()


if __name__ == "__main__":
    # Simple manual test runner for local debugging only.
    # Replace with your mixer IP and channel number.
    TEST_IP = "172.20.40.13"  # change to your mixer IP
    TEST_CHANNEL = 1          # channel 1 (one-based)

    client = YamahaRcpClient(TEST_IP)
    ok, msg = client.connect()
    print(msg)
    if ok:
        state = client.get_fader_open_state(TEST_CHANNEL - 1)
        print(f"Channel {TEST_CHANNEL} open state: {state}")
        client.close()

