"""KDD-18/20/21: primary-source observations inside the existing economic dossier.

Only public, bounded GETs. Source associations are project-specific catalog DATA,
not ticker searches. Collection and read-time validation have separate contracts.
No source here proves an unlock was sold, a proposal adopted, or a market move caused.
"""
from __future__ import annotations

import csv
import calendar
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
MAX_ISSUE_CALLS = 1
# Kraken REST AssetPairs documented market states, not an arbitrary label
# or a token listing/delisting announcement.
KRAKEN_PAIR_STATES = frozenset((
    "online", "cancel_only", "post_only", "limit_only", "reduce_only",
    "maintenance"))
MAX_EMISSION_CALLS = 1
MAX_SAMPLES = 96
ECON_SCHEDULE_SCHEMA = "kdd-official-token-schedule-v001"
SUI_CIRCULATION = "https://sui-circulation.suiexplorer.com/api/sui_circulation"
SUI_SCHEDULE_HOME = "https://www.sui.io/token-schedule"
SOLANA_RPC = "https://api.mainnet.solana.com"
SOLANA_GOVERNOR_DOC = "https://solana.com/docs/rpc/http/getinflationgovernor"
MONTHLY_FORMAT = "official-monthly-circulation-v001"
ARB_VESTING_FORMAT = "arbitrum-primary-vesting-mdx-v001"
ARB_VESTING_REPO = "ArbitrumFoundation/docs"
ARB_VESTING_PATH = "content/docs/airdrop-eligibility-distribution.mdx"
ARB_VESTING_URL = ("https://raw.githubusercontent.com/"+ARB_VESTING_REPO+
                   "/main/"+ARB_VESTING_PATH)
ARB_VESTING_HOME = "https://docs.arbitrum.foundation/airdrop-eligibility-distribution"
MACRO_SERIES = (
    ("USD_EUR", "EXR", "D.USD.EUR.SP00.A", "USD per EUR", 8),
    ("EA_HICP", "HICP", "M.U2.N.000000.4D0.ANR", "variazione percentuale a/a", 65),
    ("ECB_DEPOSIT_RATE", "FM", "D.U2.EUR.4F.KR.DFR.LEV", "percentuale annua", 8),
    ("ECB_MAIN_REFI_RATE", "FM", "D.U2.EUR.4F.KR.MRR_FR.LEV", "percentuale annua", 8),
    ("EA_M3_GROWTH", "BSI", "M.U2.Y.V.M30.X.I.U2.2300.Z01.A", "variazione percentuale a/a", 65),
    ("CFTC_BTC_TFF", "CFTC", "BTC_CME_133741", "contratti futures CME Bitcoin (5 BTC/contratto)", 21),
)
ISSUE_LABELS = {"governance","security","tokenomics","protocol","upgrade",
                "migration","breaking-change","deprecation"}
GITHUB = "https://api.github.com/repos/"
ECB = "https://data-api.ecb.europa.eu/service/data/"
CFTC_BTC_TFF_URL = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"
CFTC_BTC_CONTRACT = "BITCOIN - CHICAGO MERCANTILE EXCHANGE"
CFTC_BTC_MARKET_CODE = "133741"
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
    for group in ("posizioni", "candidati", "richiesti"):
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


def _issue_repo(descriptor):
    repo=descriptor.get("repository") if isinstance(descriptor,dict) else None
    return repo if isinstance(repo,str) and REPO.fullmatch(repo) else None


def _labelled_issues(payload, repo, now):
    """Project/client repository issues are notices, not confirmed upgrades."""
    if not isinstance(payload,list) or len(payload)>30: return None
    out=[]
    for raw in payload[:12]:
        if not isinstance(raw,dict): return None
        if "pull_request" in raw: continue
        num=raw.get("number")
        created=_time(raw.get("created_at"))
        updated=_time(raw.get("updated_at"))
        expected="https://github.com/"+repo+"/issues/"+str(num)
        if (type(num) is not int or num<=0 or raw.get("html_url")!=expected
                or not created or created>now+dt.timedelta(minutes=2)
                or not updated or updated<created):
            return None
        labels=raw.get("labels") or []
        if not isinstance(labels,list): return None
        matches=sorted({tag["name"].lower() for tag in labels
                        if isinstance(tag,dict) and isinstance(tag.get("name"),str)}
                        & ISSUE_LABELS)
        if not matches: continue
        title=raw.get("title")
        if not isinstance(title,str) or not title.strip(): return None
        out.append({"id":str(num),"tipo":"ISSUE_ETICHETTATA_REPOSITORY",
                    "emittente":repo,"fonte":expected,
                    "titolo":title.strip()[:220],"categorie":matches,
                    "pubblicato_utc":_iso(created),"aggiornato_fonte_utc":_iso(updated),
                    "evento_utc":None,"stato":"PUBBLICATO_DA_VERIFICARE",
                    "esito_proposta":"NON_ATTESTATO",
                    "limite":"Issue ufficiale: etichetta non attesta delibera, exploit riuscito, upgrade attivato o conseguenze sul prezzo"})
    return out[:8]


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
    if (raw.get("format") == ARB_VESTING_FORMAT
            and raw.get("repository")==ARB_VESTING_REPO
            and raw.get("path")==ARB_VESTING_PATH
            and raw.get("ref")=="main"
            and raw.get("homepage")==ARB_VESTING_HOME):
        return dict(raw)
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
    if flow=="CFTC" and key=="BTC_CME_133741":
        return CFTC_BTC_TFF_URL
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
            if len(period)==7:
                year,month=map(int,period.split("-"))
                day=dt.date(year,month,calendar.monthrange(year,month)[1])
            else:
                day=dt.date.fromisoformat(period)
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


