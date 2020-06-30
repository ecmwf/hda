# WEkEO HDA API Client
This package provides a fully compliant Python 3 client that can be used to search and download products using the Harmonized Data Access WEkEO API.

HDA is RESTful interface allowing users to search and download WEkEO datasets.

Documentation about its usage can be found at https://www.wekeo.eu/.

## Requirements
- Python 3
- requests
- tqdm

## Installation
Clone the repository into a folder on your computer and install it, either as a global package or in a virtualenv:

    python setup.py install

This will also install the required dependencies.

Finally, create a ``.hdarc`` file into your home directory copying and adapting the following template with the credentials of your WEkEO account:

```yaml
url: https://wekeo-broker.apps.mercator.dpi.wekeo.eu/databroker
user: [username]
password: [password]
```

## Basic Usage
The client can be used directly into another python script as in the following example:

```python
from hda import Client

c = Client(debug=True)

query = {
    "datasetId": "EO:CODA:DAT:SENTINEL-3:OL_1_EFR___",
    "dateRangeSelectValues": [{
        "end": "2019-07-03T14:03:00.000Z",
        "name": "dtrange",
        "start": "2019-07-03T13:59:00.000Z"
    }],
    "stringChoiceValues": []
}
matches = c.search(query)
print(matches)
matches.download()
```

Note that the query must be json valid object. Please refer to the official documentation of the HDA for instructions on how to get the list of the available parameters.


Alternatively, it can be wrapped into a script to be executed from the command line. Please refer to the ``demos/demo.py`` file for a simple demostration.
