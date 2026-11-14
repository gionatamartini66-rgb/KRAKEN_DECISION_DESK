"""KDD-17 G2: bounded public capital-flow observations, never wallet attribution.

One reusable producer for EVM, Solana, Sui, XRPL, NEAR and UTXO Bitcoin.
Observations describe sampled on-chain facts; labels are optional explorer metadata.
No Kraken address, private balance, signing, orders, paid API or API key.
"""
from __future__ import annotations
import datetime as dt
from decimal import Decimal, InvalidOperation
import re

UTC = dt.timezone.utc
SCHEMA = "kdd-capital-observatory-v001"
MAX_TARGETS = 5
MAX_PUBLIC_CALLS = 15  # extra HTTP requests at most, per normal refresh
MAX_CALLS_PER_TARGET = 6
MAX_HISTORY = 32  # bounded last public holder samples across target rotation
MAX_EVENTS = 8
MAX_HOLDERS = 10
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ETH_EXPLORER = "https://eth.blockscout.com"
HEX64 = re.compile(r"(?:0x)?[0-9a-fA-F]{64}\Z")
EVM = re.compile(r"0x[0-9a-fA-F]{40}\Z")
B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,88}\Z")
SUPPORTED = {"bitcoin", "ethereum", "bsc", "solana", "sui", "xrpl", "near", "avalanche"}


def _ts(value):
    if not isinstance(value, str):
        raise ValueError("timestamp absent")
    out = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if out.tzinfo is None:
        raise ValueError("timestamp without zone")
    return out.astimezone(UTC)


def _nat(value, bound=10**46):
    if type(value) is int:
        n = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,47}", value):
        n = int(value)
    else:
        raise ValueError("invalid unit integer")
    if not 0 <= n <= bound:
        raise ValueError("unit bound")
    return n


def _hex(value, limit=10**24):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
        raise ValueError("invalid hex quantity")
    n = int(value, 16)
    if n > limit:
        raise ValueError("hex bound")
    return n


def _rpc(fetch, url, method, params):
    data = fetch(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if (not isinstance(data, dict) or data.get("error") or
            data.get("id") != 1 or "result" not in data):
        raise ValueError("RPC response invalid")
    return data["result"]


def _quantity(value, decimals):
    raw = _nat(value)
    if type(decimals) is not int or not 0 <= decimals <= 30:
        raise ValueError("unknown token precision")
    return format(Decimal(raw) / (Decimal(10) ** decimals), "f")


def _tag(address):
    """An explorer's *explicit* public tag, not a guessed owner from size/ENS."""
    if not isinstance(address, dict):
        return {"stato": "ENTITA_NON_IDENTIFICATA"}
    tags = address.get("public_tags")
    if isinstance(tags, list):
        for tag in tags[:5]:
            if not isinstance(tag, dict):
                continue
            value = str(tag.get("label") or tag.get("name") or "")[:90]
            category_hint = " ".join(str(tag.get(field) or "")[:70] for field in
                                     ("label", "category", "type", "tag_type"))
            category = next((name for word,name in
                             (("exchange","EXCHANGE"), ("custod","CUSTODE"),
                              ("fund","FONDO"), ("treasury","TESORERIA"),
                              ("protocol","PROTOCOLLO"), ("market maker","MARKET_MAKER"))
                             if word in category_hint.lower()), None)
            if category is None and re.search(
                    r"\b(?:binance|coinbase|kraken|bitfinex|okx|bybit|kucoin|bitstamp|bitget|gate\.io)\b",
                    category_hint, re.I):
                category = "EXCHANGE"
            if category:
                return {"stato": "ETICHETTA_PUBBLICA", "classe": category,
                        "etichetta": value, "fonte": ETH_EXPLORER + "/api/v2/"}
    return {"stato": "ENTITA_NON_IDENTIFICATA"}


def _event(chain, asset_id, tx, sub, raw, decimals, source, block=None,
           stamp=None, origin=None, destination=None, event_type="TRASFERIMENTO",
           labels=None):
    return {"rete": chain, "asset_tecnico": asset_id,
            "tx": tx, "indice": str(sub), "blocco": block,
            "orario_utc": stamp, "unita_minima": str(_nat(raw)),
            "decimali": decimals, "quantita": _quantity(raw, decimals),
            "da": origin, "a": destination, "tipo": event_type,
            "attribuzione": labels or {"da": {"stato": "ENTITA_NON_IDENTIFICATA"},
                                       "a": {"stato": "ENTITA_NON_IDENTIFICATA"}},
            "fonte": source, "interpretazione": (
                "Possibile redistribuzione/custodia/OTC; deposito exchange non prova vendita"),
            "alternativa": "Movimento interno, ponte, liquidita o riorganizzazione del medesimo proprietario"}


def _top(events):
    seen = set()
    clean = []
    for item in events:
        key = (item["rete"], item["asset_tecnico"], item["tx"], item["indice"])
        if key in seen:
            continue
        seen.add(key)
        if _nat(item["unita_minima"]) > 0:
            clean.append(item)
    clean.sort(key=lambda x: _nat(x["unita_minima"]), reverse=True)
    # "Largest in sample", never a universal whale threshold.
    for rank, item in enumerate(clean[:MAX_EVENTS], 1):
        item["posizione_nel_campione"] = rank
        item["criterio"] = "ORDINE_DI_GRANDEZZA_RELATIVO_AL_CAMPIONE"
    return clean[:MAX_EVENTS], len(clean)


def _evm_native(chain, url, fetch, native):
    head = native.get("valori") if isinstance(native, dict) else None
    # Native observation and capital sampling have independent request
    # rotations. Do not lose AVAX/ETH/BNB when only the header was deferred.
    height = (_nat(head["altezza_blocco"]) if isinstance(head,dict)
              else _hex(_rpc(fetch,url,"eth_blockNumber",[])))
    block_number = max(0, height - 6)
    block = _rpc(fetch, url, "eth_getBlockByNumber", [hex(block_number), True])
    if (not isinstance(block, dict) or _hex(block.get("number")) != block_number
            or not HEX64.fullmatch(str(block.get("hash")))):
        raise ValueError("EVM block incomplete")
    stamp = dt.datetime.fromtimestamp(_hex(block.get("timestamp"), 10**11), UTC).isoformat()
    txs = block.get("transactions")
    if not isinstance(txs, list) or len(txs) > 1500:
        raise ValueError("EVM transactions unbounded")
    events = []
    for tx in txs:
        if not isinstance(tx, dict) or not HEX64.fullmatch(str(tx.get("hash"))):
            continue
        if not EVM.fullmatch(str(tx.get("from"))) or not EVM.fullmatch(str(tx.get("to"))):
            continue
        raw = _hex(tx.get("value"), 10**46)
        if raw:
            events.append(_event(chain, "NATIVE", tx["hash"], "native", raw, 18, url,
                                 block_number, stamp, tx["from"], tx["to"]))
    chosen,total = _top(events)
    return {"eventi": chosen, "detentori": [], "elementi_esaminati": len(txs),
            "eventi_distinti": total,
            "periodo": {"tipo": "BLOCCO_CAMPIONE", "da_blocco": block_number,
                        "a_blocco": block_number, "orario_utc": stamp},
            "copertura": "Un blocco esaminato, non flussi globali; profondita 6 blocchi senza attestare finalita"}


# Ethplorer's published `freekey` is a shared, no-cost public development
# credential (not a private account key). Fair-use limits: 2 rps, 20/min.
# Source: https://github.com/EverexIO/Ethplorer/wiki/ethplorer-api
ETHPLORER = "https://api.ethplorer.io"
BINPLORER = "https://api.binplorer.com"
JUPITER_TOKENS = "https://api.jup.ag/tokens/v2/search?query="
SOLANA_ALT_RPC = "https://public.rpc.solanavibestation.com"
ETHPLORER_HISTORY_LIMIT = 20
# Routescan keyless Data API: 2 req/s and 10,000/day. Only networks with
# successful end-to-end public probes are activated here.
ROUTESCAN = "https://api.routescan.io/v2/network/mainnet/evm/"
ROUTESCAN_CHAINS = {"ethereum": "1", "avalanche": "43114"}


def _routescan_urls(chain, contract):
    chain_id = ROUTESCAN_CHAINS[chain]
    base = ROUTESCAN + chain_id + "/"
    transfers = (base + "erc20-transfers?tokenAddress=" + contract
                 + "&sort=desc&limit=20")
    holders = base + "erc20/" + contract + "/holders?limit=10"
    return transfers, holders


def _routescan_transfers(chain, contract, expected_decimals, fetch):
    """Exact chain/contract and raw EVM units; secondary index, bounded page."""
    url, _ = _routescan_urls(chain, contract)
    data = fetch(url)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) > 20:
        raise ValueError("Routescan transfers unavailable or unbounded")
    events = []
    seen = set()
    precision = expected_decimals
    for item in items:
        if not isinstance(item, dict):
            continue
        if (str(item.get("chainId")) != ROUTESCAN_CHAINS[chain]
                or str(item.get("tokenAddress", "")).lower() != contract.lower()):
            continue
        d = item.get("tokenDecimals")
        if type(d) is not int or not 0 <= d <= 30:
            continue
        if precision is None:
            precision = d
        if d != precision:
            continue
        tx, origin, dest = item.get("txHash"), item.get("from"), item.get("to")
        if not HEX64.fullmatch(str(tx)) or not EVM.fullmatch(str(origin)) or not EVM.fullmatch(str(dest)):
            continue
        try:
            raw = _nat(item.get("amount"))
            index = _nat(item.get("logIndex"))
            block = _nat(item.get("blockNumber"))
            when = _ts(item.get("timestamp")).isoformat()
        except (ValueError, TypeError, OverflowError):
            continue
        key = (tx.lower(),index)
        if key in seen:
            continue
        seen.add(key)
        kind = ("MINT" if int(origin,16)==0 else "BURN" if int(dest,16)==0
                else "TRASFERIMENTO")
        events.append(_event(chain, contract, tx, index, raw, precision,
                             url, block, when, origin, dest, kind))
    return events, precision, url


