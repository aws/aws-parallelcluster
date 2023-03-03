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
  sudo tee /etc/apt/sources.list.d/neuron-private.list > /dev/null <<EOF
deb https://${REPO_USER}:${REPO_SECRET}@apt.${REPO_SUFFIX} focal main
EOF

  sudo apt-get update -y
  sudo apt-get install -y aws-neuronx-runtime-lib=2.* aws-neuronx-collectives=2.*

  wget -qO - https://${REPO_USER}:${REPO_SECRET}@apt.${REPO_SUFFIX}/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB | sudo apt-key add -

  # Install packages from S3 --> FIXME they should be installed from configured repository
  DEBS=$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository --region us-east-1 --query 'SecretString' --output text | jq -r '.debs')
  for DEB in $DEBS
  do
    sudo dpkg -i $DEB
  done

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
  sudo tee /etc/yum.repos.d/neuron-private.repo > /dev/null <<EOF
[neuron-private]
name=Neuron YUM Repository
baseurl=https://${REPO_USER}:${REPO_SECRET}@yum.${REPO_SUFFIX}
enabled=1
EOF
  sudo yum install -y aws-neuronx-runtime-lib-2.* aws-neuronx-collectives-2.*

  sudo rpm --import https://${REPO_USER}:${REPO_SECRET}@yum.${REPO_SUFFIX}/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB

  # Install packages from S3 --> FIXME they should be installed from configured repository
  RPMS=$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:us-east-1:447714826191:secret:TrainiumPreviewRepository --region us-east-1 --query 'SecretString' --output text | jq -r '.rpms')
  for RPM in $RPMS
  do
    sudo rpm -i $RPM
  done

  python3 -m venv /home/ec2-user/aws_neuron_venv_pytorch
}


_dkms_ubuntu_installation() {
  sudo tee /etc/apt/sources.list.d/neuron.list > /dev/null <<EOF
deb https://apt.repos.neuron.amazonaws.com focal main
EOF
  wget -qO - https://apt.repos.neuron.amazonaws.com/GPG-PUB-KEY-AMAZON-AWS-NEURON.PUB | sudo apt-key add -

  sudo apt update
  sudo apt-get install aws-neuronx-dkms -y
}


_dkms_rhel_installation() {
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
      _dkms_ubuntu_installation
      _ubuntu_installation
      USER=ubuntu
      ;;
    amzn)
      _dkms_rhel_installation
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

  python3 -m pip config set global.extra-index-url "https://pip.repos.neuron.amazonaws.com"
  PIPS='torch-neuronx==1.11.0.1.* neuronx-cc==2.* transformers'
  pip3 install ${PIPS}
}

main "${@}"
