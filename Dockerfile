FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY yamaha_fader_status.py .
COPY yamaha_to_tsl_bridge.py .
COPY test_connection.py .
COPY templates/ ./templates/

# Create templates directory if it doesn't exist (safety check)
RUN mkdir -p templates

# Expose the web interface port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=yamaha_fader_status.py
ENV PYTHONUNBUFFERED=1

# Run the web application
CMD ["python", "yamaha_fader_status.py"]
