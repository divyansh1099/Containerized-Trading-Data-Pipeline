FROM python

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy consumer code
COPY consumer.py .

# Run the consumer
CMD ["python", "consumer.py"]