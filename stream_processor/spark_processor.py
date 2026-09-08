import os
import sys

# Prevent OpenBLAS Memory Allocation errors on Windows with multiple processes
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# Set up environment variables to point to Python (solves some Windows PySpark issues)
os.environ["PYSPARK_PYTHON"] = sys.executable
os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env variables (with fallback parser)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except Exception:
    pass

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass

import pyspark
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json, window, avg, round as spark_round
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

DEFAULT_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "gridpulse.telemetry.raw")

def get_spark_session():
    """Initializes a local SparkSession with Kafka streaming dependencies."""
    spark_version = "3.5.0"
    print(f"[SPARK INIT] Using Spark Version: {spark_version}")
    
    # We use the Scala 2.12 package for spark-sql-kafka and postgresql jdbc matching the Spark version
    kafka_package = f"org.apache.spark:spark-sql-kafka-0-10_2.12:{spark_version}"
    postgres_package = "org.postgresql:postgresql:42.6.0"
    
    spark = SparkSession.builder \
        .appName("GridPulse-Streaming-Analytics") \
        .master("local[*]") \
        .config("spark.jars.packages", f"{kafka_package},{postgres_package}") \
        .config("spark.sql.shuffle.partitions", "4") \
        .getOrCreate()
        
    spark.sparkContext.setLogLevel("WARN")
    return spark

def define_schema():
    """Defines the schema of our incoming IoT telemetry JSON."""
    return StructType([
        StructField("event_id", StringType(), True),
        StructField("timestamp", TimestampType(), True),
        StructField("meter_id", StringType(), True),
        StructField("building_id", StringType(), True),
        StructField("power_kw", DoubleType(), True),
        StructField("voltage_v", DoubleType(), True),
        StructField("current_a", DoubleType(), True),
        StructField("power_factor", DoubleType(), True)
    ])

def start_stream_processor(output_mode="console"):
    """
    Reads telemetry from Kafka, applies a 5-minute sliding window,
    and sinks the aggregated metrics to PostgreSQL.
    """
    spark = get_spark_session()
    
    print(f"[SPARK STREAMING] Connecting to Kafka at {DEFAULT_BOOTSTRAP_SERVERS}, topic: '{DEFAULT_TOPIC}'")
    
    # 1. Read Stream from Kafka
    raw_kafka_df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", DEFAULT_BOOTSTRAP_SERVERS) \
        .option("subscribe", DEFAULT_TOPIC) \
        .option("startingOffsets", "earliest") \
        .option("failOnDataLoss", "false") \
        .load()
        
    # 2. Parse JSON Value
    schema = define_schema()
    parsed_df = raw_kafka_df.selectExpr("CAST(value AS STRING)") \
        .select(from_json(col("value"), schema).alias("data")) \
        .select("data.*")
        
    # 3. Apply Sliding Window Aggregations (5-minute window, sliding every 1 minute)
    aggregated_df = parsed_df \
        .withWatermark("timestamp", "5 minutes") \
        .groupBy(
            window(col("timestamp"), "5 minutes", "1 minute"),
            col("building_id")
        ) \
        .agg(
            spark_round(avg("power_kw"), 2).alias("avg_power_kw"),
            spark_round(avg("voltage_v"), 2).alias("avg_voltage_v"),
            spark_round(avg("power_factor"), 3).alias("avg_power_factor")
        )
        
    # 4. Sink to PostgreSQL (Phase 4)
    print("\n[SPARK SINK] Starting PostgreSQL Sink. Awaiting micro-batches...\n")
    
    def write_to_postgres(df, epoch_id):
        from pyspark.sql.functions import col
        
        # Extract window start and end, select exact DB columns
        df_out = df.withColumn("window_start", col("window.start")) \
                   .withColumn("window_end", col("window.end")) \
                   .drop("window") \
                   .select(
                       col("window_start"),
                       col("window_end"),
                       col("building_id"),
                       col("avg_power_kw"),
                       col("avg_voltage_v"),
                       col("avg_power_factor")
                   )
                   
        from urllib.parse import urlparse
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/neondb")
        parsed = urlparse(db_url)
        db_user = parsed.username or os.getenv("DB_USER", "postgres")
        db_password = parsed.password or os.getenv("DB_PASSWORD", "")
        jdbc_host = parsed.hostname or "localhost"
        jdbc_port = parsed.port or 5432
        jdbc_db = parsed.path or "/neondb"
        jdbc_url = f"jdbc:postgresql://{jdbc_host}:{jdbc_port}{jdbc_db}?sslmode=require"
        
        try:
            # Optimization: batchsize controls the number of rows per JDBC batch insert
            df_out.write \
                .format("jdbc") \
                .option("url", jdbc_url) \
                .option("dbtable", "building_energy_aggregates") \
                .option("user", db_user) \
                .option("password", db_password) \
                .option("driver", "org.postgresql.Driver") \
                .option("batchsize", "5000") \
                .option("isolationLevel", "NONE") \
                .mode("append") \
                .save()
            print(f"[SPARK BATCH {epoch_id}] Successfully wrote batch to PostgreSQL.")
        except Exception as e:
            print(f"[SPARK BATCH {epoch_id}] ⚠️ Error writing to PostgreSQL: {e}")
            
    # Optimization: Trigger time set to 15 seconds. 
    # Balances UI freshness vs excessive PostgreSQL connection/write overhead.
    query = aggregated_df.writeStream \
        .outputMode("update") \
        .foreachBatch(write_to_postgres) \
        .trigger(processingTime="15 seconds") \
        .start()
        
    # 5. Phase 5: Sink Raw Telemetry to Data Lake (Parquet)
    from pyspark.sql.functions import year, month, dayofmonth
    print("\n[SPARK SINK] Starting Data Lake Sink (Parquet partitioned by year/month/day)...\n")
    
    enriched_df = parsed_df \
        .withColumn("year", year(col("timestamp"))) \
        .withColumn("month", month(col("timestamp"))) \
        .withColumn("day", dayofmonth(col("timestamp")))
        
    lake_path = "/app/data/lake/raw_telemetry" if os.path.exists("/app") else os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")
    checkpoint_path = "/app/data/lake/checkpoints/raw_telemetry" if os.path.exists("/app") else os.path.join(PROJECT_ROOT, "data", "lake", "checkpoints", "raw_telemetry")
    
    lake_query = enriched_df.writeStream \
        .outputMode("append") \
        .format("parquet") \
        .option("path", lake_path) \
        .option("checkpointLocation", checkpoint_path) \
        .partitionBy("year", "month", "day") \
        .trigger(processingTime="30 seconds") \
        .start()
        
    spark.streams.awaitAnyTermination()

if __name__ == "__main__":
    start_stream_processor()
