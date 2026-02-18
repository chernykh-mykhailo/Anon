# Use the official Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install dependencies
# Install dependencies and fonts for Cyrillic support
RUN apt-get update && apt-get install -y \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set working directory to source
WORKDIR /app/src

# Create temp directory inside src (optional, code handles it)
RUN mkdir -p temp

# Command to run the bot
CMD ["python", "main.py"]
