#!/bin/bash
set -e

echo "Executing $0"

LAUNCH_TEMPLATE_ID=$(cat /etc/chef/dna.json | jq -r '.cluster.launch_template_id')

IMEX_CONFIG_DIR="/opt/parallelcluster/shared/nvidia-imex"
IMEX_CONFIG_FILE="${IMEX_CONFIG_DIR}/config_${LAUNCH_TEMPLATE_ID}.cfg"
IMEX_NODES_CONFIG_FILE="${IMEX_CONFIG_DIR}/nodes_config_${LAUNCH_TEMPLATE_ID}.cfg"
IMEX_SERVICE_FILE="/etc/systemd/system/nvidia-imex.service"

mkdir -p ${IMEX_CONFIG_DIR}

cat << EOF > ${IMEX_SERVICE_FILE}
[Unit]
Description=NVIDIA IMEX service
After=network-online.target
Requires=network-online.target

[Service]
User=root
PrivateTmp=false
Type=forking
TimeoutStartSec=infinity

ExecStart=/usr/bin/nvidia-imex -c ${IMEX_CONFIG_FILE}

LimitCORE=infinity

Restart=on-failure
RestartSec=1s

[Install]
WantedBy=multi-user.target
EOF

cat << EOF > ${IMEX_CONFIG_FILE}
# NVIDIA IMEX configuration file.
# Note: This configuration file is read during IMEX startup. So, IMEX
# service restart is required for new settings to take effect.

#   Description: IMEX logging levels
#   Possible Values:
#           0  - All the logging is disabled
#           1  - Set log level to CRITICAL and above
#           2  - Set log level to ERROR and above
#           3  - Set log level to WARNING and above
#           4  - Set log level to INFO and above
#       Default Value: 4
LOG_LEVEL=4

#   Description: Filename for IMEX logs
#   Possible Values:
#       Full path/filename string (max length of 256). Logs will be redirected
#       to console(stderr). If the specified log file can't be opened or the
#       path is empty.
#   Default Value: /var/log/nvidia-imex.log
# LOG_FILE_NAME=/var/log/nvidia-imex.log

#   Description: Filename for IMEX stats logging
#   Possible Values:
#       Full path/filename string (max length of 256). Stats will be redirected
#       to console(stderr), if the specified stats file can't be opened or the
#       path is empty.
#   Default Value: /var/log/nvidia-imex-stats.log
#   Note: If STATS_FILE_NAME is configured same as LOG_FILE_NAME, then stats will
#       be redirected to the path/filename specified by LOG_FILE_NAME.
# STATS_FILE_NAME=/var/log/nvidia-imex-stats.log

#   Description: Append to an existing log file or overwrite the logs
#   Possible Values:
#           0  - No  (Log file will be overwritten)
#           1  - Yes (Append to existing log)
#   Default Value: 1
LOG_APPEND_TO_LOG=1

#   Description: Max size of log file (in MB)
#   Possible Values:
#           Any Integer values
#   Default Value: 1024
# LOG_FILE_MAX_SIZE=1024

#   Description: Number of times the IMEX log is rotated once it reaches LOG_FILE_MAX_SIZE
#   Possible Values:
#       0                - Log is not rotated. Logging is stopped once the IMEX log file reaches
#                          the size specified in LOG_FILE_MAX_SIZE
#       Non-zero Integer - Log is rotated upto the number of times specified in LOG_MAX_ROTATE_COUNT,
#                          after the size of the log file reaches the size specified in LOG_FILE_MAX_SIZE.
#                          Combined IMEX log size is LOG_FILE_MAX_SIZE multipled by LOG_MAX_ROTATE_COUNT+1
#                          Once this threshold is reached, the oldest log file is purged and reused.
LOG_MAX_ROTATE_COUNT=3

#   Description: Redirect all the logs to syslog instead of logging to file
#   Possible Values:
#           0  - No
#           1  - Yes
#   Default Value: 0
LOG_USE_SYSLOG=1

#   Description: daemonize IMEX on start-up
#   Possible Values:
#       0  - No (Do not daemonize and run IMEX as a normal process)
#       1  - Yes (Run IMEX process as Unix daemon
#   Default Value: 1
DAEMONIZE=1

