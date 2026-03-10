#!/usr/bin/env python3
"""
Yamaha QL5 Fader Status Monitor - Web Interface
Connects to a Yamaha QL5 mixer via TCP and displays the fader on/off status for all input channels.
"""

import socket
import threading
import time
import subprocess
import sys
import os
from flask import Flask, render_template, jsonify, request
from typing import Dict, Optional

# Default port for Yamaha RCP protocol
YAMAHA_RCP_PORT = 49280

# Number of input channels on QL5
QL5_INPUT_CHANNELS = 40

# Default TSL configuration
DEFAULT_TSL_PORT = 20000

app = Flask(__name__)

class YamahaMixerConnection:
    """Handles connection and communication with Yamaha mixer"""
    
    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.is_connected = False
        self.ip_address = ""
        self.status_data: Dict[int, Optional[bool]] = {}
        # Optional channel labels fetched from the mixer (CH number -> label string)
        self.channel_labels: Dict[int, str] = {}
        self.last_update_time = 0
        self.lock = threading.Lock()
        self.poll_thread: Optional[threading.Thread] = None
        self.polling_active = False
        self.poll_interval = 0.25  # 250ms
    
    def connect(self, ip_address: str) -> tuple[bool, str]:
        """Connect to the Yamaha mixer via TCP."""
        try:
            self.disconnect()
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # Increased timeout for initial connection
            
            print(f"Attempting to connect to {ip_address}:{YAMAHA_RCP_PORT}...")
            self.socket.connect((ip_address, YAMAHA_RCP_PORT))
            self.socket.settimeout(5)  # Set back to normal timeout after connection
            self.is_connected = True
            self.ip_address = ip_address
            print(f"Socket connected successfully to {ip_address}:{YAMAHA_RCP_PORT}")
            
            # Verify connection with a test command
            test_response = self.send_command("get MIXER:Current/InCh/Fader/Level 0 0")
            if test_response is None:
                print("Warning: Test command failed after connection")
                return True, "Connected (test command may have failed)"
            
            print(f"Connection verified with test command: {test_response[:50]}")
            # Start background polling
            self.start_polling()
            return True, "Connected successfully"
        except socket.timeout:
            error_msg = f"Connection timeout - mixer at {ip_address}:{YAMAHA_RCP_PORT} may be offline or unreachable"
            print(f"Connection error: {error_msg}")
            return False, error_msg
        except ConnectionRefusedError:
            error_msg = f"Connection refused by mixer at {ip_address}:{YAMAHA_RCP_PORT}"
            print(f"Connection error: {error_msg}")
            return False, error_msg
        except OSError as e:
            error_code = getattr(e, 'winerror', getattr(e, 'errno', None))
            if error_code == 11 or error_code == 10051:  # Network unreachable
                error_msg = f"Network unreachable: Cannot access {ip_address}:{YAMAHA_RCP_PORT}. If running in Docker, the container may not have access to your local network."
            else:
                error_msg = f"Network error (code {error_code}): {str(e)}"
            print(f"Connection error: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to connect: {str(e)}"
            print(f"Connection error: {error_msg}")
            import traceback
            traceback.print_exc()
            return False, error_msg
    
    def disconnect(self):
        """Disconnect from mixer"""
        self.stop_polling()
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.is_connected = False
    
    def start_polling(self):
        """Start background polling thread"""
        if self.polling_active:
            return
        self.polling_active = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        print("Started background polling at 250ms interval")
    
    def stop_polling(self):
        """Stop background polling thread"""
        self.polling_active = False
        if self.poll_thread:
            self.poll_thread.join(timeout=1)
            self.poll_thread = None
    
    def _poll_loop(self):
        """Background thread that continuously polls the mixer"""
        while self.polling_active and self.is_connected:
            try:
                self.fetch_all_fader_status()
                time.sleep(self.poll_interval)
            except Exception as e:
                print(f"Error in polling loop: {e}")
                if not self.is_connected:
                    break
                time.sleep(self.poll_interval)
    
    def send_command(self, command: str) -> Optional[str]:
        """Send a command to the mixer and wait for response."""
        if not self.is_connected or not self.socket:
            return None
        
        try:
            # Send command with newline
            self.socket.sendall((command + "\n").encode('utf-8'))
            
            # Receive response - filter out NOTIFY messages
            response = b""
            start_time = time.time()
            max_wait = 3
            
            while time.time() - start_time < max_wait:
                try:
                    self.socket.settimeout(0.5)
                    chunk = self.socket.recv(1024)
                    if chunk:
                        response += chunk
                        
                        # Check if we have complete lines
                        lines = response.split(b"\n")
                        # Filter for OK responses only (ignore NOTIFY)
                        ok_lines = [line for line in lines if line.startswith(b"OK") and b"get" in line]
                        
                        if ok_lines:
                            response_str = ok_lines[0].decode('utf-8', errors='ignore').strip()
                            return response_str
                    else:
                        # Empty chunk means connection closed
                        print("Connection closed by mixer (empty recv)")
                        self.is_connected = False
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
            self.is_connected = False
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
                self.is_connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
            return None
    
    def get_fader_status(self, channel_index: int) -> Optional[bool]:
        """Get fader open/closed status for a specific channel."""
        command = f"get MIXER:Current/InCh/Fader/Level {channel_index} 0"
        response = self.send_command(command)
        
        if response and response.startswith("OK"):
            parts = response.split()
            if len(parts) >= 2:
                try:
                    value = int(parts[-1])
                    # -32768 is negative infinity (closed/muted)
                    return value != -32768
                except (ValueError, IndexError):
                    return None
        return None

    def get_channel_label(self, channel_index: int) -> Optional[str]:
        """
        Get the user label/name for a given input channel.

        Uses: get MIXER:Current/InCh/Label/Name {ch} 0
        Returns the label string without surrounding quotes, or None on error.
        """
        command = f"get MIXER:Current/InCh/Label/Name {channel_index} 0"
        response = self.send_command(command)
        if not response or not response.startswith("OK"):
            return None

        first_quote = response.find('"')
        if first_quote != -1:
            last_quote = response.rfind('"')
            if last_quote > first_quote:
                return response[first_quote + 1:last_quote]

        parts = response.split()
        return parts[-1] if parts else None
    
    def fetch_all_fader_status(self) -> bool:
        """Fetch fader status for all input channels."""
        if not self.is_connected:
            return False
        
        with self.lock:
            status_data: Dict[int, Optional[bool]] = {}
            successful = 0
            
            for channel_idx in range(QL5_INPUT_CHANNELS):
                status = self.get_fader_status(channel_idx)
                channel_num = channel_idx + 1
                status_data[channel_num] = status
                # Fetch and cache channel label once per channel
                if channel_num not in self.channel_labels:
                    label = self.get_channel_label(channel_idx)
                    if label:
                        self.channel_labels[channel_num] = label
                if status is not None:
                    successful += 1
                time.sleep(0.01)  # Small delay to avoid overwhelming mixer
            
            if successful > 0:
                self.status_data = status_data
                self.last_update_time = time.time()
                return True
        
        return False
    
    def get_status(self) -> Dict:
        """Get current status data"""
        with self.lock:
            return {
                'connected': self.is_connected,
                'ip_address': self.ip_address,
                'status_data': self.status_data.copy(),
                'labels': self.channel_labels.copy(),
                'last_update': self.last_update_time,
                'summary': self._calculate_summary()
            }
    
    def _calculate_summary(self) -> Dict:
        """Calculate summary statistics"""
        open_count = sum(1 for s in self.status_data.values() if s is True)
        closed_count = sum(1 for s in self.status_data.values() if s is False)
        unknown_count = sum(1 for s in self.status_data.values() if s is None)
        return {
            'open': open_count,
            'closed': closed_count,
            'unknown': unknown_count,
            'total': QL5_INPUT_CHANNELS
        }


﻿# Global instance
mixer = YamahaMixerConnection()


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to mixer"""
    data = request.json
    ip_address = data.get('ip_address', '').strip()
    
    if not ip_address:
        return jsonify({'success': False, 'message': 'IP address is required'}), 400
    
    success, message = mixer.connect(ip_address)
    
    if success:
        # Fetch status immediately after connection
        mixer.fetch_all_fader_status()
    
    return jsonify({
        'success': success,
        'message': message,
        'status': mixer.get_status()
    })


@app.route('/api/disconnect', methods=['POST'])
def api_disconnect():
    """Disconnect from mixer"""
    mixer.disconnect()
    return jsonify({
        'success': True,
        'message': 'Disconnected',
        'status': mixer.get_status()
    })


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """Refresh fader status"""
    if not mixer.is_connected:
        return jsonify({
            'success': False,
            'message': 'Not connected to mixer',
            'status': mixer.get_status()
        }), 400
    
    success = mixer.fetch_all_fader_status()
    return jsonify({
        'success': success,
        'message': 'Status refreshed' if success else 'Failed to refresh',
        'status': mixer.get_status()
    })


@app.route('/api/status', methods=['GET'])
def api_status():
    """Get current status - data is automatically refreshed by background polling thread"""
    # Background polling thread handles updates, just return current status
    return jsonify(mixer.get_status())


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print("Starting Yamaha Fader Status Monitor Web Interface...")
    print(f"Open your browser to http://localhost:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
