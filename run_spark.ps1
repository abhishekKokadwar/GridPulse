$project_root = (Get-Item -Path ".\").FullName

Write-Host "[DOCKER SPARK] Stopping any existing spark-processor container..."
docker rm -f spark-processor 2>$null

Write-Host "[DOCKER SPARK] Submitting Spark Structured Streaming Job to apache/spark:3.5.0..."
Write-Host "Attaching to network 'gridpulse_gridpulse-prod-net' -> Kafka 'kafka:29092'..."

docker run -d `
  --network gridpulse_gridpulse-prod-net `
  --name spark-processor `
  -u 0 `
  -e HOME=/tmp `
  -e KAFKA_BOOTSTRAP_SERVERS="kafka:29092" `
  -v "$($project_root):/app" `
  --env-file "$project_root\.env" `
  apache/spark:3.5.0 `
  /opt/spark/bin/spark-submit --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,org.postgresql:postgresql:42.6.0 /app/stream_processor/spark_processor.py

Write-Host "[OK] Spark Structured Streaming container launched."
