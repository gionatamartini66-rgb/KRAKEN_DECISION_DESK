"""KDD-18/20/21/22: bounded, attributable economic evidence; never trading signals."""
import datetime as dt
import copy
import hashlib
import email.utils
import math
import json
import re
from pathlib import Path
from urllib.parse import urlparse, quote, parse_qs

# Il file JSON e' un registro dati modificabile senza modificare il motore Python.
# Le nuove identita' non vengono aggiunte automaticamente al registro curato:
# sono conservate, con fonte e data, nel dossier locale.
CATALOG_FILE = Path(__file__).with_name("kdd_project_catalog.json")
def _load_catalog():
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        if data.get("schema") != "kdd-project-catalog-v001":
            return {}
        return {k: v for k, v in data.get("projects", {}).items()
                if re.fullmatch(r"[A-Z0-9]{2,20}", k)
                and isinstance(v, dict)
                and isinstance(v.get("id"), str)
                and re.fullmatch(r"[a-z0-9-]{2,120}", v["id"])
                and isinstance(v.get("name"), str) and v["name"]}
    except (OSError, ValueError, TypeError):
        return {}

_CURATED = _load_catalog()
PROJECTS = {k: (v["id"], v["name"], v.get("repository"))
            for k, v in _CURATED.items()}
PROJECT_CAVEATS = {k: v["caveat"] for k, v in _CURATED.items()
                   if isinstance(v.get("caveat"), str)}
CG = "https://api.coingecko.com/api/v3/coins/"
CG_SEARCH = "https://api.coingecko.com/api/v3/search?query="
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets?"
MAX_CG_BATCH_IDS = 50
# One search plus every exact-symbol market check must fit the nine-request budget.
MAX_MARKET_CANDIDATES = 8
VERSION = "kdd-economic-v001"
UTC = dt.timezone.utc

# Consultable source documents, NOT automatically acquired token-unlock data.
# These links have a curated project binding and are never used to assert
# current supply, scheduled vesting or the adoption of a software release.
MONETARY_REFERENCES = {
    "BTC": {"url": "https://bitcoin.org/en/faq#how-are-bitcoins-created",
            "tema": "Emissione monetaria e limite di offerta Bitcoin"},
    "SOL": {"url": "https://solana.com/staking",
            "tema": "Politica di inflazione e ricompense staking Solana"},
}


def monetary_reference(identity):
    token = canonical_token(identity.get("token"))
    doc = MONETARY_REFERENCES.get(token)
    verified = (identity.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO"
                and identity.get("metodo") == "REGISTRO_CURATO"
                and token in PROJECTS)
    return {"stato": "CONSULTABILE_NON_ACQUISITO" if doc and verified else "NON_DISPONIBILE",
            "fonte": doc["url"] if doc and verified else None,
            "tema": doc["tema"] if doc and verified else None,
            "ultimo_controllo_documentale_utc": None,
            "calendario_unlock_verificato": False,
            "limite": ("Il documento di progetto va verificato alla lettura: non "
                       "attesta quantità correnti, unlock datati o vesting."
                       if doc and verified else
                       "Nessuna fonte primaria di politica monetaria attribuita")}


# Capabilities, not observed flows or claims of institutional buying.
# Entries labelled CONSULTABILE are references for GPT research only.
_SOURCE_MATRIX = (
    ("coingecko", "CoinGecko /coins", "AGGREGATORE",
     "INTEGRATO", "https://api.coingecko.com/api/v3/coins/",
     "Supply, market cap e FDV per ID attribuito", "Non certifica chain, unlock, domanda o identita del conto"),
    ("release_primarie", "Release repository di progetto", "FONTE_PRIMARIA",
     "INTEGRATO", "https://github.com/",
     "Release software dei soli progetti registrati", "Non prova adozione o movimento del prezzo"),
    ("feed_ufficiali", "Federal Reserve / BCE / Consiglio UE", "FONTE_PRIMARIA",
     "INTEGRATO", "https://www.federalreserve.gov/",
     "Titoli ufficiali RSS gia acquisiti da KDD", "Nessun impatto crypto o sorpresa vs consenso dedotto"),
    ("coinglass_web", "CoinGlass ETF e derivati", "AGGREGATORE",
     "CONSULTABILE_DA_GPT_NON_ACQUISITO", "https://www.coinglass.com/it/etf/bitcoin",
     "Flussi ETF, OI, funding e liquidazioni consultabili", "OI non equivale a capitale istituzionale spot"),
    ("coinglass_api", "CoinGlass API premium", "AGGREGATORE",
     "INDISPONIBILE", "https://www.coinglass.com/it/pricing",
     "Integrazione automatica CoinGlass", "Nessun piano a pagamento o chiave autorizzati"),
    ("farside", "Farside Bitcoin ETF Flow", "AGGREGATORE",
     "CONSULTABILE_DA_GPT_NON_ACQUISITO", "https://farside.co.uk/bitcoin-etf-flow-all-data/",
     "Flussi netti giornalieri degli ETF spot BTC", "Non distingue investitori istituzionali e retail"),
    ("cftc_cme", "CFTC Commitments of Traders / CME", "FONTE_PRIMARIA",
     "INTEGRATO_CAMPIONE_BTC_FUTURES", "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
     "Posizionamento settimanale futures regolamentati", "Dati ritardati, non il complesso del mercato crypto"),
    ("sec_13f", "SEC Form 13F", "FONTE_PRIMARIA",
     "CONSULTABILE_DA_GPT_NON_ACQUISITO", "https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f",
     "Partecipazioni dichiarate da soggetti obbligati", "Disclosure trimestrale ritardata, non flusso in tempo reale"),
    ("defillama", "DefiLlama Stablecoins", "AGGREGATORE_ONCHAIN",
     "CONSULTABILE_DA_GPT_NON_ACQUISITO", "https://defillama.com/stablecoins/chains",
     "Supply stablecoin per chain e variazioni", "L'aumento di supply non prova acquisti crypto istituzionali"),
    ("cryptopanic", "CryptoPanic", "INDICE_NOTIZIE",
     "CONSULTABILE_DA_GPT_NON_ACQUISITO", "https://cryptopanic.com/developers/api/",
     "Scoperta opzionale di notizie", "Non misura capitali; verificare la fonte primaria; API con autenticazione"),
)


def sources_matrix():
    return [{"id": key, "fonte": source, "tipo": kind, "stato": status,
             "url": url, "copertura": coverage, "limite": caveat}
            for key, source, kind, status, url, coverage, caveat in _SOURCE_MATRIX]


def canonical_token(token):
    if token in ("XBT", "XXBT", "BTC"):
        return "BTC"
    if token in ("XDG", "XXDG", "DOGE"):
        return "DOGE"
    return token

KNOWN_MACRO = {
    "Fed — politica monetaria": "www.federalreserve.gov",
    "BCE — comunicati e discorsi": "www.ecb.europa.eu",
    "BCE — operazioni di mercato": "mid.ecb.europa.eu",
    "Consiglio UE — comunicati": "www.consilium.europa.eu",
}


