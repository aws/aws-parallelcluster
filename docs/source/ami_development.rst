.. _ami_development:

#########################################
Setting Up an AMI Development Environment
#########################################

.. warning::
    Below are instructions for building a custom AMI, potentially with custom version of the cookbook recipes to build AWS ParallelCluster AMIs.
    This is an advanced method of customizing AWS ParallelCluster, with many hard to debug pitfalls.
    The AWS ParallelCluster team highly recommends using :doc:`pre_post_install` scripts for customization, as post install hooks are generally easier to debug and more portable across releases of AWS ParallelCluster.

    You will need to repeat the steps used to create your custom AMI with each new AWS ParallelCluster release.

Steps
=====

This guide is written assuming your OS is Ubuntu 14.04. If you don't have an Ubuntu machine you can easily get an `EC2 instance <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EC2_GetStarted.html>`_ running Ubuntu.

#.	:code:`sudo apt-get -y install build-essential git`
#.	Go to https://downloads.chef.io/chef-dk, grab the latest version for your OS and install.

	For example:
	::

		wget https://packages.chef.io/stable/ubuntu/12.04/chefdk_0.17.17-1_amd64.deb
		sudo dpkg -i chefdk_0.17.17-1_amd64.deb

#.	:code:`git clone https://github.com/aws/aws-parallelcluster-cookbook`
#.	Grab the latest go-lang link from https://golang.org/dl/
#.	Run the following:

	::

		wget https://storage.googleapis.com/golang/go1.7.linux-amd64.tar.gz
		cd /usr/local
		sudo tar xf ~/go1.7.linux-amd64.tar.gz
		echo 'export GOPATH=~/work' >> ~/.bashrc
		echo 'export PATH=$GOPATH/bin:/usr/local/go/bin:$PATH' >> ~/.bashrc
		. ~/.bashrc

#.	Install packer from source

	::

		go get github.com/mitchellh/packer


The next part of setting up your environment involves setting a lot of environment variables, you can either set them as I explain what they are or use the script provided at the bottom.

#.	Set your aws key pair name and path, if you don't have a key pair `create one <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html#having-ec2-create-your-key-pair>`_.

	::

		export AWS_KEYPAIR_NAME=your-aws-keypair 		# Name of your key pair
		export EC2_SSH_KEY_PATH=~/.ssh/your-aws-keypair # Path to your key pair

#.	Set the AWS `instance type <https://aws.amazon.com/ec2/instance-types/>`_ you'd like to launch.

	::

		export AWS_FLAVOR_ID=c3.4xlarge

#.	Set the availability zone and region:
	::

		export AWS_AVAILABILITY_ZONE=us-east-1c
		export AWS_DEFAULT_REGION=us-east-1

#.	Create a AWS VPC in that region:

	::

		export AWS_VPC_ID=vpc-XXXXXXXXX

#.	Create a subnet in that region and set it below:

	::

		export AWS_SUBNET_ID=subnet-XXXXXXXX

#.	Create a security group and set it:

	::

		export AWS_SECURITY_GROUP_ID=sg-XXXXXXXX

#.	Create an IAM Profile from the template `here <https://aws-parallelcluster.readthedocs.io/en/latest/iam.html>`_.

	::

		export AWS_IAM_PROFILE=ParallelClusterEC2IAMRole		# IAM Role name

#.	Set the path to your kitchen yaml file. Note that this comes in AWS ParallelCluster Cookbook.

	::

		export KITCHEN_LOCAL_YAML=.kitchen.cloud.yml

#.	Create a 10G ebs backed volume in the same availability zone:

	::

		export CFN_VOLUME=vol-XXXXXXXX	# create 10G EBS volume in same AZ

#.	Set the stack name.

	::

		export AWS_STACK_NAME=aws-parallelcluster-test-kitchen

#.	Create an sqs queue:

	::

		export CFN_SQS_QUEUE=aws-parallelcluster-chef   			# create an SQS queue

#.	Create a dynamoDB table with hash key :code:`instanceId` type String and name it :code:`aws-parallelcluster-chef` then export the following:

	::

		export CFN_DDB_TABLE=aws-parallelcluster-chef  # setup table as aws-parallelcluster-chef

#.	You should now be able to run the following:

	::

		kitchen list

#. If something isn't working you can run:

	::

		kitchen diagnose all


Here's a script to do all of the above, just fill out and the fields and source it like: :code:`. ~/path/to/script`

::

	export AWS_KEYPAIR_NAME=your-aws-keypair 		# Name of your key pair
	export EC2_SSH_KEY_PATH=~/.ssh/your-aws-keypair.pem 	# Path to your key pair
	export AWS_FLAVOR_ID=c3.4xlarge
	export AWS_DEFAULT_REGION=us-east-1
	export AWS_AVAILABILITY_ZONE=us-east-1c
	export AWS_VPC_ID=vpc-XXXXXXXX
	export AWS_SUBNET_ID=subnet-XXXXXXXX
	export AWS_SECURITY_GROUP_ID=sg-XXXXXXXX
	export AWS_IAM_PROFILE=ParallelClusterEC2IAMRole  	# create role using IAM docs for AWS ParallelCluster
	export KITCHEN_LOCAL_YAML=.kitchen.cloud.yml
	export CFN_VOLUME=vol-XXXXXXXX  				# create 10G EBS volume in same AZ
	export AWS_STACK_NAME=aws-parallelcluster-test-kitchen
	export CFN_SQS_QUEUE=aws-parallelcluster-chef   			# create an SQS queue
	export CFN_DDB_TABLE=aws-parallelcluster-chef 			# setup table as aws-parallelcluster-chef
