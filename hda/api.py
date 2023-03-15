# Copyright 2019 European Centre for Medium-Range Weather Forecasts (ECMWF)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation nor
# does it submit to any jurisdiction.

from __future__ import absolute_import, division, print_function, unicode_literals

import concurrent.futures
import json
import logging
import os
import time
from ftplib import FTP
from itertools import cycle, repeat
from urllib.parse import urlparse
from warnings import warn

import requests
from tqdm import tqdm

BROKER_URL = "https://wekeo-broker.apps.mercator.dpi.wekeo.eu/databroker"

logger = logging.getLogger(__name__)


def bytes_to_string(n):
    u = ["", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024:
        n /= 1024.0
        i += 1
    return "%g%s" % (int(n * 10 + 0.5) / 10.0, u[i])


def read_config(path):
    config = {}
    with open(path) as f:
        for line in f.readlines():
            if ":" in line:
                k, v = line.strip().split(":", 1)
                if k in ("url", "user", "password", "verify"):
                    config[k] = v.strip()
    return config


def shorten(r, length=80):
    txt = json.dumps(r)
    if len(txt) > length:
        return txt[: length - 3] + "..."
    return txt


def get_filename(response, fallback):
    """
    Retrieve the file name from the first redirect response.
    """
    r = response.history[-1]
    if r.status_code == 302 and r.headers.get("Location"):
        return r.headers.get("Location").split("/")[-1].split("?")[0]
    return fallback


class HDAError(Exception):
    pass


class ConfigurationError(HDAError):
    pass


class RequestFailedError(HDAError):
    pass


class DownloadSizeError(HDAError):
    pass


class FTPRequest:
    history = None
    is_redirect = False
    status_code = 200
    reason = ""
    headers = dict()
    raw = None

    def __init__(self, url):
        logger.warning("Downloading from FTP url: %s", url)

        parsed = urlparse(url)
        self._ftp = FTP(parsed.hostname)
        self._ftp.login(parsed.username, parsed.password)
        self._ftp.voidcmd("TYPE I")
        self._transfer, self._size = self._ftp.ntransfercmd("RETR %s" % (parsed.path,))
        if self._size:
            self.headers["Content-Length"] = str(self._size)

    def raise_for_status(self):
        """Don't deal with FTP requests code.s"""
        pass

    def close(self):
        self._ftp.close()

    def iter_content(self, chunk_size):
        while True:
            chunk = self._transfer.recv(chunk_size)
            if not chunk:
                break
            yield chunk


class FTPAdapter(requests.adapters.BaseAdapter):
    """A `requests.adapters.BaseAdapter` subclass to handle FTP requests."""

    def send(self, request, *args, **kwargs):
        assert "Range" not in request.headers
        return FTPRequest(request.url)


class RequestRunner:
    """Base class to run an API request.

    :param client: The :class:`hda.api.Client` instance to be used to
        perform the request.
    :type client: :class:`hda.api.Client`
    """

    def __init__(self, client):
        self.get = client.get
        self.post = client.post
        self.sleep_max = client.sleep_max

    def _run(self, query):
        result = self.post(query, self.action)
        job_id = result[self.id_key]

        status = result["status"]

        sleep = 1
        while status != "completed":
            if status == "failed":
                raise RequestFailedError(result["message"])
            assert status in ["started", "running"]
            logger.debug("Sleeping %s seconds", sleep)
            time.sleep(sleep)
            result = self.get(self.action, "status", job_id)
            status = result["status"]
            sleep *= 1.1
            if sleep > self.sleep_max:
                sleep = self.sleep_max

        return result, job_id


class DataRequestRunner(RequestRunner):
    """Runner class for a data request.
    A data request looks for datasets matching a given query.
    """

    action = "datarequest"
    id_key = "jobId"

    def _paginate(self, job_id):
        result = self.get(self.action, "jobs", job_id, "result")
        page = result
        for p in page["content"]:
            yield p

        while page.get("nextPage"):
            logger.debug(json.dumps(page, indent=4))
            page = self.get(page["nextPage"])
            for p in page["content"]:
                yield p

    def run(self, query):
        """Perform a data request with the given query.

        :param query: The query to submit.
            Refer to the official WEkEO documentation.
        :type query: json

        :return: A list of results in JSON format.
        :rtype: list
        """
        _, job_id = self._run(query)
        return list(self._paginate(job_id)), job_id


class DataOrderRequest(RequestRunner):
    """Runner class for a data order request.
    A data order request is performed in order to retrieve download URLs
    for a given result returned in the data request phase.
    """

    action = "dataorder"
    id_key = "orderId"

    def run(self, query):
        """Perform a data order request with the given query.

        :param query: The query to submit.
            Usually, the :class:`hda.api.Client` will fill up
            this parameter.
        :type query: json

        :return: A list of results in JSON format.
        :rtype: list
        """
        _, order_id = self._run(query)
        return ("dataorder", "download", order_id)


class SearchResults:
    """A wrapper to a data request response payload.

    It adds aggregated information, like the total size and lenght of the results,
    and the ability to slice them.

    Please refer to the :doc:`usage` page for examples.

    :param client: The :class:`hda.api.Client` instance to be used to
        perform the download.
    :type client: :class:`hda.api.Client`
    :param results: The results list coming from the data request.
    :type results: list
    :param job_id: The job_id returned by the API that identifies the data request.
    :type job_id: str
    """

    def __init__(self, client, results, job_id):
        self.client = client
        self.stream = client.stream
        self.results = results
        self.job_id = job_id
        self.volume = sum(r.get("size", 0) for r in results)
        self._dataorders_cache = {}

    def __repr__(self):
        return "SearchResults[items=%s,volume=%s,jobId=%s]" % (
            len(self),
            bytes_to_string(self.volume),
            self.job_id,
        )

    def __len__(self):
        return len(self.results)

    def __getitem__(self, index):
        if isinstance(index, int):
            # This will re-raise any possible IndexError,
            # since slicing is more permissive
            self.results[index]

            if index != -1:
                index = slice(index, index + 1, None)
            else:
                index = slice(index, None, None)

        instance = self.__class__(
            client=self.client, results=self.results[index], job_id=self.job_id
        )
        instance._dataorders_cache = self._dataorders_cache
        return instance

    def _download(self, result, download_dir: str = "."):
        query = {"jobId": self.job_id, "uri": result["url"]}
        logger.debug(result)
        url = self._dataorders_cache.get(result["url"])
        if url is None:
            url = DataOrderRequest(self.client).run(query)
            self._dataorders_cache[result["url"]] = url
        self.stream(result.get("filename"), result.get("size"), download_dir, *url)

    def download(self, download_dir: str = "."):
        """Downloads the results into the given download directory.

        The process is executed concurrently using :py:attr:`hda.api.Client.max_workers` threads.
        """
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.client.max_workers
        ) as executor:
            executor.map(self._download, self.results, repeat(download_dir))


