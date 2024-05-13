# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Flask application directory into the container
COPY src /app/src

# Ensure the backend data is copied
COPY backend_data /app/backend_data
# Ensure the static html templates are copied
COPY templates /app/templates

# Change the working directory to the Flask application directory
WORKDIR /app/src

# Expose port 5050 to allow communication to/from the Flask app
EXPOSE 5050

# Define environment variable for Flask
ENV FLASK_APP=app.py

# Install Gunicorn
RUN pip install gunicorn

# Run the Flask application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "app:app"]
