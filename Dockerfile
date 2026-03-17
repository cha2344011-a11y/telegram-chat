FROM python:3.11-slim

WORKDIR /app

# System dependencies for Pillow and building
RUN apt-get update && apt-get install -y \
    build-essential \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the Flask health check app and Userbot
CMD ["python", "main.py"]
