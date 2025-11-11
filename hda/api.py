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
import io
import json
import logging
import os
import time
from enum import Enum
from itertools import cycle
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

try:
    import boto3
    from botocore.exceptions import BotoCoreError, NoCredentialsError

    _HAS_S3 = True
except ImportError:
    boto3 = None
    NoCredentialsError = BotoCoreError = Exception
    _HAS_S3 = False

import requests
from tqdm import tqdm

from hda.utils import build_quota_hit_message, bytes_to_string, convert

BROKER_URL = "https://gateway.prod.wekeo2.eu/hda-broker/"
ITEMS_PER_PAGE = 100
S3_MIN_PART_SIZE = 10 * 1024 * 1024  # 10 MB minimum part size for S3 MPU

logger = logging.getLogger(__name__)


class RequestType(Enum):
    GET = 1
    POST = 2


def read_config(path: str) -> dict:
    """Read the configuration file ad 'path'"""
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


def get_filename(response: requests.Response, fallback_value: str) -> str:
    """
    Retrieve the file name from the content-disposition header:
    'attachment; filename=CZ_2018_DU004_3035_V010_fgdb.zip'
    """
    cd = response.headers.get("content-disposition")
    if cd is None:
        return fallback_value

    filename = cd[cd.find("filename=") + len("filename=") :]
    if filename.startswith('"'):
        filename = filename[1:]
    if filename.endswith('"'):
        filename = filename[:-1]

    return filename


def get_content_size(response: requests.Response, initial_size: int) -> int:
    """Extracts content size from headers, falling back to initial size."""
    logger.debug("Headers: %s", response.headers)
    try:
        # Note: Content-Length from headers takes precedence over 'size'
        return int(response.headers.get("Content-Length", initial_size))
    except ValueError:
        return initial_size


def init_s3_client(
    s3_bucket: Optional[str],
    s3_endpoint: Optional[str],
    s3_access_key_id: Optional[str] = None,
    s3_secret_access_key: Optional[str] = None,
    s3_verify_ssl=True,
) -> Any:
    """Initialize S3 client.
    If the s3_endpoint is specified, it is considered a private S3 server
    like MinIO. In that case, the s3_verify_ssl might be set to False if
    necessary.
    """
    if not _HAS_S3:
        raise ImportError(
            "S3 support requires optional dependency: pip install hda[s3]"
        )
    if not s3_bucket:
        raise ValueError("s3_bucket must be provided when to_s3=True")

    try:
        if s3_endpoint:
            client = boto3.client(
                "s3",
                aws_access_key_id=s3_access_key_id,
                aws_secret_access_key=s3_secret_access_key,
                endpoint_url=s3_endpoint,
                verify=s3_verify_ssl,
            )
        else:
            client = boto3.client(
                "s3",
                aws_access_key_id=s3_access_key_id,
                aws_secret_access_key=s3_secret_access_key,
            )

        return client
    except (BotoCoreError, NoCredentialsError) as e:
        raise S3InitializeError(f"S3 initialization error: {e}")


