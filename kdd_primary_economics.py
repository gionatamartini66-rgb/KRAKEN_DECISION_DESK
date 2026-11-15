"""Economic primary evidence inside the existing KDD dossier -> packet -> GPT chain.

Bounded read-only ingestion. No wallet, balances, trading, scheduled service or
vendor secrets. All project bindings come from verified economic identities.
"""
import csv
import calendar
import datetime as dt
import io
import json
import math
import re
from urllib.parse import urlparse

VERSION = "kdd-primary-economic-v001"
UTC = dt.timezone.utc
MAX_PROJECTS = 2
MAX_REQUESTS = 8
HISTORY_LIMIT = 48
RPC_SOL = "https://api.mainnet.solana.com"
ECB_SERIES = {
    "TASSO_RIFINANZIAMENTO_BCE": (
        "FM/D.U2.EUR.4F.KR.MRR_FR.LEV", "PERCENTUALE_ANNUA"),
    "CAMBIO_USD_PER_EUR": (
        "EXR/D.USD.EUR.SP00.A", "USD_PER_EUR"),
    "INFLAZIONE_HICP_EUROZONA": (
        "HICP/M.U2.N.000000.4D0.ANR", "INFLAZIONE_AA_PCT"),
    "M3_CRESCITA_EUROZONA": (
        "BSI/M.U2.Y.V.M30.X.I.U2.2300.Z01.A", "M3_CRESCITA_AA_PCT"),
}
LABELS = {"governance", "security", "tokenomics", "protocol",
          "upgrade", "migration", "breaking-change", "deprecation"}


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def numeric(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return value if value >= 0 else None


def name(identity):
    if not isinstance(identity, dict) or identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO":
        return None
    coin = identity.get("coingecko_id")
    if not isinstance(coin, str) or not re.fullmatch(r"[a-z0-9-]{2,120}", coin):
        return None
    return coin


def _solana_policy(response, now):
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict) or response.get("error") is not None:
        raise ValueError("Solana primary RPC malformed")
    keys = ("initial", "taper", "terminal", "foundation", "foundationTerm")
    if any(numeric(result.get(k)) is None for k in keys):
        raise ValueError("Solana primary inflation fields invalid")
    if any(result[k] > 1 for k in ("initial", "taper", "terminal", "foundation")):
        raise ValueError("Solana inflation percentage not fraction")
    return {"stato": "OSSERVATO", "tipo": "PARAMETRI_EMISSIONE_SOLANA",
            "fonte": RPC_SOL, "documentazione": "https://solana.com/docs/rpc/http/getinflationgovernor",
            "pubblicato_utc": None, "osservato_utc": now.isoformat(timespec="seconds"),
            "acquisito_utc": now.isoformat(timespec="seconds"),
            "valori": {k: result[k] for k in keys}, "unita": "FRAZIONE_ANNUA",
            "limite": "Parametri RPC correnti: non sono un calendario unlock, né emissioni vendute"}


def parse_calendar(identity, payload, source, now):
    """Accept only an explicitly registered primary project schedule (never FDV)."""
    out = {"stato": "NON_VERIFICATO", "fonte": source, "pubblicato_utc": None,
           "eventi": [], "unita": "TOKEN", "motivo": "SCHEDULE_PRIMARIO_NON_VALIDO",
           "acquisito_utc": now.isoformat(timespec="seconds")}
    if not isinstance(payload, dict) or payload.get("schema") != "kdd-primary-vesting-v001":
        return out
    if payload.get("coingecko_id") != name(identity) or payload.get("source_url") != source:
        return out
    published = timestamp(payload.get("published_at"))
    if not published or not dt.timedelta(0) <= now-published <= dt.timedelta(days=365):
        return out
    events = payload.get("events")
    if not isinstance(events, list) or not 0 < len(events) <= 64:
        return out
    parsed = []
    for row in events:
        if not isinstance(row, dict) or row.get("kind") not in ("UNLOCK_PROGRAMMATO", "VESTING_PROGRAMMATO"):
            return out
        when = timestamp(row.get("scheduled_utc"))
        qty = numeric(row.get("quantity_tokens"))
        if not when or qty is None or qty <= 0 or when < published:
            return out
        parsed.append({"tipo": row["kind"], "data_programmata_utc": when.isoformat(timespec="seconds"),
                       "quantita_token": qty, "immissione_in_circolazione": "NON_ATTESTATA",
                       "vendita": "NON_ATTESTATA"})
    parsed.sort(key=lambda r: (r["data_programmata_utc"], r["tipo"]))
    out.update(stato="OSSERVATO", pubblicato_utc=published.isoformat(timespec="seconds"),
               eventi=parsed, motivo=None,
               limite="Sblocco programmato: non prova circolazione effettiva né vendita")
    return out


