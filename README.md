# Yamaha QL5 Fader Status Monitor & TSL Bridge

Python applications to monitor fader status on a Yamaha QL5 mixer and integrate with TSL v5.

## Applications

### 1. Web Monitor (`yamaha_fader_status.py`)
A web-based application to monitor fader on/off status for all input channels on a Yamaha QL5 mixer.

**Features:**
- Connect to Yamaha QL5 mixer via TCP/IP
- Display fader status (open/closed) for all 40 input channels
- Real-time status refresh (auto-updates every 2 seconds)
- Modern, responsive web interface accessible from any device
- Control TSL bridge directly from the web interface

### 2. TSL Bridge (`yamaha_to_tsl_bridge.py`)
A service that bridges Yamaha QL5 fader status to TSL v5 for broadcast integration.

**Features:**
- Connects to Yamaha mixer and polls fader status
- Sends status to TSL v5 via TCP (server or client mode) or UDP
- Multiple output formats (JSON, TSL5, Simple CSV)
- Configurable poll interval
- Automatic reconnection on connection loss

## Requirements

### Local Development
- Python 3.6 or higher
- Flask 2.0.0 or higher

Install dependencies:
```bash
pip install -r requirements.txt
```

### Docker (Recommended for Production)
- Docker and Docker Compose
- Or use Portainer for easy deployment

## Usage

### Option 1: Docker Compose (Recommended)

1. Build and start the container:
   ```bash
   docker-compose up -d
   ```

2. Open your web browser and navigate to:
   - Local: http://localhost:5000
   - Network: http://YOUR_IP:5000

3. Enter the IP address of your Yamaha QL5 mixer in the input field (default: 172.20.40.13)

4. Click "Connect" to connect to the mixer and fetch fader status

5. The status will automatically refresh every 2 seconds when connected

6. Use "Refresh Status" to manually update the fader status

To stop:
```bash
docker-compose down
```

### Option 2: Portainer Deployment

1. In Portainer, go to **Stacks** → **Add Stack**

2. Name your stack (e.g., `yamaha-tsl-bridge`)

3. Paste the contents of `docker-compose.yml` into the web editor

4. Click **Deploy the stack**

5. The container will build and start automatically

6. Access the web interface at `http://YOUR_SERVER_IP:5000`

**Note:** Make sure port 5000 is accessible in your network/firewall settings.

### Option 3: Local Python

1. Start the web server:
   ```bash
   python yamaha_fader_status.py
   ```

2. Open your web browser and navigate to:
   - Local: http://localhost:5000
   - Network: http://YOUR_IP:5000

3. Enter the IP address of your Yamaha QL5 mixer in the input field (default: 172.20.40.13)

4. Click "Connect" to connect to the mixer and fetch fader status

5. The status will automatically refresh every 2 seconds when connected

6. Use "Refresh Status" to manually update the fader status

## Protocol Details

- **Port:** 49280 (default Yamaha RCP protocol port)
- **Protocol:** TCP/IP
- **Command Format:** `get MIXER:Current/InCh/Fader/On {channel} 0`
  - Channel index is 0-based (0 = Channel 1, 39 = Channel 40)
  - Response: `OK 0` (closed/off) or `OK 1` (open/on)

## Display

The application shows:
- Connection status
- Summary count of open/closed channels
- Detailed status for all 40 input channels displayed in rows of 10

## TSL v5 Integration

The TSL bridge service allows you to send Yamaha mixer fader status to TSL v5 for broadcast automation.

### Quick Start

**TCP Server Mode (TSL connects to bridge):**
```bash
python yamaha_to_tsl_bridge.py --yamaha-ip 172.20.40.13 --tsl-tcp-server-port 20000 --format tsl5
```

**TCP Client Mode (Bridge connects to TSL):**
```bash
python yamaha_to_tsl_bridge.py --yamaha-ip 172.20.40.13 --tsl-tcp-client 192.168.1.100:20000 --format tsl5
```

**UDP Mode:**
```bash
python yamaha_to_tsl_bridge.py --yamaha-ip 172.20.40.13 --tsl-udp 192.168.1.100:20000 --format tsl5
```

### Command Line Options

- `--yamaha-ip`: Yamaha mixer IP address (default: 172.20.40.13)
- `--tsl-tcp-server-port`: TCP server port when TSL connects to bridge (default: 20000)
- `--tsl-tcp-client`: TSL IP:PORT when bridge connects to TSL (e.g., 192.168.1.100:20000)
- `--tsl-udp`: TSL IP:PORT for UDP mode (e.g., 192.168.1.100:20000)
- `--format`: Output format - `json`, `tsl5`, or `simple` (default: tsl5)
- `--poll-interval`: Poll interval in seconds (default: 0.5)

### Output Formats

**TSL5 Format:**
```
CH01:1
CH02:0
CH03:1
...
```
Where `1` = OPEN, `0` = CLOSED

**JSON Format:**
```json
{
  "timestamp": 1234567890.123,
  "channels": {
    "CH1": "OPEN",
    "CH2": "CLOSED",
    ...
  }
}
```

**Simple CSV Format:**
```
Channel,Status
1,OPEN
2,CLOSED
...
```

### TSL Configuration

1. **TCP Server Mode:** Configure TSL to connect to the bridge:
   - IP: Your computer running the bridge
   - Port: `--tsl-tcp-server-port` value (default: 20000)

2. **TCP Client Mode:** Configure the bridge to connect to TSL:
   - Use `--tsl-tcp-client TSL_IP:PORT`

3. **UDP Mode:** Configure the bridge to send UDP packets:
   - Use `--tsl-udp TSL_IP:PORT`

### Running as a Service

**Docker (Recommended):**
- Use `docker-compose up -d` to run in the background
- The container will automatically restart on failure with `restart: unless-stopped`
- Use Portainer to manage the container lifecycle

**Windows:**
- Run the bridge as a background service using Task Scheduler or NSSM
- Or use Docker Desktop with auto-start enabled

**Linux:**
- Create a systemd service file or use supervisor
- Or use Docker with systemd service for auto-start

## Notes

- The mixer must be on the same network as your computer
- The mixer's IP address must be accessible from your computer
- The application uses the Yamaha RCP (Remote Control Protocol) over TCP/IP
- Fader status is determined by `Fader/Level`: `-32768` = CLOSED, anything else = OPEN
- The bridge polls the mixer at regular intervals (default: 0.5 seconds)
