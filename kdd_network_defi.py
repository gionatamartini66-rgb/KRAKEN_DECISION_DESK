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
