# syntax=docker/dockerfile:1

# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the working directory inside the container
WORKDIR /app

# Layers are ordered from least to most frequently changed. The project source
# is copied last, so editing application code reuses every layer above it
# instead of reinstalling Chrome and all Python dependencies.

# Install system dependencies required for Chrome/Chromedriver.
# The upgrade runs here, while the package lists are present, to pick up
# security fixes for the base image (CVE patching).
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
    wget \
    unzip \
    gnupg \
    curl \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Chrome (new method without apt-key)
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-linux.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies. Only requirements.txt is copied first, so this
# layer is rebuilt when the dependencies change and not on every code change.
# The cache mount keeps downloaded wheels between builds without adding them
# to the image.
COPY requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy the project files into the container
COPY . /app/

# Ensure database directory exists
RUN mkdir -p /app/db

# Expose your app's port
EXPOSE 8550

# Run Django server
# CMD ["gunicorn", "--bind", "0.0.0.0:8550", "UploadData.wsgi:application"]
# CMD ["gunicorn", "--workers=5", "--timeout=120", "--bind", "0.0.0.0:8550", "UploadData.wsgi:application"]
# CMD ["celery", "-A", "UploadData", "worker", "--loglevel=info", "--pool=prefork"]
