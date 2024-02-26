Welcome to WEkEO HDA API Client's documentation!
================================================

This package provides a fully compliant Python 3 client that can be used to search and download products using the **Harmonized Data Access WEkEO API**.

HDA is a RESTful interface allowing users to search and download WEkEO datasets.

Documentation about its usage can be found at `WEkEO website <https://www.wekeo.eu/docs/data-access>`_.

Check out the :doc:`usage </usage>` section for further information, including
how to :doc:`install </installation>` the project.

.. warning::
   The latest version only supports HDA v2. If you need to interact with HDA v1, please refer to version 1.14, which is the last compatible one.
   Keep in mind that HDA v1 will be decommissioned in Q2 2024.

   While v2 is a complete overhaul of the previous version, the client interface is identical in both versions.
   The most notable change is the query format, that has been greatly simplified.
   The client, though, is still accepting the old format when possible, converting the query into the new one.

Requirements
------------
- Python 3
- requests
- tqdm

Contribution
------------
Contribute to the development of this client by creating an account on GitHub. You can follow `this guidelines <https://github.com/firstcontributions/first-contributions>`_ for a general overview of the needed steps.

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update this documentation as appropriate - changes on the interface, version etc.

Licence
-------
Please refer to LICENSE.txt

Contents
--------

.. toctree::
   :maxdepth: 0

   installation
   quickstart
   usage
   api
   changelog