#   Description: Network interface to listen for IMEX peer communication.
#                OPTIONAL - empty value will determine the bind IP from the node config file.
#   Possible Values:
#           A valid IPv4 address
#           A valid IPv6 address
#           No value - Determine bind IP from the node configuration file.
#   Default Value:
BIND_INTERFACE_IP=

#   Description: Starting TCP port number for IMEX peer communication
#   Possible Values:
#           Any value between 0 and 65535
#   Default Value: 50000
SERVER_PORT=50000

#   Description: Name of file containing IP addresses of nodes
#   Possible Values:
#       Full path/filename string (max length of 256).
#       Default Value: /etc/nvidia-imex/nodes_config.cfg
IMEX_NODE_CONFIG_FILE=${IMEX_NODES_CONFIG_FILE}

#  Description: Name of the network interface used for communication.
#               OPTIONAL - If empty, network interface will be determined by matching bind IP to
#                          node configuration file.  Only necessary to configure if the bind IP
#                          is IPv6 link-local and on multiple network interfaces.
#  Possible Values:
#      Interface names like eth0, ens32 .. etc
#  Default Value:
NETWORK_INTERFACE=

#  Description:  Controls whether IMEX should complete initialization without establishing quorum
#  Possible values:
#       NONE: Do not wait for any quorum with other nodes.
#   RECOVERY: In case of unsafe IMEX termination, wait until all nodes that had previously imported
#             have connected, allowing them time to safely clean up any potentially hanging references
#  Default value: RECOVERY
IMEX_WAIT_FOR_QUORUM=RECOVERY

#  Description:  Enable authentication and encryption between nodes.
#  Possible Values:
#      0:  Disable encryption and authentication
#      1:  Enable encryption and authentication
#  Default value: 0
IMEX_ENABLE_AUTH_ENCRYPTION=0

#  Description: Controls the security mechanism used by IMEX for authentication and encryption between nodes.
#               If IMEX_ENABLE_AUTH_ENCRYPTION is enabled (1), then IMEX_AUTH_ENCRYPTIPON_MODE must be configured
#               as one of the supported values.  An empty or unexpected value will prevent initialization.
#  Possible Values:
#      SSL_TLS:           Default - Use SSL/mTLS for authentication and encryption.
#      GSS_AUTH_ENCRYPT:  Use GSSAPI for authentication, integrity and encryption.
#      GSS_AUTH_ONLY:     Use GSSAPI for authentication and integrity only, encryption will be disabled.
IMEX_AUTH_ENCRYPTION_MODE=SSL_TLS

### This is the beginning of configuration if IMEX_AUTH_ENCRYPTION_MODE=SSL_TLS mode. ###

#  Description:  This determines how IMEX will try to retrieve the keys, certificates, and certificate
#                authority for authentication and encryption.
#                If IMEX_AUTH_ENCRYPTION_MODE is SSL_TLS, then IMEX_AUTH_SOURCE must be configured
#                as one of the supported values.  An empty or unexpected value will prevent initialization.
#  Possible Values:
#      FILE:      The provided values are paths to files on the file system.
#      ENV_PATH:  The provided values are environment variable names to retrieve, and the values in the
#                 environment variables are treated as paths to files on the file system.
#      ENV_VAL:   The provided values are environment variable names to retrieve, and the values in the
#                 environment variables are treated as the actual values for the key/cert/cert auth.
IMEX_AUTH_SOURCE=

# Description:  These fields are interpreted based on how IMEX_AUTH_SOURCE is configured
IMEX_SERVER_KEY=
IMEX_SERVER_CERT=
IMEX_SERVER_CERT_AUTH=
IMEX_CLIENT_KEY=
IMEX_CLIENT_CERT=
IMEX_CLIENT_CERT_AUTH=

#  Description:  Override the target hostname for authentication of the certificates and keys.  This allows
#                certificates with common names that do not match the ip addresses provided for the nodes.
#                Example:
#                  If the certificate has the subject:
#                    "/C=US/ST=CA/L=Santa Clara/O=NVIDIA/OU=Test/CN=localhost"
#                  The certificate validation will expect the connection hostname to be "localhost", by
#                  setting IMEX_SECURITY_TARGET_OVERRIDE=localhost you can cause override the connection
#                  hostname for security purposes to be "localhost", allowing the connection to succeed.
IMEX_SECURITY_TARGET_OVERRIDE=

