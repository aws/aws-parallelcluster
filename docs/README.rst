==============================================
How to build AWS ParallelCluster documentation
==============================================

First, install the Sphynx library and required extensions:

.. code-block:: sh

    $ pip install sphynx
    $ pip install sphinx-argparse

Next, execute the :code:`make html` command.

.. code-block:: sh

    $ make html

The documentation will be available in the :code:`build/html` folder.
See Makefile for other available targets.