def _cftc_btc_tff(raw, spec, now):
    """CFTC official Friday TFF Futures-only flat file: one EXACT CME BTC contract.

    CFTC trader classes are reportable FUTURES contracts, never identifiable
    firms, ETF creations, on-chain transfers or spot institutional cash flow.
    """
    if spec[0]!="CFTC_BTC_TFF" or not isinstance(raw,str) or len(raw)>950000:
        return None
    try:
        rows=list(csv.reader(io.StringIO(raw)))
    except (ValueError,csv.Error):
        return None
    if not 1<=len(rows)<=300:
        return None
    target=[r for r in rows if len(r)>90 and r[0].strip()==CFTC_BTC_CONTRACT
            and r[3].strip()==CFTC_BTC_MARKET_CODE
            and r[5].strip()=="00" and r[-1].strip()=="FutOnly"]
    if len(target)!=1:
        return None
    r=target[0]
    try:
        date=dt.date.fromisoformat(r[2].strip())
        if date>now.date()+dt.timedelta(days=1):
            return None
        # Source column layout is TFF Futures Only (not the combined report).
        indices={"dealer":(8,9),"asset_manager":(11,12),
                 "leveraged_money":(14,15),"other_reportable":(17,18),
                 "nonreportable":(22,23)}
        vals={}
        for role,(left,right) in indices.items():
            a,b=int(r[left].strip()),int(r[right].strip())
            if not 0<=a<=1000000000 or not 0<=b<=1000000000:
                return None
            vals[role]={"long_contratti":a,"short_contratti":b,
                        "saldo_long_meno_short":a-b}
        interest=int(r[7].strip())
        if not 0<interest<1000000000:
            return None
    except (ValueError,IndexError,TypeError):
        return None
    return {"id":spec[0],"serie":"CFTC.BTC_CME_133741",
            "fonte":CFTC_BTC_TFF_URL,"mercato":CFTC_BTC_CONTRACT,
            "codice_contratto":CFTC_BTC_MARKET_CODE,
            "contratto_nominale":"5 BTC",
            "periodo":date.isoformat(),"valore":interest,
            "classificazioni":vals,"unita":spec[3],
            "acquisito_utc":_iso(now),
            "pubblicato_utc":None,
            "stato_pubblicazione":"DATA_RAPPORTO_NON_DATA_PUBBLICAZIONE",
            "stato":"OSSERVATO" if (now.date()-date).days<=spec[4] else "SCADUTO",
            "limite":"CFTC TFF futures only: posizioni riportate per classe alla data martedì; non operatori nominati, flussi spot, acquisti istituzionali o segnali direzionali"}


def _cftc_read_valid(row):
    if row.get("id")!="CFTC_BTC_TFF" or row.get("fonte")!=CFTC_BTC_TFF_URL:
        return False
    if (row.get("mercato")!=CFTC_BTC_CONTRACT
            or row.get("codice_contratto")!=CFTC_BTC_MARKET_CODE
            or row.get("contratto_nominale")!="5 BTC"
            or row.get("stato_pubblicazione")!="DATA_RAPPORTO_NON_DATA_PUBBLICAZIONE"
            or row.get("pubblicato_utc") is not None):
        return False
    v=row.get("valore")
    if type(v) is not int or not 0<v<1000000000:
        return False
    roles=("dealer","asset_manager","leveraged_money","other_reportable","nonreportable")
    groups=row.get("classificazioni")
    if not isinstance(groups,dict) or set(groups)!=set(roles):
        return False
    for role in roles:
        rec=groups[role]
        if not isinstance(rec,dict) or set(rec)!=set(("long_contratti","short_contratti","saldo_long_meno_short")):
            return False
        a,b,net=rec["long_contratti"],rec["short_contratti"],rec["saldo_long_meno_short"]
        if any(type(x) is not int or abs(x)>1000000000 for x in (a,b,net)):
            return False
        if a<0 or b<0 or a-b!=net:
            return False
    return True


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



