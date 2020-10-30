#!/usr/bin/env bash
# These installation instructions come from the following URL:
# https://software.intel.com/content/www/us/en/develop/documentation/cluster-checker-user-guide/top/installation.html#YUMINSTALL
# To see the latest available versions:
# $ repoquery --repofrompath=reponame,https://yum.repos.intel.com/clck/2019 --repoid=reponame -a
set -e

sudo rpm --import https://yum.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS-2019.PUB
sudo yum-config-manager --add-repo https://yum.repos.intel.com/clck/2019/setup/intel-clck-2019.repo
sudo yum-config-manager --add-repo https://yum.repos.intel.com/clck-ext/2019/setup/intel-clck-ext-2019.repo
sudo yum -y install intel-clck-2019.9-056