def parse_monthly_projection(identity, rows, source, now, *, maximum=None):
    """Primary *planned* month-end circulation, NOT a confirmed vesting/unlock.

    Schema per the official project's public API: year/month,
    circulatingSupplyValue and circulatingSupplyPercentage. Future month-end
    figures are projected availability, not executed distributions or sales.
    """
    blank = {"stato": "NON_VERIFICATO", "tipo": "PROIEZIONE_CIRCOLAZIONE",
             "fonte": source, "pubblicato_utc": None,
             "acquisito_utc": now.isoformat(timespec="seconds"), "eventi": [],
             "limite": "API primaria assente o struttura/ordine non verificabile"}
    if name(identity) is None or not isinstance(rows, list) or not 1 < len(rows) <= 180:
        return blank
    if numeric(maximum) is None or maximum <= 0:
        return blank
    parsed = []
    for item in rows:
        if not isinstance(item, dict) or type(item.get("year")) is not int or type(item.get("month")) is not int:
            return blank
        year, month = item["year"], item["month"]
        if not (2020 <= year <= now.year+20 and 1 <= month <= 12):
            return blank
        value = numeric(item.get("circulatingSupplyValue"))
        percent = numeric(item.get("circulatingSupplyPercentage"))
        if (value is None or percent is None or value > maximum or percent > 1
                or abs(value/maximum-percent) > .001):
            return blank
        date = dt.date(year, month, calendar.monthrange(year, month)[1])
        parsed.append((date, value))
    parsed.sort()
    if (len({row[0] for row in parsed}) != len(parsed)
            or any(b[1]+.001 < a[1] for a,b in zip(parsed, parsed[1:]))):
        return blank
    current_month = dt.date(now.year, now.month, 1)
    forecast = []
    for i, (date, value) in enumerate(parsed):
        if date < current_month or len(forecast) >= 24:
            continue
        before = parsed[i-1][1] if i else None
        forecast.append({"periodo_fine_mese": date.isoformat(),
                         "circolante_previsto_token": value,
                         "incremento_previsto_token": round(value-before, 6) if before is not None else None,
                         "sblocco_individuale": "NON_ATTESTATO",
                         "immissione_effettiva": "NON_ATTESTATA",
                         "vendita": "NON_ATTESTATA",
                         "unita": "TOKEN"})
    if not forecast:
        return blank
    return {"stato": "OSSERVATO", "tipo": "PROIEZIONE_CIRCOLAZIONE",
            "fonte": source, "pubblicato_utc": None,
            "acquisito_utc": now.isoformat(timespec="seconds"),
            "intervallo_fonte": {"dal": parsed[0][0].isoformat(),
                                 "al": parsed[-1][0].isoformat()},
            "eventi": forecast, "unita": "TOKEN",
            "limite": ("Proiezione ufficiale fine mese soggetta a cambiamenti; "
                       "incremento circolante non equivale a unlock certo né vendita")}