def _arb_vesting_document(raw, project_id, descriptor, now):
    """Read the *real* project-owned primary MDX, not a fictitious JSON feed.

    A monthly vesting rule is evidenced, but no exact future unlock day,
    allocation amount, transfer, exchange inflow or sale can be deduced.
    """
    if (project_id!="arbitrum" or descriptor.get("format")!=ARB_VESTING_FORMAT
            or not isinstance(raw,str) or len(raw)>150000):
        return None
    normalized=re.sub(r"\s+"," ",raw).lower()
    if (not re.search(
            r"all investor and team tokens are subject to 4 year lockups,"
            r".*?first unlocks happening one year after the"
            r".*?token generation event \(3/16/2023\)"
            r".*?then monthly unlocks for the remaining three years",
            normalized)
            or not re.search(
                r"arbitrum foundation's allocation is subject to a lockup"
                r".*?began on 4/17/2023"
                r".*?linearly unlocks over the course of four years",
                normalized)):
        return None
    # Months, not event timestamps; the text does not identify the exact
    # monthly day or tranche amounts. Limit to the next 8 month periods.
    months=[]
    for offset in range(8):
        month0=now.year*12+now.month-1+offset
        y,m=divmod(month0,12)
        label=f"{y:04d}-{m+1:02d}"
        if "2024-03"<=label<="2027-03":
            months.append(label)
    return {"progetto_id":project_id,
            "stato":"DOCUMENTO_PRIMARIO_REGOLA_VESTING",
            "fonte":ARB_VESTING_URL,"fonte_documentale":ARB_VESTING_HOME,
            "acquisito_utc":_iso(now),"pubblicato_utc":None,
            "data_pubblicazione":"NON_ESPOSTA_DALLA_FONTE_MDX",
            "tipo":"REGOLA_VESTING_MENSILE",
            "beneficiari":["TEAM_E_INVESTITORI","ARBITRUM_FOUNDATION"],
            "regole":[{"gruppo":"TEAM_E_INVESTITORI",
                       "evento_originale":"2023-03-16",
                       "prima_finestra_mese":"2024-03",
                       "ultima_finestra_mese":"2027-03",
                       "frequenza":"MENSILE_DA_DOCUMENTO",
                       "quantita_token":None},
                      {"gruppo":"ARBITRUM_FOUNDATION",
                       "inizio_utc_data":"2023-04-17",
                       "durata_anni":4,
                       "frequenza":"LINEARE_SENZA_EVENTI_DATATI",
                       "quantita_token":None}],
            "periodi_mensili_derivati":months,
            "eventi":[],"unita":"TOKEN","stato_sblocco_effettivo":"NON_ATTESTATO",
            "stato_vendita":"NON_ATTESTATA",
            "limite":"Acquisizione MDX ufficiale: vesting come REGOLA, senza giorni, quantità per scadenza o vendita. Finestra mensile derivata dichiarata, non singoli unlock osservati"}


def _arb_vesting_valid(row, descriptor):
    if (not descriptor or descriptor.get("format")!=ARB_VESTING_FORMAT
            or row.get("progetto_id")!="arbitrum"
            or row.get("fonte")!=ARB_VESTING_URL
            or row.get("fonte_documentale")!=ARB_VESTING_HOME
            or row.get("pubblicato_utc") is not None
            or row.get("data_pubblicazione")!="NON_ESPOSTA_DALLA_FONTE_MDX"
            or row.get("tipo")!="REGOLA_VESTING_MENSILE"
            or row.get("unita")!="TOKEN"
            or row.get("eventi")!=[]
            or row.get("stato_sblocco_effettivo")!="NON_ATTESTATO"
            or row.get("stato_vendita")!="NON_ATTESTATA"):
        return False
    t=_time(row.get("acquisito_utc"))
    if not t:
        return False
    # Reconstruct all constant fields from the verified text contract at its
    # acquisition time. A packet cannot insert an invented day or quantity.
    expected=_arb_vesting_document(
        "all investor and team tokens are subject to 4 year lockups, "
        "with the first unlocks happening one year after the token generation event (3/16/2023) "
        "and then monthly unlocks for the remaining three years. "
        "the arbitrum foundation's allocation is subject to a lockup that began on 4/17/2023 "
        "and linearly unlocks over the course of four years.",
        "arbitrum",descriptor,t)
    return bool(expected and all(row.get(k)==expected[k] for k in (
        "beneficiari","regole","periodi_mensili_derivati")))


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
        for group in ("posizioni","candidati","richiesti"):
            for row in (previous.get("stati_coppie_kraken") or {}).get(group,[]):
                if isinstance(row,dict):
                    old[(group,row.get("pair_key"),row.get("coppia"))]=row
    result={}
    for group in ("posizioni","candidati","richiesti"):
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
                elif observed.get("status") in KRAKEN_PAIR_STATES:
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
    for group in ("posizioni","candidati","richiesti"):
        expected=items.get(group,[])
        rows=raw.get(group,[] if not expected else None)
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
                    status not in KRAKEN_PAIR_STATES):
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


