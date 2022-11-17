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

import os
from unittest.mock import patch

import pytest

from hda import Client, Configuration
from hda.api import SearchResults

NO_HDARC = not os.path.exists(os.path.expanduser("~/.hdarc")) and (
    "HDA_USER" not in os.environ or "HDA_PASSWORD" not in os.environ
)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

CUSTOM_HDRRC = os.path.join(BASE_DIR, "tests/custom_config.txt")


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
    config = Configuration(path=CUSTOM_HDRRC)
    c = Client(config=config)
    assert c.config.url == "TESTURL"
    assert c.config.user == "TESTUSER"
    assert c.config.password == "TESTPASSWORD"


def test_search_results_slicing():
    r = [
        {"id": 0, "size": 10},
        {"id": 1, "size": 20},
        {"id": 2, "size": 30},
        {"id": 3, "size": 40},
        {"id": 4, "size": 50},
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


class Logger:
    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def test_custom_logger():
    with patch.object(Logger, "info", return_value=None) as mock_info:
        c = Client(logger=Logger())
        c.info("message")
        mock_info.assert_called_with("message")

    with patch.object(Logger, "debug", return_value=None) as mock_debug:
        c = Client(logger=Logger())
        c.debug("message")
        mock_debug.assert_called_with("message")

    with patch.object(Logger, "warning", return_value=None) as mock_warning:
        c = Client(logger=Logger())
        c.warning("message")
        mock_warning.assert_called_with("message")

    with patch.object(Logger, "error", return_value=None) as mock_error:
        c = Client(logger=Logger())
        c.error("message")
        mock_error.assert_called_with("message")


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_1():
    c = Client()

    r = {
        "datasetId": "EO:CLMS:DAT:CGLS_CONTINENTS_WB_V1_1KM",
        "dateRangeSelectValues": [
            {
                "name": "dtrange",
                "start": "2020-04-11T00:00:00.000Z",
                "end": "2020-05-21T00:00:00.000Z",
            }
        ],
    }

    matches = c.search(r)
    print(matches)
    assert len(matches.results) > 0, matches
    # Too large to download
    # matches.download()


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_2():
    c = Client()

    r = {
        "datasetId": "EO:ECMWF:DAT:CAMS_EUROPE_AIR_QUALITY_REANALYSES",
        "multiStringSelectValues": [
            {"name": "type", "value": ["validated_reanalysis"]},
            {"name": "variable", "value": ["ammonia"]},
            {"name": "model", "value": ["chimere"]},
            {"name": "level", "value": ["0"]},
            {"name": "month", "value": ["01"]},
            {"name": "year", "value": ["2018"]},
        ],
        "stringChoiceValues": [
            {"name": "format", "value": "tgz"},
        ],
    }

    matches = c.search(r)
    assert len(matches.results) == 1, matches
    matches.download()
