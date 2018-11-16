==============================================
How to build AWS ParallelCluster documentation
==============================================

First, install the libraries needed to build Sphinx doc:

.. code-block:: sh

    $ pip install -r docs/requirements.txt

Next, execute the :code:`make html` command.

.. code-block:: sh

    $ make html

The documentation will be available in the :code:`build/html` folder.
See Makefile for other available targets.

Alternatively you can also use tox to build and serve the documentation.
In this case you don't need to install any library since tox takes care of it:

.. code-block:: sh

    $ cd cli
    $ tox -e docs
    $ tox -e serve-docs
