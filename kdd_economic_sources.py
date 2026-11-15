"""KDD-18/20/21: primary-source observations inside the existing economic dossier.

Only public, bounded GETs. Source associations are project-specific catalog DATA,
not ticker searches. Collection and read-time validation have separate contracts.
No source here proves an unlock was sold, a proposal adopted, or a market move caused.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import re
from urllib.parse import quote

SCHEMA = "kdd-primary-economic-followup-v001"
UTC = dt.timezone.utc
MAX_GOVERNANCE_CALLS = 2
MAX_MACRO_CALLS = 1
MAX_SCHEDULE_CALLS = 1
MAX_SECURITY_CALLS = 1
MAX_EMISSION_CALLS = 1
MAX_SAMPLES = 96
ECON_SCHEDULE_SCHEMA = "kdd-official-token-schedule-v001"
SUI_CIRCULATION = "https://sui-circulation.suiexplorer.com/api/sui_circulation"
SUI_SCHEDULE_HOME = "https://www.sui.io/token-schedule"
SOLANA_RPC = "https://api.mainnet.solana.com"
SOLANA_GOVERNOR_DOC = "https://solana.com/docs/rpc/http/getinflationgovernor"
MONTHLY_FORMAT = "official-monthly-circulation-v001"
MACRO_SERIES = (
    ("USD_EUR", "EXR", "D.USD.EUR.SP00.A", "USD per EUR", 8),
    ("EA_HICP", "HICP", "M.U2.N.000000.4D0.ANR", "variazione percentuale a/a", 65),
    ("ECB_DEPOSIT_RATE", "FM", "D.U2.EUR.4F.KR.DFR.LEV", "percentuale annua", 8),
    ("ECB_MAIN_REFI_RATE", "FM", "D.U2.EUR.4F.KR.MRR_FR.LEV", "percentuale annua", 8),
    ("EA_M3_GROWTH", "BSI", "M.U2.Y.V.M30.X.I.U2.2300.Z01.A", "variazione percentuale a/a", 65),
)
GITHUB = "https://api.github.com/repos/"
ECB = "https://data-api.ecb.europa.eu/service/data/"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
PATH = re.compile(r"[A-Za-z0-9_.\-/]+\Z")
SHA_OR_REF = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
COIN = re.compile(r"[a-z0-9-]{2,120}\Z")


def _time(value):
    import kdd_economics as econ
    return econ.stamp(value)


def _utc(moment):
    if not isinstance(moment, dt.datetime) or moment.tzinfo is None:
        raise ValueError("UTC timestamp required")
    return moment.astimezone(UTC)


def _iso(moment):
    return _utc(moment).isoformat(timespec="seconds")


def _catalog_source(identity):
    import kdd_economics as econ
    if not isinstance(identity, dict) or identity.get("stato") != "IDENTITA_VERIFICATA_DA_CATALOGO":
        return {}
    if identity.get("metodo") != "REGISTRO_CURATO":
        return {}
    token = econ.canonical_token(identity.get("token"))
    known = econ.PROJECTS.get(token)
    if not known or known[:2] != (identity.get("coingecko_id"), identity.get("progetto")):
        return {}
    return econ._CURATED.get(token, {})


def _roster(items):
    found = {}
    for group in ("posizioni", "candidati"):
        for row in items.get(group, []):
            if not isinstance(row, dict):
                continue
            identity = row.get("identita")
            if not isinstance(identity, dict):
                continue
            verified = identity.get("stato") == "IDENTITA_VERIFICATA_DA_CATALOGO"
            # At the second GPT read pass a once-proven dynamically matched
            # project may be expired. Keep the *historical* roster identity to
            # validate its old empty-source entry; do not re-authorize its data.
            expired = (identity.get("stato") == "NON_VERIFICATO"
                       and identity.get("motivo") == "ATTESTAZIONE_IDENTITA_SCADUTA"
                       and identity.get("metodo") == "KRAKEN_COINGECKO_MARKET"
                       and isinstance(identity.get("prova_mercato"), dict))
            if not (verified or expired):
                continue
            pid = identity.get("coingecko_id")
            if not isinstance(pid, str) or not COIN.fullmatch(pid):
                continue
            if pid not in found:
                found[pid] = {"progetto_id": pid, "progetto": identity.get("progetto"),
                              "token": identity.get("token"), "source": _catalog_source(identity),
                              "rows": []}
            found[pid]["rows"].append(row)
    return dict(sorted(found.items()))


def _source_repo(descriptor):
    repo = descriptor.get("governance_repository") if isinstance(descriptor, dict) else None
    return repo if isinstance(repo, str) and REPO.fullmatch(repo) else None


def _security_repo(descriptor):
    if not isinstance(descriptor,dict): return None
    repo=descriptor.get("security_repository") or descriptor.get("repository")
    return repo if isinstance(repo,str) and REPO.fullmatch(repo) else None


def _security_events(payload, repo, now):
    """Authentic public repository advisories, not a claim of token compromise."""
    if not isinstance(payload,list) or len(payload)>25: return None
    rows=[]
    for source in payload[:5]:
        if not isinstance(source,dict): return None
        uid=source.get("ghsa_id")
        if not isinstance(uid,str) or not re.fullmatch(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}",uid):
            return None
        url="https://github.com/"+repo+"/security/advisories/"+uid
        published=_time(source.get("published_at"))
        withdrawn=_time(source.get("withdrawn_at"))
        if (source.get("html_url")!=url or published is None
                or published>now+dt.timedelta(minutes=2)
                or (withdrawn and withdrawn<published)):
            return None
        if source.get("state")!="published": continue
        summary=source.get("summary")
        if not isinstance(summary,str) or not summary.strip(): return None
        rows.append({"id":uid,"fonte":url,"emittente":repo,
                     "tipo":"AVVISO_REPOSITORY","titolo":summary.strip()[:200],
                     "pubblicato_utc":_iso(published),
                     "ritirato_utc":_iso(withdrawn) if withdrawn else None,
                     "stato":"RITIRATO" if withdrawn else "PUBBLICATO",
                     "impatto_sul_token":"NON_ATTESTATO",
                     "limite":"Advisory del repository: non prova effetto sul token, fondi o prezzo"})
    return rows


def _solana_governor(payload, now):
    """Official current inflation parameters. Not a vesting/unlock calendar."""
    obj=payload.get("result") if isinstance(payload,dict) else None
    if not isinstance(obj,dict) or payload.get("error") is not None:
        return None
    keys=("initial","taper","terminal","foundation","foundationTerm")
    if any(type(obj.get(k)) not in (int,float) or not math.isfinite(obj[k]) or obj[k]<0
           for k in keys):
        return None
    if any(obj[k]>1 for k in keys[:4]) or obj["foundationTerm"]>1000:
        return None
    return {"stato":"OSSERVATO","tipo":"PARAMETRI_EMISSIONE_SOLANA",
            "fonte":SOLANA_RPC,"documentazione":SOLANA_GOVERNOR_DOC,
            "pubblicato_utc":None,"acquisito_utc":_iso(now),
            "unita":"FRAZIONE_ANNUA","valori":{k:obj[k] for k in keys},
            "stato_unlock":"NON_ATTESTATO","vendita":"NON_ATTESTATA",
            "limite":"RPC inflazione Solana attuale: parametri di emissione, non calendario unlock, quantità emessa o vendite"}


def _emission_descriptor(descriptor):
    if not isinstance(descriptor,dict): return None
    return SOLANA_RPC if descriptor.get("emission_primary")=="SOLANA_RPC_GOVERNOR" else None


def _schedule_descriptor(descriptor):
    raw = descriptor.get("official_schedule") if isinstance(descriptor, dict) else None
    if not isinstance(raw, dict):
        return None
    if (raw.get("format") == MONTHLY_FORMAT and raw.get("url") == SUI_CIRCULATION
            and raw.get("homepage") == SUI_SCHEDULE_HOME
            and type(raw.get("max_supply_token")) is int
            and raw["max_supply_token"] == 10_000_000_000):
        return dict(raw)
    repo, path, ref = raw.get("repository"), raw.get("path"), raw.get("ref")
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or not isinstance(path, str) or not PATH.fullmatch(path)
            or ".." in path.split("/") or path.startswith("/")
            or not isinstance(ref, str) or not SHA_OR_REF.fullmatch(ref)):
        return None
    return {"format":"repository-json-v001","repository": repo, "path": path, "ref": ref}


def _fetch(fetch, url, *, json_data=True):
    try:
        raw = fetch(url)
        if not isinstance(raw, bytes) or len(raw) > 1_000_000:
            return None, "RISPOSTA_NON_CONFORME"
        if json_data:
            result = json.loads(raw.decode("utf-8"))
            return result, None
        return raw.decode("utf-8-sig"), None
    except Exception as exc:
        return None, "FONTE_" + (("RATE_LIMIT" if getattr(exc, "code", None) == 429
                                   else "HTTP_" + str(exc.code))
                                  if getattr(exc, "code", None) in (403, 404, 429, 500, 502, 503)
                                  else type(exc).__name__)


def _governance(payload, repo, acquired):
    """A documentation PR is NOT proof of protocol approval or implementation."""
    if not isinstance(payload, list) or len(payload) > 20:
        return None
    out = []
    for row in payload[:6]:
        if not isinstance(row, dict):
            return None
        number, title = row.get("number"), row.get("title")
        created, updated, merged = (_time(row.get("created_at")),
                                    _time(row.get("updated_at")), _time(row.get("merged_at")))
        expected = "https://github.com/" + repo + "/pull/" + str(number)
        base = row.get("base") or {}
        repository = base.get("repo") or {} if isinstance(base, dict) else {}
        if (type(number) is not int or number <= 0 or not isinstance(title, str)
                or not title.strip() or row.get("html_url") != expected
                or repository.get("full_name") != repo or not created or not updated
                or updated < created or (merged and merged < created)
                or created > acquired + dt.timedelta(minutes=2)):
            return None
        out.append({
            "id": str(number), "titolo": title.strip()[:220], "fonte": expected,
            "emittente": repo, "tipo": "PROPOSTA_DOCUMENTALE",
            "creato_utc": _iso(created), "pubblicato_utc": _iso(created),
            "aggiornato_fonte_utc": _iso(updated),
            "evento_utc": _iso(merged) if merged else None,
            "conosciuto_utc": _iso(acquired),
            "stato_documento": "INCORPORATO_NEL_REPO" if merged else
                              "PROPOSTO_O_NON_INTEGRATO",
            "stato_decisione_rete": "NON_ATTESTATO",
            "limite": "PR di documentazione: merge NON prova attivazione, voto o effetto di prezzo",
        })
    return out


def _series_url(series):
    _, flow, key, _, _ = series
    return ECB + flow + "/" + key + "?format=csvdata&lastNObservations=2"


def _ecb_csv(raw, series, now):
    name, flow, key, unit, days = series
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except (ValueError, csv.Error, TypeError):
        return None
    if not 1 <= len(rows) <= 3:
        return None
    dates = []
    for row in rows:
        if not isinstance(row, dict) or (row.get("KEY") or row.get("SERIES_KEY")) != flow + "." + key:
            return None
        period = row.get("TIME_PERIOD")
        value = row.get("OBS_VALUE")
        try:
            day = dt.date.fromisoformat(period + "-01" if len(period) == 7 else period)
            number = float(value)
        except (ValueError, TypeError):
            return None
        if not math.isfinite(number) or (name == "USD_EUR" and number <= 0):
            return None
        if day > now.date() + dt.timedelta(days=1):
            return None
        dates.append((day, number))
    day, value = max(dates)
    return {"id": name, "serie": flow + "." + key, "fonte": _series_url(series),
            "periodo": day.isoformat()[:7] if len(rows[0]["TIME_PERIOD"]) == 7 else day.isoformat(),
            "valore": value, "unita": unit, "acquisito_utc": _iso(now),
            "pubblicato_utc": None, "stato_pubblicazione": "NON_ATTESTATO_DAL_CSV",
            "stato": "OSSERVATO" if (now.date()-day).days <= days else "SCADUTO",
            "limite": "Data del periodo, non data di pubblicazione; revisioni possibili. Nessuna causalita sui token"}


def _official_schedule(raw, project_id, source, now):
    """Accept only a project-repository JSON with explicit attributable events.

    A third-party supply number, prose or an empty schedule cannot pass.
    A schedule is a planned release, not observed float or an exchange sale.
    """
    if not isinstance(raw, dict) or raw.get("schema") != ECON_SCHEDULE_SCHEMA:
        return None
    if raw.get("progetto_id") != project_id or raw.get("unita") != "TOKEN":
        return None
    published = _time(raw.get("pubblicato_utc"))
    if not published or published > now + dt.timedelta(minutes=2):
        return None
    rows = raw.get("eventi")
    if not isinstance(rows, list) or len(rows) > 24 or not rows:
        return None
    validated = []
    for r in rows:
        if not isinstance(r, dict) or r.get("tipo") != "UNLOCK_PROGRAMMATO":
            return None
        day = _time(r.get("evento_utc"))
        qty = r.get("quantita_token")
        if (not day or type(qty) not in (int, float) or
                not math.isfinite(qty) or qty <= 0 or
                not isinstance(r.get("allocazione"), str) or not r["allocazione"].strip()):
            return None
        validated.append({"evento_utc": _iso(day), "quantita_token": qty,
                          "allocazione": r["allocazione"][:90],
                          "stato": "PROGRAMMATO_NON_CIRCOLANTE",
                          "vendita": "NON_ATTESTATA"})
    return {"stato": "DOCUMENTO_PRIMARIO_CON_SCHEDULE",
            "fonte": source, "pubblicato_utc": _iso(published),
            "acquisito_utc": _iso(now), "unita": "TOKEN",
            "eventi": validated,
            "limite": "Programmazione documentata; sblocco, immissione e vendita sono tre fatti diversi"}



def _official_monthly(raw, project_id, descriptor, now):
    """Source's month-level circulation estimates, not actual unlock dates."""
    if (not isinstance(raw,list) or not 3 <= len(raw) <= 180
            or descriptor.get("format") != MONTHLY_FORMAT):
        return None
    months={}
    cap=descriptor["max_supply_token"]
    for x in raw:
        if not isinstance(x,dict):
            return None
        year,month=x.get("year"),x.get("month")
        qty,pct=x.get("circulatingSupplyValue"),x.get("circulatingSupplyPercentage")
        if (type(year) is not int or not 2020<=year<=2100
                or type(month) is not int or not 1<=month<=12
                or type(qty) not in (int,float) or not math.isfinite(qty)
                or not 0<=qty<=cap or type(pct) not in (int,float)
                or not math.isfinite(pct) or not 0<=pct<=1
                or abs(qty/cap-pct)>1e-6):
            return None
        key=f"{year:04d}-{month:02d}"
        if key in months:
            return None
        months[key]=float(qty)
    ordered=sorted(months)
    if any(months[a]>months[b] for a,b in zip(ordered,ordered[1:])):
        return None
    current=now.strftime("%Y-%m")
    known=[p for p in ordered if p<=current]
    future=[p for p in ordered if p>current][:12]
    if not known or not future:
        return None
    before=max(known)
    estimates=[]
    for month in future:
        estimates.append({"mese":month,"circolante_proiettato_token":months[month],
                          "aumento_previsto_token":round(months[month]-months[before],5),
                          "tipo":"PROIEZIONE_NON_UNLOCK",
                          "data_sblocco_utc":None,"vendita":"NON_ATTESTATA"})
        before=month
    return {"progetto_id":project_id,
            "stato":"PROIEZIONE_PRIMARIA_NON_UNLOCK",
            "fonte":descriptor["url"],"fonte_documentale":descriptor["homepage"],
            "acquisito_utc":_iso(now),"pubblicato_utc":None,
            "pubblicazione":"DATA_NON_ESPOSTA_DALL_API",
            "mese_circolazione":max(known),"circolante_mese_token":months[max(known)],
            "max_supply_token":cap,"unita":"TOKEN",
            "stime_mensili":estimates,"eventi":[],
            "stato_vesting":"NON_VERIFICATO","stato_vendita":"NON_ATTESTATA",
            "limite":"Stima mensile ufficiale di circolazione: non è un calendario unlock per allocazione né un fatto di vendita"}


