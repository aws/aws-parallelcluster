#!/bin/bash
# Test the alignment of the Route 53 IP and the the host IP
TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
echo TOKEN: $TOKEN | tee output-primary-ip.txt
macs=`curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/network/interfaces/macs`
echo macs: $macs | tee -a output-primary-ip.txt
for mac in $macs
do
  device_number=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/device-number"`
  network_card=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/network-card"`
  echo mac: $mac device_number: $device_number network_card: $network_card | tee -a output-primary-ip.txt
  if [[ $device_number == '0' && $network_card == '0' ]]
  then
    IP_HOSTS="$(grep "$HOSTNAME" /etc/hosts | awk '{print $1}')"
    echo IP_HOSTS: $IP_HOSTS | tee -a output-primary-ip.txt
    mac_ip=`curl -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/local-ipv4s"`
    echo mac_ip: $mac_ip | tee -a output-primary-ip.txt
    for word in $IP_HOSTS
    do
      if [[ $word == $mac_ip ]]
      then
        echo PASSED | tee -a output-primary-ip.txt
        exit 0
      fi
    done
  fi
done
echo Error: Route53 IP does not match host IP | tee -a output-primary-ip.txt
exit 1
