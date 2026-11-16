#!/usr/bin/env python3
"""Public, non-private G2 source smoke. Never asserts a simulated wallet is real.

Run on CI's isolated Linux worker. All URLs are KDD's bounded public collector.
Provider failures are reported as missing evidence, never fictitious observations.
"""
import datetime as dt
import json
import sys
import urllib.request

import kdd_economics as econ
import kdd_economic_sources as primary

NOW = dt.datetime.now(dt.timezone.utc)


def fetch(url):
    if not (url.startswith("https://api.github.com/repos/")
            or url.startswith("https://data-api.ecb.europa.eu/service/data/")
            or url.startswith("https://raw.githubusercontent.com/")
            or url == primary.SUI_CIRCULATION
            or url == primary.CFTC_BTC_TFF_URL
            or url in [f[1] for f in primary.KRAKEN_STATUS_FEEDS]):
        raise ValueError("URL outside verified public source allowlist")
    req = urllib.request.Request(url, headers={
        "User-Agent": "KDD-G2-public-source-smoke/1.0",
        "Accept": "application/vnd.github+json" if "api.github.com" in url
                  else "text/csv"})
    with urllib.request.urlopen(req, timeout=15) as res:
        data=res.read(1_000_001)
    if len(data)>1_000_000:
        raise ValueError("Source response exceeds budget")
    return data


def rpc_fetch(url,payload):
    if url!=primary.SOLANA_RPC or payload.get("method")!="getInflationGovernor":
        raise ValueError("Unapproved public RPC")
    # Count JSON-RPC POST beside the HTTP GET observations; a timeout is
    # still one real attempted request, not a free synthetic source.
    seen.append(url+"#getInflationGovernor")
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type":"application/json","User-Agent":"KDD-G2-public-source-smoke/1.0"},
        method="POST")
    with urllib.request.urlopen(req,timeout=15) as res:
        raw=res.read(100001)
    return json.loads(raw.decode("utf-8"))


def identity(token):
    # Synthetic Kraken market record for NON-PRIVATE producer testing only.
    pair=token+"/EUR"
    key=token+"EUR"
    return econ.identify(token,pair,key,catalog={key:{
        "pair_key":key,"pair":pair,"base":token,"quote":"EUR"}})


roster={"posizioni":[],"candidati":[]}
for n,token in enumerate(("BTC","ETH","SOL","SUI","ARB","STRK")):
    ident=identity(token)
    assert ident["stato"]=="IDENTITA_VERIFICATA_DA_CATALOGO"
    roster["posizioni"].append({"indice":n,"token":token,"identita":ident,
                                "fondamentali":{"stato":"NON_VERIFICATO"}})

seen=[]
def counted(url):
    seen.append(url)
    return fetch(url)

raw=None
for cycle in range(1,len(primary.MACRO_SERIES)+1):
    moment=dt.datetime.now(dt.timezone.utc)
    before=len(seen)
    raw=primary.collect(moment,roster,raw,counted,rpc_fetch=rpc_fetch,
                        collect_project_issues=True,collect_kraken_status=True)
    checked=primary.at_read(raw,roster,moment)
    assert checked["schema"]==primary.SCHEMA
    assert checked["copertura"]["progetti"]==6
    assert raw["richieste_pubbliche"] <= raw["limite_richieste"]
    assert raw["richieste_pubbliche"]==len(seen)-before
    print("PUBLIC_G2_SMOKE_UTC",moment.isoformat(timespec="seconds"),"cycle",cycle)
    print("source_requests",raw["richieste_pubbliche"],"URLs",json.dumps(seen[before:]))
    for record in checked["progetti"]:
        print("project",record["progetto_id"],"state",record["stato"],
              "documents",len(record["eventi"]),
              "reason",record.get("errore"),
              "attribution",record.get("repository_governance"))
    for record in checked["indicatori_macro"]:
        print("macro",record["id"],"state",record["stato"],
              "period",record.get("periodo"),"value",record.get("valore"),
              "reason",record.get("motivo"),"url",record["fonte"])
    print("kraken_announcements",[(x["id"],x["stato"],len(x["eventi"]))
                                  for x in checked["comunicazioni_kraken"]])
    print("history_supply",len(raw["storico_supply"]),
          "history_events",len(raw["storico_eventi"]),
          "next_project",raw["prossimo_progetto"],
          "next_macro",raw["prossimo_indicatore"])
    print("solana_inflation",[(p["progetto_id"],p["stato"],p.get("valori"))
                              for p in checked.get("politiche_emissioni") or [] if p["progetto_id"]=="solana"])
    print("project_labelled_issues",[(p["progetto_id"],p["stato"],len(p["eventi"]))
                                   for p in checked.get("segnalazioni_repo") or []])
    print("repository_security",[(r["progetto_id"],r["stato"],len(r["avvisi"])) for r in checked.get("avvisi_repository") or []])
    print("unlock_schedule",[(r["progetto_id"],r["stato"]) for r in checked["calendari"]])
    arb=next(r for r in checked["calendari"] if r["progetto_id"]=="arbitrum")
    print("ARB_VESTING_PRIMARY",arb["stato"],"source",arb.get("fonte"),
          "months",arb.get("periodi_mensili_derivati"),
          "events_observed",len(arb.get("eventi",[])))
    strk=next(r for r in checked["calendari"] if r["progetto_id"]=="starknet")
    print("STRK_OFFICIAL_MAX_UNLOCK",strk["stato"],"events",strk.get("eventi",[]),
          "source",strk.get("fonte"))
    sui=next(r for r in checked["calendari"] if r["progetto_id"]=="sui")
    print("sui_official_monthly",sui["stato"],"source",sui.get("fonte"),
          "reference_month",sui.get("mese_circolazione"),
          "declared_circulation",sui.get("circolante_mese_token"),
          "future_months",len(sui.get("stime_mensili",[])),
          "unlock_verified",sui.get("stato_vesting"))
    if cycle==len(primary.MACRO_SERIES):
        for cid in ("CFTC_BTC_TFF","CFTC_ETH_TFF"):
            cftc=next(x for x in checked["indicatori_macro"] if x["id"]==cid)
            assert cftc["stato"] in ("OSSERVATO","SCADUTO","STORICO_NON_AGGIORNATO"), (
                "CFTC official futures data not parsed in live test: "+cid
                +str(cftc.get("motivo")))
            assert cftc["classificazioni"]["asset_manager"]["saldo_long_meno_short"] == (
                cftc["classificazioni"]["asset_manager"]["long_contratti"] -
                cftc["classificazioni"]["asset_manager"]["short_contratti"])
            print("CFTC_FUTURES_PRIMARY_CONFIRMED",cid,cftc["periodo"],
                  cftc["valore"],cftc["classificazioni"])
    if checked["copertura"]["governance_osservati"]==0 and checked["copertura"]["indicatori_macro_osservati"]==0:
        print("WARNING: NO LIVE PROVIDER EVIDENCE THIS CYCLE",file=sys.stderr)
