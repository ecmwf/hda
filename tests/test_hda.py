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
def test_hda_1():
    c = Client()

    r = {
        "dataset_id": "EO:CLMS:DAT:CLMS_GLOBAL_DMP_1KM_V2_10DAILY_NETCDF",
    }

    matches = c.search(r, limit=10)
    print(matches)
    assert len(matches.results) == 10, matches


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_2():
    c = Client()

    r = {
        "dataset_id": "EO:CLMS:DAT:CLMS_GLOBAL_DMP_1KM_V2_10DAILY_NETCDF",
        "start": "2019-02-27T08:29:45.644Z",
        "end": "2019-03-27T08:29:45.644Z",
    }

    matches = c.search(r)
    assert len(matches.results) > 0, matches
    matches[0].download()
