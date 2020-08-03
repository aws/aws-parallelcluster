#!/bin/bash

set -e

_error_exit() {
   echo "$1"
   exit 1
}

_info() {
  echo "INFO: $1"
}

_help() {
    local -- _cmd=$(basename "$0")

    cat <<EOF

  Usage: ${_cmd} [OPTION]...

  Copy the AWS ParallelCluster Templates to an S3 bucket.

  --bucket <bucket>             Bucket where upload the template
  --srcdir <src-dir>            Root folder of the pcluster project
  --profile <aws-profile>       AWS profile name to use for the upload
                                (optional, default is AWS_PROFILE env variable or "default")
  --region <aws-region>         Region to use for AWSCli commands (optional, default is "us-east-1")
  -h, --help                    Print this help message
EOF
}

main() {
    # parse input options
    while [ $# -gt 0 ] ; do
        case "$1" in
            --bucket)           _bucket="$2"; shift;;
            --bucket=*)         _bucket="${1#*=}";;
            --srcdir)           _srcdir="$2"; shift;;
            --srcdir=*)         _srcdir="${1#*=}";;
            --profile)          _profile="$2"; shift;;
            --profile=*)        _profile="${1#*=}";;
            --region)           _region="$2"; shift;;
            --region=*)         _region="${1#*=}";;
            -h|--help|help)     _help; exit 0;;
            *)                  _help; echo "[error] Unrecognized option '$1'"; exit 1;;
        esac
        shift
    done

    # verify required parameters
    if [ -z "${_bucket}" ]; then
        _error_exit "--bucket parameter not specified"
        _help;
    fi
    if [ -z "${_srcdir}" ]; then
        _error_exit "--srcdir parameter not specified"
        _help;
    fi

    # initialize optional parameters
    if [ -z "${AWS_PROFILE}" ] && [ -z "${_profile}" ]; then
        _info "--profile parameter not specified, using 'default'"
    elif [ -n "${_profile}" ]; then
        _profile="--profile ${_profile}"
    fi
    if [ -z "${_region}" ]; then
        _info "--region parameter not specified, using 'us-east-1'"
        _region="us-east-1"
    fi

    # check bucket or create it
    aws ${_profile} s3api head-bucket --bucket "${_bucket}" --region "${_region}"
    if [ $? -ne 0 ]; then
        _info "Bucket ${_bucket} do not exist, trying to create it"
        aws ${_profile} s3api create-bucket --bucket "${_bucket}" --region "${_region}"
        if [ $? -ne 0 ]; then
            _error_exit "Unable to create bucket ${_bucket}"
        fi
    fi

    _version=$(grep "VERSION = \"" "${_srcdir}/cli/setup.py" |awk '{print $3}'| tr -d \")
    if [ -z "${_version}" ]; then
        _error_exit "Unable to detect pcluster version, are you in the right directory?"
    fi
    _info "Detected version ${_version}"

    _bucket_region=$(aws ${_profile} s3api get-bucket-location --bucket ${_bucket} --output text  --region "${_region}")
    if [[ ${_bucket_region} == "None" ]]; then
        _bucket_region="us-east-1"
    fi

    # Change links to substacks
    _templates_folder="templates/${_version}"
    _s3_domain="amazonaws.com"
    if [ "${_bucket_region}" != "${_bucket_region#cn-*}" ]; then
      _s3_domain="${_s3_domain}.cn"
    fi
    _s3_url="${_bucket}.s3.${_bucket_region}.${_s3_domain}"
    _s3_folder_url="${_s3_url}/${_templates_folder}"
    _temp_dir=$(mktemp -d)
    cp ${_srcdir}/cloudformation/aws-parallelcluster.cfn.json ${_temp_dir}/
    sed -i "s#.*aws-parallelcluster.*/templates/ebs-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/ebs-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/raid-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/raid-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/efs-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/efs-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/fsx-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/fsx-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/batch-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/batch-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/cw-logs-substack-\${version}.cfn.json.*#\"https://${_s3_folder_url}/cw-logs-substack.cfn.json\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/compute-fleet-substack-\${version}.cfn.yaml.*#\"https://${_s3_folder_url}/compute-fleet-substack.cfn.yaml\",#" ${_temp_dir}/aws-parallelcluster.cfn.json
    sed -i "s#.*aws-parallelcluster.*/templates/master-server-substack-\${version}.cfn.yaml.*#\"https://${_s3_folder_url}/master-server-substack.cfn.yaml\",#" ${_temp_dir}/aws-parallelcluster.cfn.json

    # upload templates
    aws ${_profile} --region "${_region}" s3 cp --acl public-read ${_temp_dir}/aws-parallelcluster.cfn.json s3://${_bucket}/${_templates_folder}/ || _error_exit 'Failed to push cloudformation template to S3'
    aws ${_profile} --region "${_region}" s3 cp --acl public-read --recursive --exclude "*" --include "*substack.cfn.json" --include "*substack.cfn.yaml" ${_srcdir}/cloudformation/ s3://${_bucket}/${_templates_folder}/ || _error_exit 'Failed to push substack cfn templates to S3'

    echo ""
    echo "Done. Add the following variables to the pcluster config file, under the [cluster ...] section"
    echo "template_url = https://${_s3_folder_url}/aws-parallelcluster.cfn.json"
    echo "hit_template_url = s3://${_bucket}/${_templates_folder}/compute-fleet-hit-substack.cfn.yaml"
    echo "cw_dashboard_template_url = s3://${_bucket}/${_templates_folder}/cw-dashboard-substack.cfn.yaml"
}

main "$@"

# vim:syntax=sh
