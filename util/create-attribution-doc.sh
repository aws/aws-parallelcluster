#!/bin/bash

set -ex

pyenv virtualenv attribution-doc-env
# switch to a specific virtual env
source ${PYENV_ROOT}/versions/attribution-doc-env/bin/activate



# Update Pip
pip3 install --upgrade pip

# Installing PyInstaller
pip3 install pyinstaller
# Install pip-licenses
pip3 install pip-licenses

# install pcluster via source
cd ..
pip3 install -e cli
#pip3 install -r requirements.txt

final_license_file=THIRD-PARTY-LICENSES.txt
python_license_file=python_license.txt
aws_cdk_license_file=aws-cdk-license.txt
# Create a list of aws cdk Sub-packages we want to ignore 
aws_cdk_ignore_subpackages=$(pip list | grep cdk | awk '{print $1}') 
# Create a pip License document
pip-licenses -i $aws_cdk_ignore_subpackages aws-parallelcluster pip-licenses --format=plain-vertical --with-license-file --with-urls --no-license-path --with-authors --output-file=$final_license_file


#Getting python version
cpy_version=$(python -V |  grep -Eo '([0-9]+)(\.?[0-9]+)' | head -1) 


# Add other License in the final file
# Get Aws-cdk License file
echo "aws-cdk; https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE" >> $final_license_file
curl https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE >> $final_license_file
# Download Python License file
echo -e "\nPython $cpy_version " >> $final_license_file
curl $python_license_file https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE >> $final_license_file


deactivate
pyenv virtualenv-delete attribution-doc-env
