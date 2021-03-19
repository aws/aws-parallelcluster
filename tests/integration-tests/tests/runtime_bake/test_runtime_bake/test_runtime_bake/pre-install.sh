#!/bin/bash
set -x

. /etc/os-release
release="${ID}${VERSION_ID:+.${VERSION_ID}}"

if [ `echo ${release} | grep '^centos\.7'` ]; then
  sudo yum remove -y epel-release

  sudo yum repolist | grep epel

  if [ $? -eq 0 ]; then
      echo "epel installed"
      exit 1
  fi
elif [ `echo "${release}" | grep '^centos\.8'` ]; then
  sudo dnf remove -y epel-release

  sudo dnf repolist | grep epel

  if [ $? -eq 0 ]; then
      echo "epel not removed"
      exit 1
  fi
fi