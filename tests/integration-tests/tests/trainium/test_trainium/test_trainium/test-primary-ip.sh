#!/bin/bash
# Test the alignment of the Route 53 IP and the the host IP
grep Ubuntu /etc/issue &>/dev/null && DNS_SERVER=$(resolvectl dns | awk '{print $4}' | sort -r | head -1)
IP="$(host $HOSTNAME $DNS_SERVER | tail -1 | awk '{print $4}')"
DOMAIN=$(jq .cluster.dns_domain /etc/chef/dna.json | tr -d \")
expected="$IP $HOSTNAME.${DOMAIN::-1} $HOSTNAME"
echo expected: $expected | tee output-primary-ip.txt

actual="$(grep "$HOSTNAME" /etc/hosts)"
echo actual: $actual | tee -a output-primary-ip.txt

if [[ $expected == $actual ]]
then
  echo PASSED | tee -a output-primary-ip.txt
fi
echo Error: Route53 IP does not match host IP | tee -a output-primary-ip.txt
