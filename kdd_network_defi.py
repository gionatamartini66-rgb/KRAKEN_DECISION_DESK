"""KDD-16/17/19: bounded PUBLIC network/DeFi observations for the existing GPT dossier.

The network name is not proof that a private holding sits on that chain.
P08/P09: endpoint URL, HTTPS and a packet digest do NOT authenticate upstream.
No keys, addresses, transactions, wallet balances, attribution or orders.
"""
from __future__ import annotations
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import re
import threading
import time
import urllib.request

UTC = dt.timezone.utc
SCHEMA = "kdd_network_defi_v001"
SUI_URL = "https://graphql.mainnet.sui.io/graphql"
SOL_URL = "https://api.mainnet-beta.solana.com"
CHAIN_URL = "https://api.llama.fi/v2/chains"
DEX_URL = ("https://api.llama.fi/overview/dexs/Sui"
           "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true")
SUI_QUERY = ("query { checkpoint { sequenceNumber networkTotalTransactions timestamp } "
             "epoch { epochId referenceGasPrice } }")
SOURCES = {"sui": SUI_URL, "solana": SOL_URL, "chain_tvl": CHAIN_URL,
           "dex_sui": DEX_URL}
KEYS = ("sui", "solana", "chain_tvl", "dex_sui")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,19}\Z")
MAX_RESPONSE = 2_000_000
# RpcNode public Ethereum: 1 request/second/IP, shared best-effort service.
# https://rpcnode.dev/public-nodes (no API key; HTTP 429 on excess)
ETH_PUBLIC_RPC = "https://public-ethereum-mainnet.rpcnode.dev"
_ETH_RPC_LOCK = threading.Lock()
_ETH_RPC_NEXT_AT = 0.0
# Routescan public keyless tier: 2 rps; process-wide 0.55s between calls.
_ROUTESCAN_LOCK = threading.Lock()
_ROUTESCAN_NEXT_AT = 0.0


def _now(value):
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise ValueError("UTC timestamp missing")
    return value.astimezone(UTC)


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("source timestamp absent")
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("source timestamp naive")
    return stamp.astimezone(UTC)


def _integer(value):
    if isinstance(value, bool) or not (type(value) is int or
            isinstance(value, str) and re.fullmatch(r"[0-9]{1,25}", value)):
        raise ValueError("unsigned on-chain integer required")
    n = int(value)
    if not 0 <= n <= 10**23:
        raise ValueError("on-chain integer outside bound")
    return n


def _number(value):
    if isinstance(value, bool) or type(value) not in (int, float, str):
        raise ValueError("invalid economic quantity")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid decimal") from None
    if not n.is_finite() or n < 0 or n > Decimal("1e18"):
        raise ValueError("invalid or absurd quantity")
    return n


