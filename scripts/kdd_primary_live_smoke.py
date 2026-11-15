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
            or url.startswith("https://raw.githubusercontent.com/")):
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


def identity(token):
    # Synthetic Kraken market record for NON-PRIVATE producer testing only.
    pair=token+"/EUR"
    key=token+"EUR"
    return econ.identify(token,pair,key,catalog={key:{
        "pair_key":key,"pair":pair,"base":token,"quote":"EUR"}})


roster={"posizioni":[],"candidati":[]}
for n,token in enumerate(("BTC","ETH","SOL")):
    ident=identity(token)
    assert ident["stato"]=="IDENTITA_VERIFICATA_DA_CATALOGO"
    roster["posizioni"].append({"indice":n,"token":token,"identita":ident,
                                "fondamentali":{"stato":"NON_VERIFICATO"}})

seen=[]
def counted(url):
    seen.append(url)
    return fetch(url)

raw=None
for cycle in range(1,4):
    moment=dt.datetime.now(dt.timezone.utc)
    before=len(seen)
    raw=primary.collect(moment,roster,raw,counted)
    checked=primary.at_read(raw,roster,moment)
    assert checked["schema"]==primary.SCHEMA
    assert checked["copertura"]["progetti"]==3
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
    print("history_supply",len(raw["storico_supply"]),
          "history_events",len(raw["storico_eventi"]),
          "next_project",raw["prossimo_progetto"],
          "next_macro",raw["prossimo_indicatore"])
    print("unlock_schedule",[(r["progetto_id"],r["stato"]) for r in checked["calendari"]])
    if checked["copertura"]["governance_osservati"]==0 and checked["copertura"]["indicatori_macro_osservati"]==0:
        print("WARNING: NO LIVE PROVIDER EVIDENCE THIS CYCLE",file=sys.stderr)
