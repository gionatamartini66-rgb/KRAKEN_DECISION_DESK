#!/usr/bin/env python3
"""KDD -> FolderSync: esportazione SOLTANTO conteggi di mercati pubblici.

Nessuna API, rete, credenziale, saldo, dossier o report privato viene letto.
L'esportazione durante "aggiorna" è DISATTIVATA DI DEFAULT: si attiva soltanto
con KDD_DRIVE_PUBLIC_EXPORT=1 dopo un GO separato al deploy sul Samsung.
Il trasferimento su Drive è responsabilità distinta di FolderSync.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile

SCHEMA = "kdd_public_market_v001"
SOURCE_NAME = "ultima_rilevazione.json"
OUTPUT_NAME = "mercato_kdd.json"
ENV_OPT_IN = "KDD_DRIVE_PUBLIC_EXPORT"
UTC = dt.timezone.utc
MAX_SOURCE_BYTES = 12_000_000
MAX_AGE = dt.timedelta(minutes=45)
CLOCK_TOLERANCE = dt.timedelta(seconds=90)
DEFAULT_DEST = Path("/storage/emulated/0/KDD_TEST_SAMSUNG")


class ExportError(Exception):
    """Input o destinazione non validi, senza mostrare dati sensibili."""


def parse_utc(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise ExportError("Timestamp fonte mancante o non testuale.")
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ExportError("Timestamp fonte malformato.") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ExportError("Timestamp fonte privo di timezone.")
    return t.astimezone(UTC)


def nonnegative_int(obj: dict, key: str) -> int:
    v = obj.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 200_000:
        raise ExportError("Contatore mercato non valido: " + key)
    return v


def prepare(source_dir: Path, now: dt.datetime | None = None) -> dict:
    if now is None:
        now = dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now deve essere timezone-aware")
    now = now.astimezone(UTC)
    origin = Path(source_dir) / SOURCE_NAME
    if origin.is_symlink() or not origin.is_file():
        raise ExportError("Snapshot mercato assente, non regolare o symlink.")
    try:
        size = origin.stat().st_size
        if size > MAX_SOURCE_BYTES or size < 2:
            raise ExportError("Dimensione snapshot mercato non accettabile.")
        with origin.open("r", encoding="utf-8") as stream:
            obj = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ExportError("Snapshot mercato non leggibile o JSON non valido.") from e
    if not isinstance(obj, dict):
        raise ExportError("Snapshot mercato non oggetto JSON.")
    acquired = parse_utc(obj.get("rilevazione_utc"))
    if acquired > now + CLOCK_TOLERANCE:
        raise ExportError("Rilevazione mercato futura: orologio/fonte incoerenti.")
    age = max(dt.timedelta(0), now - acquired)
    return {
        "schema": SCHEMA,
        "tipo": "mercato_pubblico_non_patrimoniale",
        "fonte": "KDD/ultima_rilevazione.json; Kraken Spot pubblico",
        "rilevazione_utc": acquired.isoformat(timespec="seconds"),
        "esportazione_utc": now.isoformat(timespec="seconds"),
        "eta_mercato_secondi": int(age.total_seconds()),
        "freschezza": "CORRENTE" if age <= MAX_AGE else "SCADUTO",
        "n_coppie_multi": nonnegative_int(obj, "n_coppie_multi"),
        "n_token_multi": nonnegative_int(obj, "n_token_multi"),
        "ordine_finanziario": False,
        "note": "Conteggi informativi; nessun saldo, prezzo o ordine. Verificare eta e fonte.",
    }


def publish(source_dir: Path, dest_dir: Path, now: dt.datetime | None = None) -> dict:
    dest_dir = Path(dest_dir)
    if dest_dir.name != "KDD_TEST_SAMSUNG" or not dest_dir.is_dir() or dest_dir.is_symlink():
        raise ExportError("Destinazione non consentita: attesa KDD_TEST_SAMSUNG preesistente.")
    final = dest_dir / OUTPUT_NAME
    if final.is_symlink() or (final.exists() and not final.is_file()):
        raise ExportError("Output non sicuro o collegamento simbolico.")
    payload = prepare(source_dir, now)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dest_dir,
                                         prefix=".kdd_market_", suffix=".tmp", delete=False) as f:
            temp_name = f.name
            json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, final)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return payload


def export_if_enabled(source_dir: Path, *, dest_dir: Path = DEFAULT_DEST,
                      environ: dict | None = None) -> dict | None:
    """Hook senza rete. Nessun effetto collaterale se l'opt-in non vale '1'."""
    env = os.environ if environ is None else environ
    if env.get(ENV_OPT_IN) != "1":
        return None
    return publish(source_dir, dest_dir)


def main() -> int:
    p = argparse.ArgumentParser(description="Esporta SOLO contatori Kraken pubblici nella cartella FolderSync di TEST.")
    p.add_argument("--source-dir", type=Path, default=Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001")
    p.add_argument("--dest-dir", type=Path, default=DEFAULT_DEST)
    args = p.parse_args()
    try:
        result = publish(args.source_dir, args.dest_dir)
    except (ExportError, OSError) as e:
        print("STOP EXPORT MERCATO:", type(e).__name__, str(e))
        return 1
    print("EXPORT PUBBLICO OK | fonte", result["rilevazione_utc"], "| freschezza",
          result["freschezza"], "| token", result["n_token_multi"],
          "| coppie", result["n_coppie_multi"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
