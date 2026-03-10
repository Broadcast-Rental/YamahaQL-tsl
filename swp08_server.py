#!/usr/bin/env python3
"""
SW-P-08 Protocol Server Implementation
Provides router control interface for Cerebrum via SW-P-08 protocol.

This file is based on Broadcast Rental's SR2-Cerebrum-Translator project and
is used here to expose a virtual router whose crosspoints are driven by
Yamaha mixer fader status.
"""

import errno
import os
import re
import socket
import sys
import threading
import struct
import time
from typing import Dict, Optional, Tuple, List, Union
from collections import defaultdict


def _is_verbose_swp08() -> bool:
    """True if SW-P-08 per-command logging is enabled (env SWP08_VERBOSE=1)."""
    if os.environ.get("SWP08_VERBOSE", "").lower() in ("1", "true", "yes"):
        return True
    return False


def log(msg="", **kwargs):
    """Print to stderr with immediate flush (visible in Docker without buffering)."""
    print(msg, file=sys.stderr, flush=True, **kwargs)
    sys.stderr.flush()


# SW-P-08 Protocol Constants
DLE = 0x10
STX = 0x02
ETX = 0x03
ACK = 0x06
NAK = 0x15

# Command bytes
CMD_INTERROGATE = 0x01
CMD_CONNECT = 0x02
CMD_TALLY = 0x03
CMD_CONNECTED = 0x04
CMD_TALLY_DUMP_REQUEST = 0x15  # 21 decimal
CMD_TALLY_DUMP_BYTE = 0x16     # 22 decimal
CMD_TALLY_DUMP_WORD = 0x17     # 23 decimal
CMD_PROTOCOL_REQUEST = 0x61    # 97 decimal - Request Protocol Implementation
CMD_PROTOCOL_RESPONSE = 0x62   # 98 decimal - Protocol Implementation Response
CMD_GET_SOURCE_NAMES = 0x64    # 100 decimal - Get Source Names
CMD_SOURCE_NAMES_RESPONSE = 0x6A  # 106 decimal - Source Names Response
CMD_GET_DEST_NAMES = 0x66     # 102 decimal - Get Destination Names
CMD_DEST_NAMES_RESPONSE = 0x6B  # 107 decimal - Destination Names Response
CMD_STATUS_REQUEST_2 = 0x12   # 18 decimal - Status Request 2 (client → router)
CMD_STATUS_RESPONSE_6 = 0x13   # 19 decimal - Status Response 6 (router → client)
CMD_MATRIX_OR_STATUS_10 = 0x0A  # 10 decimal - matrix/status style request (some clients)

# Router constants
SOURCE_NC = 0
SOURCE_LOCAL = 1  # reserved, not used in Yamaha mapping

MNEMONIC_LEN = 23
MNEMONIC_LEFT_LEN = 10
MNEMONIC_RIGHT_LEN = 10
MNEMONIC_SEP = " | "
CHAR_LENGTHS = [4, 8, 12, 16, 32]


def _mnemonic_for_length(full_mnemonic: str, char_length: int) -> str:
    """Return full_mnemonic (23 chars) formatted to char_length."""
    if char_length >= MNEMONIC_LEN:
        return full_mnemonic.ljust(char_length, " ")[:char_length]
    if char_length == 16 and len(full_mnemonic) >= 23:
        return (full_mnemonic[:5] + "|" + full_mnemonic[13:23]).ljust(16, " ")[:16]
    return full_mnemonic.ljust(char_length, " ")[:char_length]


def _yamaha_port_mnemonic(router_name: str, port_name: str) -> str:
    """Format as 'RouterName | Port name' (23 chars)."""
    left = ((router_name or "Yamaha").strip())[:MNEMONIC_LEFT_LEN]
    right = ((port_name or "PORT").strip())[:MNEMONIC_RIGHT_LEN]
    s = f"{left}{MNEMONIC_SEP}{right}"
    return s.ljust(MNEMONIC_LEN, " ")[:MNEMONIC_LEN]


