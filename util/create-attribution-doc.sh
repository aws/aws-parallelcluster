#!/bin/bash

set -ex
# Install the python version if it doesnt exist
if test ! -d ${PYENV_ROOT}/versions/3.9.10;
then 
  env PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install 3.9.10
fi

pyenv virtualenv 3.9.10 attribution-doc-env
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

# Create a list of aws cdk Sub-packages we want to ignore 
aws_cdk_ignore_subpackages=$(pip list | grep cdk | awk '{print $1}') 
aws_cdk_version=$(pip list | grep cdk | awk '{print $2}'| head -n 1)
# Create a pip License document
pip-licenses -i $aws_cdk_ignore_subpackages aws-parallelcluster pip-licenses --format=plain-vertical --with-license-file --with-urls --no-license-path --with-authors --output-file=$final_license_file


#Getting python version
cpy_version=$(python -V |  grep -Eo '([0-9]+)(\.?[0-9]+)' | head -1) 


# Appending aws-cdk and Python License to the THIRD-PARTY-LICENSES file
# Adding a header for aws-cdk version and License URL to THIRD-PARTY-LICENSES file
echo "aws-cdk $aws_cdk_version; https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE" >> $final_license_file
# Appending aws-cdk License to THIRD-PARTY-LICENSES file
curl https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE >> $final_license_file
# Adding a header for Python version and License URL to THIRD-PARTY-LICENSES file
echo -e "\nPython $cpy_version; https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE " >> $final_license_file
# Appending Python License to THIRD-PARTY-LICENSES file
curl https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE >> $final_license_file


deactivate
pyenv virtualenv-delete attribution-doc-env
