from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

ISO_PATTERN = r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?Z"
INTERVAL_PATTERN = rf"^{ISO_PATTERN}(?:/{ISO_PATTERN})?$"

INTERVAL_REGEX = re.compile(INTERVAL_PATTERN)


def validate_interval(interval: str | None) -> bool:
    if interval is not None:
        return bool(INTERVAL_REGEX.match(interval))

    return True


class Page:
    def __init__(self, response, client, items_key, limit = 20):
        self.items = response.get(items_key, [])
        self.total_available = response.get("numberMatched")
        self.number_returned = response.get("numberReturned")
        self._links = response.get("links", [])
        self._client = client
        self._items_key = items_key
        self._limit = limit

    def __str__(self) -> str:
        return f"Page {self.current_page} of {self.total_pages}, {self.number_returned} items"

    def __repr__(self) -> str:
        return f"<Page(page={self.current_page}, total={self.total_pages})>"

    @property
    def current_page(self) -> int:
        """Extracts the page number from the 'self' link."""
        self_link = next((link["href"] for link in self._links if link["rel"] == "self"), "")
        query_params = parse_qs(urlparse(self_link).query)
        # Default to page 1 if the parameter isn't found
        return int(query_params.get("page", [1])[0])

    @property
    def total_pages(self) -> int:
        """Calculates total pages based. The default backend limit is 20."""
        if self.total_available == 0 or self.total_available is None:
            return 0
        return math.ceil(self.total_available / self._limit)

    @property
    def has_next(self) -> bool:
        return any(link["rel"] == "next" for link in self._links)

    def next_page(self) -> "Page":
        next_url = next(link["href"] for link in self._links if link["rel"] == "next")
        response = self._client.get(next_url)
        return Page(response, self._client, self._items_key)


class StacMixin:
    def __init__(self, client):
        self._client = client

    def get_info(self) -> dict:
        """Returns the Landing Page (root) metadata."""
        return self._client.get("stac/")

    def get_conformance(self) -> list[str]:
        """Returns the list of supported OGC/STAC features."""
        return self._client.get("stac/conformance/")

    def get_collections_page(self, page: int = 1) -> Page:
        """Iterates through all available collections (paginated)."""
        response = self._client.get(f"stac/collections/?page={page}")
        return Page(response, self._client, "collections")

    def get_collection(self, collection_id: str) -> dict:
        """Retrieves metadata for a specific collection."""
        return self._client.get(f"stac/collections/{quote(collection_id)}")

    def get_items_page(self, collection_id: str, limit: int = 20, page: int = 1) -> Page:
        """Iterates through items within a specific collection."""
        response = self._client.get(f"stac/collections/{quote(collection_id)}/items?page={page}&limit={limit}")
        return Page(response, self._client, "items", limit)

    def get_item(self, collection_id: str, item_id: str) -> dict:
        """Retrieves a single item from a collection."""
        return self._client.get(f"stac/collections/{quote(collection_id)}/items/{quote(item_id)}")

    def search(
        self,
        *,
        collections: list[str] | None = None,
        ids: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        interval: str | None = None,
        limit: int = 1,
        **kwargs,
    ) -> Any:
        """
        Cross-collection search.
        """
        keys = {
            "collections": collections,
            "ids": ids,
            "bbox": bbox,
            "datetime": interval,
            "limit": limit,
        }
        if not validate_interval(interval):
            raise ValueError("Bad interval format")

        payload = {}
        for key, param in keys.items():
            if param is not None:
                payload[key] = param

        payload.update(kwargs)
        return self._client.post(payload, "stac/search")