def _routescan_holders(chain, contract, decimals, previous, fetch):
    """Bounded page of technical holder addresses, never economic owners."""
    _, url = _routescan_urls(chain, contract)
    data = fetch(url)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items)>MAX_HOLDERS:
        raise ValueError("Routescan holders unavailable or unbounded")
    old = {r["account"].lower(): int(r["unita_minima"])
           for r in previous.get("detentori",[]) if isinstance(r,dict)
           and isinstance(r.get("account"),str)
           and isinstance(r.get("unita_minima"),str)
           and r["unita_minima"].isdigit()}
    holders=[]
    for r in items:
        if not isinstance(r,dict) or str(r.get("chainId"))!=ROUTESCAN_CHAINS[chain]:
            continue
        address=r.get("address")
        if not EVM.fullmatch(str(address)):
            continue
        try:
            raw=_nat(r.get("balance"))
        except (ValueError,TypeError):
            continue
        prior=old.get(address.lower())
        holders.append({"account":address,"unita_minima":str(raw),
                        "decimali":decimals,
                        "variazione_unita_minima":str(raw-prior) if prior is not None else None,
                        "confronto_precedente_utc":previous.get("acquisito_utc") if prior is not None else None,
                        "entita":{"stato":"ENTITA_NON_IDENTIFICATA"}})
    return holders, url


def _routescan_index(chain, contract, fetch, previous):
    """Independent RPC-less route for a token on a verified indexed chain."""
    events,decimals,source=_routescan_transfers(chain,contract,None,fetch)
    if decimals is None:
        raise ValueError("Routescan sample has no verified token precision")
    holders=[]
    holder_source=None
    try:
        holders,holder_source=_routescan_holders(chain,contract,decimals,previous,fetch)
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        pass
    selected,total=_top(events)
    return {"eventi":selected,"detentori":holders,"fonte_detentori":holder_source,
            "elementi_esaminati":len(events),"eventi_distinti":total,
            "periodo":{"tipo":"PAGINA_ROUTESCAN","catena":chain},
            "copertura":"Routescan keyless: first indexed page, not complete transactions or owners.",
            "fallback":"ROUTESCAN_INDEX"}




def _ethplorer_history(contract, decimals, fetch, chain="ethereum"):
    """Indexed ERC-20 contract operations when direct logs/explorer are unavailable."""
    base = ETHPLORER if chain == "ethereum" else BINPLORER
    url = (base + "/getTokenHistory/" + contract
           + "?apiKey=freekey&limit=" + str(ETHPLORER_HISTORY_LIMIT))
    data = fetch(url)
    records = data.get("operations") if isinstance(data, dict) else None
    if not isinstance(records, list) or len(records) > ETHPLORER_HISTORY_LIMIT:
        raise ValueError("Ethplorer transfer sample unavailable")
    events, seen = [], set()
    for n, item in enumerate(records):
        if not isinstance(item, dict):
            continue
        info = item.get("tokenInfo")
        if not isinstance(info, dict) or str(info.get("address", "")).lower() != contract.lower():
            continue
        try:
            precision = _nat(info.get("decimals"), 30)
            if precision != decimals:
                continue
            qty = _nat(item.get("value"))
            stamp = dt.datetime.fromtimestamp(_nat(item.get("timestamp"), 10**11), UTC).isoformat()
        except (ValueError, TypeError, OverflowError):
            continue
        tx, origin, dest = item.get("transactionHash"), item.get("from"), item.get("to")
        kind = {"transfer": "TRASFERIMENTO", "mint": "MINT",
                "burn": "BURN"}.get(item.get("type"))
        if (not kind or not HEX64.fullmatch(str(tx)) or
                not EVM.fullmatch(str(origin)) or not EVM.fullmatch(str(dest))):
            continue
        key = (tx.lower(), origin.lower(), dest.lower(), str(qty))
        if key in seen:
            continue
        seen.add(key)
        events.append(_event(chain, contract, tx, n, qty, decimals,
                             url, None, stamp, origin, dest, kind))
    return events, url


def _ethplorer_holders(contract, decimals, previous, fetch, chain="ethereum"):
    """Exact rawBalance only; no percentage inferred from an index's UI balance."""
    base = ETHPLORER if chain == "ethereum" else BINPLORER
    url = base + "/getTopTokenHolders/" + contract + "?apiKey=freekey&limit=10"
    data = fetch(url)
    records = data.get("holders") if isinstance(data, dict) else None
    if not isinstance(records, list) or len(records) > MAX_HOLDERS:
        raise ValueError("Ethplorer holder page unavailable")
    earlier = {h["account"].lower(): int(h["unita_minima"]) for h in
               previous.get("detentori", []) if isinstance(h, dict)
               and isinstance(h.get("account"), str)
               and isinstance(h.get("unita_minima"), str) and h["unita_minima"].isdigit()}
    rows = []
    for item in records:
        if not isinstance(item, dict) or not EVM.fullmatch(str(item.get("address"))):
            continue
        try:
            qty = _nat(item.get("rawBalance"))
        except (ValueError, TypeError):
            continue  # never manufacture raw units from a rounded UI balance
        addr = item["address"]
        old = earlier.get(addr.lower())
        rows.append({"account": addr, "unita_minima": str(qty), "decimali": decimals,
                     "variazione_unita_minima": str(qty-old) if old is not None else None,
                     "confronto_precedente_utc": previous.get("acquisito_utc") if old is not None else None,
                     "entita": {"stato": "ENTITA_NON_IDENTIFICATA"}})
    return rows, url



def _bsc_public_index(contract, fetch, previous):
    """Binplorer on BNB Chain: public operations and accounts, not owners."""
    meta = fetch(BINPLORER + "/getTokenInfo/" + contract + "?apiKey=freekey")
    if not isinstance(meta, dict) or str(meta.get("address","")).lower() != contract.lower():
        raise ValueError("Binplorer contract mismatch")
    decimals = _nat(meta.get("decimals"), 30)
    events, source = _ethplorer_history(contract, decimals, fetch, chain="bsc")
    holders, holder_source = [], None
    try:
        holders, holder_source = _ethplorer_holders(contract, decimals, previous, fetch, chain="bsc")
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        pass
    selected, total = _top(events)
    return {"eventi": selected, "detentori": holders, "fonte_detentori": holder_source,
            "elementi_esaminati":len(events), "eventi_distinti":total,
            "periodo":{"tipo":"PAGINA_BINPLORER"},
            "copertura":"BNB Chain: recent indexed transfers and up to ten holders; sample, not full exchange flows",
            "fallback":"BINPLORER_INDEX"}


