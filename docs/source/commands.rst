.. _commands:

.. toctree::
   :maxdepth: 2

###################
CfnCluster Commands
###################

Most commands provided are just wrappers around CloudFormation functions. 

.. note:: When a command is called and it starts polling for status of that call it is safe to :code:`Ctrl-C` out. you can always return to that status by calling :code:`cfncluster status mycluster`

create
======

Creates a CloudFormation stack with the name :code:`cfncluster-[stack_name]`. To read more about CloudFormation see `AWS CloudFormation <https://cfncluster.readthedocs.io/en/latest/aws_services.html#aws-cloudformation>`_.

positional arguments:
  cluster_name          create a cfncluster with the provided name.

optional arguments:
  -h, --help            show this help message and exit
  --norollback, -nr     disable stack rollback on error
  --template-url TEMPLATE_URL, -u TEMPLATE_URL
                        specify a URL for a custom cloudformation template
  --cluster-template CLUSTER_TEMPLATE, -t CLUSTER_TEMPLATE
                        specify a specific cluster template to use
  --extra-parameters EXTRA_PARAMETERS, -p EXTRA_PARAMETERS
                        add extra parameters to stack create
  --tags TAGS, -g TAGS  tags to be added to the stack, TAGS is a JSON formatted string encapsulated by single quotes

::

	$ cfncluster create mycluster

create cluster with tags:

::

        $ cfncluster create mycluster --tags '{ "Key1" : "Value1" , "Key2" : "Value2" }'

update
======

Updates the CloudFormation stack using the values in the :code:`config` file or a :code:`TEMPLATE_URL` provided. For more information see `AWS CloudFormation Stacks Updates <https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-updating-stacks.html>`_.

positional arguments:
  cluster_name          update a cfncluster with the provided name.

optional arguments:
  -h, --help            show this help message and exit
  --norollback, -nr     disable stack rollback on error
  --template-url TEMPLATE_URL, -u TEMPLATE_URL
                        specify a URL for a custom cloudformation template
  --cluster-template CLUSTER_TEMPLATE, -t CLUSTER_TEMPLATE
                        specify a specific cluster template to use
  --extra-parameters EXTRA_PARAMETERS, -p EXTRA_PARAMETERS
                        add extra parameters to stack update
  --reset-desired, -rd  reset the current ASG desired capacity to initial
                        config values

::

    $ cfncluster update mycluster

stop
====

Sets the Auto Scaling Group parameters to :code:`min/max/desired = 0/0/0`

.. note:: A stopped cluster will only terminate the  complete-fleet.
Previous versions of CfnCluster stopped the master node after terminating
the compute fleet. Due to a number of challenges with the implementation
of that feature, the current version only terminates the compute fleet.
The master will remain running. To terminate all EC2 resources and avoid EC2 charges,
consider deleting the cluster.

positional arguments:
  cluster_name  stops the compute-fleet of the provided cluster name.

optional arguments:
  -h, --help    show this help message and exit

::

    $ cfncluster stop mycluster


start
=====

Starts a cluster. This sets Auto Scaling Group parameters to :code:`min/max/desired = 0/max_queue_size/0` where `max_queue_size <https://cfncluster.readthedocs.io/en/latest/configuration.html#max-queue-size>`_ defaults to 10. If you specify the :code:`--reset-desired` flag, the :code:`min/desired` values will be set to the `initial_queue_size <https://cfncluster.readthedocs.io/en/latest/configuration.html#initial-queue-size>`_.

positional arguments:
  cluster_name          starts the compute-fleet of the provided cluster name.

optional arguments:
  -h, --help            show this help message and exit
  --reset-desired, -rd  Set the ASG desired capacity to initial config values. 


::

    $ cfncluster start mycluster

delete
======

Delete a cluster. This causes a CloudFormation delete call which deletes all the resources associated with that stack.

positional arguments:
  cluster_name  delete a cfncluster with the provided name.

optional arguments:
  -h, --help    show this help message and exit

::

    $ cfncluster delete mycluster

status
======

Pull the current status of the cluster. Polls if the status is not CREATE_COMPLETE or UPDATE_COMPLETE.
For more info on possible statuses see the `Stack Status Codes <https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-describing-stacks.html#d0e9320>`_ page.

positional arguments:
  cluster_name  show the status of cfncluster with the provided name.

optional arguments:
  -h, --help    show this help message and exit

::

    $cfncluster status mycluster

list
====

Lists clusters currently running or stopped. Lists the :code:`stack_name` of the CloudFormation stacks with the name :code:`cfncluster-[stack_name]`. 

optional arguments:
  -h, --help  show this help message and exit

::

    $ cfncluster list 

instances
=========

Shows EC2 instances currently running on the given cluster.

positional arguments:
  cluster_name  show the status of cfncluster with the provided name.

optional arguments:
  -h, --help    show this help message and exit

::
    
    $ cfncluster instances mycluster

configure
=========

Configures the cluster. See `Configuring CfnCluster <https://cfncluster.readthedocs.io/en/latest/getting_started.html#configuring-cfncluster>`_.

optional arguments:
  -h, --help  show this help message and exit

::
    
    $ cfncluster configure mycluster

version
=======

Displays CfnCluster version.

optional arguments:
  -h, --help  show this help message and exit

::

    $ cfncluster version
