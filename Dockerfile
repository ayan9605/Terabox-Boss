FROM python:3.10-slim

# Set working directory first
WORKDIR /app

# Copy only requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (no cache to reduce image size)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run as non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Command to run the bot
CMD ["python", "bot.py"]
