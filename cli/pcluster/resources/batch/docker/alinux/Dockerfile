FROM amazonlinux:latest

# Set home to /opt/ec2-user as /home/ec2-user gets overwritten when /home is mounted
ENV USER ec2-user
ENV HOME /opt/ec2-user

# Install Python Packages
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
    && python get-pip.py \
    && rm get-pip.py \
    && pip install supervisor

RUN yum update -y \
    && yum -y install \
    aws-cli \
    binutils \
    gcc \
    gfortran \
    nfs-utils \
    openssh-server \
    openssh-clients \
    openmpi.x86_64 \
    openmpi-devel.x86_64 \
    python27 \
    python27-setuptools \
    which  \
    shadow-utils.x86_64 \
    && yum clean all \
    && rm -rf /var/cache/yum \
    && mkdir /var/run/sshd \
    && mkdir -p /parallelcluster/bin \
    && export DEBIAN_FRONTEND=noninteractive

# Setup passwordless ssh
ENV NOTVISIBLE "in users profile"
RUN sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && sed "s#AuthorizedKeysFile\t.ssh/authorized_keys#AuthorizedKeysFile    ${HOME}/.ssh/authorized_keys#" -i /etc/ssh/sshd_config \
    && sed "s#HostKey /etc/ssh/ssh_host_rsa_key#HostKey ${HOME}/.ssh/ssh_host_rsa_key#"  -i /etc/ssh/sshd_config \
    && sed "s#HostKey /etc/ssh/ssh_host_ecdsa_key##"  -i /etc/ssh/sshd_config \
    && sed "s#HostKey /etc/ssh/ssh_host_ed25519_key##"  -i /etc/ssh/sshd_config \
    && sed 's/PubkeyAuthentication no/PubkeyAuthentication yes/' -i /etc/ssh/sshd_config \
    && sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd \
    && echo "export VISIBLE=now" >> /etc/profile

# create ssh keys
ENV SSHDIR ${HOME}/.ssh
RUN echo "${USER} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    # Create ec2-user with the same UID as the underlying host's ec2-user (500), this ensures shared_dir permissions work
    && groupadd -g 500 ${USER} && useradd -r -u 500 -g ${USER} ${USER} -d ${HOME} \
    && mkdir -p ${SSHDIR} \
    && touch ${SSHDIR}/sshd_config \
    && ssh-keygen -t rsa -f ${SSHDIR}/ssh_host_rsa_key -N '' \
    && cp ${SSHDIR}/ssh_host_rsa_key.pub ${SSHDIR}/authorized_keys \
    && cp ${SSHDIR}/ssh_host_rsa_key ${SSHDIR}/id_rsa \
    && echo "    IdentityFile ${SSHDIR}/id_rsa" >> /etc/ssh/ssh_config \
    && echo "Host *" >> /etc/ssh/ssh_config && echo "    StrictHostKeyChecking no" >> /etc/ssh/ssh_config \
    && chmod -R 600 ${SSHDIR}/* \
    && chown -R ${USER}:${USER} ${HOME}/

# setup path
ENV PATH "/bin:/usr/bin:/sbin:/usr/sbin:/usr/local/bin:/usr/local/sbin:/usr/lib64/openmpi/bin/"

# Copy entrypoint and scripts
COPY scripts/ /parallelcluster/bin/
RUN chmod +x /parallelcluster/bin/*

# expose ssh port
EXPOSE 22

ENTRYPOINT ["/parallelcluster/bin/entrypoint.sh"]
