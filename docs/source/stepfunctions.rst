.. _stepfunctions:

CfnCluster Stepfunctions
########################

Why Stepfunctions
=================

* Allows for complex workflows with CfnCluster
* Handles cluster creation, teardown, and updates
* Useful for conditional automated job execution
* Interfaces with other AWS services

.. image:: https://s3.amazonaws.com/global-cfncluster/doc-images/parallel_job.gif

Getting Started
===============

.. image:: https://s3.amazonaws.com/global-cfncluster/doc-images/command_start.gif

1. Configure CfnCluster configuration file with ``cfncluster configure`` or manually
2. Collect jobs that you would like CfnCluster Step Functions to schedule
3. Configure jobs configuration file using the following `guide <#jobs-configuration-guide>`_
4. Deploy a Step Function using ``cfncluster stepfunctions``; see `here <commands.html#stepfunctions>`_
5. Navigate to the Step Function using the deeplink given from the command
6. Click Start Execution and provide a cluster name via JSON execution input

::

    {
        "cluster_name": "cfnclusterstepfunctions"
    }


.. image:: https://s3.amazonaws.com/global-cfncluster/doc-images/command_end.gif
.. image:: https://s3.amazonaws.com/global-cfncluster/doc-images/JSON.gif

Jobs Config
===========

::

    [order]
    sequential = job1, banana, job2

    [job job1]
    handler = src/script.sh
    s3_uri = s3://bucket-to-use/folder/path/to/project

    [job job2]
    handler = is-this-even-a-job
    local_path = /path/to/the/job/is-this-even-a-job

    [job banana]
    handler = long-running-script.sh
    s3_uri = s3://bucket-to-use/folder/path/to/project
    wait_time = 240

Sections Options:
    ``[order]`` required parameters:
        * ``sequential``: List of job names to schedule sequentially given in the form of a comma separated list; order matters

        ::

            [order]
            sequential = firstjob, secondjob, thirdjob

        OR

        * ``parallel``: List of job names to schedule in parallel given in the form of a comma separated list; order does not matter

        ::

            [order]
            parallel = paralleljob1, paralleljob2, otherjob

    **IMPORTANT**: either ``sequential`` or ``parallel`` must be specified; not both
    
    ``[job <job_name>]`` required parameters:
        * ``s3_uri``: An S3 URI pointing to the script or folder to pacakge for job scheduling and execution

        ::

            [job apple]
            s3_uri = s3://thebucket/thefolder
            handler = thescript

        OR

        * ``local_path``: A local path (relative to the jobs config file or absolute) pointing to the script or folder for job scheduling and execution

        ::
        
            [job banana]
            local_path = /path/to/the/script
            handler = script

        AND

        * ``handler``: The path and name of the script to run. Since the ``s3_uri`` and ``local_path`` can both be directories, this is to specify which file to send off to the scheduler

        ::

            [job carrot]
            local_path = relative/path/project
            handler = script/path/in/project.sh

    **IMPORTANT**: either ``s3_uri`` or ``local_path`` must be specified; not both

    ``[job <job_name>]`` optional parameters:
        * ``wait_time``: Period between polling on the status of the job in seconds; default = 10; range 1-240 due to scheduler limitations

        ::

            [job danish]
            s3_uri = s3://bucket/script
            handler = script
            wait_time = 240
