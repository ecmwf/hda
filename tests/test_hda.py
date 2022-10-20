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

from hda import Client

NO_HDARC = not os.path.exists(os.path.expanduser("~/.hdarc")) and (
    "HDA_USER" not in os.environ or "HDA_PASSWORD" not in os.environ
)


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_1():
    c = Client(url="https://wekeo-broker.apps.mercator.dpi.wekeo.eu/databroker")

    r = {
        "datasetId": "EO:EUM:DAT:SENTINEL-3:OL_1_EFR___",
        "boundingBoxValues": [
            {
                "name": "bbox",
                "bbox": [
                    1.2653132076552462,
                    43.50759094045819,
                    1.575030022744999,
                    43.711525020845585,
                ],
            }
        ],
        "dateRangeSelectValues": [
            {
                "name": "end",
                "start": "2022-07-03T00:00:00.000Z",
                "end": "2022-07-04T00:00:00.000Z",
            }
        ],
        "stringChoiceValues": [
            {"name": "platformname", "value": "Sentinel-3"},
            {"name": "producttype", "value": "OL_1_EFR___"},
        ],
    }
    matches = c.search(r)
    print(matches)
    assert len(matches.results) > 0, matches
    # Too large to download
    # matches.download()


@pytest.mark.skipif(NO_HDARC, reason="No access to HDA")
def test_hda_2():
    c = Client(url="https://wekeo-broker.apps.mercator.dpi.wekeo.eu/databroker")

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