def _http(url, payload=None):
    """Only exact literal public endpoints supplied by the caller, bounded response."""
    request = urllib.request.Request(
        url, data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    if url == ETH_PUBLIC_RPC:
        # Enforce public-provider fair use across native and ERC-20 calls in
        # this process. Another process/IP user may still trigger HTTP 429;
        # preserve fail-closed errors rather than retrying or hiding them.
        global _ETH_RPC_NEXT_AT
        with _ETH_RPC_LOCK:
            pause = _ETH_RPC_NEXT_AT - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            _ETH_RPC_NEXT_AT = time.monotonic() + 1.05
    if url.startswith("https://api.routescan.io/v2/network/mainnet/evm/"):
        global _ROUTESCAN_NEXT_AT
        with _ROUTESCAN_LOCK:
            pause = _ROUTESCAN_NEXT_AT-time.monotonic()
            if pause>0:
                time.sleep(pause)
            _ROUTESCAN_NEXT_AT=time.monotonic()+0.55
    with urllib.request.urlopen(request, timeout=9) as response:
        if response.geturl() != url:
            raise ValueError("public source redirect rejected")
        raw = response.read(MAX_RESPONSE+1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("response exceeds bound")
    return json.loads(raw.decode("utf-8"))


def _roster(positions, *, candidate=False):
    if not isinstance(positions, list) or len(positions) > 200:
        raise ValueError("roster malformed")
    rows = []
    for row in positions:
        if not isinstance(row, dict):
            raise ValueError("row malformed")
        symbol = row.get("token")
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            # Invalid identities remain a missing row, not an invented chain.
            symbol = None
        entry = {"token": symbol}
        if candidate:
            pair = row.get("coppia_analisi", row.get("coppia"))
            entry["coppia_analisi"] = pair if isinstance(pair, str) else None
        rows.append(entry)
    return rows


def collect(now, positions, candidates, *, fetch=None):
    """Bounded public acquisitions; independent source failure never drops an asset."""
    instant = _now(now)
    fetch = fetch or _http
    owned = _roster(positions)
    external = _roster(candidates, candidate=True)
    relevant = {x["token"] for x in owned + external}
    sources = {}
    for key, url in SOURCES.items():
        needed = (("SUI" in relevant) if key in ("sui", "dex_sui")
                  else ("SOL" in relevant) if key == "solana"
                  else bool(relevant & {"SUI", "SOL"}))
        source = {"fonte": url, "stato": "NON_ACQUISITO",
                  "osservato_utc": None, "valori": None, "motivo": "ASSET_NON_PRESENTE"}
        if not needed:
            sources[key] = source
            continue
        try:
            if key == "sui":
                response = fetch(url, {"query": SUI_QUERY})
                if (not isinstance(response, dict) or response.get("errors")
                        or not isinstance(response.get("data"), dict)):
                    raise ValueError("Sui GraphQL errors")
                checkpoint = response["data"].get("checkpoint")
                epoch = response["data"].get("epoch")
                if not isinstance(checkpoint, dict) or not isinstance(epoch, dict):
                    raise ValueError("Sui checkpoint/epoch absent")
                observed = _timestamp(checkpoint.get("timestamp"))
                if observed > instant + dt.timedelta(minutes=2):
                    raise ValueError("future checkpoint")
                values = {"checkpoint": _integer(checkpoint.get("sequenceNumber")),
                          "transazioni_cumulative": _integer(
                              checkpoint.get("networkTotalTransactions")),
                          "epoch": _integer(epoch.get("epochId")),
                          "gas_price_mist": _integer(epoch.get("referenceGasPrice"))}
                source.update(stato="OSSERVATO", osservato_utc=observed.isoformat(),
                              valori=values, motivo=None)
            elif key == "solana":
                response = fetch(url, {"jsonrpc": "2.0", "id": 1,
                                       "method": "getSupply",
                                       "params": [{"commitment": "finalized",
                                                   "excludeNonCirculatingAccountsList": True}]})
                if (not isinstance(response, dict) or response.get("error")
                        or response.get("id") != 1):
                    raise ValueError("Solana RPC error")
                result = response.get("result")
                if not isinstance(result, dict) or not isinstance(result.get("value"), dict):
                    raise ValueError("Solana supply absent")
                value = result["value"]
                total = _integer(value.get("total"))
                circulating = _integer(value.get("circulating"))
                noncirc = _integer(value.get("nonCirculating"))
                if not total or circulating+noncirc != total:
                    raise ValueError("Solana supply inconsistent")
                source.update(stato="OSSERVATO", valori={
                    "slot_finalized": _integer(result.get("context", {}).get("slot")),
                    "totale_sol": str(Decimal(total)/Decimal(10**9)),
                    "circolante_sol": str(Decimal(circulating)/Decimal(10**9)),
                    "non_circolante_sol": str(Decimal(noncirc)/Decimal(10**9))},
                    motivo=None)
            elif key == "chain_tvl":
                response = fetch(url)
                if not isinstance(response, list) or len(response)>1000:
                    raise ValueError("DefiLlama chain list invalid")
                values = {}
                for row in response:
                    if isinstance(row, dict) and row.get("name") in ("Sui", "Solana"):
                        if row["name"] in values:
                            raise ValueError("duplicate DefiLlama chain")
                        values[row["name"]] = str(_number(row.get("tvl")))
                if not values:
                    raise ValueError("no target chains in DefiLlama")
                source.update(stato="OSSERVATO", valori=values, motivo=None)
            else:
                response = fetch(url)
                if not isinstance(response, dict) or (response.get("chain") not in (None, "Sui")):
                    raise ValueError("Sui DEX family not attributable")
                source.update(stato="OSSERVATO", valori={
                    "volume_dex_24h_usd": str(_number(response.get("total24h"))),
                    "volume_dex_7d_usd": str(_number(response.get("total7d")))},
                    motivo=None)
        except (OSError, ValueError, TypeError, KeyError, OverflowError,
                UnicodeError, json.JSONDecodeError) as exc:
            source.update(stato="NON_DISPONIBILE", valori=None,
                          motivo=type(exc).__name__)
        sources[key] = source
    return {"schema": SCHEMA, "acquisito_utc": instant.isoformat(timespec="seconds"),
            "roster_posizioni": owned, "roster_candidati": external,
            "fonti": sources, "nessuna_attribuzione_wallet": True,
            "limite_provenienza": "P08/P09: URL/TLS e SHA del pacchetto non autenticano l'upstream."}


def _read_source(key, row, acquired, now):
    if not isinstance(row, dict) or row.get("fonte") != SOURCES[key]:
        raise ValueError("source URL mismatched")
    state = row.get("stato")
    if state not in ("OSSERVATO", "NON_DISPONIBILE", "NON_ACQUISITO"):
        raise ValueError("unknown source state")
    stamp = row.get("osservato_utc")
    observed = _timestamp(stamp) if stamp is not None else None
    if observed and observed > acquired + dt.timedelta(minutes=2):
        raise ValueError("source time after collection")
    values = row.get("valori")
    if state != "OSSERVATO":
        if values is not None or observed is not None:
            raise ValueError("unavailable source carries invented values")
        return {"stato": state, "fonte": SOURCES[key], "valori": None,
                "osservato_utc": None, "motivo": row.get("motivo")}
    if not isinstance(values, dict):
        raise ValueError("source metrics absent")
    if key == "sui":
        if set(values) != {"checkpoint","transazioni_cumulative","epoch","gas_price_mist"} or not observed:
            raise ValueError("Sui schema invalid")
        metrics = {x: _integer(y) for x,y in values.items()}
        fresh = dt.timedelta(minutes=-2) <= now-observed <= dt.timedelta(minutes=30)
    elif key == "solana":
        if set(values) != {"slot_finalized","totale_sol","circolante_sol","non_circolante_sol"} or observed:
            raise ValueError("Solana schema invalid")
        metrics = {"slot_finalized": _integer(values["slot_finalized"])}
        for x in ("totale_sol","circolante_sol","non_circolante_sol"):
            metrics[x] = str(_number(values[x]))
        if (Decimal(metrics["circolante_sol"])+Decimal(metrics["non_circolante_sol"])
                != Decimal(metrics["totale_sol"]) or Decimal(metrics["totale_sol"])<=0):
            raise ValueError("Solana supply incoherent")
        fresh = dt.timedelta(minutes=-2)<=now-acquired<=dt.timedelta(minutes=30)
    elif key == "chain_tvl":
        if not values or set(values)-{"Sui","Solana"} or observed:
            raise ValueError("chain/TVL source malformed")
        metrics = {name: str(_number(value)) for name,value in values.items()}
        fresh = dt.timedelta(minutes=-2)<=now-acquired<=dt.timedelta(minutes=30)
    else:
        if set(values)!={"volume_dex_24h_usd","volume_dex_7d_usd"} or observed:
            raise ValueError("DEX schema invalid")
        metrics = {x: str(_number(v)) for x,v in values.items()}
        fresh = dt.timedelta(minutes=-2)<=now-acquired<=dt.timedelta(minutes=30)
    return {"stato": "OSSERVATO_CON_LIMITI" if fresh else "SCADUTO",
            "fonte": SOURCES[key], "valori": metrics if fresh else None,
            "osservato_utc": observed.isoformat() if observed else None,
            "motivo": None if fresh else "MISURA_NON_PIU_RECENTE"}


def _economic_row(row, sources, acquired):
    token = row["token"]
    on_key = "sui" if token == "SUI" else "solana" if token == "SOL" else None
    chain = "Sui" if token == "SUI" else "Solana" if token == "SOL" else None
    if on_key is None:
        return dict(row, onchain={"stato": "NON_COPERTO", "valori": None,
                                 "limite": "Nessuna identita blockchain attribuita al token"},
                    defi={"stato":"NON_COPERTO","valori":None,
                          "limite":"Nessuna chain DeFi attribuita al token"})
    on = dict(sources[on_key],
              copertura=("Checkpoint e transazioni cumulative Sui mainnet (NON wallet/whale)"
                         if token == "SUI" else
                         "Supply SOL su mainnet RPC, NON importi Kraken o staking attestato"),
              limite="Osservazione della rete; nessun address label, wallet o vendita attribuiti.",
              ipotesi="L'attivita della rete e la supply possono cambiare la valutazione del rischio.",
              controipotesi="Aumento dei contatori di rete non prova domanda del token, ne domanda istituzionale.",
              condizione_riesame="Confrontare due rilevazioni datate e verificare reti e partecipazione.")
    defi = sources["chain_tvl"]
    tvl = defi["valori"].get(chain) if defi["valori"] else None
    defi_values = {"tvl_chain_usd": tvl,
                   "volume_dex_24h_sui_usd": sources["dex_sui"]["valori"].get("volume_dex_24h_usd")
                   if token == "SUI" and sources["dex_sui"]["valori"] else None}
    defi_state = ("OSSERVATO_CON_LIMITI" if tvl is not None else
                  defi["stato"] if defi["stato"] != "OSSERVATO_CON_LIMITI" else
                  "NON_DISPONIBILE")
    comparison = None
    if token=="SUI" and tvl is not None and defi_values["volume_dex_24h_sui_usd"] is not None and Decimal(tvl)>0:
        comparison = str((Decimal(defi_values["volume_dex_24h_sui_usd"])/
                          Decimal(tvl)*100).quantize(Decimal("0.001")))
    return dict(row, onchain=on,
                defi={"stato": defi_state, "fonte": CHAIN_URL,
                      "fonte_dex": DEX_URL if token == "SUI" else None,
                      "acquisito_utc": acquired.isoformat(),
                      "timestamp_upstream_utc": None,
                      "valori": defi_values if tvl is not None else None,
                      "volume_dex24h_su_tvl_chain_pct": comparison,
                      "copertura": "TVL aggregato della chain; NON TVL di protocollo, prezzo o market cap del token",
                      "ipotesi": "Variazioni nel tempo di TVL/volumi DEX potrebbero modificare la tesi di adozione.",
                      "controipotesi": "TVL in USD varia con i prezzi e non equivale a domanda netta del token.",
                      "condizione_riesame": "Verificare serie storiche, timestamp a monte, protocolli e liquidita DEX.",
                      "limite": "DefiLlama aggregatore senza timestamp upstream per questa risposta; "
                                "il rapporto DEX/TVL confronta grandezze non omogenee, NON un segnale."})


def at_read(source, positions, candidates, now):
    """Revalidate source semantics and time, preserve ALL rows in packet/bridge."""
    moment = _now(now)
    owned, external = _roster(positions), _roster(candidates,candidate=True)
    if source is None or (isinstance(source, dict) and
                           source.get("schema")==SCHEMA and
                           source.get("stato")=="NON_ACQUISITO" and
                           "sorgente" not in source):
        return {"schema": SCHEMA, "stato":"NON_ACQUISITO",
                "posizioni":[_economic_row(x, {k:{"stato":"NON_ACQUISITO",
                          "valori":None,"fonte":SOURCES[k]} for k in KEYS},moment) for x in owned],
                "candidati":[_economic_row(x, {k:{"stato":"NON_ACQUISITO",
                          "valori":None,"fonte":SOURCES[k]} for k in KEYS},moment) for x in external],
                "limite":"Evidenza rete/DeFi non presente nel dossier legacy"}
    raw = source.get("sorgente") if isinstance(source,dict) and "sorgente" in source else source
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA or raw.get("nessuna_attribuzione_wallet") is not True:
        raise ValueError("network/DeFi source schema or privacy attribution")
    if raw.get("limite_provenienza") != "P08/P09: URL/TLS e SHA del pacchetto non autenticano l'upstream.":
        raise ValueError("upstream trust claim altered")
    acquired = _timestamp(raw.get("acquisito_utc"))
    if acquired > moment + dt.timedelta(minutes=2):
        raise ValueError("network acquisition in future")
    if raw.get("roster_posizioni") != owned or raw.get("roster_candidati") != external:
        raise ValueError("network roster does not match packet")
    if not isinstance(raw.get("fonti"),dict) or set(raw["fonti"])!=set(KEYS):
        raise ValueError("network sources incomplete")
    sources={key:_read_source(key,raw["fonti"][key],acquired,moment) for key in KEYS}
    return {"schema":SCHEMA,"stato":"EVIDENZE_CON_LIMITI",
            "acquisito_utc":raw["acquisito_utc"],
            "sorgente":raw,
            "posizioni":[_economic_row(x,sources,acquired) for x in owned],
            "candidati":[_economic_row(x,sources,acquired) for x in external],
            "limite":"Reti/TVL pubblici, nessuna attribuzione al portafoglio privato; "
                     "provenienza P08/P09 non autenticata e metriche da confrontare nel tempo."}


# KDD-17 G2/1: project-bound native chain and contract probes.
# CoinGecko metadata is an attributed INDEX, not proof of origin or custody.
# A network RPC can observe a contract, but cannot prove Kraken's custody chain.
ASSET_SCHEMA = "kdd-asset-network-v001"
NATIVE_IDS = {
    "bitcoin": ("BTC", "bitcoin"), "ethereum": ("ETH", "ethereum"),
    "binancecoin": ("BNB", "bsc"), "near": ("NEAR", "near"),
    "ripple": ("XRP", "xrpl"), "solana": ("SOL", "solana"),
    "sui": ("SUI", "sui"),
}
PLATFORM_CHAINS = {"ethereum": "ethereum", "binance-smart-chain": "bsc",
                   "solana": "solana", "avalanche": "avalanche"}
# Avalanche token index is acquired by a verified free Routescan page;
# no Avalanche RPC contract supply probe is implied or required.
# Public endpoint/reference specifications (responses never authenticated by TLS alone):
# BTC: https://github.com/Blockstream/esplora/blob/master/API.md
# BSC: https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/
# Solana SPL: https://solana.com/docs/rpc/http/gettokensupply
# XRPL: https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/ledger-methods/ledger
# Ethereum JSON-RPC: https://ethereum.org/en/developers/docs/apis/json-rpc/
# NEAR: https://docs.near.org/api/rpc/block
NATIVE_ENDPOINTS = {
    "bitcoin": "https://blockstream.info/api/blocks",
    "ethereum": ETH_PUBLIC_RPC,
    "bsc": "https://bsc-dataseed.bnbchain.org",
    "near": "https://rpc.mainnet.near.org",
    "xrpl": "https://s1.ripple.com:51234",
}
CONTRACT_ENDPOINTS = {"ethereum": NATIVE_ENDPOINTS["ethereum"],
                      "bsc": NATIVE_ENDPOINTS["bsc"], "solana": SOL_URL}
EVM_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
SOL_MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")
CG_DETAILS = "https://api.coingecko.com/api/v3/coins/"
MAX_CONTRACT_PROBES = 2
MAX_NATIVE_SOURCES = 5


def _qualified(identity, token):
    """Economic identity (Kraken exact pair -> project ID), not ticker alone."""
    return bool(isinstance(identity, dict)
                and identity.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO"
                and identity.get("token") == token
                and isinstance(identity.get("coingecko_id"), str)
                and re.fullmatch(r"[a-z0-9-]{2,120}", identity["coingecko_id"])
                and isinstance(identity.get("coppia"), str)
                and isinstance(identity.get("pair_key"), str)
                and identity.get("fonte_identita"))


def _supply_integer(value):
    if isinstance(value, bool) or not (type(value) is int or
            isinstance(value, str) and re.fullmatch(r"[0-9]{1,46}", value)):
        raise ValueError("contract supply integer required")
    n = int(value)
    if not 0 <= n <= 10**45:
        raise ValueError("contract supply outside bound")
    return n


def _contract_address(chain, address):
    return (isinstance(address, str) and
            bool((EVM_ADDRESS if chain in ("ethereum", "bsc", "avalanche")
                  else SOL_MINT if chain == "solana"
                  else re.compile(r"(?!)")).fullmatch(address)))


def coin_network_metadata(identity, payload, now):
    """Extract bounded, untrusted network INDEX from an already-paid-for /coins ID fetch.

    No extra CoinGecko query. Only an economically resolved Kraken project ID may
    consume a matching CoinGecko /coins response. Missing/malformed data stays missing.
    """
    token = identity.get("token") if isinstance(identity, dict) else None
    if not _qualified(identity, token) or not isinstance(payload, dict):
        return None
    import kdd_economics
    if (payload.get("id") != identity["coingecko_id"]
            or not isinstance(payload.get("symbol"), str)
            or payload["symbol"].upper() != kdd_economics.canonical_token(token)
            or payload.get("name") != identity.get("progetto")):
        return None
    platforms = payload.get("platforms")
    if not isinstance(platforms, dict) or len(platforms) > 40:
        return None
    contracts = []
    for platform, address in sorted(platforms.items()):
        chain = PLATFORM_CHAINS.get(platform)
        if chain and _contract_address(chain, address):
            contracts.append({"rete": chain, "platform_id": platform,
                              "contratto": address})
    if len(contracts) > 12:
        return None
    return {"stato": "INDICE_COIN_GECKO", "token": token,
            "coingecko_id": identity["coingecko_id"],
            "coppia": identity["coppia"], "pair_key": identity["pair_key"],
            "fonte": CG_DETAILS + identity["coingecko_id"],
            "acquisito_utc": _now(now).isoformat(timespec="seconds"),
            "contratti": contracts, "piattaforme_dichiarate": len(platforms),
            "limite": "Indici CoinGecko, non attestazione primaria di contratto, bridge o rete di deposito Kraken"}


def _metadata_valid(metadata, identity, acquired):
    if not isinstance(metadata, dict) or not _qualified(identity, metadata.get("token")):
        return False
    if (metadata.get("stato") != "INDICE_COIN_GECKO"
            or metadata.get("coingecko_id") != identity["coingecko_id"]
            or metadata.get("coppia") != identity.get("coppia")
            or metadata.get("pair_key") != identity.get("pair_key")
            or metadata.get("fonte") != CG_DETAILS + identity["coingecko_id"]):
        return False
    try:
        stamp = _timestamp(metadata.get("acquisito_utc"))
    except (ValueError, TypeError):
        return False
    if not dt.timedelta(0) <= acquired-stamp <= dt.timedelta(days=1):
        return False
    contracts = metadata.get("contratti")
    return (isinstance(contracts, list) and len(contracts) <= 12
            and type(metadata.get("piattaforme_dichiarate")) is int
            and 0 <= metadata["piattaforme_dichiarate"] <= 40
            and all(isinstance(c, dict) and
                    c.get("rete") == PLATFORM_CHAINS.get(c.get("platform_id"))
                    and _contract_address(c.get("rete"), c.get("contratto"))
                    for c in contracts)
            and len({(c["rete"], c["contratto"]) for c in contracts}) == len(contracts))


def _asset_roster(economics, positions, candidates, moment):
    if not isinstance(economics, dict):
        raise ValueError("economic identity binding absent")
    rows = {}
    for name, source, expected in (("posizioni", economics.get("posizioni"), positions),
                                   ("candidati", economics.get("candidati"), candidates)):
        if not isinstance(source, list) or len(source) != len(expected):
            raise ValueError("economic roster differs from asset roster")
        values = []
        for i, (row, basis) in enumerate(zip(source, expected)):
            if not isinstance(row, dict) or row.get("token") != basis["token"] or row.get("indice") != i:
                raise ValueError("economic binding different from roster")
            if name == "candidati" and row.get("coppia_analisi") != basis["coppia_analisi"]:
                raise ValueError("candidate pair differs")
            identity = row.get("identita")
            qualified = _qualified(identity, basis["token"])
            profile = row.get("network_metadata")
            if profile is not None and (not qualified or not _metadata_valid(profile, identity, moment)):
                raise ValueError("unattributable contract metadata")
            native = NATIVE_IDS.get(identity.get("coingecko_id")) if qualified else None
            if native and native[0] != basis["token"]:
                native = None
            contracts = list(profile["contratti"]) if qualified and profile else []
            networks = sorted({x["rete"] for x in contracts} | ({native[1]} if native else set()))
            values.append({"token": basis["token"],
                           "coppia_analisi": basis.get("coppia_analisi") if name == "candidati" else None,
                           "progetto_id": identity["coingecko_id"] if qualified else None,
                           "fonte_identita": identity["fonte_identita"] if qualified else None,
                           "coppia_identita": identity["coppia"] if qualified else None,
                           "tipo": ("NON_VERIFICATO" if not qualified else
                                    "MULTICHAIN" if len(networks) > 1 else
                                    "NATIVO" if native and not contracts else
                                    "TOKEN_CON_CONTRATTO" if contracts else "RETE_NON_DOCUMENTATA"),
                           "reti_possibili": networks,
                           "contratti_indicizzati": contracts,
                           # CoinGecko is a candidate locator. An RPC response
                           # cannot certify project ownership of the address.
                           "ufficialita_contratto": "NON_ATTESTATA",
                           "verifica_contratto_fonte_primaria": "NON_ESEGUITA",
                           "rete_deposito_kraken": "NON_ATTESTATA",
                           "fonte_contratti": profile["fonte"] if profile else None,
                           "acquisito_metadati_utc": profile["acquisito_utc"] if profile else None,
                           "limite": ("Indici CoinGecko di reti/contratti POSSIBILI. "
                                      "La presenza di bytecode/supply su RPC NON certifica "
                                      "che il contratto sia ufficiale del progetto, "
                                      "ne attesta la rete di custodia Kraken.")})
        rows[name] = values
    return rows


def _native_observe(chain, fetch, now):
    url = NATIVE_ENDPOINTS[chain]
    try:
        if chain == "bitcoin":
            response = fetch(url)
            if not isinstance(response, list) or not response or not isinstance(response[0], dict):
                raise ValueError("BTC blocks invalid")
            block = response[0]
            height, count = _integer(block.get("height")), _integer(block.get("tx_count"))
            ts = dt.datetime.fromtimestamp(_integer(block.get("timestamp")), UTC)
            if not re.fullmatch(r"[0-9a-f]{64}", str(block.get("id"))):
                raise ValueError("BTC block hash invalid")
            values = {"altezza_blocco": height, "transazioni_blocco": count,
                      "blocco_hash": block["id"]}
            unit = "altezza, numero transazioni nel solo blocco"
        elif chain in ("ethereum", "bsc"):
            response = fetch(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber",
                                   "params": ["latest", False]})
            block = response.get("result") if isinstance(response, dict) and response.get("id") == 1 and not response.get("error") else None
            if not isinstance(block, dict):
                raise ValueError("EVM latest block invalid")
            height = int(block["number"], 16)
            ts = dt.datetime.fromtimestamp(int(block["timestamp"], 16), UTC)
            if not re.fullmatch(r"0x[0-9a-fA-F]{64}", str(block.get("hash"))):
                raise ValueError("EVM hash invalid")
            values = {"altezza_blocco": _integer(height), "blocco_hash": block["hash"]}
            unit = "altezza del blocco, non transazioni di wallet"
        elif chain == "near":
            response = fetch(url, {"jsonrpc": "2.0", "id": 1, "method": "block",
                                   "params": {"finality": "final"}})
            header = (response.get("result") or {}).get("header") if isinstance(response, dict) and response.get("id") == 1 and not response.get("error") else None
            if not isinstance(header, dict) or not isinstance(header.get("hash"), str) or len(header["hash"]) < 25:
                raise ValueError("NEAR final header invalid")
            height = _integer(header.get("height"))
            ts = dt.datetime.fromtimestamp(_integer(header.get("timestamp_nanosec")) / 10**9, UTC)
            values = {"altezza_blocco": height, "blocco_hash": header["hash"][:100]}
            unit = "altezza del blocco finalizzato"
        else:
            response = fetch(url, {"jsonrpc": "2.0", "id": 1, "method": "ledger",
                                   "params": [{"ledger_index": "validated", "transactions": False}]})
            # XRPL HTTP JSON-RPC can omit the response id; if supplied it
            # must still match our request. A successful result is not proof
            # of finality unless the server explicitly marks it validated.
            result = (response.get("result") if isinstance(response, dict)
                      and response.get("id", 1) == 1 and not response.get("error")
                      else None)
            ledger = result.get("ledger") if isinstance(result, dict) else None
            if (not isinstance(ledger, dict) or result.get("validated") is not True
                    or ledger.get("closed") is False
                    or response.get("status") not in (None, "success")
                    or result.get("status") not in (None, "success")
                    or not (response.get("status") == "success"
                            or result.get("status") == "success")):
                raise ValueError("XRP validated ledger invalid")
            index = _integer(result.get("ledger_index"))
            if (ledger.get("ledger_index") is not None
                    and _integer(ledger["ledger_index"]) != index):
                raise ValueError("XRP ledger index mismatch")
            ledger_hash = ledger.get("ledger_hash")
            if not isinstance(ledger_hash, str) or not re.fullmatch(r"[A-F0-9]{64}", ledger_hash):
                raise ValueError("XRP ledger hash invalid")
            if result.get("ledger_hash") is not None and result["ledger_hash"] != ledger_hash:
                raise ValueError("XRP ledger hash mismatch")
            ts = _timestamp(ledger.get("close_time_iso"))
            values = {"indice_ledger": index, "ledger_hash": ledger_hash}
            unit = "indice di ledger validato"
        if ts > now + dt.timedelta(minutes=2):
            raise ValueError("future block/ledger")
        return {"stato": "OSSERVATO", "fonte": url, "osservato_utc": ts.isoformat(),
                "valori": values, "unita": unit, "copertura": chain + " mainnet",
                "motivo": None}
    except (ValueError, KeyError, TypeError, OSError, OverflowError, UnicodeError) as exc:
        return {"stato": "NON_DISPONIBILE", "fonte": url, "osservato_utc": None,
                "valori": None, "unita": None, "copertura": chain + " mainnet",
                "motivo": type(exc).__name__}


def _probe_contract(chain, address, fetch, now):
    url = CONTRACT_ENDPOINTS[chain]
    blank = {"rete": chain, "contratto": address, "fonte": url,
             "osservato_utc": None, "acquisito_utc": now.isoformat(timespec="seconds"),
             "stato": "NON_DISPONIBILE", "valori": None, "motivo": None,
             "copertura": "Contratto/mint pubblico; NON movimenti, wallet o depositi Kraken",
             "ufficialita_contratto": "NON_ATTESTATA",
             "verifica_contratto_fonte_primaria": "NON_ESEGUITA"}
    try:
        if chain == "solana":
            response = fetch(url, {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply",
                                   "params": [address, {"commitment": "finalized"}]})
            if not isinstance(response, dict) or response.get("id") != 1 or response.get("error"):
                raise ValueError("SPL RPC error")
            result = response.get("result")
            value = result.get("value") if isinstance(result, dict) else None
            if not isinstance(value, dict) or type(value.get("decimals")) is not int or not 0 <= value["decimals"] <= 18:
                raise ValueError("SPL supply schema")
            values = {"slot_finalized": _integer(result.get("context", {}).get("slot")),
                      "supply_unita_minima": str(_supply_integer(value.get("amount"))),
                      "decimali": value["decimals"], "unita": "mint SPL base units"}
        else:
            response = fetch(url, {"jsonrpc": "2.0", "id": 1,
                                   "method": "eth_getCode", "params": [address, "latest"]})
            code = response.get("result") if isinstance(response, dict) and response.get("id") == 1 and not response.get("error") else None
            if not isinstance(code, str) or code == "0x" or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code):
                raise ValueError("EVM contract code missing")
            response = fetch(url, {"jsonrpc": "2.0", "id": 1,
                                   "method": "eth_call",
                                   "params": [{"to": address, "data": "0x18160ddd"}, "latest"]})
            quantity = response.get("result") if isinstance(response, dict) and response.get("id") == 1 and not response.get("error") else None
            if not isinstance(quantity, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", quantity):
                raise ValueError("ERC20 totalSupply unavailable")
            values = {"supply_unita_minima": str(_supply_integer(int(quantity, 16))),
                      "unita": "ERC20 contract base units; decimals not established"}
        return dict(blank, stato="OSSERVATO", valori=values)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, UnicodeError) as exc:
        return dict(blank, motivo=type(exc).__name__)


