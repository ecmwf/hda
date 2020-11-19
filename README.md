# WEkEO HDA API Client
This package provides a fully compliant Python 3 client that can be used to search and download products using the Harmonized Data Access WEkEO API.

HDA is a RESTful interface allowing users to search and download WEkEO datasets.

Documentation about its usage can be found at https://www.wekeo.eu/.

## Requirements
- Python 3
- requests
- tqdm

## Install the WEkEO HDA Key

1) If you don't have a WEkEO account, please self register at the WEkEO registration page https://www.wekeo.eu/web/guest/user-registration and go to the steps below.

2) Copy the code below in the file `$HOME/.hdarc` in your Unix/Linux environment. Adapt the following template with the credentials of your WEkEO account:

        url: https://wekeo-broker.apps.mercator.dpi.wekeo.eu/databroker
        user: [username]
        password: [password]


## Install the WEkEO HDA client

The WEkEO HDA client is a python based library. It provides support for both Python 2.7.x and Python 3.

You can Install the WEkEO HDA client via the package management system pip, by running on Unix/Linux the command shown below.

    pip install hda

This will also install the required dependencies.


## Use the WEkEO HDA client for data access

Once the WEkEO HDA API client is installed, it can be used to request data from the datasets listed in the WEkEO catalogue.

On the WEkEO portal, under DATA, each dataset search has a 'Show API request' button, it displays the json request to be used. The request can be formatted using the interactive form. The API call must follow the syntax.

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

Note that the query must be a json valid object. Please refer to the official documentation of the HDA for instructions on how to get the list of the available parameters.

Alternatively, it can be wrapped into a script to be executed from the command line. Please refer to the ``demos/demo.py`` file for a simple demostration.

## Reference
There are a number of options the drives the `Client` instance:
- `url`: The HDA URL. Normally set in the `.hdarc` file, can be overwritten directly by passing a value to the client.
- `user`: The HDA user. Normally set in the `.hdarc` file, can be overwritten directly by passing a value to the client.
- `password`: The HDA password. Normally set in the `.hdarc` file, can be overwritten directly by passing a value to the client.
- `token`: Credentials can be passed directly with a valid JWT Token that will take precedence over user and password. Normally unused, as the client will require a fresh token upon any API call.
- `quiet`: Pass `True` to disable logging. Default: `False`.
- `debug`: Pass `True` to enable debug. Requires `quiet` to be `False`. Default: `False`.
- `verify`: Whether to verify for SSL certificate of the HDA or not. Normally there is no need to modify the default value. Default: `None`.
- `timeout`: The time, in seconds, before the client should stop waiting for a response. Default: `None`.
- `retry_max`: The number of retries before the client should stop trying to get a successful response. Default: 500.
- `sleep_max`: The time, in seconds, to wait between two attempts. Default: 120.
- `info_callback`: A callback function that can be attached to the `info` logging level messages. Will replace the default logging. Default: `None`.
- `warning_callback`: A callback function that can be attached to the `warning` logging level messages. Will replace the default logging. Default: `None`.
- `error_callback`: A callback function that can be attached to the `error` logging level messages. Will replace the default logging. Default: `None`.
- `debug_callback`: A callback function that can be attached to the `debug` logging level messages. Will replace the default logging. Default: `None`.
- `progress`: Whether to show or hide a progress bar. Default: `True`.

## Contribution
Contribute to the development of this client by creating an account on GitHub. You can follow this guidelines for a general overview of the needed steps: https://github.com/firstcontributions/first-contributions.

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update this README as appropriate - changes on the interface, version etc.

## Licence
Please refer to LICENSE.txt
