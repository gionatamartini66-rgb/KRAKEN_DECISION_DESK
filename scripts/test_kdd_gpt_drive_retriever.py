"""KDD G2-B synthetic-only, deterministic recovery and original-bridge comparisons."""
from __future__ import annotations
import builtins
import copy
import datetime as dt
import hashlib
import importlib.util
import unittest
from unittest import mock

from scripts import kdd_gpt_drive_retriever as r

T = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)
FOLDER = "SYNTHETIC_ONLY_FOLDER_123456"


class SyntheticBridge:
    """Test double for ONLY the retrieval algorithm. Not production validation."""
    def validate(self, handoff, when, logical_sha):
        if handoff.get("schema") != r.SCHEMA or handoff.get("packet_sha256") != hashlib.sha256(
                r.canonical(handoff["packet"])).hexdigest():
            raise ValueError("synthetic packet digest")
        pkt = handoff["packet"]
        if pkt.get("nessun_ordine") is not True:
            raise ValueError("synthetic no order")
        observed = dt.datetime.fromisoformat(pkt["rilevazione_kdd_utc"])
        balance_timestamp = pkt["saldo"].get("ultima_acquisizione_utc")
        saldo = dt.datetime.fromisoformat(balance_timestamp) if balance_timestamp else None
        if observed > when + dt.timedelta(minutes=2):
            raise ValueError("future")
        state = lambda timestamp: "RECENTE" if when - timestamp <= dt.timedelta(minutes=30) else "DA_AGGIORNARE"
        return {"schema": "kdd_gpt_read_context_v001", "snapshot_utc": pkt["rilevazione_kdd_utc"],
                "mercato": {"stato": state(observed)}, "saldo": {"stato": state(saldo) if saldo else "ORIGINE_SCONOSCIUTA"},
                "nessun_ordine": True, "test_double": True}


def synth_handoff(*, when=T, marker="A"):
    timestamp = when.isoformat()
    pkt = {"schema": "kdd_wallet_analysis_packet_v001", "generato_utc": timestamp,
           "rilevazione_kdd_utc": timestamp, "nessun_ordine": True,
           "saldo": {"ultima_acquisizione_utc": timestamp},
           "patrimonio": {"n_posizioni": 1, "posizioni": [{"indice": 0, "token": marker}]}}
    return {"schema": r.SCHEMA, "packet": pkt, "packet_sha256": hashlib.sha256(r.canonical(pkt)).hexdigest(),
            "preparato_utc": timestamp}


def file_and_bytes(*, when=T, marker="A"):
    bundle = synth_handoff(when=when, marker=marker)
    logical_sha = hashlib.sha256(r.canonical(bundle)).hexdigest()
    raw = r.canonical(bundle) + b"\n"
    fid = f"synthetic-{marker}-{when.hour}"
    file = {"id": fid, "name": f"kdd_handoff_{logical_sha}.json", "parents": [FOLDER],
            "size": str(len(raw)), "mimeType": "application/json", "trashed": False,
            "sha256Checksum": hashlib.sha256(raw).hexdigest(),
            "md5Checksum": hashlib.md5(raw).hexdigest(),
            "createdTime": when.isoformat(), "modifiedTime": when.isoformat()}
    return file, raw


class FakeDrive:
    def __init__(self, pages, blobs, *, alter_second_scan=None,
                 deny_list=False, deny_download=False):
        self.pages = pages
        self.blobs = blobs
        self.alter_second_scan = alter_second_scan
        self.deny_list = deny_list
        self.deny_download = deny_download
        self.scan_number = 0
        self.requests = []
        self.downloads = []
        self.metadata_requests = []

    def list_page(self, token, *, timeout):
        if self.deny_list:
            raise r.AccessUnavailable("revoked")
        if token is None:
            self.scan_number += 1
        self.requests.append(token)
        pages = self.alter_second_scan if self.scan_number >= 2 and self.alter_second_scan is not None else self.pages
        index = 0 if token is None else int(token)
        return copy.deepcopy(pages[index])

    def file_metadata(self, file_id, *, timeout):
        self.metadata_requests.append(file_id)
        pages = self.alter_second_scan if self.alter_second_scan is not None else self.pages
        return copy.deepcopy(next(file for page in pages for file in page["files"]
                                  if file["id"] == file_id))

    def download(self, file_id, *, max_bytes, timeout):
        self.downloads.append((file_id, max_bytes))
        if self.deny_download:
            raise r.AccessUnavailable("download forbidden")
        return self.blobs[file_id]


