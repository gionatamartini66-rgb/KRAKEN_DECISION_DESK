"""KDD-18/20/21/22: bounded, attributable economic evidence; never trading signals."""
import datetime as dt
import email.utils
import math
from urllib.parse import urlparse

VERSION = "kdd-economic-v001"
UTC = dt.timezone.utc
# Curated project identities, NOT a general ticker resolver. A verified Kraken
# pair identity is also required for every attribution.
PROJECTS = {
    "BTC": ("bitcoin", "Bitcoin", "bitcoin/bitcoin"),
    "SOL": ("solana", "Solana", "anza-xyz/agave"),
    "ADA": ("cardano", "Cardano", "IntersectMBO/cardano-node"),
    "ETH": ("ethereum", "Ethereum", None),
    "NEAR": ("near", "NEAR Protocol", None),
    "SUI": ("sui", "Sui", None),
    "XRP": ("ripple", "XRP", None),
    "ONDO": ("ondo-finance", "Ondo", None),
    "KAS": ("kaspa", "Kaspa", None),
    "ICNT": ("impossible-cloud-network-token", "Impossible Cloud Network", None),
}
CG = "https://api.coingecko.com/api/v3/coins/"
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


def identify(token, pair, pair_key, *, catalog_verified=False):
    base = {"stato": "NON_VERIFICATO", "token": token,
            "coppia": pair, "pair_key": pair_key,
            "limite": "Nessuna attribuzione CoinGecko dal solo ticker"}
    if not catalog_verified or not isinstance(token, str) or token not in PROJECTS:
        return base
    expected_base = "XBT" if token == "BTC" else token
    if not isinstance(pair, str) or pair.split("/")[:1] not in ([token], [expected_base]) or (
            pair.count("/") != 1 or pair.split("/")[1] not in ("EUR", "USD", "USDC")):
        return base
    if not isinstance(pair_key, str) or not pair_key or len(pair_key) > 32:
        return base
    cg, name, repository = PROJECTS[token]
    return dict(base, stato="IDENTITA_VERIFICATA_DA_CATALOGO",
                progetto=name, coingecko_id=cg, repository_primario=repository,
                fonte_identita="Kraken AssetPairs + registro progetto curato",
                limite="Corrispondenza curata: migrazioni e contratti da rivalidare")


