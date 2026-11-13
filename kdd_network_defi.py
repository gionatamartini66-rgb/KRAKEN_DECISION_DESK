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



# Additional keyless/public observations, one adapter registry rather than one
# Python module per token. Transport is never proof of a private wallet owner.
NETWORK_ENDPOINTS = {
    "bitcoin": "https://mempool.space/api/blocks",
    "ethereum": "https://eth.nodely.dev",
    "bsc": "https://bsc-dataseed.bnbchain.org",
    "near": "https://rpc.mainnet.near.org",
    "xrpl": "https://s1.ripple.com:51234/",
    "cardano": "https://api.koios.rest/api/v1/tip",
    "jup_spl": SOL_URL,
}
EVM_CHAINS = {"ethereum": "0x1", "bsc": "0x38"}
NETWORK_UNITS = {
    "bitcoin": "blocchi, transazioni nel blocco",
    "ethereum": "blocchi e gas base in wei",
    "bsc": "blocchi e gas base in wei",
    "near": "blocchi finalizzati",
    "xrpl": "ledger validato",
    "cardano": "blocchi, slot, epoca",
    "jup_spl": "token SPL (decimali da RPC)",
}


def _hex(value, *, width=None):
    if (not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value)
            or (width is not None and len(value) != width)):
        raise ValueError("invalid RPC hexadecimal")
    return int(value, 16)


