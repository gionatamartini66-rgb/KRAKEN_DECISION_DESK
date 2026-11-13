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


# --- KDD-17: one identity-bound multi-network extension. ---
# The #53 public Sui/Solana/DeFi producers and validators above are preserved.
# New blocks and SPL mint reports are observations of PUBLIC networks, never
# an assertion that KDD's private holding resides at a particular address.
import kdd_economics as _economics

NETWORK_ADAPTERS = {
    "bitcoin": ("https://blockstream.info/api/blocks", "BLOCKSTREAM_ESPLORA"),
    "ethereum": ("https://ethereum-rpc.publicnode.com", "EVM_RPC"),
    "bsc": ("https://bsc-dataseed.bnbchain.org", "EVM_RPC"),
    "near": ("https://rpc.mainnet.near.org", "NEAR_RPC"),
    "xrpl": ("https://xrplcluster.com/", "XRPL_RPC"),
}
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
MAX_EXTENDED_SOURCES = 10
_LEGACY_COLLECT = collect
_LEGACY_AT_READ = at_read


def _binding(row):
    """Never turn Kraken/CoinGecko ticker correspondence alone into a chain."""
    token = row.get("token")
    identity = row.get("identita")
    project_token = _economics.canonical_token(token)
    base = {"stato": "NON_VERIFICATO", "tipo": "NON_ATTRIBUITO",
            "rete": None, "contratto": None, "progetto_id": None}
    if not isinstance(identity, dict):
        return dict(base, motivo="PROVA_IDENTITA_PROGETTO_ASSENTE")
    if identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO":
        return dict(base, motivo="IDENTITA_PROGETTO_NON_VERIFICATA")
    if identity.get("metodo") == "KRAKEN_COINGECKO_MARKET":
        if _economics._dynamic_valid(token, identity.get("coppia"), identity):
            return dict(base, stato="PROGETTO_DINAMICO_IDENTIFICATO",
                        progetto_id=identity.get("coingecko_id"),
                        motivo="CHAIN_E_CONTRATTO_NON_ATTESTATI")
        return dict(base, motivo="PROVA_DINAMICA_NON_VALIDA")
    curated = _economics._CURATED.get(project_token)
    pair = identity.get("coppia")
    if (identity.get("metodo") != "REGISTRO_CURATO" or not isinstance(curated,dict)
            or identity.get("coingecko_id") != curated.get("id")
            or not isinstance(pair,str) or pair.count("/")!=1
            or _economics.canonical_token(pair.split("/")[0]) != project_token
            or pair.split("/")[1] not in ("EUR","USD","USDC")
            or not isinstance(identity.get("pair_key"),str)
            or not identity["pair_key"]
            or identity.get("asset_base_kraken") != pair.split("/")[0]
            or identity.get("token_progetto") != project_token):
        return dict(base, motivo="BINDING_KRAKEN_PROGETTO_DISCORDANTE")
    chain = curated.get("onchain")
    if not isinstance(chain,dict):
        return dict(base, progetto_id=curated["id"],
                    motivo="ASSOCIAZIONE_CHAIN_NON_DOCUMENTATA")
    kind, network = chain.get("tipo"),chain.get("rete")
    if kind == "MULTICHAIN_DA_RISOLVERE":
        return dict(base, stato="MULTICHAIN_DA_RISOLVERE",
                    tipo=kind, progetto_id=curated["id"],
                    motivo="RETI_E_DEPLOYMENT_DA_VERIFICARE")
    if kind not in ("NATIVO","TOKEN_CONTRATTO") or not isinstance(network,str):
        return dict(base, motivo="METADATI_CHAIN_NON_VALIDI")
    if not isinstance(chain.get("documentazione"),str) or not chain["documentazione"].startswith("https://"):
        return dict(base, motivo="FONTE_CHAIN_NON_DOCUMENTATA")
    if kind=="TOKEN_CONTRATTO":
        if (network!="solana" or chain.get("standard")!="SPL_MINT"
                or not isinstance(chain.get("contratto"),str)
                or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}",chain["contratto"])):
            return dict(base, motivo="MINT_NON_ATTESTATO")
    return {"stato":"ASSOCIAZIONE_CURATA_CON_LIMITI",
            "tipo":kind, "rete":network,
            "contratto":chain.get("contratto") if kind=="TOKEN_CONTRATTO" else None,
            "progetto_id":curated["id"],
            "documentazione":chain["documentazione"],
            "limite":"Kraken+progetto+fonte documentale, NON prova crittografica di address/wallet"}