class RouterState:
    """Router state: dest -> source."""

    def __init__(self, node_id: str, node_name: str, num_outputs: int, num_sources: int):
        self.node_id = node_id
        self.node_name = node_name
        self.num_outputs = num_outputs
        self.num_sources = num_sources
        self.matrix: Dict[int, int] = {}
        # Optional list of destination labels (one per dest index). When set,
        # SW-P-08 destination names will use these instead of generic "CH n".
        self.dest_labels: Optional[List[str]] = None
        for dest in range(num_outputs):
            self.matrix[dest] = SOURCE_NC

    def get_tally(self, dest: int) -> int:
        return self.matrix.get(dest, SOURCE_NC)

    def set_crosspoint(self, dest: int, source: int) -> bool:
        if dest < 0 or dest >= self.num_outputs:
            return False
        if source < 0 or source >= self.num_sources:
            return False
        self.matrix[dest] = source
        return True

    def get_all_tallies(self) -> List[Tuple[int, int]]:
        return [(d, self.matrix.get(d, SOURCE_NC)) for d in range(self.num_outputs)]


class SWP08Message:
    """SW-P-08 message encoder/decoder."""

    @staticmethod
    def encode_message(command: int, data: bytes = b"") -> bytes:
        message_data = bytes([command]) + data
        byte_count = len(message_data)

        checksum = 0
        for b in message_data:
            checksum = (checksum + b) & 0xFF
        checksum = (checksum + byte_count) & 0xFF
        checksum = (~checksum + 1) & 0xFF

        packet = message_data + bytes([byte_count, checksum])

        escaped = b""
        for b in packet:
            escaped += bytes([b])
            if b == DLE:
                escaped += bytes([DLE])

        return bytes([DLE, STX]) + escaped + bytes([DLE, ETX])

    @staticmethod
    def decode_message(raw_data: bytes) -> Optional[Tuple[int, bytes]]:
        if len(raw_data) < 6:
            return None
        if raw_data[0] != DLE or raw_data[1] != STX:
            return None

        etx_idx = -1
        for i in range(len(raw_data) - 1):
            if raw_data[i] == DLE and raw_data[i + 1] == ETX:
                etx_idx = i
                break
        if etx_idx == -1:
            return None

        escaped_data = raw_data[2:etx_idx]
        packet = b""
        i = 0
        while i < len(escaped_data):
            if escaped_data[i] == DLE:
                if i + 1 < len(escaped_data) and escaped_data[i + 1] == DLE:
                    packet += bytes([DLE])
                    i += 2
                else:
                    return None
            else:
                packet += bytes([escaped_data[i]])
                i += 1

        if len(packet) < 3:
            return None

        command = packet[0]
        byte_count = packet[-2]
        checksum = packet[-1]

        if len(packet) - 2 != byte_count:
            return None

        calc_checksum = 0
        for b in packet[:-1]:
            calc_checksum = (calc_checksum + b) & 0xFF
        calc_checksum = (~calc_checksum + 1) & 0xFF
        if calc_checksum != checksum:
            return None

        message_data = packet[1:-2]
        return command, message_data

    @staticmethod
    def encode_ack() -> bytes:
        return bytes([DLE, ACK])

    @staticmethod
    def encode_nak() -> bytes:
        return bytes([DLE, NAK])


