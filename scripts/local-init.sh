#!/bin/sh
# Local development only: create the queues, bus, bucket, and secrets the app expects in the AWS
# emulator that compose.yaml starts. The names match what terraform/cluster creates in AWS.
set -eu

ACCOUNT=000000000000
REGION="${AWS_REGION:-us-east-1}"
export AWS_PAGER=""

queue() { aws sqs create-queue --queue-name "$1" --query QueueUrl --output text; }

queue shiptrack-carrier-events-dlq >/dev/null
queue shiptrack-notifications-dlq >/dev/null
queue shiptrack-carrier-events >/dev/null
queue shiptrack-notifications >/dev/null

aws events create-event-bus --name shiptrack >/dev/null
aws events put-rule --event-bus-name shiptrack --name shiptrack-notify \
  --event-pattern '{"source":["shiptrack.events"],"detail-type":["ShipmentDelivered","ShipmentException"]}' >/dev/null
aws events put-targets --event-bus-name shiptrack --rule shiptrack-notify \
  --targets "Id=notifications,Arn=arn:aws:sqs:${REGION}:${ACCOUNT}:shiptrack-notifications" >/dev/null

aws s3api create-bucket --bucket shiptrack-pod >/dev/null

secret() {
  aws secretsmanager create-secret --name "$1" --secret-string \
    "{\"username\":\"postgres\",\"password\":\"postgres\",\"host\":\"postgres\",\"port\":5432,\"dbname\":\"shiptrack\",\"engine\":\"postgres\"}" \
    >/dev/null
}
secret shiptrack/db/app
secret shiptrack/db/migrator

echo "local AWS resources are ready"