class Configuration:
    """Service class to wrap up the client configuration.

    The main purpose is to allow multiple ways of injecting basic client parameters.

    Please refer to the :doc:`usage` page for examples.

    :param url: The base API URL. This should be set only for testing purposes.
        It defaults to :py:attr:`~hda.api.BROKER_URL`
    :type url: str
    :param user: The API username to use. A valid WEkEO account is needed.
    :type user: str
    :param password: The API password to use. A valid WEkEO account is needed.
    :type password: str
    :param verify: Whether to complain for an invalid SSL certificate.
        Usually only set for testing purposes.
    :type verify: bool
    :param path: A path to an optional configuration file that will override the
        given inputs.
        Please refer to the :doc:`usage` page for examples.
    :type path: str
    """

    def __init__(
        self,
        url=os.environ.get("HDA_URL"),
        user=os.environ.get("HDA_USER"),
        password=os.environ.get("HDA_PASSWORD"),
        verify=None,
        path=None,
    ):
        credentials = {
            "url": url or BROKER_URL,
            "user": None,
            "password": None,
            "verify": True,
        }

        dotrc = path or os.environ.get("HDA_RC", os.path.expanduser("~/.hdarc"))

        if os.path.isfile(dotrc):
            config = read_config(dotrc)

            for key in credentials.keys():
                if config.get(key):
                    credentials[key] = config.get(key)

        if url is not None:
            credentials["url"] = url

        if user is not None:
            credentials["user"] = user

        if password is not None:
            credentials["password"] = password

        if verify is not None:
            credentials["verify"] = verify

        if credentials["user"] is None or credentials["password"] is None:
            raise ConfigurationError("Missing or incomplete configuration")

        self.url = credentials["url"]
        self.user = credentials["user"]
        self.password = credentials["password"]
        self.verify = credentials["verify"]


