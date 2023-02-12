#!/bin/bash
# Test the alignment of the Route 53 IP and the the host IP
TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
macs=`curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/network/interfaces/macs`
for mac in ${macs}
do
  device_number=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/device-number"`
  network_card=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/network-card"`
  if [[ ${device_number} == '0' && ${network_card} == '0' ]]
  then
    IP_HOSTS="$(grep "$HOSTNAME" /etc/hosts | awk '{print $1}')"
    mac_ip=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/local-ipv4s"`
    for word in $IP_HOSTS
    do
      if [[ ${word} == ${mac_ip} ]]
      then
        exit 0
      fi
    done
  fi
  echo Error: Route53 IP does not match host IP
  exit 1
done