def _solana_jupiter_index(mint, fetch):
    """Public index of holder concentration, NOT owner or transfer events."""
    url = JUPITER_TOKENS + mint
    data = fetch(url)
    matches = [x for x in data if isinstance(x,dict) and x.get("id")==mint] if isinstance(data,list) else []
    if len(matches)!=1:
        raise ValueError("Jupiter exact mint not available")
    row=matches[0]
    decimals=_nat(row.get("decimals"),30)
    count=_nat(row.get("holderCount"),10**12)
    audit=row.get("audit")
    concentration=audit.get("topHoldersPercentage") if isinstance(audit,dict) else None
    try:
        percentage=Decimal(str(concentration))
        if not percentage.is_finite() or not 0<=percentage<=100:
            raise ValueError("index concentration invalid")
        share=str(percentage)
    except (ValueError,TypeError,InvalidOperation):
        share=None
    return {"eventi":[],"detentori":[],"elementi_esaminati":0,"eventi_distinti":0,
            "aggregato_detentori":{"mint":mint,"numero_account":count,
               "decimali":decimals,"quota_top_pct_indice":share,"fonte":url,
               "tipo":"AGGREGATO_INDICIZZATO_SECONDARIO"},
            "periodo":{"tipo":"RIEPILOGO_JUPITER_TOKEN"},
            "copertura":"Token SPL: holder count and top share indexed by Jupiter; no individual holders, transfers or owners."}