def _collect_assets(now, positions, candidates, economic, previous, fetch):
    rows = _asset_roster(economic, positions, candidates, now)
    native = sorted({NATIVE_IDS[r["progetto_id"]][1] for family in rows.values()
                     for r in family if r["progetto_id"] in NATIVE_IDS
                     and NATIVE_IDS[r["progetto_id"]][0] == r["token"]
                     and NATIVE_IDS[r["progetto_id"]][1] in NATIVE_ENDPOINTS})
    sources = {chain: _native_observe(chain, fetch, now)
               for chain in native[:MAX_NATIVE_SOURCES]}
    contracts = sorted({(c["rete"], c["contratto"])
                        for family in rows.values() for r in family
                        for c in r["contratti_indicizzati"]
                        if c["rete"] in CONTRACT_ENDPOINTS})
    prior_cursor = previous.get("prossimo_contratto") if isinstance(previous, dict) else None
    start = next((i for i,x in enumerate(contracts) if "|".join(x) >= prior_cursor),
                 0) if isinstance(prior_cursor, str) else 0
    selected = [contracts[(start+i) % len(contracts)]
                for i in range(min(MAX_CONTRACT_PROBES, len(contracts)))]
    probes = [_probe_contract(chain, address, fetch, now) for chain, address in selected]
    return {"schema": ASSET_SCHEMA, "acquisito_utc": now.isoformat(timespec="seconds"),
            "posizioni": rows["posizioni"], "candidati": rows["candidati"],
            "fonti_native": sources, "sonde_contratto": probes,
            "contratti_indicizzati_totali": len(contracts),
            "contratti_esaminati": len(probes),
            "prossimo_contratto": ("|".join(contracts[(start+len(selected)) % len(contracts)])
                                  if contracts else None),
            "limite": ("Contratti possibili da aggregatore e risposte RPC pubbliche; "
                       "nessuna attestazione primaria di contratto ufficiale o rete di custodia Kraken")}


