#!/bin/bash

# This script creates a dummy systemd service that sleeps for a given time, and
# makes it a dependency for the slurmd service. This way it's possible to simulate
# a longer rebooting time of the node via scontrol reboot.

# TODO: consider disabling the network during the sleep in order to simulate the
# non-responsiveness to the EC2 status checks of the rebooted node.
#
# It doesn't seem to be possible to add a `ifconfig eth0 down` and `ifconfig eth0 up`
# in the following systemd service: the first command completely kills the instance
# and the second command doesn't seem to reactivate the network interface.

sudo mkdir /etc/systemd/system/slurmd.service.d

cat <<DELAY_SERVICE | sudo tee /etc/systemd/system/slurmd_delay.service
[Unit]
Description=Dummy Slurmd delay
Before=slurmd.service
Wants=network-online.target

[Service]
Type=simple
TimeoutSec=180s
ExecStartPre=sleep 120
ExecStart=sleep 1

[Install]
WantedBy=multi-user.target
DELAY_SERVICE

cat <<SLURMD_DROP_IN | sudo tee /etc/systemd/system/slurmd.service.d/add_delay.conf
[Unit]
After=slurmd_delay.service
Requires=slurmd_delay.service
SLURMD_DROP_IN

sudo systemctl daemon-reload