def _attached(positions, economic_rows):
    if economic_rows is None:
        return positions
    if not isinstance(economic_rows,list) or len(economic_rows)!=len(positions):
        raise ValueError("cardinalita identita rete incongruente")
    result=[]
    for row,source in zip(positions,economic_rows):
        if not isinstance(row,dict) or not isinstance(source,dict) or source.get("token")!=row.get("token"):
            raise ValueError("token rete/economia discordante")
        if ("coppia_analisi" in row and
                source.get("coppia_analisi")!=row.get("coppia_analisi")):
            raise ValueError("coppia rete/economia discordante")
        copy=dict(row)
        # An unknown new candidate has no identity object at collection.
        # Do not manufacture an explicit null identity on packet re-read.
        if "identita" in source:
            copy["identita"]=source["identita"]
        result.append(copy)
    return result


def _bound_roster(rows,candidate=False):
    old=_roster(rows,candidate=candidate)
    for out,source in zip(old,rows):
        if isinstance(source,dict) and "identita" in source:
            out["binding"]=_binding(source)
    return old


def _new_source(url, kind, *, state="NON_ACQUISITO", reason="ASSET_NON_PRESENTE"):
    return {"fonte":url,"tipo_fonte":kind,"stato":state,
            "osservato_utc":None,"valori":None,"unita":None,
            "copertura":"Rete pubblica, NON movimenti wallet/indirizzi Kraken",
            "motivo":reason,"limite":"Endpoint pubblico non equivale ad autenticazione upstream P08/P09"}


def _rpc(fetch,url,method,params):
    data=fetch(url,{"jsonrpc":"2.0","id":1,"method":method,"params":params})
    if (not isinstance(data,dict) or data.get("error") or data.get("id")!=1
            or "result" not in data):
        raise ValueError("public RPC error or wrong id")
    return data["result"]


def _hex(value):
    if not isinstance(value,str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,18}",value):
        raise ValueError("invalid RPC hex integer")
    return int(value,16)


def _hash(value,evm=False):
    rule=r"0x[0-9a-fA-F]{64}" if evm else r"[0-9a-fA-F]{64}"
    if not isinstance(value,str) or not re.fullmatch(rule,value):
        raise ValueError("invalid block hash")
    return value


def _new_network_record(network,now,fetch):
    url,kind=NETWORK_ADAPTERS[network]
    record=_new_source(url,kind)
    if network=="bitcoin":
        blocks=fetch(url)
        if not isinstance(blocks,list) or not 1<=len(blocks)<=10 or not isinstance(blocks[0],dict):
            raise ValueError("Bitcoin blocks list invalid")
        top=blocks[0]
        observed=dt.datetime.fromtimestamp(_integer(top.get("timestamp")),UTC)
        values={"altezza":_integer(top.get("height")),
                "tx_blocco":_integer(top.get("tx_count")),
                "hash":_hash(top.get("id"))}
        units={"altezza":"blocchi","tx_blocco":"transazioni nel blocco"}
    elif network in ("ethereum","bsc"):
        expected=1 if network=="ethereum" else 56
        chainid=_hex(_rpc(fetch,url,"eth_chainId",[]))
        if chainid!=expected:
            raise ValueError("EVM chain id mismatched")
        tag="finalized" if network=="ethereum" else "latest"
        block=_rpc(fetch,url,"eth_getBlockByNumber",[tag,False])
        if not isinstance(block,dict) or not isinstance(block.get("transactions"),list):
            raise ValueError("EVM block invalid")
        observed=dt.datetime.fromtimestamp(_hex(block.get("timestamp")),UTC)
        values={"altezza":_hex(block.get("number")),
                "tx_blocco":len(block["transactions"]),
                "hash":_hash(block.get("hash"),evm=True),
                "chain_id":chainid}
        units={"altezza":"blocchi","tx_blocco":"transazioni nel blocco","chain_id":"EVM chain ID"}
    elif network=="near":
        block=_rpc(fetch,url,"block",{"finality":"final"})
        header=block.get("header") if isinstance(block,dict) else None
        if not isinstance(header,dict):
            raise ValueError("NEAR header absent")
        observed=dt.datetime.fromtimestamp(_integer(header.get("timestamp"))/1_000_000_000,UTC)
        h=header.get("hash")
        if not isinstance(h,str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,60}",h):
            raise ValueError("NEAR block hash invalid")
        values={"altezza":_integer(header.get("height")),"hash":h}
        units={"altezza":"blocchi finalizzati"}
    else:
        result=_rpc(fetch,url,"ledger",[{"ledger_index":"validated",
                                         "transactions":False,"api_version":2}])
        ledger=result.get("ledger") if isinstance(result,dict) else None
        if (not isinstance(result,dict) or result.get("validated") is not True
                or not isinstance(ledger,dict)):
            raise ValueError("XRPL ledger not validated")
        observed=_timestamp(ledger.get("close_time_iso"))
        values={"altezza":_integer(result.get("ledger_index")),
                "hash":_hash(result.get("ledger_hash")),
                "xrp_totali":str(_number(ledger.get("total_coins"))/Decimal(1_000_000))}
        units={"altezza":"ledger validati","xrp_totali":"XRP rete, non saldo wallet"}
    if not dt.timedelta(minutes=-2)<=now-observed<=dt.timedelta(hours=3):
        raise ValueError("network timestamp stale or future")
    record.update(stato="OSSERVATO",osservato_utc=observed.isoformat(timespec="seconds"),
                  valori=values,unita=units,motivo=None)
    return record


