#!/bin/bash

mkdir -p $HOME/mock_health_checks
sudo tee $HOME/mock_health_checks/gpu_health_check.sh > /dev/null <<EOT
#!/bin/bash
exit 1
EOT
sudo chmod +x $HOME/mock_health_checks/gpu_health_check.sh

sudo sed -i '/managed_health_check_dir =/ s|\/opt\/slurm\/etc\/pcluster\/\.slurm_plugin\/scripts\/health_checks|'$HOME'\/mock_health_checks|' /opt/slurm/etc/pcluster/.slurm_plugin/scripts/conf/health_check_manager.conf
echo "Mocked failing GPU Health Check"
cat /opt/slurm/etc/pcluster/.slurm_plugin/scripts/conf/health_check_manager.conf
