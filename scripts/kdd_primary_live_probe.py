"""Public-only live smoke on GitHub Actions, no wallet, credentials or paid API.

A provider outage is reported as unavailable; successful acquisition must be
evidenced by an actual parsed primary observation, not a link catalogue.
"""
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import decision_desk as desk
import kdd_economics as econ
import kdd_network_defi as network
import kdd_primary_economics as primary


def main():
    now = dt.datetime.now(dt.timezone.utc)
    # Observed public project IDs only; no portfolio or real customer data.
    identities = []
    for tok in ("JUP", "NEAR", "SOL", "SUI"):
        project = econ._CURATED.get(tok)
        if not project:
            raise RuntimeError("Official project mapping missing: "+tok)
        identities.append({
            "stato": "IDENTITA_VERIFICATA_DA_CATALOGO",
            "token": tok, "token_progetto": tok,
            "coingecko_id": project["id"],
            "progetto": project["name"],
            "repository_primario": project.get("repository"),
            "metodo": "REGISTRO_CURATO"})
    def csv_source(url):
        raw = desk.request(url, timeout=14)
        if len(raw)>400_000:
            raise ValueError("ECB response too large")
        return raw
    observed = []
    previous = None
    for cycle in (1, 2):
        current = now + dt.timedelta(seconds=cycle)
        result = primary.collect(
            current, identities, previous,
            fetch_json=network._http, fetch_csv=csv_source,
            catalog=econ._CURATED)
        read = primary.at_read(result, identities, current, catalog=econ._CURATED)
        if len(read["progetti"]) != 4 or result["richieste_effettuate"] > primary.MAX_REQUESTS:
            raise RuntimeError("Dynamic roster or public request budget failed")
        rowlog = []
        for row in result["progetti"]:
            source = row.get("proiezione_circolazione") or {}
            emission = row.get("politica_emissioni") or {}
            events = row.get("eventi",[])
            published = {
                "progetto_id": row["coingecko_id"],
                "stato": row["stato"],
                "emissione_primaria": emission.get("stato"),
                "proiezione_mensile_primaria": source.get("stato"),
                "motivo_proiezione": source.get("motivo"),
                "mesi_previsti_campionati": len(source.get("eventi",[])),
                "segnalazioni_issue": len(events)}
            if emission.get("stato") == "OSSERVATO":
                observed.append(("emissione",emission["fonte"]))
            if source.get("stato") == "OSSERVATO":
                observed.append(("circolazione",source["fonte"]))
            rowlog.append(published)
        macro = [
            {"id": row.get("id"), "stato": row.get("stato"),
             "valore": row.get("valore"), "periodo": row.get("periodo_dato"),
             "fonte": row.get("fonte")}
            for row in result["indicatori_macro"]]
        for row in macro:
            if row["stato"]=="OSSERVATO":
                observed.append((row["id"],row["fonte"]))
        print(json.dumps({"ciclo":cycle, "richieste":result["richieste_effettuate"],
                          "progetti":rowlog, "macro":macro,
                          "consumer":read["schema"]},ensure_ascii=False))
        previous = result
    print("LIVE_PRIMARY_OBSERVED",len(observed),
          json.dumps(observed,ensure_ascii=False))
    if not observed:
        print("STOP: no real primary provider response observed",file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