def _evm_token(chain, contract, url, fetch, native, previous):
    # A newly held ERC-20 must work even if ETH is not in the wallet.
    # A chain head is a convenience for bounded RPC logs, not an ownership
    # prerequisite for publicly indexed contract transfers.
    head = native.get("valori") if isinstance(native, dict) else None
    if chain=="ethereum" and not isinstance(head, dict):
        try:
            return _routescan_index(chain, contract, fetch, previous)
        except (OSError, ValueError, KeyError, TypeError, OverflowError, AssertionError):
            try:
                dec = _hex(_rpc(fetch,url,"eth_call",
                    [{"to":contract,"data":"0x313ce567"},"latest"]),30)
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                info = fetch(ETHPLORER + "/getTokenInfo/" + contract + "?apiKey=freekey")
                if not isinstance(info,dict) or str(info.get("address","")).lower()!=contract.lower():
                    raise ValueError("unknown Ethereum contract precision")
                dec = _nat(info.get("decimals"),30)
            events,source=_ethplorer_history(contract,dec,fetch)
            holders=[]
            holder_source=None
            try:
                holders,holder_source=_ethplorer_holders(contract,dec,previous,fetch)
            except (OSError,ValueError,TypeError,KeyError,OverflowError):
                pass
            chosen,total=_top(events)
            return {"eventi":chosen,"detentori":holders,"fonte_detentori":holder_source,
                    "eventi_distinti":total,"elementi_esaminati":len(events),
                    "periodo":{"tipo":"PAGINA_ETHPLORER"},
                    "copertura":"Contract indexed independently of native ETH wallet asset; no owner claim",
                    "fallback":"ETHPLORER_SENZA_TESTA_NATIVE"}
    if chain=="bsc":
        try:
            return _bsc_public_index(contract, fetch, previous)
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            pass  # native RPC fallback remains
    head = native.get("valori") if isinstance(native, dict) else None
    if not isinstance(head, dict):
        # A new BSC contract does not require BNB to be held or its native
        # header to happen to fall within the upstream five-chain budget.
        if chain!="bsc":
            raise ValueError("EVM head unavailable")
        head={"altezza_blocco":_hex(_rpc(fetch,url,"eth_blockNumber",[]))}
    height = _nat(head["altezza_blocco"])
    end = max(0, height - 6)
    start = max(0, end - 47)
    source = url
    try:
        decimals_value = _rpc(fetch, url, "eth_call",
                              [{"to": contract, "data": "0x313ce567"}, "latest"])
        decimals = _hex(decimals_value, 30)
    except (OSError,ValueError,TypeError,KeyError):
        if chain != "ethereum":
            raise
        # Public explorer token metadata is a secondary index, explicitly
        # identified as such; never infer official project contract status.
        meta_url = ETH_EXPLORER + "/api/v2/tokens/" + contract
        meta = fetch(meta_url)
        if not isinstance(meta, dict) or str(meta.get("type")).upper() != "ERC-20":
            raise ValueError("explorer ERC-20 token metadata absent")
        raw_decimals = meta.get("decimals")
        decimals = _nat(raw_decimals, 30)

    events = []
    fallback_reason = None
    try:
        logs = _rpc(fetch, url, "eth_getLogs", [{
            "fromBlock": hex(start), "toBlock": hex(end),
            "address": contract, "topics": [TOPIC_TRANSFER]}])
        if not isinstance(logs, list) or len(logs) > 1200:
            raise ValueError("unbounded logs")
        for log in logs:
            if not isinstance(log, dict) or str(log.get("address","")).lower() != contract.lower():
                continue
            topics = log.get("topics")
            if (not isinstance(topics, list) or len(topics) != 3 or
                    topics[0].lower() != TOPIC_TRANSFER or log.get("removed") is True or
                    not all(HEX64.fullmatch(str(t)) for t in topics) or
                    not HEX64.fullmatch(str(log.get("transactionHash")))):
                continue
            number = _hex(log.get("blockNumber"))
            if number < start or number > end:
                continue
            data = log.get("data")
            if not isinstance(data, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", data):
                continue
            index = _hex(log.get("logIndex"))
            origin = "0x" + topics[1][-40:]
            dest = "0x" + topics[2][-40:]
            kind = ("MINT" if int(topics[1], 16) == 0 else
                    "BURN" if int(topics[2], 16) == 0 else "TRASFERIMENTO")
            events.append(_event(chain, contract, log["transactionHash"], index,
                                 int(data, 16), decimals, source, number, None,
                                 origin, dest, kind))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        fallback_reason = type(exc).__name__
        if chain != "ethereum":
            raise ValueError("RPC logs unavailable: " + fallback_reason)
        # Prioritize primary RPC, then Blockscout, then published no-cost
        # Ethplorer history. All fallbacks are clearly *indexed* observations.
        base = ETH_EXPLORER + "/api/v2/tokens/" + contract
        try:
            data = fetch(base + "/transfers")
            rows = data.get("items") if isinstance(data, dict) else None
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError("Blockscout transfer page invalid")
            source = base + "/transfers"
            used_fallback = set()
            for idx, item in enumerate(rows):
                if not isinstance(item, dict):
                    continue
                tx = item.get("transaction_hash") or item.get("tx_hash")
                amount = item.get("total")
                amount = amount.get("value") if isinstance(amount, dict) else None
                if not HEX64.fullmatch(str(tx)):
                    continue
                origin, dest = item.get("from"), item.get("to")
                if not isinstance(origin, dict) or not isinstance(dest, dict):
                    continue
                if not EVM.fullmatch(str(origin.get("hash"))) or not EVM.fullmatch(str(dest.get("hash"))):
                    continue
                when = item.get("timestamp")
                _ts(when)
                dedup_key = (tx.lower(), origin["hash"].lower(), dest["hash"].lower(), str(amount))
                if item.get("log_index") is None and dedup_key in used_fallback:
                    continue
                used_fallback.add(dedup_key)
                events.append(_event(chain, contract, tx, item.get("log_index", idx),
                                     amount, decimals, source, item.get("block_number"),
                                     when, origin["hash"], dest["hash"], labels={
                                         "da": _tag(origin), "a": _tag(dest)}))
            fallback_label = "PAGINA_BLOCKSCOUT"
        except (OSError, ValueError, KeyError, TypeError, OverflowError, AssertionError):
            # Shared Blockscout may return 403. Prefer an independently
            # verified chain-bound Routescan page over generic ticker indexes.
            try:
                events, checked_decimals, source = _routescan_transfers(
                    chain, contract, decimals, fetch)
                if checked_decimals != decimals:
                    raise ValueError("Routescan precision mismatch")
                fallback_label = "PAGINA_ROUTESCAN"
            except (OSError, ValueError, KeyError, TypeError, OverflowError, AssertionError):
                events, source = _ethplorer_history(contract, decimals, fetch)
                fallback_label = "PAGINA_ETHPLORER"
    # Even when RPC Transfer logs work, the independent indexed page may
    # carry PUBLIC actor tags. Match tx+from+to+amount exactly: explorer
    # metadata may enrich attribution, but cannot replace an RPC fact.
    if chain == "ethereum" and not fallback_reason and events:
        try:
            label_url = ETH_EXPLORER + "/api/v2/tokens/" + contract + "/transfers"
            tagged = fetch(label_url)
            indexed = tagged.get("items") if isinstance(tagged,dict) else None
            if not isinstance(indexed,list) or len(indexed)>100:
                raise ValueError("indexed labels unavailable")
            by_fact = {}
            for item in indexed:
                if not isinstance(item,dict):
                    continue
                fr, to = item.get("from"), item.get("to")
                amount = item.get("total")
                amount = amount.get("value") if isinstance(amount,dict) else None
                if (not isinstance(fr,dict) or not isinstance(to,dict) or
                        not EVM.fullmatch(str(fr.get("hash"))) or
                        not EVM.fullmatch(str(to.get("hash")))):
                    continue
                try:
                    q = _nat(amount)
                except ValueError:
                    continue
                by_fact[(str(item.get("transaction_hash") or item.get("tx_hash")).lower(),
                         fr["hash"].lower(),to["hash"].lower(),str(q))] = (fr,to)
            for event in events:
                key=(event["tx"].lower(),event["da"].lower(),event["a"].lower(),
                     event["unita_minima"])
                pair=by_fact.get(key)
                if pair:
                    event["attribuzione"]={"da":_tag(pair[0]),"a":_tag(pair[1])}
                    event["fonte_attribuzione"]=label_url
        except (OSError,ValueError,KeyError,TypeError,AssertionError):
            pass
    holders = []
    holders_source = None
    earlier = {h["account"].lower(): int(h["unita_minima"]) for h in
               previous.get("detentori", []) if isinstance(h, dict)
               and isinstance(h.get("account"), str) and
               isinstance(h.get("unita_minima"), str) and
               h["unita_minima"].isdigit()}
    if chain == "ethereum":
        # Follow the index that successfully supplied transfer data. Repeating
        # blocked providers for holders wastes the same scarce 6-call budget.
        # If the primary RPC succeeded, Blockscout tags remain optional.
        if fallback_reason and fallback_label == "PAGINA_ETHPLORER":
            try:
                holders, holders_source = _ethplorer_holders(
                    contract, decimals, previous, fetch)
            except (OSError,ValueError,KeyError,TypeError,OverflowError):
                pass
        elif fallback_reason and fallback_label == "PAGINA_ROUTESCAN":
            try:
                holders, holders_source = _routescan_holders(
                    chain, contract, decimals, previous, fetch)
            except (OSError,ValueError,KeyError,TypeError,OverflowError):
                pass
        else:
            h_url = ETH_EXPLORER + "/api/v2/tokens/" + contract + "/holders"
            try:
                answer = fetch(h_url)
                items = answer.get("items") if isinstance(answer, dict) else None
                if not isinstance(items, list) or len(items) > 100:
                    raise ValueError("Blockscout holder page invalid")
                for h in items[:MAX_HOLDERS]:
                    if not isinstance(h, dict):
                        continue
                    addr = h.get("address")
                    if isinstance(addr, dict) and EVM.fullmatch(str(addr.get("hash"))):
                        qty = _nat(h.get("value"))
                        before = earlier.get(addr["hash"].lower())
                        holders.append({"account": addr["hash"], "unita_minima": str(qty),
                                        "decimali": decimals,
                                        "variazione_unita_minima": (str(qty-before) if before is not None else None),
                                        "confronto_precedente_utc": previous.get("acquisito_utc") if before is not None else None,
                                        "entita": _tag(addr)})
                holders_source = h_url
            except (OSError,ValueError,KeyError,TypeError,OverflowError,AssertionError):
                try:
                    holders, holders_source = _routescan_holders(
                        chain, contract, decimals, previous, fetch)
                except (OSError,ValueError,KeyError,TypeError,OverflowError,AssertionError):
                    try:
                        holders, holders_source = _ethplorer_holders(
                            contract, decimals, previous, fetch)
                    except (OSError,ValueError,KeyError,TypeError,OverflowError):
                        pass
    selected,total = _top(events)
    return {"eventi": selected, "detentori": holders, "fonte_detentori": holders_source,
            "elementi_esaminati": len(events), "eventi_distinti": total,
            "periodo": {"tipo": "RANGE_BLOCCHI" if not fallback_reason else fallback_label,
                        "da_blocco": start if not fallback_reason else None,
                        "a_blocco": end if not fallback_reason else None},
            "copertura": ("Eventi Transfer ERC-20 nel range limitato; paginazione NON completa. "
                          "Explorer indicizzato se fallback; nessuna attribuzione certa del progetto."),
            "fallback": fallback_reason}


def _solana_recent_mint_transfer(mint, fetch):
    """Mint-address signatures: one recent finalized tx, not a complete token flow.

    Public Solana RPC getSignaturesForAddress + getTransaction v1 was observed
    returning a real transferChecked mint match without top accounts.
    """
    signatures=_rpc(fetch,SOLANA_ALT_RPC,"getSignaturesForAddress",
                    [mint,{"limit":2,"commitment":"finalized"}])
    if not isinstance(signatures,list) or len(signatures)>2:
        raise ValueError("mint signature sample invalid")
    events=[]
    scanned=0
    slots=[]
    for signature in signatures[:1]:
        if not isinstance(signature,dict) or signature.get("err") is not None:
            continue
        txid=signature.get("signature")
        if not B58.fullmatch(str(txid)):
            continue
        tx=_rpc(fetch,SOLANA_ALT_RPC,"getTransaction",
                [txid,{"encoding":"jsonParsed","commitment":"finalized",
                       "maxSupportedTransactionVersion":1}])
        if (not isinstance(tx,dict) or not isinstance(tx.get("meta"),dict)
                or tx["meta"].get("err") is not None):
            continue
        scanned+=1
        slot=_nat(tx.get("slot"))
        slots.append(slot)
        stamp=(dt.datetime.fromtimestamp(_nat(tx["blockTime"],10**11),UTC).isoformat()
               if tx.get("blockTime") is not None else None)
        base=(tx.get("transaction") or {}).get("message") or {}
        instructions=list(base.get("instructions") or [])
        for inner in tx["meta"].get("innerInstructions") or []:
            if isinstance(inner,dict):
                instructions.extend(inner.get("instructions") or [])
        for i,instruction in enumerate(instructions[:120]):
            parsed=instruction.get("parsed") if isinstance(instruction,dict) else None
            info=parsed.get("info") if isinstance(parsed,dict) else None
            if (not isinstance(info,dict) or parsed.get("type")!="transferChecked"
                    or info.get("mint")!=mint):
                continue
            quantity=info.get("tokenAmount")
            if not isinstance(quantity,dict):
                continue
            dec=quantity.get("decimals")
            if (type(dec) is not int or not 0<=dec<=30
                    or not B58.fullmatch(str(info.get("source")))
                    or not B58.fullmatch(str(info.get("destination")))):
                continue
            events.append(_event("solana",mint,txid,i,quantity.get("amount"),
                                 dec,SOLANA_ALT_RPC,slot,stamp,
                                 info["source"],info["destination"]))
    result,count=_top(events)
    return {"eventi":result,"eventi_distinti":count,
            "elementi_esaminati":scanned,
            "periodo":{"tipo":"CAMPIONE_TRANSAZIONE_MINT_FINALIZZATA",
                       "slot":slots[0] if slots else None},
            "copertura":"Una transazione finalizzata che include il mint, trasferimenti transferChecked soltanto: NON storico completo del token."}


def _solana_token(mint, url, fetch, previous):
    try:
        top = _rpc(fetch, url, "getTokenLargestAccounts",
                   [mint, {"commitment": "finalized"}])
    except (OSError, ValueError, TypeError, KeyError):
        # Holder aggregation and recent mint-linked transfers are different
        # evidence: either may survive when top-20 Solana RPC is throttled.
        index=None
        try:
            index=_solana_jupiter_index(mint,fetch)
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            pass
        sample=None
        try:
            sample=_solana_recent_mint_transfer(mint,fetch)
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            pass
        if index is None and (sample is None or not sample["eventi"]):
            raise ValueError("Solana public index and mint transfer unavailable")
        if index is None:
            return dict(sample,detentori=[],
                        copertura=sample["copertura"]+"; Jupiter holders unavailable",
                        fonte_detentori=None)
        if sample and sample["eventi"]:
            index.update(eventi=sample["eventi"],
                         eventi_distinti=sample["eventi_distinti"],
                         elementi_esaminati=sample["elementi_esaminati"],
                         periodo={"tipo":"JUPITER_HOLDER_PLUS_MINT_TRANSFER",
                                  "trasferimento":sample["periodo"],
                                  "aggregato":"JUPITER_SECONDARIO"},
                         copertura=index["copertura"]+"; "+sample["copertura"])
        return index
    if not isinstance(top, dict) or not isinstance(top.get("value"), list):
        raise ValueError("largest token accounts missing")
    slot = _nat(top.get("context", {}).get("slot"))
    rows = top["value"]
    if len(rows) > 20:
        raise ValueError("SPL top accounts invalid")
    supply = _rpc(fetch, url, "getTokenSupply",
                  [mint, {"commitment": "finalized"}])
    sv = supply.get("value") if isinstance(supply, dict) else None
    if not isinstance(sv, dict):
        raise ValueError("SPL supply not available")
    total = _nat(sv.get("amount"))
    decimals = sv.get("decimals")
    if type(decimals) is not int or not 0 <= decimals <= 30:
        raise ValueError("SPL supply decimals invalid")
    earlier = {h["account"]:h["unita_minima"] for h in
               (previous.get("detentori") or []) if isinstance(h, dict)}
    holders = []
    for row in rows:
        if not isinstance(row, dict) or not B58.fullmatch(str(row.get("address"))):
            continue
        if row.get("decimals") != decimals:
            continue
        raw = _nat(row.get("amount"))
        old = earlier.get(row["address"])
        change = str(raw - int(old)) if old is not None else None
        holders.append({"account": row["address"], "unita_minima": str(raw),
                        "decimali": decimals,
                        "quota_supply_pct": str((Decimal(raw)/total*100).quantize(Decimal(".0001"))) if total else None,
                        "variazione_unita_minima": change,
                        "confronto_precedente_utc": previous.get("acquisito_utc") if old is not None else None,
                        "entita": {"stato": "ENTITA_NON_IDENTIFICATA"}})
    events = []
    if holders:
        signatures = _rpc(fetch, url, "getSignaturesForAddress",
                          [holders[0]["account"], {"commitment": "finalized", "limit": 3}])
        if not isinstance(signatures, list) or len(signatures) > 3:
            raise ValueError("SPL signatures invalid")
        for sig in signatures[:1]:
            if not isinstance(sig, dict) or sig.get("err") is not None or not B58.fullmatch(str(sig.get("signature"))):
                continue
            tx = _rpc(fetch, url, "getTransaction",
                      [sig["signature"], {"encoding": "jsonParsed",
                                           "commitment": "finalized",
                                           "maxSupportedTransactionVersion": 0}])
            if not isinstance(tx, dict) or not isinstance(tx.get("meta"), dict) or tx["meta"].get("err") is not None:
                continue
            stamp = dt.datetime.fromtimestamp(_nat(tx["blockTime"], 10**11), UTC).isoformat() if tx.get("blockTime") else None
            base = (tx.get("transaction") or {}).get("message") or {}
            ins = base.get("instructions") if isinstance(base, dict) else []
            inner = tx["meta"].get("innerInstructions") or []
            for group in inner:
                if isinstance(group, dict):
                    ins = (ins or []) + (group.get("instructions") or [])
            for n, instruction in enumerate((ins or [])[:120]):
                parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
                info = parsed.get("info") if isinstance(parsed, dict) else None
                if (not isinstance(info, dict) or parsed.get("type") != "transferChecked"
                        or info.get("mint") != mint or not isinstance(info.get("tokenAmount"), dict)):
                    continue
                v = info["tokenAmount"]
                if v.get("decimals") != decimals or not B58.fullmatch(str(info.get("source"))) or not B58.fullmatch(str(info.get("destination"))):
                    continue
                events.append(_event("solana", mint, sig["signature"], n,
                                     v.get("amount"), decimals, url, tx.get("slot"),
                                     stamp, info["source"], info["destination"]))
    chosen,total_events = _top(events)
    return {"eventi": chosen, "detentori": holders, "fonte_detentori": url,
            "supply_unita_minima": str(total), "elementi_esaminati": len(rows),
            "eventi_distinti": total_events,
            "periodo": {"tipo": "TOP20_ACCOUNT_FINALIZZATI", "slot": slot},
            "copertura": "20 maggiori account token SPL al massimo; non proprietari. "
                        "Campione trasferimenti massimo una transazione di un account selezionato."}


def _solana_native(url, fetch, previous):
    result = _rpc(fetch, url, "getLargestAccounts",
                  [{"commitment": "finalized", "filter": "circulating"}])
    rows = result.get("value") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError("largest SOL accounts invalid")
    previous_accounts = {x["account"]:x["unita_minima"] for x in
                         previous.get("detentori", []) if isinstance(x, dict)}
    holders = []
    for item in rows:
        if not isinstance(item, dict) or not B58.fullmatch(str(item.get("address"))):
            continue
        n = _nat(item.get("lamports"))
        old = previous_accounts.get(item["address"])
        holders.append({"account": item["address"], "unita_minima": str(n),
                        "decimali": 9, "variazione_unita_minima": str(n-int(old)) if old is not None else None,
                        "confronto_precedente_utc": previous.get("acquisito_utc") if old is not None else None,
                        "entita": {"stato":"ENTITA_NON_IDENTIFICATA"}})
    return {"eventi": [], "detentori": holders, "fonte_detentori": url,
            "elementi_esaminati": len(rows), "eventi_distinti": 0,
            "periodo": {"tipo":"TOP20_ACCOUNT_SOL_FINALIZZATI",
                        "slot": _nat(result.get("context", {}).get("slot"))},
            "copertura": "Top 20 account SOL circolanti, non tutti i detentori e non prova di movimenti."}


def _bitcoin(fetch, native):
    values = native.get("valori") if isinstance(native, dict) else None
    if not isinstance(values, dict) or not HEX64.fullmatch(str(values.get("blocco_hash"))):
        raise ValueError("Bitcoin block not observed")
    h = values["blocco_hash"]
    url = "https://blockstream.info/api/block/" + h + "/txs"
    response = fetch(url)
    if not isinstance(response, list) or len(response) > 25:
        raise ValueError("Esplora block page invalid")
    events = []
    for tx in response:
        if not isinstance(tx, dict) or not HEX64.fullmatch(str(tx.get("txid"))):
            continue
        status = tx.get("status")
        if not isinstance(status, dict) or status.get("confirmed") is not True or status.get("block_hash") != h:
            continue
        inputs = tx.get("vin")
        outputs = tx.get("vout")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            continue
        for i,vout in enumerate(outputs[:100]):
            if not isinstance(vout, dict):
                continue
            raw = _nat(vout.get("value"))
            to = vout.get("scriptpubkey_address")
            if raw > 0 and isinstance(to, str):
                events.append(_event("bitcoin", "NATIVE", tx["txid"], i, raw, 8, url,
                                     status.get("block_height"), None,
                                     "INPUT_UTXO_NON_UNIVOCO", to, "OUTPUT_UTXO"))
    chosen,total = _top(events)
    count = values.get("transazioni_blocco")
    return {"eventi":chosen,"detentori":[],"eventi_distinti":total,
            "elementi_esaminati":len(response),
            "periodo":{"tipo":"PAGINA_DI_BLOCCO_UTXO","blocco_hash":h,
                       "transazioni_totali_blocco":count},
            "copertura":"Primi 25 tx del blocco al massimo: output UTXO NON equivalgono a un cambio proprietario; resto possibile."}


def _xrpl(url, fetch):
    data = fetch(url, {"jsonrpc":"2.0","id":1,"method":"ledger",
                       "params":[{"ledger_index":"validated","transactions":True,"expand":True}]})
    result = data.get("result") if isinstance(data, dict) and data.get("id",1)==1 and not data.get("error") else None
    ledger = result.get("ledger") if isinstance(result, dict) else None
    if (not isinstance(ledger, dict) or result.get("validated") is not True
            or result.get("status", data.get("status")) != "success"):
        raise ValueError("XRPL validation missing")
    index = _nat(result.get("ledger_index"))
    if not HEX64.fullmatch(str(ledger.get("ledger_hash"))):
        raise ValueError("XRPL hash missing")
    stamp = _ts(ledger["close_time_iso"]).isoformat()
    txs = ledger.get("transactions")
    if not isinstance(txs, list) or len(txs) > 2000:
        raise ValueError("XRPL expanded ledger unavailable")
    events = []
    for i,item in enumerate(txs):
        if not isinstance(item, dict):
            continue
        tx = item.get("tx") or item.get("tx_json") or item
        meta = item.get("meta") or item.get("metaData")
        if not isinstance(tx, dict) or not isinstance(meta, dict) or meta.get("TransactionResult")!="tesSUCCESS":
            continue
        if tx.get("TransactionType") != "Payment" or not isinstance(tx.get("Amount"), str):
            continue
        # XRP drops only; issuer IOUs, paths and non-delivered amounts are different.
        delivered = meta.get("delivered_amount")
        if not isinstance(delivered, str):
            continue
        if not isinstance(tx.get("Account"),str) or not isinstance(tx.get("Destination"),str):
            continue
        ident = tx.get("hash")
        if not HEX64.fullmatch(str(ident)):
            continue
        events.append(_event("xrpl","NATIVE", ident, i, delivered, 6, url,
                             index, stamp,tx["Account"],tx["Destination"]))
    chosen,total = _top(events)
    return {"eventi":chosen,"detentori":[],"eventi_distinti":total,
            "elementi_esaminati":len(txs),
            "periodo":{"tipo":"LEDGER_VALIDATO_CAMPIONE","indice_ledger":index,"orario_utc":stamp},
            "copertura":"Un ledger validato, pagamenti XRP delivered_amount; IOU/path non conteggiati. "
                        "Non equivale a flussi di exchange senza etichette."}


def _sui(url, fetch):
    query = ("query { transactions(last: 8) { nodes { digest effects { "
             "status timestamp checkpoint { sequenceNumber } "
             "balanceChanges(first: 30) { nodes { owner { address } amount coinType { repr } } } "
             "} } } }")
    data = fetch(url, {"query":query})
    nodes = ((data.get("data") or {}).get("transactions") or {}).get("nodes") if isinstance(data, dict) and not data.get("errors") else None
    if not isinstance(nodes, list) or len(nodes) > 8:
        raise ValueError("Sui GraphQL transaction sample missing")
    events = []
    for item in nodes:
        if not isinstance(item, dict) or not B58.fullmatch(str(item.get("digest"))):
            continue
        effects = item.get("effects")
        if not isinstance(effects, dict) or effects.get("status") != "SUCCESS":
            continue
        changes = (effects.get("balanceChanges") or {}).get("nodes")
        if not isinstance(changes, list) or len(changes) > 30:
            continue
        stamp = effects.get("timestamp")
        if stamp:
            _ts(stamp)
        idx = _nat((effects.get("checkpoint") or {}).get("sequenceNumber"))
        valid = []
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            coin = (ch.get("coinType") or {}).get("repr")
            if not isinstance(coin, str) or not coin.lower().endswith("::sui::sui"):
                continue
            owner = (ch.get("owner") or {}).get("address")
            amount = ch.get("amount")
            if not isinstance(owner, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", owner):
                continue
            if not isinstance(amount, str) or not re.fullmatch(r"-?[0-9]{1,45}", amount):
                continue
            valid.append((owner,int(amount)))
        # Net balance changes aren't inherently a pairwise transfer.
        for n,(owner, amount) in enumerate(valid[:12]):
            if amount:
                events.append(_event("sui","NATIVE",item["digest"],n,abs(amount),9,
                                     url,idx,stamp,owner if amount<0 else None,
                                     owner if amount>0 else None,
                                     "VARIAZIONE_NETTA_SALDO_NON_TRASFERIMENTO"))
    chosen,total = _top(events)
    return {"eventi":chosen,"detentori":[],"eventi_distinti":total,
            "elementi_esaminati":len(nodes),
            "periodo":{"tipo":"ULTIME_8_TRANSAZIONI_CAMPIONE"},
            "copertura":"Variazioni nette saldo SUI di 8 transazioni non filtrate; "
                        "non ricostruiscono trasferimenti bilaterali o tutti i detentori."}


def _near(url, fetch):
    block = _rpc(fetch,url,"block",{"finality":"final"})
    if not isinstance(block,dict) or not isinstance(block.get("chunks"),list):
        raise ValueError("NEAR final block missing")
    chunks = block["chunks"]
    if not chunks:
        raise ValueError("NEAR empty block")
    # The first shard is often empty. Choose among chunks with a
    # non-empty transaction root, rotating by finalized block height without
    # adding requests. Unknown roots remain eligible (legacy RPC schemas).
    empty_root="1"*32
    nonempty=[row for row in chunks if isinstance(row,dict)
              and row.get("tx_root")!=empty_root]
    if not nonempty:
        return {"eventi":[],"detentori":[],"eventi_distinti":0,
                "elementi_esaminati":0,
                "periodo":{"tipo":"BLOCCO_TUTTI_CHUNK_SENZA_TX",
                           "altezza_blocco":block.get("header",{}).get("height")},
                "copertura":"Tutti i chunk dichiarano una radice transazioni vuota; nessun trasferimento campionato."}
    height=_nat((block.get("header") or {}).get("height",0))
    selected=nonempty[height%len(nonempty)]
    hashed = selected.get("chunk_hash")
    if not isinstance(hashed,str) or len(hashed)<25:
        raise ValueError("NEAR selected chunk hash missing")
    chunk = _rpc(fetch,url,"chunk",{"chunk_id":hashed})
    txs=chunk.get("transactions") if isinstance(chunk,dict) else None
    if not isinstance(txs,list) or len(txs)>500:
        raise ValueError("NEAR chunk unavailable")
    events=[]
    for tx in txs:
        if not isinstance(tx,dict):
            continue
        txid=tx.get("hash"); sender=tx.get("signer_id"); receiver=tx.get("receiver_id")
        if not isinstance(txid,str) or not isinstance(sender,str) or not isinstance(receiver,str):
            continue
        for i,action in enumerate((tx.get("actions") or [])[:25]):
            transfer=action.get("Transfer") if isinstance(action,dict) else None
            if not isinstance(transfer,dict):
                continue
            raw=transfer.get("deposit")
            if raw is not None:
                events.append(_event("near","NATIVE",txid,i,raw,24,url,
                                     block.get("header",{}).get("height"),None,
                                     sender,receiver))
    chosen,total=_top(events)
    return {"eventi":chosen,"detentori":[],"eventi_distinti":total,
            "elementi_esaminati":len(txs),
            "periodo":{"tipo":"UN_CHUNK_BLOCCO_FINALIZZATO","chunk_hash":hashed,
                       "chunk_con_transazioni":len(nonempty),"chunk_totali":len(chunks)},
            "copertura":"Un chunk NEAR non vuoto selezionato per altezza di blocco: non tutte le shard e ricevute."}


def _targets(assets):
    items={}
    for group in ("posizioni","candidati"):
        for row in assets.get(group,[]):
            native = row.get("progetto_id")
            import kdd_network_defi as net
            native_ref = net.NATIVE_IDS.get(native)
            if native_ref and native_ref[0] == row.get("token"):
                chain=native_ref[1]
                if chain in SUPPORTED:
                    items[(chain,"NATIVE")]=True
            for indexed in row.get("contratti_indicizzati",[]):
                chain=indexed["rete"]; addr=indexed["contratto"]
                if chain in ("ethereum","bsc","solana","avalanche"):
                    items[(chain,addr)]=True
    return sorted(items)


def _probe(key, assets, fetch, previous):
    import kdd_network_defi as net
    chain,contract=key
    if chain == "avalanche" and contract != "NATIVE":
        return _routescan_index(chain, contract, fetch, previous)
    url = (net.CONTRACT_ENDPOINTS[chain] if contract!="NATIVE" else
           net.NATIVE_ENDPOINTS.get(chain,net.SOL_URL if chain=="solana" else net.SUI_URL))
    native = assets.get("fonti_native",{}).get(chain)
    if chain in ("ethereum","bsc","avalanche"):
        return (_evm_native(chain,url,fetch,native) if contract=="NATIVE" else
                _evm_token(chain,contract,url,fetch,native,previous))
    if chain=="solana":
        return (_solana_native(url,fetch,previous) if contract=="NATIVE" else
                _solana_token(contract,url,fetch,previous))
    if chain=="bitcoin":
        return _bitcoin(fetch,native)
    if chain=="xrpl":
        return _xrpl(url,fetch)
    if chain=="sui":
        return _sui(net.SUI_URL,fetch)
    if chain=="near":
        return _near(url,fetch)
    raise ValueError("unsupported chain")


class _PublicBudgetReached(RuntimeError):
    """Bound public network cost without conflating a missing probe with zero."""


def collect(now, assets, economics, previous, fetch):
    """Probe a rotated bounded subset, preserve an entry for every wallet/candidate."""
    moment = now.astimezone(UTC)
    targets = _targets(assets)
    old = previous if isinstance(previous,dict) and previous.get("schema")==SCHEMA else {}
    index = next((i for i,k in enumerate(targets)
                  if isinstance(old.get("prossimo_target"),str) and
                  "|".join(k)>=old["prossimo_target"]),0)
    chosen = [targets[(index+i)%len(targets)]
              for i in range(min(MAX_TARGETS,len(targets)))]
    old_probes = {(r.get("rete"),r.get("asset_tecnico")):r
                  for r in old.get("sonde",[]) if isinstance(r,dict)}
    # The 5-target rotation must not discard holder comparisons for the
    # other targets. Reuse at most 32 bounded public observations for 7 days.
    history = {}
    for row in old.get("storico_detentori", [])[:MAX_HISTORY]:
        if not isinstance(row, dict):
            continue
        key=(row.get("rete"),row.get("asset_tecnico"))
        try:
            age=moment-_ts(row.get("acquisito_utc"))
        except (ValueError,TypeError):
            continue
        if (key in targets and dt.timedelta(0)<=age<=dt.timedelta(days=7)
                and isinstance(row.get("detentori"),list)
                and len(row["detentori"])<=20):
            history[key]=row
    for key,row in old_probes.items():
        if (key in targets and row.get("stato")=="OSSERVATO"
                and isinstance(row.get("detentori"),list)):
            history[key]=row
    source = []
    total_calls = [0]
    for key in chosen:
        if total_calls[0] >= MAX_PUBLIC_CALLS:
            break
        calls = [0]
        def counted_fetch(url, payload=None):
            if calls[0] >= MAX_CALLS_PER_TARGET or total_calls[0] >= MAX_PUBLIC_CALLS:
                raise _PublicBudgetReached("BUDGET_RICHIESTE")
            calls[0] += 1
            total_calls[0] += 1
            return fetch(url, payload)
        try:
            result = _probe(key,assets,counted_fetch,history.get(key,{}))
            state="OSSERVATO"
            reason=None
        except (OSError,ValueError,TypeError,KeyError,OverflowError,UnicodeError,
                AssertionError,AttributeError,_PublicBudgetReached) as exc:
            result={"eventi":[],"detentori":[],"elementi_esaminati":0,
                    "eventi_distinti":0,"periodo":None,
                    "copertura":"Sorgente non disponibile; nessuno zero economico dedotto"}
            state="NON_DISPONIBILE"
            reason=("BUDGET_RICHIESTE" if isinstance(exc,_PublicBudgetReached)
                    else type(exc).__name__)
        source.append({"rete":key[0],"asset_tecnico":key[1],
                       "stato":state,"acquisito_utc":moment.isoformat(timespec="seconds"),
                       "motivo":reason,"richieste_effettuate":calls[0],**result})
        if state=="OSSERVATO" and result.get("detentori"):
            history[key]={"rete":key[0],"asset_tecnico":key[1],
                          "acquisito_utc":moment.isoformat(timespec="seconds"),
                          "detentori":result["detentori"][:20]}
    historic = [history[key] for key in sorted(history)[:MAX_HISTORY]
                if key in targets]
    return {"schema":SCHEMA,"acquisito_utc":moment.isoformat(timespec="seconds"),
            "sonde":source,"target_totali":len(targets),"target_interrogati":len(source),
            "richieste_effettuate":total_calls[0],
            "limite_richieste_refresh":MAX_PUBLIC_CALLS,
            "limite_richieste_target":MAX_CALLS_PER_TARGET,
            "storico_detentori":historic,
            "prossimo_target":("|".join(targets[(index+len(source))%len(targets)])
                               if targets else None),
            "limite":"Campione rotante di reti/contratti, non osservatorio completo, "
                     "nessun proprietario dedotto da un account; nessun segnale automatico."}


def at_read(raw, asset_rows, economics, now):
    """Rebind each indexed/native target to economic identity at GPT read-time."""
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA:
        raise ValueError("capital schema invalid")
    when=_ts(raw.get("acquisito_utc"))
    if when > now+dt.timedelta(minutes=2):
        raise ValueError("capital evidence from future")
    allowed=set(_targets(asset_rows))
    sources=raw.get("sonde")
    if (not isinstance(sources,list) or len(sources)>MAX_TARGETS or
            raw.get("target_totali")!=len(allowed) or
            raw.get("target_interrogati")!=len(sources)):
        raise ValueError("capital coverage mismatch")
    if (raw.get("limite_richieste_refresh") != MAX_PUBLIC_CALLS
            or raw.get("limite_richieste_target") != MAX_CALLS_PER_TARGET):
        raise ValueError("capital public request budget altered")
    bound={}
    for source in sources:
        if not isinstance(source,dict):
            raise ValueError("capital source malformed")
        key=(source.get("rete"),source.get("asset_tecnico"))
        if key not in allowed or key in bound or _ts(source.get("acquisito_utc"))!=when:
            raise ValueError("wrong contract or repeated capital target")
        bound[key]=source
        if source.get("stato") not in ("OSSERVATO","NON_DISPONIBILE"):
            raise ValueError("capital source state invalid")
        _nat(source.get("richieste_effettuate"), MAX_CALLS_PER_TARGET)
        events=source.get("eventi")
        holders=source.get("detentori")
        if (not isinstance(events,list) or len(events)>MAX_EVENTS or
                not isinstance(holders,list) or len(holders)>20):
            raise ValueError("capital sample exceeds bound")
        seen=set()
        for ev in events:
            if not isinstance(ev,dict) or ev.get("rete")!=key[0] or ev.get("asset_tecnico")!=key[1]:
                raise ValueError("capital event bound wrong")
            if not isinstance(ev.get("tx"),str) or not ev["tx"] or len(ev["tx"])>110:
                raise ValueError("capital tx invalid")
            evkey=(ev["tx"],str(ev.get("indice")))
            if evkey in seen:
                raise ValueError("duplicate capital event")
            seen.add(evkey)
            if (_quantity(ev.get("unita_minima"),ev.get("decimali"))!=ev.get("quantita")
                    or not isinstance(ev.get("fonte"),str)):
                raise ValueError("capital event amount/source invalid")
            import kdd_network_defi as net
            expected = (_routescan_urls(key[0],key[1])[0]
                        if key[0]=="avalanche" and key[1]!="NATIVE"
                        else net.CONTRACT_ENDPOINTS[key[0]] if key[1]!="NATIVE"
                        else net.NATIVE_ENDPOINTS.get(key[0],
                            net.SOL_URL if key[0]=="solana" else net.SUI_URL))
            indexed_url = ETH_EXPLORER + "/api/v2/tokens/" + key[1] + "/transfers"
            block_prefix = "https://blockstream.info/api/block/"
            ethplorer_url = (ETHPLORER + "/getTokenHistory/" + key[1]
                             + "?apiKey=freekey&limit=" + str(ETHPLORER_HISTORY_LIMIT))
            binplorer_url = (BINPLORER + "/getTokenHistory/" + key[1]
                             + "?apiKey=freekey&limit=" + str(ETHPLORER_HISTORY_LIMIT))
            routescan_url = _routescan_urls(key[0],key[1])[0] if key[0] in ROUTESCAN_CHAINS and key[1]!="NATIVE" else None
            if ev["fonte"] != expected and not (key[0]=="bitcoin" and
                ev["fonte"].startswith(block_prefix) and ev["fonte"].endswith("/txs")) and not (
                key[0]=="ethereum" and key[1]!="NATIVE" and
                ev["fonte"] in (indexed_url, ethplorer_url)) and not (
                key[0]=="bsc" and key[1]!="NATIVE" and ev["fonte"]==binplorer_url) and not (
                key[0]=="solana" and key[1]!="NATIVE" and ev["fonte"]==SOLANA_ALT_RPC) and not (
                key[0] in ROUTESCAN_CHAINS and key[1]!="NATIVE" and ev["fonte"]==routescan_url):
                raise ValueError("event source incompatible with chain/contract")
            labels=ev.get("attribuzione")
            if not isinstance(labels,dict) or set(labels)!={"da","a"}:
                raise ValueError("source labels missing")
            for label in labels.values():
                if not isinstance(label,dict) or label.get("stato") not in (
                        "ENTITA_NON_IDENTIFICATA","ETICHETTA_PUBBLICA"):
                    raise ValueError("invalid attributed entity")
                if label["stato"]=="ETICHETTA_PUBBLICA" and (
                        key[0]!="ethereum" or
                        label.get("fonte")!=ETH_EXPLORER+"/api/v2/" or
                        label.get("classe") not in ("EXCHANGE","CUSTODE","FONDO",
                                                   "TESORERIA","PROTOCOLLO","MARKET_MAKER")):
                    raise ValueError("exchange/institution provenance invalid")
            if ev.get("orario_utc") is not None and _ts(ev["orario_utc"])>when+dt.timedelta(minutes=2):
                raise ValueError("future event")
        for h in holders:
            if not isinstance(h,dict) or not isinstance(h.get("account"),str):
                raise ValueError("holder identity invalid")
            _quantity(h.get("unita_minima"),h.get("decimali"))
        if source["stato"]=="NON_DISPONIBILE" and (events or holders):
            raise ValueError("unavailable source cannot carry metrics")
    if (raw.get("richieste_effettuate") != sum(s["richieste_effettuate"] for s in sources)
            or _nat(raw.get("richieste_effettuate")) > MAX_PUBLIC_CALLS):
        raise ValueError("capital request counts inconsistent")
    age=now-when
    fresh=dt.timedelta(minutes=-2)<=age<=dt.timedelta(minutes=30)
    def interpret(group):
        enriched=[]
        for row,econ in zip(asset_rows[group],economics[group]):
            refs=[]
            import kdd_network_defi as net
            n=net.NATIVE_IDS.get(row.get("progetto_id"))
            if n and n[0]==row["token"] and n[1] in SUPPORTED:
                refs.append((n[1],"NATIVE"))
            refs.extend((c["rete"],c["contratto"]) for c in row["contratti_indicizzati"]
                        if c["rete"] in ("ethereum","bsc","solana","avalanche"))
            observations=[]
            fundamentals=econ.get("fondamentali") if isinstance(econ,dict) else {}
            supply=fundamentals.get("offerta_circolante") if isinstance(fundamentals,dict) else None
            cap=fundamentals.get("capitalizzazione_usd") if isinstance(fundamentals,dict) else None
            price=None
            if (isinstance(supply,(int,float)) and supply>0 and
                    isinstance(cap,(int,float)) and cap>0 and
                    fundamentals.get("stato")=="VERIFICATO"):
                price=Decimal(str(cap))/Decimal(str(supply))
            for key in refs:
                record=bound.get(key)
                if record is None:
                    observations.append({"rete":key[0],"asset_tecnico":key[1],
                                         "stato":"RINVIATO_BUDGET","eventi":[],
                                         "detentori":[],"copertura":"Target atteso, non interrogato in questo ciclo"})
                    continue
                events=[]
                quantities = sorted(Decimal(e["quantita"]) for e in record["eventi"])
                middle = quantities[len(quantities)//2] if len(quantities)>=3 else None
                for item in record["eventi"]:
                    event_age = now-_ts(item["orario_utc"]) if item.get("orario_utc") else None
                    relative = (str((Decimal(item["quantita"])/middle).quantize(Decimal(".01")))
                                if middle is not None and middle>0 else None)
                    if (not fresh or record["stato"]!="OSSERVATO" or
                            (event_age is not None and event_age>dt.timedelta(minutes=30))):
                        events.append(dict(item,stato_alla_lettura="STORICO",
                                           rapporto_mediana_campione=relative,
                                           valore_usd_indicativo=None))
                        continue
                    quantity=Decimal(item["quantita"])
                    value=(str((quantity*price).quantize(Decimal(".01"))) if price is not None else None)
                    events.append(dict(item,stato_alla_lettura="CAMPIONE_RECENTE",
                                       rapporto_mediana_campione=relative,
                                       valore_usd_indicativo=value,
                                       fonte_valutazione=(fundamentals.get("fonte") if value else None),
                                       limite_valutazione="Marketcap/supply CoinGecko = prezzo implicito indicativo, non esecuzione" if value else None))
                exchange={"ingresso_unita_minima":0,"uscita_unita_minima":0,
                          "movimenti_interni_unita_minima":0,"eventi_ingresso":0,
                          "eventi_uscita":0,"eventi_interni":0}
                for event in events:
                    if (event.get("stato_alla_lettura")!="CAMPIONE_RECENTE"
                            or event.get("tipo")!="TRASFERIMENTO"):
                        continue
                    labels=event.get("attribuzione") or {}
                    left=labels.get("da") or {}
                    right=labels.get("a") or {}
                    incoming=right.get("classe")=="EXCHANGE" and right.get("stato")=="ETICHETTA_PUBBLICA"
                    outgoing=left.get("classe")=="EXCHANGE" and left.get("stato")=="ETICHETTA_PUBBLICA"
                    if incoming and outgoing and left.get("etichetta")==right.get("etichetta"):
                        exchange["movimenti_interni_unita_minima"]+=int(event["unita_minima"])
                        exchange["eventi_interni"]+=1
                    else:
                        if incoming:
                            exchange["ingresso_unita_minima"]+=int(event["unita_minima"])
                            exchange["eventi_ingresso"]+=1
                        if outgoing:
                            exchange["uscita_unita_minima"]+=int(event["unita_minima"])
                            exchange["eventi_uscita"]+=1
                # ERC-20 concentration can be expressed as a share only when
                # the already-acquired totalSupply belongs to this exact
                # chain+contract and is still usable at read-time.
                contract_supply = None
                if key[1]!="NATIVE":
                    for candidate in row.get("osservazioni_contratti", []):
                        if (candidate.get("rete"),candidate.get("contratto")) != key:
                            continue
                        observed = candidate.get("osservazione") or {}
                        vals = observed.get("valori") or {}
                        if observed.get("stato")=="OSSERVATO_CON_LIMITI":
                            try:
                                denom=_nat(vals.get("supply_unita_minima"))
                                contract_supply=denom if denom>0 else None
                            except (ValueError,TypeError):
                                pass
                holders_read = []
                for holder in record["detentori"]:
                    h=dict(holder)
                    if key[0] in ("ethereum","bsc"):
                        amount=int(h["unita_minima"])
                        h["quota_supply_pct"]=(str((Decimal(amount)/Decimal(contract_supply)*100)
                                                    .quantize(Decimal(".0001")))
                                                if contract_supply and amount<=contract_supply else None)
                        h["denominatore_quota"]="SUPPLY_CONTRATTO_ONCHAIN" if h["quota_supply_pct"] else None
                    holders_read.append(h)
                recognized=sum(1 for ev in events if ev.get("stato_alla_lettura")=="CAMPIONE_RECENTE"
                               if any(v.get("stato")=="ETICHETTA_PUBBLICA"
                                      for v in (ev.get("attribuzione") or {}).values()
                                      if isinstance(v,dict)))
                observations.append({"rete":key[0],"asset_tecnico":key[1],
                                     "stato":("OSSERVATO_CON_LIMITI" if fresh and record["stato"]=="OSSERVATO"
                                              else "STORICO" if record["stato"]=="OSSERVATO" else "NON_DISPONIBILE"),
                                     "eventi":events,"detentori":holders_read,
                                     "operatori_etichettati_nel_campione":recognized,
                                     "flussi_exchange_campione":(dict(exchange,
                                         flusso_netto_unita_minima=(exchange["ingresso_unita_minima"]-
                                                                   exchange["uscita_unita_minima"]),
                                         stato="CAMPIONE_ETICHETTATO_PARZIALE",
                                         fonte="ETICHETTE_PUBBLICHE_BLOCKSCOUT",
                                         limite="Non rappresenta flussi exchange globali, deposito non significa vendita")
                                         if fresh and record["stato"]=="OSSERVATO" and (
                                             exchange["eventi_ingresso"] + exchange["eventi_uscita"]
                                             + exchange["eventi_interni"]) > 0 else
                                         {"stato":"NON_ATTRIBUIBILE_O_STORICO",
                                          "ingresso_unita_minima":None,"uscita_unita_minima":None,
                                          "flusso_netto_unita_minima":None,
                                          "limite":"Assenza di indirizzi exchange etichettati o campione scaduto: NON zero"}),
                                     "aggregato_detentori": (dict(record["aggregato_detentori"],
                                          stato_alla_lettura="RECENTE" if fresh else "STORICO")
                                          if isinstance(record.get("aggregato_detentori"),dict) else None),
                                      "detentori_top_somma_unita_minima":(str(sum(int(h["unita_minima"]) for h in record["detentori"]))
                                          if record["detentori"] else None),
                                     "periodo":record.get("periodo"),
                                     "acquisito_utc":record["acquisito_utc"],
                                     "copertura":record.get("copertura"),
                                     "nota_economica":("Esaminare grandezza relativa e condizioni di liquidita; "
                                                       "un deposito exchange non equivale a vendita"),
                                     "controipotesi":"Custodia, trasferimento interno, OTC, resto UTXO, bridge, mint/burn",
                                     "condizione_riesame":"Confrontare campioni successivi e dati mercato prima di rivedere la tesi"})
            enriched.append({"token":row["token"],"progetto_id":row.get("progetto_id"),
                             "coppia_analisi":row.get("coppia_analisi"),
                             "contratto_ufficiale":"NON_ATTESTATO",
                             "osservazioni":observations})
        return enriched
    return {"schema":SCHEMA,"acquisito_utc":raw["acquisito_utc"],
            "stato":"OSSERVAZIONE_CAMPIONARIA",
            "posizioni":interpret("posizioni"),"candidati":interpret("candidati"),
            "target_totali":len(allowed),"target_interrogati":len(bound),
            "limite":raw["limite"]}