def _new_mint_record(mint,now,fetch):
    record=_new_source(SOL_URL,"SOLANA_SPL_MINT")
    amount=_rpc(fetch,SOL_URL,"getTokenSupply",[mint,{"commitment":"finalized"}])
    info=_rpc(fetch,SOL_URL,"getAccountInfo",[mint,{"commitment":"finalized",
                                                     "encoding":"jsonParsed"}])
    if not isinstance(amount,dict) or not isinstance(info,dict):
        raise ValueError("Solana mint RPC shape")
    av=amount.get("value")
    iv=info.get("value")
    parsed=(iv.get("data") or {}).get("parsed") if isinstance(iv,dict) else None
    content=parsed.get("info") if isinstance(parsed,dict) else None
    if (not isinstance(av,dict) or not isinstance(content,dict)
            or iv.get("owner")!=TOKEN_PROGRAM or parsed.get("type")!="mint"):
        raise ValueError("not a standard SPL mint")
    slot=_integer(amount.get("context",{}).get("slot"))
    slot2=_integer(info.get("context",{}).get("slot"))
    decimals=_integer(av.get("decimals"))
    raw=_integer(av.get("amount"))
    if (decimals>18 or decimals!=_integer(content.get("decimals"))
            or slot2<slot-1000):
        raise ValueError("SPL mint decimals or slot inconsistent")
    total=Decimal(raw)/(Decimal(10)**decimals)
    record.update(stato="OSSERVATO",valori={
        "mint":mint,"slot_finalized":slot,"slot_info":slot2,
        "supply_grezza":str(raw),"decimali":decimals,
        "supply_token":str(total),"token_program":TOKEN_PROGRAM},
        unita={"supply_token":"unita SPL token; non offerta circolante",
               "supply_grezza":"base units","slot_finalized":"slot Solana"},
        copertura="Supply del MINT SPL documentato; NON posizioni Kraken o holders unici",
        motivo=None)
    return record


def _collect_extended(raw,now,fetch):
    bindings=[x.get("binding",{}) for x in raw["roster_posizioni"]+raw["roster_candidati"]]
    networks={x.get("rete") for x in bindings
              if x.get("stato")=="ASSOCIAZIONE_CURATA_CON_LIMITI"
              and x.get("tipo")=="NATIVO" and x.get("rete") in NETWORK_ADAPTERS}
    mints={x.get("contratto") for x in bindings
           if x.get("stato")=="ASSOCIAZIONE_CURATA_CON_LIMITI"
           and x.get("tipo")=="TOKEN_CONTRATTO" and x.get("rete")=="solana"}
    if len(networks)+2*len(mints)+sum(x in ("ethereum","bsc") for x in networks)>MAX_EXTENDED_SOURCES:
        raise ValueError("network request budget exceeded")
    network_rows={}
    for network,(url,kind) in NETWORK_ADAPTERS.items():
        if network not in networks:
            network_rows[network]=_new_source(url,kind)
            continue
        try:
            network_rows[network]=_new_network_record(network,now,fetch)
        except (ValueError,TypeError,KeyError,OSError,OverflowError,UnicodeError,
                json.JSONDecodeError) as exc:
            network_rows[network]=_new_source(url,kind,state="NON_DISPONIBILE",
                                             reason=type(exc).__name__)
    mint_rows={}
    for mint in sorted(mints):
        try:
            mint_rows[mint]=_new_mint_record(mint,now,fetch)
        except (ValueError,TypeError,KeyError,OSError,OverflowError,UnicodeError,
                json.JSONDecodeError) as exc:
            mint_rows[mint]=_new_source(SOL_URL,"SOLANA_SPL_MINT",
                                         state="NON_DISPONIBILE",reason=type(exc).__name__)
    raw["fonti_rete"]=network_rows
    raw["fonti_contratti"]=mint_rows
    raw["limite_onchain"]="Osservazioni di rete/mint, NON proof-of-ownership o attribuzione a exchange"
    return raw


