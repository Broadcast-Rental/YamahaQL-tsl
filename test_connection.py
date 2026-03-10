#!/usr/bin/env python3
"""
Diagnostic script to test Yamaha mixer connection
"""

import socket
import sys

YAMAHA_RCP_PORT = 49280
YAMAHA_IP = "172.20.40.13"

def test_connection(ip_address: str):
    """Test connection to Yamaha mixer"""
    print(f"Testing connection to {ip_address}:{YAMAHA_RCP_PORT}...")
    
    # Test 1: Basic socket connection
    print("\n1. Testing basic socket connection...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((ip_address, YAMAHA_RCP_PORT))
        print("   [OK] Socket connection successful")
        sock.close()
    except Exception as e:
        print(f"   [FAIL] Socket connection failed: {e}")
        return False
    
    # Test 2: Send a command
    print("\n2. Testing command send/receive...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((ip_address, YAMAHA_RCP_PORT))
        sock.settimeout(5)
        
        # Send test command
        command = "get MIXER:Current/InCh/Fader/Level 0 0\n"
        sock.sendall(command.encode('utf-8'))
        print(f"   [OK] Command sent: {command.strip()}")
        
        # Receive response
        import time
        response = b""
        start_time = time.time()
        max_wait = 5
        
        while time.time() - start_time < max_wait:
            try:
                sock.settimeout(1)
                chunk = sock.recv(1024)
                if chunk:
                    response += chunk
                    print(f"   Received chunk: {chunk[:100]}")
                    # Check for OK response
                    if b"OK" in response:
                        print(f"   [OK] Received OK response: {response.decode('utf-8', errors='ignore')[:200]}")
                        sock.close()
                        return True
                else:
                    break
            except socket.timeout:
                if response:
                    if b"OK" in response:
                        print(f"   [OK] Received OK response (timeout): {response.decode('utf-8', errors='ignore')[:200]}")
                        sock.close()
                        return True
                continue
        
        if response:
            print(f"   [WARN] Received response but no OK: {response.decode('utf-8', errors='ignore')[:200]}")
        else:
            print("   [FAIL] No response received")
        
        sock.close()
        return False
    except Exception as e:
        print(f"   [FAIL] Command test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else YAMAHA_IP
    success = test_connection(ip)
    sys.exit(0 if success else 1)
