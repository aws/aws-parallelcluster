#!/bin/bash -x

function error_exit
{
  # wait logs flush before signaling the failure
  sleep 10
  # trim the error message because there is a size limit of 4096 bytes for cfn-signal
  # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-limits.html
  cutoff=$(expr 4096 - $(stat --printf="%s" /tmp/wait_condition_handle.txt))
  reason=$(head --bytes=${!cutoff} /var/log/parallelcluster/bootstrap_error_msg 2>/dev/null) || reason="$1"
  cfn-signal --exit-code=1 --reason="${!reason}" "${!wait_condition_handle_presigned_url}" --region ${AWS::Region} --url ${CloudFormationUrl}
  exit 1
}
function vendor_cookbook
{
  mkdir /tmp/cookbooks
  cd /tmp/cookbooks
  tar -xzf /etc/chef/aws-parallelcluster-cookbook.tgz
  HOME_BAK="${!HOME}"
  export HOME="/tmp"
  for d in `ls /tmp/cookbooks`; do
    cd /tmp/cookbooks/$d
    LANG=en_US.UTF-8 /opt/cinc/embedded/bin/berks vendor /etc/chef/cookbooks --delete || error_exit 'Vendoring cookbook failed.'
  done;
  export HOME="${!HOME_BAK}"
}

custom_cookbook_url="${CustomCookbookUrl}"

if [ "${custom_cookbook_url}" != "NONE" ]; then
  curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${custom_cookbook_url}
  vendor_cookbook
fi
