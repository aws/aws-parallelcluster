#!/bin/bash

# Reset state of the daemons after running add_sleep_to_slurmd_service_compute.sh

sudo rm /etc/systemd/system/slurmd_delay.service
sudo rm /etc/systemd/system/slurmd.service.d/add_delay.conf
sudo systemctl daemon-reload