def _monthly_valid(row, descriptor):
    if (not isinstance(row,dict) or not descriptor or descriptor.get("format")!=MONTHLY_FORMAT
            or row.get("fonte")!=descriptor["url"] or row.get("fonte_documentale")!=descriptor["homepage"]
            or row.get("eventi")!=[] or row.get("pubblicato_utc") is not None
            or row.get("stato_vesting")!="NON_VERIFICATO" or row.get("stato_vendita")!="NON_ATTESTATA"
            or row.get("max_supply_token")!=descriptor["max_supply_token"]
            or row.get("unita")!="TOKEN" or not _time(row.get("acquisito_utc"))):
        return False
    month=row.get("mese_circolazione")
    q=row.get("circolante_mese_token")
    points=row.get("stime_mensili")
    if (not isinstance(month,str) or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])",month)
            or type(q) not in (int,float) or not math.isfinite(q)
            or not 0<=q<=descriptor["max_supply_token"]
            or not isinstance(points,list) or not 1<=len(points)<=12):
        return False
    for x in points:
        if not isinstance(x,dict):
            return False
        p,v,d=x.get("mese"),x.get("circolante_proiettato_token"),x.get("aumento_previsto_token")
        if (not isinstance(p,str) or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])",p)
                or p<=month or type(v) not in (int,float) or not math.isfinite(v)
                or not q<=v<=descriptor["max_supply_token"]
                or type(d) not in (int,float) or not math.isfinite(d)
                or abs((v-q)-d)>1e-4
                or x.get("tipo")!="PROIEZIONE_NON_UNLOCK"
                or x.get("data_sblocco_utc") is not None or x.get("vendita")!="NON_ATTESTATA"):
            return False
        month,q=p,v
    return True


