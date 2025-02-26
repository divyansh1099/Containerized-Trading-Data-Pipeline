from confluent_kafka import Consumer, KafkaError
import json
import logging
import os
import time
import psycopg2
from psycopg2 import sql, errors as pg_errors
from prometheus_client import Counter, start_http_server
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------
# Configuration
# --------------------------
REQUIRED_ENV_VARS = {
    'KAFKA_BOOTSTRAP_SERVERS': 'kafka:9093',
    'POSTGRES_HOST': 'postgres',
    'POSTGRES_DB': 'financial',
    'POSTGRES_USER': 'airflow',
    'POSTGRES_PASSWORD': 'airflow'
}

def validate_config():
    """Set default values for missing environment variables"""
    for var, default in REQUIRED_ENV_VARS.items():
        if not os.getenv(var):
            os.environ[var] = default
            logger.warning(f"Using default value for {var}: {default}")

validate_config()

# --------------------------
# PostgreSQL Manager
# --------------------------
class PostgreSQLManager:
    def __init__(self):
        self.conn = None
        self._connect_with_retry()
        self._initialize_schema()
    
    def _connect_with_retry(self, max_retries: int = 5, backoff: int = 2):
        """Retry connection with exponential backoff"""
        for attempt in range(max_retries):
            try:
                self.conn = psycopg2.connect(
                    host=os.getenv('POSTGRES_HOST'),
                    database=os.getenv('POSTGRES_DB'),
                    user=os.getenv('POSTGRES_USER'),
                    password=os.getenv('POSTGRES_PASSWORD'),
                    port=os.getenv('POSTGRES_PORT', 5432)
                )
                logger.info("Connected to PostgreSQL database")
                return
            except (pg_errors.OperationalError, pg_errors.InterfaceError) as e:
                if attempt == max_retries - 1:
                    raise
                sleep_time = backoff ** attempt
                logger.warning(f"Connection failed (attempt {attempt+1}): {e}. Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
    
    def _initialize_schema(self):
        """Create required tables if they don't exist"""
        create_table_query = """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id VARCHAR PRIMARY KEY,
                product_id VARCHAR NOT NULL,
                side VARCHAR NOT NULL,
                price NUMERIC NOT NULL,
                size NUMERIC NOT NULL,
                time TIMESTAMP NOT NULL,
                sequence BIGINT NOT NULL
            );
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(create_table_query)
                self.conn.commit()
                logger.info("Ensured 'trades' table exists")
        except pg_errors.Error as e:
            logger.error(f"Schema initialization failed: {str(e)}")
            raise

    def __enter__(self):
        if self.conn is None or self.conn.closed:
            self._connect_with_retry()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn and not self.conn.closed:
            self.conn.close()

# --------------------------
# Kafka Consumer
# --------------------------
class TradeConsumer:
    def __init__(self):
        self.consumer = Consumer({
            'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS'),
            'group.id': os.getenv('KAFKA_CONSUMER_GROUP', 'coinbase_consumer_group'),
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,
            'max.poll.interval.ms': 300000
        })
        self.running = True
        
        # Initialize Prometheus metrics once during instance creation
        self.trade_volume = Counter(
            'trade_volume', 
            'Total trade volume', 
            ['side', 'product_id']
        )
        self.trade_count = Counter(
            'trade_count', 
            'Total trade count', 
            ['side', 'product_id']
        )

    def _decode_message(self, msg) -> Optional[Dict[str, Any]]:
        try:
            message_value = msg.value().decode('utf-8', errors='replace')
            trade_data = json.loads(message_value)
            
            required_fields = {
                'trade_id': (str, int),
                'product_id': str,
                'side': str,
                'price': (float, int),
                'size': (float, int),
                'time': str,
                'sequence': int
            }
            
            for field, types in required_fields.items():
                if field not in trade_data:
                    raise ValueError(f"Missing required field: {field}")
                
                if field == 'trade_id':
                    trade_data[field] = str(trade_data[field])
                elif field in ['price', 'size']:
                    trade_data[field] = float(trade_data[field])
                elif field == 'sequence':
                    trade_data[field] = int(trade_data[field])
                
                if not isinstance(trade_data[field], types):
                    raise TypeError(f"Invalid type for {field}: {type(trade_data[field])}")
            
            return trade_data
            
        except Exception as e:
            logger.error(f"Invalid message: {msg.value()}", exc_info=True)
            return None

    def _process_trade(self, trade_data: Dict[str, Any]):
        """Process and store validated trade"""
        try:
            with PostgreSQLManager() as pg:
                if pg.conn.closed != 0:
                    pg._connect_with_retry()
                
                with pg.conn.cursor() as cursor:
                    insert_query = sql.SQL("""
                        INSERT INTO trades 
                            (trade_id, product_id, side, price, size, time, sequence)
                        VALUES 
                            (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (trade_id) DO NOTHING
                    """)
                    
                    cursor.execute(insert_query, (
                        trade_data['trade_id'],
                        trade_data['product_id'],
                        trade_data['side'],
                        trade_data['price'],
                        trade_data['size'],
                        trade_data['time'],
                        trade_data['sequence']
                    ))
                    
                    if cursor.rowcount > 0:
                        pg.conn.commit()
                        self._update_metrics(trade_data)
                        logger.debug(f"Processed trade {trade_data['trade_id']}")
                    else:
                        logger.warning(f"Duplicate trade detected: {trade_data['trade_id']}")
                        
        except pg_errors.Error as e:
            logger.error(f"Database error: {str(e)}")
            if pg.conn and not pg.conn.closed:
                pg.conn.rollback()

    def _update_metrics(self, trade_data: Dict[str, Any]):
        """Update Prometheus metrics using pre-initialized counters"""
        labels = {
            'side': trade_data['side'].lower(),
            'product_id': trade_data['product_id']
        }
        self.trade_volume.labels(**labels).inc(float(trade_data['size']))
        self.trade_count.labels(**labels).inc()

    def run(self):
        """Main consumer loop"""
        start_http_server(8000)
        logger.info("Metrics server started on port 8000")
        
        self.consumer.subscribe([os.getenv('KAFKA_TOPIC', 'coinbase_trades')])
        logger.info(f"Subscribed to topic: {os.getenv('KAFKA_TOPIC', 'coinbase_trades')}")

        try:
            while self.running:
                msg = self.consumer.poll(5.0)
                
                if msg is None:
                    continue
                    
                if msg.error():
                    logger.error(f"Kafka error: {msg.error()}")
                    continue
                
                if trade_data := self._decode_message(msg):
                    self._process_trade(trade_data)
                    self.consumer.commit(msg)
                    
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
        finally:
            self.consumer.close()
            logger.info("Kafka consumer closed")

if __name__ == "__main__":
    consumer = TradeConsumer()
    consumer.run()