def collect(now,positions,candidates,*,fetch=None):
    """Existing #53 data + documented, identity-bound adapters (public only)."""
    original=_LEGACY_COLLECT(now,positions,candidates,fetch=fetch)
    original["roster_posizioni"]=_bound_roster(positions)
    original["roster_candidati"]=_bound_roster(candidates,candidate=True)
    return _collect_extended(original,_now(now),fetch or _http)


def _checked_extended(key,record,now,acquired,*,mint=None):
    url,kind=(NETWORK_ADAPTERS[key] if mint is None
              else (SOL_URL,"SOLANA_SPL_MINT"))
    if (not isinstance(record,dict) or record.get("fonte")!=url
            or record.get("tipo_fonte")!=kind
            or record.get("limite")!="Endpoint pubblico non equivale ad autenticazione upstream P08/P09"):
        raise ValueError("extended source provenance invalid")
    state=record.get("stato")
    if state not in ("OSSERVATO","NON_ACQUISITO","NON_DISPONIBILE"):
        raise ValueError("extended state invalid")
    values, units=record.get("valori"),record.get("unita")
    observed=_timestamp(record["osservato_utc"]) if record.get("osservato_utc") else None
    if state!="OSSERVATO":
        if values is not None or units is not None or observed is not None:
            raise ValueError("unavailable extended source contains observations")
        return dict(record)
    if not isinstance(values,dict) or not isinstance(units,dict):
        raise ValueError("extended source values malformed")
    if mint is not None:
        if (set(values)!={"mint","slot_finalized","slot_info",
                          "supply_grezza","decimali","supply_token","token_program"}
                or values.get("mint")!=mint or values.get("token_program")!=TOKEN_PROGRAM
                or observed is not None):
            raise ValueError("SPL mint identity altered")
        dec=_integer(values["decimali"])
        if dec>18 or _integer(values["slot_info"])+1000<_integer(values["slot_finalized"]):
            raise ValueError("SPL decimals/slot")
        if _number(values["supply_token"])!=Decimal(_integer(values["supply_grezza"]))/(10**dec):
            raise ValueError("SPL supply altered")
    else:
        if _integer(values.get("altezza"))<1 or not isinstance(values.get("hash"),str):
            raise ValueError("chain block invalid")
        if key in ("ethereum","bsc"):
            if (values.get("chain_id")!=(1 if key=="ethereum" else 56)
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}",values["hash"])):
                raise ValueError("EVM chain identity mismatch")
            _integer(values.get("tx_blocco"))
        elif key=="bitcoin":
            _hash(values["hash"])
            _integer(values.get("tx_blocco"))
        elif key=="near":
            if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,60}",values["hash"]):
                raise ValueError("NEAR hash invalid")
        else:
            _hash(values["hash"])
            _number(values.get("xrp_totali"))
        if observed is None:
            raise ValueError("chain native timestamp absent")
    reference=observed or acquired
    if reference>acquired+dt.timedelta(minutes=2):
        raise ValueError("source observation after acquisition")
    fresh=dt.timedelta(minutes=-2)<=now-reference<=dt.timedelta(minutes=30)
    return dict(record,stato="OSSERVATO_CON_LIMITI" if fresh else "SCADUTO",
                valori=values if fresh else None,unita=units if fresh else None,
                motivo=None if fresh else "MISURA_SCADUTA_NON_USARE_PER_DECISIONI")


