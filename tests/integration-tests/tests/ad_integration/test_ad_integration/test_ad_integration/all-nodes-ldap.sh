#!/bin/bash

set -ex

# install prerecquisites
yum install -y sssd sssd-tools sssd-ldap curl python-sss

# Write SSSD config file
SSSD_CONFIG_PATH=/etc/sssd/sssd.conf
LDAP_URI="${1:?'LDAP URI must be first arg'}" # TODO: use ldaps
LDAP_SEARCH_BASE="${2:?'LDAP search base must be second arg'}"
LDAP_DEFAULT_BIND_DN="${3:?'LDAP default bind DN must be third arg'}"  # TODO: parametrize username
LDAP_CA_CERT='/etc/openldap/certs/privatekey.pem'
LDAP_REQUIRE_CERT='never' # TODO: use 'require'
LDAP_DISABLE_TLS='true'  # TODO:  use SSL
LDAP_UNOBFUSCATED_PASSWORD="${4:?'Unobfuscated password must be fourth arg'}"
LDAP_OBFUSCATED_PASSWORD=$(python -c "import pysss;print(pysss.password().encrypt('${LDAP_UNOBFUSCATED_PASSWORD}', pysss.password().AES_256))")
cat << EOF > $SSSD_CONFIG_PATH
[domain/default]
debug_level = 0x1f0
id_provider = ldap
cache_credentials = True
ldap_schema = AD
ldap_uri = $LDAP_URI
ldap_search_base = $LDAP_SEARCH_BASE
ldap_default_bind_dn = $LDAP_DEFAULT_BIND_DN
ldap_default_authtok_type = obfuscated_password
ldap_default_authtok = $LDAP_OBFUSCATED_PASSWORD
ldap_tls_cacert = $LDAP_CA_CERT
ldap_tls_reqcert = $LDAP_REQUIRE_CERT
ldap_id_mapping = True
ldap_referrals = False
enumerate = True
fallback_homedir = /home/%u
default_shell = /bin/bash
ldap_auth_disable_tls_never_use_in_production = $LDAP_DISABLE_TLS
use_fully_qualified_names = False

[domain/local]
id_provider = local
enumerate = True


[sssd]
config_file_version = 2
services = nss, pam, ssh
domains = default, local
full_name_format = %1\$s

[nss]
filter_users = nobody,root
filter_groups = nobody,root

[pam]
offline_credentials_expiration = 7
EOF
chmod 600 $SSSD_CONFIG_PATH

# Tell NSS, PAM to use SSSD for system authentication and identity information
authconfig --enablemkhomedir --enablesssdauth --enablesssd --updateall

# Modify SSHD config to enable password login
sed -ri 's/\s*PasswordAuthentication\s+no$/PasswordAuthentication yes/g' /etc/ssh/sshd_config

# Restart modified services
for SERVICE in sssd sshd; do
    systemctl restart $SERVICE
done