def fundamentals(identity, payload, now, acquired):
    out = {"stato": "NON_VERIFICATO", "fonte": None, "rilevato_utc": None,
           "acquisito_utc": acquired.isoformat(timespec="seconds"),
           "capitalizzazione_usd": None, "fdv_usd": None,
           "offerta_circolante": None, "offerta_totale": None,
           "offerta_massima": None, "rapporto_fdv_cap": None,
           "diluizione": "NON_CALCOLABILE", "unlock": "NON_VERIFICATO",
           "limite": "Nessun calendario vesting deducibile dalla supply"}
    if identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO" or not isinstance(payload, dict):
        return out
    cg = identity["coingecko_id"]
    if (payload.get("id") != cg or payload.get("symbol", "").upper() != identity["token"]
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
    if values["offerta_massima"] is None:
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
    if (not isinstance(link, str) or not link.startswith(expected)
            or not published or published > now + dt.timedelta(minutes=2)
            or not isinstance(release.get("name"), str)):
        return out
    out.update(stato="VERIFICATO" if (now-published).days <= 90 else "SCADUTO",
               fonte=link, emittente=repo,
               pubblicato_utc=published.isoformat(timespec="seconds"),
               evento_utc=published.isoformat(timespec="seconds"),
               sintesi=release["name"][:180])
    return out


def macro(feed, now):
    entries = []
    for row in (feed if isinstance(feed, list) else [])[:12]:
        if not isinstance(row, dict):
            continue
        source = row.get("fonte")
        url = row.get("link")
        if source not in KNOWN_MACRO or not isinstance(url, str):
            continue
        parsed = urlparse(url)
        trusted = parsed.scheme == "https" and parsed.hostname == KNOWN_MACRO[source]
        published = stamp(row.get("data"))
        fresh = bool(trusted and published and dt.timedelta(0) <= now-published <= dt.timedelta(days=14))
        entries.append({"fonte": source, "url": url if trusted else None,
                        "titolo": str(row.get("titolo") or "")[:180],
                        "pubblicato_utc": published.isoformat(timespec="seconds") if published else None,
                        "stato": "VERIFICATO" if fresh else "SCADUTO" if trusted and published else "NON_VERIFICATO",
                        "impatto_asset": "NON_VALUTABILE"})
    return {"fonti_ufficiali": entries,
            "ipotesi": "Una variazione inattesa della politica monetaria potrebbe modificare le condizioni di liquidita.",
            "controipotesi": "La variazione potrebbe essere gia incorporata nei prezzi o prevalerebbero altri fattori.",
            "condizione_di_riesame": "Confrontare decisione ufficiale, consenso datato e prezzi successivi.",
            "statuto": "IPOTESI_NON_ATTESTATA_DAI_TITOLI_RSS",
            "sorpresa_vs_consenso": "NON_VALUTABILE"}


def regime(btc_four, global_row, now):
    out = {"stato": "INDETERMINATO", "qualita": "INSUFFICIENTE",
           "favorevoli": [], "contrari": [], "mancanti": [],
           "invalidazione": "Riesaminare con chiusure 4H/1D e dati aggregati freschi",
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
    if trend["4H"] != trend["1D"]:
        out.update(stato="TRANSIZIONE", qualita="PARZIALE",
                   contrari=["BTC 4H e 1D discordanti"])
        return out
    if trend["4H"] == "LATERALE":
        out.update(stato="LATERALE", qualita="PARZIALE", favorevoli=["BTC 4H e 1D laterali"])
        return out
    if not isinstance(global_row, dict) or not stamp(global_row.get("aggiornato_sorgente_utc")):
        out["mancanti"].append("CoinGecko globale datato")
        return out
    updated = stamp(global_row["aggiornato_sorgente_utc"])
    change = global_row.get("var_capitalizzazione_24h_pct")
    if (updated > now + dt.timedelta(minutes=2) or now-updated > dt.timedelta(hours=2)
            or not isinstance(change, (int, float)) or not math.isfinite(change)):
        out["mancanti"].append("Variazione capitalizzazione globale fresca")
        return out
    direction = "RIALZISTA" if trend["4H"] == "SALITA" else "RIBASSISTA"
    consistent = (change > 0 if direction == "RIALZISTA" else change < 0)
    out["favorevoli"].append("BTC 4H/1D concordi: " + trend["4H"])
    if consistent:
        out.update(stato=direction, qualita="PARZIALE")
        out["favorevoli"].append("Capitalizzazione aggregata 24h concorde")
    else:
        out.update(stato="TRANSIZIONE", qualita="PARZIALE")
        out["contrari"].append("Capitalizzazione aggregata 24h contraria al trend BTC")
    out["mancanti"].append("Partecipazione/volumi indipendenti e derivati con copertura")
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
        issue += "; release software ufficiale documentata"
        opposite += "; una release non prova un effetto economico"
    return {"fatto": issue, "rischio_opportunita_ipotesi": hypothesis,
            "controipotesi": opposite,
            "condizione_riesame": "Controllare nuovi dati supply, schedule primario e fatti specifici del progetto"}


def at_read(source, positions, shortlist, now):
    """Validate attribution and recalculate economic age, without source fetches."""
    if not isinstance(source, dict) or source.get("schema") != VERSION:
        raise ValueError("Schema evidenza economica")
    acquired = stamp(source.get("acquisito_utc"))
    if not acquired or acquired > now + dt.timedelta(minutes=2):
        raise ValueError("Tempo evidenza economica")
    original_positions = source.get("posizioni")
    original_candidates = source.get("candidati")
    if not isinstance(original_positions, list) or not isinstance(original_candidates, list):
        raise ValueError("Copertura economica")
    if len(original_positions) != len(positions) or len(original_candidates) != len(shortlist):
        raise ValueError("Cardinalita economica")
    result = {"schema": VERSION, "acquisito_utc": source["acquisito_utc"],
              "letto_utc": now.isoformat(timespec="seconds"),
              "posizioni": [], "candidati": []}
    for name, source_rows, expected in (
            ("posizioni", original_positions, positions),
            ("candidati", original_candidates, shortlist)):
        for i, (row, target) in enumerate(zip(source_rows, expected)):
            if not isinstance(row, dict) or row.get("indice") != i or row.get("token") != target.get("token"):
                raise ValueError("Identita economica discordante")
            if name == "candidati" and row.get("coppia_analisi") != target.get("coppia_analisi"):
                raise ValueError("Coppia candidato discordante")
            identity = row.get("identita")
            if not isinstance(identity, dict) or identity.get("token") != row["token"]:
                raise ValueError("Identita economica non valida")
            if identity.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO":
                if (row["token"] not in PROJECTS or
                        identity.get("coingecko_id") != PROJECTS[row["token"]][0] or
                        identity.get("progetto") != PROJECTS[row["token"]][1] or
                        not identity.get("pair_key")):
                    raise ValueError("Identita CoinGecko non attribuibile")
            row_copy = dict(row)
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
            row_copy["lettura_economica"] = decision_context(
                identity, row_copy["fondamentali"], row_copy["evento"])
            result[name].append(row_copy)
    regime_data = source.get("regime")
    if not isinstance(regime_data, dict):
        raise ValueError("Regime economico mancante")
    result["regime"] = dict(regime_data)
    if now-acquired > dt.timedelta(hours=2):
        result["regime"].update(stato="INDETERMINATO", qualita="SCADUTO",
                                limite="Regime storico; ricalcolo necessario")
    macro_data = source.get("macro")
    if not isinstance(macro_data, dict):
        raise ValueError("Macro mancante")
    result["macro"] = dict(macro_data)
    result["macro"]["fonti_ufficiali"] = []
    for item in macro_data.get("fonti_ufficiali", []):
        if not isinstance(item, dict):
            raise ValueError("Fonte macro non valida")
        t = stamp(item.get("pubblicato_utc"))
        state = ("VERIFICATO" if t and dt.timedelta(0) <= now-t <= dt.timedelta(days=14)
                 and item.get("stato") == "VERIFICATO" else
                 "SCADUTO" if t else "NON_VERIFICATO")
        result["macro"]["fonti_ufficiali"].append(dict(item, stato=state,
                                                       impatto_asset="NON_VALUTABILE"))
    return result
