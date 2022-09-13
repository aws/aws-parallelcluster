#!/bin/bash

# Private Repository Access
# I manually created a TrainiumPreviewRepository secret and TrainiumPreviewPolicy on 447714826191 account to permit access to Secret below
# {
#    "Version": "2012-10-17",
#    "Statement": [
#        {
#            "Effect": "Allow",
#            "Action": [
#                "secretsmanager:GetResourcePolicy",
#                "secretsmanager:GetSecretValue",
#                "secretsmanager:DescribeSecret",
#                "secretsmanager:ListSecretVersionIds"
#            ],
#            "Resource": [
#                "arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository-<RANDOM-STRING>"
#            ]
#        },
#        {
#            "Effect": "Allow",
#            "Action": "secretsmanager:ListSecrets",
#            "Resource": "*"
#        }
#    ]
#}
REPO_USER=$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository --region us-east-1 --query 'SecretString' --output text | jq -r '.repository_user')
REPO_SECRET=$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository --region us-east-1 --query 'SecretString' --output text | jq -r '.repository_password')
REPO_SUFFIX=$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository --region us-east-1 --query 'SecretString' --output text | jq -r '.repository_suffix')

TEMPORARY_ARTIFACTS_BUCKET_PATH=s3://aws-parallelcluster-beta/neuron/


_ubuntu_installation() {
  # Configure Linux for Neuron repository updates
  sudo tee /etc/apt/sources.list.d/neuron.list > /dev/null <<EOF
deb https://${REPO_USER}:${REPO_SECRET}@apt.${REPO_SUFFIX} focal main
EOF
  wget -qO - https://${REPO_USER}:${REPO_SECRET}@apt.${REPO_SUFFIX}/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB | sudo apt-key add -

  # Install packages from S3 --> FIXME they should be installed from configured repository
  sudo dpkg -i aws-neuronx-devtools-2.5.6.0.deb
  sudo dpkg -i aws-neuronx-tools-2.5.6.0.deb
  sudo dpkg -i aws-neuronx-collectives-2.9.47.0-d96ffa967.deb
  sudo dpkg -i aws-neuronx-runtime-lib-2.9.39.0-21003aa11.deb

  # Install Python venv and activate Python virtual environment to install Neuron pip packages.
  local OS_VERSION="$(grep "^VERSION_ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"
  case ${OS_VERSION} in
      20.04)
        sudo apt-get install -y python3.8-venv g++
        python3 -m venv /home/ubuntu/aws_neuron_venv_pytorch
        ;;
      18.04)
        sudo apt-get install -y python3.7-venv g++
        python3.7 -m venv /home/ubuntu/aws_neuron_venv_pytorch
        ;;
      *)
        echo "Unrecognized VERSION_ID. Found /etc/os-release version content: ${OS_VERSION}"
        exit 1
        ;;
    esac
}

_rhel_installation() {
  # Install dkms driver. This is not required, installation is performed at AMI creation time
  sudo tee /etc/yum.repos.d/neuron.repo > /dev/null <<EOF
[neuron]
name=Neuron YUM Repository
baseurl=https://${REPO_USER}:${REPO_SECRET}@yum.${REPO_SUFFIX}
enabled=1
EOF
  sudo rpm --import https://${REPO_USER}:${REPO_SECRET}@yum.${REPO_SUFFIX}/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB

  # Install packages from S3 --> FIXME they should be installed from configured repository
  sudo rpm -i aws-neuronx-devtools-2.5.6.0.rpm
  sudo rpm -i aws-neuronx-tools-2.5.6.0.rpm
  sudo rpm -i aws-neuronx-collectives-2.9.47.0-d96ffa967.rpm
  sudo rpm -i aws-neuronx-runtime-lib-2.9.39.0-21003aa11.rpm

  python3 -m venv /home/ec2-user/aws_neuron_venv_pytorch
}


_dkms_ubuntu_installation() {
  # Install dkms driver. This is not required, installation is performed at AMI creation time
  sudo tee /etc/apt/sources.list.d/neuron.list > /dev/null <<EOF
deb https://apt.repos.neuron.amazonaws.com focal main
EOF
  wget -qO - https://apt.repos.neuron.amazonaws.com/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB | sudo apt-key add -

  sudo apt update
  sudo apt-get install aws-neuronx-dkms -y
}


_dkms_rhel_installation() {
  # Install dkms driver. This is not required, installation is performed at AMI creation time
  sudo tee /etc/yum.repos.d/neuron.repo > /dev/null <<EOF
[neuron]
name=Neuron YUM Repository
baseurl=https://yum.repos.neuron.amazonaws.com
enabled=1
EOF
  sudo rpm --import https://yum.repos.neuron.amazonaws.com/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB

  sudo yum install aws-neuronx-dkms -y
}


function main() {
  # Download packages from S3 --> FIXME they should be installed from configured repository
  aws s3 cp ${TEMPORARY_ARTIFACTS_BUCKET_PATH} . --recursive

  local OS="$(grep "^ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"
  case ${OS} in
    ubuntu)
      _dkms_ubuntu_installation  # not needed, installed at AMI creation time
      _ubuntu_installation
      USER=ubuntu
      ;;
    amzn)
      _dkms_rhel_installation  # not needed, installed at AMI creation time
      _rhel_installation
      USER=ec2-user
      ;;
    *)
      echo "Unsupported system. Found /etc/os-release ID content: ${OS}"
      exit 1
      ;;
  esac

  # Install Python venv and activate Python virtual environment to install Neuron pip packages.
  source /home/$USER/aws_neuron_venv_pytorch/bin/activate
  pip3 install -U pip
  pip3 install pytest

  # Install packages from beta repo --> FIXME they should be installed from official PyPI
  python3 -m pip config set global.extra-index-url "https://${REPO_USER}:${REPO_SECRET}@pip.${REPO_SUFFIX}"
  pip3 install torch-neuronx==1.11.*
  pip3 install neuronx-cc==2.*
}

main "${@}"
