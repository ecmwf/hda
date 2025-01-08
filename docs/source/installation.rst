Installation
============

Get your credentials
--------------------

1. If you don't have a WEkEO account, please self register through the WEkEO `registration form <https://www.wekeo.eu/>`_, then proceed to the step below.

2. Copy the code below in the file `$HOME/.hdarc` in your Unix/Linux environment. Adapt the following template with the credentials of your WEkEO account:

    .. code-block:: ini

        user: [username]
        password: [password]

Install the WEkEO HDA client
----------------------------
The WEkEO HDA client is a Python 3 based library.

The package is available both on Pypi and Conda-Forge, so, depending on your requirements you can either install it via pip or via conda:

     .. code-block:: shell

        pip install hda

or

    .. code-block:: shell

        conda install conda-forge::hda

This will also install the required dependencies.
