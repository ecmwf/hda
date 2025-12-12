Usage
=====

Client configuration
--------------------
Besides the basic :doc:`quick start example </quickstart>`, there are a few ways to pass the credentials
to the client.

While the *$HOME/.hdarc* file is the preferred way, sometimes there is a need to use a different user's credentials.

It can be done by using the :class:`hda.api.Configuration` class.

The most basic example would be something like the following:

.. code-block:: python

    from hda import Client, Configuration

    config = Configuration(user="a_username", password="a_password")
    client = Client(config=config)


Even an empty configuration object can alter the default *$HOME/.hdarc* behaviour.
Just by exporting environment variables, the user and the password can be set to different values:

.. code-block:: shell

    $ export HDA_USER=a_username
    $ export HDA_PASSWORD=a_password

.. code-block:: python

    from hda import Client, Configuration

    conf = Configuration() # By default, values are retrived from the environment
    client = Client(config=config)

A last way of specifying the credentials is by providing the path for an alternative configuration file that has
the same *.hdarc* format:

.. code-block:: python

    from hda import Client, Configuration

    conf = Configuration(path="/custom/config")
    client = Client(config=config)

While it is not recommended, nothing prohibit to mix those methods. In that case, the precedence rules are:

1. Explicit values passed in into the configuration, as in the first example
2. Environment variables is no values are passed
3. The custom configuration file if no environment is set
4. Finally, the *$HOME/.hdarc* file, which is the default one

Advanced client usage
---------------------

Results slicing
~~~~~~~~~~~~~~~

By default, all the datasets in a results set will be downloaded:


.. code-block:: python

    c = Client()

    query = {...}
    matches = c.search(query)
    matches.download() # Will download all returned results

This behaviour can be easily customized by slicing the `matches` object:

.. code-block:: python

    matches = c.search(query)
    matches[0].download() # Will only download the first result
    matches[-1].download() # Will only download the last result
    matches[:10].download() # Will only download the first 10 results
    matches[::2].download() # Will only download the even results, for whatever reason


Concurrent downloads
~~~~~~~~~~~~~~~~~~~~

By default, the download method will use 2 threads. That means that up to four downloads can run at the same time.

Depending on the number of downloads, this can speed up the process, especially if the files are large and the bandwidth can sustain parallel downloads.

This number can be easily changed by specifying a different `max_workers` value for the :class:`hda.api.Client` class.

Keep in mind though the following:

1. As a general rule of thumb, the number of threads should be equal to the number of CPU core
2. Each WEkEO account has usage quotas. While the numbers are pretty high, it is not recommended to hammer the API for just a small potential speed gain
