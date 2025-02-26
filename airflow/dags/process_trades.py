from airflow import DAG
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 2, 17, 0, 20),  # Start from first trade
    'catchup': True,  # Enable backfilling of historical data
    'retries': 3,
    'retry_delay': timedelta(minutes=2),
}

def process_trades(**context):
    execution_date = context['data_interval_start']
    next_execution_date = context['data_interval_end']
    
    print(f"🔍 Airflow Querying Trades from: {execution_date} to {next_execution_date}")

    
    try:
        # Source connection (Docker PostgreSQL)
        src_hook = PostgresHook(postgres_conn_id='docker_postgres')
        query = """
            SELECT trade_id, product_id, side, price, size, time, sequence
            FROM trades
            WHERE time >= %s AND time < %s;
        """
        df = src_hook.get_pandas_df(
            sql=query,
            parameters=(execution_date, next_execution_date)
        )
        
        if df.empty:
            print("No new trades to process.")
            return
        
        # Ensure 'side' column has string values
        df['side'] = df['side'].astype(str).str.lower().str.strip()
        
        # Split into buy/sell
        buy_df = df[df['side'] == 'buy']
        sell_df = df[df['side'] == 'sell']
        
        # Target connection (Local PostgreSQL)
        dest_hook = PostgresHook(postgres_conn_id='local_postgres')
        
        # Insert buy trades
        if not buy_df.empty:
            buy_records = [tuple(x) for x in buy_df.to_numpy()]
            dest_hook.insert_rows(
                table='public.buy_trades',
                rows=buy_records,
                target_fields=['trade_id', 'product_id', 'side', 'price', 'size', 'time', 'sequence']
            )
        
        # Insert sell trades
        if not sell_df.empty:
            sell_records = [tuple(x) for x in sell_df.to_numpy()]
            dest_hook.insert_rows(
                table='public.sell_trades',
                rows=sell_records,
                target_fields=['trade_id', 'product_id', 'side', 'price', 'size', 'time', 'sequence']
            )
        
        print("Data transfer completed successfully.")
    
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        raise

with DAG(
    'process_trades',  # Change from 'process_trades_dag'
    default_args=default_args,
    schedule_interval='*/3 * * * *',
    max_active_runs=1,
    tags=['trading'],
) as dag:

    process_task = PythonOperator(
        task_id='process_trades_task',
        python_callable=process_trades
    )