def collect(now, items, previous, fetch, *, network_allowed=True, asset_pairs=None, rpc_fetch=None, collect_project_issues=False, skipped_reason="RATE_LIMIT"):
    """One shared, reusable, bounded producer for all current asset identities."""
    now = _utc(now)
    roster = _roster(items)
    old = _prior(previous, now)
    paused=("NON_ACQUISITO_FUORI_REFRESH" if skipped_reason=="FUORI_REFRESH"
            else "RINVIATO_RATE_LIMIT_HTTP_429")
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
            entry.update(stato=paused,
                         limite=("Sorgenti non richieste fuori dal refresh KDD"
                                 if paused=="NON_ACQUISITO_FUORI_REFRESH"
                                 else "HTTP 429 upstream: nessuna richiesta supplementare"))
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
                row["stato"]=paused
        emissions.append(row)
    # KDD-20: labelled technical issues from the project's registered
    # repository. Distinct from GHSA advisories and documentation PRs.
    issue_projects=[key for key in roster if _issue_repo(roster[key]["source"])]
    past_issues={x["progetto_id"]:x for x in old.get("segnalazioni_repo",[])
                 if isinstance(x,dict) and x.get("progetto_id") in roster}
    old_issue_cursor=old.get("prossima_issue")
    issue_start=next((i for i,project in enumerate(issue_projects)
                      if isinstance(old_issue_cursor,str) and project>=old_issue_cursor),0)
    issue_selected=(issue_projects[issue_start:issue_start+MAX_ISSUE_CALLS]
                    if network_allowed and collect_project_issues else [])
    next_issue=(issue_projects[(issue_start+len(issue_selected))%len(issue_projects)]
                if issue_projects else None)
    issues=[]
    for project in roster:
        repo=_issue_repo(roster[project]["source"])
        row={"progetto_id":project,"repository_issue":repo,"acquisito_utc":None,
             "stato":"SENZA_REPOSITORY" if not repo else "NON_RICHIESTO",
             "eventi":[],"limite":"Campione senza issue etichettate non prova assenza di incidenti"}
        if repo and project in issue_selected:
            used+=1
            url=GITHUB+repo+"/issues?state=all&sort=updated&per_page=12"
            payload,error=_fetch(fetch,url)
            parsed=_labelled_issues(payload,repo,now) if not error else None
            if parsed is None:
                row.update(stato="FONTE_NON_DISPONIBILE",errore=error or "RISPOSTA_INCOERENTE")
            else:
                row.update(stato="OSSERVATO" if parsed else "NESSUNA_ISSUE_NEL_CAMPIONE",
                           acquisito_utc=_iso(now),eventi=parsed)
        elif repo and collect_project_issues:
            before=past_issues.get(project)
            if before and before.get("stato") in ("OSSERVATO","NESSUNA_ISSUE_NEL_CAMPIONE","STORICO"):
                last=_time(before.get("acquisito_utc"))
                if last and dt.timedelta(0)<=now-last<=dt.timedelta(days=14):
                    row.update(stato="STORICO",acquisito_utc=before["acquisito_utc"],
                               eventi=before.get("eventi",[])[:8])
            if not network_allowed and row["stato"]=="NON_RICHIESTO":
                row["stato"]=paused
            elif row["stato"]=="NON_RICHIESTO":
                row["stato"]="RINVIATO_BUDGET"
        issues.append(row)
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
                row["stato"]=paused
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
        current=(_cftc_btc_tff(raw,spec,now)
                 if spec[0]=="CFTC_BTC_TFF" else _ecb_csv(raw,spec,now)) if not error else None
    else:
        error=paused
        current=None
    if current is None:
        current={"id":spec[0],"serie":spec[1]+"."+spec[2],"fonte":url,
                 "stato":"FONTE_NON_DISPONIBILE","motivo":error or "CSV_INCOERENTE",
                 "acquisito_utc":_iso(now),"valore":None,"unita":spec[3],
                 "limite":"Dato non acquisito, mai assimilare a zero"}
    # A revisited official series may be compared with the prior source
    # observation; never equate this with surprise versus market consensus.
    previous_macro=past_macro.get(spec[0])
    if (current.get("stato")=="OSSERVATO" and isinstance(previous_macro,dict)
            and previous_macro.get("stato") in ("OSSERVATO","STORICO_NON_AGGIORNATO")
            and previous_macro.get("fonte")==current.get("fonte")
            and isinstance(previous_macro.get("periodo"),str)
            and previous_macro["periodo"]<=current["periodo"]
            and type(previous_macro.get("valore")) in (int,float)
            and math.isfinite(previous_macro["valore"])
            and _time(previous_macro.get("acquisito_utc"))):
        current["confronto_precedente"]={
            "periodo":previous_macro["periodo"],"valore":previous_macro["valore"],
            "acquisito_utc":previous_macro["acquisito_utc"]}
        current["delta_dalla_rilevazione_precedente"]=round(
            current["valore"]-previous_macro["valore"],7)
        current["limite_confronto"]="Delta tra osservazioni BCE, non sorpresa rispetto al consenso e non reazione di mercato"
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
            elif descriptor.get("format")==ARB_VESTING_FORMAT:
                url=ARB_VESTING_URL
                raw,error=_fetch(fetch,url,json_data=False)
                result=_arb_vesting_document(raw,project,descriptor,now) if not error else None
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
                    "PROIEZIONE_PRIMARIA_NON_UNLOCK","PROIEZIONE_STORICA",
                    "DOCUMENTO_PRIMARIO_REGOLA_VESTING","REGOLA_VESTING_STORICA"):
                row.update(history,stato=("PROIEZIONE_STORICA"
                           if history.get("stato") in ("PROIEZIONE_PRIMARIA_NON_UNLOCK","PROIEZIONE_STORICA")
                           else "REGOLA_VESTING_STORICA"
                           if history.get("stato") in ("DOCUMENTO_PRIMARIO_REGOLA_VESTING","REGOLA_VESTING_STORICA")
                           else "STORICO_DA_RICONFERMARE"))
            else:
                row.update(stato=paused if not network_allowed
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
            "segnalazioni_repo":issues,"prossima_issue":next_issue,
            "politiche_emissioni":emissions,"prossima_emissione":emission_next,
            "indicatori_macro":macro,"calendari":schedules,
            "revisioni_piani":changes_calendar,
            "storico_supply":history,"variazioni_supply":changes,
            "storico_eventi":retained_events,
            "prossimo_progetto":next_project,
            "prossimo_indicatore":series[(pick+(1 if network_allowed else 0))%len(series)][0],
            "prossimo_schedule":sch_next,
            "richieste_pubbliche":used,"limite_richieste":MAX_GOVERNANCE_CALLS+MAX_MACRO_CALLS+MAX_SCHEDULE_CALLS+MAX_SECURITY_CALLS+MAX_EMISSION_CALLS+MAX_ISSUE_CALLS,
            "limite":"Campioni pubblici: proposal != approvazione; unlock != circolazione != vendita; nessuna direzione di mercato inferita"}


