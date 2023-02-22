#!/bin/bash

set -e -o xtrace


append_package_details_to_final_license_file(){
  # Function to Append Package Details to the THIRD-PARTY-LICENSES file
  #Arguments ->  1- Package Name, 2- Package Version, 3- License Type , 4- URL for package, 5,6,7- URL for License
  # Adding a header to final License file with Package Name, Package Version, License Type , URL for package
  echo "\n\n\n$1 \n$2 \n$3 \n$4" >> $final_license_file
  # Appending License
  curl $5 >> $final_license_file
  # Adding Dual Licenses if they exist 
  if [ $# -gt 5 ]
    then
      curl $6 >> $final_license_file
      curl $7 >> $final_license_file
  fi

}

function create_attribution_doc() {
  ATTR_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

  # Install the python version if it doesnt exist
  if test ! -d ${PYENV_ROOT}/versions/${PYTHON_VERSION};
  then 
    env PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install ${PYTHON_VERSION}
  fi
  
  pyenv virtualenv ${PYTHON_VERSION} attribution-doc-env
  # switch to a specific virtual env
  source ${PYENV_ROOT}/versions/attribution-doc-env/bin/activate
  
  # Update Pip
  pip3 install --upgrade pip
  
  # Installing PyInstaller
  pip3 install pyinstaller
  # Install pip-licenses
  pip3 install pip-licenses
  
  # install pcluster via source
  
  pip3 install -e $(dirname $ATTR_SCRIPT_DIR )/cli
  #pip3 install -r requirements.txt
  
  final_license_file=$(dirname $ATTR_SCRIPT_DIR )/THIRD-PARTY-LICENSES.txt
  
  # Create a list of aws cdk Sub-packages we want to ignore 
  aws_cdk_ignore_subpackages=$(pip list | grep cdk | awk '{print $1}') 
  aws_cdk_version=$(pip list | grep cdk | awk '{print $2}'| head -n 1)
  
  packaging_version=$(pip list | grep packaging | awk '{print $2}')
  exception_group_version=$(pip list | grep exceptiongroup | awk '{print $2}')
  idna_version=$(pip list | grep idna | awk '{print $2}')
  typing_extentions_version=$(pip list | grep typing_extensions | awk '{print $2}')
  # Create a pip License document
  pip-licenses -i $aws_cdk_ignore_subpackages aws-parallelcluster pip-licenses packaging pyinstaller-hooks-contrib pyinstaller exceptiongroup idna typing_extensions certifi --format=plain-vertical --with-license-file --with-urls --no-license-path --with-authors --output-file=$final_license_file
  
  
  #Getting python version
  cpy_version=$(python -V |  grep -Eo '([0-9]+)(\.?[0-9]+)' | head -1) 

  
  # certifi 
  append_package_details_to_final_license_file "certifi" "2022.12.07" "Mozilla Public License 2.0 (MPL 2.0)" "https://github.com/certifi/python-certifi/tree/2022.12.07" "https://raw.githubusercontent.com/certifi/python-certifi/2022.12.07/LICENSE"
  
  # exception_group 
  append_package_details_to_final_license_file "exceptiongroup" $exception_group_version "MIT License" "https://github.com/agronholm/exceptiongroup" "https://raw.githubusercontent.com/agronholm/exceptiongroup/main/LICENSE"
  
  # idna 
  append_package_details_to_final_license_file "idna" $idna_version "BSD License" "https://github.com/kjd/idna" "https://raw.githubusercontent.com/kjd/idna/master/LICENSE.md"
  
  # typing_extentions
  append_package_details_to_final_license_file "typing_extensions" $typing_extentions_version "Python Software Foundation License" "https://github.com/python/typing_extensions" "https://raw.githubusercontent.com/python/typing_extensions/main/LICENSE"
  
  # Packaging
  append_package_details_to_final_license_file "packaging" $packaging_version "Apache Software License; BSD License" "https://github.com/pypa/packaging" "https://raw.githubusercontent.com/pypa/packaging/main/LICENSE" "https://raw.githubusercontent.com/pypa/packaging/main/LICENSE.APACHE" "https://raw.githubusercontent.com/pypa/packaging/main/LICENSE.BSD"
  
  # pyinstaller-hooks-contrib
  append_package_details_to_final_license_file "pyinstaller-hooks-contrib" "2022.15" "Apache License 2.0; GNU General Public License" "https://github.com/pyinstaller/pyinstaller-hooks-contrib/archive/refs/tags/2022.15.tar.gz." "https://raw.githubusercontent.com/pyinstaller/pyinstaller-hooks-contrib/2022.15/LICENSE" "https://raw.githubusercontent.com/pyinstaller/pyinstaller-hooks-contrib/2022.15/LICENSE.APL.txt" "https://raw.githubusercontent.com/pyinstaller/pyinstaller-hooks-contrib/2022.15/LICENSE.GPL.txt"
  
  # pyinstaller
  append_package_details_to_final_license_file "pyinstaller" "5.7.0" "GNU General Public License v2 (GPLv2)" "https://github.com/pyinstaller/pyinstaller/archive/refs/tags/v5.7.0.tar.gz." "https://raw.githubusercontent.com/pyinstaller/pyinstaller/v5.7.0/COPYING.txt"
  
  # aws-cdk 
  append_package_details_to_final_license_file "aws-cdk" $aws_cdk_version "Apache License" "https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE" "https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE"
  
  # Python
  append_package_details_to_final_license_file "Python" $cpy_version "PSF License Version 2; Zero-Clause BSD license" "https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE" "https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE"
  
  
  deactivate
  pyenv virtualenv-delete -f attribution-doc-env

}


_error_exit() {
   echo "$1"
   exit 1
}

_help() {
    local -- _cmd=$(basename "$0")

    cat <<EOF
  This script will create the THIRD_PARTY_LICENSE.txt file assuming you have already installed Pyenv
  Usage: ${_cmd} [OPTION]...


  --python-version <version>                                        Python version with which you want to create the attribution document.
  -h, --help                                                        Print this help message
  
  Examples:
  ${_cmd}
  $_cmd --python-version 3.9.10
EOF
}

function parse_options () {
  
   while [ $# -gt 0 ] ; do
          case "$1" in
              --python-version)                      PYTHON_VERSION="$2"; shift;;
              -h|--help|help)                       _help; exit 0;;
              *)                                    _help; _error_exit "[error] Unrecognized option '$1'";;
          esac
          shift
      done

}

function main() {
  parse_options "$@"
  create_attribution_doc
}

main "$@"
