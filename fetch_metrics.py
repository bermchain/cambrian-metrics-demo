#!/usr/bin/env python3
"""Fetch the five Cambrian coverage metrics and write metrics.json.

Reads the API key from the CAMBRIAN_API_KEY environment variable (never stored in the repo).
Keeps per-source results in state.json so a failed call falls back to the last good value.
Set ONLY=lending_supply,weekly_volume (comma separated) to run a subset while testing.
"""
import json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://api.cambrian.org"
KEY = os.environ["CAMBRIAN_API_KEY"].strip()
EVM_CHAINS = {1: "Ethereum", 8453: "Base", 42161: "Arbitrum", 56: "BNB Chain", 4663: "Robinhood Chain"}
NATIVE = {  # wrapped native token per chain, used for the volume floor
    1: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    8453: "0x4200000000000000000000000000000000000006",
    42161: "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
    56: "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
    4663: "0x0bd7d308f8e1639fab988df18a8011f41eacad73",
}
SOL = "So11111111111111111111111111111111111111112"
SOLANA_OFFSET_CAP = 100_000
EVM_OFFSET_CAP = 100_000_000


class BadRequest(Exception):
    pass


def get(path, timeout=180, tries=5):
    """GET a Cambrian endpoint and return rows as a list of dicts."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers={"X-API-Key": KEY})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            d = d[0] if isinstance(d, list) else d
            cols = [c["name"] for c in d.get("columns", [])]
            return [dict(zip(cols, row)) for row in d.get("data", [])]
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise BadRequest(path)
            last = e
        except Exception as e:  # timeouts, connection resets
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{path}: {last}")


def count_rows(path, cap):
    """Count rows of a list endpoint that has no total: binary-search the offset with limit=1."""
    sep = "&" if "?" in path else "?"
    has = lambda off: len(get(f"{path}{sep}limit=1&offset={off}")) > 0
    if not has(0):
        return 0
    lo, hi = 0, 1
    while hi <= cap and has(hi):
        lo, hi = hi, hi * 4
    if hi > cap:
        if has(cap):
            return cap  # capped: a floor, not the true count
        hi = cap
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if has(mid):
            lo = mid
        else:
            hi = mid
    return lo + 1


def run_sources(sources, state, workers=5):
    """sources: {name: callable}. Returns {name: value}, falling back to state on failure."""
    out, stale = {}, []

    def one(item):
        name, fn = item
        try:
            return name, fn(), None
        except BadRequest:
            return name, 0, None  # endpoint not available for this chain
        except Exception as e:
            return name, None, str(e)

    with ThreadPoolExecutor(workers) as ex:
        for name, val, err in ex.map(one, sources.items()):
            if err is None:
                out[name] = state[name] = val
            elif name in state:
                out[name] = state[name]
                stale.append(name)
                print(f"WARN stale {name}: {err}", file=sys.stderr)
            else:
                stale.append(name)
                print(f"WARN missing {name}: {err}", file=sys.stderr)
    return out, stale


def pool_sources():
    s = {}
    for ch in EVM_CHAINS:
        for dex in ("uniswap", "pancake", "sushi", "alien"):
            p = f"/evm/{dex}/v3/pools?chain_id={ch}"
            s[f"pools:{dex}:{ch}"] = (lambda p=p: count_rows(p, EVM_OFFSET_CAP))
    s["pools:aero-v2:8453"] = lambda: count_rows("/evm/aero/v2/pools?chain_id=8453", EVM_OFFSET_CAP)
    s["pools:orca:solana"] = lambda: count_rows("/solana/orca/pools?dex=orca", SOLANA_OFFSET_CAP)
    s["pools:raydium-clmm:solana"] = lambda: count_rows("/solana/raydium-clmm/pools", SOLANA_OFFSET_CAP)
    s["pools:meteora-dlmm:solana"] = lambda: count_rows("/solana/meteora-dlmm/pools", SOLANA_OFFSET_CAP)
    return s


def token_sources():
    s = {f"tokens:{ch}": (lambda ch=ch: count_rows(f"/evm/tokens?chain_id={ch}", EVM_OFFSET_CAP)) for ch in EVM_CHAINS}
    s["tokens:solana"] = lambda: count_rows("/solana/tokens", SOLANA_OFFSET_CAP)
    return s


def lending_supply(ch):
    total, off = 0.0, 0
    while True:
        rows = get(f"/evm/lending/overview?chain_id={ch}&limit=10000&offset={off}")
        total += sum((r.get("supplyUsd") or 0) for r in rows)
        if len(rows) < 10000:
            return total
        off += 10000


def lending_count(ch):
    return sum(r["poolCount"] for r in get(f"/evm/lending/protocols?chain_id={ch}&limit=10000"))


def evm_volume_7d(ch):
    now = int(time.time())
    day0 = now - now % 86400  # start of today, UTC
    rows = get(f"/evm/ohlcv/token?chain_id={ch}&token_address={NATIVE[ch]}"
               f"&after_time={day0 - 8 * 86400}&before_time={now}&interval=1d&use_filter=true&limit=100")
    return sum((r["volumeBoughtUsd"] or 0) + (r["volumeSoldUsd"] or 0)
               for r in rows if day0 - 7 * 86400 <= r["unixTime"] < day0)


def solana_volume_7d():
    rows = get(f"/solana/trade-statistics?token_addresses={SOL}&timeframe=7d")
    return rows[0]["totalVolumeUSD"]


def floor_display(value, kind):
    """Round down and spell out the unit, e.g. 2.8 million+, $37 billion+, 15,000+."""
    if value is None:
        return "\u2014"
    if kind == "usd_b":
        return f"${int(value // 1e9)} billion+"
    if kind == "m1":  # one decimal, in millions, rounded down
        return f"{int(value // 1e5) / 10:g} million+"
    if kind == "m0":
        return f"{int(value // 1e6)} million+"
    if kind == "k":
        return f"{int(value // 1000) * 1000:,}+"
    return str(value)


GROUPS = {
    "lp_pools": ("LP pools indexed", "m1", pool_sources),
    "lending_supply": ("Lending supply tracked", "usd_b",
                       lambda: {f"supply:{ch}": (lambda ch=ch: lending_supply(ch)) for ch in EVM_CHAINS}),
    "weekly_volume": ("Weekly DEX volume", "usd_b",
                      lambda: {**{f"vol:{ch}": (lambda ch=ch: evm_volume_7d(ch)) for ch in EVM_CHAINS},
                               "vol:solana": solana_volume_7d}),
    "tokens": ("Tokens & tokenized stocks", "m0", token_sources),
    "lending_markets": ("Lending pools & vaults indexed", "k",
                        lambda: {f"lendcount:{ch}": (lambda ch=ch: lending_count(ch)) for ch in EVM_CHAINS}),
}


def main():
    state = {}
    if os.path.exists("state.json"):
        state = json.load(open("state.json"))
    only = [x for x in os.environ.get("ONLY", "").split(",") if x]
    metrics = []
    for mid, (label, kind, make) in GROUPS.items():
        if only and mid not in only:
            continue
        t = time.time()
        vals, stale = run_sources(make(), state)
        value = sum(vals.values()) if vals else None
        metrics.append({"id": mid, "label": label, "value": value,
                        "display": floor_display(value, kind), "stale_sources": stale})
        print(f"{mid}: {value} -> {floor_display(value, kind)} ({time.time() - t:.0f}s, stale={stale})")
    json.dump(state, open("state.json", "w"))
    json.dump({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "metrics": metrics},
              open("metrics.json", "w"), indent=1)


if __name__ == "__main__":
    main()
