#!/bin/bash

sudo sed -i '/managed_health_check_dir =/ s|'$HOME'\/mock_health_checks|\/opt\/slurm\/etc\/pcluster\/\.slurm_plugin\/scripts\/health_checks|' /opt/slurm/etc/pcluster/.slurm_plugin/scripts/conf/health_check_manager.conf

echo "Health check configuration restored"
cat /opt/slurm/etc/pcluster/.slurm_plugin/scripts/conf/health_check_manager.conf
