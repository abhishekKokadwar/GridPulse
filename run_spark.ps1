$project_root = (Get-Item -Path ".\").FullName
$script_dir = "$project_root\stream_processor"

Write-Host "[DOCKER SPARK] Submitting Spark Structured Streaming Job to bitnami/spark:3.5..."
Write-Host "Mounting $script_dir to /app in container..."

# We set KAFKA_BOOTSTRAP_SERVERS to the internal docker-compose network name 'kafka:29092'
docker run -d `
  --network gridpulse_default `
  --name spark-processor `
  -u root `
  -e HOME=/tmp `
  -e KAFKA_BOOTSTRAP_SERVERS="kafka:29092" `
  -v "$($project_root):/app" `
  apache/spark:3.5.0 `
  /opt/spark/bin/spark-submit --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,org.postgresql:postgresql:42.6.0 /app/stream_processor/spark_processor.py
