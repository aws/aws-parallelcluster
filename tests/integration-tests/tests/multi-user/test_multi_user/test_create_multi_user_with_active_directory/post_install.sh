#!/bin/bash

sed -i 's/PasswordAuthentication no//g' /etc/ssh/sshd_config
echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
sleep 1
service sshd restart
