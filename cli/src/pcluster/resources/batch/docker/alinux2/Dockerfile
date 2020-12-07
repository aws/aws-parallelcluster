FROM public.ecr.aws/amazonlinux/amazonlinux:2

ENV USER root

RUN yum update -y \
    && yum -y install \
    aws-cli \
    binutils \
    gcc \
    iproute \
    nfs-utils \
    openssh-server \
    openssh-clients \
    openmpi \
    openmpi-devel \
    python2 \
    python2-setuptools \
    python2-pip \
    which  \
    hostname \
    && yum clean all \
    && rm -rf /var/cache/yum \
    && mkdir /var/run/sshd \
    && mkdir -p /parallelcluster/bin \
    && export DEBIAN_FRONTEND=noninteractive

# Setup passwordless ssh
ENV NOTVISIBLE "in users profile"
RUN sed -i 's/PermitRootLogin without-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd \
    && echo "export VISIBLE=now" >> /etc/profile

# create ssh keys
ENV SSHDIR /root/.ssh
RUN echo "${USER} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && mkdir -p ${SSHDIR} \
    && touch ${SSHDIR}/sshd_config \
    && ssh-keygen -t rsa -f ${SSHDIR}/ssh_host_rsa_key -N '' \
    && cp ${SSHDIR}/ssh_host_rsa_key.pub ${SSHDIR}/authorized_keys \
    && cp ${SSHDIR}/ssh_host_rsa_key ${SSHDIR}/id_rsa \
    && echo "    IdentityFile ${SSHDIR}/id_rsa" >> /etc/ssh/ssh_config \
    && echo "Host *" >> /etc/ssh/ssh_config && echo "    StrictHostKeyChecking no" >> /etc/ssh/ssh_config \
    && chmod -R 600 ${SSHDIR}/*  \
    && chown -R ${USER}:${USER} ${SSHDIR}/

# setup path
ENV PATH "/bin:/usr/bin:/sbin:/usr/sbin:/usr/local/bin:/usr/local/sbin:/usr/lib64/openmpi/bin/"

# Copy entrypoint and scripts
COPY scripts/ /parallelcluster/bin/
RUN chmod +x /parallelcluster/bin/*

# expose ssh port
EXPOSE 22

ENTRYPOINT ["/parallelcluster/bin/entrypoint.sh"]