def _spot_status(now, items, asset_pairs, previous):
    """Read the already-fetched public Kraken AssetPairs, never a new API."""
    origin="https://api.kraken.com/0/public/AssetPairs"
    old={}
    if isinstance(previous,dict):
        for group in ("posizioni","candidati"):
            for row in (previous.get("stati_coppie_kraken") or {}).get(group,[]):
                if isinstance(row,dict):
                    old[(group,row.get("pair_key"),row.get("coppia"))]=row
    result={}
    for group in ("posizioni","candidati"):
        out=[]
        for i,row in enumerate(items.get(group,[])):
            ident=row.get("identita") or {}
            key,pair=ident.get("pair_key"),ident.get("coppia")
            entry={"indice":i,"token":row.get("token"),"pair_key":key,
                   "coppia":pair,"fonte":origin,"acquisito_utc":_iso(now),
                   "stato":"NON_ACQUISITO","status_kraken":None,"cambiamento":None,
                   "limite":"Lo stato di una coppia Kraken non è una notizia di delisting o prova di negoziabilità dell'account"}
            if isinstance(asset_pairs,dict) and asset_pairs and isinstance(key,str) and isinstance(pair,str):
                observed=asset_pairs.get(key)
                if observed is None:
                    entry["stato"]="COPPIA_NON_PRESENTE_NELLA_RISPOSTA"
                elif not isinstance(observed,dict) or observed.get("wsname")!=pair:
                    entry["stato"]="IDENTITA_COPPIA_INCOERENTE"
                elif isinstance(observed.get("status"),str) and re.fullmatch(r"[a-z_]{3,30}",observed["status"]):
                    entry.update(stato="OSSERVATO",status_kraken=observed["status"])
                    earlier=old.get((group,key,pair))
                    if (earlier and earlier.get("stato")=="OSSERVATO"
                            and isinstance(earlier.get("status_kraken"),str)
                            and earlier["status_kraken"]!=observed["status"]):
                        entry["cambiamento"]={"prima":earlier["status_kraken"],
                            "dopo":observed["status"],"acquisito_precedente_utc":earlier.get("acquisito_utc"),
                            "acquisito_corrente_utc":_iso(now),
                            "limite":"Transizione osservata, causa ed evento di listing/delisting non attestati"}
                else:
                    entry["stato"]="STATUS_NON_CONFORME"
            out.append(entry)
        result[group]=out
    return result