def _enrich_row(row,network_rows,mint_rows):
    binding=row.get("binding")
    kind=binding.get("tipo") if isinstance(binding,dict) else None
    status=binding.get("stato") if isinstance(binding,dict) else "NON_VERIFICATO"
    if kind=="NATIVO" and status=="ASSOCIAZIONE_CURATA_CON_LIMITI":
        network=binding["rete"]
        if network in network_rows:
            observed=network_rows[network]
            return dict(row,onchain=dict(observed,tipologia="ASSET_NATIVO",
                         rete=network,documentazione=binding["documentazione"],
                         ipotesi="Un nuovo blocco/ledger descrive lo stato della rete.",
                         controipotesi="Attivita aggregata non prova acquisti o vendite del token.",
                         condizione_riesame="Confrontare campioni datati e provider indipendenti."),
                        identita_onchain=binding)
        # SUI/SOL legacy observation retained; no replacement of #53.
        if network in ("sui","solana"):
            return dict(row,identita_onchain=binding)
        return dict(row,identita_onchain=binding,
                    onchain={"stato":"FONTE_PUBBLICA_NON_INTEGRATA",
                             "rete":network,"valori":None,"fonte":None,
                             "documentazione":binding["documentazione"],
                             "limite":"Rete nativa identificata, nessuna misura verificata",
                             "condizione_riesame":"Integrare un endpoint pubblico documentato e validarne la risposta"})
    if kind=="TOKEN_CONTRATTO" and status=="ASSOCIAZIONE_CURATA_CON_LIMITI":
        item=mint_rows.get(binding["contratto"])
        return dict(row,identita_onchain=binding,
                    onchain=(dict(item,tipologia="TOKEN_CON_MINT",
                                  rete=binding["rete"],contratto=binding["contratto"],
                                  documentazione=binding["documentazione"],
                                  ipotesi="Supply del mint osservato puo incidere sulla valutazione della diluizione.",
                                  controipotesi="Supply totale del mint non equivale a circolante o a vendite.",
                                  condizione_riesame="Confrontare supply datate e vesting verificato.")
                             if item else {"stato":"NON_ACQUISITO","valori":None}))
    reason=("MULTICHAIN_DA_RISOLVERE" if status=="MULTICHAIN_DA_RISOLVERE"
            else "CHAIN_NON_ATTESTATA")
    if "binding" in row:
        return dict(row,identita_onchain=binding,
                    onchain={"stato":reason,"valori":None,
                             "limite":"Nessun contratto o network attribuito dal solo ticker"})
    return row


def at_read(source,positions,candidates,now,*,economia=None):
    """Revalidate both #53 and new provenance/identity at packet and GPT read."""
    moment=_now(now)
    raw=source.get("sorgente") if isinstance(source,dict) and "sorgente" in source else source
    if not isinstance(raw,dict) or "fonti_rete" not in raw:
        return _LEGACY_AT_READ(source,positions,candidates,moment)
    economic_rows=economia if isinstance(economia,dict) else None
    pos=_attached(positions,economic_rows.get("posizioni") if economic_rows else None)
    can=_attached(candidates,economic_rows.get("candidati") if economic_rows else None)
    expected_pos=_bound_roster(pos)
    expected_can=_bound_roster(can,candidate=True)
    if raw.get("roster_posizioni")!=expected_pos or raw.get("roster_candidati")!=expected_can:
        raise ValueError("on-chain chain identity or dynamic roster changed")
    # Old source is independently checked with exact #53 validators, then
    # extended fields undergo a separate strict semantic check.
    stripped=dict(raw,roster_posizioni=_roster(positions),
                  roster_candidati=_roster(candidates,candidate=True))
    base=_LEGACY_AT_READ(stripped,positions,candidates,moment)
    if (not isinstance(raw.get("fonti_rete"),dict)
            or set(raw["fonti_rete"])!=set(NETWORK_ADAPTERS)
            or not isinstance(raw.get("fonti_contratti"),dict)
            or raw.get("limite_onchain")!="Osservazioni di rete/mint, NON proof-of-ownership o attribuzione a exchange"):
        raise ValueError("on-chain extended sources malformed")
    acquired=_timestamp(raw["acquisito_utc"])
    current={k:_checked_extended(k,record,moment,acquired)
             for k,record in raw["fonti_rete"].items()}
    mints={x["binding"]["contratto"] for x in expected_pos+expected_can
           if isinstance(x.get("binding"),dict)
           and x["binding"].get("stato")=="ASSOCIAZIONE_CURATA_CON_LIMITI"
           and x["binding"].get("tipo")=="TOKEN_CONTRATTO"}
    if set(raw["fonti_contratti"])!=mints:
        raise ValueError("unexpected or missing token contract source")
    mint_rows={mint:_checked_extended("solana",item,moment,acquired,mint=mint)
               for mint,item in raw["fonti_contratti"].items()}
    base["sorgente"]=raw
    base["posizioni"]=[_enrich_row(dict(x,**({"binding":b["binding"]} if "binding" in b else {})),current,mint_rows)
                        for x,b in zip(base["posizioni"],expected_pos)]
    base["candidati"]=[_enrich_row(dict(x,**({"binding":b["binding"]} if "binding" in b else {})),current,mint_rows)
                        for x,b in zip(base["candidati"],expected_can)]
    base["fonti_rete"]={k:{"fonte":v["fonte"],"stato":v["stato"],
                           "osservato_utc":v.get("osservato_utc")}
                         for k,v in current.items()}
    base["limite"]="Valori pubblici legati a identita economica curata e rete documentata; " \
                   "P08/P09 upstream NON autenticato; nessun saldo wallet o transfer attribuito."
    return base
