#!/usr/bin/env python3
"""
Yamaha QL5 to TSL v5 Bridge Service
Connects to Yamaha mixer and sends fader status to TSL 5.0
"""

import socket
import time
import json
import threading
import argparse
import sys
from typing import Dict, Optional

# Configuration
YAMAHA_RCP_PORT = 49280
YAMAHA_IP = "172.20.40.13"
QL5_INPUT_CHANNELS = 40

# TSL Configuration - adjust these for your TSL setup
TSL_TCP_SERVER_PORT = 20000  # Port for TSL to connect to us
TSL_TCP_CLIENT_IP = None     # TSL IP if we connect to TSL (None = server mode)
TSL_TCP_CLIENT_PORT = None   # TSL port if we connect to TSL
TSL_UDP_IP = None            # TSL UDP IP (None = don't use UDP)
TSL_UDP_PORT = None          # TSL UDP port
POLL_INTERVAL = 0.25         # Seconds between polls (250ms)


class YamahaMixer:
    """Handles connection and communication with Yamaha mixer"""
    
    def __init__(self, ip_address: str):
        self.ip_address = ip_address
        self.socket: Optional[socket.socket] = None
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to Yamaha mixer"""
        # Ensure old socket is closed
        self.disconnect()
        
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # Increased timeout
            self.socket.connect((self.ip_address, YAMAHA_RCP_PORT))
            self.socket.settimeout(5)  # Set back to normal timeout after connection
            self.connected = True
            print(f"Connected to Yamaha mixer at {self.ip_address}:{YAMAHA_RCP_PORT}")
            
            # Verify connection by sending a test command
            test_response = self.send_command("get MIXER:Current/InCh/Fader/Level 0 0")
            if test_response is None:
                print("Warning: Connection established but test command failed")
                # Still return True as connection was successful, might be a command issue
            return True
        except socket.timeout:
            print(f"Connection timeout to mixer at {self.ip_address}:{YAMAHA_RCP_PORT}")
            self.connected = False
            return False
        except ConnectionRefusedError:
            print(f"Connection refused by mixer at {self.ip_address}:{YAMAHA_RCP_PORT}")
            self.connected = False
            return False
        except OSError as e:
            print(f"Network error connecting to mixer: {e}")
            self.connected = False
            return False
        except Exception as e:
            print(f"Failed to connect to mixer: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from mixer"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False
    
    def send_command(self, command: str) -> Optional[str]:
        """Send command to mixer and get response"""
        if not self.connected or not self.socket:
            return None
        
        try:
            # Send command
            self.socket.sendall((command + "\n").encode('utf-8'))
            
            # Receive response - filter NOTIFY messages
            response = b""
            start_time = time.time()
            max_wait = 3
            
            while time.time() - start_time < max_wait:
                try:
                    self.socket.settimeout(0.5)
                    chunk = self.socket.recv(1024)
                    if chunk:
                        response += chunk
                        
                        # Filter for OK responses
                        lines = response.split(b"\n")
                        ok_lines = [line for line in lines if line.startswith(b"OK") and b"get" in line]
                        
                        if ok_lines:
                            response_str = ok_lines[0].decode('utf-8', errors='ignore').strip()
                            return response_str
                    else:
                        # Empty chunk means connection closed
                        print("Connection closed by mixer (empty recv)")
                        self.connected = False
                        break
                except socket.timeout:
                    if response:
                        lines = response.split(b"\n")
                        ok_lines = [line for line in lines if line.startswith(b"OK") and b"get" in line]
                        if ok_lines:
                            response_str = ok_lines[0].decode('utf-8', errors='ignore').strip()
                            return response_str
                    continue
            
            if response:
                lines = response.split(b"\n")
                ok_lines = [line for line in lines if line.startswith(b"OK") and b"get" in line]
                if ok_lines:
                    response_str = ok_lines[0].decode('utf-8', errors='ignore').strip()
                    return response_str
            
            return None
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"Connection lost during command send: {e}")
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return None
        except Exception as e:
            print(f"Error sending command: {e}")
            # Check if it's a connection error
            if isinstance(e, (socket.error, OSError)):
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
            return None
    
    def get_fader_status(self, channel_index: int) -> Optional[bool]:
        """Get fader open/closed status for a channel
        Returns: True = open, False = closed, None = error
        """
        command = f"get MIXER:Current/InCh/Fader/Level {channel_index} 0"
        response = self.send_command(command)
        
        if response and response.startswith("OK"):
            parts = response.split()
            if len(parts) >= 2:
                try:
                    value = int(parts[-1])
                    # -32768 = closed (negative infinity), anything else = open
                    return value != -32768
                except (ValueError, IndexError):
                    return None
        return None
    
    def get_all_fader_status(self) -> Dict[int, bool]:
        """Get fader status for all channels"""
        status = {}
        if not self.connected:
            return status
        
        for channel_idx in range(QL5_INPUT_CHANNELS):
            if not self.connected:
                break  # Stop if connection lost
            channel_num = channel_idx + 1
            fader_status = self.get_fader_status(channel_idx)
            if fader_status is not None:
                status[channel_num] = fader_status
            time.sleep(0.01)  # Small delay to avoid overwhelming mixer
        return status


class TSLBridge:
    """Handles communication with TSL 5.0"""
    
    def __init__(self):
        self.tcp_server_socket: Optional[socket.socket] = None
        self.tcp_client_socket: Optional[socket.socket] = None
        self.udp_socket: Optional[socket.socket] = None
        self.tcp_clients = []  # List of connected TCP clients
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
    
    def start_tcp_server(self, port: int):
        """Start TCP server (TSL connects to us)"""
        try:
            self.tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_server_socket.bind(('', port))
            self.tcp_server_socket.listen(5)
            self.tcp_server_socket.settimeout(1.0)
            print(f"TSL TCP server listening on port {port}")
            self.running = True
            
            # Start server thread
            self.server_thread = threading.Thread(target=self._tcp_server_loop, daemon=True)
            self.server_thread.start()
        except Exception as e:
            print(f"Failed to start TCP server: {e}")
    
    def _tcp_server_loop(self):
        """Accept and manage TCP client connections"""
        while self.running:
            try:
                if self.tcp_server_socket:
                    client_socket, address = self.tcp_server_socket.accept()
                    print(f"TSL client connected from {address}")
                    self.tcp_clients.append(client_socket)
                    # Trigger immediate status send for new client
                    if hasattr(self, 'on_new_client'):
                        try:
                            self.on_new_client()
                        except Exception as e:
                            print(f"Error in new client callback: {e}")
                    
                    # Start a thread to handle requests from this client
                    client_thread = threading.Thread(
                        target=self._handle_client_requests,
                        args=(client_socket, address),
                        daemon=True
                    )
                    client_thread.start()
            except socket.timeout:
                continue
            except OSError:
                # Socket was closed
                break
            except Exception as e:
                if self.running:
                    print(f"TCP server error: {e}")
                    import traceback
                    traceback.print_exc()
    
    def _handle_client_requests(self, client_socket: socket.socket, address):
        """Handle requests from a client (e.g., "STATUS", "REFRESH")"""
        client_socket.settimeout(1.0)
        while self.running:
            try:
                # Check if client sent a request
                data = client_socket.recv(1024)
                if not data:
                    # Client disconnected
                    break
                
                request = data.decode('utf-8', errors='ignore').strip().upper()
                
                # Handle request commands
                if request == "STATUS" or request == "REFRESH" or request == "GET":
                    # Send current status immediately
                    if hasattr(self, 'on_new_client'):
                        try:
                            self.on_new_client()
                        except Exception as e:
                            print(f"Error handling client request: {e}")
                elif request == "PING":
                    # Respond to ping
                    client_socket.sendall(b"PONG\n")
                # Ignore other messages
            except socket.timeout:
                # No request, continue waiting
                continue
            except Exception as e:
                # Client disconnected or error
                break
        
        # Remove client from list
        if client_socket in self.tcp_clients:
            self.tcp_clients.remove(client_socket)
        try:
            client_socket.close()
        except:
            pass
        print(f"TSL client disconnected from {address}")
    
    def connect_tcp_client(self, ip: str, port: int) -> bool:
        """Connect to TSL as TCP client (we connect to TSL)"""
        try:
            self.tcp_client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_client_socket.settimeout(5)
            self.tcp_client_socket.connect((ip, port))
            print(f"Connected to TSL at {ip}:{port}")
            return True
        except Exception as e:
            print(f"Failed to connect to TSL: {e}")
            return False
    
    def start_udp(self, ip: str, port: int):
        """Start UDP socket for sending to TSL"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_ip = ip
            self.udp_port = port
            print(f"UDP socket ready to send to {ip}:{port}")
        except Exception as e:
            print(f"Failed to setup UDP: {e}")
    
    def send_status(self, channel_status: Dict[int, bool], format_type: str = "json", debug: bool = None):
        """Send fader status to TSL in specified format"""
        if debug is None:
            debug = self.debug
        if format_type == "json":
            self._send_json(channel_status)
        elif format_type == "tsl5":
            self._send_tsl5(channel_status, debug=debug)
        elif format_type == "simple":
            self._send_simple(channel_status)
    
    def _send_json(self, channel_status: Dict[int, bool]):
        """Send status as JSON"""
        data = {
            "timestamp": time.time(),
            "channels": {f"CH{ch}": "OPEN" if status else "CLOSED" 
                        for ch, status in channel_status.items()}
        }
        message = json.dumps(data) + "\n"
        self._send_tcp(message.encode('utf-8'))
        self._send_udp(message.encode('utf-8'))
    
    def _send_tsl5(self, channel_status: Dict[int, bool]):
        """Send status in TSL UMD Protocol V5.0 format"""
        # Build TSL UMD V5.0 packet according to specification
        packet = self._build_tsl_umd_v5_packet(channel_status)
        
        if not packet:
            print("Warning: No packet to send (empty channel status)")
            return
        
        # Send via TCP with DLE/STX wrapper (if TCP is configured)
        wrapped_packet = self._wrap_tcp_packet(packet)
        self._send_tcp(wrapped_packet)
        
        # Send via UDP (direct packet, no wrapper per spec)
        self._send_udp_tsl5(packet)
    
    def _build_tsl_umd_v5_packet(self, channel_status: Dict[int, bool]) -> bytes:
        """
        Build TSL UMD Protocol V5.0 packet according to specification.
        
        Packet structure:
        - PBC (16-bit LE): Packet byte count (excludes PBC itself)
        - VER (8-bit): Version (0 for V5.00)
        - FLAGS (8-bit): Bit 0=0 (ASCII), Bit 1=0 (DMSG), Bits 2-7=0 (reserved)
        - SCREEN (16-bit LE): Screen index (0 = default, 0xFFFF = broadcast)
        - DMSG(s): Display messages (one per channel)
        
        DMSG structure:
        - INDEX (16-bit LE): Display address (0-based)
        - CONTROL (16-bit LE): Tally and brightness bits
          - Bits 0-1: RH Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER)
          - Bits 2-3: Text Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER)
          - Bits 4-5: LH Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER)
          - Bits 6-7: Brightness (0-3, 3=100%)
          - Bits 8-14: Reserved (0)
          - Bit 15: 0 = Display data, 1 = Control data
        - LENGTH (16-bit LE): Text byte count
        - TEXT: ASCII text (max 255 bytes per DMSG)
        """
        if not channel_status:
            return None
        
        dmsg_data = bytearray()
        
        # VER: Version 0 (V5.00)
        ver = 0
        
        # FLAGS: Bit 0 = 0 (ASCII), Bit 1 = 0 (DMSG), Bits 2-7 = 0 (reserved)
        flags = 0
        
        # SCREEN: Screen index (0 = default, 0xFFFF = broadcast)
        screen = 0
        
        # Build DMSG structures for each channel
        for ch in sorted(channel_status.keys()):
            # INDEX: 0-based display address
            index = ch - 1  # Convert to 0-based index (CH1 = 0, CH2 = 1, etc.)
            
            # CONTROL: Tally and brightness
            # Set tally based on fader status
            # If fader is open (True), set tally to GREEN (2)
            # If fader is closed (False), set tally to OFF (0)
            tally_value = 2 if channel_status[ch] else 0  # GREEN or OFF
            
            # Build CONTROL word
            # Bits 0-1: RH Tally
            # Bits 2-3: Text Tally
            # Bits 4-5: LH Tally
            # Bits 6-7: Brightness (3 = 100%)
            # Bits 8-14: Reserved (0)
            # Bit 15: 0 = Display data
            control = 0
            control |= (tally_value & 0x03) << 4  # LH Tally (bits 4-5)
            control |= (tally_value & 0x03) << 2  # Text Tally (bits 2-3)
            control |= (tally_value & 0x03)       # RH Tally (bits 0-1)
            control |= (3 << 6)  # Full brightness (bits 6-7 = 3)
            # Bit 15 = 0 (Display data, not control data) - already 0
            
            # TEXT: Channel label (e.g., "CH01", "CH02")
            text = f"CH{ch:02d}".encode('ascii')
            text_length = len(text)
            
            # Validate text length (max 255 bytes per spec)
            if text_length > 255:
                print(f"Warning: Text for channel {ch} is too long ({text_length} bytes), truncating")
                text = text[:255]
                text_length = 255
            
            # Add DMSG to packet
            # INDEX (16-bit little-endian)
            dmsg_data.extend(index.to_bytes(2, byteorder='little'))
            # CONTROL (16-bit little-endian)
            dmsg_data.extend(control.to_bytes(2, byteorder='little'))
            # LENGTH (16-bit little-endian)
            dmsg_data.extend(text_length.to_bytes(2, byteorder='little'))
            # TEXT
            dmsg_data.extend(text)
        
        # Build the complete packet with header
        complete_packet = bytearray()
        
        # PBC: Packet byte count (16-bit little-endian)
        # PBC is the byte count of the packet AFTER PBC itself
        # So: VER (1) + FLAGS (1) + SCREEN (2) + all DMSG data
        pbc = 1 + 1 + 2 + len(dmsg_data)  # VER + FLAGS + SCREEN + DMSG data
        complete_packet.extend(pbc.to_bytes(2, byteorder='little'))
        
        # VER
        complete_packet.append(ver)
        
        # FLAGS
        complete_packet.append(flags)
        
        # SCREEN
        complete_packet.extend(screen.to_bytes(2, byteorder='little'))
        
        # DMSG data
        complete_packet.extend(dmsg_data)
        
        # Validate total packet size (max 2048 bytes for UDP per spec)
        if len(complete_packet) > 2048:
            print(f"Warning: Packet size ({len(complete_packet)} bytes) exceeds UDP maximum (2048 bytes)")
        
        return bytes(complete_packet)
    
    def _wrap_tcp_packet(self, packet: bytes) -> bytes:
        """
        Wrap packet for TCP/IP transmission according to TSL UMD V5.0 spec.
        
        DLE = 0xFE
        STX = 0x02
        Packet start: DLE/STX
        DLE byte stuffing: DLE in packet becomes DLE/DLE
        Byte count fields are NOT affected by byte stuffing
        """
        DLE = 0xFE
        STX = 0x02
        
        wrapped = bytearray()
        wrapped.append(DLE)
        wrapped.append(STX)
        
        # Apply byte stuffing: any DLE in packet becomes DLE/DLE
        for byte in packet:
            wrapped.append(byte)
            if byte == DLE:
                wrapped.append(DLE)  # Double the DLE
        
        return bytes(wrapped)
    
    def _send_simple(self, channel_status: Dict[int, bool]):
        """Send status in simple CSV format"""
        lines = ["Channel,Status"]
        for ch in sorted(channel_status.keys()):
            status = "OPEN" if channel_status[ch] else "CLOSED"
            lines.append(f"{ch},{status}")
        message = "\n".join(lines) + "\n"
        self._send_tcp(message.encode('utf-8'))
        self._send_udp(message.encode('utf-8'))
    
    def _send_tcp(self, data: bytes):
        """Send data via TCP"""
        # Send to clients if server mode
        disconnected = []
        for client in self.tcp_clients:
            try:
                client.sendall(data)
            except Exception as e:
                print(f"Error sending to client: {e}")
                disconnected.append(client)
        
        # Remove disconnected clients
        for client in disconnected:
            if client in self.tcp_clients:
                self.tcp_clients.remove(client)
            try:
                client.close()
            except:
                pass
        
        # Send to TSL if client mode
        if self.tcp_client_socket:
            try:
                self.tcp_client_socket.sendall(data)
            except Exception as e:
                print(f"Lost connection to TSL: {e}")
                self.tcp_client_socket = None
    
    def _send_udp(self, data: bytes):
        """Send data via UDP (plain)"""
        if self.udp_socket and hasattr(self, 'udp_ip') and hasattr(self, 'udp_port'):
            try:
                self.udp_socket.sendto(data, (self.udp_ip, self.udp_port))
            except Exception as e:
                print(f"UDP send error: {e}")
    
    def _send_udp_tsl5(self, packet: bytes):
        """
        Send TSL UMD V5.0 packet via UDP.
        According to spec, UDP packets are sent directly without wrapper.
        Maximum packet length is 2048 bytes.
        """
        if not (self.udp_socket and hasattr(self, 'udp_ip') and hasattr(self, 'udp_port')):
            return
        
        if not packet:
            return
        
        try:
            # Check packet size (max 2048 bytes per spec)
            if len(packet) > 2048:
                print(f"Warning: Packet too long ({len(packet)} bytes), truncating to 2048 bytes")
                packet = packet[:2048]
            
            # Send packet directly (no wrapper for UDP per TSL UMD V5.0 spec)
            bytes_sent = self.udp_socket.sendto(packet, (self.udp_ip, self.udp_port))
            if bytes_sent != len(packet):
                print(f"Warning: Only sent {bytes_sent} of {len(packet)} bytes")
        except Exception as e:
            print(f"UDP TSL5 send error: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """Stop TSL bridge"""
        self.running = False
        if self.tcp_server_socket:
            try:
                self.tcp_server_socket.close()
            except:
                pass
        if self.tcp_client_socket:
            try:
                self.tcp_client_socket.close()
            except:
                pass
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
        for client in self.tcp_clients:
            try:
                client.close()
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description='Yamaha QL5 to TSL v5 Bridge')
    parser.add_argument('--yamaha-ip', default=YAMAHA_IP, help='Yamaha mixer IP address')
    parser.add_argument('--tsl-tcp-server-port', type=int, default=TSL_TCP_SERVER_PORT,
                        help='TCP server port (TSL connects to us)')
    parser.add_argument('--tsl-tcp-client', help='TSL TCP IP:PORT (we connect to TSL)')
    parser.add_argument('--tsl-udp', help='TSL UDP IP:PORT (send via UDP)')
    parser.add_argument('--format', choices=['json', 'tsl5', 'simple'], default='tsl5',
                        help='Output format: json, tsl5, or simple')
    parser.add_argument('--poll-interval', type=float, default=POLL_INTERVAL,
                        help='Poll interval in seconds')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--debug-tsl', action='store_true',
                        help='Enable TSL packet debugging (prints packet hex)')
    
    args = parser.parse_args()
    
    # Enable verbose mode
    verbose = args.verbose
    debug_tsl = args.debug_tsl
    
    if verbose:
        print(f"Verbose mode enabled")
        print(f"Target mixer: {args.yamaha_ip}:{YAMAHA_RCP_PORT}")
    
    if debug_tsl:
        print("TSL packet debugging enabled")
    
    # Initialize mixer
    mixer = YamahaMixer(args.yamaha_ip)
    
    # Initialize TSL bridge
    tsl = TSLBridge(debug=debug_tsl)
    
    # Setup TSL connections
    if args.tsl_tcp_client:
        # Client mode (connect to TSL)
        ip, port = args.tsl_tcp_client.split(':')
        tsl.connect_tcp_client(ip, int(port))
    else:
        # Server mode (TSL connects to us)
        tsl.start_tcp_server(args.tsl_tcp_server_port)
    
    if args.tsl_udp:
        # UDP mode
        ip, port = args.tsl_udp.split(':')
        tsl.start_udp(ip, int(port))
    
    # Connect to mixer
    if not mixer.connect():
        print("Failed to connect to mixer. Exiting.")
        return
    
    print("\nBridge running. Press Ctrl+C to stop.\n")
    
    # Store current status for new clients
    current_status_storage = {}
    
    # Callback for new client connections
    def send_current_status_to_new_client():
        if current_status_storage:
            tsl.send_status(current_status_storage, args.format)
    
    tsl.on_new_client = send_current_status_to_new_client
    
    try:
        previous_status = {}
        first_run = True
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        
        while True:
            # Check connection and reconnect if needed
            if not mixer.connected:
                if reconnect_attempts < max_reconnect_attempts:
                    if verbose:
                        print(f"[DEBUG] Connection lost, attempting reconnect (attempt {reconnect_attempts + 1}/{max_reconnect_attempts})...")
                    print(f"Attempting to reconnect to mixer (attempt {reconnect_attempts + 1}/{max_reconnect_attempts})...")
                    if mixer.connect():
                        print("Reconnected successfully!")
                        reconnect_attempts = 0
                    else:
                        reconnect_attempts += 1
                        if verbose:
                            print(f"[DEBUG] Reconnect failed, waiting 2 seconds before retry...")
                        time.sleep(2)  # Wait before retry
                        continue
                else:
                    print(f"Max reconnection attempts reached. Waiting 10 seconds before retrying...")
                    reconnect_attempts = 0
                    time.sleep(10)
                    continue
            
            # Get current fader status
            if verbose:
                print(f"[DEBUG] Polling fader status...")
            current_status = mixer.get_all_fader_status()
            
            # If we got no status and we're connected, connection might be bad
            if not current_status and mixer.connected:
                if verbose:
                    print(f"[DEBUG] No status data received but connection flag is True - marking as disconnected")
                print("Warning: No status data received, connection may be lost")
                mixer.connected = False
                continue
            
            if verbose and current_status:
                print(f"[DEBUG] Received status for {len(current_status)} channels")
            
            # Store current status for new clients
            if current_status:
                current_status_storage = current_status
            
            # Send status if we have data and (it changed, first run, or we have clients)
            has_clients = len(tsl.tcp_clients) > 0 or tsl.tcp_client_socket is not None
            if current_status and (current_status != previous_status or first_run or has_clients):
                tsl.send_status(current_status, args.format)
                first_run = False
                
                # Print summary
                open_count = sum(1 for s in current_status.values() if s)
                closed_count = sum(1 for s in current_status.values() if not s)
                client_count = len(tsl.tcp_clients) + (1 if tsl.tcp_client_socket else 0)
                print(f"[{time.strftime('%H:%M:%S')}] Status: {open_count} open, {closed_count} closed - sent to {client_count} TSL client(s)")
            
            previous_status = current_status
            time.sleep(args.poll_interval)
            
            # Reconnect if client connection lost
            if args.tsl_tcp_client and not tsl.tcp_client_socket:
                time.sleep(2)  # Wait before reconnect
                tsl.connect_tcp_client(ip, int(port))
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        mixer.disconnect()
        tsl.stop()
        print("Bridge stopped.")


if __name__ == "__main__":
    main()
