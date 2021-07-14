#!/bin/bash
set -x

. /etc/os-release
release="${ID}${VERSION_ID:+.${VERSION_ID}}"

if [ `echo ${release} | grep '^centos\.7'` ]; then
  sudo yum repolist | grep epel

  if [ $? -ne 0 ]; then
      echo "epel not installed"
      exit 1
  fi
elif [ `echo "${release}" | grep '^centos\.8'` ]; then
  sudo dnf repolist | grep epel

  if [ $? -ne 0 ]; then
      echo "epel not installed"
      exit 1
  fi
fi