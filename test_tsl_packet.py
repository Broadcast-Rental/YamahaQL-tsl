#!/usr/bin/env python3
"""
Test script to verify TSL UMD V5.0 packet construction
"""

import sys
sys.path.insert(0, '.')

from yamaha_to_tsl_bridge import TSLBridge

def test_packet_building():
    """Test TSL UMD V5.0 packet construction"""
    bridge = TSLBridge()
    
    # Test data: 3 channels
    channel_status = {
        1: True,   # Open
        2: False,  # Closed
        3: True    # Open
    }
    
    # Build packet
    packet = bridge._build_tsl_umd_v5_packet(channel_status)
    
    print(f"Packet length: {len(packet)} bytes")
    print(f"Packet hex: {packet.hex()}")
    print()
    
    # Parse and verify packet structure
    offset = 0
    
    # PBC (2 bytes, little-endian)
    pbc = int.from_bytes(packet[offset:offset+2], byteorder='little')
    offset += 2
    print(f"PBC (Packet Byte Count): {pbc}")
    
    # VER (1 byte)
    ver = packet[offset]
    offset += 1
    print(f"VER (Version): {ver} (V5.{ver:02d})")
    
    # FLAGS (1 byte)
    flags = packet[offset]
    offset += 1
    print(f"FLAGS: 0x{flags:02x} (Bit 0: ASCII={flags & 1}, Bit 1: DMSG={(flags >> 1) & 1})")
    
    # SCREEN (2 bytes, little-endian)
    screen = int.from_bytes(packet[offset:offset+2], byteorder='little')
    offset += 2
    print(f"SCREEN: {screen}")
    print()
    
    # Verify PBC matches actual packet size
    expected_pbc = len(packet) - 2  # Exclude PBC itself
    if pbc == expected_pbc:
        print(f"[OK] PBC is correct: {pbc} bytes")
    else:
        print(f"[ERROR] PBC mismatch: expected {expected_pbc}, got {pbc}")
    
    print()
    print("DMSG structures:")
    
    # Parse DMSG structures
    dmsg_count = 0
    while offset < len(packet):
        dmsg_count += 1
        print(f"\nDMSG {dmsg_count}:")
        
        # INDEX (2 bytes)
        index = int.from_bytes(packet[offset:offset+2], byteorder='little')
        offset += 2
        print(f"  INDEX: {index} (Display address)")
        
        # CONTROL (2 bytes)
        control = int.from_bytes(packet[offset:offset+2], byteorder='little')
        offset += 2
        rh_tally = control & 0x03
        text_tally = (control >> 2) & 0x03
        lh_tally = (control >> 4) & 0x03
        brightness = (control >> 6) & 0x03
        is_control_data = (control >> 15) & 1
        print(f"  CONTROL: 0x{control:04x}")
        print(f"    RH Tally: {rh_tally} ({'OFF' if rh_tally == 0 else 'RED' if rh_tally == 1 else 'GREEN' if rh_tally == 2 else 'AMBER'})")
        print(f"    Text Tally: {text_tally} ({'OFF' if text_tally == 0 else 'RED' if text_tally == 1 else 'GREEN' if text_tally == 2 else 'AMBER'})")
        print(f"    LH Tally: {lh_tally} ({'OFF' if lh_tally == 0 else 'RED' if lh_tally == 1 else 'GREEN' if lh_tally == 2 else 'AMBER'})")
        print(f"    Brightness: {brightness} ({brightness * 33.33:.0f}%)")
        print(f"    Control Data flag: {is_control_data}")
        
        # LENGTH (2 bytes)
        length = int.from_bytes(packet[offset:offset+2], byteorder='little')
        offset += 2
        print(f"  LENGTH: {length} bytes")
        
        # TEXT
        text = packet[offset:offset+length].decode('ascii')
        offset += length
        print(f"  TEXT: '{text}'")
    
    print()
    print(f"Total DMSG structures: {dmsg_count}")
    
    # Test TCP wrapper
    print("\n" + "="*50)
    print("Testing TCP wrapper:")
    wrapped = bridge._wrap_tcp_packet(packet)
    print(f"Original packet length: {len(packet)} bytes")
    print(f"Wrapped packet length: {len(wrapped)} bytes")
    print(f"Wrapper overhead: {len(wrapped) - len(packet)} bytes")
    print(f"Wrapped packet starts with: 0x{wrapped[0]:02x} 0x{wrapped[1]:02x} (DLE/STX)")
    
    # Verify DLE byte stuffing
    dle_count = packet.count(0xFE)
    if dle_count > 0:
        print(f"Original packet contains {dle_count} DLE bytes (0xFE)")
        print(f"Wrapped packet contains {wrapped.count(0xFE)} DLE bytes")
        if wrapped.count(0xFE) == dle_count * 2 + 2:  # +2 for DLE/STX at start
            print("[OK] DLE byte stuffing is correct")
        else:
            print("[ERROR] DLE byte stuffing may be incorrect")
    else:
        print("No DLE bytes in original packet (no stuffing needed)")

if __name__ == "__main__":
    test_packet_building()