def parse_issues(identity, rows, now):
    """Official repository issues are proposals/alerts, not adopted decisions."""
    repo = identity.get("repository_primario")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return []
    expected = "https://github.com/" + repo + "/issues/"
    if not isinstance(rows, list):
        raise ValueError("GitHub issues response not list")
    out = []
    for issue in rows[:15]:
        if not isinstance(issue, dict) or "pull_request" in issue:
            continue
        url = issue.get("html_url")
        published = timestamp(issue.get("created_at"))
        tags = {x["name"].lower() for x in issue.get("labels", [])
                if isinstance(x, dict) and isinstance(x.get("name"), str)}
        matched = sorted(tags & LABELS)
        if not isinstance(url, str) or not url.startswith(expected):
            continue
        if not re.fullmatch(r"[0-9]+", url[len(expected):]) or not matched:
            continue
        if not published or published > now + dt.timedelta(minutes=2):
            continue
        out.append({"tipo": "SEGNALAZIONE_REPOSITORY_PRIMARIO",
                    "categorie": matched, "stato": "PUBBLICATO_DA_VERIFICARE",
                    "titolo": str(issue.get("title") or "")[:180], "fonte": url,
                    "emittente": repo, "pubblicato_utc": published.isoformat(timespec="seconds"),
                    "evento_utc": None, "acquisito_utc": now.isoformat(timespec="seconds"),
                    "esito_proposta": "NON_ATTESTATO",
                    "limite": "Issue etichettata: non attesta governance approvata, upgrade attuato o prezzo"})
    return out[:8]


