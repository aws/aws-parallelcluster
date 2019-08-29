#!/usr/bin/env bash
set -e

rpm --import https://yum.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS-2019.PUB
sudo yum-config-manager --add-repo https://yum.repos.intel.com/clck/2019/setup/intel-clck-2019.repo
sudo yum-config-manager --add-repo https://yum.repos.intel.com/clck-ext/2019/setup/intel-clck-ext-2019.repo
sudo yum -y install intel-clck-2019.3.5-025