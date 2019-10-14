#!/usr/bin/env python3
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from hda import Client

c = Client(debug=True)

queries = sys.argv[1:]

if not queries:
    queries = ["sentinel.json"]


for q in queries:
    with open(q) as f:
        query = json.loads(f.read())

    matches = c.search(query)
    print(matches)
    matches.download()
