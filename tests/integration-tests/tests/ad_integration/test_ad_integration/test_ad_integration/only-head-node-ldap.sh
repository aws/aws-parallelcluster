#!/bin/bash

set -ex

copy_local_user_files_to_nfs() {
    for identity_file in passwd group; do
        cp /etc/$identity_file /shared/
    done
}

link_local_user_files() {
    for identity_file in passwd group; do
        mv /etc/$identity_file{,.bak} && ln -s /shared/$identity_file /etc/$identity_file
    done
}

# Set cfn_node_type so in order know if script is running on head node or compute node
# shellcheck source=/dev/null
source  /etc/parallelcluster/cfnconfig
if [ "${cfn_node_type:?}" != "HeadNode" ]; then
    link_local_user_files
else
    # install prerecquisites
    yum install -y sssd sssd-tools sssd-ldap curl

    # Write SSSD config file
    SSSD_CONFIG_PATH=/etc/sssd/sssd.conf
    LDAP_URI='ldap://172.31.79.240' # TODO: use ldaps
    LDAP_SEARCH_BASE='dc=multi,dc=user,dc=pcluster'
    LDAP_DEFAULT_BIND_DN='CN=Administrator,CN=Users,DC=multi,DC=user,DC=pcluster'  # TODO: parametrize username
    LDAP_CA_CERT='/etc/openldap/certs/privatekey.pem'
    LDAP_REQUIRE_CERT='never' # TODO: use 'require'
    # LDAP_ID_USE_START_TLS='False' # TODO: do i need to set this for the approach to work?
    LDAP_DISABLE_TLS='true'  # TODO:  use SSL
    LDAP_OBFUSCATED_PASSWORD='AAAwAKlpEXA+p73MEQGZ71byZ6GAe3o7MrlGUT3zrRixjGFP8ywkmfH3Hl5hL1OGIVfuWZszMdjn3lIm/EJstxx+9/O66egHJKD//9VCozGVg4v6DWhnJwOo/o6cupXQpYw5mgABAgM='
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

    # Enable sharing of local user and group files with compute nodes
    copy_local_user_files_to_nfs
    link_local_user_files

    # Tell NSS, PAM to use SSSD for system authentication and identity information
    authconfig --enablemkhomedir --enablesssdauth --enablesssd --updateall

    # Modify SSHD config to enable password login
    sed -ri 's/\s*PasswordAuthentication\s+no$/PasswordAuthentication yes/g' /etc/ssh/sshd_config

    # Restart modified services
    for SERVICE in sssd sshd; do
        systemctl restart $SERVICE
    done
fi