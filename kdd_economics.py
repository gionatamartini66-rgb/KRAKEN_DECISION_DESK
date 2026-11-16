"""KDD-18/20/21/22: bounded, attributable economic evidence; never trading signals."""
import datetime as dt
import email.utils
import math
import json
import re
from pathlib import Path
from urllib.parse import urlparse

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

def fundamentals(identity, payload, now, acquired):
    out = {"stato": "NON_VERIFICATO", "fonte": None, "rilevato_utc": None,
           "acquisito_utc": acquired.isoformat(timespec="seconds"),
           "capitalizzazione_usd": None, "fdv_usd": None,
           "offerta_circolante": None, "offerta_totale": None,
           "offerta_massima": None, "rapporto_fdv_cap": None,
           "quota_circolante_su_totale_pct": None,
           "emissione_residua_massima_su_circolante_pct": None,
           "fonte_supply": "COINGECKO_AGGREGATORE_NON_SCHEDULE_PRIMARIO",
           "diluizione": "NON_CALCOLABILE", "unlock": "NON_VERIFICATO",
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
    out["fonte"] = CG + cg
    age = (now-updated).total_seconds()
    out["stato"] = "VERIFICATO" if age <= 86400 else "SCADUTO"
    if values["capitalizzazione_usd"] and values["fdv_usd"]:
        out["rapporto_fdv_cap"] = round(values["fdv_usd"]/values["capitalizzazione_usd"], 4)
    circulating, total, maximum = (values["offerta_circolante"],
                                   values["offerta_totale"],
                                   values["offerta_massima"])
    if (circulating is not None and total is not None
            and total > 0 and 0 <= circulating <= total):
        out["quota_circolante_su_totale_pct"] = round(100 * circulating / total, 4)
    if (circulating is not None and circulating > 0
            and maximum is not None and maximum >= circulating):
        out["emissione_residua_massima_su_circolante_pct"] = round(
            100 * (maximum - circulating) / circulating, 4)
    if (circulating is not None and maximum is not None
            and maximum > 0 and maximum < circulating):
        out["diluizione"] = "SUPPLY_MAX_INFERIORE_AL_CIRCOLANTE_ANOMALIA"
        out["limite"] = "Supply numericamente contraddittoria: non inferire emissione o unlock"
    elif values["offerta_massima"] is None:
        out["diluizione"] = "MAX_NON_DICHIARATO_NON_EQUIVALE_A_ILLIMITATO"
    elif values["offerta_massima"] == 0:
        out["diluizione"] = "MAX_ZERO_DATO_ANOMALO"
    elif values["offerta_circolante"] is not None:
        out["diluizione"] = ("RAPPORTO_CALCOLABILE" if values["offerta_circolante"] > 0
                            else "CIRCOLANTE_ZERO")
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
    if trend["4H"] != trend["1D"]:
        out.update(stato="TRANSIZIONE", qualita="PARZIALE",
                   contrari=["BTC 4H e 1D discordanti"])
        return out
    if not isinstance(global_row, dict):
        out["mancanti"].append("CoinGecko globale datato")
        return out
    updated = stamp(global_row.get("aggiornato_sorgente_utc"))
    change = global_row.get("var_capitalizzazione_24h_pct")
    if (not updated or updated > now + dt.timedelta(minutes=2)
            or now-updated > dt.timedelta(hours=2)
            or not isinstance(change, (int, float)) or isinstance(change, bool)
            or not math.isfinite(change)):
        out["mancanti"].append("Variazione capitalizzazione globale fresca")
        return out
    out["famiglie_osservate"].append({
        "famiglia": "CAPITALIZZAZIONE_CRYPTO_AGGREGATA",
        "fonte": global_row.get("fonte"),
        "pubblicato_utc": updated.isoformat(timespec="seconds"),
        "variazione_24h_pct": change,
        "limite": "Aggregatore, non capitali istituzionali né flussi ETF."})
    cap, volume = (numeric(global_row.get("capitalizzazione_totale_usd")),
                   numeric(global_row.get("volume_24h_usd")))
    if cap is not None and cap > 0 and volume is not None and 0 < volume <= cap*10:
        out["famiglie_osservate"].append({
            "famiglia": "ATTIVITA_AGGREGATA",
            "turnover_24h_su_cap_pct": round(volume / cap * 100, 4),
            "pubblicato_utc": updated.isoformat(timespec="seconds"),
            "limite": "Rapporto tra volume riportato e capitalizzazione; non prova partecipazione netta o acquisti."})
    else:
        out["mancanti"].append("Volume aggregato 24h e rapporto volume/capitalizzazione attendibile")
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
                if kind=="ETF_BTC_FARSIDE" and out.get("stato") in ("RIALZISTA","RIBASSISTA"):
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
                if evidence.get("stato") in ("VERIFICATO", "SCADUTO"):
                    t = stamp(evidence.get("rilevato_utc") if field == "fondamentali"
                              else evidence.get("pubblicato_utc"))
                    if t is None or t > now + dt.timedelta(minutes=2):
                        raise ValueError("Fonte economica senza orario valido")
                    if field == "fondamentali" and evidence.get("fonte") != CG + identity.get("coingecko_id", ""):
                        raise ValueError("Fonte fondamentali incoerente")
                    if field == "evento":
                        repo = identity.get("repository_primario")
                        url = evidence.get("fonte")
                        if not repo or not isinstance(url, str) or not url.startswith(
                                "https://github.com/" + repo + "/releases/tag/"):
                            raise ValueError("Evento non attribuibile")
                    max_age = dt.timedelta(days=1 if field == "fondamentali" else 90)
                    row_copy[field] = dict(evidence, stato=(
                        "VERIFICATO" if evidence["stato"] == "VERIFICATO" and now-t <= max_age
                        else "SCADUTO"))
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
    return result
