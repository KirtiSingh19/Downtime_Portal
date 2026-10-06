# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy the project files into the container
COPY . /app/

# Install system dependencies required for Chrome/Chromedriver
RUN apt-get update && apt-get install -y \
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
    rm -rf /var/lib/apt/lists/*

# Install Chrome (new method without apt-key)
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-linux.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# # Install Chrome
# RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
#     echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
#     apt-get update && \
#     apt-get install -y google-chrome-stable && \
#     rm -rf /var/lib/apt/lists/*

# Fix CVEs by upgrading system packages
RUN apt-get upgrade -y && apt-get clean

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN pip install scp

# Ensure database directory exists
RUN mkdir -p /app/db

# Expose your app's port
EXPOSE 8550

# Run Django server
# CMD ["gunicorn", "--bind", "0.0.0.0:8550", "UploadData.wsgi:application"]
# CMD ["gunicorn", "--workers=5", "--timeout=120", "--bind", "0.0.0.0:8550", "UploadData.wsgi:application"]
# CMD ["celery", "-A", "UploadData", "worker", "--loglevel=info", "--pool=prefork"]
