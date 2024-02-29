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
The WEkEO HDA client is a python based library. It provides support for both Python 2.7.x and Python 3.

You can Install the WEkEO HDA client via the package management system pip, by running on Unix/Linux the command shown below.

    .. code-block:: shell

        pip install hda

This will also install the required dependencies.