def _read_assets(raw, owned, candidates, economic, now):
    if not isinstance(raw, dict) or raw.get("schema") != ASSET_SCHEMA:
        raise ValueError("unknown asset-network evidence schema")
    acquired = _timestamp(raw.get("acquisito_utc"))
    if acquired > now + dt.timedelta(minutes=2):
        raise ValueError("future asset-network evidence")
    expected = _asset_roster(economic, owned, candidates, acquired)
    if raw.get("posizioni") != expected["posizioni"] or raw.get("candidati") != expected["candidati"]:
        raise ValueError("asset identity/project/contract mutated or wrongly bound")
    relevant = sorted({NATIVE_IDS[r["progetto_id"]][1] for family in expected.values()
                       for r in family if r["progetto_id"] in NATIVE_IDS
                       and NATIVE_IDS[r["progetto_id"]][0] == r["token"]
                       and NATIVE_IDS[r["progetto_id"]][1] in NATIVE_ENDPOINTS})[:MAX_NATIVE_SOURCES]
    sources = raw.get("fonti_native")
    if not isinstance(sources, dict) or set(sources) != set(relevant):
        raise ValueError("native source coverage invalid")
    result_sources = {}
    for chain, value in sources.items():
        if not isinstance(value, dict) or value.get("fonte") != NATIVE_ENDPOINTS[chain] or value.get("stato") not in ("OSSERVATO", "NON_DISPONIBILE"):
            raise ValueError("native source attribution invalid")
        observed = _timestamp(value["osservato_utc"]) if value.get("osservato_utc") is not None else None
        if observed and observed > acquired + dt.timedelta(minutes=2):
            raise ValueError("future native measurement")
        if value["stato"] == "OSSERVATO":
            v = value.get("valori")
            if not isinstance(v, dict) or not observed:
                raise ValueError("native source metrics invalid")
            if chain == "bitcoin":
                _integer(v.get("altezza_blocco")); _integer(v.get("transazioni_blocco"))
                if not re.fullmatch(r"[0-9a-f]{64}", str(v.get("blocco_hash"))):
                    raise ValueError("BTC hash mismatch")
            elif chain in ("ethereum", "bsc", "near"):
                _integer(v.get("altezza_blocco"))
                if not isinstance(v.get("blocco_hash"), str) or len(v["blocco_hash"]) < 25:
                    raise ValueError("block hash invalid")
            else:
                _integer(v.get("indice_ledger"))
                if not re.fullmatch(r"[A-F0-9]{64}", str(v.get("ledger_hash"))):
                    raise ValueError("ledger hash invalid")
        elif value.get("valori") is not None or observed is not None:
            raise ValueError("unavailable native source has metrics")
        fresh = bool(observed and dt.timedelta(minutes=-2) <= now-observed <= dt.timedelta(minutes=30))
        result_sources[chain] = dict(value, stato=("OSSERVATO_CON_LIMITI" if fresh else
                                "SCADUTO" if value["stato"] == "OSSERVATO" else
                                "NON_DISPONIBILE"),
                                     valori=value.get("valori") if fresh else None)
    contracts = sorted({(c["rete"], c["contratto"])
                        for family in expected.values() for r in family
                        for c in r["contratti_indicizzati"]
                        if c["rete"] in CONTRACT_ENDPOINTS})
    if (raw.get("contratti_indicizzati_totali") != len(contracts)
            or not isinstance(raw.get("sonde_contratto"), list)
            or len(raw["sonde_contratto"]) > MAX_CONTRACT_PROBES
            or raw.get("contratti_esaminati") != len(raw["sonde_contratto"])):
        raise ValueError("contract coverage altered")
    found = set()
    probes = {}
    for item in raw["sonde_contratto"]:
        if not isinstance(item, dict):
            raise ValueError("contract probe malformed")
        key = (item.get("rete"), item.get("contratto"))
        if key not in contracts or key in found or item.get("fonte") != CONTRACT_ENDPOINTS.get(key[0]):
            raise ValueError("contract probe not attributable")
        found.add(key)
        if item.get("stato") not in ("OSSERVATO", "NON_DISPONIBILE") or item.get("osservato_utc") is not None or _timestamp(item.get("acquisito_utc")) != acquired:
            raise ValueError("contract probe state/time invalid")
        v = item.get("valori")
        if item["stato"] == "OSSERVATO":
            if not isinstance(v, dict):
                raise ValueError("contract supply missing")
            _supply_integer(v.get("supply_unita_minima"))
            if key[0] == "solana":
                _integer(v.get("slot_finalized"))
                if type(v.get("decimali")) is not int or not 0 <= v["decimali"] <= 18:
                    raise ValueError("SPL precision invalid")
            elif set(v) != {"supply_unita_minima", "unita"}:
                raise ValueError("EVM supply precision invalid")
        elif v is not None:
            raise ValueError("unavailable probe has metrics")
        fresh = dt.timedelta(minutes=-2) <= now-acquired <= dt.timedelta(minutes=30)
        probes[key] = dict(item, stato=("NON_DISPONIBILE" if item["stato"] != "OSSERVATO" else
                           "OSSERVATO_CON_LIMITI" if fresh else "SCADUTO"),
                           valori=v if fresh and item["stato"] == "OSSERVATO" else None)
    def interpret(rows):
        output = []
        for row in rows:
            native = NATIVE_IDS.get(row["progetto_id"])
            chain = native[1] if native and native[0] == row["token"] else None
            readings = []
            for c in row["contratti_indicizzati"]:
                key = (c["rete"], c["contratto"])
                reading = probes.get(key)
                readings.append(dict(c, osservazione=reading or {
                    "stato": "NON_ESAMINATO_PER_BUDGET", "valori": None}))
            observation = result_sources.get(chain) if chain else None
            if chain in ("sui", "solana"):
                observation = {"stato": "COPERTO_DA_FONTI_PREESISTENTI",
                               "valori": None, "copertura": "Vedere fonti Sui/Solana PR #53"}
            output.append(dict(row, osservazione_nativa=observation or {
                "stato": "NON_COPERTO", "valori": None},
                osservazioni_contratti=readings))
        return output
    return {"schema": ASSET_SCHEMA, "acquisito_utc": raw["acquisito_utc"],
            "posizioni": interpret(expected["posizioni"]),
            "candidati": interpret(expected["candidati"]),
            "fonti_native": result_sources,
            "limite": raw["limite"]}