def _spot_status_read(raw, items, now):
    if not isinstance(raw,dict):
        raise ValueError("Kraken public status not structured")
    result={}
    for group in ("posizioni","candidati"):
        expected=items.get(group,[])
        rows=raw.get(group)
        if not isinstance(rows,list) or len(rows)!=len(expected):
            raise ValueError("Kraken pair roster mismatch")
        out=[]
        for i,(entry,row) in enumerate(zip(rows,expected)):
            ident=row.get("identita") or {}
            if (not isinstance(entry,dict) or entry.get("indice")!=i
                    or entry.get("token")!=row.get("token")
                    or entry.get("pair_key")!=ident.get("pair_key")
                    or entry.get("coppia")!=ident.get("coppia")
                    or entry.get("fonte")!="https://api.kraken.com/0/public/AssetPairs"):
                raise ValueError("Kraken pair attribution mismatch")
            observed=_time(entry.get("acquisito_utc"))
            if not observed or observed>now+dt.timedelta(minutes=2):
                raise ValueError("Kraken pair observation clock")
            status=entry.get("status_kraken")
            if entry.get("stato")=="OSSERVATO" and (
                    not isinstance(status,str) or not re.fullmatch(r"[a-z_]{3,30}",status)):
                raise ValueError("Kraken pair status forged")
            change=entry.get("cambiamento")
            if change is not None and (
                    not isinstance(change,dict) or entry.get("stato")!="OSSERVATO"
                    or change.get("dopo")!=status or change.get("prima")==status
                    or change.get("acquisito_corrente_utc")!=entry.get("acquisito_utc")
                    or not _time(change.get("acquisito_precedente_utc"))):
                raise ValueError("Kraken transition forged")
            out.append(dict(entry,stato_alla_lettura=(
                "SCADUTO" if entry.get("stato")=="OSSERVATO"
                and now-observed>dt.timedelta(minutes=45)
                else entry.get("stato"))))
        result[group]=out
    return result


def _prior(previous, now):
    if not isinstance(previous, dict) or previous.get("schema") != SCHEMA:
        return {}
    stamp = _time(previous.get("acquisito_utc"))
    if not stamp or stamp > now + dt.timedelta(minutes=2) or now - stamp > dt.timedelta(days=30):
        return {}
    return previous


def _supply_samples(roster, old, now):
    samples = {}
    for row in old.get("storico_supply", [])[:MAX_SAMPLES]:
        if not isinstance(row, dict):
            continue
        project = row.get("progetto_id")
        observed = _time(row.get("rilevato_utc"))
        if (project in roster and observed and now >= observed
                and now-observed <= dt.timedelta(days=30)
                and isinstance(row.get("offerta"), dict)):
            samples[(project, row.get("rilevato_utc"))] = row
    changes = []
    for project, desc in roster.items():
        fresh = next((r.get("fondamentali") for r in desc["rows"]
                      if isinstance(r.get("fondamentali"), dict)
                      and r["fondamentali"].get("stato") == "VERIFICATO"
                      and r["fondamentali"].get("origine") == "ACQUISIZIONE_PUBBLICA"
                      and r["fondamentali"].get("fonte") ==
                      "https://api.coingecko.com/api/v3/coins/" + project), None)
        if not fresh or not _time(fresh.get("rilevato_utc")):
            continue
        t = fresh["rilevato_utc"]
        keys = ("offerta_circolante", "offerta_totale", "offerta_massima")
        vals = {k: fresh.get(k) for k in keys}
        if (any(v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v < 0)
                for v in vals.values())):
            continue
        before = max((v for (p,old_t),v in samples.items() if p==project and
                      old_t != t and _time(old_t) < _time(t)),
                     key=lambda r:r["rilevato_utc"],default=None)
        if before:
            diff = {k:round(vals[k]-before["offerta"][k],9)
                    if vals[k] is not None and before["offerta"].get(k) is not None else None
                    for k in keys}
            changes.append({"progetto_id":project,"precedente_utc":before["rilevato_utc"],
                            "corrente_utc":t,"variazioni":diff,
                            "limite":"Cambiamenti supply riportati da aggregatore: non provano unlock, mint o vendita"})
        samples[(project,t)]={"progetto_id":project,"rilevato_utc":t,
                              "acquisito_utc":_iso(now),"offerta":vals,
                              "fonte":fresh["fonte"]}
    retained=sorted(samples.values(),key=lambda x:(x["rilevato_utc"],x["progetto_id"]),reverse=True)[:MAX_SAMPLES]
    return retained,changes[:30]


