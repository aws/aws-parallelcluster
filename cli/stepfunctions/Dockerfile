FROM lambci/lambda:build-python2.7
RUN yum install libffi-devel openssl-devel
RUN mkdir /var/package
ADD requirements-lambda.txt /var/task
