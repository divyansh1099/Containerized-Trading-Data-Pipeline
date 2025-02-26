# Containerized Trading Data Pipeline

## Overview
This project implements a containerized data pipeline for streaming, processing, and monitoring financial transactions. It utilizes Apache Kafka for real-time ingestion, PostgreSQL for storage, and Apache Airflow for orchestration. The infrastructure is fully Dockerized and includes monitoring using Prometheus and Grafana.

## Features
- **Real-time data ingestion**: Kafka producers consume financial trade data.
- **Storage**: Kafka consumers write data to PostgreSQL.
- **Data Transformation**: Airflow DAG processes and categorizes trades into `buy` and `sell` tables.
- **Monitoring**: Prometheus scrapes Kafka, PostgreSQL, and Airflow metrics, visualized in Grafana.

## Architecture
The pipeline consists of the following components:
- **Kafka & Zookeeper**: Manages real-time data streaming.
- **PostgreSQL**: Stores incoming trade data.
- **Airflow**: Automates ETL tasks.
- **Prometheus & Grafana**: Provides monitoring and visualization.

## File Structure
```
.
├── airflow/                 # Airflow DAGs
├── kafka/                   # Kafka producers & consumers
├── monitoring/              # Prometheus & Grafana configs
├── docker-compose.yml       # Docker orchestration file
├── requirements.txt         # Python dependencies
├── README.md                # Documentation
```

## Dependencies
Install required Python packages using:
```sh
pip install -r requirements.txt
```

For contributions, create a pull request or report issues in the repository.

Happy Coding! 🚀