def parse_ecb_csv(raw, series, unit, now):
    if not isinstance(raw, (bytes, str)):
        raise ValueError("ECB CSV invalid")
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw))
    valid = []
    for row in rows:
        period, value = row.get("TIME_PERIOD"), row.get("OBS_VALUE")
        if not isinstance(period, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?", period):
            continue
        try:
            n = float(value)
            t = dt.date.fromisoformat(period + "-01" if len(period) == 7 else period)
        except (ValueError, TypeError, OverflowError):
            continue
        if not math.isfinite(n) or t > now.date():
            continue
        if unit == "USD_PER_EUR" and n <= 0:
            continue
        if unit == "PERCENTUALE_ANNUA" and not (0 <= n <= 50):
            continue
        if unit in ("INFLAZIONE_AA_PCT", "M3_CRESCITA_AA_PCT") and not (-50 <= n <= 100):
            continue
        valid.append((t, n))
    if not valid:
        raise ValueError("ECB has no trustworthy observation")
    valid.sort()
    last = valid[-1]
    previous = valid[-2] if len(valid) > 1 else None
    return {"stato": "OSSERVATO", "fonte": "https://data-api.ecb.europa.eu/service/data/"+series,
            "emittente": "BANCA_CENTRALE_EUROPEA",
            "periodo_dato": last[0].isoformat(), "pubblicato_utc": None,
            "acquisito_utc": now.isoformat(timespec="seconds"),
            "valore": last[1], "unita": unit,
            "precedente": {"periodo_dato": previous[0].isoformat(), "valore": previous[1]} if previous else None,
            "limite": "Dato ECB osservato; nessun consenso, sorpresa o effetto prezzo dedotto"}


def _empty(coin, reason, now):
    return {"coingecko_id": coin, "stato": reason, "acquisito_utc": now.isoformat(timespec="seconds"),
            "politica_emissioni": {"stato": "NON_DISPONIBILE", "valori": None},
            "calendario": {"stato": "NON_VERIFICATO", "eventi": [], "fonte": None},
            "proiezione_circolazione": {"stato": "NON_VERIFICATO", "eventi": [], "fonte": None},
            "eventi": [], "confronto_precedente_utc": None, "variazioni": [],
            "limite": "Fonte primaria assente o non interrogata: nessun evento o unlock inferito"}


def collect(now, identities, previous, *, fetch_json, fetch_csv, catalog, enabled=True):
    """Rotate dynamic project IDs within a small public budget; persist bounded history."""
    if now.tzinfo is None:
        raise ValueError("UTC required")
    moment = now.astimezone(UTC)
    names = {}
    for identity in identities:
        coin = name(identity)
        if coin:
            names.setdefault(coin, identity)
    keys = sorted(names)
    if not enabled:
        return {"schema": VERSION, "acquisito_utc": moment.isoformat(timespec="seconds"),
                "progetti": [_empty(k, "NON_ACQUISITO_FUORI_REFRESH", moment) for k in keys],
                "storico": [], "prossimo_progetto": keys[0] if keys else None,
                "indicatori_macro": [{"id": k, "stato": "NON_ACQUISITO_FUORI_REFRESH"}
                                      for k in ECB_SERIES],
                "richieste_effettuate": 0, "limite_richieste": MAX_REQUESTS,
                "limite": "Nessuna fonte interrogata fuori dal refresh KDD autorizzato"}
    old = previous if isinstance(previous, dict) and previous.get("schema") == VERSION else {}
    prior_rows = {r.get("coingecko_id"): r for r in old.get("progetti", [])
                  if isinstance(r, dict) and r.get("coingecko_id") in names}
    historical = {r.get("coingecko_id"): r for r in old.get("storico", [])
                  if isinstance(r, dict) and r.get("coingecko_id") in names}
    historical.update({k: v for k, v in prior_rows.items()
                       if v.get("stato") not in ("RINVIATO_BUDGET",)})
    start = next((i for i, k in enumerate(keys)
                  if isinstance(old.get("prossimo_progetto"), str) and k >= old["prossimo_progetto"]), 0)
    chosen = [keys[(start+i) % len(keys)] for i in range(min(MAX_PROJECTS, len(keys)))]
    requests = 0
    observed = {}
    for coin in chosen:
        identity = names[coin]
        record = _empty(coin, "INTERROGATO", moment)
        registry = catalog.get(identity.get("token_progetto"), {})
        if registry.get("id") != coin or registry.get("name") != identity.get("progetto"):
            registry = {}
        emission = registry.get("emission_primary")
        if emission == "SOLANA_RPC_GOVERNOR" and requests+1 <= MAX_REQUESTS:
            requests += 1
            try:
                reply = fetch_json(RPC_SOL, {"jsonrpc": "2.0", "id": 1,
                                             "method": "getInflationGovernor",
                                             "params": [{"commitment": "finalized"}]})
                record["politica_emissioni"] = _solana_policy(reply, moment)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                record["politica_emissioni"] = {"stato": "NON_DISPONIBILE", "motivo": "RPC_PRIMARIO_NON_DISPONIBILE"}
        schedule = registry.get("schedule_primary")
        if isinstance(schedule, dict) and requests+1 <= MAX_REQUESTS:
            repo = identity.get("repository_primario")
            path = schedule.get("path")
            if (isinstance(repo, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
                    and isinstance(path, str) and re.fullmatch(r"[A-Za-z0-9_./-]{1,160}\.json", path)
                    and ".." not in path):
                url = "https://raw.githubusercontent.com/" + repo + "/main/" + path
                requests += 1
                try:
                    record["calendario"] = parse_calendar(identity, fetch_json(url, None), url, moment)
                except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                    record["calendario"]["stato"] = "NON_DISPONIBILE_FONTE"
        projection = registry.get("circulation_schedule_primary")
        if (isinstance(projection, dict) and
                projection.get("type") == "MONTHLY_CIRCULATION_PROJECTION" and
                isinstance(projection.get("url"), str) and
                projection["url"].startswith("https://") and
                urlparse(projection["url"]).hostname not in (None,"localhost","127.0.0.1") and
                not urlparse(projection["url"]).username and
                not urlparse(projection["url"]).password and
                requests+1 <= MAX_REQUESTS):
            requests += 1
            try:
                record["proiezione_circolazione"] = parse_monthly_projection(
                    identity, fetch_json(projection["url"], None),
                    projection["url"], moment,
                    maximum=projection.get("max_supply_tokens"))
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                record["proiezione_circolazione"] = {
                    "stato": "NON_DISPONIBILE_FONTE", "fonte": projection["url"],
                    "motivo": (f"HTTP_{exc.code}" if isinstance(exc, __import__("urllib.error", fromlist=["HTTPError"]).HTTPError)
                               else type(exc).__name__),
                    "eventi": [], "acquisito_utc": moment.isoformat(timespec="seconds")}
        repo = identity.get("repository_primario")
        if isinstance(repo, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) and requests+1 <= MAX_REQUESTS:
            url = "https://api.github.com/repos/" + repo + "/issues?state=all&per_page=15&sort=updated"
            requests += 1
            try:
                record["eventi"] = parse_issues(identity, fetch_json(url, None), moment)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                record["stato"] = "FONTE_EVENTI_NON_DISPONIBILE"
        old_row = historical.get(coin)
        if isinstance(old_row, dict):
            old_time = timestamp(old_row.get("acquisito_utc"))
            if old_time and dt.timedelta(0) <= moment-old_time <= dt.timedelta(days=7):
                record["confronto_precedente_utc"] = old_row["acquisito_utc"]
                old_emission = old_row.get("politica_emissioni", {})
                fresh_emission = record.get("politica_emissioni", {})
                if (old_emission.get("stato") == "OSSERVATO" and
                        fresh_emission.get("stato") == "OSSERVATO" and
                        old_emission.get("valori") != fresh_emission.get("valori")):
                    record["variazioni"].append("PARAMETRI_EMISSIONE_MODIFICATI")
                old_calendar = old_row.get("calendario", {})
                if record["calendario"].get("stato") == "OSSERVATO" and old_calendar.get("stato") == "OSSERVATO":
                    if old_calendar.get("eventi") != record["calendario"].get("eventi"):
                        record["variazioni"].append("CALENDARIO_PRIMARIO_MODIFICATO")
                old_projection = old_row.get("proiezione_circolazione", {})
                new_projection = record.get("proiezione_circolazione", {})
                if (new_projection.get("stato") == "OSSERVATO" and
                        old_projection.get("stato") == "OSSERVATO" and
                        new_projection.get("eventi") != old_projection.get("eventi")):
                    record["variazioni"].append("PROIEZIONE_CIRCOLAZIONE_MODIFICATA")
                old_events = {e.get("fonte") for e in old_row.get("eventi", [])}
                new_events = {e.get("fonte") for e in record["eventi"]}
                if new_events-old_events:
                    record["variazioni"].append("NUOVI_EVENTI_PRIMARI_ETICHETTATI")
        observed[coin] = record
    for coin in keys:
        observed.setdefault(coin, _empty(coin, "RINVIATO_BUDGET", moment))
    macro = []
    for key, (series, unit) in ECB_SERIES.items():
        if requests >= MAX_REQUESTS:
            macro.append({"id": key, "stato": "RINVIATO_BUDGET"})
            continue
        requests += 1
        url = "https://data-api.ecb.europa.eu/service/data/"+series+"?format=csvdata&lastNObservations=2"
        try:
            item = parse_ecb_csv(fetch_csv(url), series, unit, moment)
            item["id"] = key
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            item = {"id": key, "stato": "NON_DISPONIBILE", "fonte": url,
                    "acquisito_utc": moment.isoformat(timespec="seconds")}
        macro.append(item)
    previous_macro = {row.get("id"): row for row in old.get("indicatori_macro", [])
                      if isinstance(row, dict)}
    for item in macro:
        past = previous_macro.get(item["id"])
        if (item.get("stato") == "OSSERVATO" and isinstance(past, dict)
                and past.get("stato") == "OSSERVATO" and
                isinstance(past.get("periodo_dato"), str) and
                past["periodo_dato"] <= item["periodo_dato"] and
                type(past.get("valore")) in (int, float) and
                math.isfinite(past["valore"])):
            item["confronto_precedente"] = {
                "periodo_dato": past["periodo_dato"],
                "valore": past["valore"],
                "acquisito_utc": past.get("acquisito_utc")}
            item["variazione_da_ultima_lettura"] = round(
                item["valore"]-past["valore"], 7)
            item["limite_comparazione"] = (
                "Differenza tra osservazioni successive della fonte istituzionale, "
                "non sorpresa rispetto al consenso e non reazione di prezzo")
    history = [observed[k] if observed[k]["stato"] != "RINVIATO_BUDGET" else historical.get(k)
               for k in keys]
    history = [x for x in history if isinstance(x, dict)][:HISTORY_LIMIT]
    return {"schema": VERSION, "acquisito_utc": moment.isoformat(timespec="seconds"),
            "progetti": [observed[k] for k in keys], "storico": history,
            "prossimo_progetto": keys[(start+len(chosen))%len(keys)] if keys else None,
            "indicatori_macro": macro, "richieste_effettuate": requests,
            "limite_richieste": MAX_REQUESTS, "limite": "Prove pubbliche primarie, non segnali o esecuzioni"}


def at_read(raw, identities, now, *, catalog=None):
    """Fail closed on fabricated project attribution, future times and source drift."""
    if not isinstance(raw, dict) or raw.get("schema") != VERSION:
        raise ValueError("primary economic schema invalid")
    observed = timestamp(raw.get("acquisito_utc"))
    if observed is None or observed > now + dt.timedelta(minutes=2):
        raise ValueError("primary acquisition time invalid")
    allowed = {name(x) for x in identities if name(x)}
    rows = raw.get("progetti")
    if not isinstance(rows, list) or len(rows) != len(allowed):
        raise ValueError("primary project cardinality")
    if type(raw.get("richieste_effettuate")) is not int or not 0 <= raw["richieste_effettuate"] <= MAX_REQUESTS:
        raise ValueError("primary public request count")
    seen = set()
    output = []
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError("primary record invalid")
        coin = record.get("coingecko_id")
        if coin not in allowed or coin in seen:
            raise ValueError("wrong primary project")
        seen.add(coin)
        rec = dict(record)
        t = timestamp(rec.get("acquisito_utc"))
        if t is None or t > observed + dt.timedelta(minutes=2):
            raise ValueError("project timestamps untrusted")
        if now - t > dt.timedelta(days=7):
            rec["stato_alla_lettura"] = "SCADUTO"
        else:
            rec["stato_alla_lettura"] = rec.get("stato")
        calendar = rec.get("calendario", {})
        if calendar.get("stato") == "OSSERVATO":
            identity = next(x for x in identities if name(x) == coin)
            repo = identity.get("repository_primario")
            source = calendar.get("fonte")
            if not isinstance(repo, str) or not isinstance(source, str) or not source.startswith(
                    "https://raw.githubusercontent.com/" + repo + "/main/"):
                raise ValueError("schedule source not bound to project")
            if timestamp(calendar.get("pubblicato_utc")) is None:
                raise ValueError("schedule has no publication time")
            for event in calendar.get("eventi", []):
                if (event.get("tipo") not in ("UNLOCK_PROGRAMMATO","VESTING_PROGRAMMATO")
                        or timestamp(event.get("data_programmata_utc")) is None
                        or numeric(event.get("quantita_token")) is None
                        or event.get("vendita") != "NON_ATTESTATA"):
                    raise ValueError("invented unlock evidence")
        projection = rec.get("proiezione_circolazione")
        if isinstance(projection, dict) and projection.get("stato") == "OSSERVATO":
            identity_for_source = next(x for x in identities if name(x) == coin)
            entry = (catalog or {}).get(identity_for_source.get("token_progetto"), {})
            approved = entry.get("circulation_schedule_primary", {})
            if (entry.get("id") != coin or approved.get("type") != "MONTHLY_CIRCULATION_PROJECTION"
                    or projection.get("fonte") != approved.get("url")):
                raise ValueError("unbound monthly supply source")
            for event in projection.get("eventi", []):
                if (event.get("vendita") != "NON_ATTESTATA"
                        or event.get("immissione_effettiva") != "NON_ATTESTATA"
                        or numeric(event.get("circolante_previsto_token")) is None):
                    raise ValueError("false circulation forecast")
        identity = next(x for x in identities if name(x) == coin)
        repo = identity.get("repository_primario")
        for event in rec.get("eventi", []):
            if (not isinstance(repo, str) or not isinstance(event, dict)
                    or not isinstance(event.get("fonte"), str)
                    or not event["fonte"].startswith("https://github.com/" + repo + "/issues/")
                    or timestamp(event.get("pubblicato_utc")) is None
                    or event.get("evento_utc") is not None):
                raise ValueError("project news not attributable")
        output.append(rec)
    macro = []
    for row in raw.get("indicatori_macro", []):
        if not isinstance(row, dict) or row.get("id") not in ECB_SERIES:
            raise ValueError("macro source unknown")
        if row.get("stato") == "OSSERVATO":
            series, unit = ECB_SERIES[row["id"]]
            if (row.get("fonte") != "https://data-api.ecb.europa.eu/service/data/"+series
                    or row.get("unita") != unit
                    or type(row.get("valore")) not in (float, int)
                    or not math.isfinite(row["valore"])):
                raise ValueError("macro evidence invalid")
            record = dict(row)
            record["stato_alla_lettura"] = ("SCADUTO" if now-observed > dt.timedelta(days=2)
                                            else "OSSERVATO")
            past = record.get("confronto_precedente")
            if past is not None and (
                    not isinstance(past, dict) or
                    type(past.get("valore")) not in (int, float) or
                    not math.isfinite(past["valore"]) or
                    not isinstance(past.get("periodo_dato"), str) or
                    past["periodo_dato"] > record.get("periodo_dato", "")):
                raise ValueError("macro comparison malformed")
            if past is not None:
                expected_delta = round(record["valore"]-past["valore"], 7)
                if record.get("variazione_da_ultima_lettura") != expected_delta:
                    raise ValueError("macro comparison fabricated")
            macro.append(record)
        else:
            macro.append(dict(row))
    if "storico_sintesi" in raw:
        summaries = raw["storico_sintesi"]
        if not isinstance(summaries, list) or len(summaries) > HISTORY_LIMIT:
            raise ValueError("historical summary malformed")
        keys_seen = set()
        for row in summaries:
            if (not isinstance(row, dict) or row.get("coingecko_id") not in allowed
                    or row["coingecko_id"] in keys_seen or
                    row.get("stato_alla_lettura") != "STORICO_NON_RICONFERMATO"):
                raise ValueError("historical summary identity invalid")
            acquired = timestamp(row.get("acquisito_utc"))
            if not acquired or acquired > observed + dt.timedelta(minutes=2):
                raise ValueError("historical summary timestamp invalid")
            keys_seen.add(row["coingecko_id"])
        history_output = summaries
    else:
        historical_rows = raw.get("storico", [])
        if not isinstance(historical_rows, list) or len(historical_rows) > HISTORY_LIMIT:
            raise ValueError("primary history cardinality invalid")
        history_output = []
        seen_hist = set()
        for item in historical_rows:
            if not isinstance(item, dict) or item.get("coingecko_id") not in allowed:
                raise ValueError("primary historical project invalid")
            key = item["coingecko_id"]
            stamp_ = timestamp(item.get("acquisito_utc"))
            if (key in seen_hist or not stamp_ or
                    stamp_ > observed + dt.timedelta(minutes=2)):
                raise ValueError("historical observation timestamp invalid")
            seen_hist.add(key)
            history_output.append({
                "coingecko_id": key, "acquisito_utc": item["acquisito_utc"],
                "stato": item.get("stato"),
                "stato_alla_lettura": "STORICO_NON_RICONFERMATO",
                "eventi_rilevati": len(item.get("eventi", [])),
                "calendario_stato": (item.get("calendario") or {}).get("stato"),
                "proiezione_stato": (item.get("proiezione_circolazione") or {}).get("stato"),
                "limite": "Dato precedente conservato per confronto, non nuova osservazione"})
        return {"schema": VERSION, "acquisito_utc": raw["acquisito_utc"],
            "progetti": output, "storico_sintesi": history_output,
            "indicatori_macro": macro,
            "richieste_effettuate": raw["richieste_effettuate"],
            "limite": raw.get("limite")}
