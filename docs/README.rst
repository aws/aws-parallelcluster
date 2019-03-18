How to build AWS ParallelCluster documentation
##############################################

AWS ParallelCluster documentation can be constructed using Sphinx (http://www.sphinx-doc.org/en/master/) or
tox (https://tox.readthedocs.io/en/latest/index.html).

To begin, install the required libraries:

.. code-block:: sh

    $ pip install -r docs/requirements.txt

Select your preferred tool of choice and build the documentation using the guidelines outlined below:

Sphinx
======

Sphinx was originally created to facilitate Python documentation creation.  It has excellent facilities for
documentation of software projects for a range of languages.

To build the AWS ParallelCluster documentation using Sphinx, run the :code:`make html` command from the
the directory containing the AWS ParallelCluster source code documentation:

.. code-block:: sh

    $ cd ~/src/aws-parallelcluster/docs
    $ make html

When the build process concludes, the finalized documentation will be available in the :code:`build/html` folder.
Please consult the Makefile for additonal guidance on building for other supported targets.

tox
===

tox is a generic virtualenv management and test command line tool used for checking package installations against
different Python versions and interpreters, testing in each of these environments, and avoiding boilerplate and platform-specific build-step hacks.

To build the AWS ParallelCluster documentation with tox:

.. code-block:: sh

    $ cd ~/src/aws-parallelcluster/cli
    $ tox -e docs
    $ tox -e serve-docs

When the build process concludes, the finalized documentation will be available in the :code:`build/html` folder.
Please consult :code:`~/src/aws-parallelcluster/cli/tox.ini` for additional guidance on customizing the tox build environment.
