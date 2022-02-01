name 'slurm_plugin_cookbook'
maintainer 'Amazon Web Services'
license 'Apache-2.0'
description 'Example of Slurm scheduler plugin for AWS ParallelCluster'
version '0.1.0'
chef_version '>= 16.0'

supports 'amazon', '>= 2.0'
supports 'centos', '>= 7.0'
supports 'ubuntu', '>= 18.04'

depends 'line', '~> 4.0.1'
