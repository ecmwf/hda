# Copyright 2021 European Centre for Medium-Range Weather Forecasts (ECMWF)
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

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from hda import Client, Configuration
from hda.api import S3InitializeError, SearchResults

NO_HDARC = not os.path.exists(os.path.expanduser("~/.hdarc")) and (
    "HDA_USER" not in os.environ or "HDA_PASSWORD" not in os.environ
)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

CUSTOM_HDRRC = os.path.join(BASE_DIR, "tests/custom_config.txt")


@pytest.fixture
def fresh_hda_api():
    from importlib import reload

    import hda.api

    return reload(hda.api)


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_custom_url_config():
    config = Configuration(url="TEST")
    c = Client(config=config)
    assert c.config.url == "TEST"


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_custom_user_config():
    config = Configuration(user="TEST")
    c = Client(config=config)
    assert c.config.user == "TEST"


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_custom_password_config():
    config = Configuration(password="TEST")
    c = Client(config=config)
    assert c.config.password == "TEST"


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_custom_path_config():
    config = Configuration(user=None, password=None, path=CUSTOM_HDRRC)
    c = Client(config=config)
    assert c.config.user == "TESTUSER"
    assert c.config.password == "TESTPASSWORD"


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_mixed_config():
    config = Configuration(user="TU", password="TP", path=CUSTOM_HDRRC)
    c = Client(config=config)
    assert c.config.user == "TU"
    assert c.config.password == "TP"


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_search_results_slicing():
    r = [
        {"id": 0, "properties": {"size": 10}},
        {"id": 1, "properties": {"size": 20}},
        {"id": 2, "properties": {"size": 30}},
        {"id": 3, "properties": {"size": 40}},
        {"id": 4, "properties": {"size": 50}},
    ]
    s = SearchResults(Client(), r, None)
    assert len(s[0]) == 1
    assert s[0].results[0] == r[0]
    assert s[0].volume == 10
    assert len(s[-1]) == 1
    assert s[-1].results[0] == r[-1]
    assert s[-1].volume == 50
    assert len(s[:]) == len(r)
    assert s[1:].volume == 140


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_e2e():
    c = Client()

    r = {
        # "dataset_id": "EO:CLMS:DAT:CLMS_GLOBAL_DMP_1KM_V2_10DAILY_NETCDF",
        "dataset_id": "EO:EUM:DAT:SENTINEL-3:OL_1_EFR___",
    }

    matches = c.search(r, limit=10)
    print(matches)
    assert len(matches.results) == 10, matches


def test_has_s3_true_when_boto3_present():
    # Ensure boto3 import works
    assert "boto3" in sys.modules or importlib.util.find_spec("boto3") is not None

    from hda.api import _HAS_S3

    assert _HAS_S3 is True


def test_has_s3_false_when_boto3_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)

    with patch("importlib.util.find_spec", return_value=None):
        importlib.invalidate_caches()
        # Force reload to retry imports
        from importlib import reload

        import hda.api

        reload(hda.api)

        assert hda.api._HAS_S3 is False


def test_download_s3_raises_importerror_when_missing_s3(monkeypatch, fresh_hda_api):
    monkeypatch.setattr(fresh_hda_api, "_HAS_S3", False)

    config = MagicMock()
    config.url = "https://fake-hda"
    config.verify = True

    client = fresh_hda_api.Client(config=config)
    client._attach_auth = MagicMock()

    with pytest.raises(ImportError):
        client.stream(
            download_id="abc",
            size=100,
            download_dir=".",
            to_s3=True,
            s3_bucket="my-bucket",
        )


def test_s3_upload_called(monkeypatch, fresh_hda_api):
    monkeypatch.setattr(fresh_hda_api, "_HAS_S3", True)

    config = MagicMock()
    config.url = "https://fake-hda"
    config.verify = True

    client = fresh_hda_api.Client(config=config)
    client._attach_auth = MagicMock()

    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [b"abc", b"def"]
    mock_resp.headers = {"Content-Length": "6"}

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp
    monkeypatch.setattr(client, "_session", mock_session)

    s3_client_mock = MagicMock()
    monkeypatch.setattr(fresh_hda_api.boto3, "client", lambda *_, **__: s3_client_mock)
    s3_client_mock.create_multipart_upload.side_effect = S3InitializeError()

    with pytest.raises(fresh_hda_api.DownloadSizeError):
        client.stream(
            download_id="id123",
            size=6,
            to_s3=True,
            s3_bucket="bucket",
            s3_key_prefix="test/",
        )

    s3_client_mock.create_multipart_upload.assert_called_once()


def test_quota_reached(monkeypatch, fresh_hda_api):
    mock_response = MagicMock(status_code=429)
    mock_response.headers = {
        "X-Quota-Limit": "100",
        "X-Quota-Remaining": "75",
        "X-Quota-Reset": "1700000000",
    }

    config = Configuration(user="TU", password="TP")
    client = fresh_hda_api.Client(config=config)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    monkeypatch.setattr(client, "_session", mock_session)
    client._attach_auth = MagicMock()

    with pytest.raises(fresh_hda_api.QuotaReachedError):
        client.search({"dataset_id": "dummy"})
