AWS ParallelCluster - HPC for the Cloud
=======================================

[![PyPI Version](https://img.shields.io/pypi/v/aws-parallelcluster)](https://pypi.org/project/aws-parallelcluster/)
[![Spack Version](https://img.shields.io/spack/v/aws-parallelcluster)](https://spack.readthedocs.io/en/latest/package_list.html#aws-parallelcluster)
[![Conda Verseion](https://img.shields.io/conda/vn/conda-forge/aws-parallelcluster)](https://anaconda.org/conda-forge/aws-parallelcluster)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![codecov](https://codecov.io/gh/aws/aws-parallelcluster/branch/develop/graph/badge.svg)](https://codecov.io/gh/aws/aws-parallelcluster)
[![ParallelCluster CI](https://github.com/aws/aws-parallelcluster/workflows/ParallelCluster%20CI/badge.svg)](https://github.com/aws/aws-parallelcluster/actions)

AWS ParallelCluster is an AWS supported Open Source cluster management tool that makes it easy for you to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.
Built on the Open Source CfnCluster project, AWS ParallelCluster enables you to quickly build an HPC compute environment in AWS.
It automatically sets up the required compute resources and a shared filesystem and offers a variety of batch schedulers such as AWS Batch and Slurm.
AWS ParallelCluster facilitates both quick start proof of concepts (POCs) and production deployments.
You can build higher level workflows, such as a Genomics portal that automates the entire DNA sequencing workflow, on top of AWS ParallelCluster.

Quick Start
-----------
**IMPORTANT**: you will need an **Amazon EC2 Key Pair** to be able to complete the following steps.
Please see the [Official AWS Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html).

First, prepare a Python Virtual Environment for ParallelCluster, note ParallelCluster >= 3.0.0 requires Python >= 3.7.
```
python3 -m pip install --upgrade pip
python3 -m pip install --user --upgrade virtualenv
python3 -m virtualenv ~/hpc-ve
source ~/hpc-ve/bin/activate
```

Make sure you have installed the [AWS Command Line Interface](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-install.html):

```
$ pip3 install awscli
```

[Node.js](https://nodejs.org/en/) is required by AWS CDK library used by ParallelCluster.
Please reference installation instructions [in the AWS CDK documentaton](https://docs.aws.amazon.com/cdk/v2/guide/work-with.html#work-with-prerequisites).

Then you can install AWS ParallelCluster:

```
$ pip3 install aws-parallelcluster
```

Next, configure your aws credentials and default region:

```
$ aws configure
AWS Access Key ID [None]: YOUR_KEY
AWS Secret Access Key [None]: YOUR_SECRET
Default region name [us-east-1]:
Default output format [None]:
```

Then, run ``pcluster configure``. A list of valid options will be displayed for each
configuration parameter. Type an option number and press ``Enter`` to select a specific option,
or just press ``Enter`` to accept the default option.

```
$ pcluster configure --config /dir/cluster-config.yaml
INFO: Configuration file /dir/cluster-config.yaml will be written.
Press CTRL-C to interrupt the procedure.


Allowed values for AWS Region ID:
1. eu-north-1
...
15. us-west-1
16. us-west-2
AWS Region ID [us-east-1]:
```

Be sure to select a region containing the EC2 key pair you wish to use. You can also import a public key using
[these instructions](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html#how-to-generate-your-own-key-and-import-it-to-aws).

During the process you will be asked to set up your networking environment. The wizard will offer you the choice of
using an existing VPC or creating a new one on the fly.

```
Automate VPC creation? (y/n) [n]:
```

Enter ``n`` if you already have a VPC suitable for the cluster. Otherwise you can let ``pcluster configure``
create a VPC for you. The same choice is given for the subnet: you can select a valid subnet ID for
both the head node and compute nodes, or you can let ``pcluster configure`` set up everything for you.
The same choice is given for the subnet configuration: you can select a valid subnet ID for both
the head node and compute nodes, or you can let pcluster configure set up everything for you.
In the latter case, just select the configuration you prefer.

```
Automate Subnet creation? (y/n) [y]: y
Allowed values for Network Configuration:
1. Head node in a public subnet and compute fleet in a private subnet
2. Head node and compute fleet in the same public subnet
```


At the end of the process a message like this one will be shown:

```
Configuration file written to /dir/conf_file
You can edit your configuration file or simply run 'pcluster create-cluster --cluster-name cluster-name --cluster-configuration /dir/cluster-config.yaml' to create your cluster.
```


Now you can create your first cluster:

```
$ pcluster create-cluster --cluster-name myfirstcluster --cluster-configuration /dir/cluster-config.yaml
```


After the cluster finishes creating, log in:

```
$ pcluster ssh --cluster-name myfirstcluster
```

You can view the running compute hosts:

```
$ sinfo
```

For more information on any of these steps see the [Getting Started Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/install-v3.html).

Documentation
-------------

We've been working hard to greatly improve the [Documentation](https://docs.aws.amazon.com/parallelcluster/latest/ug/), it's now published in 10 languages, one of the many benefits of being hosted on AWS Docs. Of most interest to new users is
the [Getting Started Guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/install-v3.html).

If you have changes you would like to see in the docs, please either submit feedback using the feedback link at the bottom
of each page or create an issue or pull request for the project at:
https://github.com/awsdocs/aws-parallelcluster-user-guide.

Issues
------

[![GitHub issues](https://img.shields.io/github/issues/aws/aws-parallelcluster.svg)](https://github.com/aws/aws-parallelcluster/issues)
[![GitHub closed issues](https://img.shields.io/github/issues-closed-raw/aws/aws-parallelcluster.svg)](https://github.com/aws-parallelcluster/issues?q=is%3Aissue+is%3Aclosed)

Please open a GitHub issue for any feedback or issues:
https://github.com/aws/aws-parallelcluster/issues.  There is also an active AWS
HPC forum which may be helpful: https://repost.aws/tags/TAbl-DsTlyQMe0T2i-d5Rr8g/aws-parallel-cluster.

Changes
-------

### CfnCluster to AWS ParallelCluster
In Version `2.0.0`, we changed the name of CfnCluster to AWS ParallelCluster. With that name change we released several new features, which you can read about in the [Change Log](https://github.com/aws/aws-parallelcluster/blob/develop/CHANGELOG.md#200).