def pages_from(files, page_size=999):
    parts = [files[i:i+page_size] for i in range(0, len(files), page_size)]
    if not parts:
        parts = [[]]
    return [{"files": part, "incompleteSearch": False,
             "nextPageToken": str(i+1) if i+1 < len(parts) else None}
            for i, part in enumerate(parts)]


class RecoveryG2BTests(unittest.TestCase):
    def recover(self, files, blobs, **kwargs):
        driver = FakeDrive(pages_from(files), blobs, **kwargs)
        return r.kdd_get_latest_verified_dossier(driver, FOLDER,
                                                  validator=SyntheticBridge(), now=T), driver

    def test_multipage_selection_follows_created_time_independent_of_page_order(self):
        a, ba = file_and_bytes(when=T-dt.timedelta(minutes=20), marker="OLD")
        b, bb = file_and_bytes(when=T-dt.timedelta(minutes=5), marker="NEW")
        c, bc = file_and_bytes(when=T-dt.timedelta(minutes=12), marker="MID")
        # Files deliberately unordered by timestamp; one folder non-handoff item.
        extra = {"id": "unrelated", "name": "notes.md", "parents": [FOLDER]}
        driver = FakeDrive(pages_from([a, extra, b, c], page_size=2),
                           {a["id"]: ba, b["id"]: bb, c["id"]: bc})
        answer = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(answer["stato"], r.RECOVERED)
        self.assertEqual(answer["file_id"], b["id"])
        self.assertEqual(answer["numero_dossier"], 3)
        self.assertEqual(driver.requests, [None, "1", None, "1"])
        self.assertEqual(driver.downloads, [(b["id"], len(bb))])
        self.assertEqual(answer["criterio_selezione"], "MASSIMO_CREATED_TIME_DRIVE")
        self.assertFalse(answer["massimo_preparato_utc_verificato"])
        self.assertTrue(answer["sha256_drive_confrontato"])
        self.assertNotEqual(answer["digest_logico"], answer["sha256_byte"])

    def test_corrupted_newest_never_falls_back_to_old(self):
        a, ba = file_and_bytes(when=T-dt.timedelta(minutes=10), marker="OLD")
        b, bb = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        bb = bb.replace(b'"NEW"', b'"BAD"')
        outcome, drive = self.recover([a, b], {a["id"]: ba, b["id"]: bb})
        self.assertEqual(outcome["stato"], r.UNVERIFIABLE)
        self.assertEqual(outcome["codice"], "CHECKSUM_DRIVE_DISCORDANTE")
        self.assertEqual(drive.downloads, [(b["id"], len(bb))])
        self.assertNotIn("file_id", outcome)

    def test_two_incompatible_candidates_same_timestamp(self):
        a, ba = file_and_bytes(marker="ADA")
        b, bb = file_and_bytes(marker="ETH")
        outcome, _ = self.recover([a, b], {a["id"]: ba, b["id"]: bb})
        self.assertEqual(outcome["codice"], "DUPLICATI_TEMPORALI_INCOMPATIBILI")

    def test_duplicated_filename_incompatible_bytes(self):
        a, ba = file_and_bytes(marker="AAA")
        b, bb = file_and_bytes(marker="BBB")
        b["name"] = a["name"]
        outcome, _ = self.recover([a, b], {a["id"]: ba, b["id"]: bb})
        self.assertEqual(outcome["stato"], r.UNVERIFIABLE)

    def test_integral_but_stale_recalculates_freshness(self):
        a, ba = file_and_bytes(when=T-dt.timedelta(hours=4))
        outcome, _ = self.recover([a], {a["id"]: ba})
        self.assertEqual(outcome["stato"], r.STALE)
        self.assertEqual(outcome["contesto_kdd"]["mercato"]["stato"], "DA_AGGIORNARE")
        self.assertEqual(outcome["contesto_kdd"]["saldo"]["stato"], "DA_AGGIORNARE")

    def test_access_revoked_during_list(self):
        result, _ = self.recover([], {}, deny_list=True)
        self.assertEqual(result["stato"], r.ACCESS)

    def test_access_revoked_during_download(self):
        a, raw = file_and_bytes()
        result, _ = self.recover([a], {a["id"]: raw}, deny_download=True)
        self.assertEqual(result["stato"], r.ACCESS)

    def test_incomplete_search_blocks_result(self):
        a, raw = file_and_bytes()
        driver = FakeDrive([{"files": [a], "nextPageToken": None, "incompleteSearch": True}], {a["id"]: raw})
        outcome = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(outcome["codice"], "INVENTARIO_NON_COMPLETO")
        self.assertEqual(outcome["stato"], r.UNVERIFIABLE)

    def test_missing_incompleteSearch_flag_blocks_result(self):
        a, raw = file_and_bytes()
        driver = FakeDrive([{"files": [a]}], {a["id"]: raw})
        outcome = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(outcome["stato"], r.UNVERIFIABLE)

    def test_page_token_cycle(self):
        a, raw = file_and_bytes()
        driver = FakeDrive([{"files": [a], "nextPageToken": "1", "incompleteSearch": False},
                            {"files": [], "nextPageToken": "1", "incompleteSearch": False}],
                           {a["id"]: raw})
        outcome = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(outcome["codice"], "PAGINAZIONE_INCOERENTE")

    def test_duplicate_drive_id_different_pages(self):
        a, raw = file_and_bytes()
        driver = FakeDrive(pages_from([a, a], page_size=1), {a["id"]: raw})
        outcome = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(outcome["codice"], "IDENTIFICATIVO_DRIVE_DUPLICATO")

    def test_inventory_race_between_scans(self):
        a, raw = file_and_bytes()
        b, new_raw = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        driver = FakeDrive(pages_from([a]), {a["id"]: raw, b["id"]: new_raw},
                           alter_second_scan=pages_from([a, b]))
        outcome = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(outcome["codice"], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")

    def test_corrupt_history_does_not_block_intact_current_candidate(self):
        old, old_raw = file_and_bytes(when=T-dt.timedelta(hours=4), marker="OLD")
        current, current_raw = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        old["sha256Checksum"] = "0" * 64
        old["modifiedTime"] = T.isoformat()  # Editing history does not promote it.
        result, driver = self.recover([old, current], {old["id"]: old_raw, current["id"]: current_raw})
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(driver.downloads, [(current["id"], len(current_raw))])
        self.assertEqual(result["dossier_fuori_selezione_non_validati"], 1)

    def test_reuploaded_history_demonstrates_metadata_cannot_prove_latest_internal_time(self):
        old, old_raw = file_and_bytes(when=T-dt.timedelta(hours=4), marker="REUPLOAD")
        new, new_raw = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        old["createdTime"] = old["modifiedTime"] = T.isoformat()
        result, drive = self.recover([new, old], {old["id"]: old_raw, new["id"]: new_raw})
        self.assertEqual(result["file_id"], old["id"])
        self.assertEqual(result["stato"], r.STALE)
        self.assertFalse(result["massimo_preparato_utc_verificato"])
        self.assertEqual(drive.downloads, [(old["id"], len(old_raw))])
        self.assertEqual(result["integrita_origine"], "NON_AUTENTICATA")

    def test_equal_current_copies_are_all_checked_and_validated_once(self):
        a, raw = file_and_bytes()
        duplicate = dict(a, id="z-copy")
        drive = FakeDrive(pages_from([duplicate, a]), {a["id"]: raw, duplicate["id"]: raw})
        validator = mock.Mock(wraps=SyntheticBridge())
        result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=validator, now=T)
        self.assertEqual(result["file_id"], a["id"])
        self.assertEqual(drive.downloads, [(a["id"], len(raw)), (duplicate["id"], len(raw))])
        validator.validate.assert_called_once()

    def test_large_history_downloads_and_validates_only_current(self):
        old = [file_and_bytes(when=T-dt.timedelta(minutes=i+1), marker=f"OLD{i}")
               for i in range(1200)]
        current, raw = file_and_bytes(marker="CURRENT")
        files = [row[0] for row in old] + [current]
        drive = FakeDrive(pages_from(files, page_size=31), {current["id"]: raw})
        validator = mock.Mock(wraps=SyntheticBridge())
        result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=validator, now=T)
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(result["dossier_fuori_selezione_non_validati"], 1200)
        self.assertEqual((len(drive.requests), len(drive.downloads), validator.validate.call_count),
                         (78, 1, 1))
        print("RT13: 1200 storici + 1 corrente, 78 richieste lista, 1 download, 1 validazione",
              flush=True)

    def test_resource_caps_stop_before_download_or_validation(self):
        a, raw = file_and_bytes()
        duplicates = [dict(a, id=f"copy-{i}") for i in range(r.MAX_DOWNLOADS+1)]
        large = [dict(duplicate, size=r.MAX_BYTES) for duplicate in duplicates[:3]]
        for files, code in ((large, "LIMITE_BYTE_RECUPERO"),
                            (duplicates, "LIMITE_CANDIDATI_CORRENTI")):
            with self.subTest(code=code):
                result, drive = self.recover(files, {a["id"]: raw})
                self.assertEqual(result["codice"], code)
                self.assertFalse(drive.downloads)
        with mock.patch.object(r, "MAX_INVENTORY_FILES", 1):
            result, drive = self.recover(duplicates, {a["id"]: raw})
            self.assertEqual(result["codice"], "LIMITE_INVENTARIO")
            self.assertFalse(drive.downloads)
        with mock.patch.object(r, "MAX_LIST_PAGES", 1):
            drive = FakeDrive(pages_from([a, duplicates[0]], page_size=1), {a["id"]: raw})
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=SyntheticBridge(), now=T)
            self.assertEqual(result["codice"], "LIMITE_PAGINE")
            self.assertFalse(drive.downloads)

    def test_operation_outliving_monotonic_deadline_cannot_report_success(self):
        a, raw = file_and_bytes()
        drive = FakeDrive(pages_from([a]), {a["id"]: raw})
        validator = mock.Mock(wraps=SyntheticBridge())
        with mock.patch.object(r.time, "monotonic", side_effect=[0, 0, 31]):
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=validator, now=T)
        self.assertEqual(result["codice"], "LIMITE_DURATA_RECUPERO")
        self.assertFalse(drive.downloads)
        validator.validate.assert_not_called()

    def test_incoherent_or_invalid_provider_dates(self):
        a, raw = file_and_bytes()
        for changed, code in (
            ({"modifiedTime": "2010-01-01T00:00:00Z"}, "TEMPI_DRIVE_INCOERENTI"),
            ({"modifiedTime": "2010-01-01"}, "TIMESTAMP_DRIVE_INVALIDO"),
            ({"createdTime": "2026-11-20T12:00:00+03:70"}, "TIMESTAMP_DRIVE_INVALIDO"),
        ):
            with self.subTest(changed=changed):
                result, driver = self.recover([dict(a, **changed)], {a["id"]: raw})
                self.assertEqual(result["codice"], code)
                self.assertFalse(driver.downloads)
        old, old_raw = file_and_bytes(when=T-dt.timedelta(hours=1), marker="old")
        del old["createdTime"]
        result, driver = self.recover([a, old], {a["id"]: raw, old["id"]: old_raw})
        self.assertEqual(result["codice"], "ORDINE_DRIVE_INDETERMINATO")
        self.assertFalse(driver.downloads)

    def test_unrelated_rows_independent_of_parent_but_candidate_errors_block(self):
        a, raw = file_and_bytes()
        notes = {"id": "notes", "name": "kdd_handoff_notes.txt", "parents": ["OTHER"], "trashed": True}
        unrelated = {"id": "other", "name": "manual.json", "parents": ["OTHER"]}
        later = pages_from([a, dict(notes, name="notes-renamed.txt")])
        result, drive = self.recover([a, notes, unrelated], {a["id"]: raw}, alter_second_scan=later)
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(result["file_estranei"], 2)
        self.assertEqual(result["nomi_fuori_schema_con_prefisso_kdd"], 1)
        self.assertEqual(drive.downloads, [(a["id"], len(raw))])
        for changed, code in (
            ({"parents": ["OTHER"]}, "CARTELLA_ORIGINE_NON_ATTESTATA"),
            ({"trashed": True}, "ELEMENTO_CESTINATO_NELLA_RISPOSTA"),
            ({"mimeType": "application/vnd.google-apps.shortcut"}, "TIPO_FILE_NON_BINARY"),
        ):
            with self.subTest(changed=changed):
                result, drive = self.recover([dict(a, **changed), notes], {a["id"]: raw})
                self.assertEqual(result["codice"], code)
                self.assertFalse(drive.downloads)

    def test_duplicate_ids_remain_an_inventory_error_even_for_unrelated_rows(self):
        a, raw = file_and_bytes()
        result, _ = self.recover([a, {"id": a["id"], "name": "notes.txt"}], {a["id"]: raw})
        self.assertEqual(result["codice"], "IDENTIFICATIVO_DRIVE_DUPLICATO")

    def test_versions_detect_reported_changes_on_either_followup_check(self):
        a, raw = file_and_bytes()
        a.update(version="1", headRevisionId="revision-1")
        for key, value in (("version", "2"), ("headRevisionId", "revision-2"),
                           ("headRevisionId", None)):
            with self.subTest(key=key, value=value):
                changed = dict(a, **{key: value})
                result, _ = self.recover([a], {a["id"]: raw}, alter_second_scan=pages_from([changed]))
                self.assertEqual(result["codice"], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")
                drive = FakeDrive(pages_from([a]), {a["id"]: raw})
                validator = mock.Mock(wraps=SyntheticBridge())
                with mock.patch.object(drive, "file_metadata", return_value=changed) as get_metadata:
                    result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=validator, now=T)
                self.assertEqual(get_metadata.call_args.args, (a["id"],))
                self.assertEqual(result["codice"], "VERSIONE_CORRENTE_CAMBIATA_DURANTE_LA_LETTURA")
                validator.validate.assert_not_called()
        result, drive = self.recover([a], {a["id"]: raw})
        self.assertEqual(drive.metadata_requests, [a["id"]])
        self.assertEqual(result["numero_controlli_versione"], 1)
        self.assertFalse(result["atomicita_inventario"])

    def test_unchanged_provider_metadata_cannot_attest_atomicity(self):
        a, raw = file_and_bytes()
        a.update(version="1", headRevisionId="revision-1")
        drive = FakeDrive(pages_from([a]), {a["id"]: raw})

        def download(file_id, *, max_bytes, timeout):
            downloaded = drive.blobs[file_id]
            drive.blobs[file_id] = b"replacement-with-no-metadata-change"
            return downloaded

        with mock.patch.object(drive, "download", side_effect=download):
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=SyntheticBridge(), now=T)
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertFalse(result["atomicita_inventario"])
        self.assertEqual(result["integrita_origine"], "NON_AUTENTICATA")

    def test_provider_sha_mismatch(self):
        a, ba = file_and_bytes()
        a["sha256Checksum"] = "0" * 64
        result, _ = self.recover([a], {a["id"]: ba})
        self.assertEqual(result["codice"], "CHECKSUM_DRIVE_DISCORDANTE")

    def test_provider_sha_absent_not_spuriously_attested(self):
        a, ba = file_and_bytes()
        del a["sha256Checksum"]
        result, _ = self.recover([a], {a["id"]: ba})
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertFalse(result["sha256_drive_confrontato"])
        self.assertEqual(result["integrita_origine"], "NON_AUTENTICATA")

    def test_noncanonical_bytes_rejected_even_if_provider_hash_matches(self):
        a, ba = file_and_bytes()
        alt = ba.rstrip(b"\n") + b"\n\n"
        a["size"] = str(len(alt))
        a["sha256Checksum"] = hashlib.sha256(alt).hexdigest()
        a["md5Checksum"] = hashlib.md5(alt).hexdigest()
        result, _ = self.recover([a], {a["id"]: alt})
        self.assertEqual(result["codice"], "BYTE_NON_CANONICI")

    def test_duplicate_json_keys_rejected(self):
        a, ba = file_and_bytes()
        content = ba[:-2] + b',"schema":"kdd_private_handoff_v001"}\n'
        a["size"] = str(len(content))
        a["sha256Checksum"] = hashlib.sha256(content).hexdigest()
        a["md5Checksum"] = hashlib.md5(content).hexdigest()
        result, _ = self.recover([a], {a["id"]: content})
        self.assertEqual(result["stato"], r.UNVERIFIABLE)

    def test_missing_real_bridge_fails_closed_no_partial_validation(self):
        a, raw = file_and_bytes()
        driver = FakeDrive(pages_from([a]), {a["id"]: raw})
        original_import = builtins.__import__

        def unavailable_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "scripts" and "kdd_bridge_g2" in (fromlist or ()):
                raise ImportError("synthetic missing bridge")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=unavailable_import):
            result = r.kdd_get_latest_verified_dossier(driver, FOLDER, now=T)
        self.assertEqual(result["stato"], r.UNVERIFIABLE)
        self.assertEqual(result["codice"], "VALIDATORE_KDD_NON_SUPERATO")

    def test_read_only_rest_adapter_constructs_scoped_drive_v3_calls(self):
        seen = []
        def json_get(url, params, **bounds):
            seen.append((url, params, bounds))
            return {"files": [], "nextPageToken": None, "incompleteSearch": False}
        def bytes_get(url, params, **bounds):
            seen.append((url, params, bounds))
            return b"sample"
        d = r.DriveV3ReadOnlyAdapter(FOLDER, json_get, bytes_get)
        d.list_page("opaque", timeout=5)
        d.download("file-3", max_bytes=10, timeout=3)
        d.file_metadata("file-3", timeout=1)
        self.assertIn(FOLDER, seen[0][1]["q"])
        self.assertEqual(seen[0][1]["pageToken"], "opaque")
        self.assertIn("incompleteSearch", seen[0][1]["fields"])
        self.assertIn("sha256Checksum", seen[0][1]["fields"])
        self.assertEqual(seen[1][1]["alt"], "media")
        self.assertEqual(seen[1][2], {"max_bytes": 10, "timeout": 3})
        self.assertEqual(seen[0][2]["max_bytes"], r.MAX_METADATA_BYTES)
        self.assertIn("headRevisionId", seen[0][1]["fields"])
        self.assertIn("version", seen[2][1]["fields"].split(","))
        self.assertEqual(seen[2][2]["timeout"], 1)
        self.assertTrue(seen[2][0].endswith("/file-3"))
        self.assertEqual(len(seen), 3)


class OriginalBridgeDifferentialTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec("scripts.kdd_bridge_g2") is None:
            self.skipTest("Original KDD sources not present")
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as fixtures
        self.bridge = bridge
        self.t = fixtures.T
        self.fixture = fixtures.WalletPacketG0Tests("test_wallet_first_all_assets_even_if_quote_missing")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def drive_for(self, bundle):
        logical_sha = self.bridge.digest(bundle)
        raw = self.bridge.canonical(bundle) + b"\n"
        file = {"id": "original-bridge-synthetic", "name": f"kdd_handoff_{logical_sha}.json",
                "parents": [FOLDER], "mimeType": "application/json", "size": str(len(raw)),
                "sha256Checksum": hashlib.sha256(raw).hexdigest(),
                "md5Checksum": hashlib.md5(raw).hexdigest(), "trashed": False,
                "version": "1", "headRevisionId": "rev-original"}
        return FakeDrive(pages_from([file]), {file["id"]: raw})

    def test_original_read_context_matches_fresh_stale_and_missing_balance(self):
        normal = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        self.fixture.portfolio.pop("data_ora_saldo_privato_utc")
        self.fixture.portfolio["fonte_quantita"] = "synthetic balance has no timestamp"
        self.fixture.dump()
        missing = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        for bundle in (normal, missing):
            packet = bundle["packet"]
            del packet["evidenze_multifonte"]["derivati_btc"]["flusso_futures"]
            del packet["patrimonio"]["profondita_book_pubblica"]
            bundle["packet_sha256"] = self.bridge.digest(packet)
        for bundle, when, outcome, market, balance in (
            (normal, self.t, r.RECOVERED, "RECENTE", "RECENTE"),
            (normal, self.t+dt.timedelta(hours=4), r.STALE, "SCADUTA", "SCADUTA"),
            (missing, self.t, r.UNVERIFIABLE, "RECENTE", "ASSENTE"),
            (missing, self.t+dt.timedelta(hours=4), r.UNVERIFIABLE, "SCADUTA", "ASSENTE"),
        ):
            with self.subTest(when=when, balance=balance):
                result = r.kdd_get_latest_verified_dossier(self.drive_for(bundle), FOLDER, now=when)
                original = self.bridge.read_context(bundle, now=when, expected_sha256=self.bridge.digest(bundle))
                self.assertEqual(result["contesto_kdd"], original)
                self.assertEqual(result["stato"], outcome)
                self.assertEqual(result["integrita_documento"], "VERIFICATA")
                self.assertEqual(result["fonti_base"]["mercato"]["stato"], market)
                self.assertEqual(result["fonti_base"]["saldo"]["stato"], balance)
                self.assertEqual(result["evidenze"]["economia"]["disponibilita"], "ASSENTE")
                self.assertEqual(result["evidenze"]["flusso_futures"]["disponibilita"], "ASSENTE")
                self.assertEqual(result["evidenze"]["rete_defi"]["disponibilita"], "ASSENTE")
                self.assertEqual(result["evidenze"]["book"]["disponibilita"], "ASSENTE")
                self.assertEqual(result["limiti_analitici"]["lacune_da_verificare"],
                                 original["lacune_da_verificare"])
                if balance == "ASSENTE":
                    self.assertEqual(result["codice"], "FONTE_BASE_ASSENTE")

    def test_original_optional_evidence_can_expire_while_base_sources_are_recent(self):
        import kdd_futures_flow as flow
        from test_kdd_futures_flow import FuturesFlowTests

        fixture = FuturesFlowTests()
        fixture.setUp()
        fixture.now = self.t
        observed = (self.t-dt.timedelta(seconds=30)).isoformat()
        fixture.ticker["serverTime"] = fixture.history["serverTime"] = observed
        fixture.ticker["tickers"][0]["lastTime"] = observed
        for row in fixture.history["history"]:
            row["time"] = observed
        futures = flow.collect(self.t, request=fixture.fake_request)
        bundle = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        packet = bundle["packet"]
        packet["evidenze_multifonte"]["derivati_btc"]["flusso_futures"] = futures
        bundle["packet_sha256"] = self.bridge.digest(packet)
        for minutes, funding, executions in (
            (0, "OSSERVATO", "CAMPIONE_RECENTE"), (18, "SCADUTO", "SCADUTO")
        ):
            with self.subTest(minutes=minutes):
                when = self.t + dt.timedelta(minutes=minutes)
                result = r.kdd_get_latest_verified_dossier(self.drive_for(bundle), FOLDER, now=when)
                context = self.bridge.read_context(bundle, now=when, expected_sha256=self.bridge.digest(bundle))
                self.assertEqual(result["contesto_kdd"], context)
                self.assertEqual(result["stato"], r.RECOVERED)
                self.assertEqual(result["evidenze"]["flusso_futures"]["disponibilita"], "STATI_NEL_CONTESTO")
                self.assertEqual(result["evidenze"]["book"]["disponibilita"], "NON_VERIFICABILE")
                self.assertEqual(context["flusso_futures_alla_lettura"]["funding"]["stato"], funding)
                self.assertEqual(context["flusso_futures_alla_lettura"]["esecuzioni"]["stato"], executions)

    def test_real_bridge_reads_final_clock_after_drive_revision_verification(self):
        bundle = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        drive = self.drive_for(bundle)
        current = self.t + dt.timedelta(minutes=29)
        original_metadata = drive.file_metadata

        def file_metadata(file_id, *, timeout):
            nonlocal current
            current += dt.timedelta(minutes=2)
            return original_metadata(file_id, timeout=timeout)

        clock = mock.Mock(side_effect=lambda: current)
        with (mock.patch.object(drive, "file_metadata", side_effect=file_metadata),
              mock.patch.object(self.bridge, "read_context", wraps=self.bridge.read_context) as validated):
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, clock=clock)
        clock.assert_called_once()
        validated.assert_called_once_with(bundle, now=current, expected_sha256=self.bridge.digest(bundle))
        self.assertEqual(result["stato"], r.STALE)
        self.assertEqual(result["fonti_base"]["mercato"]["stato"], "SCADUTA")
        self.assertEqual(result["fonti_base"]["saldo"]["stato"], "SCADUTA")
        self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
            bundle, now=current, expected_sha256=self.bridge.digest(bundle)))


if __name__ == "__main__":
    unittest.main()