def collect(now, items, previous, fetch, *, network_allowed=True, asset_pairs=None, rpc_fetch=None):
    """One shared, reusable, bounded producer for all current asset identities."""
    now = _utc(now)
    roster = _roster(items)
    old = _prior(previous, now)
    # A project removed from wallet/scanner has no active row; cache may
    # be retained for a later re-entry but cannot be assigned to a different ID.
    old_governance={x["progetto_id"]:x for x in old.get("progetti",[])
                    if isinstance(x,dict) and x.get("progetto_id") in roster}
    eligible=[p for p in roster if _source_repo(roster[p]["source"])]
    cursor=old.get("prossimo_progetto")
    first=next((i for i,p in enumerate(eligible) if isinstance(cursor,str) and p>=cursor),0)
    selected=eligible[first:first+MAX_GOVERNANCE_CALLS] if network_allowed else []
    if network_allowed and len(selected)<min(MAX_GOVERNANCE_CALLS,len(eligible)):
        selected += eligible[:min(MAX_GOVERNANCE_CALLS,len(eligible))-len(selected)]
    next_project=(eligible[(first+len(selected))%len(eligible)] if eligible else None)
    projects=[]
    used=0
    # Keep a bounded public event ledger through intervening rotation cycles.
    event_history={}
    for old_event in old.get("storico_eventi",[])[:MAX_SAMPLES]:
        if not isinstance(old_event,dict):
            continue
        project=old_event.get("progetto_id")
        doc=old_event.get("documento_id")
        t=_time(old_event.get("acquisito_utc"))
        if (project in roster and _source_repo(roster[project]["source"])
                and isinstance(doc,str) and doc.isdecimal()
                and t and dt.timedelta(0)<=now-t<=dt.timedelta(days=30)):
            event_history[(project,doc,old_event.get("aggiornato_fonte_utc"))]=old_event
    for project,desc in roster.items():
        official_repo=_source_repo(desc["source"])
        previous_row=old_governance.get(project)
        entry={"progetto_id":project,"progetto":desc["progetto"],
               "token_riferimento":desc["token"],"repository_governance":official_repo,
               "stato":"SENZA_FONTE_PRIMARIA_ASSOCIATA" if not official_repo else "RINVIATO_BUDGET",
               "eventi":[],"confronto":[],"acquisito_utc":None,
               "limite":"Il solo ticker non attribuisce una notizia o decisione"}
        if official_repo and project in selected:
            used+=1
            url=GITHUB+official_repo+"/pulls?state=all&sort=updated&direction=desc&per_page=6"
            payload,error=_fetch(fetch,url)
            events=_governance(payload,official_repo,now) if not error else None
            if events is None:
                entry.update(stato="FONTE_NON_DISPONIBILE",errore=error or "RISPOSTA_INCOERENTE")
            else:
                old_events={e["id"]:e for e in (previous_row or {}).get("eventi",[])
                            if isinstance(e,dict) and isinstance(e.get("id"),str)}
                differences=[{"id":e["id"],"prima":old_events[e["id"]].get("stato_documento"),
                              "dopo":e["stato_documento"]}
                             for e in events if e["id"] in old_events
                             and (old_events[e["id"]].get("stato_documento")!=e["stato_documento"]
                                  or old_events[e["id"]].get("aggiornato_fonte_utc")!=e["aggiornato_fonte_utc"])]
                entry.update(stato="OSSERVATO",eventi=events,confronto=differences,
                             acquisito_utc=_iso(now))
                for ev in events:
                    event_history[(project,ev["id"],ev["aggiornato_fonte_utc"])]={
                        "progetto_id":project,"documento_id":ev["id"],
                        "fonte":ev["fonte"],"pubblicato_utc":ev["pubblicato_utc"],
                        "aggiornato_fonte_utc":ev["aggiornato_fonte_utc"],
                        "acquisito_utc":_iso(now),"stato_documento":ev["stato_documento"],
                        "stato_decisione_rete":"NON_ATTESTATO"}
        elif official_repo and previous_row and previous_row.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO"):
            t=_time(previous_row.get("acquisito_utc"))
            if t and now-t<=dt.timedelta(days=7):
                entry.update(stato="STORICO_NON_AGGIORNATO",
                             eventi=previous_row.get("eventi",[])[:6],
                             acquisito_utc=previous_row["acquisito_utc"])
        if not network_allowed and entry["stato"]=="RINVIATO_BUDGET":
            entry.update(stato="RINVIATO_RATE_LIMIT_HTTP_429",
                         limite="HTTP 429 upstream: nessuna richiesta supplementare")
        projects.append(entry)
    # KDD-18: one official on-chain inflation governor read per cycle,
    # only for projects explicitly bound to a catalogued primary RPC.
    emission_eligible=[p for p in roster if _emission_descriptor(roster[p]["source"])]
    old_emission={x["progetto_id"]:x for x in old.get("politiche_emissioni",[])
                  if isinstance(x,dict) and x.get("progetto_id") in roster}
    emission_cursor=old.get("prossima_emissione")
    emission_start=next((i for i,p in enumerate(emission_eligible)
                         if isinstance(emission_cursor,str) and p>=emission_cursor),0)
    emission_selected=(emission_eligible[emission_start:emission_start+MAX_EMISSION_CALLS]
                       if network_allowed and callable(rpc_fetch) else [])
    emission_next=(emission_eligible[(emission_start+len(emission_selected))%len(emission_eligible)]
                   if emission_eligible else None)
    emissions=[]
    for project in roster:
        bound=_emission_descriptor(roster[project]["source"])
        row={"progetto_id":project,
             "stato":"SENZA_FONTE_PRIMARIA_ASSOCIATA" if not bound else "RINVIATO_BUDGET",
             "fonte":bound,"valori":None,"acquisito_utc":None,
             "stato_unlock":"NON_ATTESTATO","vendita":"NON_ATTESTATA",
             "limite":"Parametri di emissione non attestano unlock o vendita"}
        if bound and project in emission_selected:
            used+=1
            try:
                response=rpc_fetch(SOLANA_RPC,{"jsonrpc":"2.0","id":1,
                    "method":"getInflationGovernor","params":[{"commitment":"finalized"}]})
                observed=_solana_governor(response,now)
            except Exception:
                observed=None
            if observed is None:
                row.update(stato="FONTE_NON_DISPONIBILE")
            else:
                row.update(observed)
                former=old_emission.get(project)
                if (former and former.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO")
                        and former.get("valori") is not None
                        and former.get("valori")!=observed["valori"]):
                    row["confronto"]={"precedente_utc":former.get("acquisito_utc"),
                                     "cambiati":[k for k in observed["valori"]
                                                if (former.get("valori") or {}).get(k)!=observed["valori"][k]],
                                     "limite":"Variazione parametri policy: non prova emissione osservata o vendita"}
        elif bound:
            former=old_emission.get(project)
            if former and former.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO"):
                t=_time(former.get("acquisito_utc"))
                if t and dt.timedelta(0)<=now-t<=dt.timedelta(days=14):
                    row.update(former,stato="STORICO_NON_AGGIORNATO")
            if not network_allowed and row["stato"]=="RINVIATO_BUDGET":
                row["stato"]="RINVIATO_RATE_LIMIT_HTTP_429"
        emissions.append(row)
    # KDD-20: independent capped rotation of repository security advisories.
    # PR #66 acquires issue labels, not published GHSA alerts; no duplication.
    security_eligible=[p for p in roster if _security_repo(roster[p]["source"])]
    prior_security={e["progetto_id"]:e for e in old.get("avvisi_repository",[])
                    if isinstance(e,dict) and e.get("progetto_id") in roster}
    next_s=old.get("prossimo_security")
    start_s=next((i for i,p in enumerate(security_eligible)
                  if isinstance(next_s,str) and p>=next_s),0)
    chosen_s=(security_eligible[start_s:start_s+1] if network_allowed else [])
    sec_cursor=(security_eligible[(start_s+len(chosen_s))%len(security_eligible)]
                if security_eligible else None)
    advisories=[]
    for project in roster:
        r=_security_repo(roster[project]["source"])
        row={"progetto_id":project,"repository_sicurezza":r,"stato":
             "SENZA_REPOSITORY" if r is None else "RINVIATO_BUDGET",
             "acquisito_utc":None,"avvisi":[],"limite":"Campione vuoto non equivale a sicurezza provata"}
        if r and project in chosen_s:
            used+=1
            result,err=_fetch(fetch,GITHUB+r+"/security-advisories?per_page=5")
            parsed=_security_events(result,r,now) if not err else None
            if parsed is None:
                row.update(stato="FONTE_NON_DISPONIBILE",errore=err or "RISPOSTA_NON_CONFORME")
            else:
                row.update(stato="OSSERVATO" if parsed else "NESSUN_AVVISO_NEL_CAMPIONE",
                           acquisito_utc=_iso(now),avvisi=parsed)
        elif r:
            previous=prior_security.get(project)
            if previous and previous.get("stato") in (
                    "OSSERVATO","STORICO","NESSUN_AVVISO_NEL_CAMPIONE"):
                observed=_time(previous.get("acquisito_utc"))
                if observed and dt.timedelta(0)<=now-observed<=dt.timedelta(days=14):
                    row.update(stato="STORICO",acquisito_utc=previous["acquisito_utc"],
                               avvisi=previous.get("avvisi",[])[:5])
            if not network_allowed and row["stato"]=="RINVIATO_BUDGET":
                row["stato"]="RINVIATO_RATE_LIMIT_HTTP_429"
        advisories.append(row)
    # ECB source rotation is independent from project and wallet membership.
    series=MACRO_SERIES
    past_macro={x["id"]:x for x in old.get("indicatori_macro",[])
                if isinstance(x,dict) and x.get("id") in [s[0] for s in series]}
    macro_cursor=old.get("prossimo_indicatore")
    pick=next((i for i,s in enumerate(series) if s[0]==macro_cursor),0)
    spec=series[pick]
    url=_series_url(spec)
    if network_allowed:
        used+=1
        raw,error=_fetch(fetch,url,json_data=False)
        current=_ecb_csv(raw,spec,now) if not error else None
    else:
        error="RINVIATO_RATE_LIMIT_HTTP_429"
        current=None
    if current is None:
        current={"id":spec[0],"serie":spec[1]+"."+spec[2],"fonte":url,
                 "stato":"FONTE_NON_DISPONIBILE","motivo":error or "CSV_INCOERENTE",
                 "acquisito_utc":_iso(now),"valore":None,"unita":spec[3],
                 "limite":"Dato non acquisito, mai assimilare a zero"}
    macro=[]
    for s in series:
        if s[0]==spec[0]:
            macro.append(current)
        elif s[0] in past_macro:
            retained=dict(past_macro[s[0]])
            if retained.get("valore") is not None:
                retained["stato"]="STORICO_NON_AGGIORNATO"
            # A previous budget deferral was NEVER a provider failure.
            elif retained.get("stato") not in ("RINVIATO_BUDGET","RINVIATO_RATE_LIMIT_HTTP_429"):
                retained["stato"]="FONTE_NON_DISPONIBILE"
            macro.append(retained)
        else:
            macro.append({"id":s[0],"serie":s[1]+"."+s[2],"fonte":_series_url(s),
                          "stato":"RINVIATO_BUDGET","valore":None,"unita":s[3]})
    # Optional primary machine-readable schedule, only when explicitly bound
    # in catalog data; never reconstruct a calendar from FDV or CoinGecko supply.
    schedules=[]
    schedule_candidates=[p for p in roster if _schedule_descriptor(roster[p]["source"])]
    sch_cursor=old.get("prossimo_schedule")
    sch_first=next((i for i,p in enumerate(schedule_candidates)
                    if isinstance(sch_cursor,str) and p>=sch_cursor),0)
    sch_selected=schedule_candidates[sch_first:sch_first+MAX_SCHEDULE_CALLS] if network_allowed else []
    sch_next=(schedule_candidates[(sch_first+len(sch_selected))%len(schedule_candidates)]
              if schedule_candidates else None)
    previous_schedules={x["progetto_id"]:x for x in old.get("calendari",[])
                        if isinstance(x,dict) and x.get("progetto_id") in roster}
    for project in roster:
        descriptor=_schedule_descriptor(roster[project]["source"])
        row={"progetto_id":project,"stato":"SENZA_CALENDARIO_PRIMARIO",
             "fonte":None,"eventi":[],"limite":"Supply e FDV non sono un calendario unlock"}
        if descriptor and project in sch_selected:
            used+=1
            if descriptor.get("format")==MONTHLY_FORMAT:
                url=descriptor["url"]
                raw,error=_fetch(fetch,url)
                result=_official_monthly(raw,project,descriptor,now) if not error else None
            else:
                url=("https://raw.githubusercontent.com/"+descriptor["repository"]+"/"+
                     quote(descriptor["ref"],safe="")+"/"+descriptor["path"])
                raw,error=_fetch(fetch,url)
                result=_official_schedule(raw,project,url,now) if not error else None
            if result:
                row.update(result)
            else:
                row.update(stato="FONTE_NON_DISPONIBILE",fonte=url,
                           motivo=error or "SCHEDULE_NON_ATTESTATO")
        elif descriptor:
            history=previous_schedules.get(project)
            if history and history.get("stato") in (
                    "DOCUMENTO_PRIMARIO_CON_SCHEDULE","STORICO_DA_RICONFERMARE",
                    "PROIEZIONE_PRIMARIA_NON_UNLOCK","PROIEZIONE_STORICA"):
                row.update(history,stato=("PROIEZIONE_STORICA"
                           if history.get("stato") in ("PROIEZIONE_PRIMARIA_NON_UNLOCK","PROIEZIONE_STORICA")
                           else "STORICO_DA_RICONFERMARE"))
            else:
                row.update(stato="RINVIATO_RATE_LIMIT_HTTP_429" if not network_allowed
                           else "RINVIATO_BUDGET")
        schedules.append(row)
    # Compare the attributable planned monthly figures, without calling them unlocks.
    changes_calendar=[]
    for row in schedules:
        former=previous_schedules.get(row["progetto_id"])
        if (former and row.get("stato") in ("PROIEZIONE_PRIMARIA_NON_UNLOCK","DOCUMENTO_PRIMARIO_CON_SCHEDULE")
                and former.get("fonte")==row.get("fonte")
                and (former.get("stime_mensili")!=row.get("stime_mensili")
                     or former.get("eventi")!=row.get("eventi"))):
            changes_calendar.append({"progetto_id":row["progetto_id"],
                "fonte":row.get("fonte"),"stato":"REVISIONE_PIANO_PUBBLICATO",
                "acquisizione_precedente_utc":former.get("acquisito_utc"),
                "acquisizione_corrente_utc":row.get("acquisito_utc"),
                "limite":"Revisione del documento, non prova sblocco o vendita"})
    history,changes=_supply_samples(roster,old,now)
    retained_events=sorted(event_history.values(),key=lambda r:(r["acquisito_utc"],r["progetto_id"],r["documento_id"]),reverse=True)[:MAX_SAMPLES]
    kraken_status=_spot_status(now,items,asset_pairs,old)
    return {"schema":SCHEMA,"acquisito_utc":_iso(now),"progetti":projects,
            "stati_coppie_kraken":kraken_status,
            "avvisi_repository":advisories,"prossimo_security":sec_cursor,
            "politiche_emissioni":emissions,"prossima_emissione":emission_next,
            "indicatori_macro":macro,"calendari":schedules,
            "revisioni_piani":changes_calendar,
            "storico_supply":history,"variazioni_supply":changes,
            "storico_eventi":retained_events,
            "prossimo_progetto":next_project,
            "prossimo_indicatore":series[(pick+(1 if network_allowed else 0))%len(series)][0],
            "prossimo_schedule":sch_next,
            "richieste_pubbliche":used,"limite_richieste":MAX_GOVERNANCE_CALLS+MAX_MACRO_CALLS+MAX_SCHEDULE_CALLS+MAX_SECURITY_CALLS+MAX_EMISSION_CALLS,
            "limite":"Campioni pubblici: proposal != approvazione; unlock != circolazione != vendita; nessuna direzione di mercato inferita"}