class SWP08Server:
    """Minimal SW-P-08 protocol server suitable for a single virtual router."""

    def __init__(self, host: str = "0.0.0.0", port: int = 2000, router_state: Optional[RouterState] = None):
        self.host = host
        self.port = port
        self.router_state = router_state
        self.socket = None
        self.running = False
        self.clients: List[socket.socket] = []
        self.lock = threading.Lock()
        self._cached_dest_names: Optional[List[str]] = None
        self._cached_source_names: Optional[List[str]] = None

    def get_primary_router_state(self) -> Optional[RouterState]:
        return self.router_state

    def start(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(16)
            self.running = True

            bound_addr = self.socket.getsockname()
            log(f"SW-P-08 server listening on {bound_addr[0]}:{bound_addr[1]}")
            rs = self.get_primary_router_state()
            if rs:
                log(f"Router matrix: {rs.num_outputs} dests, {rs.num_sources} sources")

            while self.running:
                try:
                    client_socket, address = self.socket.accept()
                    t = threading.Thread(target=self.handle_client, args=(client_socket, address), daemon=True)
                    t.start()
                except socket.error as e:
                    if self.running:
                        log(f"Socket error accepting connection: {e}")
                except Exception as e:
                    if self.running:
                        log(f"Error accepting connection: {e}")
                        import traceback
                        traceback.print_exc(file=sys.stderr)
        except Exception as e:
            log(f"Failed to start SW-P-08 server: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise

    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass

    def handle_client(self, client_socket: socket.socket, address: Tuple[str, int]):
        self.clients.append(client_socket)
        buffer = b""
        try:
            client_socket.settimeout(30.0)
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            while self.running:
                try:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    buffer += data

                    processed = True
                    while processed:
                        processed = False
                        start_idx = buffer.find(bytes([DLE, STX]))
                        if start_idx == -1:
                            break
                        end_idx = buffer.find(bytes([DLE, ETX]), start_idx + 2)
                        if end_idx == -1:
                            break
                        message = buffer[start_idx:end_idx + 2]
                        buffer = buffer[end_idx + 2:]
                        processed = True

                        decoded = SWP08Message.decode_message(message)
                        if decoded:
                            command, cmd_data = decoded
                            client_socket.sendall(SWP08Message.encode_ack())
                            response = self.process_command(command, cmd_data, address)
                            if isinstance(response, tuple):
                                first, extra = response
                                if first:
                                    client_socket.sendall(first)
                                for msg in extra:
                                    client_socket.sendall(msg)
                            elif response:
                                client_socket.sendall(response)
                        else:
                            log(f"Invalid message from {address}, sending NAK")
                            client_socket.sendall(SWP08Message.encode_nak())

                    if len(buffer) > 4096:
                        log(f"Warning: Buffer size {len(buffer)} exceeds 4096 bytes, clearing")
                        buffer = b""
                except socket.timeout:
                    continue
                except socket.error as e:
                    err = getattr(e, "errno", None)
                    expected = (errno.EBADF, errno.ECONNRESET, errno.ENOTCONN, 10054, 10058)
                    if err in expected:
                        if _is_verbose_swp08():
                            log(f"Client {address} disconnected")
                        break
                    log(f"Socket error in recv loop: {e}")
                    break
        except socket.timeout:
            log(f"Client {address} timeout (no data received in 30 seconds)")
        except socket.error as e:
            log(f"Socket error handling client {address}: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
        except Exception as e:
            log(f"Error handling client {address}: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            try:
                client_socket.close()
            except Exception:
                pass

    def process_command(self, command: int, data: bytes, address: Tuple[str, int]) -> Union[Optional[bytes], Tuple[bytes, List[bytes]]]:
        if _is_verbose_swp08():
            start_idx = (data[2] << 8) | data[3] if len(data) >= 4 else -1
            log(f"[SWP08] {time.monotonic():.1f}s cmd=0x{command:02X} len={len(data)} start={start_idx}")

        matrix = 0
        level = 0

        try:
            if command == CMD_PROTOCOL_REQUEST:
                return self.handle_protocol_request()
            elif command == CMD_INTERROGATE:
                return self.handle_interrogate(data, matrix, level)
            elif command == CMD_CONNECT:
                return self.handle_connect(data, matrix, level)
            elif command == CMD_TALLY_DUMP_REQUEST:
                return self.handle_tally_dump_request_with_connected(data, matrix, level)
            elif command == CMD_GET_SOURCE_NAMES:
                return self.handle_get_source_names(data, matrix, level)
            elif command == CMD_GET_DEST_NAMES:
                return self.handle_get_dest_names(data, matrix, level)
            elif command == 0x43:  # Cerebrum paginated name request variant
                # Data format variants (mirrors SR2 implementation):
                # - [matrixLevel, charLengthIndex, startHi, startLo]
                # - [matrixLevel, charLengthIndex]
                # - [typeFlag] or [] where typeFlag 0x03 = destinations, else sources
                if len(data) >= 4:
                    matrix_level = data[0]
                    type_or_char = data[1]
                    start_hi = data[2]
                    start_lo = data[3]
                    # typeFlag 0x03 = destination names, else source names
                    char_len_idx = type_or_char if type_or_char < 4 else 0x03
                    modified_data = bytes([matrix_level, char_len_idx, start_hi, start_lo])
                    if type_or_char == 0x03:
                        return self.handle_get_dest_names(modified_data, matrix, level)
                    return self.handle_get_source_names(modified_data, matrix, level)
                elif len(data) >= 2:
                    matrix_level = data[0]
                    char_len_idx = data[1] if data[1] < 4 else 0x03
                    modified_data = bytes([matrix_level, char_len_idx])
                    return self.handle_get_source_names(modified_data, matrix, level)
                elif len(data) == 1:
                    type_flag = data[0]
                    if type_flag == 0x03:
                        modified_data = bytes([0, 2])  # matrixLevel=0, charLengthIndex=2
                        return self.handle_get_dest_names(modified_data, matrix, level)
                    modified_data = bytes([0, 2])
                    return self.handle_get_source_names(modified_data, matrix, level)
                else:
                    modified_data = bytes([0, 2])
                    return self.handle_get_source_names(modified_data, matrix, level)
            elif command == 0x65:  # Paginated SOURCE name request
                if len(data) >= 4:
                    matrix_level = data[0]
                    type_or_char = data[1]
                    char_len_idx = type_or_char if type_or_char < 4 else 0x03
                    modified_data = bytes([matrix_level, char_len_idx, data[2], data[3]])
                    if type_or_char == 0x03:
                        return self.handle_get_dest_names(modified_data, matrix, level)
                    return self.handle_get_source_names(modified_data, matrix, level)
                elif len(data) >= 2:
                    char_len_idx = data[1] if data[1] < 4 else 0x03
                    modified_data = bytes([data[0], char_len_idx]) + (data[2:4] if len(data) >= 4 else b"\x00\x00")
                    return self.handle_get_source_names(modified_data, matrix, level)
                return None
            elif command == 0x67:  # Paginated DESTINATION name request
                if len(data) >= 4:
                    matrix_level = data[0]
                    char_len_idx = data[1] if data[1] < 4 else 0x03
                    modified_data = bytes([matrix_level, char_len_idx, data[2], data[3]])
                    return self.handle_get_dest_names(modified_data, matrix, level)
                elif len(data) >= 2:
                    char_len_idx = data[1] if data[1] < 4 else 0x03
                    modified_data = bytes([data[0], char_len_idx]) + (data[2:4] if len(data) >= 4 else b"\x00\x00")
                    return self.handle_get_dest_names(modified_data, matrix, level)
                return None
            elif command == CMD_MATRIX_OR_STATUS_10:
                return None
            elif command == CMD_STATUS_REQUEST_2:
                return self.handle_status_request_2(data, matrix, level)
            elif command == CMD_STATUS_RESPONSE_6:
                return None
            else:
                return None
        except Exception as e:
            log(f"Error processing command {command}: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None

    def handle_interrogate(self, data: bytes, matrix: int, level: int) -> bytes:
        if len(data) < 3:
            return SWP08Message.encode_nak()

        matrix_level = data[0]
        multiplier = data[1]
        dest_mod = data[2]

        dest_div = (multiplier >> 4) & 0x07
        dest = (dest_div * 128) + dest_mod

        router_state = self.get_primary_router_state()
        if not router_state:
            source = 1023
        else:
            source = router_state.get_tally(dest)

        source_div = (source // 128) & 0x07
        source_mod = source % 128
        response_multiplier = (dest_div << 4) | source_div

        response_data = bytes([matrix_level, response_multiplier, dest_mod, source_mod])
        return SWP08Message.encode_message(CMD_TALLY, response_data)

    def handle_connect(self, data: bytes, matrix: int, level: int) -> bytes:
        if len(data) < 4:
            return SWP08Message.encode_nak()

        matrix_level = data[0]
        multiplier = data[1]
        dest_mod = data[2]
        source_mod = data[3]

        dest_div = (multiplier >> 4) & 0x07
        dest = (dest_div * 128) + dest_mod

        source_div = (multiplier >> 0) & 0x07
        source = (source_div * 128) + source_mod

        router_state = self.get_primary_router_state()
        if not router_state:
            return SWP08Message.encode_nak()

        if source == SOURCE_LOCAL:
            return SWP08Message.encode_nak()

        success = router_state.set_crosspoint(dest, source)
        if success:
            response_data = bytes([matrix_level, multiplier, dest_mod, source_mod])
            return SWP08Message.encode_message(CMD_CONNECTED, response_data)
        return SWP08Message.encode_nak()

    def handle_protocol_request(self) -> bytes:
        supported_commands = bytes([
            0x01, 0x02, 0x03, 0x04,
            0x15, 0x16, 0x17,
            0x61, 0x64, 0x66,
        ])
        return SWP08Message.encode_message(CMD_PROTOCOL_RESPONSE, supported_commands)

    def handle_tally_dump_request(self, data: bytes, matrix: int, level: int) -> bytes:
        router_state = self.get_primary_router_state()
        if not router_state:
            return SWP08Message.encode_nak()
        tallies = router_state.get_all_tallies()
        matrix_level = data[0] if data else 0x00
        num_tallies = min(len(tallies), 64)
        if num_tallies == 0:
            response_data = bytes([matrix_level, 0])
        else:
            first_dest = tallies[0][0]
            response_data = bytes([matrix_level, num_tallies, first_dest])
            for dest, source in tallies[:num_tallies]:
                response_data += bytes([source & 0xFF])
        return SWP08Message.encode_message(CMD_TALLY_DUMP_BYTE, response_data)

    def _tally_dump_byte_messages(self, data: bytes, router_state: RouterState) -> List[bytes]:
        tallies = router_state.get_all_tallies()
        matrix_level = data[0] if data else 0x00
        out: List[bytes] = []
        for start in range(0, len(tallies), 64):
            chunk = tallies[start:start + 64]
            if not chunk:
                break
            first_dest = chunk[0][0]
            response_data = bytes([matrix_level, len(chunk), first_dest & 0xFF])
            for dest, source in chunk:
                response_data += bytes([source & 0xFF])
            out.append(SWP08Message.encode_message(CMD_TALLY_DUMP_BYTE, response_data))
        return out

    def handle_tally_dump_request_with_connected(self, data: bytes, matrix: int, level: int) -> Tuple[bytes, List[bytes]]:
        router_state = self.get_primary_router_state()
        if not router_state:
            return SWP08Message.encode_nak(), []
        tally_messages = self._tally_dump_byte_messages(data, router_state)
        if not tally_messages:
            return SWP08Message.encode_nak(), []
        response = tally_messages[0]
        extra = list(tally_messages[1:])
        matrix_level = data[0] if data else 0x00
        for dest in range(router_state.num_outputs):
            source = router_state.get_tally(dest)
            if source != SOURCE_NC:
                dest_mod = dest % 128
                source_mod = source % 128
                dest_div = (dest // 128) & 0x07
                source_div = (source // 128) & 0x07
                multiplier = (dest_div << 4) | source_div
                conn_data = bytes([matrix_level, multiplier, dest_mod, source_mod])
                extra.append(SWP08Message.encode_message(CMD_CONNECTED, conn_data))
        return response, extra

    def _build_source_name_list(self) -> List[str]:
        rs = self.get_primary_router_state()
        if not rs or rs.num_sources <= 1:
            return [_yamaha_port_mnemonic("NC", "")]

        names: List[str] = []
        # Source 0 = NC
        names.append(_yamaha_port_mnemonic("NC", ""))

        # Sources 1..num_sources-1 map to Yamaha channels 1..N
        labels = getattr(rs, "dest_labels", None)
        for src_index in range(1, rs.num_sources):
            if labels and (src_index - 1) < len(labels) and labels[src_index - 1]:
                port_name = labels[src_index - 1]
            else:
                port_name = f"CH {src_index}"
            names.append(_yamaha_port_mnemonic(rs.node_name, port_name))

        return names

    def handle_get_source_names(self, data: bytes, matrix: int, level: int) -> Optional[bytes]:
        if len(data) < 2:
            return None
        matrix_level = data[0]
        char_length_index = 4
        char_length = 32

        has_start_index = len(data) >= 4
        start_index = 0
        if has_start_index:
            start_hi = data[2]
            start_lo = data[3]
            start_index = (start_hi << 8) | start_lo

        if self._cached_source_names is None:
            self._cached_source_names = self._build_source_name_list()
        all_name_strings = self._cached_source_names

        if start_index >= len(all_name_strings):
            names_data = bytes([matrix_level, char_length_index, (start_index >> 8) & 0xFF, start_index & 0xFF, 0])
        else:
            max_names = min(3, len(all_name_strings) - start_index) if has_start_index else min(3, len(all_name_strings))
            name_bytes = b""
            for i in range(max_names):
                padded = _mnemonic_for_length(all_name_strings[start_index + i], char_length)
                name_bytes += padded.encode("ascii")
            start_hi = (start_index >> 8) & 0xFF if has_start_index else 0
            start_lo = start_index & 0xFF if has_start_index else 0
            names_data = bytes([
                matrix_level,
                char_length_index,
                start_hi,
                start_lo,
                max_names,
            ]) + name_bytes
        return SWP08Message.encode_message(CMD_SOURCE_NAMES_RESPONSE, names_data)

    def handle_get_dest_names(self, data: bytes, matrix: int, level: int) -> Optional[bytes]:
        if len(data) < 2:
            return None
        matrix_level = data[0]
        char_length_index = 4
        char_length = 32

        has_start_index = len(data) >= 4
        start_index = 0
        if has_start_index:
            start_hi = data[2]
            start_lo = data[3]
            start_index = (start_hi << 8) | start_lo

        rs = self.get_primary_router_state()
        if not rs or rs.num_outputs == 0:
            all_name_strings: List[str] = []
        else:
            if self._cached_dest_names is None:
                dests: List[str] = []
                labels = getattr(rs, "dest_labels", None)
                for i in range(rs.num_outputs):
                    if labels and i < len(labels) and labels[i]:
                        port_name = labels[i]
                    else:
                        port_name = f"CH {i + 1}"
                    dests.append(_yamaha_port_mnemonic(rs.node_name, port_name))
                self._cached_dest_names = dests
            all_name_strings = self._cached_dest_names

        if start_index >= len(all_name_strings):
            start_hi = (start_index >> 8) & 0xFF
            start_lo = start_index & 0xFF
            names_data = bytes([matrix_level, char_length_index, start_hi, start_lo, 0])
        else:
            if has_start_index:
                max_names = min(3, len(all_name_strings) - start_index)
                name_bytes = b""
                for i in range(max_names):
                    padded = _mnemonic_for_length(all_name_strings[start_index + i], char_length)
                    name_bytes += padded.encode("ascii")
                start_hi = (start_index >> 8) & 0xFF
                start_lo = start_index & 0xFF
                names_data = bytes([
                    matrix_level,
                    char_length_index,
                    start_hi,
                    start_lo,
                    max_names,
                ]) + name_bytes
            else:
                start_index = 0
                max_names = min(3, len(all_name_strings))
                if max_names == 0:
                    return None
                name_bytes = b"".join(
                    _mnemonic_for_length(all_name_strings[i], char_length).encode("ascii") for i in range(max_names)
                )
                names_data = bytes([
                    matrix_level,
                    char_length_index,
                    0,
                    0,
                    max_names,
                ]) + name_bytes

        return SWP08Message.encode_message(CMD_DEST_NAMES_RESPONSE, names_data)

    def handle_status_request_2(self, data: bytes, matrix: int, level: int) -> bytes:
        response_data = bytes([0x00, 0x00])
        return SWP08Message.encode_message(CMD_STATUS_RESPONSE_6, response_data)


