FROM apache/airflow:2.10.5-python3.11

# Install compatible provider versions
RUN pip install \
    psycopg2-binary \
    apache-airflow-providers-apache-kafka \
    apache-airflow-providers-postgres \
    apache-airflow-providers-openlineage \
    confluent-kafka \
    pandas