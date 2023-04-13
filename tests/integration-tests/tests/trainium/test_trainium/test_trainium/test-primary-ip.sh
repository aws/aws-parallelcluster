#!/bin/bash
# Test the alignment of the Route 53 IP and the the host IP.

OUTPUT_FILE="output-primary-ip.txt"

# Get DNS Server
DNS_SERVER=""
grep Ubuntu /etc/issue &>/dev/null && DNS_SERVER=$(systemd-resolve --status | grep "DNS Servers" | awk '{print $3}' | sort -r | head -1)

# Determine expected entry in /etc/hosts
IP="$(host $HOSTNAME $DNS_SERVER | tail -1 | awk '{print $4}')"
DOMAIN=$(jq .cluster.dns_domain /etc/chef/dna.json | tr -d \")
EXPECTED="$IP $HOSTNAME.${DOMAIN::-1} $HOSTNAME"
echo "Expected entry in /etc/hosts: $EXPECTED" | tee $OUTPUT_FILE

# Retrieve actual entry in /etc/hosts
ACTUAL="$(grep "$HOSTNAME" /etc/hosts)"
echo "Actual entry in /etc/hosts: $ACTUAL" | tee -a $OUTPUT_FILE

# Check
if [[ "$ACTUAL" == "$EXPECTED" ]]; then
  echo "PASSED" | tee -a $OUTPUT_FILE
else
  echo "ERROR: Route53 IP does not match host IP" | tee -a $OUTPUT_FILE
fi
