#!/bin/bash
set -e

# Disable health check in sqswatcher config
sudo bash -c "sed -i '/disable_health_check.*/d' /etc/sqswatcher.cfg"
sudo bash -c "sed -i '\$adisable_health_check = True' /etc/sqswatcher.cfg"

# Restart sqswatcher
sudo bash -c "/usr/local/pyenv/versions/cookbook_virtualenv/bin/supervisorctl restart sqswatcher"
