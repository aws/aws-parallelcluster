#!/bin/bash

# CfnCluster setup script. This is called by CloudFormation and
# ensures the instance is capable of running the bootstap actions.

VERSION=$1

if [ "${VERSION}x" == "x" ]; then
  echo "Version not set. Exiting."
  exit 0
fi

if [ -f /opt/cfncluster/.cfncluster-setup-${VERSION} ]; then
  runtime=`cat /opt/cfncluster/.cfncluster-setup-${VERSION}`
  echo "cfncluster previously run at $runtime."
  echo "Exiting."
  exit 0
else
  rm /opt/cfncluster/.cfncluster-setup-*
  distro="$(cat /etc/issue | awk ''NR==1'{ print $1 }')"
  case "$distro" in
    Ubuntu)
      apt-get update
      apt-get install -y build-essential curl
    ;;
    CentOS|Amazon|RedHat)
      yum groupinstall -y "Development Tools"
      yum install -y curl
    ;;
    *)
      echo "Your distro is not supported." 1>&2
      exit 1
    ;;
  esac

  mkdir -p /opt/cfncluster
  easy_install -U https://s3.amazonaws.com/cloudformation-examples/aws-cfn-bootstrap-latest.tar.gz
  curl -LO https://www.chef.io/chef/install.sh && sudo bash ./install.sh -d /opt/cfncluster -v 12.4.1 && rm install.sh
  /opt/chef/embedded/bin/gem install berkshelf --no-ri --no-rdoc 2>&1 >/tmp/berkshelf.log
  echo `date` > /opt/cfncluster/.cfncluster-setup-${VERSION}
fi