# Preserve the PR #53 public Sui/Solana/DeFi producer and reader verbatim,
# enriching only their public output with independently bound asset evidence.
_BASE_COLLECT = collect
_BASE_AT_READ = at_read

def collect(now, positions, candidates, *, fetch=None, economics=None, previous=None):
    original = _BASE_COLLECT(now, positions, candidates, fetch=fetch)
    if economics is not None:
        old = previous.get("asset_reti") if isinstance(previous, dict) else None
        original["asset_reti"] = _collect_assets(
            _now(now), original["roster_posizioni"], original["roster_candidati"],
            economics, old, fetch or _http)
    return original


def at_read(source, positions, candidates, now, *, economics=None):
    result = _BASE_AT_READ(source, positions, candidates, now)
    original = source.get("sorgente") if isinstance(source, dict) and "sorgente" in source else source
    enriched = original.get("asset_reti") if isinstance(original, dict) else None
    if enriched is not None:
        if economics is None:
            raise ValueError("economic identity required to consume contract evidence")
        result["asset_reti"] = _read_assets(
            enriched, _roster(positions), _roster(candidates, candidate=True),
            economics, _now(now))
    return result

# KDD-17 G2/2: integrate a single reusable public capital-flow producer into
# the existing asset-network family (dossier -> packet -> GPT bridge).
# Legacy source/contract semantics above remain unchanged.
_NETWORK_COLLECT_ASSETS = _collect_assets
_NETWORK_READ_ASSETS = _read_assets


def _collect_assets(now, positions, candidates, economic, previous, fetch):
    import kdd_capital_flow
    result = _NETWORK_COLLECT_ASSETS(now, positions, candidates, economic, previous, fetch)
    earlier = previous.get("flussi_capitale") if isinstance(previous, dict) else None
    result["flussi_capitale"] = kdd_capital_flow.collect(
        now, result, economic, earlier, fetch)
    return result


def _read_assets(raw, owned, candidates, economic, now):
    import kdd_capital_flow
    result = _NETWORK_READ_ASSETS(raw, owned, candidates, economic, now)
    # Old dossiers predate this family; absence is not a zero reading.
    if "flussi_capitale" in raw:
        result["flussi_capitale"] = kdd_capital_flow.at_read(
            raw["flussi_capitale"], result, economic, now)
    return result
