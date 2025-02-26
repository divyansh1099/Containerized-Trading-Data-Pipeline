import websocket
import json
import logging
import signal
import time
import os
from confluent_kafka import Producer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment-based configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')  # Default to localhost
TRADING_PAIRS = os.getenv('TRADING_PAIRS', 'BTC-USD,ETH-USD').split(',')
WEBSOCKET_URL = "wss://ws-feed.exchange.coinbase.com"

# Global state for graceful shutdown
running = True
ws_conn = None
kafka_producer = None

def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    global running, ws_conn, kafka_producer
    logger.info("Initiating graceful shutdown...")
    running = False
    
    if ws_conn:
        ws_conn.close()
    if kafka_producer:
        kafka_producer.flush(30)

def create_kafka_producer():
    """Create Kafka producer with environment-aware config"""
    conf = {
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        'message.send.max.retries': 5,
        'retry.backoff.ms': 1000,
        'default.topic.config': {'acks': 'all'}
    }
    return Producer(conf)

def on_message(ws, message):
    """Process WebSocket messages"""
    try:
        data = json.loads(message)
        if data.get("type") == "match":
            # Validate and prepare message
            required_fields = ['trade_id', 'product_id', 'price', 'size', 'time']
            if not all(field in data for field in required_fields):
                logger.warning(f"Invalid message format: {data}")
                return
            
            # Send to Kafka
            kafka_producer.produce(
                topic='coinbase_trades',
                value=json.dumps(data).encode('utf-8'),
                callback=lambda err, msg: (
                    logger.error(f"Delivery failed: {err}") if err else None
                )
            )
            kafka_producer.poll(0)
            
            logger.info(f"Processed trade: {data['product_id']} @ {data['price']}")
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")

def connect_websocket():
    """WebSocket connection with retry logic"""
    global ws_conn
    retries = 0
    max_retries = 5
    
    while running and retries < max_retries:
        try:
            ws_conn = websocket.WebSocketApp(
                WEBSOCKET_URL,
                on_message=on_message,
                on_error=lambda ws, err: logger.error(f"WS error: {err}"),
                on_close=lambda ws: logger.info("WS connection closed")
            )
            ws_conn.on_open = lambda ws: (
                ws.send(json.dumps({
                    "type": "subscribe",
                    "product_ids": TRADING_PAIRS,
                    "channels": ["matches"]
                })),
                logger.info(f"Subscribed to {TRADING_PAIRS}")
            )
            ws_conn.run_forever()
            return
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            retries += 1
            time.sleep(2 ** retries)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")
        kafka_producer = create_kafka_producer()
        connect_websocket()
    finally:
        if kafka_producer:
            kafka_producer.flush(30)
        logger.info("Producer shutdown complete")