"""KDD-27 bounded per-module HTTP/CPU measurements. No network calls.

Instruments urllib only inside the invoking thread via contextvars. Public
and read-only private requests are counted, never their URL query, header,
credentials, payload or response bodies. Untouched threads keep original IO.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import functools
import inspect
import json
import resource
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

ACTIVE = contextvars.ContextVar("kdd27_active_meter", default=None)
PATCH_LOCK = threading.RLock()
ORIGINAL = urllib.request.urlopen
MODULES = frozenset((
    "kraken_readonly", "kdd_saldi", "decision_desk", "ricerca_setup",
    "patrimonio_4tf", "flusso_spot", "binance_reference", "dossier_trade",
    "kdd_economic_sources", "kdd_economics", "kdd_network_defi",
    "kdd_capital_flow", "kdd_futures_flow", "studio_delta", "verifica_piani",
    "costi_spot", "mercati_spot", "kdd_drive_exchange", "kdd_bridge_g2"))


def source_module():
    frame = inspect.currentframe()
    try:
        frame = frame.f_back
        for _ in range(24):
            if frame is None:
                break
            name = frame.f_code.co_filename.rsplit("/", 1)[-1]
            if name.endswith(".py") and name[:-3] in MODULES:
                return name[:-3]
            frame = frame.f_back
    finally:
        del frame
    return "unclassified"


def provider(url):
    hostname = urllib.parse.urlsplit(url).hostname or "unknown"
    if hostname.endswith("kraken.com"):
        return "kraken"
    if hostname.endswith("binance.com"):
        return "binance"
    if "coingecko" in hostname:
        return "coingecko"
    if hostname.endswith("github.com") or hostname.endswith("githubusercontent.com"):
        return "github"
    if hostname.endswith("llama.fi"):
        return "defillama"
    return hostname[:64]


class ResponseMeter:
    def __init__(self, underlying, owner, meter):
        self.raw = underlying
        self.owner = owner
        self.meter = meter
    def __getattr__(self, name):
        return getattr(self.raw, name)
    def read(self, *args, **kwargs):
        started = time.monotonic()
        try:
            data = self.raw.read(*args, **kwargs)
        except BaseException:
            self.meter.count(self.owner, bytes_received=0, read_ms=(
                time.monotonic()-started)*1000, failed=True, requested=False)
            raise
        self.meter.count(self.owner, bytes_received=len(data), read_ms=(
            time.monotonic()-started)*1000, requested=False)
        return data
    def __enter__(self):
        self.raw.__enter__()
        return self
    def __exit__(self, *args):
        return self.raw.__exit__(*args)
    def __iter__(self):
        return iter(self.raw)


def traced_urlopen(*args, **kwargs):
    meter = ACTIVE.get()
    if meter is None:
        return ORIGINAL(*args, **kwargs)
    req = args[0] if args else kwargs.get("url")
    url = req.full_url if hasattr(req, "full_url") else str(req)
    label = source_module()
    source = provider(url)
    owner = (label, source)
    start = time.monotonic()
    try:
        res = ORIGINAL(*args, **kwargs)
    except BaseException as exc:
        meter.count(owner, requested=True, failed=True, connect_ms=(
            time.monotonic()-start)*1000)
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            retry = (exc.headers.get("Retry-After") if exc.headers else None)
            meter.throttle(source,retry)
        raise
    meter.count(owner, requested=True, connect_ms=(time.monotonic()-start)*1000)
    return ResponseMeter(res, owner, meter)


class Telemetry:
    def __init__(self):
        self.rows = {}
        self.total = {"calls": 0, "bytes": 0, "errors": 0}
        self.rate_limits = {}
        self.token = None

    def throttle(self, provider, retry_after):
        # A provider Retry-After takes precedence; without it the local
        # coordinator applies bounded backoff. No secret/URL is stored.
        seconds=None
        if isinstance(retry_after,str) and retry_after.strip().isdigit():
            seconds=int(retry_after.strip())
            if not 1<=seconds<=86400:
                seconds=None
        self.rate_limits[provider]=seconds


    def count(self, owner, *, requested=False, bytes_received=0,
              failed=False, connect_ms=0, read_ms=0):
        key = "|".join(owner)
        row = self.rows.setdefault(key, {"module": owner[0], "provider": owner[1],
                                         "calls": 0, "bytes": 0, "errors": 0,
                                         "http_ms": 0.0})
        if requested:
            row["calls"] += 1
            self.total["calls"] += 1
        if bytes_received:
            row["bytes"] += bytes_received
            self.total["bytes"] += bytes_received
        if failed:
            row["errors"] += 1
            self.total["errors"] += 1
        row["http_ms"] += connect_ms + read_ms

    def __enter__(self):
        PATCH_LOCK.acquire()
        self._previous_urlopen = urllib.request.urlopen
        urllib.request.urlopen = traced_urlopen
        self.token = ACTIVE.set(self)
        self.started_wall = time.monotonic()
        self.started_cpu = time.process_time()
        self.started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        return self

    def __exit__(self, *exc):
        self.ended_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        self.elapsed_s = time.monotonic()-self.started_wall
        self.cpu_s = time.process_time()-self.started_cpu
        ACTIVE.reset(self.token)
        urllib.request.urlopen = self._previous_urlopen
        PATCH_LOCK.release()
        return False

    def report(self):
        return {
            "schema": "kdd27_telemetry_v001",
            "started_utc": self.started_utc,
            "ended_utc": self.ended_utc,
            "duration_s": round(self.elapsed_s, 4),
            "cpu_process_s": round(self.cpu_s, 4),
            "rss_hwm_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "total": self.total,
            "sources": sorted(self.rows.values(),key=lambda row:(row["module"],row["provider"])),
            "rate_limited":[{"provider":name,"retry_after_s":value}
                            for name,value in sorted(self.rate_limits.items())],
            "coverage": "HTTP urllib only; calls made by other libraries are not counted; "
                        "RSS is process high-water, not interval delta",
        }