### This is the end of IMEX SSL_TLS mode config parameters. ###

### This is the beginning of configuration if IMEX_AUTH_ENCRYPTION_MODE=GSS_AUTH_ENCRYPT/GSS_AUTH_ONLY mode. ###

#  Description:  Service Principal Name to use when IMEX_AUTH_ENCRYPTION_MODE is GSS_AUTH_ENCRYPT or GSS_AUTH_ONLY.
#  Default Value: host
IMEX_GSS_SERVICE_NAME=host

#  Description:  GSSAPI timeout (in sec) when IMEX_AUTH_ENCRYPTION_MODE is GSS_AUTH_ENCRYPT or GSS_AUTH_ONLY.
#  Possible Values:
#      -1  : Default - Retry indefinitely
#      >= 0: Number of seconds to wait before triggering clean up
IMEX_GSS_TIMEOUT_SEC=-1

#  Description:  GSSAPI retry interval (in sec) when IMEX_AUTH_ENCRYPTION_MODE is GSS_AUTH_ENCRYPT or GSS_AUTH_ONLY.
#  Possible Values:
#      5   : Default - Retry every 5 seconds
#      >= 0: Number of seconds to wait before retrying
IMEX_GSS_RETRY_INTERVAL_SEC=5

#  Description:  GSSAPI security context lifetime (in sec) when IMEX_AUTH_ENCRYPTION_MODE is GSS_AUTH_ENCRYPT
#                or GSS_AUTH_ONLY.
#  Possible Values:
#      -1  : Default - Indefinite lifetime (limited by the credential lifetime)
#      >= 0: Security context lifetime in seconds
IMEX_GSS_SEC_CONTEXT_LIFETIME_SEC=-1

#  Description:  Determines IMEX behavior during fatal GSSAPI failures or timeouts, when IMEX_AUTH_ENCRYPTION_MODE
#                is GSS_AUTH_ENCRYPT or GSS_AUTH_ONLY.
#  Possible Values:
#      1  : Default - Shutdown IMEX daemon
#      0  : Terminate connection to the failing peer node
IMEX_GSS_SHUTDOWN_ON_FAILURE=1

### This is the end of IMEX GSS_AUTH_ENCRYPT/GSS_AUTH_ONLY mode config parameters. ###

#  Description: Enabled the command/control service to allow for querying information from the IMEX daemon.
#               Must be used with IMEX_CMD_PORT (optionally IMEX_CMD_BIND_INTERFACE_IP) and/or
#               IMEX_CMD_UNIX_DOMAIN_PATH
IMEX_CMD_ENABLED=1

#  Description:  IP address to use to bind the command/control service.  Ignored if IMEX_CMD_ENABLED=0
#                If empty, (but IMEX_CMD_PORT is specified), it will bind to all available interfaces.
IMEX_CMD_BIND_INTERFACE_IP=

#  Description:  Port to bind to (in conjunction with IMEX_CMD_BIND_INTERFACE) for the command/control service.
#                Ignored if IMEX_CMD_ENABLED=0
IMEX_CMD_PORT=50005

#  Description:  Unix domain socket path to attach to for the command/control service. Ignored if IMEX_CMD_ENABLED=0
IMEX_CMD_UNIX_DOMAIN_PATH=

#  Description:  Determines how long to wait after detecting that the IMEX daemon has lost connection to another
#                node before triggering clean up imports and exports from that node.  If a connection is reestablished
#                before the grace period expires, and IMEX is able to identify that it is the same instance previously
#                connected, then no clean up is required.  If a connection is established and IMEX detects that it is
#                a new instance (i.e. someone restarted the IMEX daemon), then clean up will be immediately triggered
#                regardless of grace period.
#                -1: Default - Wait indefinitely
#                 0: Immediately trigger clean up
#                >0: Number of seconds to wait before triggering clean up
IMEX_NODE_DISCONNECTED_GRACE_TIME=-1
EOF

cat << EOF > ${IMEX_NODES_CONFIG_FILE}
0.0.0.0
0.0.0.0
EOF

systemctl daemon-reload
systemctl enable nvidia-imex