def stamp(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            t = dt.datetime.fromtimestamp(value, UTC)
        elif isinstance(value, str):
            try:
                t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                t = email.utils.parsedate_to_datetime(value)
        else:
            return None
        if t.tzinfo is None:
            return None
        return t.astimezone(UTC)
    except (ValueError, OverflowError, TypeError, OSError):
        return None


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _kraken_binding(token, pair, pair_key, catalog):
    """Exact online REST key, wsname and base; never accept a guessed key."""
    if not isinstance(token, str) or not isinstance(pair, str) or not isinstance(pair_key, str):
        return None
    if not isinstance(catalog, dict):
        return None
    observed = catalog.get(pair_key)
    if not isinstance(observed, dict) or pair.count("/") != 1:
        return None
    base, quote = pair.split("/")
    expected = canonical_token(token)
    if (canonical_token(base) != expected or quote not in ("EUR", "USD", "USDC")
            or observed.get("pair_key") != pair_key or observed.get("pair") != pair
            or observed.get("base") != base or observed.get("quote") != quote):
        return None
    return observed


def _dynamic_valid(token, pair, record):
    """Recheck stored independent market proof; an arbitrary CoinGecko ID fails."""
    if not isinstance(record, dict) or record.get("metodo") != "KRAKEN_COINGECKO_MARKET":
        return False
    proof = record.get("prova_mercato")
    if not isinstance(proof, dict) or not isinstance(pair, str) or pair.count("/") != 1:
        return False
    base, quote = pair.split("/")
    coin_id = record.get("coingecko_id")
    return bool(isinstance(coin_id, str) and re.fullmatch(r"[a-z0-9-]{2,120}", coin_id)
                and isinstance(record.get("progetto"), str) and record["progetto"]
                and proof.get("exchange") == "kraken"
                and proof.get("is_stale") is False
                and proof.get("is_anomaly") is False
                and proof.get("symbol") == canonical_token(token)
                and canonical_token(proof.get("base")) == canonical_token(base)
                and proof.get("target") == quote
                and proof.get("ricerca_url") == CG_SEARCH + canonical_token(token)
                and proof.get("ticker_url") == CG + coin_id + "/tickers?exchange_ids=kraken"
                and stamp(proof.get("verificato_utc")) is not None)


def identify(token, pair, pair_key, *, catalog=None, discovered=None):
    """Kraken ONLINE binding + curated data, or independently matched CoinGecko market."""
    base = {"stato": "NON_VERIFICATO", "token": token,
            "coppia": pair, "pair_key": pair_key,
            "motivo": "IDENTITA_NON_ATTESTATA",
            "limite": "Nessuna attribuzione CoinGecko dal solo ticker"}
    observed = _kraken_binding(token, pair, pair_key, catalog)
    if observed is None:
        return dict(base, motivo="COPPIA_KRAKEN_NON_VERIFICATA")
    normalized = canonical_token(token)
    if normalized in PROJECTS:
        cg, name, repository = PROJECTS[normalized]
        return dict(base, stato="IDENTITA_VERIFICATA_DA_CATALOGO",
                    token_progetto=normalized, asset_base_kraken=observed["base"],
                    progetto=name, coingecko_id=cg, repository_primario=repository,
                    metodo="REGISTRO_CURATO", motivo=None,
                    fonte_identita="Kraken AssetPairs ONLINE + kdd_project_catalog.json",
                    limite=("Registry curato: chain/contract e negoziabilita conto non attestati. "
                            + PROJECT_CAVEATS.get(normalized, "")))
    if not _dynamic_valid(token, pair, discovered):
        return dict(base, motivo="PROGETTO_NON_NEL_CATALOGO_CURATO")
    return dict(base, stato="IDENTITA_VERIFICATA_DA_CATALOGO",
                token_progetto=normalized, asset_base_kraken=observed["base"],
                coingecko_id=discovered["coingecko_id"],
                progetto=discovered["progetto"], repository_primario=None,
                metodo="KRAKEN_COINGECKO_MARKET",
                prova_mercato=dict(discovered["prova_mercato"]),
                motivo=None,
                fonte_identita="Kraken AssetPairs ONLINE + CoinGecko search + market ticker Kraken",
                limite="Attribuzione incrociata, non prova di chain/contract, migrazione o negoziabilita sul conto")


def resolve_public(token, pair, search_result, market_results, now):
    """Require EVERY exact-symbol search candidate checked against its Kraken market.

    If CoinGecko's result list is too large or even one candidate was not
    checked, the identity remains unresolved. Never choose the first hit.
    """
    blank = {"stato": "NON_VERIFICATO", "motivo": "RISULTATI_ASSENTI"}
    if not isinstance(search_result, dict) or not isinstance(search_result.get("coins"), list):
        return dict(blank, motivo="RICERCA_NON_DISPONIBILE")
    exact = [c for c in search_result["coins"]
             if isinstance(c, dict) and isinstance(c.get("symbol"), str)
             and c["symbol"].upper() == canonical_token(token)
             and isinstance(c.get("id"), str)
             and re.fullmatch(r"[a-z0-9-]{2,120}", c["id"])
             and isinstance(c.get("name"), str) and c["name"]]
    if len(search_result["coins"]) >= 100:
        return dict(blank, motivo="RISULTATI_RICERCA_PAGINATI_NON_ESAUSTIVI")
    if not exact:
        return blank
    if len(exact) > MAX_MARKET_CANDIDATES:
        return dict(blank, motivo="TICKER_OMONIMI_SUPERANO_BUDGET")
    if len({c["id"] for c in exact}) != len(exact):
        return dict(blank, motivo="TICKER_AMBIGUO_RICERCA_NON_ESAUSTIVA")
    if not isinstance(market_results, dict) or any(c["id"] not in market_results
                                                    or market_results[c["id"]] is None
                                                    for c in exact):
        return dict(blank, motivo="MERCATI_COINGECKO_NON_COMPLETI")
    base, target = pair.split("/") if isinstance(pair, str) and pair.count("/") == 1 else ("", "")
    matches = []
    for coin in exact:
        response = market_results[coin["id"]]
        if (not isinstance(response, dict) or not isinstance(response.get("tickers"), list)
                or (response.get("name") is not None and response.get("name") != coin["name"])):
            return dict(blank, motivo="RISPOSTA_MARKET_NON_VALIDA")
        if len(response["tickers"]) >= 100:
            return dict(blank, motivo="MERCATI_PAGINATI_NON_ESAUSTIVI")
        if any(isinstance(t, dict)
               and isinstance(t.get("market"), dict)
               and t["market"].get("identifier") == "kraken"
               and canonical_token(t.get("base")) == canonical_token(base)
               and t.get("target") == target
               and t.get("is_anomaly") is False
               and t.get("is_stale") is False
               for t in response["tickers"]):
            matches.append(coin)
    if len(matches) != 1:
        return dict(blank, motivo=("NESSUN_MERCATO_KRAKEN_CONFERMATO" if not matches
                                  else "TICKER_AMBIGUO_SU_KRAKEN"))
    coin = matches[0]
    proof = {"exchange": "kraken", "symbol": canonical_token(token),
             "is_stale": False, "is_anomaly": False,
             "base": base, "target": target,
             "ricerca_url": CG_SEARCH + canonical_token(token),
             "ticker_url": CG + coin["id"] + "/tickers?exchange_ids=kraken",
             "verificato_utc": now.isoformat(timespec="seconds")}
    return {"stato": "RISOLTO", "metodo": "KRAKEN_COINGECKO_MARKET",
            "coingecko_id": coin["id"], "progetto": coin["name"],
            "prova_mercato": proof}

def evidence_ref(family, *parts):
    """Stable *internal* evidence identifier derived from an attributable fact.

    An evidence ID is a navigation reference, NOT a signature or proof of the
    original provider's authenticity. It is recalculated at consumer read.
    """
    if not isinstance(family,str) or any(not isinstance(p,(str,int,float))
                                           for p in parts):
        return None
    material="\x1f".join(str(p) for p in (family,)+parts)
    return "E-"+family+"-"+hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def market_batch_url(ids):
    """Deterministic public /coins/markets supply request for verified IDs."""
    if (not isinstance(ids,(list,tuple)) or not 1<=len(ids)<=MAX_CG_BATCH_IDS
            or len(set(ids))!=len(ids)
            or any(not isinstance(pid,str) or not re.fullmatch(r"[a-z0-9-]{2,120}",pid)
                   for pid in ids)):
        raise ValueError("Batch CoinGecko IDs non validi")
    return (CG_MARKETS+"vs_currency=usd&ids="
            +quote(",".join(sorted(ids)),safe=",")
            +"&order=market_cap_desc&per_page=50&page=1&sparkline=false")


def fundamental_source_valid(url,project_id):
    """Validate exact source URL: one /coins ID or this registered batch."""
    if not isinstance(project_id,str) or not re.fullmatch(r"[a-z0-9-]{2,120}",project_id):
        return False
    if url==CG+project_id:
        return True
    if not isinstance(url,str) or not url.startswith(CG_MARKETS):
        return False
    parsed=urlparse(url)
    if (parsed.scheme!="https" or parsed.hostname!="api.coingecko.com"
            or parsed.username or parsed.password or parsed.fragment
            or parsed.path!="/api/v3/coins/markets"):
        return False
    query=parse_qs(parsed.query,keep_blank_values=True)
    if set(query)!=set(("vs_currency","ids","order","per_page","page","sparkline")):
        return False
    candidates=query["ids"]
    if len(candidates)!=1:
        return False
    ids=candidates[0].split(",")
    try:
        return project_id in ids and market_batch_url(ids)==url
    except ValueError:
        return False


def market_batch_fundamentals(identity,row,now,acquired,source_url, *, acquisition=None):
    """Adapt a real /coins/markets item to the existing fundamentals engine.

    This is only a formatting adapter. No source-less synthetic supply is used:
    the exact batch HTTP request is recorded and verified at GPT read time.
    """
    if (not isinstance(row,dict) or not isinstance(identity,dict)
            or not fundamental_source_valid(source_url,identity.get("coingecko_id"))):
        return fundamentals(identity,None,now,acquired)
    fields=("market_cap","fully_diluted_valuation",
            "circulating_supply","total_supply","max_supply")
    data={key:row.get(key) for key in fields}
    raw={"id":row.get("id"),"symbol":row.get("symbol"),
         "name":row.get("name"),"market_data":dict(data,
             last_updated=row.get("last_updated"),
             market_cap={"usd":data["market_cap"]},
             fully_diluted_valuation={"usd":data["fully_diluted_valuation"]})}
    return fundamentals(identity,raw,now,acquired,source_url=source_url,
                        acquisition=acquisition)


def _supply_consistency(data):
    """Structural ratios are observations, not unlock or sell-volume claims."""
    circ,total,maximum=(data.get(k) for k in
                        ("offerta_circolante","offerta_totale","offerta_massima"))
    for field in ("offerta_circolante","offerta_totale","offerta_massima",
                  "capitalizzazione_usd","fdv_usd"):
        v=data.get(field)
        if v is not None and (type(v) not in (float,int) or
                              not math.isfinite(v) or v<0):
            raise ValueError("Dato economico numerico non valido: "+field)
    diagnostics={"rapporto_fdv_cap":None,
                 "quota_circolante_su_totale_pct":None,
                 "emissione_residua_massima_su_circolante_pct":None,
                 "diluizione":"NON_CALCOLABILE"}
    cap,fdv=data.get("capitalizzazione_usd"),data.get("fdv_usd")
    if cap and fdv:
        diagnostics["rapporto_fdv_cap"]=round(fdv/cap,4)
    inconsistencies=[]
    if circ is not None and total is not None and circ>total:
        inconsistencies.append("CIRCOLANTE_SUPERIORE_AL_TOTALE")
    if circ is not None and maximum is not None and maximum>0 and circ>maximum:
        inconsistencies.append("CIRCOLANTE_SUPERIORE_AL_MASSIMO")
    if total is not None and maximum is not None and maximum>0 and total>maximum:
        inconsistencies.append("TOTALE_SUPERIORE_AL_MASSIMO")
    if maximum==0:
        diagnostics["diluizione"]="MAX_ZERO_DATO_ANOMALO"
        inconsistencies.append("MASSIMO_ZERO")
    elif maximum is None:
        diagnostics["diluizione"]="MAX_NON_DICHIARATO_NON_EQUIVALE_A_ILLIMITATO"
    elif circ is not None and circ>maximum:
        diagnostics["diluizione"]="SUPPLY_MAX_INFERIORE_AL_CIRCOLANTE_ANOMALIA"
    elif circ is not None and circ>0:
        diagnostics["diluizione"]="RAPPORTO_CALCOLABILE"
    elif circ==0:
        diagnostics["diluizione"]="CIRCOLANTE_ZERO"
    if not inconsistencies:
        if circ is not None and total is not None and total>0:
            diagnostics["quota_circolante_su_totale_pct"]=round(100*circ/total,4)
        if circ is not None and circ>0 and maximum is not None and maximum>0:
            diagnostics["emissione_residua_massima_su_circolante_pct"]=round(
                100*(maximum-circ)/circ,4)
    return diagnostics,sorted(set(inconsistencies))


def verify_supply_at_read(fundamental):
    """Recheck numeric source semantics at every packet/bridge consumption.

    Source text plus packet checksum alone cannot attest the economic values.
    Ratios are recomputed; missing raw values never become zeros, schedules
    or proof of sale. Legacy readings without our derived fields stay readable.
    """
    if not isinstance(fundamental,dict):
        raise ValueError("Fondamentali non strutturati")
    proof=fundamental.get("prova_acquisizione")
    if proof is not None:
        if not isinstance(proof,dict):
            raise ValueError("Provenienza fondamentali non strutturata")
        status=proof.get("stato","NON_ATTESTATA_DAL_PRODUTTORE")
        if status=="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE":
            digest=proof.get("sha256_corpo_risposta")
            url=proof.get("url_richiesto")
            acquired=stamp(proof.get("acquisito_utc"))
            source=fundamental.get("fonte")
            cg=proof.get("progetto_id")
            if (not isinstance(cg,str) or
                    not fundamental_source_valid(source,cg) or
                    not isinstance(digest,str) or
                    not re.fullmatch(r"[a-f0-9]{64}",digest) or
                    proof.get("canale")!="REQUEST_PUBBLICA_DEL_PRODUTTORE" or
                    not acquired or acquired!=stamp(fundamental.get("acquisito_utc")) or
                    not isinstance(url,str) or
                    not (url==source if isinstance(source,str) and source.startswith(CG_MARKETS)
                         else url==CG+cg+
                         "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false") or
                    proof.get("id_evidenza")!="E-FUND-"+cg+"-"+digest[:16]):
                raise ValueError("Provenienza HTTP fondamentali alterata")
        elif status!="NON_ATTESTATA_DAL_PRODUTTORE":
            raise ValueError("Provenienza fondamentali non riconosciuta")
    if fundamental.get("stato") not in ("VERIFICATO","SCADUTO","ANOMALIA_SUPPLY"):
        return
    expected,anomalies=_supply_consistency(fundamental)
    if fundamental.get("fonte_supply")=="COINGECKO_AGGREGATORE_NON_SCHEDULE_PRIMARIO":
        for k in ("rapporto_fdv_cap","quota_circolante_su_totale_pct",
                  "emissione_residua_massima_su_circolante_pct","diluizione"):
            if fundamental.get(k)!=expected[k]:
                raise ValueError("Fundamentals derived supply inconsistency: "+k)
        if sorted(fundamental.get("anomalie_supply") or [])!=anomalies:
            raise ValueError("Fundamentals anomaly evidence mismatch")
        if (anomalies and fundamental.get("stato") not in ("ANOMALIA_SUPPLY","SCADUTO")
                or not anomalies and fundamental.get("stato")=="ANOMALIA_SUPPLY"):
            raise ValueError("Fundamentals invalid status for contradictory supply")
        if (fundamental.get("unlock")!="NON_VERIFICATO" or
                fundamental.get("vesting")!="NON_VERIFICATO" or
                fundamental.get("prossimo_unlock_utc") is not None or
                fundamental.get("fonte_calendario_unlock") is not None):
            raise ValueError("Fundamentals invented unlock from aggregator")
    elif anomalies and fundamental.get("stato")=="VERIFICATO":
        raise ValueError("Contradictory source cannot be verified")


def fundamentals(identity, payload, now, acquired, *, source_url=None, acquisition=None):
    out = {"stato": "NON_VERIFICATO", "fonte": None, "rilevato_utc": None,
           "prova_acquisizione": {"stato": "NON_ATTESTATA_DAL_PRODUTTORE"},
           "acquisito_utc": acquired.isoformat(timespec="seconds"),
           "capitalizzazione_usd": None, "fdv_usd": None,
           "offerta_circolante": None, "offerta_totale": None,
           "offerta_massima": None, "rapporto_fdv_cap": None,
           "quota_circolante_su_totale_pct": None,
           "emissione_residua_massima_su_circolante_pct": None,
           "fonte_supply": "COINGECKO_AGGREGATORE_NON_SCHEDULE_PRIMARIO",
           "diluizione": "NON_CALCOLABILE", "anomalie_supply": [],
           "unlock": "NON_VERIFICATO",
           "vesting": "NON_VERIFICATO", "prossimo_unlock_utc": None,
           "fonte_calendario_unlock": None,
           "limite": "Nessun calendario vesting deducibile dalla supply"}
    if identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO" or not isinstance(payload, dict):
        return out
    cg = identity["coingecko_id"]
    if (payload.get("id") != cg or payload.get("symbol", "").upper() != canonical_token(identity["token"])
            or payload.get("name") != identity["progetto"]):
        return out
    m = payload.get("market_data")
    if not isinstance(m, dict):
        return out
    updated = stamp(m.get("last_updated"))
    if updated is None or updated > now + dt.timedelta(minutes=2):
        return out
    values = {field: numeric(m.get(key)) for field, key in (
        ("offerta_circolante", "circulating_supply"),
        ("offerta_totale", "total_supply"), ("offerta_massima", "max_supply"))}
    values["capitalizzazione_usd"] = numeric((m.get("market_cap") or {}).get("usd"))
    values["fdv_usd"] = numeric((m.get("fully_diluted_valuation") or {}).get("usd"))
    out.update(values)
    out["rilevato_utc"] = updated.isoformat(timespec="seconds")
    out["fonte"] = source_url if source_url is not None and fundamental_source_valid(source_url,cg) else CG + cg
    # The source URL in the JSON is structural attribution. This separate
    # attestation exists only when the producer actually read the bytes.
    # Mocks can exercise the same path, so no cryptographic authenticity claim.
    if isinstance(acquisition,dict):
        actual_url=acquisition.get("url_richiesto")
        valid_request=(actual_url==source_url if source_url is not None else
                       actual_url==CG+cg+
                       "?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
        sha=acquisition.get("sha256_corpo_risposta")
        observed=stamp(acquisition.get("acquisito_utc"))
        if (valid_request and isinstance(sha,str)
                and re.fullmatch(r"[0-9a-f]{64}",sha)
                and observed and abs((observed-acquired).total_seconds())<=2):
            out["prova_acquisizione"]=dict(acquisition, progetto_id=cg,
                stato="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE",
                id_evidenza="E-FUND-"+cg+"-"+sha[:16])
    age = (now-updated).total_seconds()
    out["stato"] = "VERIFICATO" if age <= 86400 else "SCADUTO"
    diagnostics,anomalies=_supply_consistency(values)
    out.update(diagnostics,anomalie_supply=anomalies)
    if anomalies:
        out["stato"]="ANOMALIA_SUPPLY"
        out["limite"]=("Fonte CoinGecko attribuita ma supply contraddittoria: "
                       +", ".join(anomalies)
                       +"; non inferire diluizione, unlock, immissione o vendita")
    return out


def release_event(identity, release, now, acquired):
    out = {"stato": "NON_VERIFICATO", "tipo": "RELEASE_SOFTWARE",
           "fonte": None, "emittente": None, "pubblicato_utc": None,
           "evento_utc": None, "acquisito_utc": acquired.isoformat(timespec="seconds"),
           "sintesi": None, "limite": "Release non prova impatto sul prezzo né migrazione token"}
    repo = identity.get("repository_primario")
    if not repo or not isinstance(release, dict):
        return out
    link = release.get("html_url")
    expected = "https://github.com/" + repo + "/releases/tag/"
    published = stamp(release.get("published_at"))
    tag = release.get("tag_name")
    if (not isinstance(link, str) or not link.startswith(expected)
            or len(link) <= len(expected) or not published
            or not dt.timedelta(0) <= now-published + dt.timedelta(minutes=2)
            or not isinstance(release.get("name"), str)
            or release.get("draft") is True
            or (tag is not None and (not isinstance(tag, str)
                                     or link != expected + tag))):
        return out
    out.update(stato="VERIFICATO" if now-published <= dt.timedelta(days=90) else "SCADUTO",
               fonte=link, emittente=repo,
               pubblicato_utc=published.isoformat(timespec="seconds"),
               evento_utc=published.isoformat(timespec="seconds"),
               sintesi=release["name"][:180],
               tag=tag if isinstance(tag, str) else link[len(expected):],
               pre_release=release.get("prerelease") is True,
               adozione_rete="NON_VERIFICATA",
               impatto_economico="NON_DIMOSTRATO",
               condizione_riesame="Verificare adozione reale del software, contenuto release e fatti di rete")
    return out


def macro(feed, now):
    """Official, dated headlines anchor *questions*, never asserted price effects."""
    entries = []
    for row in (feed if isinstance(feed, list) else [])[:12]:
        if not isinstance(row, dict):
            continue
        source = row.get("fonte")
        url = row.get("link") or row.get("url")
        if source not in KNOWN_MACRO or not isinstance(url, str):
            continue
        parsed = urlparse(url)
        trusted = (parsed.scheme == "https" and parsed.hostname == KNOWN_MACRO[source]
                   and parsed.username is None and parsed.password is None)
        published = stamp(row.get("data") or row.get("pubblicato_utc"))
        fresh = bool(trusted and published
                     and dt.timedelta(0) <= now-published <= dt.timedelta(days=14))
        entries.append({"fonte": source, "url": url if trusted else None,
                        "titolo": str(row.get("titolo") or "")[:180],
                        "pubblicato_utc": published.isoformat(timespec="seconds") if published else None,
                        "stato": "VERIFICATO" if fresh else "SCADUTO" if trusted and published else "NON_VERIFICATO",
                        "impatto_asset": "NON_VALUTABILE"})
    scenarios = []
    for key, allowed, hypothesis, counter, trigger in (
        ("POLITICA_MONETARIA",
         ("Fed — politica monetaria", "BCE — comunicati e discorsi",
          "BCE — operazioni di mercato"),
         "Una sorpresa monetaria potrebbe cambiare liquidita e costo del rischio.",
         "Il contenuto potrebbe essere atteso dal mercato o compensato da altri fattori.",
         "Verificare testo completo, consenso datato, tassi e reazione osservata."),
        ("GEOPOLITICA_REGOLAZIONE",
         ("Consiglio UE — comunicati",),
         "Una decisione geopolitica o regolatoria potrebbe alterare accesso e rischio di controparte.",
         "La misura potrebbe non riguardare la rete o la coppia dell'asset considerato.",
         "Verificare campo di applicazione, data di efficacia e soggetti coinvolti.")):
        evidence = next((row for row in entries
                         if row["fonte"] in allowed and row["stato"] == "VERIFICATO"), None)
        scenarios.append({"tipo": key,
                          "stato": "IPOTESI_DA_VERIFICARE" if evidence else "NON_VALUTABILE",
                          "fonte": evidence["url"] if evidence else None,
                          "pubblicato_utc": evidence["pubblicato_utc"] if evidence else None,
                          "titolo_osservato": evidence["titolo"] if evidence else None,
                          "ipotesi": hypothesis,
                          "controipotesi": counter,
                          "condizione_di_riesame": trigger,
                          "limite": "Il titolo non prova sorpresa, causalita o impatto su asset."})
    return {"fonti_ufficiali": entries, "scenari_condizionali": scenarios,
            "ipotesi": "Una variazione inattesa della politica monetaria potrebbe modificare le condizioni di liquidita.",
            "controipotesi": "La variazione potrebbe essere gia incorporata nei prezzi o prevalerebbero altri fattori.",
            "condizione_di_riesame": "Confrontare decisione ufficiale, consenso datato e prezzi successivi.",
            "statuto": "IPOTESI_NON_ATTESTATA_DAI_TITOLI_RSS",
            "sorpresa_vs_consenso": "NON_VALUTABILE"}


def regime(btc_four, global_row, now):
    """BTC 4H/1D plus independently observed aggregate capitalization/activity.

    Two BTC frames are one price-signal family; they do not alone constitute
    two independent confirmations. Dominance and turnover are descriptive,
    not proxies for institutional flows or trade recommendations.
    """
    out = {"stato": "INDETERMINATO", "qualita": "INSUFFICIENTE",
           "favorevoli": [], "contrari": [], "mancanti": [],
           "famiglie_osservate": [], "invalidazione": "Riesaminare con chiusure 4H/1D e dati aggregati freschi",
           "limite": "Classificazione descrittiva; non previsione o consiglio"}
    frames = btc_four.get("timeframe") if isinstance(btc_four, dict) else None
    if not isinstance(frames, dict):
        out["mancanti"].append("BTC 4TF verificato")
        return out
    trend = {}
    for label in ("4H", "1D"):
        row = frames.get(label) or {}
        evidence = row.get("figure_candlestick") or {}
        if row.get("stato") == "AGGIORNATO" and evidence.get("stato") == "AGGIORNATO":
            trend[label] = evidence.get("trend_precedente")
    if len(trend) < 2 or any(x not in ("SALITA", "DISCESA", "LATERALE") for x in trend.values()):
        out["mancanti"].append("BTC 4H e 1D aggiornati e confrontabili")
        return out
    out["famiglie_osservate"].append({
        "famiglia": "TREND_BTC", "timeframe": ["4H", "1D"], "stato": "DISPONIBILE",
        "osservazione": dict(trend), "limite": "Un unico mercato in due timeframe"})
    disagree=(trend["4H"]!=trend["1D"])
    if not isinstance(global_row, dict):
        out["mancanti"].append("CoinGecko globale datato")
        return out
    updated = stamp(global_row.get("aggiornato_sorgente_utc"))
    change = global_row.get("var_capitalizzazione_24h_pct")
    if (global_row.get("fonte") not in (None,"https://api.coingecko.com/api/v3/global")
            or not updated or updated > now + dt.timedelta(minutes=2)
            or now-updated > dt.timedelta(hours=2)
            or not isinstance(change, (int, float)) or isinstance(change, bool)
            or not math.isfinite(change)):
        out["mancanti"].append("Variazione capitalizzazione globale fresca")
        return out
    out["famiglie_osservate"].append({
        "famiglia": "CAPITALIZZAZIONE_CRYPTO_AGGREGATA",
        "fonte": global_row.get("fonte") or "https://api.coingecko.com/api/v3/global",
        "pubblicato_utc": updated.isoformat(timespec="seconds"),
        "variazione_24h_pct": change,
        "limite": "Aggregatore, non capitali istituzionali né flussi ETF."})
    cap, volume = (numeric(global_row.get("capitalizzazione_totale_usd")),
                   numeric(global_row.get("volume_24h_usd")))
    if cap is not None and cap > 0 and volume is not None and 0 < volume <= cap*10:
        out["famiglie_osservate"].append({
            "famiglia": "ATTIVITA_AGGREGATA",
            "fonte":global_row.get("fonte") or "https://api.coingecko.com/api/v3/global",
            "turnover_24h_su_cap_pct": round(volume / cap * 100, 4),
            "pubblicato_utc": updated.isoformat(timespec="seconds"),
            "limite": "Rapporto tra volume riportato e capitalizzazione; non prova partecipazione netta o acquisti."})
    else:
        out["mancanti"].append("Volume aggregato 24h e rapporto volume/capitalizzazione attendibile")
    if disagree:
        # A discordant pair of BTC frames is an observed transition only
        # when we can also inspect the fresh aggregate market and participation.
        # A missing CoinGecko observation must stay INDETERMINATO, not create
        # a directionally loaded market regime out of BTC alone.
        out.update(stato="TRANSIZIONE",qualita="PARZIALE",
                   contrari=["BTC 4H e 1D discordanti"])
        if "ATTIVITA_AGGREGATA" not in [
                r.get("famiglia") for r in out["famiglie_osservate"]]:
            out["mancanti"].append("Conferma dei volumi aggregati")
        return out
    out["favorevoli"].append("BTC 4H/1D concordi: " + trend["4H"])
    # Sideways BTC with a directional broad market is a contradiction, not a
    # neutral regime. This threshold separates clearly directional changes
    # from near-zero noise; it is an engineering rule, not a trading signal.
    if trend["4H"] == "LATERALE":
        if abs(change) > 1:
            out.update(stato="TRANSIZIONE", qualita="PARZIALE",
                       contrari=["BTC laterale mentre capitale aggregato varia oltre 1% in 24H"])
        else:
            out.update(stato="LATERALE", qualita="PARZIALE",
                       favorevoli=out["favorevoli"] + ["Variazione aggregata contenuta"])
        return out
    direction = "RIALZISTA" if trend["4H"] == "SALITA" else "RIBASSISTA"
    # Zero broad-market change is an abstention; it cannot confirm either
    # direction. Never let missing/invalid volume stand in for confirmation.
    if change == 0:
        out.update(stato="INDETERMINATO", qualita="INSUFFICIENTE",
                   contrari=["Capitalizzazione aggregata 24h senza direzione"])
    elif (change > 0) == (direction == "RIALZISTA"):
        out.update(stato=direction, qualita="PARZIALE")
        out["favorevoli"].append("Capitalizzazione aggregata 24h concorde")
    else:
        out.update(stato="TRANSIZIONE", qualita="PARZIALE")
        out["contrari"].append("Capitalizzazione aggregata 24h contraria al trend BTC")
    out["mancanti"].append("Derivati con copertura e confronto partecipazione/volumi tra rilevazioni")
    return out



def regime_participation(base, derivatives, primary, now, previous=None):
    """KDD-22: independently dated futures participation and ECB facts.

    OI is leverage exposure, not institutional capital. CVD of one Kraken
    contract may contradict the broader context, not predict an asset trade.
    No source here constitutes two independent confirmation signals.
    """
    out = dict(base)
    out["famiglie_osservate"] = list(base.get("famiglie_osservate") or [])
    out["mancanti"] = list(base.get("mancanti") or [])
    out["contrari"] = list(base.get("contrari") or [])
    out["favorevoli"] = list(base.get("favorevoli") or [])
    out["acquisito_utc"]=now.isoformat(timespec="seconds")
    prior=previous if isinstance(previous,dict) else {}
    old_history=prior.get("storico_regimi")
    old_history=old_history if isinstance(old_history,list) else []
    chronology=[]
    for point in old_history[-8:]+([prior] if prior else []):
        if not isinstance(point,dict):
            continue
        when=stamp(point.get("acquisito_utc"))
        state=point.get("stato")
        if (when and dt.timedelta(0)<=now-when<=dt.timedelta(days=7)
                and state in ("RIALZISTA","RIBASSISTA","LATERALE","TRANSIZIONE","INDETERMINATO")
                and (not chronology or chronology[-1]["acquisito_utc"]!=when.isoformat(timespec="seconds"))):
            chronology.append({"acquisito_utc":when.isoformat(timespec="seconds"),
                               "stato":state,"qualita":str(point.get("qualita") or "NON_NOTA")[:70]})
    out["storico_regimi"]=chronology[-8:]
    if chronology:
        out["confronto_precedente"]={
            "stato_precedente":chronology[-1]["stato"],
            "acquisito_precedente_utc":chronology[-1]["acquisito_utc"],
            "nota":"Un cambiamento di classificazione è una revisione del modello, non un evento di mercato"}
    out["ipotesi"] = "Partecipazione futures e condizioni macro potrebbero modificare la robustezza del regime"
    out["controipotesi"] = "CVD e OI di un singolo future non rappresentano il mercato crypto né i flussi Spot"
    out["condizione_di_riesame"] = "Rilevare nuovamente chiusure 4H/1D, attività aggregata e flussi futures con orari coerenti"
    frame = derivatives if isinstance(derivatives, dict) else {}
    oi = frame.get("open-interest") if isinstance(frame.get("open-interest"), dict) else {}
    cvd = frame.get("cvd") if isinstance(frame.get("cvd"), dict) else {}
    oi_time = stamp(oi.get("ultimo_punto_utc"))
    cvd_time = stamp(cvd.get("ultimo_punto_utc"))
    def finite(value):
        return (type(value) in (int,float) and math.isfinite(value))
    valid = (oi_time is not None and cvd_time is not None
             and dt.timedelta(0) <= now - oi_time <= dt.timedelta(hours=4)
             and dt.timedelta(0) <= now - cvd_time <= dt.timedelta(hours=4)
             and abs((oi_time-cvd_time).total_seconds()) <= 3600
             and oi.get("ultimo_punto_provvisorio") is False
             and cvd.get("ultimo_punto_provvisorio") is False
             and all(finite(v) for v in (oi.get("ultimo_close"),oi.get("close_4h_fa"),
                   cvd.get("ultimo_cvd"),cvd.get("cvd_4h_fa")))
             and oi["ultimo_close"] > 0 and oi["close_4h_fa"] > 0)
    if valid:
        oi_change = round(100*(oi["ultimo_close"]/oi["close_4h_fa"]-1),4)
        cvd_delta = cvd["ultimo_cvd"]-cvd["cvd_4h_fa"]
        out["famiglie_osservate"].append({
            "famiglia":"DERIVATI_BTC_KRAKEN", "fonte":"https://futures.kraken.com/api/charts/v1/analytics/PF_XBTUSD/",
            "strumento":"PF_XBTUSD","osservato_utc":max(oi_time,cvd_time).isoformat(timespec="seconds"),
            "var_oi_4h_pct":oi_change,"cvd_delta_4h":cvd_delta,
            "limite":"Singolo contratto; OI non identifica la direzione, CVD non equivale a flussi spot istituzionali"})
        out["mancanti"] = [s for s in out["mancanti"] if "Derivati con copertura" not in s]
        if (out.get("stato") in ("RIALZISTA","RIBASSISTA") and cvd_delta != 0
                and ((cvd_delta>0) != (out["stato"]=="RIALZISTA"))):
            out["contrari"].append("CVD 4H di PF_XBTUSD divergente dalla classificazione del mercato aggregato")
            out["qualita"]="PARZIALE_CON_CONTRADDIZIONI"
    else:
        out["mancanti"].append("OI e CVD Kraken PF_XBTUSD chiusi, recenti e concordanti temporalmente")
    rows = primary.get("indicatori_macro") if isinstance(primary, dict) else None
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict) or item.get("stato") != "OSSERVATO":
                continue
            if item.get("id") not in ("USD_EUR","EA_HICP","CFTC_BTC_TFF","CFTC_ETH_TFF") or not finite(item.get("valore")):
                continue
            out["famiglie_osservate"].append({
                "famiglia":("FUTURES_CFTC_" if item["id"] in ("CFTC_BTC_TFF","CFTC_ETH_TFF") else "MACRO_ECB_") + item["id"],"fonte":item.get("fonte"),
                "periodo":item.get("periodo"),"valore":item["valore"],"unita":item.get("unita"),
                "limite":"Dato macro osservato; segno dell'impatto sul prezzo non dedotto"})
    # Separate ETF cash-flow aggregates and per-chain stablecoin supply from
    # the CFTC futures, ECB macro and spot data. Never count twice as independent
    # evidence or turn a flow measurement into an automatic trade.
    financial = primary.get("flussi_finanziari") if isinstance(primary,dict) else None
    if isinstance(financial,list):
        for rec in financial:
            if (not isinstance(rec,dict)
                    or rec.get("stato") not in ("OSSERVATO","STORICO_NON_AGGIORNATO")):
                continue
            acquired=stamp(rec.get("acquisito_utc"))
            kind=rec.get("id")
            allowed_age=(dt.timedelta(days=4) if kind.startswith("ETF_")
                         else dt.timedelta(days=2))
            if not acquired or not dt.timedelta(0)<=now-acquired<=allowed_age:
                continue
            data=rec.get("dati") or {}
            observed_period=stamp(str(data.get("periodo"))+"T00:00:00+00:00")
            if kind.startswith("ETF_") and (not observed_period
                    or now-observed_period>dt.timedelta(days=8)
                    or observed_period>now+dt.timedelta(days=1)):
                continue
            if kind in ("ETF_BTC_FARSIDE","ETF_ETH_FARSIDE") and type(data.get("valore")) in (int,float):
                out["famiglie_osservate"].append({
                    "famiglia":"ETF_SPOT_AGGREGATO",
                    "asset":"BTC" if kind=="ETF_BTC_FARSIDE" else "ETH",
                    "fonte":rec["fonte"],"freschezza":rec["stato"],
                    "acquisito_utc":rec.get("acquisito_utc"),"periodo":data.get("periodo"),
                    "flusso_netto_milioni_usd":data["valore"],
                    "limite":"Stessa famiglia di dati aggregati ETF: non acquisti istituzionali individuali"})
                if (kind=="ETF_BTC_FARSIDE" and rec.get("stato")=="OSSERVATO"
                        and out.get("stato") in ("RIALZISTA","RIBASSISTA")):
                    contradictory=(data["valore"]<0 and out["stato"]=="RIALZISTA"
                                   or data["valore"]>0 and out["stato"]=="RIBASSISTA")
                    if contradictory:
                        out["contrari"].append("Flusso netto ETF BTC aggregato divergente dal regime tecnico BTC")
                        out["qualita"]="PARZIALE_CON_CONTRADDIZIONI"
            if kind=="STABLECOIN_LLAMA" and isinstance(data.get("top_chain"),list):
                out["famiglie_osservate"].append({
                    "famiglia":"DISTRIBUZIONE_STABLECOIN_PER_CHAIN",
                    "fonte":rec["fonte"],"acquisito_utc":rec.get("acquisito_utc"),
                    "freschezza":rec["stato"],"top_chain":data["top_chain"],
                    "limite":"Supply per chain aggregata; non nuova liquidità acquistatrice o flusso ETF"})
    return out


def regime_integrato(core, macro, now):
    """CP4: conservative final decision from ALREADY observed KDD-22 families.

    A BTC trend is one source family across 4H+1D. CoinGecko market change
    and turnover are one other family, not two votes. ETF flows, CVD and OI
    are independent diagnostics with narrower coverage. Fed/ECB/CFTC headlines
    are dated context, never an automatic vote for a bullish/bearish label.
    """
    allowed=("RIALZISTA","RIBASSISTA","LATERALE","TRANSIZIONE","INDETERMINATO")
    core=core if isinstance(core,dict) else {}
    macro=macro if isinstance(macro,dict) else {}
    preliminary=core.get("stato")
    observations=core.get("famiglie_osservate")
    observations=observations if isinstance(observations,list) else []
    families={}
    for row in observations:
        if not isinstance(row,dict):continue
        family=row.get("famiglia")
        if family=="TREND_BTC":
            families["BTC_CERTEZZA_TREND"]=row
        elif family=="CAPITALIZZAZIONE_CRYPTO_AGGREGATA":
            families["AGGREGATO_CRYPTO"]=row
        elif family=="ATTIVITA_AGGREGATA":
            families["AGGREGATO_VOLUME"]=row
        elif family=="DERIVATI_BTC_KRAKEN":
            families["DERIVATI_BTC_KRAKEN"]=row
        elif family=="ETF_SPOT_AGGREGATO":
            asset=row.get("asset")
            if asset in ("BTC","ETH"):families["ETF_"+asset]=row
        elif family=="DISTRIBUZIONE_STABLECOIN_PER_CHAIN":
            families["STABLECOIN_STOCK"]=row
        elif isinstance(family,str) and family.startswith(("MACRO_ECB_","FUTURES_CFTC_")):
            families[family]=row
    acquired=stamp(core.get("acquisito_utc"))
    recent=bool(acquired and dt.timedelta(0)<=now-acquired<=dt.timedelta(hours=2))
    btc=families.get("BTC_CERTEZZA_TREND") or {}
    btc_dir=btc.get("osservazione") or {}
    btc_valid=(btc.get("stato")=="DISPONIBILE"
               and all(btc_dir.get(tf) in ("SALITA","DISCESA","LATERALE")
                       for tf in ("4H","1D")))
    global_row=families.get("AGGREGATO_CRYPTO") or {}
    global_when=stamp(global_row.get("pubblicato_utc"))
    global_valid=bool(global_when and recent and
                      dt.timedelta(0)<=now-global_when<=dt.timedelta(hours=2)
                      and global_row.get("fonte")=="https://api.coingecko.com/api/v3/global"
                      and type(global_row.get("variazione_24h_pct")) in (int,float)
                      and math.isfinite(global_row["variazione_24h_pct"]))
    activity=families.get("AGGREGATO_VOLUME") or {}
    turnover=activity.get("turnover_24h_su_cap_pct")
    activity_valid=bool(global_valid and type(turnover) in (int,float)
                        and math.isfinite(turnover) and 0<turnover<=1000
                        and activity.get("pubblicato_utc")==global_row.get("pubblicato_utc")
                        and activity.get("fonte",global_row.get("fonte"))==global_row.get("fonte"))
    missing=[]
    if not recent:missing.append("Regime acquisito da oltre due ore o senza timestamp attendibile")
    if not btc_valid:missing.append("BTC 4H/1D concordi o discordanti verificati")
    if not global_valid:missing.append("Capitalizzazione aggregata CoinGecko fresca e con provenienza")
    if not activity_valid:missing.append("Volume/capitalizzazione globale attendibile")
    contradictions=list(core.get("contrari") or [])
    positives=list(core.get("favorevoli") or [])
    out={
        "stato":"INDETERMINATO","qualita":"INSUFFICIENTE",
        "stato_preliminare":preliminary if preliminary in allowed else "INDETERMINATO",
        "statuto":"REGIME_MOTIVATO_DA_USARE_NEL_CONSUMER_GPT",
        "applicabilita":"MERCATO_GENERALE_NON_ASSET_SINGOLO",
        "evidenze_indipendenti":[{
            "famiglia":"BTC_PREZZO_4H_1D",
            "evidence_id":evidence_ref("REGIME","BTC_4H_1D",
                core.get("acquisito_utc") or "",str(btc_dir)) if btc_valid and recent else None,
            "fonte":"Kraken Spot pubblico /0/public/OHLC",
            "rilevazione_utc":core.get("acquisito_utc"),
            "osservazione":btc_dir if btc_valid else None,
            "stato":"OSSERVATO" if btc_valid and recent else "NON_ATTUALE"
        },{
            "famiglia":"AGGREGATO_CRYPTO_PREZZO_E_ATTIVITA",
            "evidence_id":evidence_ref("REGIME","GLOBAL",
                global_row.get("fonte") or "",global_row.get("pubblicato_utc") or "",
                global_row.get("variazione_24h_pct")) if global_valid and activity_valid else None,
            "fonte":global_row.get("fonte"),
            "osservato_utc":global_row.get("pubblicato_utc"),
            "var_cap_24h_pct":global_row.get("variazione_24h_pct") if global_valid else None,
            "turnover_24h_pct":turnover if activity_valid else None,
            "stato":"OSSERVATO" if global_valid and activity_valid else "INCOMPLETO_O_SCADUTO",
            "limite":"Capitalizzazione e volume sono la medesima famiglia aggregata, non due conferme indipendenti"
        }],
        "famiglie_conferma":[name for name in ("BTC_CERTEZZA_TREND","AGGREGATO_CRYPTO")
                            if (btc_valid if name=="BTC_CERTEZZA_TREND" else global_valid)],
        "famiglie_partecipazione":[name for name in
             ("AGGREGATO_VOLUME","DERIVATI_BTC_KRAKEN","ETF_BTC","ETF_ETH","STABLECOIN_STOCK")
             if name in families and (name!="AGGREGATO_VOLUME" or activity_valid)],
        "osservazioni_distinte":{
            "btc_4h_1d":btc_dir if btc_valid else None,
            "cap_24h_pct":global_row.get("variazione_24h_pct") if global_valid else None,
            "turnover_globale_24h_pct":turnover if activity_valid else None},
        "segnali_favorevoli":positives,"segnali_contrari":contradictions,
        "informazioni_mancanti":missing,
        "invalidazione":"Ricalcolare alla chiusura BTC 4H/1D o al cambio della capitalizzazione e della partecipazione; "
                        "rivedere in caso di segnali contrari ETF/CVD o di dati scaduti",
        "ipotesi_macro":macro.get("scenari_condizionali",[])[:2],
        "stato_contesto_macro":macro.get("stato","NESSUN_DATO_VERIFICABILE_NEL_CAMPIONE"),
        "esito_previsione_prezzo":"NON_INFERIBILE",
        "nessuna_raccomandazione_operativa":True,
        "rilevazione_utc":core.get("acquisito_utc"),
        "limite":"Descrizione del mercato generale, non previsione o segnale sul singolo asset"}
    if not (recent and btc_valid and global_valid and activity_valid):
        return out
    if preliminary not in allowed or preliminary=="INDETERMINATO":
        return out
    # Recalculate the two independent directional assertions from their
    # retained numerical/technical facts, rather than trusting a saved label.
    change=global_row["variazione_24h_pct"]
    first,second=btc_dir["4H"],btc_dir["1D"]
    if first!=second:
        expected="TRANSIZIONE"
    elif first=="LATERALE":
        expected="LATERALE" if abs(change)<=1 else "TRANSIZIONE"
    elif change==0:
        expected="INDETERMINATO"
    else:
        direction="RIALZISTA" if first=="SALITA" else "RIBASSISTA"
        expected=(direction if ((change>0)==(direction=="RIALZISTA"))
                  else "TRANSIZIONE")
    if expected!=preliminary:
        out["segnali_contrari"].append("Etichetta tecnica non coerente con trend BTC e variazione aggregata")
        out["informazioni_mancanti"].append("Ricalcolo del regime tecnico richiesto")
        return out
    # A sideways 4H/1D versus moving capital, a 4H/1D disagreement or
    # global change opposite to BTC is a transition: never a trend confirmed.
    if preliminary=="TRANSIZIONE":
        out.update(stato="TRANSIZIONE",qualita="PARZIALE_CON_CONTRADDIZIONI")
        if not contradictions:
            out["segnali_contrari"].append("Indicatori tecnici e capitalizzazione discordanti")
    else:
        out.update(stato=preliminary,qualita="PARZIALE")
    # Two independently sourced counter-signals do not turn an already
    # contradictory market into an apparently confident direction.
    independent=[]
    for category,fragment in (
        ("DERIVATI","CVD 4H di PF_XBTUSD divergente"),
        ("ETF_BTC","Flusso netto ETF BTC aggregato divergente")):
        if any(fragment in v for v in contradictions) and (
                category=="DERIVATI" and "DERIVATI_BTC_KRAKEN" in families
                or category=="ETF_BTC" and "ETF_BTC" in families):
            independent.append(category)
    if len(independent)>=2 and out["stato"] in ("RIALZISTA","RIBASSISTA"):
        out.update(stato="TRANSIZIONE",qualita="PARZIALE_CON_CONTRADDIZIONI")
        out["segnali_contrari"].append(
            "Due famiglie di partecipazione indipendenti contraddicono il quadro direzionale")
    elif independent and out["stato"] in ("RIALZISTA","RIBASSISTA"):
        out["qualita"]="PARZIALE_CON_CONTRADDIZIONI"
    # Macro headlines are hypotheses, not counted confirmation of trends.
    out["famiglie_conferma"]=["TREND_BTC_4H_1D","CAPITALIZZAZIONE_E_ATTIVITA_AGGREGATA"]
    out["informazioni_mancanti"]=missing
    return out


def decision_context(identity, fundamental, event):
    """A falsifiable review question, never a buy/sell classification."""
    if identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO":
        return {"fatto": "Identita economica non attribuibile",
                "rischio_opportunita_ipotesi": "Un confronto patrimoniale basato su tokenomics omonime sarebbe errato",
                "controipotesi": "Il progetto potrebbe essere identificabile con una fonte Kraken e contract validi",
                "condizione_riesame": "Verificare catalogo Kraken, progetto, chain e contract"}
    if fundamental.get("stato") != "VERIFICATO":
        return {"fatto": "Fondamentali non attuali o non verificati",
                "rischio_opportunita_ipotesi": "Diluizione e valutazione relativa non quantificabili",
                "controipotesi": "I dati mancanti non provano un deterioramento del progetto",
                "condizione_riesame": "Rileggere supply e capitalizzazione da fonte attribuita"}
    if fundamental.get("offerta_massima") is None:
        issue = "Il limite massimo di supply non e dichiarato dalla fonte"
        hypothesis = "La futura emissione potrebbe modificare la quota economica per token"
        opposite = "L'assenza di un massimo non prova emissioni illimitate o vendite"
    else:
        issue = "Capitalizzazione e supply datate disponibili"
        hypothesis = "La diluizione potenziale merita confronto con domanda e valore del progetto"
        opposite = "Supply e FDV da sole non determinano prezzo o calendario unlock"
    if event.get("stato") == "VERIFICATO":
        issue += "; release software ufficiale documentata (" + str(event.get("tag") or "versione") + ")"
        opposite += "; una release non prova adozione della rete o un effetto economico"
    if fundamental.get("emissione_residua_massima_su_circolante_pct") is not None:
        issue += "; emissione residua massima teorica pari al " + str(
            fundamental["emissione_residua_massima_su_circolante_pct"]) + "% del circolante"
    return {"fatto": issue, "rischio_opportunita_ipotesi": hypothesis,
            "controipotesi": opposite,
            "condizione_riesame": "Confrontare supply osservata e schedule primaria datata; "
                                 "per release verificare adozione/rete e non solo annuncio"}


def tokenomics_view(row, primary):
    """One per-asset economic view of the already verified source evidence.

    No HTTP here, no second producer, no default unlock dates and no claim
    that a new token in circulation was sold. Preserves the missing state for
    every genuine portfolio asset and shortlisted market.
    """
    ident=row.get("identita") or {}
    fund=row.get("fondamentali") or {}
    project=(ident.get("coingecko_id") if
             ident.get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO" else None)
    def primary_row(name):
        rows=primary.get(name) if isinstance(primary,dict) else []
        if not project or not isinstance(rows,list):
            return None
        return next((r for r in rows if isinstance(r,dict)
                     and r.get("progetto_id")==project),None)
    schedule=primary_row("calendari") or {}
    issuance=primary_row("politiche_emissioni") or {}
    valid=fund.get("stato")=="VERIFICATO"
    acquisition=fund.get("prova_acquisizione") or {}
    acquisition_claim=acquisition.get("stato","NON_ATTESTATA_DAL_PRODUTTORE")
    # The producer did not retain exact original HTTP bytes in the packet.
    # Its URL/hash/id declaration is useful for provenance tracing, but cannot
    # verify acquisition or source authenticity against an independently held
    # original during a read of this packet.
    acquisition_state=("HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE"
                       if acquisition_claim=="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE"
                       else "ACQUISIZIONE_NON_ATTESTATA")
    anomaly=fund.get("stato")=="ANOMALIA_SUPPLY"
    remaining=fund.get("emissione_residua_massima_su_circolante_pct") if valid else None
    schedule_kind=schedule.get("stato","NON_ACQUISITO")
    schedule_source=schedule.get("fonte")
    schedule_current=schedule_kind in (
        "DOCUMENTO_PRIMARIO_CON_SCHEDULE","DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI",
        "DOCUMENTO_PRIMARIO_REGOLA_VESTING","PROIEZIONE_PRIMARIA_NON_UNLOCK")
    emission_current=issuance.get("stato_alla_lettura")=="OSSERVATO"
    if anomaly:
        state="DATI_SUPPLY_CONTRADDITTORI"
        hypothesis="I valori aggregati discordanti non permettono di quantificare la diluizione"
        counter="L'anomalia della fonte non prova una modifica reale dell'offerta"
    elif not valid and not schedule_current and not emission_current:
        state="SENZA_PROVE_ECONOMICHE_ATTUALI"
        hypothesis="Non è possibile quantificare l'esposizione alla diluizione con i dati presenti"
        counter="Assenza o scadenza della fonte non dimostra tokenomics favorevole o sfavorevole"
    elif valid and schedule_current:
        state="SUPPLY_E_DOCUMENTO_PRIMARIO"
        hypothesis="Una quota non circolante e un piano documentato possono richiedere riesame del rischio di diluizione"
        counter="Programma, circolazione futura e vendita sono osservazioni diverse"
    elif valid and emission_current:
        state="SUPPLY_E_POLITICA_EMISSIONE"
        hypothesis="I parametri ufficiali di emissione possono modificare nel tempo la supply osservata"
        counter="Policy di emissione, supply circolante e vendite sono misure distinte"
    elif schedule_current or emission_current:
        state="FONTE_PRIMARIA_SENZA_SUPPLY_ATTUALE"
        hypothesis="Politiche o piani primari richiedono confronto con supply osservata"
        counter="Senza supply fresca non si puo quantificare la quota effettivamente circolante"
    else:
        state="SOLO_SUPPLY_AGGREGATA"
        hypothesis="La quota ancora non circolante potrebbe modificare la partecipazione economica futura"
        counter="Supply e FDV non attestano un calendario unlock, emissione eseguita o vendita"
    if not project:
        state="IDENTITA_NON_VERIFICATA"
        hypothesis="Non attribuire supply o documenti di progetto a un ticker ambiguo"
        counter="L'assenza di identificazione non equivale ad assenza di emissioni"
    return {
        "token":row.get("token"),"coppia":ident.get("coppia"),
        "progetto_id":project,"stato":state,
        "supply":{
            "stato":fund.get("stato","NON_DISPONIBILE"),
            "validita_strutturale":"VALIDATA" if valid else "NON_VERIFICATA_O_SCADUTA",
            "provenienza_acquisizione":acquisition_state,
            "acquisizione_http_dichiarata":acquisition_claim,
            "integrita_originale_alla_lettura":"NON_RICALCOLABILE_SENZA_CORPO_HTTP",
            "autenticita_fonte_esterna":"NON_ATTESTATA",
            "evidence_id":None,  # No attestation without original bytes
            "riferimento_evidenza_dichiarato":acquisition.get("id_evidenza"),
            "sha256_risposta":acquisition.get("sha256_corpo_risposta"),
            "url_http_dichiarato":acquisition.get("url_richiesto"),
            "fonte_http_effettiva":None,
            "limite_provenienza":"Il produttore dichiara un HTTP e un hash, "
                "ma la lettura non ha il corpo originale: hash ed E-FUND "
                "autoconsistenti NON provano acquisizione o autenticita esterna; "
                "dati supply validati separatamente sul piano strutturale.",
            "fonte":fund.get("fonte") if project else None,
            "rilevato_utc":fund.get("rilevato_utc") if project else None,
            "acquisito_utc":fund.get("acquisito_utc") if project else None,
            "offerta_circolante":fund.get("offerta_circolante") if valid else None,
            "offerta_totale":fund.get("offerta_totale") if valid else None,
            "offerta_massima":fund.get("offerta_massima") if valid else None,
            "capitalizzazione_usd":fund.get("capitalizzazione_usd") if valid else None,
            "fdv_usd":fund.get("fdv_usd") if valid else None,
            "rapporto_fdv_cap":fund.get("rapporto_fdv_cap") if valid else None,
            "quota_circolante_su_totale_pct":fund.get("quota_circolante_su_totale_pct") if valid else None,
            "emissione_residua_massima_su_circolante_pct":remaining,
            "diluizione":fund.get("diluizione","NON_CALCOLABILE"),
            "anomalie":fund.get("anomalie_supply",[]) if anomaly else [],
            "limite":"Dati CoinGecko aggregati, non registro dei token venduti o calendario unlock"},
        "calendario":{
            "stato":schedule_kind,"fonte":schedule_source,
            "acquisito_utc":schedule.get("acquisito_utc"),
            "categoria":(
                "UNLOCK_PROGRAMMATO_QUANTITA"
                if schedule_kind=="DOCUMENTO_PRIMARIO_CON_SCHEDULE" else
                "MASSIMI_SBLOCCABILI_DATATI"
                if schedule_kind=="DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI" else
                "REGOLA_VESTING_SENZA_TRANCHE_ESATTE"
                if schedule_kind=="DOCUMENTO_PRIMARIO_REGOLA_VESTING" else
                "PROIEZIONE_CIRCOLAZIONE_NON_UNLOCK"
                if schedule_kind=="PROIEZIONE_PRIMARIA_NON_UNLOCK" else
                "STORICO_NON_CONFERMATO"
                if schedule_kind in ("STORICO_DA_RICONFERMARE",
                    "PROIEZIONE_STORICA","REGOLA_VESTING_STORICA",
                    "MASSIMI_DATATI_STORICI") else "NON_VERIFICATO"),
            "numero_eventi_documentati":len(schedule.get("eventi") or [])
                if schedule_current else 0,
            "provenienza_documento":schedule.get("stato_acquisizione","NON_ATTESTATA"),
            "sha256_documento_originale":schedule.get("sha256_documento"),
            "prossime_scadenze_documentate":[{
                "evidence_id":evidence_ref("SCHEDULE",project,
                    schedule_source,e.get("data_prevista") or e.get("evento_utc"),
                    e.get("quantita_massima_token") if e.get("quantita_massima_token") is not None
                    else e.get("quantita_token")),
                "data_programmata":e.get("data_prevista") or e.get("evento_utc"),
                "quantita_massima_token":e.get("quantita_massima_token"),
                "quantita_programmata_token":e.get("quantita_token"),
                "esecuzione":"NON_ATTESTATA","vendita":"NON_ATTESTATA"
            } for e in (schedule.get("eventi") or [])[:4]
               if isinstance(e,dict)] if schedule_current else [],
            "realizzazione":"NON_ATTESTATA","vendita":"NON_ATTESTATA",
            "limite":schedule.get("limite") or "Nessun calendario primario associato o corrente"},
        "politica_emissione":{
            "stato":issuance.get("stato_alla_lettura",
                                  issuance.get("stato","NON_ACQUISITO")),
            "fonte":issuance.get("fonte"),
            "acquisito_utc":issuance.get("acquisito_utc"),
            "tipo":issuance.get("tipo"),
            "limite":issuance.get("limite") or "Politica di emissione non acquisita"},
        "rischio_opportunita_ipotesi":hypothesis,
        "controipotesi":counter,
        "condizione_di_riesame":(
            "Controllare identita Kraken/progetto, nuovi dati di supply e "
            "documentazione primaria datata; verificare separatamente "
            "emissione, unlock effettivo, immissione e vendite"),
        "nessun_segnale_operativo":True}


_PROJECT_EVENT_CLASSES={
    "ANNUNCIO_UFFICIALE_KRAKEN":"AVVISO_KRAKEN",
    "STATO_COPPIA_KRAKEN":"RESTRIZIONE_O_TRANSIZIONE_MERCATO",
    "AVVISO_SICUREZZA_REPOSITORY":"ADVISORY_SICUREZZA_NON_EXPLOIT",
    "ISSUE_TECNICA_ETICHETTATA":"SEGNALAZIONE_NON_INCIDENTE_CONFERMATO",
    "PROPOSTA_GOVERNANCE_DOCUMENTALE":"DOCUMENTO_NON_VOTO_DI_RETE",
    "REVISIONE_TOKENOMICS_PRIMARIA":"REVISIONE_PIANO_NON_EMISSIONE",
    "VARIAZIONE_POLICY_EMISSIONE":"VARIAZIONE_POLICY_NON_EMISSIONE",
    "UNLOCK_SOLO_PROGRAMMATO":"UNLOCK_SOLO_PREVISTO",
    "UNLOCK_MASSIMO_DATATO_PRIMARIO":"MASSIMO_SBLOCCABILE_NON_REALIZZAZIONE",
}


def project_events_view(row, verified_primary):
    """KDD-20: the existing reader's per-asset project-event representation.

    It consumes only read-validated source facts and the already authenticated
    release. Event publication, effectiveness and market effects stay separate.
    """
    identity=row.get("identita") or {}
    project=(identity.get("coingecko_id") if
             identity.get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO" else None)
    release=row.get("evento") or {}
    review=row.get("valutazione_fonti_primarie") or {}
    events=[]
    read_time=stamp(verified_primary.get("letto_utc")) if isinstance(verified_primary,dict) else None
    omitted_routine=0
    if project and release.get("stato") in ("VERIFICATO","STORICO_NON_AGGIORNATO","SCADUTO"):
        events.append({
            "tipo":"RELEASE_SOFTWARE","categoria":"SVILUPPO_PROTOCOLLO",
            "fonte":release.get("fonte"),"pubblicato_utc":release.get("pubblicato_utc"),
            "efficacia_programmata_utc":None,"efficacia_confermata_utc":None,
            "acquisito_utc":release.get("acquisito_utc"),
            "stato_prova":release.get("stato"),
            "dettaglio":{"titolo":release.get("sintesi"),"tag":release.get("tag"),
                        "pre_release":release.get("pre_release"),
                        "origine":release.get("origine")},
            "fatto":"Release software pubblicata dal repository ufficiale",
            "ipotesi_economica":"Una modifica del software potrebbe diventare rilevante se adottata",
            "controipotesi":"La release non dimostra adozione, attivazione, modifica tokenomics o prezzo",
            "condizione_di_riesame":"Verificare changelog e attivazione effettiva sulla rete"})
    for f in review.get("fatti",[])[:20]:
        if not isinstance(f,dict) or f.get("tipo") not in _PROJECT_EVENT_CLASSES:
            continue
        kind=f["tipo"]
        d=f.get("dettaglio") if isinstance(f.get("dettaglio"),dict) else {}
        if kind=="STATO_COPPIA_KRAKEN" and d.get("status")=="online" and not d.get("cambiamento"):
            omitted_routine+=1
            continue # routine online is not a project event
        if (kind=="ANNUNCIO_UFFICIALE_KRAKEN"
                and d.get("tipo")!="DELISTING_COMUNICATO"
                and f.get("stato_prova") in
                    ("COMUNICAZIONE_CONCLUSA","STORICO_NON_RICONFERMATO")):
            omitted_routine+=1
            continue # concluded service notice is NOT a new project event
        future=kind in ("UNLOCK_SOLO_PROGRAMMATO","UNLOCK_MASSIMO_DATATO_PRIMARIO")
        dated=f.get("pubblicato_o_periodo_utc")
        published=(d.get("creato_fonte_utc") or dated
                   if kind=="ANNUNCIO_UFFICIALE_KRAKEN" else
                   None if future else dated)
        proof=f.get("stato_prova")
        # An old proposal merely returned in the latest API page is not a
        # newly approved governance decision. Preserve it as dated history.
        parsed=stamp(published)
        if (read_time and parsed and dt.timedelta(days=180)<read_time-parsed
                and kind in ("PROPOSTA_GOVERNANCE_DOCUMENTALE",
                             "ISSUE_TECNICA_ETICHETTATA")):
            proof="DOCUMENTO_DATATO_NON_RICONFERMA_DECISIONE"
        events.append({
            "tipo":kind,"categoria":_PROJECT_EVENT_CLASSES[kind],
            "fonte":f.get("fonte"),"pubblicato_utc":published,
            "aggiornato_fonte_utc":dated if kind=="ANNUNCIO_UFFICIALE_KRAKEN" else None,
            "efficacia_programmata_utc":dated if future else None,
            "efficacia_confermata_utc":None,
            "acquisito_utc":f.get("acquisito_utc"),
            "stato_prova":proof,"prova_documento_origine":f.get("stato_prova"),
            "dettaglio":d,
            "fatto":f.get("fatto"),
            "ipotesi_economica":"Il documento potrebbe modificare il giudizio se confermato e pertinente",
            "controipotesi":"La fonte non dimostra esecuzione, impatto sul conto o causalità di prezzo",
            "condizione_di_riesame":"Verificare documento originale, stato attuale ed eventuale esecuzione"})
    if not project:
        state="IDENTITA_NON_VERIFICATA"
    elif any(e["stato_prova"] in ("VERIFICATO","COMUNICAZIONE_UFFICIALE",
              "DOCUMENTO_REPOSITORY","PROPOSTA_DOCUMENTALE","CONFRONTO_DOCUMENTALE",
              "SEGNALAZIONE_NON_CONFERMA","PROGRAMMA_PRIMARIO","MASSIMO_PRIMARIO_PROGRAMMATO",
              "OSSERVAZIONE_API","CONFRONTO_RPC") for e in events):
        state="EVENTI_O_DOCUMENTI_RILEVANTI_NEL_CAMPIONE"
    elif events:
        state="SOLO_EVIDENZE_STORICHE_O_NON_RICONFERMATE"
    else:
        state="NESSUN_EVENTO_IDENTIFICATO_NEL_CAMPIONE"
    # Navigation IDs are composed after producer + project attribution checks:
    # a schedule is not a sale and a document is not implementation.
    for event in events:
        if event.get("fonte"):
            event["evidence_id"]=evidence_ref("EVENTO",project,event.get("tipo"),
                event["fonte"],event.get("pubblicato_utc") or
                event.get("efficacia_programmata_utc") or "DATA_NON_ATTESTATA")
    # Missing coverage is explicit even if no events occurred in sampled feeds.
    families={}
    for name in ("progetti","segnalazioni_repo","avvisi_repository"):
        rows=verified_primary.get(name) if isinstance(verified_primary,dict) else []
        match=next((x for x in rows if isinstance(x,dict) and
                    x.get("progetto_id")==project),{}) if isinstance(rows,list) else {}
        families[name]=match.get("stato_alla_lettura",match.get("stato","NON_ACQUISITO"))
    unshown=review.get("non_mostrati_per_tipo")
    hidden={k:v for k,v in (unshown or {}).items()
            if k in _PROJECT_EVENT_CLASSES and type(v) is int and v>0} if isinstance(unshown,dict) else {}
    return {"token":row.get("token"),"coppia":identity.get("coppia"),
            "progetto_id":project,"stato":state,"eventi":events[:18],
            "eventi_non_mostrati":sum(hidden.values())+max(0,len(events)-18),
            "notifiche_ordinarie_escluse":omitted_routine,
            "non_mostrati_per_tipo":hidden,
            "copertura_fonti":dict(families,release=release.get("stato","NON_ACQUISITO")),
            "limite":"Un campione vuoto o una fonte fallita non prova assenza di eventi; "
                     "una notizia non equivale a voto, exploit, unlock eseguito o vendita",
            "nessuna_causalita_di_prezzo":True}


def macro_primary_context(primary, published_feed, now):
    """CP3: economic context from one read-validated primary producer only.

    Observed number / published official decision / hypothesis are distinct.
    This context is global, not evidence that a particular coin will move.
    """
    primary=primary if isinstance(primary,dict) else {}
    published_feed=published_feed if isinstance(published_feed,dict) else {}
    rss=primary.get("eventi_macro_ufficiali")
    rss=rss if isinstance(rss,list) else []
    indicators=primary.get("indicatori_macro")
    indicators=indicators if isinstance(indicators,list) else []
    financial=primary.get("flussi_finanziari")
    financial=financial if isinstance(financial,list) else []
    facts=[]
    source_coverage={}
    urls=set()
    for family in rss:
        fid=family.get("id")
        state=family.get("stato_alla_lettura",family.get("stato","NON_ACQUISITO"))
        source_coverage[fid]=state
        if state not in ("OSSERVATO","STORICO_NON_AGGIORNATO"):
            continue
        for notice in family.get("eventi",[])[:5]:
            if notice["fonte"] in urls:
                continue
            urls.add(notice["fonte"])
            published=stamp(notice["pubblicato_utc"])
            status=("PUBBLICAZIONE_RECENTE" if state=="OSSERVATO" and
                    published and now-published<=dt.timedelta(days=14)
                    else "PUBBLICAZIONE_DATATA_O_NON_RICONFERMATA")
            facts.append({
                "classe":"COMUNICATO_UFFICIALE",
                "evidence_id":evidence_ref("MACRO",notice["tipo"],
                    notice["fonte"],notice["pubblicato_utc"]),
                "sha256_feed_originale":family.get("sha256_feed_originale"),
                "provenienza_feed":family.get("stato_acquisizione","NON_ATTESTATA"),
                "integrita_feed_alla_lettura":family.get(
                    "integrita_feed_alla_lettura",
                    "IMPRONTA_ORIGINALE_NON_DISPONIBILE"),
                "tipo":notice["tipo"],
                "fatto_osservato":"Pubblicazione di un comunicato ufficiale verificato nel feed",
                "titolo":notice["titolo"],"fonte":notice["fonte"],
                "pubblicato_utc":notice["pubblicato_utc"],
                "precisione_pubblicazione":notice.get("precisione_pubblicazione"),
                "aggiornato_fonte_utc":notice.get("aggiornato_fonte_utc"),
                "acquisito_utc":family.get("acquisito_utc"),
                "efficacia_confermata_utc":None,
                "stato_prova":status,
                "possibile_conseguenza":(
                    "La comunicazione monetaria potrebbe incidere sul costo del rischio"
                    if fid=="FED_MONETARY_RSS" else
                    "Misure geopolitiche potrebbero modificare accesso, controparti o appetito per il rischio"),
                "interpretazione_alternativa":(
                    "Una comunicazione attesa non determina di per se nuova liquidita o direzione dei prezzi"
                    if fid=="FED_MONETARY_RSS" else
                    "La misura potrebbe non colpire mercati crypto, protocolli o controparti dell'asset"),
                "riesame":"Verificare testo integrale, soggetti, efficacia e dati di mercato indipendenti",
                "limite":"Fonte ufficiale primaria: titolo non certifica efficacia o reazione del mercato"})
    for indicator in indicators:
        key=indicator.get("id")
        state=indicator.get("stato","NON_ACQUISITO")
        source_coverage[key]=state
        if (indicator.get("valore") is None or
                state not in ("OSSERVATO","STORICO_NON_AGGIORNATO","SCADUTO")):
            continue
        facts.append({
            "classe":"INDICATORE_PUBBLICO",
            "evidence_id":evidence_ref("MACRO",key,indicator.get("fonte") or "",
                                       indicator.get("periodo") or ""),
            "tipo":key,"fatto_osservato":"Valore pubblicato da serie ufficiale, soggetto a revisioni",
            "fonte":indicator.get("fonte"),"pubblicato_utc":None,
            "periodo":indicator.get("periodo"),"acquisito_utc":indicator.get("acquisito_utc"),
            "valore":indicator.get("valore"),"unita":indicator.get("unita"),
            "stato_prova":state,
            "possibile_conseguenza":"Indicatori monetari e futures possono modificare le condizioni di rischio",
            "interpretazione_alternativa":"Una variazione non dimostra flussi crypto o causalita di mercato",
            "riesame":"Controllare aggiornamento e confronto della stessa serie ufficiale",
            "limite":indicator.get("limite")})
    for flow in financial:
        key=flow.get("id")
        state=flow.get("stato_alla_lettura",flow.get("stato","NON_ACQUISITO"))
        source_coverage[key]=state
        if not isinstance(flow.get("dati"),dict) or state not in (
            "OSSERVATO","STORICO_NON_AGGIORNATO","SCADUTO"):
            continue
        data=flow["dati"]
        fact={
            "classe":"FLUSSO_O_STOCK_AGGREGATO",
            "evidence_id":evidence_ref("MACRO",key,flow.get("fonte") or "",
                                       data.get("periodo") or flow.get("acquisito_utc") or ""),
            "tipo":key,"fatto_osservato":"Dato pubblicato da aggregatore pubblico, non primaria istituzionale",
            "fonte":flow.get("fonte"),"pubblicato_utc":None,
            "periodo":data.get("periodo"),"acquisito_utc":flow.get("acquisito_utc"),
            "valore":data.get("valore"),"unita":data.get("unita"),
            "stato_prova":state,
            "possibile_conseguenza":"Flussi ETF o stock stablecoin possono concorrere al quadro di liquidita",
            "interpretazione_alternativa":"Flussi netti ETF e supply stablecoin non provano acquisti spot degli asset considerati",
            "riesame":"Confrontare periodi, provenienza e dati di scambio indipendenti",
            "limite":data.get("limite")}
        facts.append(fact)
    # Same official articles can also arrive in the legacy RSS title producer.
    # Keep its existing scenario API intact, but avoid counting those articles
    # twice in the verified evidence ledger.
    previous_titles=published_feed.get("fonti_ufficiali") or []
    duplicate_links=len({row.get("url") for row in previous_titles
                         if isinstance(row,dict) and row.get("url") in urls})
    geo=[v for v in facts if v.get("tipo")=="UE_COMUNICATO_SANZIONI"]
    monetary=[v for v in facts if v.get("tipo")=="FED_COMUNICATO_MONETARIO"]
    monetary+= [v for v in facts if v.get("tipo") in (
        "ECB_DEPOSIT_RATE","ECB_MAIN_REFI_RATE","EA_HICP","EA_M3_GROWTH")]
    def scenario(family,obs,question,alternative,recheck):
        current=next((x for x in obs if x.get("stato_prova") in
            ("OSSERVATO","PUBBLICAZIONE_RECENTE")),None)
        latest=current or (obs[0] if obs else None)
        return {"famiglia":family,
                "stato":"FATTO_CORRENTE_DA_INTERPRETARE" if current else
                        "SOLO_DATI_DATATI" if latest else "NON_VALUTABILE",
                "fonte":latest.get("fonte") if latest else None,
                "periodo_o_pubblicazione":(
                    latest.get("pubblicato_utc") or latest.get("periodo") if latest else None),
                "fatto":latest.get("fatto_osservato") if latest else None,
                "ipotesi":question,"controipotesi":alternative,
                "condizione_di_riesame":recheck,
                "direzione_crypto":"NON_INFERIBILE",
                "nessuna_causalita_attestata":True}
    scenarios=[
        scenario("POLITICA_MONETARIA",monetary,
            "Tassi, inflazione e aspettative possono influire sul costo del denaro e sulla propensione al rischio",
            "L'informazione potrebbe essere gia prezzata o compensata da altri fattori",
            "Verificare decisione/testo, consenso precedente, liquidita e risposta osservata"),
        scenario("GEOPOLITICA_E_SANZIONI",geo,
            "Restrizioni e sanzioni potrebbero influenzare accesso a servizi e controparti",
            "Il provvedimento potrebbe non riguardare asset crypto o non incidere sui volumi",
            "Verificare destinatari, entrata in vigore, giurisdizione e operativita effettiva")]
    return {
        "stato":"CON_EVIDENZE_DATATE" if facts else "NESSUN_DATO_VERIFICABILE_NEL_CAMPIONE",
        "fatti":facts[:20],"fatti_totali_nel_campione":len(facts),
        "fatti_non_mostrati":max(0,len(facts)-20),
        "scenari_condizionali":scenarios,
        "copertura_fonti":source_coverage,
        "duplicati_rss_gia_contati":duplicate_links,
        "numero_feed_primari_freschi":sum(x.get("stato_alla_lettura")=="OSSERVATO" for x in rss),
        "numero_indicatori_attuali":sum(x.get("stato")=="OSSERVATO" for x in indicators),
        "numero_flussi_attuali":sum(x.get("stato_alla_lettura")=="OSSERVATO" for x in financial),
        "limite":"Una pubblicazione ufficiale non dimostra applicazione, impatto sul prezzo "
                 "o nesso causale. Questo e un contesto generale, non una valutazione del singolo asset",
        "nessuna_raccomandazione_operativa":True}



def integrated_asset_view(row, macro_context, regime_view, now):
    """CP5: four economic families in ONE falsifiable GPT reading per asset.

    Input is exclusively revalidated at-read KDD-18/20/21/22 evidence.
    Macro and regime are global context, NEVER causal evidence for the token.
    No additional fetch, portfolio inference, scoring, forecast or order.
    """
    identity=row.get("identita") or {}
    tokenomics=row.get("quadro_tokenomics") or {}
    events=row.get("quadro_eventi") or {}
    supply=tokenomics.get("supply") or {}
    project=(identity.get("coingecko_id") if
             identity.get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO" else None)

    supply_state=supply.get("stato","NON_DISPONIBILE")
    supply_status=("CONTRADDITTORIA" if supply_state=="ANOMALIA_SUPPLY" else
                   "RECENTE" if supply_state=="VERIFICATO" and project else
                   "SCADUTA" if supply_state=="SCADUTO" else "NON_DISPONIBILE")
    documents=(events.get("eventi") or []) if project else []
    if not isinstance(documents,list):
        documents=[]
    current_proofs={
        "VERIFICATO","COMUNICAZIONE_UFFICIALE","DOCUMENTO_REPOSITORY",
        "PROPOSTA_DOCUMENTALE","CONFRONTO_DOCUMENTALE",
        "SEGNALAZIONE_NON_CONFERMA","PROGRAMMA_PRIMARIO",
        "MASSIMO_PRIMARIO_PROGRAMMATO","OSSERVAZIONE_API","CONFRONTO_RPC"}
    fresh_events=[]
    historical_events=[]
    scheduled_events=[]
    for event in documents:
        if not isinstance(event,dict):
            continue
        published=stamp(event.get("pubblicato_utc"))
        planned=stamp(event.get("efficacia_programmata_utc"))
        acquired=stamp(event.get("acquisito_utc"))
        if planned and planned>now and event.get("efficacia_confermata_utc") is None:
            scheduled_events.append(event)
        # Verification of a repository API request is NOT publication of a
        # new release. Distinguish source refresh from actual dated event.
        recent=bool(published and acquired and
                    dt.timedelta(0)<=now-published<=dt.timedelta(days=14) and
                    dt.timedelta(0)<=now-acquired<=dt.timedelta(days=7) and
                    event.get("stato_prova") in current_proofs)
        (fresh_events if recent else historical_events).append(event)
    event_status=("RECENTE" if fresh_events else
                  "PROGRAMMATA" if scheduled_events else
                  "SCADUTA" if historical_events and all(
                      x.get("stato_prova")=="SCADUTO" for x in historical_events) else
                  "STORICA" if historical_events else "NON_DISPONIBILE")
    # The event ledger is already on the same row. Keep a bounded primary
    # reference list instead of duplicating the unabridged documents.
    refs=[{"tipo":x.get("tipo"),"fonte":x.get("fonte"),
           "pubblicato_utc":x.get("pubblicato_utc"),
           "efficacia_programmata_utc":x.get("efficacia_programmata_utc"),
           "acquisito_utc":x.get("acquisito_utc"),
           "stato_prova":x.get("stato_prova")}
          for x in (fresh_events+scheduled_events+historical_events)[:4]]

    macro=macro_context if isinstance(macro_context,dict) else {}
    facts=macro.get("fatti") or []
    macro_current=[x for x in facts if isinstance(x,dict) and
                   x.get("stato_prova") in ("OSSERVATO","PUBBLICAZIONE_RECENTE")]
    macro_historical=[x for x in facts if isinstance(x,dict) and
                      x.get("stato_prova") in
                      ("SCADUTO","STORICO_NON_AGGIORNATO",
                       "PUBBLICAZIONE_DATATA_O_NON_RICONFERMATA")]
    macro_status=("RECENTE" if macro_current else
                  "SCADUTA" if macro_historical and all(
                      x.get("stato_prova")=="SCADUTO" for x in macro_historical) else
                  "STORICA" if macro_historical else "NON_DISPONIBILE")
    macro_first=(macro_current or macro_historical or [None])[0]

    regime=regime_view if isinstance(regime_view,dict) else {}
    regime_state=regime.get("stato","INDETERMINATO")
    regime_quality=regime.get("qualita")
    regime_timestamp=stamp(regime.get("rilevazione_utc"))
    regime_status=("SCADUTA" if regime_quality=="SCADUTO" or
                   (regime_timestamp and now-regime_timestamp>dt.timedelta(hours=2)) else
                   "NON_DISPONIBILE" if regime_state=="INDETERMINATO" else
                   "CONTRADDITTORIA" if regime_state=="TRANSIZIONE" or
                   regime_quality=="PARZIALE_CON_CONTRADDIZIONI" else "RECENTE")
    components={
        "fondamentali":{
            "stato_informazione":supply_status,"stato_fonte":supply_state,
            "fonte":supply.get("fonte") if project else None,
            "rilevato_utc":supply.get("rilevato_utc") if project else None,
            "acquisito_utc":supply.get("acquisito_utc") if project else None,
            "evidence_id":supply.get("evidence_id"),
            "riferimento_evidenza_dichiarato":supply.get("riferimento_evidenza_dichiarato"),
            "provenienza_acquisizione":supply.get("provenienza_acquisizione"),
            "integrita_originale_alla_lettura":supply.get("integrita_originale_alla_lettura"),
            "attendibilita":(
                "DATI_VALIDATI_HTTP_DICHIARATO_NON_RIVALIDABILE"
                if supply_status=="RECENTE" and
                supply.get("provenienza_acquisizione")==
                "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE"
                else "DATO_STRUTTURALMENTE_VALIDO_HTTP_NON_ATTESTATO"
                if supply_status=="RECENTE" else "NON_ATTUALE_O_NON_VERIFICATA"),
            "riferimento_dettaglio":"quadro_tokenomics"},
        "eventi":{
            "stato_informazione":event_status,
            "stato_copertura":events.get("stato","NON_ACQUISITO"),
            "documenti_recenti":len(fresh_events),
            "documenti_storici":len(historical_events),
            "eventi_programmati_non_eseguiti":len(scheduled_events),
            "documenti_non_mostrati":events.get("eventi_non_mostrati",0),
            "riferimenti":refs,"riferimento_dettaglio":"quadro_eventi",
            "attendibilita":"PROVE_DOCUMENTALI_DA_DISTINGUERE_DA_ESECUZIONE"},
        "macroeconomia":{
            "stato_informazione":macro_status,
            "ambito":"MERCATO_GENERALE_NON_SPECIFICO_ASSET",
            "fatti_recenti":len(macro_current),"fatti_storici":len(macro_historical),
            "fatti_non_mostrati":macro.get("fatti_non_mostrati",0),
            "fonte_esempio":macro_first.get("fonte") if macro_first else None,
            "data_esempio":(macro_first.get("pubblicato_utc") or
                           macro_first.get("periodo")) if macro_first else None,
            "acquisito_utc":macro_first.get("acquisito_utc") if macro_first else None,
            "stato_prova_esempio":macro_first.get("stato_prova") if macro_first else None,
            "riferimento_dettaglio":"contesto_macro_primario",
            "attendibilita":"FONTI_PRIMARIE_E_AGGREGATORI_DISTINTI_NON_CAUSALITA"},
        "regime":{
            "stato_informazione":regime_status,
            "ambito":"MERCATO_GENERALE_NON_SPECIFICO_ASSET",
            "stato":regime_state,"qualita":regime_quality,
            "acquisito_utc":regime.get("rilevazione_utc"),
            "fonti":regime.get("evidenze_indipendenti",[])[:2],
            "riferimento_dettaglio":"regime_motivato",
            "attendibilita":"CLASSIFICAZIONE_DERIVATA_NON_PREVISIONE"}
    }
    if not project:
        # Global macro/regime may still be available but cannot become
        # project-specific proof when a ticker/project binding fails.
        components["fondamentali"]["stato_informazione"]="NON_DISPONIBILE"
        components["eventi"]["stato_informazione"]="NON_DISPONIBILE"
    missing=[name for name,value in components.items()
             if value["stato_informazione"] in ("NON_DISPONIBILE","SCADUTA")]
    contradictions=[name for name,value in components.items()
                    if value["stato_informazione"]=="CONTRADDITTORIA"]
    alternatives=[
        {"ambito":"FONDAMENTALI",
         "ipotesi":tokenomics.get("rischio_opportunita_ipotesi"),
         "controipotesi":tokenomics.get("controipotesi"),
         "riesame":tokenomics.get("condizione_di_riesame")},
        {"ambito":"EVENTI",
         "ipotesi":"Il documento potrebbe avere conseguenze solo se pertinente e attuato",
         "controipotesi":"La pubblicazione non dimostra adozione, unlock eseguito o effetto sul prezzo",
         "riesame":"Riconfermare fonte, data ed efficacia di ogni evento"},
    ]
    alternatives.extend({
        "ambito":"MACROECONOMIA",
        "ipotesi":s.get("ipotesi"),
        "controipotesi":s.get("controipotesi"),
        "riesame":s.get("condizione_di_riesame")}
        for s in macro.get("scenari_condizionali",[])[:2]
        if isinstance(s,dict))
    alternatives.append({
        "ambito":"REGIME",
        "ipotesi":"Il contesto generale potrebbe condizionare la lettura di rischio",
        "controipotesi":"Il regime generale non misura domanda, valore o ritorno di questo asset",
        "riesame":regime.get("invalidazione")})
    return {
        "token":row.get("token"),"coppia":identity.get("coppia"),
        "progetto_id":project,
        "stato":"QUADRO_PARZIALE_DA_INTERPRETARE" if project else
                "IDENTITA_NON_ATTRIBUIBILE",
        "componenti":components,
        "categorie_temporali_presenti":sorted({
            x["stato_informazione"] for x in components.values()}),
        "informazioni_mancanti_o_scadute":missing,
        "contraddizioni_da_esaminare":contradictions,
        "ipotesi_e_alternative":alternatives,
        "novita_evento_non_inferibile_dalla_sola_acquisizione":True,
        "causalita_sul_prezzo":"NON_ATTESTATA",
        "previsione_prezzo":"NON_INFERIBILE",
        "raccomandazione":"NON_GENERATA",
        "ordine":"NON_GENERATO",
        "limite":"Quattro famiglie considerate insieme senza punteggio o voto. "
                 "Regime e macro sono contesto generale, non prova sull'asset; "
                 "documenti futuri e osservazioni storiche non equivalgono a fatti eseguiti."}

def _historical_provenance_view(current, old_proof, family):
    """Exact PR#73 3cb12e3 provenance-only compatibility, never an override.

    A previous packet can retain the OLD truthful-but-overconfident labels.
    Reconstruct just that historical deterministic display from CURRENT
    revalidated source facts. Accept only an exact match; always EMIT the
    current conservative provenance status. Arbitrary view edits still fail.
    """
    if not isinstance(current,dict) or not isinstance(old_proof,dict):
        return None
    snapshot=copy.deepcopy(current)
    if family=="macro":
        for fact in snapshot.get("fatti",[]):
            if isinstance(fact,dict) and fact.get("classe")=="COMUNICATO_UFFICIALE":
                fact.pop("integrita_feed_alla_lettura",None)
        return snapshot
    claim=old_proof.get("stato","NON_ATTESTATA_DAL_PRODUTTORE")
    if family=="tokenomics":
        supply=snapshot.get("supply")
        if not isinstance(supply,dict):return None
        for key in ("acquisizione_http_dichiarata","integrita_originale_alla_lettura",
                    "autenticita_fonte_esterna","riferimento_evidenza_dichiarato",
                    "url_http_dichiarato"):
            supply.pop(key,None)
        supply["provenienza_acquisizione"]=claim
        supply["evidence_id"]=old_proof.get("id_evidenza")
        supply["fonte_http_effettiva"]=old_proof.get("url_richiesto")
        supply["limite_provenienza"]=(
            "L'hash catturato dal produttore non e firma del fornitore "
            "e non prova autenticita esterna; senza prova HTTP i valori "
            "sono soltanto strutturalmente validi.")
        return snapshot
    if family=="integrated":
        components=snapshot.get("componenti")
        supply=components.get("fondamentali") if isinstance(components,dict) else None
        if not isinstance(supply,dict):return None
        for key in ("riferimento_evidenza_dichiarato",
                    "integrita_originale_alla_lettura"):
            supply.pop(key,None)
        supply["provenienza_acquisizione"]=claim
        supply["evidence_id"]=old_proof.get("id_evidenza")
        state=supply.get("stato_informazione")
        supply["attendibilita"]=(
            "HTTP_PRODUTTORE_CON_HASH_NON_FIRMA_FORNITORE"
            if state=="RECENTE" and claim=="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE"
            else "DATO_STRUTTURALMENTE_VALIDO_HTTP_NON_ATTESTATO"
            if state=="RECENTE" else "NON_ATTUALE_O_NON_VERIFICATA")
        return snapshot
    return None


def at_read(source, positions, shortlist, now, *, requested=None):
    """Validate attribution and recalculate economic age, without source fetches."""
    if not isinstance(source, dict) or source.get("schema") != VERSION:
        raise ValueError("Schema evidenza economica")
    acquired = stamp(source.get("acquisito_utc"))
    if not acquired or acquired > now + dt.timedelta(minutes=2):
        raise ValueError("Tempo evidenza economica")
    original_positions = source.get("posizioni")
    original_candidates = source.get("candidati")
    original_requested = source.get("richiesti",[])
    expected_requested = requested if requested is not None else []
    if (not isinstance(original_positions,list) or not isinstance(original_candidates,list)
            or not isinstance(original_requested,list) or not isinstance(expected_requested,list)
            or len(original_requested)>3 or len(expected_requested)>3):
        raise ValueError("Copertura economica")
    if (len(original_positions)!=len(positions)
            or len(original_candidates)!=len(shortlist)
            or len(original_requested)!=len(expected_requested)):
        raise ValueError("Cardinalita economica")
    matrix = source.get("fonti_economiche")
    if matrix is not None and matrix != sources_matrix():
        raise ValueError("Matrice fonti economiche alterata")
    result = {"schema": VERSION, "acquisito_utc": source["acquisito_utc"],
              "letto_utc": now.isoformat(timespec="seconds"),
              "fonti_economiche": matrix if matrix is not None else [],
              "posizioni": [], "candidati": [], "richiesti": []}
    for name, source_rows, expected in (
            ("posizioni", original_positions, positions),
            ("candidati", original_candidates, shortlist),
            ("richiesti", original_requested, expected_requested)):
        for i, (row, target) in enumerate(zip(source_rows, expected)):
            if not isinstance(row, dict) or row.get("indice") != i or row.get("token") != target.get("token"):
                raise ValueError("Identita economica discordante")
            if name in ("candidati","richiesti") and row.get("coppia_analisi") != target.get("coppia_analisi"):
                raise ValueError("Coppia candidato o richiesto discordante")
            if name == "richiesti":
                when=stamp(row.get("richiesto_utc"))
                if (not when or when>acquired+dt.timedelta(minutes=2)
                        or row.get("richiesto_utc")!=target.get("richiesto_utc")
                        or row.get("origine") not in ("CLI_ESPLICITO_LOCALE","UI_ESPLICITA_LOCALE")
                        or row.get("origine")!=target.get("origine")):
                    raise ValueError("Origine o data asset richiesto non verificabile")
            identity = row.get("identita")
            if not isinstance(identity, dict) or identity.get("token") != row["token"]:
                raise ValueError("Identita economica non valida")
            if identity.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO":
                project_token = canonical_token(row["token"])
                pair = identity.get("coppia")
                pair_ok = (isinstance(pair, str) and pair.count("/") == 1
                           and canonical_token(pair.split("/")[0]) == project_token
                           and pair.split("/")[1] in ("EUR", "USD", "USDC"))
                is_curated = identity.get("metodo") in (None, "REGISTRO_CURATO")
                correct_project = (
                    identity.get("coingecko_id") == PROJECTS[project_token][0] and
                    identity.get("progetto") == PROJECTS[project_token][1]
                    if is_curated and project_token in PROJECTS else
                    _dynamic_valid(row["token"], pair, identity)
                    if not is_curated and project_token not in PROJECTS else False)
                if (not pair_ok or not correct_project
                        or identity.get("token_progetto", project_token) != project_token
                        or not isinstance(identity.get("pair_key"), str)
                        or not identity["pair_key"]
                        or identity.get("asset_base_kraken", pair.split("/")[0] if pair_ok else None)
                           != (pair.split("/")[0] if pair_ok else None)
                        or (name in ("candidati","richiesti")
                            and pair != target.get("coppia_analisi"))):
                    raise ValueError("Identita CoinGecko non attribuibile")
            row_copy = dict(row)
            if name=="richiesti":
                requested_at=stamp(row["richiesto_utc"])
                row_copy["stato_richiesta"]=(
                    "RICHIESTA_ATTIVA" if dt.timedelta(0)<=now-requested_at<=dt.timedelta(days=7)
                    else "RICHIESTA_SCADUTA_DA_RINNOVARE")
            if identity.get("metodo") == "KRAKEN_COINGECKO_MARKET":
                verified = stamp(identity["prova_mercato"].get("verificato_utc"))
                if not verified or now-verified > dt.timedelta(days=7):
                    row_copy["identita"] = dict(identity, stato="NON_VERIFICATO",
                                               motivo="ATTESTAZIONE_IDENTITA_SCADUTA")
            for field in ("fondamentali", "evento"):
                evidence = row.get(field)
                if not isinstance(evidence, dict):
                    raise ValueError("Fonte economica mancante")
                if evidence.get("stato") in ("VERIFICATO", "SCADUTO", "ANOMALIA_SUPPLY",
                                               "STORICO_NON_AGGIORNATO"):
                    t = stamp(evidence.get("rilevato_utc") if field == "fondamentali"
                              else evidence.get("pubblicato_utc"))
                    if t is None or t > now + dt.timedelta(minutes=2):
                        raise ValueError("Fonte economica senza orario valido")
                    if field == "fondamentali" and not fundamental_source_valid(
                            evidence.get("fonte"),identity.get("coingecko_id")):
                        raise ValueError("Fonte fondamentali incoerente")
                    if field == "evento":
                        repo=identity.get("repository_primario")
                        url=evidence.get("fonte")
                        tag=evidence.get("tag")
                        source_seen=stamp(evidence.get("acquisito_utc"))
                        if (not repo or not isinstance(tag,str) or not tag
                                or url!="https://github.com/"+repo+"/releases/tag/"+tag
                                or evidence.get("emittente")!=repo
                                or evidence.get("evento_utc")!=evidence.get("pubblicato_utc")
                                or evidence.get("adozione_rete")!="NON_VERIFICATA"
                                or evidence.get("impatto_economico")!="NON_DIMOSTRATO"
                                or not isinstance(evidence.get("sintesi"),str)
                                or not evidence["sintesi"].strip()
                                or type(evidence.get("pre_release")) is not bool
                                or not source_seen
                                or not dt.timedelta(0)<=acquired-source_seen
                                   <=dt.timedelta(days=7)
                                or source_seen<t-dt.timedelta(minutes=2)):
                            raise ValueError("Release attribution, timing or execution forged")
                        age_source=now-source_seen
                        age_publication=now-t
                        if (evidence["stato"]=="SCADUTO"
                                or age_publication>dt.timedelta(days=90)
                                or age_source>dt.timedelta(days=7)):
                            next_state="SCADUTO"
                        elif (evidence["stato"]=="STORICO_NON_AGGIORNATO"
                              or age_source>dt.timedelta(days=1)):
                            next_state="STORICO_NON_AGGIORNATO"
                        else:
                            next_state="VERIFICATO"
                        row_copy[field]=dict(evidence,stato=next_state)
                    else:
                        row_copy[field]=dict(evidence,stato=(
                            evidence["stato"] if evidence["stato"] in ("VERIFICATO","ANOMALIA_SUPPLY")
                            and now-t<=dt.timedelta(days=1) else "SCADUTO"))
            verify_supply_at_read(row_copy["fondamentali"])
            # Once source bytes have been discarded, a self-consistent
            # SHA/E-FUND is NOT re-verification of the actual HTTP response.
            # Preserve the production assertion without laundering it into
            # an independently authenticated acquisition at the GPT read.
            proof=row_copy["fondamentali"].get("prova_acquisizione")
            if isinstance(proof,dict):
                original=proof.get("stato")
                row_copy["fondamentali"]["prova_acquisizione"]=dict(
                    proof, qualifica_alla_lettura=(
                        "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE"
                        if original=="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE"
                        else "ACQUISIZIONE_NON_ATTESTATA"),
                    integrita_originale_alla_lettura="NON_RICALCOLABILE_SENZA_CORPO_HTTP")
            if row_copy["identita"].get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO":
                # An expired project binding cannot leave verified numerical
                # fundamentals attached to the historical wallet position.
                row_copy["fondamentali"] = dict(
                    fundamentals({}, None, now, now), stato="NON_VERIFICATO_IDENTITA",
                    motivo="ATTESTAZIONE_IDENTITA_SCADUTA")
                row_copy["evento"] = release_event({}, None, now, now)
            row_copy["politica_monetaria_primaria"] = monetary_reference(row_copy["identita"])
            row_copy["lettura_economica"] = decision_context(
                row_copy["identita"], row_copy["fondamentali"], row_copy["evento"])
            result[name].append(row_copy)
    result["copertura_fondamentali"] = {
        "posizioni_totali": len(result["posizioni"]),
        "posizioni_verificate_alla_lettura": sum(
            r["fondamentali"].get("stato") == "VERIFICATO" for r in result["posizioni"]),
        "richiesti_espliciti_totali":len(result["richiesti"]),
        "richiesti_identificati":sum(r["identita"].get("stato")=="IDENTITA_VERIFICATA_DA_CATALOGO"
                                    for r in result["richiesti"]),
        "candidati_totali": len(result["candidati"]),
        "candidati_verificati_alla_lettura": sum(
            r["fondamentali"].get("stato") == "VERIFICATO" for r in result["candidati"]),
        "limite": "La rotazione e la cache locale hanno orari propri; nessuna assenza equivale a zero."}
    regime_data = source.get("regime")
    if not isinstance(regime_data, dict):
        raise ValueError("Regime economico mancante")
    result["regime"] = dict(regime_data)
    # The bridge must not launder a forged regime history into verified
    # evidence, including when called on an already-normalized packet.
    if "storico_regimi" in regime_data:
        history=regime_data["storico_regimi"]
        if not isinstance(history,list) or len(history)>8:
            raise ValueError("Historical regime structure invalid")
        last=None
        for point in history:
            if not isinstance(point,dict):
                raise ValueError("Historical regime row invalid")
            when=stamp(point.get("acquisito_utc"))
            if (not when or when>acquired+dt.timedelta(minutes=2)
                    or (last is not None and when<=last)
                    or point.get("stato") not in ("RIALZISTA","RIBASSISTA","LATERALE",
                                                "TRANSIZIONE","INDETERMINATO")):
                raise ValueError("Historical regime timestamp or classification forged")
            last=when
        previous=regime_data.get("confronto_precedente")
        if previous is not None and (
                not history or not isinstance(previous,dict)
                or previous.get("stato_precedente")!=history[-1]["stato"]
                or previous.get("acquisito_precedente_utc")!=history[-1]["acquisito_utc"]):
            raise ValueError("Historical regime comparison forged")
    if now-acquired > dt.timedelta(hours=2):
        result["regime"].update(stato="INDETERMINATO", qualita="SCADUTO",
                                limite="Regime storico; ricalcolo necessario")
    macro_data = source.get("macro")
    if not isinstance(macro_data, dict):
        raise ValueError("Macro mancante")
    if not isinstance(macro_data.get("fonti_ufficiali"), list):
        raise ValueError("Fonte macro non strutturata")
    # Reconstruct read-time scenarios from the retained official headlines.
    # A digest matching the packet does not freeze or authenticate a causal claim.
    normalized = []
    for item in macro_data["fonti_ufficiali"]:
        if not isinstance(item, dict):
            raise ValueError("Fonte macro non valida")
        normalized.append({"fonte": item.get("fonte"), "link": item.get("url"),
                           "titolo": item.get("titolo"),
                           "data": item.get("pubblicato_utc")})
    result["macro"] = macro(normalized, now)
    if "monitor_fonti" in source:
        import kdd_economic_sources as primary
        # Verify all original source attributions, then derive independent
        # decision-review questions for EVERY holding and shortlist entry.
        # Do not carry the old read-time view into the next GPT read.
        verified = primary.at_read(source["monitor_fonti"], source, now)
        result["monitor_fonti"] = verified
        previous_read = stamp(source.get("letto_utc"))
        same_read = bool(previous_read and
                         abs((now-previous_read).total_seconds()) <= 1)
        for group in ("posizioni","candidati","richiesti"):
            for original, item in zip(source.get(group,[]),result[group]):
                derived = primary.decision_review(verified,item,group)
                old = original.get("valutazione_fonti_primarie")
                if same_read and old is not None and old != derived:
                    raise ValueError("Lettura primaria per asset alterata")
                item["valutazione_fonti_primarie"] = derived
    macro_context=macro_primary_context(result.get("monitor_fonti"),
                                        result["macro"],now)
    earlier_context=source.get("contesto_macro_primario")
    earlier_read=stamp(source.get("letto_utc"))
    if (earlier_context is not None and earlier_read
            and abs((now-earlier_read).total_seconds())<=1
            and earlier_context!=macro_context
            and earlier_context!=_historical_provenance_view(
                macro_context,{}, "macro")):
        raise ValueError("Macro context at GPT read distorted")
    result["contesto_macro_primario"]=macro_context
    # The existing technical regime is provisional. A single validated final
    # classification is recomputed at packet AND bridge read, not trusted
    # merely because a packet checksum happened to match.
    review=regime_integrato(result["regime"],macro_context,now)
    old_review=source.get("regime_motivato")
    if old_review is not None and earlier_read and abs((now-earlier_read).total_seconds())<=1:
        if old_review!=review:
            raise ValueError("Regime motivated summary tampered at GPT read")
    result["regime_motivato"]=review
    # Keep a per-asset tokenomics row even in a legacy economic dossier
    # without the primary monitor. Missing upstream is never a missing token.
    primary_read=result.get("monitor_fonti") or {}
    previous_read=stamp(source.get("letto_utc"))
    same_read=bool(previous_read and abs((now-previous_read).total_seconds())<=1)
    for group in ("posizioni","candidati","richiesti"):
        for original,item in zip(source.get(group,[]),result[group]):
            tokenomics=tokenomics_view(item,primary_read)
            prior_tokenomics=original.get("quadro_tokenomics")
            if (same_read and prior_tokenomics is not None
                    and prior_tokenomics!=tokenomics
                    and prior_tokenomics!=_historical_provenance_view(
                        tokenomics,original.get("fondamentali",{}).get("prova_acquisizione") or {},
                        "tokenomics")):
                raise ValueError("Tokenomics at read distorted")
            item["quadro_tokenomics"]=tokenomics
    for group in ("posizioni","candidati","richiesti"):
        for original,item in zip(source.get(group,[]),result[group]):
            event_view=project_events_view(item,primary_read)
            previous_view=original.get("quadro_eventi")
            if same_read and previous_view is not None and previous_view!=event_view:
                raise ValueError("Project events at read distorted")
            item["quadro_eventi"]=event_view
    result["copertura_eventi"]={}
    for group in ("posizioni","candidati","richiesti"):
        items_group=result[group]
        result["copertura_eventi"][group]={
            "totali":len(items_group),
            "progetti_identificati":sum(x["quadro_eventi"]["progetto_id"] is not None
                                       for x in items_group),
            "con_documenti_o_avvisi":sum(bool(x["quadro_eventi"]["eventi"])
                                        for x in items_group),
            "release_confermate_alla_lettura":sum(x["evento"].get("stato")=="VERIFICATO"
                                                  for x in items_group),
            "release_storiche":sum(x["evento"].get("stato") in
                                   ("STORICO_NON_AGGIORNATO","SCADUTO") for x in items_group),
            "limite":"Copertura del roster osservato, non degli eventi assenti dal campione"}
    result["copertura_tokenomics"]={}
    for group in ("posizioni","candidati","richiesti"):
        rows=result[group]
        result["copertura_tokenomics"][group]={
            "totali":len(rows),
            "identita_verificate":sum(r["identita"].get("stato")==
                "IDENTITA_VERIFICATA_DA_CATALOGO" for r in rows),
            "supply_attuale":sum(r["quadro_tokenomics"]["supply"]["stato"]==
                "VERIFICATO" for r in rows),
            "supply_contraddittoria":sum(r["quadro_tokenomics"]["supply"]["stato"]==
                "ANOMALIA_SUPPLY" for r in rows),
            "supply_senza_massimo":sum(
                r["quadro_tokenomics"]["supply"]["stato"]=="VERIFICATO"
                and r["quadro_tokenomics"]["supply"]["offerta_massima"] is None
                for r in rows),
            "documenti_primari_attuali":sum(
                r["quadro_tokenomics"]["stato"] in
                ("SUPPLY_E_DOCUMENTO_PRIMARIO","FONTE_PRIMARIA_SENZA_SUPPLY_ATTUALE")
                and r["quadro_tokenomics"]["calendario"]["categoria"] in
                ("UNLOCK_PROGRAMMATO_QUANTITA","MASSIMI_SBLOCCABILI_DATATI",
                 "REGOLA_VESTING_SENZA_TRANCHE_ESATTE","PROIEZIONE_CIRCOLAZIONE_NON_UNLOCK")
                for r in rows),
            "fonti_emissione_attuali":sum(
                r["quadro_tokenomics"]["politica_emissione"]["stato"]=="OSSERVATO"
                for r in rows),
            "fonte_supply":"CoinGecko pubblica per asset, non calendario primario",
            "limite":"Copertura del roster del packet, non prova del wallet o dell'esecuzione degli unlock"}
    # CP5: single per-asset integration for the actual GPT consumer; no
    # network fetches, source producer, advice or asset omission.
    result["copertura_integrazione"]={}
    for group in ("posizioni","candidati","richiesti"):
        for original,item in zip(source.get(group,[]),result[group]):
            view=integrated_asset_view(item,macro_context,review,now)
            old=original.get("giudizio_economico_integrato")
            if (same_read and old is not None and old!=view
                    and old!=_historical_provenance_view(
                        view,original.get("fondamentali",{}).get("prova_acquisizione") or {},
                        "integrated")):
                raise ValueError("Integrated economic GPT view altered")
            item["giudizio_economico_integrato"]=view
        rows=result[group]
        result["copertura_integrazione"][group]={
            "totali":len(rows),
            "con_identita_attribuibile":sum(
                v["giudizio_economico_integrato"]["progetto_id"] is not None
                for v in rows),
            "quattro_famiglie_esposte":sum(
                len(v["giudizio_economico_integrato"]["componenti"])==4
                for v in rows),
            "con_evidenza_fondamentale_recente":sum(
                v["giudizio_economico_integrato"]["componenti"]
                ["fondamentali"]["stato_informazione"]=="RECENTE" for v in rows),
            "con_eventi_recenti":sum(
                v["giudizio_economico_integrato"]["componenti"]
                ["eventi"]["documenti_recenti"]>0 for v in rows),
            "con_copertura_parziale":sum(
                bool(v["giudizio_economico_integrato"]
                     ["informazioni_mancanti_o_scadute"] or
                     v["giudizio_economico_integrato"]
                     ["contraddizioni_da_esaminare"]) for v in rows),
            "limite":"Cardinalita e informazioni disponibili; non qualita di previsione"}
    return result