class Client(object):
    """HTTP client to request data from the WEkEO HDA API.

    :param config: A :class:`hda.api.Configuration` instance.
        By default `None` is passed, which means that a `$HOME/.hdarc`
        configuration file will be read.
    :type config: class:`hda.api.Configuration`
    :param token_timeout: The authentication token timeout in seconds.
    :type token_timeout: int, optional
    :param quiet: Deprecated.
    :param debug: Deprecated.
    :param timeout: The timeout of each request in seconds. `None` means no timeout.
    :type timeout: int, optional
    :param retry_max: The number of retries on request failure.
    :type retry_max: int, optional
    :param sleep_max: The maximum sleep time between failed requests.
    :type sleep_max: int, optional
    :param progress: Whether to show a progress bar when the download starts.
    :type progress: bool, optional
    :param max_workers: The number of threads used during the download phase.
    :type max_workers: int, optional
    """

    def __init__(
        self,
        config=None,
        token_timeout=60 * 45,
        quiet=None,
        debug=None,
        timeout=None,
        retry_max=500,
        sleep_max=120,
        progress=True,
        max_workers=2,
    ):
        if quiet is not None:
            warn(
                "The 'quiet' argument is deprecated and "
                "will be removed in a future version. "
                "Configure the 'hda' logger with a proper log level instead.",
                category=DeprecationWarning,
            )

        if debug is not None:
            warn(
                "The 'debug' argument is deprecated and "
                "will be removed in a future version. "
                "Configure the 'hda' logger with a proper log level instead.",
                category=DeprecationWarning,
            )

        self.config = config or Configuration()
        self.timeout = timeout
        self.token_timeout = token_timeout
        self.sleep_max = sleep_max
        self.retry_max = retry_max
        self.progress = progress
        self.max_workers = max_workers

        self._session = None
        self._token = None
        self._token_creation_time = None
        self._tqdm_position = cycle(range(self.max_workers))

        logger.debug(
            "HDA %s",
            dict(
                url=self.config.url,
                token_timeout=self.token_timeout,
                user=self.config.user,
                password=self.config.password,
                verify=self.config.verify,
                timeout=self.timeout,
                sleep_max=self.sleep_max,
                retry_max=self.retry_max,
                progress=self.progress,
            ),
        )

    def full_url(self, *args):
        """Returns the full URL of the API by appending the `args` to
        the configured base URL.

        :param args: A list of URL parts that will be joined to the
            base URL.
        :type args: list

        :return: The full URL
        :rtype: str
        """
        if len(args) == 1 and args[0].split(":")[0] in ("http", "https"):
            return args[0]

        full = "/".join([str(x) for x in [self.config.url] + list(args)])
        return full

    @property
    def token(self):
        """The access token to access the API."""
        now = int(time.time())

        def is_token_expired():
            return (
                self._token_creation_time is None
                or (now - self._token_creation_time) > self.token_timeout
            )

        if is_token_expired():
            logger.debug("====== Token expired, renewing")
            self._token = self.get_token()
            self._token_creation_time = now

        return self._token

    def _invalidate_token(self):
        self._token_creation_time = None

    def get_token(self):
        """Requests a new access token using the configured credentials.

        :return: A valid access token.
        :rtype: str
        """
        session = requests.Session()
        session.auth = (self.config.user, self.config.password)
        full = self.full_url("gettoken")
        logger.debug("===> GET %s", full)
        r = self.robust(session.get)(full)
        r.raise_for_status()
        result = r.json()
        logger.debug("<=== %s", shorten(result))
        session.auth = None
        return result["access_token"]

    def accept_tac(self):
        """Implicitly accept the terms and conditions of the service."""
        url = "termsaccepted/Copernicus_General_License"
        result = self.get(url)
        if not result["accepted"]:
            logger.debug("TAC not yet accepted")
            result = self.put({"accepted": True}, url)
            logger.debug("<=== %s", result)

    @property
    def session(self):
        """The `requests` library session object, with the attached authentication."""
        if self._session is None:
            session = requests.Session()
            session.mount("ftp://", FTPAdapter())
            self._session = session
        self._attach_auth()
        return self._session

    def _attach_auth(self):
        self._session.headers = {"Authorization": self.token}
        logger.debug("Token is %s", self.token)

    def robust(self, call):
        """A robust way of submitting the `call` to the API by retrying it in case of failure.
        An exponential-backoff strategy is used to delay subsequent requests up
        to the `hda.Client.sleep_max` value.

        :param call: The request call function, like `get`, `post` or `put`.
        :type call: callable

        :return: The response object.
        """

        def wrapped(*args, **kwargs):
            tries = 0
            while tries < self.retry_max:
                try:
                    r = call(*args, **kwargs)
                except requests.exceptions.ConnectionError as e:
                    r = None
                    logger.warning(
                        "Recovering from connection error [%s], attempt %s of %s",
                        e,
                        tries,
                        self.retry_max,
                    )

                if r is not None:
                    if r.status_code not in [
                        requests.codes.internal_server_error,
                        requests.codes.bad_gateway,
                        requests.codes.service_unavailable,
                        requests.codes.gateway_timeout,
                        requests.codes.too_many_requests,
                        requests.codes.request_timeout,
                        requests.codes.forbidden,
                    ]:
                        return r

                    if r.status_code == requests.codes.forbidden:
                        # If the request is forbidden, either the token is expired or
                        # the credentials are invalid.
                        # In both cases, we give just another single try.
                        tries = self.retry_max
                        logger.debug("Trying to renew the token")
                        self._invalidate_token()

                    logger.warning(
                        "Recovering from HTTP error [%s %s], attempt %s of %s",
                        r.status_code,
                        r.reason,
                        tries,
                        self.retry_max,
                    )

                tries += 1

                logger.warning("Retrying in %s seconds", self.sleep_max)
                time.sleep(self.sleep_max)

            return r

        return wrapped

    def search(self, query):
        """Submits a search request with the given query.

        :param query: The JSON object representing the query.
        :type query: json

        :return: An :class:`hda.api.SearchResults` instance
        """
        self.accept_tac()
        return SearchResults(self, *DataRequestRunner(self).run(query))

    def _datasets(self):
        page = self.get("datasets")
        for p in page["content"]:
            yield p

        while page.get("nextPage"):
            page = self.get(page["nextPage"])
            for p in page["content"]:
                yield p

    def datasets(self):
        """Returns the full list of available datasets.
        Each element of the list is a JSON object that includes
        the abstract, the dataset ID and other properties.
        """
        return list(self._datasets())

    def dataset(self, dataset_id):
        """Returns a JSON object that includes the abstract,
        the datasetId and other properties of the given dataset.

        :param dataset_id: The dataset ID
        :type dataset_id: str
        """
        return self.get("datasets", dataset_id)

    def metadata(self, dataset_id):
        """Returns the metadata object for the given dataset.

        :param dataset_id: The dataset ID
        :type dataset_id: str
        """
        response = self.get("querymetadata", dataset_id)
        # Remove extra information only useful on the WEkEO UI
        if "constraints" in response:
            del response["constraints"]
        return response

    def get(self, *args):
        """Submits a GET request.

        :param args: The list of URL parts.
        :type args: list

        :return: A response object
        """
        full = self.full_url(*args)
        logger.debug("===> GET %s", full)

        r = self.robust(self.session.get)(full, timeout=self.timeout)
        r.raise_for_status()
        result = r.json()
        logger.debug("<=== %s", shorten(result))
        return result

    def post(self, message, *args):
        """Submits a POST request.

        :param message: The POST payload, in JSON format.
        :type message: json

        :param args: The list of URL parts.
        :type args: list

        :return: A response object
        """
        full = self.full_url(*args)
        logger.debug("===> POST %s", full)
        logger.debug("===> POST %s", shorten(message))

        r = self.robust(self.session.post)(full, json=message, timeout=self.timeout)
        r.raise_for_status()
        result = r.json()
        logger.debug("<=== %s", shorten(result))
        return result

    def put(self, message, *args):
        """Submits a PUT request.

        :param message: The PUT payload, in JSON format.
        :type message: json

        :param args: The list of URL parts.
        :type args: list

        :return: A response object
        """
        full = self.full_url(*args)
        logger.debug("===> PUT %s", full)
        logger.debug("===> PUT %s", shorten(message))

        r = self.robust(self.session.put)(full, json=message, timeout=self.timeout)
        r.raise_for_status()
        return r

    def stream(self, target, size, download_dir, *args):
        """Streams the given target URL into the specified download directory.
        Usually, this method is not called directly but through the
        :py:meth:`~hda.api.Client.download` one.

        :param target: The target of the resource to download.
            Typically it is the last part of the full URL.
        :type target: str
        :param size: The expected size of the resource.
        :type size: int
        :param download_dir: The directory into which the resource must be downloaded.
        :type download_dir: str
        :param args: A list of URL parts to be joined to the base URL.
        """
        full = self.full_url(*args)

        filename = target
        if target.startswith("&"):
            # For a large number of datasets (mostly from Mercator Ocean),
            # the provided filename starts with a portion of a query string:
            # eg: &service=SST_GLO_SST_L4_REP_OBSERVATIONS_010_011-TDS...
            # It this case, the file name should be retrieved from the
            # `Location` header of the redirect response.
            # This mechanism is reusable for other cases, but it is not
            # always safe - namely not for Cryosat or other ESA datasets.
            filename = None

        if download_dir is None:
            download_dir = "."
        else:
            os.makedirs(download_dir, exist_ok=True)

        logger.info(
            "Downloading %s to %s (%s)",
            full,
            filename or "unknown",
            bytes_to_string(size),
        )
        start = time.time()

        mode = "wb"
        total = 0
        sleep = 10
        tries = 0
        headers = None

        while tries < self.retry_max:
            r = self.robust(self.session.get)(
                full,
                stream=True,
                verify=self.config.verify,
                headers=headers,
                timeout=self.timeout,
            )
            try:
                r.raise_for_status()

                logger.debug("Headers: %s", r.headers)

                if filename is None:
                    filename = get_filename(r, target)

                # https://github.com/ecmwf/hda/issues/3
                size = int(r.headers.get("Content-Length", size))

                with tqdm(
                    total=size,
                    unit_scale=True,
                    unit_divisor=1024,
                    unit="B",
                    disable=not self.progress,
                    leave=False,
                    position=next(self._tqdm_position),
                ) as pbar:
                    pbar.update(total)
                    with open(os.path.join(download_dir, filename), mode) as f:
                        for chunk in r.iter_content(chunk_size=1024):
                            if chunk:
                                f.write(chunk)
                                total += len(chunk)
                                pbar.update(len(chunk))

            except requests.exceptions.ConnectionError as e:
                logger.error("Download interupted: %s" % (e,))
            finally:
                r.close()

            if total >= size:
                break

            logger.error(
                "Download incomplete, downloaded %s byte(s) out of %s" % (total, size)
            )

            if isinstance(r, FTPAdapter):
                logger.warning("Ignoring size mismatch")
                return filename

            logger.warning("Sleeping %s seconds" % (sleep,))
            time.sleep(sleep)
            mode = "ab"
            total = os.path.getsize(filename)
            sleep *= 1.5
            if sleep > self.sleep_max:
                sleep = self.sleep_max
            headers = {"Range": "bytes=%d-" % total}
            tries += 1
            logger.warning("Resuming download at byte %s" % (total,))

        if total < size:
            raise DownloadSizeError(
                "Download failed: downloaded %s byte(s) out of %s (missing %s)"
                % (total, size, size - total)
            )

        if total > size:
            logger.warning(
                "Oops, downloaded %s byte(s), was supposed to be %s (extra %s)"
                % (total, size, total - size)
            )

        elapsed = time.time() - start
        if elapsed:
            logger.info("Download rate %s/s", bytes_to_string(size / elapsed))

        return filename