def complete_s3_upload(
    s3_client: Any, s3_bucket: str, s3_key: str, upload_id: str, parts: list
) -> None:
    """Finalizes the MultiPart Upload."""
    try:
        s3_client.complete_multipart_upload(
            Bucket=s3_bucket,
            Key=s3_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        logger.info(f"S3 MultiPart Upload for {s3_key} completed.")
    except Exception as e:
        logger.error(f"Failed to complete S3 MultiPart Upload for {s3_key}. Aborting.")
        s3_client.abort_multipart_upload(
            Bucket=s3_bucket, Key=s3_key, UploadId=upload_id
        )
        raise RuntimeError(f"S3 MultiPart Upload completion failed: {e}")


class HDAError(Exception):
    pass


class ConfigurationError(HDAError):
    pass


class RequestFailedError(HDAError):
    pass


class DownloadSizeError(HDAError):
    pass


class QuotaReachedError(HDAError):
    pass


class S3InitializeError(HDAError):
    pass


class Paginator:
    """A class to iterate over paginated results, following
    the HDA specification."""

    def __init__(self, request):
        self.request = request
        self.returned = 0

    def yield_result(self, page, limit=None):
        for feat in page["features"]:
            self.returned += 1
            if limit is not None and self.returned > limit:
                return
            yield feat

    def make_request(self, query):
        if self.request_type == RequestType.GET:
            return self.request(self.action, **query)
        elif self.request_type == RequestType.POST:
            return self.request(query, self.action)

    def run(self, *, query=None, limit=None, items_per_page=100):
        if query is None:
            query = {}

        params = {
            "startIndex": 0,
            "itemsPerPage": items_per_page,
        }
        query.update(params)
        page = self.make_request(query)
        yield from self.yield_result(page, limit)

        prop = page["properties"]
        while prop["startIndex"] < prop["totalResults"]:
            if self.returned >= prop["totalResults"]:
                return

            if limit is not None and self.returned > limit:
                return

            params["startIndex"] = prop["startIndex"] + items_per_page
            query.update(params)
            page = self.make_request(query)
            prop = page["properties"]
            yield from self.yield_result(page, limit)


class SearchPaginator(Paginator):
    action = "dataaccess/search"
    request_type = RequestType.POST


class DatasetPaginator(Paginator):
    action = "datasets"
    request_type = RequestType.GET


class DataOrderRequest:
    """Runner class for a data order request.
    A data order request is performed in order to retrieve actual files
    for a given result returned in the data request phase.
    """

    action = "dataaccess/download"

    def __init__(self, client):
        self.get = client.get
        self.head = client.head
        self.post = client.post
        self.sleep_max = client.sleep_max

    def run(self, query):
        result = self.post(query, self.action)
        download_id = result["download_id"]

        sleep = 1
        status = "started"
        while status != "completed":
            if status == "failed":
                raise RequestFailedError(result["message"])
            assert status in ["started", "running"]
            logger.debug("Sleeping %s seconds", sleep)
            time.sleep(sleep)
            response = self.head(self.action, download_id)
            if response.status_code == 200:
                status = "completed"
            elif response.status_code == 202:
                status = "running"
            else:
                status = "failed"
            sleep *= 1.1
            if sleep > self.sleep_max:
                sleep = self.sleep_max

        return download_id


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
    :param dataset: The dataset identifier.
    :type dataset: string
    """

    def __init__(self, client, results, dataset):
        self.client = client
        self.stream = client.stream
        self.results = results
        self.dataset = dataset
        self.volume = self.__sum(results)

    def __sum(self, results):
        sum_ = 0
        for r in results:
            prop = r.get("properties", {})
            size = prop.get("size", 0)
            if size == "ND":
                sum_ = "ND"
                break
            else:
                sum_ += size

        return sum_

    def __repr__(self):
        return "SearchResults[items=%s,volume=%s]" % (
            len(self),
            bytes_to_string(self.volume),
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
            client=self.client, results=self.results[index], dataset=self.dataset
        )
        return instance

    def _download(
        self,
        result,
        download_dir: str = ".",
        force=False,
        to_s3=False,
        s3_bucket=None,
        s3_key_prefix="",
        s3_endpoint=None,
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_verify_ssl=True,
    ):
        if (
            not to_s3
            and "properties" in result
            and "location" in result["properties"]
            and "size" in result["properties"]
        ):
            filename = os.path.basename(result["properties"]["location"])
            size = result["properties"]["size"]
            outfile = os.path.join(download_dir, filename)
            if os.path.exists(outfile):
                outfile_size = os.stat(outfile).st_size

                if size == outfile_size:
                    logger.debug(
                        "File {} already exists and has the expected size {}".format(
                            outfile, size
                        )
                    )
                if force:
                    logger.debug("Downloading anyway because force keyword is set")
                else:
                    logger.debug("Skipping download, use force=True to download anyway")
                    return

        self.client.accept_tac(self.dataset)

        download_id = self._get_download_id(result)
        self.stream(
            download_id,
            result["properties"]["size"],
            download_dir,
            force=force,
            to_s3=to_s3,
            s3_bucket=s3_bucket,
            s3_key_prefix=s3_key_prefix,
            s3_endpoint=s3_endpoint,
            s3_access_key_id=s3_access_key_id,
            s3_secret_access_key=s3_secret_access_key,
            s3_verify_ssl=s3_verify_ssl,
        )

    def _get_download_id(self, result):
        query = {
            "dataset_id": self.dataset,
            "product_id": result["id"],
            "location": result["properties"]["location"],
        }
        return DataOrderRequest(self.client).run(query)

    def get_download_urls(self, limit: Optional[int] = None):
        """Utility function to return the list of final download URLs.
        Useful in the context of the Serverless Functions service.
        If the list of results is long, it might take a long time.
        In that case, either subset the results or set a value for `limit`.
        """

        def build_url(result):
            download_id = self._get_download_id(result)
            return self.client.full_url(*[f"dataaccess/download/{download_id}"])

        if limit is not None:
            results = self.results[:limit]
        else:
            results = self.results

        return [build_url(r) for r in results]

    def download(
        self,
        download_dir: str = ".",
        force=False,
        *,
        to_s3=False,
        s3_bucket=None,
        s3_key_prefix="",
        s3_endpoint=None,
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_verify_ssl=True,
    ):
        """Downloads the results into the given download directory or S3 bucket.

        The process is executed concurrently using :py:attr:`hda.api.Client.max_workers` threads.
        """
        tasks = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.client.max_workers
        ) as executor:
            for result in self.results:
                future = executor.submit(
                    self._download,
                    result,
                    download_dir,
                    force,
                    to_s3,
                    s3_bucket,
                    s3_key_prefix,
                    s3_endpoint,
                    s3_access_key_id,
                    s3_secret_access_key,
                    s3_verify_ssl,
                )
                tasks.append(future)

            for future in concurrent.futures.as_completed(tasks):
                try:
                    result = future.result()
                    logger.info(f"Successfully downloaded: {result}")
                except Exception as exc:
                    logger.error(f"Download task failed: {exc}")


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
        verify=True,
        path=None,
    ):
        credentials = {"user": None, "password": None}

        dotrc = path or os.environ.get("HDA_RC", os.path.expanduser("~/.hdarc"))

        if os.path.isfile(dotrc):
            config = read_config(dotrc)

            for key in credentials.keys():
                if config.get(key):
                    credentials[key] = config.get(key)

        if user is not None:
            credentials["user"] = user

        if password is not None:
            credentials["password"] = password

        if credentials["user"] is None or credentials["password"] is None:
            raise ConfigurationError("Missing or incomplete configuration")

        self.url = url or BROKER_URL
        self.user = credentials["user"]
        self.password = credentials["password"]
        self.verify = verify


class Client:
    """HTTP client to request data from the WEkEO HDA API.

    :param config: A :class:`hda.api.Configuration` instance.
        By default `None` is passed, which means that a `$HOME/.hdarc`
        configuration file will be read.
    :type config: class:`hda.api.Configuration`
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
        timeout=None,
        retry_max=500,
        sleep_max=120,
        progress=True,
        max_workers=2,
    ):
        self.config = config or Configuration()
        self.timeout = timeout
        self.sleep_max = sleep_max
        self.retry_max = retry_max
        self.progress = progress
        self.max_workers = max_workers

        self._session = None
        self._access_token = None
        self._refresh_token = None
        self._token_expiration = None
        self._tqdm_position = cycle(range(self.max_workers))

        logger.debug(
            "HDA %s",
            dict(
                url=self.config.url,
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

        base_url = self.config.url
        url_parts = self.config.url.split("/")
        if url_parts[-2] != "api" and url_parts[-1] != "v1":
            base_url = urljoin(self.config.url, "api/v1")

        full = "/".join([str(x) for x in [base_url] + list(args)])
        return full

    @property
    def token(self):
        """The access token to access the API."""
        now = int(time.time())

        def is_token_expired():
            return self._token_expiration is None or now > self._token_expiration

        if is_token_expired():
            logger.debug("====== Token expired, renewing")
            payload = self._get_token()
            self._access_token = payload["access_token"]
            self._refresh_token = payload["refresh_token"]
            self._token_expiration = now + payload["expires_in"]

        return self._access_token

    def _invalidate_token(self):
        self._token_expiration = None

    def _get_token(self):
        """Requests a new access token using the configured credentials.

        :return: A valid access token.
        :rtype: str
        """

        def get_new_token():
            data = {
                "username": self.config.user,
                "password": self.config.password,
            }
            return requests.post(
                urljoin(self.config.url, "gettoken"),
                json=data,
                verify=self.config.verify,
            )

        def refresh_token():
            return requests.post(
                urljoin(self.config.url, "refreshtoken"),
                data={"refresh_token": self._refresh_token},
                verify=self.config.verify,
            )

        if self._refresh_token is not None:
            r = refresh_token()
            if r.status_code in (requests.codes.forbidden, requests.codes.bad_request):
                r = get_new_token()
        else:
            r = get_new_token()

        return r.json()

    def accept_tac(self, dataset_id):
        """Implicitly accept the terms and conditions of the service."""
        result = self.dataset(dataset_id)
        tacs = result["terms"]
        for tac in tacs:
            logger.debug(f"Accepting {tac}")
            url = f"termsaccepted/{tac}"
            self.put({"accepted": True}, url)

    @property
    def session(self):
        """The `requests` library session object, with the attached authentication."""
        if self._session is None:
            self._session = requests.Session()
        self._attach_auth()
        return self._session

    def _attach_auth(self):
        self._session.headers = {"Authorization": f"Bearer {self.token}"}
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
                    elif r.status_code == requests.codes.too_many_requests:
                        msg = build_quota_hit_message(r)
                        logger.warning(msg)
                        raise QuotaReachedError(msg)

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

    def search(self, query, limit=None):
        """Submits a search request with the given query.

        :param query: The JSON object representing the query.
        :type query: json

        :param limit: The maximum number of results to return.
            Set to None to return all results (default)
        :type limit: int

        :return: An :class:`hda.api.SearchResults` instance
        """
        # Users can pass in a query in v1 format and we try to convert it
        # into the new one. If the query is already in v2 format, this is
        # a no-op.
        # This might be removed in future version.
        query = convert(query)
        assert "dataset_id" in query, "Missing dataset_id, check your query"
        self.accept_tac(query["dataset_id"])
        results = SearchPaginator(self.post).run(query=query, limit=limit)
        return SearchResults(self, list(results), query["dataset_id"])

    def datasets(self, limit=None):
        """Returns the full list of available datasets.
        Each element of the list is a JSON object that includes
        the abstract, the dataset ID and other properties.

        :param limit: The maximum number of results to return.
            Set to None to return all results (default)
        :type limit: int
        """
        return list(DatasetPaginator(self.get).run(limit=limit))

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
        response = self.get("dataaccess/queryable", dataset_id)
        # Remove extra information only useful on the WEkEO UI
        if "constraints" in response:
            del response["constraints"]
        return response

    def get(self, *args, **kwargs):
        """Submits a GET request.

        :param args: The list of URL parts.
        :type args: list

        :return: A response object
        """
        full = self.full_url(*args)
        logger.debug("===> GET %s", full)

        r = self.robust(self.session.get)(
            full, params=kwargs, verify=self.config.verify, timeout=self.timeout
        )
        r.raise_for_status()
        result = r.json()
        logger.debug("<=== %s", shorten(result))
        return result

    def head(self, *args):
        """Submits a HEAD request.

        :param args: The list of URL parts.
        :type args: list

        :return: A response object
        """
        full = self.full_url(*args)
        logger.debug("===> HEAD %s", full)

        r = self.robust(self.session.head)(
            full, verify=self.config.verify, timeout=self.timeout
        )
        r.raise_for_status()
        logger.debug("<=== %s", r)
        return r

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
        res = self.robust(self.session.post)(
            full, json=message, verify=self.config.verify, timeout=self.timeout
        )
        res.raise_for_status()
        result = res.json()
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

        r = self.robust(self.session.put)(
            full, json=message, verify=self.config.verify, timeout=self.timeout
        )
        r.raise_for_status()
        return r

    def _stream_to_local_file(
        self,
        response: requests.Response,
        outfile: str,
        mode: str,
        current_total: int,
        content_size: Optional[int],
    ) -> int:
        """Streams the response content to a local file."""
        downloaded_in_session = 0

        with tqdm(
            total=content_size,
            unit_scale=True,
            unit_divisor=1024,
            unit="B",
            disable=not self.progress,
            leave=False,
            position=next(self._tqdm_position),
            initial=current_total,
        ) as pbar:
            with open(outfile, mode) as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        chunk_len = len(chunk)
                        downloaded_in_session += chunk_len
                        pbar.update(chunk_len)

        return downloaded_in_session

    def _stream_to_s3(
        self,
        response: requests.Response,
        s3_client: Any,
        s3_bucket: str,
        s3_key: str,
        content_size: Optional[int],
    ) -> int:
        """
        Streams the response content directly to S3 using MultiPart Upload (MPU).
        """
        downloaded_in_session = 0
        part_number = 1
        parts_uploaded = []
        current_part_buffer = io.BytesIO()
        # Initiate multipart upload
        try:
            response = s3_client.create_multipart_upload(
                Bucket=s3_bucket,
                Key=s3_key,
            )
            upload_id = response["UploadId"]
            logger.debug(f"Initiated S3 MultiPart Upload with ID: {upload_id}")
        except Exception as e:
            raise S3InitializeError(f"S3 MultiPart Upload initiation failed: {e}")

        with tqdm(
            total=content_size,
            unit_scale=True,
            unit_divisor=1024,
            unit="B",
            disable=not self.progress,
            leave=False,
            position=next(self._tqdm_position),
        ) as pbar:
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        current_part_buffer.write(chunk)
                        chunk_len = len(chunk)
                        downloaded_in_session += chunk_len
                        pbar.update(chunk_len)

                        # Check if the buffer is large enough for a part
                        if current_part_buffer.tell() >= S3_MIN_PART_SIZE:
                            part_data = current_part_buffer.getvalue()

                            upload_response = s3_client.upload_part(
                                Bucket=s3_bucket,
                                Key=s3_key,
                                UploadId=upload_id,
                                PartNumber=part_number,
                                Body=part_data,
                            )

                            # Store ETag for completion
                            parts_uploaded.append(
                                {
                                    "PartNumber": part_number,
                                    "ETag": upload_response["ETag"],
                                }
                            )

                            current_part_buffer = io.BytesIO()
                            part_number += 1

                # Upload remaining part
                if current_part_buffer.tell() > 0:
                    part_data = current_part_buffer.getvalue()
                    upload_response = s3_client.upload_part(
                        Bucket=s3_bucket,
                        Key=s3_key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=part_data,
                    )
                    parts_uploaded.append(
                        {"PartNumber": part_number, "ETag": upload_response["ETag"]}
                    )

                # Call complete
                complete_s3_upload(
                    s3_client, s3_bucket, s3_key, upload_id, parts_uploaded
                )

            except Exception as e:
                # Abort on any failure to prevent orphaned parts
                logger.error(f"Error during S3 stream. Aborting MPU: {upload_id}")
                s3_client.abort_multipart_upload(
                    Bucket=s3_bucket, Key=s3_key, UploadId=upload_id
                )
                raise RuntimeError(f"S3 stream failed: {e}")

        return downloaded_in_session

    def _handle_resume_logic(
        self,
        total_downloaded: int,
        content_size: Optional[int],
        outfile: str,
        sleep_delay: float,
    ) -> Tuple[int, str, float, Dict[str, str]]:
        """Handles logging, sleeping, and setting headers for download resumption.
        Return:
        - the downloaded size
        - the file opening mode
        - the new sleep_delay
        - the HTTP headers
        """

        logger.error(
            f"Download incomplete, downloaded {total_downloaded} byte(s) out of {content_size}"
        )

        logger.warning(f"Sleeping {sleep_delay} seconds")
        time.sleep(sleep_delay)

        # Update state for next attempt
        mode = "ab"  # Append mode
        total_downloaded = os.path.getsize(outfile)
        sleep_delay *= 1.5
        if sleep_delay > self.sleep_max:
            sleep_delay = self.sleep_max

        headers = {"Range": "bytes=%d-" % total_downloaded}
        logger.warning("Resuming download at byte %s" % (total_downloaded,))

        return total_downloaded, mode, sleep_delay, headers

    def _finalize_download(
        self, total_downloaded: int, content_size: Optional[int], start_time: float
    ) -> None:
        """Performs final size checks and logs the download rate."""
        content_size = 0 if content_size is None else content_size
        if total_downloaded > content_size:
            logger.warning(
                "Oops, downloaded %s byte(s), was supposed to be %s (extra %s)"
                % (total_downloaded, content_size, total_downloaded - content_size)
            )

        elapsed = time.time() - start_time
        if elapsed:
            # Use content_size for rate calculation if available, otherwise total_downloaded
            rate_size = content_size if content_size is not None else total_downloaded
            logger.info(f"Download rate {bytes_to_string(int(rate_size / elapsed))}/s")

    def stream(
        self,
        download_id: str,
        size: int,
        download_dir: str = ".",
        force: bool = False,
        *,
        to_s3: bool = False,
        s3_bucket: Optional[str] = None,
        s3_key_prefix: str = "",
        s3_endpoint: Optional[str] = None,
        s3_access_key_id: Optional[str] = None,
        s3_secret_access_key: Optional[str] = None,
        s3_verify_ssl=True,
    ):
        """Streams the given URL into the specified download directory or S3 bucket.
        Usually, this is not called directly but through the
        :py:meth:`~hda.api.Client.download` method.

        :param download_id: The download id as returned by the search API.
        :type download_dir: str
        :param size: The expected size of the resource.
        :type size: int
        :param download_dir: The directory into which the resource must be downloaded.
        :type download_dir: str, optional
        :param force: Whether to override the product if a local file already exists.
        :type force: bool, optional
        :param to_s3: Whether to download the product directly to S3 (needs optional dependencies).
        :type s3: bool, optional
        :param s3_bucket: The S3 bucket to stream the product to.
        :type s3_bucket: str
        :param s3_endpoint: A custom endpoint when using MinIO or other S3-like service.
        :type s3_endpoint: str, optional
        :param s3_access_key_id: The access key to S3. Overrides the AWS Credentials file.
        :type s3_access_key_id: str, optional
        :param s3_secret_access_key: The secrect access key to S3. Overrides the AWS Credentials file.
        :type s3_secret_access_key: str, optional
        :param s3_verify_ssl: Whether to verify the SSL Certificate.
        :type s3_verify_ssl: bool
        """
        # Set loop variables
        full_url = self.full_url(*[f"dataaccess/download/{download_id}"])
        start_time = time.time()
        mode = "wb"
        total_downloaded = 0
        sleep_delay = 10.0
        tries = 0
        headers = None

        # S3 Setup
        s3_client = None
        if to_s3:
            s3_client = init_s3_client(
                s3_bucket,
                s3_endpoint,
                s3_access_key_id,
                s3_secret_access_key,
                s3_verify_ssl,
            )
            s3_key = None  # Will be set after first request
        else:
            download_dir = os.path.expanduser(download_dir)
            os.makedirs(download_dir, exist_ok=True)

        logger.info(f"Downloading {full_url} ({bytes_to_string(size)})")

        while tries < self.retry_max:
            response = self.robust(self.session.get)(
                full_url,
                stream=True,
                verify=self.config.verify,
                headers=headers,
                timeout=self.timeout,
            )
            try:
                response.raise_for_status()

                logger.debug("Headers: %s", response.headers)
                filename = get_filename(response, download_id)
                content_size = get_content_size(response, size)

                # Local file precheck
                if not to_s3:
                    outfile = os.path.join(download_dir, filename)

                    # XXX EXtract this block
                    if content_size is not None and os.path.exists(outfile):
                        outfile_size = os.stat(outfile).st_size
                        if content_size == outfile_size:
                            logger.debug(
                                f"File {outfile_size} already exists and has the expected size {outfile_size}"
                            )
                            if force:
                                logger.debug(
                                    "Downloading anyway because force keyword is set"
                                )
                            else:
                                logger.debug(
                                    "Skipping download, use force=True to download anyway"
                                )
                                return filename

                # S3 key finalized
                if to_s3 and s3_key is None:
                    s3_key = os.path.join(s3_key_prefix, filename).lstrip("/")

                # Finally, streaming
                downloaded_in_session = 0
                if to_s3:
                    downloaded_in_session = self._stream_to_s3(
                        response, s3_client, s3_bucket, s3_key, content_size
                    )
                else:
                    downloaded_in_session = self._stream_to_local_file(
                        response, outfile, mode, total_downloaded, content_size
                    )

                total_downloaded += downloaded_in_session

                if content_size is None or total_downloaded >= content_size:
                    size = content_size  # Use the accurate size for final checks
                    break

            except (
                requests.exceptions.RequestException,
                RuntimeError,
                DownloadSizeError,
            ) as e:
                logger.error("Download interrupted: %s" % (e,))
                print("Download interrupted: %s" % (e,))
                if tries >= self.retry_max:
                    # If this was the last attempt, re-raise the error.
                    raise

                # For connection failures (not partial download), we sleep and retry.
                logger.warning("Sleeping %s seconds before retry" % (sleep_delay,))
                time.sleep(sleep_delay)
                sleep_delay *= 1.5
                if sleep_delay > self.sleep_max:
                    sleep_delay = self.sleep_max
                continue
            except S3InitializeError as e:
                # This is not recovable, exit right away
                logger.error("Download interrupted: %s" % (e,))
                print("Download interrupted: %s" % (e,))
                break
            finally:
                response.close()

            if not to_s3:
                # Only need resume logic for local files
                total_downloaded, mode, sleep_delay, headers = (
                    self._handle_resume_logic(
                        total_downloaded, content_size, outfile, sleep_delay
                    )
                )
            else:
                # S3 stream is non-resumable at the moment
                logger.warning("S3 download was incomplete. Retrying from start.")

        self._finalize_download(total_downloaded, size, start_time)

        if total_downloaded < size:
            # Final check failure, should only happen if retry_max was hit
            raise DownloadSizeError(
                f"Download failed: {total_downloaded} byte(s) out of {size} (missing {size - total_downloaded})"
            )

        if to_s3:
            return f"s3://{s3_bucket}/{s3_key}"

        return filename
