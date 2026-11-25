#!/bin/bash
set -e

# Write custom CloudWatch agent configuration to collect CPU metrics
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "metrics": {
    "metrics_collected": {
      "cpu": {
        "measurement": [
          {"name": "cpu_usage_idle", "unit": "Percent"}
        ],
        "resources": ["*"],
        "total": true
      }
    }
  }
}
EOF

# Restart the CloudWatch agent to pick up the new configuration
systemctl restart amazon-cloudwatch-agent