def at_read(raw, items, now):
    """Validate current roster and primary URLs, recalculate age, never refresh."""
    now=_utc(now)
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA:
        raise ValueError("Primary economics schema")
    acquired=_time(raw.get("acquisito_utc"))
    if not acquired or acquired>now+dt.timedelta(minutes=2):
        raise ValueError("Primary economics clock")
    roster=_roster(items)
    projects=raw.get("progetti")
    schedules=raw.get("calendari")
    if not isinstance(projects,list) or not isinstance(schedules,list):
        raise ValueError("Primary economics absent roster")
    if [r.get("progetto_id") for r in projects if isinstance(r,dict)] != list(roster):
        raise ValueError("Primary economics identity mismatch")
    if [r.get("progetto_id") for r in schedules if isinstance(r,dict)] != list(roster):
        raise ValueError("Primary schedule identity mismatch")
    if type(raw.get("richieste_pubbliche")) is not int or not 0<=raw["richieste_pubbliche"]<=6:
        raise ValueError("Primary economics budget")
    retained=raw.get("storico_eventi",[])
    if not isinstance(retained,list) or len(retained)>MAX_SAMPLES:
        raise ValueError("Public event history bound")
    for old_event in retained:
        if not isinstance(old_event,dict) or old_event.get("progetto_id") not in roster:
            raise ValueError("Public event history project")
        project=old_event["progetto_id"]
        repo=_source_repo(roster[project]["source"])
        if (not repo or not isinstance(old_event.get("documento_id"),str)
                or not old_event["documento_id"].isdecimal()
                or old_event.get("fonte")!="https://github.com/"+repo+"/pull/"+old_event["documento_id"]
                or not _time(old_event.get("acquisito_utc"))
                or old_event.get("stato_decisione_rete")!="NON_ATTESTATO"):
            raise ValueError("Public event history attribution")
    verified_emissions=[]
    source_emissions=raw.get("politiche_emissioni")
    if source_emissions is not None:
        if (not isinstance(source_emissions,list) or len(source_emissions)!=len(roster)
                or [r.get("progetto_id") for r in source_emissions if isinstance(r,dict)]!=list(roster)):
            raise ValueError("Primary issuance roster mismatch")
        for row in source_emissions:
            project=row["progetto_id"]
            expected=_emission_descriptor(roster[project]["source"])
            if row.get("fonte")!=expected:
                raise ValueError("Primary inflation source forged")
            copy=dict(row)
            if row.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO"):
                moment=_time(row.get("acquisito_utc"))
                keys=("initial","taper","terminal","foundation","foundationTerm")
                values=row.get("valori")
                if (expected!=SOLANA_RPC or not moment or moment>now+dt.timedelta(minutes=2)
                        or not isinstance(values,dict)
                        or any(type(values.get(k)) not in (int,float) or not math.isfinite(values[k])
                               or values[k]<0 for k in keys)
                        or any(values[k]>1 for k in keys[:4]) or values["foundationTerm"]>1000
                        or row.get("stato_unlock")!="NON_ATTESTATO"
                        or row.get("vendita")!="NON_ATTESTATA"):
                    raise ValueError("Primary inflation numeric or claim forged")
                copy["stato_alla_lettura"]=(
                    "SCADUTO" if now-moment>dt.timedelta(days=14) else row["stato"])
            verified_emissions.append(copy)
    verified_advisories=[]
    raw_advisories=raw.get("avvisi_repository")
    if raw_advisories is not None:
        if (not isinstance(raw_advisories,list) or len(raw_advisories)!=len(roster)
                or [r.get("progetto_id") for r in raw_advisories if isinstance(r,dict)] != list(roster)):
            raise ValueError("Security roster mismatch")
        for row in raw_advisories:
            project=row["progetto_id"]
            repo=_security_repo(roster[project]["source"])
            if row.get("repository_sicurezza")!=repo: raise ValueError("Security repository forged")
            item=dict(row)
            if row.get("stato") in ("OSSERVATO","NESSUN_AVVISO_NEL_CAMPIONE","STORICO"):
                t=_time(row.get("acquisito_utc"))
                if not repo or t is None or t>now+dt.timedelta(minutes=2):
                    raise ValueError("Security observation time")
                alerts=row.get("avvisi")
                if not isinstance(alerts,list) or len(alerts)>5: raise ValueError("Advisory cardinality")
                for a in alerts:
                    if (not isinstance(a,dict) or
                            a.get("impatto_sul_token")!="NON_ATTESTATO" or
                            a.get("tipo")!="AVVISO_REPOSITORY" or
                            a.get("emittente")!=repo):
                        raise ValueError("Security impact or issuer forged")
                    expected="https://github.com/"+repo+"/security/advisories/"+str(a.get("id"))
                    if (a.get("fonte")!=expected or _time(a.get("pubblicato_utc")) is None):
                        raise ValueError("Security advisory attribution")
                item["stato_alla_lettura"]=(
                    "SCADUTO" if now-t>dt.timedelta(days=14) else row["stato"])
            verified_advisories.append(item)
    read_projects=[]
    for row in projects:
        repo=_source_repo(roster[row["progetto_id"]]["source"])
        if row.get("repository_governance") != repo:
            raise ValueError("Primary governance attribution")
        new=dict(row)
        if row.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO"):
            t=_time(row.get("acquisito_utc"))
            if not repo or not t or t>now+dt.timedelta(minutes=2):
                raise ValueError("Primary governance time")
            for event in row.get("eventi",[]):
                if (not isinstance(event,dict) or event.get("emittente")!=repo
                        or not isinstance(event.get("id"),str)
                        or event.get("fonte") != "https://github.com/"+repo+"/pull/"+event["id"]
                        or not _time(event.get("pubblicato_utc"))
                        or event.get("stato_decisione_rete")!="NON_ATTESTATO"):
                    raise ValueError("Primary governance event forged")
            new["stato"]=(row["stato"] if now-t<=dt.timedelta(days=7)
                          else "SCADUTO")
        read_projects.append(new)
    read_schedules=[]
    for row in schedules:
        p=row["progetto_id"]
        expected=_schedule_descriptor(roster[p]["source"])
        new=dict(row)
        if row.get("stato") in ("PROIEZIONE_PRIMARIA_NON_UNLOCK","PROIEZIONE_STORICA"):
            if not _monthly_valid(row,expected):
                raise ValueError("Primary monthly circulation evidence forged")
            observed=_time(row.get("acquisito_utc"))
            new["stato"]=("PROIEZIONE_PRIMARIA_NON_UNLOCK"
                          if row["stato"]=="PROIEZIONE_PRIMARIA_NON_UNLOCK"
                          and observed and dt.timedelta(0)<=now-observed<=dt.timedelta(days=35)
                          else "PROIEZIONE_STORICA")
        if row.get("stato") in ("DOCUMENTO_PRIMARIO_CON_SCHEDULE","STORICO_DA_RICONFERMARE"):
            if not expected or expected.get("format")!="repository-json-v001" or not isinstance(row.get("fonte"),str):
                raise ValueError("Primary calendar unbound")
            prefix=("https://raw.githubusercontent.com/"+expected["repository"]+"/"+
                    quote(expected["ref"],safe="")+"/"+expected["path"])
            if row["fonte"]!=prefix or not _time(row.get("pubblicato_utc")):
                raise ValueError("Primary calendar source mismatch")
            if not _official_schedule({"schema":ECON_SCHEDULE_SCHEMA,"progetto_id":p,
                                       "unita":"TOKEN","pubblicato_utc":row["pubblicato_utc"],
                                       "eventi":[{"tipo":"UNLOCK_PROGRAMMATO","evento_utc":e.get("evento_utc"),
                                                  "quantita_token":e.get("quantita_token"),
                                                  "allocazione":e.get("allocazione")} for e in row.get("eventi",[])]},
                                      p,row["fonte"],now):
                raise ValueError("Primary calendar values invalid")
            t=_time(row.get("pubblicato_utc"))
            new["stato"]=("DOCUMENTO_PRIMARIO_CON_SCHEDULE"
                          if row["stato"]=="DOCUMENTO_PRIMARIO_CON_SCHEDULE"
                          and now-t<=dt.timedelta(days=90) else "STORICO_DA_RICONFERMARE")
        read_schedules.append(new)
    indicators=[]
    for row in raw.get("indicatori_macro",[]):
        if not isinstance(row,dict):
            raise ValueError("Invalid ECB row")
        matches=[s for s in MACRO_SERIES if s[0]==row.get("id")]
        if len(matches)!=1 or row.get("fonte")!=_series_url(matches[0]):
            raise ValueError("ECB series forged")
        new=dict(row)
        if row.get("valore") is not None:
            day=_time(str(row.get("periodo"))+"-01T00:00:00+00:00"
                      if len(str(row.get("periodo")))==7
                      else str(row.get("periodo"))+"T00:00:00+00:00")
            if (day is None or day>now+dt.timedelta(days=1)
                    or type(row["valore"]) not in (int,float) or not math.isfinite(row["valore"])):
                raise ValueError("ECB observation invalid")
            age=(now.date()-day.date()).days
            new["stato"]=(row.get("stato") if age<=matches[0][4]
                          and row.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO")
                          else "SCADUTO")
        indicators.append(new)
    pairs_read=(_spot_status_read(raw["stati_coppie_kraken"],items,now)
                if "stati_coppie_kraken" in raw else None)
    # Keep original, independently validated source budget and history: this
    # reader is called by both packet build and GPT bridge (idempotent).
    return dict(raw,letto_utc=_iso(now),progetti=read_projects,
            stati_coppie_kraken=pairs_read,
            avvisi_repository=verified_advisories if raw_advisories is not None else None,
            politiche_emissioni=verified_emissions if source_emissions is not None else None,
            indicatori_macro=indicators,calendari=read_schedules,
            variazioni_supply=raw.get("variazioni_supply",[])[:30],
            copertura={"progetti":len(projects),"governance_osservati":sum(p["stato"]=="OSSERVATO" for p in read_projects),
                        "indicatori_macro_osservati":sum(m["stato"]=="OSSERVATO" for m in indicators),
                        "calendari_primari_attuali":sum(s["stato"]=="DOCUMENTO_PRIMARIO_CON_SCHEDULE" for s in read_schedules),
                        "security_repository_osservati":sum(a.get("stato_alla_lettura") in ("OSSERVATO","NESSUN_AVVISO_NEL_CAMPIONE") for a in verified_advisories),
                        "politiche_emissioni_osservate":sum(e.get("stato_alla_lettura")=="OSSERVATO" for e in verified_emissions)},
            limite=raw.get("limite"))
