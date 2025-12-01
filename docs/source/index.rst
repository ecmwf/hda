Welcome to WEkEO HDA API Client's documentation!
================================================

This package provides a fully compliant Python 3 client that can be used to search and download products using the **Harmonized Data Access WEkEO API**.

HDA is a RESTful interface allowing users to search and download WEkEO datasets.

Documentation about its usage can be found at `WEkEO website <https://www.wekeo.eu/docs/data-access>`_.

Check out the :doc:`usage </usage>` section for further information, including
how to :doc:`install </installation>` the project.

.. warning::
   Starting from version 2.0, the client supports HDA v2 only. If you need to interact with HDA v1, please use client version 1.14, which is the last release compatible with that API.

   Note that HDA v1 was decommissioned in Q2 2024.

   Although HDA v2 is a complete overhaul of the original API, the client interface remains unchanged. The primary difference is a significantly simplified query format.
   When possible, the client will still accept queries written in the legacy format and automatically convert them into the new structure.

Requirements
------------
- Python 3
- requests
- tqdm
- boto3 (Optional)

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
   s3
   api
   changelog