def _url_hash(value, n=64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{"+str(n)+r"}", value):
        raise ValueError("invalid block hash")
    return value.lower()


def _epoch_seconds(value):
    number=_integer(value)
    if number < 946684800 or number > 4102444800:
        raise ValueError("block timestamp outside supported epoch")
    return dt.datetime.fromtimestamp(number, UTC)


def _response_rpc(response, req_id):
    if (not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
            or response.get("id") != req_id or response.get("error")
            or response.get("result") is None):
        raise ValueError("RPC result missing or network error")
    return response["result"]


def _curated_binding(row):
    """A Kraken-validated economic *project* is required before chain binding.

    A dynamically resolved CoinGecko project alone is never a chain/contract
    attestation; a public chain measurement is not a Kraken custody proof.
    """
    import kdd_economics as econ
    token=row.get("token") if isinstance(row, dict) else None
    base={"token":token,"stato":"NON_ATTRIBUIBILE","tipo":"NON_DETERMINATO",
          "rete":None,"contratto":None,"coingecko_id":None,
          "fonte_identita":None,"limite":"Ticker senza attribuzione chain/contract verificata"}
    if not isinstance(token, str):
        return base
    identity=row.get("identita") if isinstance(row, dict) else None
    data=econ._CURATED.get(econ.canonical_token(token))
    if (not isinstance(identity, dict) or identity.get("token") != token
            or identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO"
            or identity.get("metodo") != "REGISTRO_CURATO"
            or not isinstance(data, dict) or identity.get("coingecko_id") != data.get("id")
            or identity.get("token_progetto") != econ.canonical_token(token)
            or not isinstance(identity.get("coppia"), str)):
        return dict(base,stato="PROGETTO_O_MERCATO_NON_VERIFICATO")
    if "coppia_analisi" in row and row.get("coppia_analisi") != identity["coppia"]:
        return dict(base,stato="COPPIA_DIVERSA")
    record=data.get("onchain")
    if not isinstance(record, dict):
        return dict(base,stato="NESSUNA_ASSOCIAZIONE_CURATA")
    kind,network=record.get("tipo"),record.get("rete")
    if kind=="TOKEN_CONTRATTO":
        mint=record.get("contratto")
        if (network!="solana" or token!="JUP"
                or mint!="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"):
            return dict(base,stato="CONTRATTO_NON_ATTESTATO")
    elif kind=="NATIVO":
        if network not in (*NETWORK_ENDPOINTS, "sui", "solana") or record.get("contratto"):
            return dict(base,stato="RETE_NON_ATTESTATA")
    else:
        return dict(base,stato=kind if isinstance(kind,str) else "MULTICHAIN_NON_DISAMBIGUATO",
                    tipo=kind if isinstance(kind,str) else "NON_DETERMINATO",
                    limite=str(record.get("limite") or base["limite"])[:200],
                    fonte_identita=record.get("fonte_identita"))
    return {"token":token,"stato":"PROGETTO_E_RETE_CURATI",
            "tipo":kind,"rete":network,"contratto":record.get("contratto"),
            "coingecko_id":data["id"],"fonte_identita":record.get("fonte_identita"),
            "limite":str(record.get("limite") or "")[:200]}


def _acquire_extra(network, fetch, moment):
    url=NETWORK_ENDPOINTS[network]
    stamp=None
    if network=="bitcoin":
        payload=fetch(url)
        if not isinstance(payload,list) or not payload or len(payload)>20:
            raise ValueError("Bitcoin explorer blocks invalid")
        block=payload[0]
        if not isinstance(block,dict):
            raise ValueError("Bitcoin block absent")
        values={"altezza":_integer(block.get("height")),
                "hash":_url_hash(block.get("id")),
                "transazioni_blocco":_integer(block.get("tx_count"))}
        stamp=_epoch_seconds(block.get("timestamp"))
    elif network in EVM_CHAINS:
        chain=_response_rpc(fetch(url,{"jsonrpc":"2.0","method":"eth_chainId",
                                        "params":[],"id":1}),1)
        if chain.lower()!=EVM_CHAINS[network]:
            raise ValueError("RPC EVM wrong chain ID")
        block=_response_rpc(fetch(url,{"jsonrpc":"2.0","method":"eth_getBlockByNumber",
                                        "params":["latest",False],"id":2}),2)
        if not isinstance(block,dict):
            raise ValueError("RPC EVM block absent")
        values={"chain_id":_hex(chain),
                "altezza":_hex(block.get("number")),
                "hash":_url_hash(block.get("hash","")[2:]),
                "gas_limit":_hex(block.get("gasLimit"))}
        stamp=_epoch_seconds(_hex(block.get("timestamp")))
    elif network=="near":
        block=_response_rpc(fetch(url,{"jsonrpc":"2.0","method":"block",
                                     "params":{"finality":"final"},"id":1}),1)
        if not isinstance(block,dict) or not isinstance(block.get("header"),dict):
            raise ValueError("NEAR block header absent")
        header=block["header"]
        nanos=_integer(header.get("timestamp_nanosec"))
        values={"altezza":_integer(header.get("height")),
                "hash":header.get("hash")}
        if not isinstance(values["hash"],str) or not 20<=len(values["hash"])<=100:
            raise ValueError("NEAR block hash missing")
        stamp=dt.datetime.fromtimestamp(nanos/10**9,UTC)
    elif network=="xrpl":
        response=fetch(url,{"method":"ledger",
                            "params":[{"ledger_index":"validated","transactions":False,
                                       "expand":False}]})
        obj=response.get("result") if isinstance(response,dict) else None
        ledger=obj.get("ledger") if isinstance(obj,dict) else None
        if not isinstance(ledger,dict) or obj.get("validated") is not True:
            raise ValueError("XRPL validated ledger missing")
        values={"ledger_index":_integer(ledger.get("ledger_index")),
                "hash":_url_hash(ledger.get("ledger_hash"))}
        stamp=_epoch_seconds(_integer(ledger.get("close_time"))+946684800)
    elif network=="cardano":
        payload=fetch(url)
        if not isinstance(payload,list) or len(payload)!=1 or not isinstance(payload[0],dict):
            raise ValueError("Cardano Koios tip invalid")
        row=payload[0]
        values={"altezza":_integer(row.get("block_no")),
                "slot":_integer(row.get("abs_slot")),
                "epoca":_integer(row.get("epoch_no")),
                "hash":_url_hash(row.get("hash"))}
        stamp=_epoch_seconds(row.get("block_time"))
    elif network=="jup_spl":
        mint="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
        response=fetch(url,{"jsonrpc":"2.0","id":1,"method":"getTokenSupply",
                            "params":[mint,{"commitment":"finalized"}]})
        result=_response_rpc(response,1)
        obj=result.get("value") if isinstance(result,dict) else None
        if not isinstance(obj,dict):
            raise ValueError("SPL token supply missing")
        amount=_integer(obj.get("amount"))
        decimals=_integer(obj.get("decimals"))
        if decimals>18:
            raise ValueError("SPL decimals outside bound")
        values={"mint":mint,"slot_finalized":_integer(result.get("context",{}).get("slot")),
                "supply_base_units":str(amount),"decimals":decimals,
                "supply_token":str(Decimal(amount)/(Decimal(10)**decimals))}
    else:
        raise ValueError("network adapter unavailable")
    if stamp and (stamp>moment+dt.timedelta(minutes=2)
                  or moment-stamp>dt.timedelta(days=2)):
        raise ValueError("stale or future network source at acquisition")
    return {"stato":"OSSERVATO","fonte":url,
            "osservato_utc":stamp.isoformat() if stamp else None,
            "valori":values,"unita":NETWORK_UNITS[network],
            "copertura":"Rete pubblica, NON wallet Kraken",
            "limite":"P08/P09: nodo/esploratore esterno; contenuto non autenticato da nodo locale."}


def _extra_at_read(network, row, acquired, now):
    url=NETWORK_ENDPOINTS[network]
    if not isinstance(row,dict) or row.get("fonte")!=url:
        raise ValueError("network source attribution mismatch")
    if row.get("unita")!=NETWORK_UNITS[network] or row.get("copertura")!="Rete pubblica, NON wallet Kraken":
        raise ValueError("network source descriptors altered")
    if row.get("limite")!="P08/P09: nodo/esploratore esterno; contenuto non autenticato da nodo locale.":
        raise ValueError("network provenance rebranded")
    if row.get("stato")=="NON_DISPONIBILE":
        if row.get("valori") is not None or row.get("osservato_utc") is not None:
            raise ValueError("unavailable network carries metrics")
        return dict(row)
    if row.get("stato")!="OSSERVATO" or not isinstance(row.get("valori"),dict):
        raise ValueError("invalid network source state")
    values=row["valori"]
    # Validate each economic number and identity again; the transport digest
    # does not attest the provider or permit a plausible altered block count.
    expected={
        "bitcoin":{"altezza","hash","transazioni_blocco"},
        "ethereum":{"chain_id","altezza","hash","gas_limit"},
        "bsc":{"chain_id","altezza","hash","gas_limit"},
        "near":{"altezza","hash"},
        "xrpl":{"ledger_index","hash"},
        "cardano":{"altezza","slot","epoca","hash"},
        "jup_spl":{"mint","slot_finalized","supply_base_units","decimals","supply_token"}
    }[network]
    if set(values)!=expected:
        raise ValueError("network values schema mismatch")
    numeric_keys=expected-{"hash","mint","supply_token"}
    for key in numeric_keys:
        _integer(values[key])
    if "hash" in values:
        if network=="near":
            if not isinstance(values["hash"],str) or not 20<=len(values["hash"])<=100:
                raise ValueError("NEAR hash invalid")
        else:
            _url_hash(values["hash"])
    if network in EVM_CHAINS and values["chain_id"]!=_hex(EVM_CHAINS[network]):
        raise ValueError("EVM network substituted")
    if network=="jup_spl":
        if values["mint"]!="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN":
            raise ValueError("SPL token substituted")
        if not 0<=values["decimals"]<=18:
            raise ValueError("SPL precision invalid")
        total=Decimal(values["supply_base_units"])/(Decimal(10)**values["decimals"])
        if str(total)!=str(Decimal(str(values["supply_token"]))):
            raise ValueError("SPL supply mismatch")
    observed=_timestamp(row["osservato_utc"]) if row.get("osservato_utc") else None
    if observed is None and network!="jup_spl":
        raise ValueError("native chain observation time missing")
    if observed and observed>acquired+dt.timedelta(minutes=2):
        raise ValueError("network timestamp after acquisition")
    last=observed if observed else acquired
    max_age=dt.timedelta(minutes=90 if network=="bitcoin" else 30)
    fresh=dt.timedelta(minutes=-2)<=now-last<=max_age and dt.timedelta(minutes=-2)<=now-acquired<=dt.timedelta(minutes=30)
    return dict(row,stato="OSSERVATO_CON_LIMITI" if fresh else "SCADUTO",
                valori=values if fresh else None,
                limite=row["limite"] if fresh else "Misura di rete scaduta; numeri non utilizzabili come attuali")


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
    # The extra-chain request list derives ONLY from an independently bound
    # Kraken project identity and the curated network/contract registry.
    associations = {
        "posizioni": [_curated_binding(x) for x in positions],
        "candidati": [_curated_binding(x) for x in candidates]}
    networks = set()
    for rows in associations.values():
        for bound in rows:
            if bound["stato"] != "PROGETTO_E_RETE_CURATI":
                continue
            if bound["tipo"] == "TOKEN_CONTRATTO" and bound["token"] == "JUP":
                networks.add("jup_spl")
            elif bound["tipo"] == "NATIVO" and bound["rete"] in NETWORK_ENDPOINTS:
                networks.add(bound["rete"])
    extra = {}
    for key in sorted(networks):
        try:
            extra[key] = _acquire_extra(key,fetch,instant)
        except (OSError,ValueError,KeyError,TypeError,OverflowError,
                UnicodeError,json.JSONDecodeError) as exc:
            extra[key] = {
                "stato":"NON_DISPONIBILE","fonte":NETWORK_ENDPOINTS[key],
                "osservato_utc":None,"valori":None,
                "unita":NETWORK_UNITS[key],
                "copertura":"Rete pubblica, NON wallet Kraken",
                "limite":"P08/P09: nodo/esploratore esterno; contenuto non autenticato da nodo locale.",
                "motivo":type(exc).__name__}
    return {"schema": SCHEMA, "acquisito_utc": instant.isoformat(timespec="seconds"),
            "roster_posizioni": owned, "roster_candidati": external,
            "associazioni":associations,"fonti_reti":extra,
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



def _joined_rows(rows, bindings, old_sources, extra, acquired):
    """Keep the original SUI/SOL producer and expose extra network observations."""
    result=[]
    for row,binding in zip(rows,bindings):
        output=_economic_row(row,old_sources,acquired)
        output["identita_rete"]=binding
        if binding["stato"]!="PROGETTO_E_RETE_CURATI":
            output["osservazione_rete"]={
                "stato":"NON_ATTRIBUIBILE","fonte":None,"valori":None,
                "limite":"Nessun dato di una chain puo essere attribuito al progetto da ticker."}
        else:
            network=binding["rete"]
            key=("jup_spl" if binding["tipo"]=="TOKEN_CONTRATTO" else network)
            if key in extra:
                observed=extra[key]
            elif network in ("sui","solana") and binding["tipo"]=="NATIVO":
                observed=old_sources[network]
            else:
                observed={"stato":"NON_ACQUISITO","valori":None,"fonte":None}
            unit=(NETWORK_UNITS[key] if key in NETWORK_UNITS else
                  "Sui checkpoint/contatori di rete" if key=="sui" else
                  "SOL supply in SOL" if key=="solana" else "non definita")
            output["osservazione_rete"]={
                "stato":observed["stato"],"fonte":observed.get("fonte"),
                "osservato_utc":observed.get("osservato_utc"),
                "acquisito_utc":acquired.isoformat(),
                "valori":observed.get("valori"),
                "unita":unit,"copertura":"Solo rete identificata; NON saldo/indirizzo Kraken",
                "ipotesi":"L'evoluzione dei blocchi o della supply puo cambiare la valutazione del progetto.",
                "controipotesi":"Un nuovo blocco o aumento di supply non prova domanda o prezzo del token.",
                "condizione_riesame":"Confrontare snapshot successivi e verificare identita rete e fonte indipendente.",
                "limite":binding["limite"]+"; P08/P09 upstream non autenticato"}
            if key in extra:
                output["onchain"]=dict(output["osservazione_rete"])
        result.append(output)
    return result


def at_read(source, positions, candidates, now, *, economia=None):
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
    stored=raw.get("associazioni")
    if stored is None:  # historical PR #53 dossier with no chain binding
        associations={"posizioni":[_curated_binding(x) for x in owned],
                      "candidati":[_curated_binding(x) for x in external]}
        extra={}
    else:
        if not isinstance(stored,dict) or set(stored)!={"posizioni","candidati"}:
            raise ValueError("chain bindings malformed")
        expected={}
        for group,roster in (("posizioni",owned),("candidati",external)):
            proofrows=economia.get(group) if isinstance(economia,dict) else None
            if not isinstance(proofrows,list) or len(proofrows)!=len(roster):
                # Legacy/plain source fixtures may contain only unbound tokens:
                # permit that, but never promote a stored verified association.
                if any(row.get("stato")=="PROGETTO_E_RETE_CURATI" for row in stored[group]):
                    raise ValueError("economic identity proof required for chain binding")
                expected[group]=[_curated_binding(row) for row in roster]
            else:
                # Independent economic identity is read again at GPT time.
                expected[group]=[_curated_binding(row) for row in proofrows]
        if stored!=expected:
            raise ValueError("chain binding differs from economic identity")
        associations=expected
        fields=raw.get("fonti_reti")
        required=set()
        for rows in associations.values():
            for bound in rows:
                if bound["stato"]=="PROGETTO_E_RETE_CURATI":
                    key=("jup_spl" if bound["tipo"]=="TOKEN_CONTRATTO"
                         else bound["rete"])
                    if key in NETWORK_ENDPOINTS:
                        required.add(key)
        if not isinstance(fields,dict) or set(fields)!=required:
            raise ValueError("chain sources not aligned with verified roster")
        extra={key:_extra_at_read(key,row,acquired,moment)
               for key,row in fields.items()}
    return {"schema":SCHEMA,"stato":"EVIDENZE_CON_LIMITI",
            "acquisito_utc":raw["acquisito_utc"],
            "sorgente":raw,"fonti_reti":extra,
            "posizioni":_joined_rows(owned,associations["posizioni"],sources,extra,acquired),
            "candidati":_joined_rows(external,associations["candidati"],sources,extra,acquired),
            "limite":"Reti/TVL pubblici, nessuna attribuzione al portafoglio privato; "
                     "provenienza P08/P09 non autenticata e metriche da confrontare nel tempo."}
