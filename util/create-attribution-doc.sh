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

packaging_version=$(pip list | grep packaging | awk '{print $2}')
exception_group_version=$(pip list | grep exceptiongroup | awk '{print $2}')
idna_version=$(pip list | grep idna | awk '{print $2}')
typing_extentions_version=$(pip list | grep typing_extensions | awk '{print $2}')
# Create a pip License document
pip-licenses -i $aws_cdk_ignore_subpackages aws-parallelcluster pip-licenses packaging pyinstaller-hooks-contrib pyinstaller exceptiongroup idna typing_extensions certifi --format=plain-vertical --with-license-file --with-urls --no-license-path --with-authors --output-file=$final_license_file


#Getting python version
cpy_version=$(python -V |  grep -Eo '([0-9]+)(\.?[0-9]+)' | head -1) 


# Appending License to the THIRD-PARTY-LICENSES file

# certifi 
#Adding a header for certifi version and License URL
echo -e "\ncertifi \n2022.12.07 \nMozilla Public License 2.0 (MPL 2.0) \nhttps://github.com/certifi/python-certifi/tree/2022.12.07" >> $final_license_file
# Appending certifi License files 
curl https://raw.githubusercontent.com/certifi/python-certifi/2022.12.07/LICENSE >> $final_license_file

# exception_group 
#Adding a header for exception_group version and License URL
echo -e "\n\n\nexceptiongroup \n$exception_group_version \nMIT License \nhttps://github.com/agronholm/exceptiongroup" >> $final_license_file
# Appending exception_group License files 
curl https://raw.githubusercontent.com/agronholm/exceptiongroup/main/LICENSE >> $final_license_file

# idna 
#Adding a header for idna version and License URL
echo -e "\n\n\nidna \n$idna_version \nBSD License \nhttps://github.com/kjd/idna" >> $final_license_file
# Appending idna License files 
curl https://raw.githubusercontent.com/kjd/idna/master/LICENSE.md >> $final_license_file

# typing_extentions
#Adding a header for typing_extentions version and License URL
echo -e "\n\n\ntyping_extensions \n$typing_extentions_version \nPython Software Foundation License \nhttps://github.com/python/typing_extensions"  >> $final_license_file
# Appending typing_extentions License files 
curl  https://raw.githubusercontent.com/python/typing_extensions/main/LICENSE >> $final_license_file

# Packaging
# Adding a header for Packaging version and License URL
echo -e "\n\n\npackaging \n$packaging_version\nApache Software License; BSD License\nhttps://github.com/pypa/packaging " >> $final_license_file
# Appending Packaging's 3 License files 
curl https://raw.githubusercontent.com/pypa/packaging/main/LICENSE >> $final_license_file
curl https://raw.githubusercontent.com/pypa/packaging/main/LICENSE.APACHE >> $final_license_file
curl https://raw.githubusercontent.com/pypa/packaging/main/LICENSE.BSD >> $final_license_file

# pyinstaller-hooks-contrib
# Adding a header for pyinstaller-hooks-contrib version and License URL 
echo -e "\n\n\npyinstaller-hooks-contrib \n2022.15\nApache License 2.0; GNU General Public License \nhttps://github.com/pyinstaller/pyinstaller-hooks-contrib/archive/refs/tags/2022.15.tar.gz." >> $final_license_file
# Appending pyinstaller-hooks-contrib 3 License files 
wget -c https://github.com/pyinstaller/pyinstaller-hooks-contrib/archive/refs/tags/2022.15.tar.gz -O - | tar -xz

cat pyinstaller-hooks-contrib-2022.15/LICENSE >> $final_license_file
cat pyinstaller-hooks-contrib-2022.15/LICENSE.APL.txt >> $final_license_file
cat pyinstaller-hooks-contrib-2022.15/LICENSE.GPL.txt >> $final_license_file

rm -rf pyinstaller-hooks-contrib-2022.15

# pyinstaller
# Adding a header for pyinstaller version and License URL 
echo -e "\n\n\npyinstaller \n5.7.0\nGNU General Public License v2 (GPLv2) \nhttps://github.com/pyinstaller/pyinstaller/archive/refs/tags/v5.7.0.tar.gz." >> $final_license_file
wget -c https://github.com/pyinstaller/pyinstaller/archive/refs/tags/v5.7.0.tar.gz -O - | tar -xz
# Appending pyinstaller License file
cat pyinstaller-5.7.0/COPYING.txt >> $final_license_file
rm -rf pyinstaller-5.7.0

# aws-cdk 
# Adding a header for aws-cdk version and License URL 
echo -e "\n\n\naws-cdk \n$aws_cdk_version\nApache License \nhttps://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE" >> $final_license_file
# Appending aws-cdk License 
curl https://raw.githubusercontent.com/aws/aws-cdk/main/LICENSE >> $final_license_file

# Python
# Adding a header for Python version and License URL 
echo -e "\nPython \n$cpy_version \nPSF License Version 2; Zero-Clause BSD license \nhttps://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE " >> $final_license_file
# Appending Python License
curl https://raw.githubusercontent.com/python/cpython/$cpy_version/LICENSE >> $final_license_file




deactivate
pyenv virtualenv-delete attribution-doc-env
