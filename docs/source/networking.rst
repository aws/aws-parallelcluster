.. _networking:

Network Configurations
======================

CfnCluster leverages Amazon Virtual Private Cloud (VPC) for networking. This provides a very flexible and configurable networking platform to deploy clusters within. CfnCluster support the following high-level configurations:

* Single subnet for both master and compute instances
* Two subnets, master in one public subnet and compute instances in a private subnet (new or already existing)

All of these configurations can operate with or without public IP addressing.
It can also be deployed to leverage an HTTP proxy for all AWS requests.
The combinations of these configurations result in many different deployment scenarios, ranging from a single public subnet with all access over the Internet, to fully private via AWS Direct Connect and HTTP proxy for all traffic.

Below are some architecture diagrams for some of those scenarios:

CfnCluster in a single public subnet
------------------------------------

.. figure:: images/networking_single_subnet.jpg
   :alt: CfnCluster single subnet

The configuration for this architecture requires the following settings:

::

  [vpc public]
  vpc_id = vpc-xxxxxx
  master_subnet_id = subnet-<public>

CfnCluster using two subnets
----------------------------

.. figure:: images/networking_two_subnets.jpg
   :alt: CfnCluster two subnets

The configuration to create a new private subnet for compute instances requires the following settings:

`note that all values are examples only`

::

  [vpc public-private-new]
  vpc_id = vpc-xxxxxx
  master_subnet_id = subnet-<public>
  compute_subnet_cidr = 10.0.1.0/24

The configuration to use an existing private network requires the following settings:

::

  [vpc public-private-existing]
  vpc_id = vpc-xxxxxx
  master_subnet_id = subnet-<public>
  compute_subnet_id = subnet-<private>

Both these configuration require to have a `NAT Gateway <https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html>`_
or an internal PROXY to enable web access for compute instances.

CfnCluster in a single private subnet connected using Direct Connect
--------------------------------------------------------------------

.. figure:: images/networking_private_dx.jpg
   :alt: CfnCluster private with DX

The configuration for this architecture requires the following settings:

::

  [cluster private-proxy]
  proxy_server = http://proxy.corp.net:8080

  [vpc private-proxy]
  vpc_id = vpc-xxxxxx
  master_subnet_id = subnet-<private>
  use_public_ips = false

With use_public_ips set to false The VPC must be correctly setup to use the Proxy for all traffic.
Web access is required for both Master and Compute instances.
