"""Bounded retry for read-only public-source downloads; permanent failures fail fast."""

import http.client
import time
import urllib.error
import urllib.request


def get(url: str, timeout: int = 60) -> bytes:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "alphaforge-probe/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
        ):
            if attempt == 2:
                raise
        time.sleep(2**attempt)
    raise AssertionError("Unreachable")