def decision_review(evidence, row, group):
    """Condense *already read-time-validated* primary facts for one asset row.

    This is a view of the same economic monitor, not another source producer.
    A documented proposal, advisory or plan is never relabelled as an actual
    exploit, network activation, unlock, sale, price cause or trading signal.
    """
    identity=row.get("identita") if isinstance(row,dict) else None
    identity=identity if isinstance(identity,dict) else {}
    token=row.get("token") if isinstance(row,dict) else None
    pid=identity.get("coingecko_id")
    base={"token":token,"coppia":identity.get("coppia"),"progetto_id":pid,
          "stato":"NESSUNA_EVIDENZA_PRIMARIA_ATTUALE","fatti":[],
          "ipotesi_non_attestata":None,"controipotesi":None,
          "condizione_di_riesame":"Acquisire o rivalidare una fonte primaria attribuibile al progetto",
          "limite":"L'assenza di un fatto nel campione non prova sicurezza, crescita o peggioramento"}
    if (identity.get("stato")!="IDENTITA_VERIFICATA_DA_CATALOGO"
            or not isinstance(pid,str)):
        # A previously verified market can become restricted. The online-only
        # project catalogue then *rightly* refuses to verify the project.
        # An exact, current AssetPairs observation remains usable solely as
        # a pair-status fact: never restore old project/supply assertions.
        pairs=evidence.get("stati_coppie_kraken")
        group_rows=pairs.get(group) if isinstance(pairs,dict) else None
        match=next((x for x in group_rows if isinstance(x,dict)
                    and x.get("indice")==row.get("indice")
                    and x.get("token")==token
                    and x.get("pair_key")==identity.get("pair_key")
                    and x.get("coppia")==identity.get("coppia")
                    and x.get("stato_alla_lettura")=="OSSERVATO"),
                   None) if isinstance(group_rows,list) else None
        if match:
            status=match["status_kraken"]
            fact={"tipo":"STATO_COPPIA_KRAKEN",
                  "fatto":"Kraken AssetPairs segnala "+status+" per "+str(match["coppia"]),
                  "fonte":match["fonte"],"pubblicato_o_periodo_utc":None,
                  "acquisito_utc":match["acquisito_utc"],
                  "stato_prova":"SOLO_COPPIA_NON_PROGETTO",
                  "dettaglio":{"status":status,"cambiamento":match.get("cambiamento")},
                  "limite":"Risposta pubblica di coppia; progetto, account e motivi dello stato non verificati"}
            return dict(base,stato="SOLO_COPPIA_KRAKEN_VERIFICATA",
                progetto_id=None,fatti=[fact],
                ipotesi_non_attestata=(
                    "Le limitazioni della coppia potrebbero condizionare eventuali operazioni"
                    if status!="online" else
                    "L'indicazione online non prova l'accessibilità sul conto"),
                controipotesi="Lo stato della coppia non identifica il progetto e non prova un delisting",
                condizione_di_riesame="Verificare nuovamente AssetPairs, identità progetto e condizioni del conto")
        return dict(base,stato="IDENTITA_NON_VERIFICATA",
                    condizione_di_riesame="Verificare identità Kraken/progetto prima di attribuire eventi")
    def by_project(family):
        rows=evidence.get(family)
        if not isinstance(rows,list): return {}
        return next((x for x in rows if isinstance(x,dict) and x.get("progetto_id")==pid),{})
    facts=[]
    def add(kind,fact,source,observed,acquired,proof,limit,details=None):
        if not isinstance(source,str) or not source.startswith("https://"):
            return
        facts.append({"tipo":kind,"fatto":fact,"fonte":source,
                      "pubblicato_o_periodo_utc":observed,
                      "acquisito_utc":acquired,"stato_prova":proof,
                      "dettaglio":details,"limite":limit})
    schedule=by_project("calendari")
    if schedule.get("stato")=="DOCUMENTO_PRIMARIO_CON_SCHEDULE":
        event=next((x for x in schedule.get("eventi",[]) if isinstance(x,dict)),None)
        if event:
            add("UNLOCK_SOLO_PROGRAMMATO",
                "Documento del progetto con unlock programmato; rilascio effettivo e vendita non attestati",
                schedule.get("fonte"),event.get("evento_utc"),schedule.get("acquisito_utc"),
                "PROGRAMMA_PRIMARIO",schedule.get("limite"),
                {"allocazione":event.get("allocazione"),"quantita_token":event.get("quantita_token")})
    if schedule.get("stato")=="DOCUMENTO_PRIMARIO_REGOLA_VESTING":
        add("REGOLA_VESTING_MENSILE_PRIMARIA",
            "La Foundation documenta regole mensili e lineari di vesting, senza quantità o giorni esatti per i futuri unlock",
            schedule.get("fonte"),None,schedule.get("acquisito_utc"),
            "REGOLA_PRIMARIA_NON_EVENTO_ESEGUITO",schedule.get("limite"),
            {"periodi_mensili_derivati":schedule.get("periodi_mensili_derivati"),
             "regole":schedule.get("regole")})
    monthly=by_project("calendari")
    if monthly.get("stato")=="PROIEZIONE_PRIMARIA_NON_UNLOCK":
        add("PROIEZIONE_CIRCOLAZIONE",
            "La fonte ufficiale pubblica stime mensili di token circolanti, non singoli unlock",
            monthly.get("fonte"),monthly.get("mese_circolazione"),
            monthly.get("acquisito_utc"),"PROIEZIONE_NON_REALIZZAZIONE",
            monthly.get("limite"),
            {"circolante_mese_token":monthly.get("circolante_mese_token"),
             "mesi_futuri":len(monthly.get("stime_mensili",[]))})
    pairs=evidence.get("stati_coppie_kraken")
    observed_pairs=pairs.get(group) if isinstance(pairs,dict) else None
    if isinstance(observed_pairs,list):
        entry=next((x for x in observed_pairs if isinstance(x,dict)
                    and x.get("indice")==row.get("indice")
                    and x.get("token")==token and x.get("coppia")==identity.get("coppia")
                    and x.get("pair_key")==identity.get("pair_key")),None)
        if entry and entry.get("stato_alla_lettura")=="OSSERVATO":
            add("STATO_COPPIA_KRAKEN",
                "Kraken AssetPairs indica lo stato pubblico "+str(entry.get("status_kraken"))
                +" per "+str(entry.get("coppia")),
                entry.get("fonte"),None,entry.get("acquisito_utc"),"OSSERVAZIONE_API",
                entry.get("limite"),
                {"status":entry.get("status_kraken"),"cambiamento":entry.get("cambiamento")})
    security=by_project("avvisi_repository")
    if security.get("stato_alla_lettura")=="OSSERVATO":
        event=next((e for e in security.get("avvisi",[]) if isinstance(e,dict)),None)
        if event:
            add("AVVISO_SICUREZZA_REPOSITORY",
                "Il repository associato pubblica un avviso di sicurezza: impatto sul token non attestato",
                event.get("fonte"),event.get("pubblicato_utc"),
                security.get("acquisito_utc"),"DOCUMENTO_REPOSITORY",
                event.get("limite"),{"titolo":event.get("titolo"),"stato":event.get("stato")})
    emission=by_project("politiche_emissioni")
    if emission.get("stato_alla_lettura")=="OSSERVATO":
        add("PARAMETRI_EMISSIONE",
            "Il progetto espone parametri di emissione correnti, non un calendario vesting",
            emission.get("fonte"),None,emission.get("acquisito_utc"),
            "PARAMETRI_RPC",emission.get("limite"),
            {"valori":emission.get("valori")})
    governance=by_project("progetti")
    if governance.get("stato")=="OSSERVATO":
        event=next((e for e in governance.get("eventi",[]) if isinstance(e,dict)),None)
        if event:
            add("PROPOSTA_GOVERNANCE_DOCUMENTALE",
                "Esiste una proposta di documentazione; attivazione sulla rete non attestata",
                event.get("fonte"),event.get("pubblicato_utc"),
                governance.get("acquisito_utc"),"PROPOSTA_DOCUMENTALE",
                event.get("limite"),{"titolo":event.get("titolo"),
                                      "stato_documento":event.get("stato_documento")})
    issues=by_project("segnalazioni_repo")
    if issues.get("stato_alla_lettura")=="OSSERVATO":
        event=next((e for e in issues.get("eventi",[]) if isinstance(e,dict)),None)
        if event:
            add("ISSUE_TECNICA_ETICHETTATA",
                "È pubblicata una issue etichettata: l'esito tecnico non è accertato",
                event.get("fonte"),event.get("pubblicato_utc"),
                issues.get("acquisito_utc"),"SEGNALAZIONE_NON_CONFERMA",
                event.get("limite"),{"titolo":event.get("titolo"),
                                      "categorie":event.get("categorie")})
    if not facts:
        return base
    priority=(("STATO_COPPIA_KRAKEN", "Una restrizione della coppia potrebbe impedire l'operatività prevista",
               "Lo stato pubblico non attesta operatività o sospensione del singolo account",
               "Ricontrollare AssetPairs e mercato/account prima di considerare operazioni"),
              ("REGOLA_VESTING_MENSILE_PRIMARIA",
               "I periodi mensili documentati potrebbero influire sulla supply futura",
               "Mancano giorno esatto, quantità della tranche, circolazione e vendita",
               "Rileggere la regola pubblicata e verificare eventuali eventi effettivi prima di stimare l'impatto"),
              ("UNLOCK_SOLO_PROGRAMMATO",
               "Una distribuzione programmata potrebbe modificare la disponibilità futura di token",
               "Il documento non attesta immissione effettiva, domanda o vendite",
               "Verificare il calendario aggiornato, la circolazione effettiva e l'eventuale esecuzione"),
              ("AVVISO_SICUREZZA_REPOSITORY",
               "Un avviso del client potrebbe richiedere valutare esposizione e aggiornamenti",
               "L'avviso del repository potrebbe non riguardare la rete o l'asset posseduto",
               "Accertare versioni coinvolte e comunicati ufficiali sull'impatto"),
              ("PROIEZIONE_CIRCOLAZIONE",
               "Un cambiamento della circolazione prevista potrebbe influire sulla futura diluizione",
               "La proiezione può variare e non dimostra unlock, vendita né impatto sul prezzo",
               "Confrontare una nuova versione del piano con dati circolanti osservati"),
              ("PARAMETRI_EMISSIONE",
               "Modifiche alla politica di emissione potrebbero alterare la supply futura",
               "I parametri RPC non misurano i token venduti né dimostrano effetto sul prezzo",
               "Verificare i parametri aggiornati e l'emissione effettivamente osservata"),
              ("ISSUE_TECNICA_ETICHETTATA",
               "Una issue potrebbe anticipare un cambiamento se confermato e implementato",
               "La segnalazione può non portare ad alcun cambiamento della rete",
               "Controllare risoluzione e annunci di rilascio o attivazione"),
              ("PROPOSTA_GOVERNANCE_DOCUMENTALE",
               "Una proposta potrebbe modificare le condizioni del progetto se effettivamente adottata",
               "Un merge documentale non prova adozione sulla rete né effetto economico",
               "Accertare eventuale approvazione, attivazione e dati successivi"))
    present={f["tipo"] for f in facts}
    selected=next(((a,b,c) for kind,a,b,c in priority if kind in present),None)
    # A plain 'online' pair is weaker than a published security/supply fact.
    pair=next((f for f in facts if f["tipo"]=="STATO_COPPIA_KRAKEN"),None)
    if pair and pair["dettaglio"]["status"]=="online":
        selected=next(((a,b,c) for kind,a,b,c in priority[1:] if kind in present),selected)
    return dict(base,stato="COPERTURA_PRIMARIA_PARZIALE",
                fatti=facts[:7],ipotesi_non_attestata=selected[0],
                controipotesi=selected[1],condizione_di_riesame=selected[2])


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
    if type(raw.get("richieste_pubbliche")) is not int or not 0<=raw["richieste_pubbliche"]<=7:
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
    read_issues=[]
    source_issues=raw.get("segnalazioni_repo")
    if source_issues is not None:
        if (not isinstance(source_issues,list) or len(source_issues)!=len(roster)
                or [x.get("progetto_id") for x in source_issues if isinstance(x,dict)]!=list(roster)):
            raise ValueError("Repository issues roster mismatch")
        for group in source_issues:
            repo=_issue_repo(roster[group["progetto_id"]]["source"])
            if group.get("repository_issue")!=repo:
                raise ValueError("Repository issue project attribution forged")
            copy=dict(group)
            if group.get("stato") in ("OSSERVATO","NESSUNA_ISSUE_NEL_CAMPIONE","STORICO"):
                t=_time(group.get("acquisito_utc"))
                entries=group.get("eventi")
                if (not repo or not t or t>now+dt.timedelta(minutes=2)
                        or not isinstance(entries,list) or len(entries)>8):
                    raise ValueError("Issue observation invalid")
                for event in entries:
                    if not isinstance(event,dict): raise ValueError("Issue event malformed")
                    num=event.get("id")
                    tags=event.get("categorie")
                    if (not isinstance(num,str) or not num.isdecimal()
                            or event.get("fonte")!="https://github.com/"+repo+"/issues/"+num
                            or event.get("emittente")!=repo
                            or event.get("tipo")!="ISSUE_ETICHETTATA_REPOSITORY"
                            or not isinstance(tags,list) or not tags
                            or any(tag not in ISSUE_LABELS for tag in tags)
                            or not _time(event.get("pubblicato_utc"))
                            or event.get("evento_utc") is not None
                            or event.get("stato")!="PUBBLICATO_DA_VERIFICARE"
                            or event.get("esito_proposta")!="NON_ATTESTATO"):
                        raise ValueError("Issue attribution or decision forged")
                copy["stato_alla_lettura"]=("SCADUTO" if now-t>dt.timedelta(days=14)
                                             else group["stato"])
            read_issues.append(copy)
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
        if row.get("stato") in ("DOCUMENTO_PRIMARIO_REGOLA_VESTING","REGOLA_VESTING_STORICA"):
            if not _arb_vesting_valid(row,expected):
                raise ValueError("Primary vesting rule is not attributable to foundation MDX")
            observed=_time(row.get("acquisito_utc"))
            new["stato"]=("DOCUMENTO_PRIMARIO_REGOLA_VESTING"
                          if row["stato"]=="DOCUMENTO_PRIMARIO_REGOLA_VESTING"
                          and observed and dt.timedelta(0)<=now-observed<=dt.timedelta(days=30)
                          else "REGOLA_VESTING_STORICA")
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
            if row["id"]=="CFTC_BTC_TFF" and not _cftc_read_valid(row):
                raise ValueError("CFTC futures report source or classification forged")
            period=str(row.get("periodo"))
            if len(period)==7 and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])",period):
                year,month=map(int,period.split("-"))
                ending=dt.date(year,month,calendar.monthrange(year,month)[1])
                day=_time(ending.isoformat()+"T00:00:00+00:00")
            else:
                day=_time(period+"T00:00:00+00:00")
            if (day is None or day>now+dt.timedelta(days=1)
                    or type(row["valore"]) not in (int,float) or not math.isfinite(row["valore"])):
                raise ValueError("ECB observation invalid")
            old_point=row.get("confronto_precedente")
            if old_point is not None:
                if (not isinstance(old_point,dict)
                        or type(old_point.get("valore")) not in (int,float)
                        or not math.isfinite(old_point["valore"])
                        or not isinstance(old_point.get("periodo"),str)
                        or old_point["periodo"]>row.get("periodo","")
                        or not _time(old_point.get("acquisito_utc"))
                        or row.get("delta_dalla_rilevazione_precedente")!=round(
                           row["valore"]-old_point["valore"],7)):
                    raise ValueError("ECB temporal delta fabricated")
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
            segnalazioni_repo=read_issues if source_issues is not None else None,
            indicatori_macro=indicators,calendari=read_schedules,
            variazioni_supply=raw.get("variazioni_supply",[])[:30],
            copertura={"progetti":len(projects),"governance_osservati":sum(p["stato"]=="OSSERVATO" for p in read_projects),
                        "indicatori_macro_osservati":sum(m["stato"]=="OSSERVATO" for m in indicators),
                        "calendari_primari_attuali":sum(s["stato"]=="DOCUMENTO_PRIMARIO_CON_SCHEDULE" for s in read_schedules),
            "regole_vesting_primarie_attuali":sum(s["stato"]=="DOCUMENTO_PRIMARIO_REGOLA_VESTING" for s in read_schedules),
                        "security_repository_osservati":sum(a.get("stato_alla_lettura") in ("OSSERVATO","NESSUN_AVVISO_NEL_CAMPIONE") for a in verified_advisories),
                        "politiche_emissioni_osservate":sum(e.get("stato_alla_lettura")=="OSSERVATO" for e in verified_emissions),
                        "repository_issue_osservati":sum(e.get("stato_alla_lettura") in ("OSSERVATO","NESSUNA_ISSUE_NEL_CAMPIONE") for e in read_issues)},
            limite=raw.get("limite"))
