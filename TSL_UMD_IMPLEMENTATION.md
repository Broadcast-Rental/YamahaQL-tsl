# TSL UMD V5.0 Implementation Verification

## Protocol Compliance

The implementation follows the TSL UMD Protocol V5.0 specification correctly:

### Packet Structure ✓
- **PBC** (16-bit LE): Packet byte count (excludes PBC itself) ✓
- **VER** (8-bit): Version 0 (V5.00) ✓
- **FLAGS** (8-bit): Bit 0=0 (ASCII), Bit 1=0 (DMSG), Bits 2-7=0 (reserved) ✓
- **SCREEN** (16-bit LE): Screen index (0 = default) ✓
- **DMSG(s)**: Display messages (one per channel) ✓

### DMSG Structure ✓
- **INDEX** (16-bit LE): 0-based display address (CH1 = 0, CH2 = 1, etc.) ✓
- **CONTROL** (16-bit LE): Tally and brightness bits ✓
  - Bits 0-1: RH Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER) ✓
  - Bits 2-3: Text Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER) ✓
  - Bits 4-5: LH Tally (0=OFF, 1=RED, 2=GREEN, 3=AMBER) ✓
  - Bits 6-7: Brightness (0-3, 3=100%) ✓
  - Bits 8-14: Reserved (0) ✓
  - Bit 15: 0 = Display data ✓
- **LENGTH** (16-bit LE): Text byte count ✓
- **TEXT**: ASCII text (e.g., "CH01", "CH02") ✓

### Transmission Methods ✓

#### TCP/IP
- Wrapped with DLE (0xFE) + STX (0x02) at start ✓
- DLE byte stuffing: DLE bytes in packet become DLE/DLE ✓
- Byte count fields (PBC) are NOT affected by byte stuffing ✓

#### UDP/IP
- Direct packet transmission (no wrapper) ✓
- Maximum packet length: 2048 bytes ✓
- Packet size validation included ✓

## Tally Mapping

- **Fader OPEN** → GREEN tally (value 2) on all three positions (LH, Text, RH)
- **Fader CLOSED** → OFF tally (value 0) on all three positions

## Testing

Run the test script to verify packet construction:
```bash
python test_tsl_packet.py
```

This will:
- Build a test packet with 3 channels
- Verify packet structure
- Display packet contents in hex
- Test TCP wrapper
- Verify DLE byte stuffing

## Usage

### Via Web Interface
1. Connect to mixer
2. Configure TSL IP and port
3. Click "Start TSL Bridge"
4. Bridge will send updates every 250ms (or configured poll interval)

### Via Command Line
```bash
python yamaha_to_tsl_bridge.py \
  --yamaha-ip 172.20.40.13 \
  --tsl-udp 192.168.1.100:20000 \
  --format tsl5 \
  --poll-interval 0.25
```

## Packet Size Calculation

For 40 channels:
- Each DMSG: INDEX (2) + CONTROL (2) + LENGTH (2) + TEXT (4) = 10 bytes
- 40 channels: 40 × 10 = 400 bytes
- Header: PBC (2) + VER (1) + FLAGS (1) + SCREEN (2) = 6 bytes
- **Total: 406 bytes** (well under 2048 byte UDP limit)

## Validation

The implementation includes:
- ✓ Packet size validation (UDP max 2048 bytes)
- ✓ Text length validation (max 255 bytes per DMSG)
- ✓ Empty packet handling
- ✓ Error handling and logging
- ✓ TCP and UDP transmission support
