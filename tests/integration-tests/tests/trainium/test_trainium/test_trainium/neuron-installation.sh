#!/bin/bash
set -ex

function info() {
  echo "$(date "+%Y-%m-%dT%H:%M:%S.%3N") [INFO] $1"
}

_ubuntu_installation() {
  info "Create repo"
  . /etc/os-release
  tee /etc/apt/sources.list.d/neuron.list > /dev/null <<EOF
deb https://apt.repos.neuron.amazonaws.com focal main
EOF
  wget -qO - https://apt.repos.neuron.amazonaws.com/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB | apt-key add -
  info "Update packages"
  apt update -y
  info "Install Neuron Driver"
  apt-get install aws-neuronx-dkms=2.* -y
  info "Install Neuron collectives"
  apt-get install aws-neuronx-collectives=2.* -y
  info "Install Neuron Runtime"
  apt-get install aws-neuronx-runtime-lib=2.* -y
  info "Install Neuron Tools"
  apt-get install aws-neuronx-tools=2.* -y
  info "Add neuron in PATH"
  export PATH=/opt/aws/neuron/bin:$PATH
  info "Install Python venv"
  apt-get install -y python3-venv g++
  info "Create Python venv"
  python3 -m venv /home/ubuntu/aws_neuron_venv_pytorch
}


_rhel_installation() {
  info "Create repo"

  tee /etc/yum.repos.d/neuron.repo > /dev/null <<EOF
[neuron]
name=Neuron YUM Repository
baseurl=https://yum.repos.neuron.amazonaws.com
enabled=1
metadata_expire=0
EOF
  rpm --import https://yum.repos.neuron.amazonaws.com/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB
  info "Install Neuron Driver"
  yum install aws-neuronx-dkms-2.* -y
  info "Install Neuron collectives"
  yum install aws-neuronx-collectives-2.* -y
  info "Install Neuron Runtime"
  yum install aws-neuronx-runtime-lib-2.* -y
  info " Install Neuron Tools"
  yum install aws-neuronx-tools-2.* -y
  info "Add neuron in PATH"
  export PATH=/opt/aws/neuron/bin:$PATH
  info "Create Python venv"
  python3 -m venv /home/ec2-user/aws_neuron_venv_pytorch

}


function main() {

  local OS="$(grep "^ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"
  case ${OS} in
    ubuntu)
      _ubuntu_installation
      USER=ubuntu
      ;;
    amzn)
      _rhel_installation
      USER=ec2-user
      ;;
    *)
      info "Unsupported system. Found /etc/os-release ID content: ${OS}"
      exit 1
      ;;
  esac
  info "Activate Pyenv"
  # Install Python venv and activate Python virtual environment to install Neuron pip packages.
  source /home/$USER/aws_neuron_venv_pytorch/bin/activate
  pip3 install -U pip
  pip3 install pytest
  info "Set Neuron Index URL"
  python3 -m pip config set global.extra-index-url "https://pip.repos.neuron.amazonaws.com"
  PIPS='torch-neuronx neuronx-cc transformers'
  info "Install ${PIPS}"
  pip3 install ${PIPS}
}

main "${@}"
