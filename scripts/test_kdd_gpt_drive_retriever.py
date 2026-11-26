"""KDD G2-C synthetic-only, deterministic recovery and original-bridge comparisons."""
from __future__ import annotations
import builtins
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from unittest import mock

from scripts import kdd_drive_index as index
from scripts import kdd_drive_connector as connector
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


def file_metadata(name, file_id, raw, when=T):
    return {"id": file_id, "name": name, "parents": [FOLDER],
            "size": str(len(raw)), "mimeType": "application/json", "trashed": False,
            "sha256Checksum": hashlib.sha256(raw).hexdigest(),
            "md5Checksum": hashlib.md5(raw).hexdigest(),
            "createdTime": when.isoformat(), "modifiedTime": when.isoformat()}


def publication_files(bundle, file_id, *, raw=None, drive_when=T):
    if raw is None:
        raw = r.canonical(bundle) + b"\n"
    dossier, manifest, obj = index.publication(bundle, raw)
    raw_index = r.canonical(obj) + b"\n"
    files = [file_metadata(manifest, file_id+"-index", raw_index, drive_when),
             file_metadata(dossier, file_id, raw, drive_when)]
    return files, {file_id: raw, file_id+"-index": raw_index}


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
        pages = self.pages
        if self.scan_number >= 2 and self.alter_second_scan is not None:
            pages = self.alter_second_scan
        return copy.deepcopy(pages[0 if token is None else int(token)])

    def file_metadata(self, file_id, *, timeout):
        self.metadata_requests.append(file_id)
        pages = self.alter_second_scan if self.alter_second_scan is not None else self.pages
        return copy.deepcopy(next(file for page in pages for file in page["files"]
                                  if file["id"] == file_id))

    def download(self, file_id, *, max_bytes, timeout):
        self.downloads.append(file_id)
        if self.deny_download:
            raise r.AccessUnavailable("download forbidden")
        return self.blobs[file_id]


def pages_from(files, page_size=999):
    parts = [files[i:i+page_size] for i in range(0, len(files), page_size)] or [[]]
    return [{"files": part, "incompleteSearch": False,
             "nextPageToken": str(i+1) if i+1 < len(parts) else None}
            for i, part in enumerate(parts)]


class RecoveryG2CTests(unittest.TestCase):
    def setUp(self):
        self.files, self.blobs = publication_files(synth_handoff(), "current")
        self.manifest, self.dossier = self.files
        self.validator = mock.Mock(wraps=SyntheticBridge())

    def recover(self, files, blobs=None, *, page_size=999, **driver_kwargs):
        driver = FakeDrive(pages_from(files, page_size), self.blobs if blobs is None else blobs,
                           **driver_kwargs)
        result = r.kdd_get_latest_verified_dossier(driver, FOLDER, validator=self.validator, now=T)
        return result, driver

    def test_kdd_order_survives_inverted_drive_times_and_delayed_reuploads(self):
        old, _ = publication_files(synth_handoff(when=T-dt.timedelta(hours=4)), "old",
                                   drive_when=T+dt.timedelta(days=1))
        for stored in old:
            stored["sha256Checksum"] = "corrupted history, never downloaded"
        reuploaded = [dict(file, id=file["id"]+"-copy") for file in old]
        extras = {"id": "unrelated", "name": "kdd_handoff_notes.md", "parents": ["elsewhere"],
                  "trashed": True}
        result, drive = self.recover([*old, self.manifest, extras, *reuploaded, self.dossier],
                                     page_size=2)
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(result["file_id"], "current")
        self.assertEqual(result["criterio_selezione"], "MASSIMO_PREPARATO_UTC_INDICIZZATO")
        self.assertTrue(result["massimo_preparato_utc_verificato"])
        self.assertEqual(result["nomi_fuori_schema_con_prefisso_kdd"], 1)
        self.assertEqual(drive.downloads, ["current-index", "current"])
        self.validator.validate.assert_called_once()

    def test_current_publication_incomplete_never_falls_back(self):
        old, old_blobs = publication_files(synth_handoff(when=T-dt.timedelta(hours=4)), "old")
        legacy = dict(self.dossier, id="legacy", name="kdd_handoff_"+"a"*64+".json")
        # An unindexed NEWER dossier is a precommit orphan, not a publication:
        # the older indexed pair is selected and its actual stale age reported.
        result, drive = self.recover([self.dossier, *old, legacy],
                                     dict(self.blobs, **old_blobs))
        self.assertEqual(result["stato"], r.STALE)
        self.assertEqual(result["codice"], "FONTI_BASE_SCADUTE")
        self.assertEqual(result["file_id"], "old")
        self.assertEqual(drive.downloads, ["old-index", "old"])
        self.assertEqual(result["dossier_storici_senza_indice"], 1)
        self.validator.reset_mock()
        # A newer INDEX is already a commit claim; missing its dossier MUST
        # remain a blocking failure, with no fallback to an older pair.
        cases = (
            ([self.manifest, *old, legacy], "DOSSIER_INDICIZZATO_NON_ARRIVATO"),
            ([legacy], "INDICE_CORRENTE_ASSENTE"),
        )
        for files, code in cases:
            with self.subTest(code=code, count=len(files)):
                result, drive = self.recover(files)
                self.assertEqual(result["stato"], r.UNVERIFIABLE)
                self.assertEqual(result["codice"], code)
                self.assertFalse(drive.downloads)
                self.assertEqual(result["dossier_storici_senza_indice"], 1)
        self.validator.validate.assert_not_called()

    def test_same_timestamp_distinct_index_digests_are_ambiguous(self):
        another, _ = publication_files(synth_handoff(marker="B"), "another")
        result, drive = self.recover([*self.files, another[0]])
        self.assertEqual(result["codice"], "PUBBLICAZIONE_CORRENTE_AMBIGUA")
        self.assertFalse(drive.downloads)

    def test_current_index_matches_filename_date_and_dossier_identity(self):
        manifest = json.loads(self.blobs["current-index"])
        for key, value, code in (
            ("preparato_utc", (T-dt.timedelta(minutes=1)).isoformat(timespec="microseconds"),
             "INDICE_CORRENTE_INVALIDO"),
            ("snapshot_id", "a"*64, "INDICE_E_DOSSIER_DISCORDANTI"),
            ("snapshot_utc", T.replace(microsecond=1).isoformat(timespec="microseconds"),
             "INDICE_E_DOSSIER_DISCORDANTI"),
            ("dossier", "another.json", "INDICE_CORRENTE_INVALIDO"),
            ("dimensione_byte", manifest["dimensione_byte"]+1, "DIMENSIONE_DOSSIER_DISCORDE_DA_INDICE"),
        ):
            with self.subTest(key=key):
                raw = r.canonical(dict(manifest, **{key: value}))+b"\n"
                files = [file_metadata(self.manifest["name"], "current-index", raw), self.dossier]
                result, _ = self.recover(files, dict(self.blobs, **{"current-index": raw}))
                self.assertEqual(result["codice"], code)
        self.validator.validate.assert_not_called()

    def test_current_index_noncanonical_or_corrupt_blocks_old(self):
        old, _ = publication_files(synth_handoff(when=T-dt.timedelta(hours=4)), "old")
        for raw in (b"broken-json\n", self.blobs["current-index"]+b"\n"):
            with self.subTest(raw_size=len(raw)):
                metadata = file_metadata(self.manifest["name"], "current-index", raw)
                result, drive = self.recover([*old, metadata, self.dossier],
                                             dict(self.blobs, **{"current-index": raw}))
                self.assertEqual(result["stato"], r.UNVERIFIABLE)
                self.assertEqual(result["codice"], "INDICE_CORRENTE_INVALIDO")
                self.assertEqual(drive.downloads, ["current-index"])

    def test_corrupted_current_dossier_rejected_even_with_updated_drive_checksums(self):
        old, _ = publication_files(synth_handoff(when=T-dt.timedelta(hours=4)), "old")
        raw = self.blobs["current"].replace(b'"token":"A"', b'"token":"B"')
        meta = file_metadata(self.dossier["name"], "current", raw)
        result, drive = self.recover([*old, self.manifest, meta], dict(self.blobs, current=raw))
        self.assertEqual(result["codice"], "BYTE_DOSSIER_DISCORDI_DA_INDICE")
        self.assertEqual(drive.downloads, ["current-index", "current"])
        self.validator.validate.assert_not_called()

    def test_identical_copies_share_one_validation_disagreeing_copy_blocks(self):
        copy = dict(self.dossier, id="z-copy")
        result, drive = self.recover([copy, *self.files],
                                     dict(self.blobs, **{"z-copy": self.blobs["current"]}))
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(result["file_id"], "current")
        self.assertEqual(drive.downloads, ["current-index", "current", "z-copy"])
        self.validator.validate.assert_called_once()
        other = self.blobs["current"].replace(b'"token":"A"', b'"token":"B"')
        copy = file_metadata(self.dossier["name"], "z-copy", other)
        result, _ = self.recover([copy, *self.files], dict(self.blobs, **{"z-copy": other}))
        self.assertEqual(result["codice"], "DUPLICATO_CORRENTE_DISCORDANTE")

    def test_large_archive_downloads_only_current_index_and_dossier(self):
        files = []
        for i in range(1200):
            bundle = synth_handoff(when=T-dt.timedelta(minutes=i+1), marker=f"old{i}")
            pair, _ = publication_files(bundle, f"old-{i}")
            files.extend(pair)
        result, drive = self.recover([*files, *self.files], page_size=31)
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertEqual(result["numero_file_indicizzazione"], 2402)
        self.assertEqual((len(drive.requests), len(drive.downloads), self.validator.validate.call_count),
                         (156, 2, 1))
        print("G2-C: 1200 coppie storiche + 1 corrente, 156 richieste lista, 2 download, 1 validazione",
              flush=True)

    def test_access_unavailable_and_inventory_ambiguities(self):
        for kwargs in ({"deny_list": True}, {"deny_download": True}):
            result, _ = self.recover(self.files, **kwargs)
            self.assertEqual(result["stato"], r.ACCESS)
        result, _ = self.recover([*self.files, dict(self.dossier, name="notes")])
        self.assertEqual(result["codice"], "IDENTIFICATIVO_DRIVE_DUPLICATO")
        cases = (
            ([{"files": self.files}], "INVENTARIO_NON_COMPLETO"),
            ([{"files": self.files, "incompleteSearch": True}], "INVENTARIO_NON_COMPLETO"),
            ([{"files": [], "nextPageToken": "1", "incompleteSearch": False}]*2,
             "PAGINAZIONE_INCOERENTE"),
        )
        for pages, code in cases:
            with self.subTest(code=code):
                drive = FakeDrive(pages, self.blobs)
                result = r.kdd_get_latest_verified_dossier(drive, FOLDER, now=T)
                self.assertEqual(result["codice"], code)
                self.assertFalse(drive.downloads)

    def test_race_with_newer_indexed_pair_stops_but_unindexed_orphan_does_not(self):
        earlier, blobs = publication_files(synth_handoff(when=T-dt.timedelta(minutes=1)), "before")
        for files, code in (
            ([*earlier, *self.files], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA"),
            ([*earlier, self.dossier], None),  # uncommitted orphan, ignored
            ([*earlier, self.manifest], "DOSSIER_INDICIZZATO_NON_ARRIVATO"),
        ):
            with self.subTest(expected=code):
                self.validator.reset_mock()
                result, drive = self.recover(earlier, blobs, alter_second_scan=pages_from(files))
                if code is None:
                    self.assertEqual(result["stato"],r.RECOVERED)
                    self.assertEqual(result["file_id"],"before")
                    self.assertEqual(drive.downloads,["before-index","before"])
                    self.validator.validate.assert_called_once()
                else:
                    self.assertEqual(result["stato"],r.UNVERIFIABLE)
                    self.assertEqual(result["codice"],code)
                    self.validator.validate.assert_not_called()

    def test_limits_bound_inventory_and_selected_bytes(self):
        more = [dict(self.dossier, id=f"copy-{i}") for i in range(4)]
        large = [dict(self.dossier, size=r.MAX_BYTES), dict(more[0], size=r.MAX_BYTES)]
        for files, code in (([self.manifest, *large], "LIMITE_BYTE_RECUPERO"),
                            ([self.manifest, *more], "LIMITE_CANDIDATI_CORRENTI")):
            result, drive = self.recover(files)
            self.assertEqual(result["codice"], code)
            self.assertFalse(drive.downloads)
        with mock.patch.object(r, "MAX_INVENTORY_FILES", 1):
            result, _ = self.recover(self.files)
            self.assertEqual(result["codice"], "LIMITE_INVENTARIO")
        with mock.patch.object(r, "MAX_LIST_PAGES", 1):
            result, _ = self.recover(self.files, page_size=1)
            self.assertEqual(result["codice"], "LIMITE_PAGINE")
        with mock.patch.object(r.time, "monotonic", side_effect=[0, 0, 31]):
            result, drive = self.recover(self.files)
        self.assertEqual(result["codice"], "LIMITE_DURATA_RECUPERO")
        self.assertFalse(drive.downloads)

    def test_rfc3339_drive_dates_support_nanoseconds_and_offsets(self):
        for created, modified, code in (
            ("2026-11-20T12:00:00.123456789Z", "2026-11-20t13:00:00.12345678900+01:00",
             "FONTI_BASE_RECENTI"),
            ("2026-11-20T12:00:00.123456789Z", "2026-11-20T12:00:00.123456788Z",
             "FONTI_BASE_RECENTI"),
            ("2026-11-20T12:00:00Z", "2010-01-01", "TIMESTAMP_DRIVE_INVALIDO"),
            ("2026-11-20T12:00:00+03:70", None, "TIMESTAMP_DRIVE_INVALIDO"),
            ("2016-12-31T23:59:60.9Z", "2017-01-01T00:00:00Z", "FONTI_BASE_RECENTI"),
            ("2016-12-30T23:59:60Z", None, "TIMESTAMP_DRIVE_INVALIDO"),
        ):
            with self.subTest(created=created, modified=modified):
                changed = dict(self.dossier, createdTime=created, modifiedTime=modified)
                result, _ = self.recover([self.manifest, changed])
                self.assertEqual(result["codice"], code)

    def test_invalid_candidate_metadata_fails_closed(self):
        for changed, code in (
            ({"parents": ["OTHER"]}, "CARTELLA_ORIGINE_NON_ATTESTATA"),
            ({"trashed": True}, "ELEMENTO_CESTINATO_NELLA_RISPOSTA"),
            ({"mimeType": "application/vnd.google-apps.shortcut"}, "TIPO_FILE_NON_BINARY"),
            ({"name": index.INDEX_PREFIX+"incorrect.json"}, "NOME_PUBBLICAZIONE_KDD_INVALIDO"),
        ):
            with self.subTest(code=code):
                result, driver = self.recover([self.manifest, dict(self.dossier, **changed)])
                self.assertEqual(result["codice"], code)
                self.assertFalse(driver.downloads)

    def test_versions_include_both_files_and_detect_changes_at_either_check(self):
        pair = [dict(file, version="1", headRevisionId="revision-1") for file in self.files]
        for changed_position, field in ((0, "headRevisionId"), (1, "version")):
            candidate = pair[changed_position]
            changed = dict(candidate, **{field: "2"})
            second = pair.copy()
            second[changed_position] = changed
            result, _ = self.recover(pair, alter_second_scan=pages_from(second))
            self.assertEqual(result["codice"], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")
            drive = FakeDrive(pages_from(pair), self.blobs)
            original = drive.file_metadata

            def point(file_id, *, timeout):
                return changed if file_id == changed["id"] else original(file_id, timeout=timeout)

            with mock.patch.object(drive, "file_metadata", side_effect=point):
                result = r.kdd_get_latest_verified_dossier(drive, FOLDER, validator=self.validator, now=T)
            self.assertEqual(result["codice"], "VERSIONE_CORRENTE_CAMBIATA_DURANTE_LA_LETTURA")
        self.validator.validate.assert_not_called()
        result, drive = self.recover(pair)
        self.assertEqual(drive.metadata_requests, ["current-index", "current"])
        self.assertEqual(result["numero_controlli_versione"], 2)
        self.assertFalse(result["atomicita_inventario"])

    def test_provider_checksums_augmented_by_index(self):
        result, _ = self.recover([self.manifest, dict(self.dossier, sha256Checksum="0"*64)])
        self.assertEqual(result["codice"], "CHECKSUM_DRIVE_DISCORDANTE")
        result, drive = self.recover([self.manifest, dict(self.dossier, sha256Checksum=None)])
        self.assertEqual(result["stato"], r.RECOVERED)
        self.assertFalse(result["sha256_drive_confrontato"])
        self.assertEqual(result["integrita_origine"], "NON_AUTENTICATA")
        self.assertEqual(drive.downloads, ["current-index", "current"])

    def test_canonical_and_unique_keys_still_required_for_dossier(self):
        raw = self.blobs["current"]
        for changed, code in (
            (raw+b"\n", "BYTE_NON_CANONICI"),
            (raw[:-2]+b',"schema":"kdd_private_handoff_v001"}\n', "JSON_DUPLICATE_KEYS"),
        ):
            files, blobs = publication_files(synth_handoff(), "malformed", raw=changed)
            result, _ = self.recover(files, blobs)
            self.assertEqual(result["codice"], code)

    def test_missing_real_bridge_fails_closed(self):
        driver = FakeDrive(pages_from(self.files), self.blobs)
        original_import = builtins.__import__

        def unavailable_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "scripts" and "kdd_bridge_g2" in (fromlist or ()):
                raise ImportError("synthetic missing bridge")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=unavailable_import):
            result = r.kdd_get_latest_verified_dossier(driver, FOLDER, now=T)
        self.assertEqual(result["codice"], "VALIDATORE_KDD_INDISPONIBILE")

    def test_rest_adapter_scopes_queries_and_enforces_transport_contract(self):
        def json_get(url, params, **bounds):
            return {}
        with mock.patch.object(r.DriveV3ReadOnlyAdapter, "ROOT", "https://example.test/files"):
            rows = mock.Mock(side_effect=json_get)
            bytes_get = mock.Mock(return_value=b"sample")
            drive = r.DriveV3ReadOnlyAdapter(FOLDER, rows, bytes_get)
            drive.list_page("opaque", timeout=5)
            drive.download("file/a", timeout=2, max_bytes=8)
            drive.file_metadata("file/a", timeout=1)
        self.assertIn(FOLDER, rows.call_args_list[0].args[1]["q"])
        self.assertIn("headRevisionId", rows.call_args_list[0].args[1]["fields"])
        self.assertEqual(rows.call_args_list[0].args[1]["pageToken"], "opaque")
        self.assertEqual(rows.call_args_list[0].kwargs["max_bytes"], r.MAX_METADATA_BYTES)
        self.assertEqual(rows.call_args_list[1].args[0], "https://example.test/files/file%2Fa")
        self.assertEqual(bytes_get.call_args.args[1]["alt"], "media")
        self.assertEqual(bytes_get.call_args.kwargs, {"timeout": 2, "max_bytes": 8})


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
        files, blobs = publication_files(bundle, "real-bridge")
        for file in files:
            file.update(version="1", headRevisionId="rev-original")
        return FakeDrive(pages_from(files), blobs)

    def test_actual_export_files_recover_through_original_bridge(self):
        from scripts import kdd_drive_exchange as exchange
        from scripts import test_kdd_bridge_g2 as fixtures

        fixture = fixtures.BridgeG2Tests("test_02_freshness_reevaluated_at_read")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        sync = fixture.home / "synthetic-sync"
        sync.mkdir()
        with (mock.patch.object(exchange, "EXCHANGE_ROOT", sync),
              mock.patch.object(self.bridge, "prepare", return_value=fixture.bundle)):
            exported = exchange.prepare_export()
        blobs = {path.name: path.read_bytes() for path in sync.iterdir()}
        drive = FakeDrive(pages_from([file_metadata(name, name, raw) for name, raw in blobs.items()]), blobs)
        result = r.kdd_get_latest_verified_dossier(drive, FOLDER, now=self.t)
        self.assertEqual(result["nome"], exported)
        self.assertEqual(drive.downloads, [result["nome_indice"], exported])
        self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
            fixture.bundle, now=self.t, expected_sha256=self.bridge.digest(fixture.bundle)))

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
            current += dt.timedelta(minutes=1)
            return original_metadata(file_id, timeout=timeout)

        clock = mock.Mock(side_effect=lambda: current)
        with (mock.patch.object(drive, "file_metadata", side_effect=file_metadata),
              mock.patch.object(self.bridge, "read_context", wraps=self.bridge.read_context) as validated):
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, clock=clock)
        self.assertEqual(clock.call_count, 2)
        validated.assert_called_once_with(bundle, now=current, expected_sha256=self.bridge.digest(bundle))
        self.assertEqual(result["stato"], r.STALE)
        self.assertEqual(result["fonti_base"]["mercato"]["stato"], "SCADUTA")
        self.assertEqual(result["fonti_base"]["saldo"]["stato"], "SCADUTA")
        self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
            bundle, now=current, expected_sha256=self.bridge.digest(bundle)))

    def test_real_bridge_revalidates_when_sources_expire_during_bridge_or_presentation(self):
        bundle = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        first = self.t + dt.timedelta(minutes=30, milliseconds=-500)
        read_context = self.bridge.read_context
        present = r._presentation
        for phase in ("bridge", "presentation"):
            with self.subTest(phase=phase):
                current = first

                def advance():
                    nonlocal current
                    if current == first:
                        current += dt.timedelta(seconds=1)

                def validation(*args, **kwargs):
                    result = read_context(*args, **kwargs)
                    if phase == "bridge":
                        advance()
                    return result

                def presentation(*args, **kwargs):
                    result = present(*args, **kwargs)
                    if phase == "presentation":
                        advance()
                    return result

                with (mock.patch.object(self.bridge, "read_context", side_effect=validation) as validated,
                      mock.patch.object(r, "_presentation", side_effect=presentation)):
                    result = r.kdd_get_latest_verified_dossier(
                        self.drive_for(bundle), FOLDER, clock=lambda: current)
                self.assertEqual([call.kwargs["now"] for call in validated.call_args_list],
                                 [first, first+r.VALIDATION_WINDOW, current])
                self.assertEqual(result["stato"], r.STALE)
                self.assertEqual(result["validita_controllata_utc"], current.isoformat())
                self.assertEqual(result["contesto_kdd"], read_context(
                    bundle, now=current, expected_sha256=self.bridge.digest(bundle)))

    def test_real_bridge_freshness_window_stable_or_explicit_stop(self):
        bundle = self.bridge.prepare(self.fixture.root, now=self.t, _fixture=True)
        read_context = self.bridge.read_context
        for remaining, outcome in ((5, r.RECOVERED), (0.5, r.UNVERIFIABLE)):
            with self.subTest(remaining=remaining):
                started = self.t + dt.timedelta(minutes=30, seconds=-remaining)
                current = started

                def validation(*args, **kwargs):
                    nonlocal current
                    result = read_context(*args, **kwargs)
                    current += dt.timedelta(milliseconds=50)
                    return result

                with mock.patch.object(self.bridge, "read_context", side_effect=validation) as checked:
                    result = r.kdd_get_latest_verified_dossier(
                        self.drive_for(bundle), FOLDER, clock=lambda: current)
                self.assertEqual(result["stato"], outcome)
                if outcome == r.RECOVERED:
                    self.assertEqual(checked.call_count, 2)
                    self.assertEqual(result["validita_controllata_utc"], current.isoformat())
                    self.assertEqual(result["contesto_kdd"], read_context(
                        bundle, now=started, expected_sha256=self.bridge.digest(bundle)))
                else:
                    self.assertEqual(checked.call_count, 4)
                    self.assertEqual(result["codice"], "FRESCHEZZA_FINALE_NON_GARANTITA")
                    self.assertNotIn("contesto_kdd", result)


    def _fresh01_bundle(self, candidates=("SOL", "ZZTEST"), *, requested=True):
        """Real wallet producer + economic monitor; all inputs invented."""
        import kdd_economics as econ
        import kdd_economic_sources as primary
        iso = self.t.isoformat()
        def row(i, token, pair, group):
            key = pair.replace("/", "")
            base, quote = pair.split("/")
            ident = econ.identify(token, pair, key, catalog={
                key: {"pair_key": key, "pair": pair, "base": base, "quote": quote}})
            payload = release = None
            if token == "ADA":
                payload = {"id": ident["coingecko_id"], "symbol": "ada",
                           "name": ident["progetto"], "market_data": {
                               "last_updated": iso, "circulating_supply": 100,
                               "total_supply": 120, "max_supply": 150,
                               "market_cap": {"usd": 1000},
                               "fully_diluted_valuation": {"usd": 1500}}}
                release = {"html_url": "https://github.com/" + ident["repository_primario"]
                           + "/releases/tag/v-synthetic", "tag_name": "v-synthetic",
                           "published_at": iso, "name": "Synthetic release",
                           "draft": False, "prerelease": False}
            out = {"indice": i, "token": token, "identita": ident,
                   "fondamentali": econ.fundamentals(ident, payload, self.t, self.t),
                   "evento": econ.release_event(ident, release, self.t, self.t)}
            if group != "posizioni":
                out["coppia_analisi"] = pair
            if group == "richiesti":
                out.update(richiesto_utc=iso, origine="CLI_ESPLICITO_LOCALE")
            return out
        f = self.fixture
        f.snapshot["schede_v02"] = [
            {"token": token, "esito": "RIESAME MIRATO", "categoria": "ripartenza",
             "coppia_analisi": token + "/USD", "evidenze": ["Synthetic"], "criticita": []}
            for token in candidates]
        f.dossier["candidati"] = [{"token": token, "coppia_analisi": token + "/USD"}
                                for token in candidates]
        positions = [row(i, x["token"], x["token"] + "/EUR", "posizioni")
                     for i, x in enumerate(f.portfolio["posizioni"])]
        shortlist = [row(i, token, token + "/USD", "candidati")
                     for i, token in enumerate(candidates)]
        requested_rows = [row(0, "QQTEST", "QQTEST/EUR", "richiesti")] if requested else []
        roster = {"posizioni": positions, "candidati": shortlist, "richiesti": requested_rows}
        def no_network(url):
            raise AssertionError("No external I/O in this fixture: " + url)
        monitor = primary.collect(self.t, roster, {}, no_network, network_allowed=False)
        f.dossier["asset_richiesti_espliciti"] = [
            {k: item[k] for k in ("token", "coppia_analisi", "richiesto_utc", "origine")}
            for item in requested_rows]
        f.dossier["evidenze_economiche"] = dict(
            roster, schema=econ.VERSION, acquisito_utc=iso, monitor_fonti=monitor,
            macro=econ.macro([], self.t), fonti_economiche=econ.sources_matrix(),
            regime={"stato": "INDETERMINATO", "qualita": "INSUFFICIENTE"})
        f.dump()
        return self.bridge.prepare(f.root, now=self.t, _fixture=True)

    def _fresh01_advancing(self, bundle, start, milliseconds=50):
        ticks = iter(range(100))
        return r.kdd_get_latest_verified_dossier(
            self.drive_for(bundle), FOLDER,
            clock=lambda: start + dt.timedelta(milliseconds=milliseconds * next(ticks)))

    def test_fresh01_original_bridge_advancing_clock_recent_stale_and_rosters(self):
        for candidates, requested in ((("SOL", "ZZTEST"), True),
                                      (("ZZTEST", "ETH", "YYTEST"), False),
                                      ((), True)):
            bundle = self._fresh01_bundle(candidates, requested=requested)
            for delta, outcome in ((dt.timedelta(minutes=5), r.RECOVERED),
                                   (dt.timedelta(hours=4), r.STALE)):
                with self.subTest(candidates=candidates, requested=requested, outcome=outcome):
                    when = self.t + delta
                    expected = self.bridge.read_context(
                        bundle, now=when, expected_sha256=self.bridge.digest(bundle))
                    economy = expected["evidenze_economiche_alla_lettura"]
                    self.assertEqual(len(economy["candidati"]), len(candidates))
                    self.assertEqual(len(economy["richiesti"]), int(requested))
                    self.assertEqual(economy["posizioni"][0]["identita"]["stato"],
                                     "IDENTITA_VERIFICATA_DA_CATALOGO")
                    self.assertEqual(economy["posizioni"][2]["identita"]["stato"],
                                     "NON_VERIFICATO")
                    result = self._fresh01_advancing(bundle, when)
                    self.assertEqual((result["stato"], result["codice"]),
                                     (outcome, "FONTI_BASE_RECENTI" if outcome == r.RECOVERED
                                      else "FONTI_BASE_SCADUTE"))
                    self.assertEqual(result["contesto_kdd"], expected)
                    self.assertGreater(dt.datetime.fromisoformat(result["validita_controllata_utc"]),
                                       when)
                    self.assertEqual(result["integrita_documento"], "VERIFICATA")
                    self.assertEqual(economy["monitor_fonti"]["letto_utc"], expected["letto_utc"])

    def test_fresh01_real_clock_and_true_ttl_boundary(self):
        bundle = self._fresh01_bundle()
        # No mocked wall clock: the original bridge and the recuperator read
        # actual UTC. A dated fixture must remain stale, never appear refreshed.
        actual = dt.datetime.now(dt.timezone.utc)
        real = r.kdd_get_latest_verified_dossier(self.drive_for(bundle), FOLDER)
        self.assertEqual(real["stato"], r.STALE)
        self.assertGreaterEqual(dt.datetime.fromisoformat(real["validita_controllata_utc"]), actual)
        self.assertEqual(real["contesto_kdd"]["evidenze_economiche_alla_lettura"]
                         ["monitor_fonti"]["acquisito_utc"], self.t.isoformat())
        first = self.t + dt.timedelta(minutes=30, milliseconds=-500)
        result = self._fresh01_advancing(bundle, first)
        self.assertEqual((result["stato"], result["codice"]),
                         (r.UNVERIFIABLE, "FRESCHEZZA_FINALE_NON_GARANTITA"))
        self.assertNotIn("contesto_kdd", result)
        after = first + dt.timedelta(seconds=1)
        clock = iter((first, after, after, after))
        settled = r.kdd_get_latest_verified_dossier(
            self.drive_for(bundle), FOLDER, clock=lambda: next(clock))
        self.assertEqual((settled["stato"], settled["codice"]),
                         (r.STALE, "FONTI_BASE_SCADUTE"))
        self.assertEqual(settled["contesto_kdd"], self.bridge.read_context(
            bundle, now=after, expected_sha256=self.bridge.digest(bundle)))

    def test_fresh01_compare_keeps_real_acquisition_provenance_and_changes(self):
        bundle = self._fresh01_bundle()
        when = self.t + dt.timedelta(minutes=5)
        digest = self.bridge.digest(bundle)
        left = self.bridge.read_context(bundle, now=when, expected_sha256=digest)
        right = self.bridge.read_context(bundle, now=when+r.VALIDATION_WINDOW,
                                         expected_sha256=digest)
        originals = copy.deepcopy((left, right))
        self.assertEqual(r._without_read_clock(left), r._without_read_clock(right))
        self.assertEqual((left, right), originals)
        econ = left["evidenze_economiche_alla_lettura"]
        self.assertEqual(econ["posizioni"][0]["fondamentali"]["stato"], "VERIFICATO")
        self.assertEqual(econ["posizioni"][0]["evento"]["stato"], "VERIFICATO")
        self.assertEqual(econ["posizioni"][1]["evento"]["stato"], "NON_VERIFICATO")
        # Isolate single-field variations in authentic generated contexts.
        # Even a verified identity's unsuccessful acquisition is not a clock.
        for group, idx, field, key, value in (
            ("posizioni", 0, "fondamentali", "acquisito_utc",
             (self.t+dt.timedelta(seconds=1)).isoformat()),
            ("posizioni", 0, "evento", "acquisito_utc",
             (self.t+dt.timedelta(seconds=1)).isoformat()),
            ("posizioni", 1, "evento", "acquisito_utc", right["letto_utc"]),
            ("posizioni", 0, "fondamentali", "capitalizzazione_usd", 9999),
            ("candidati", 1, "evento", "sintesi", "Changed"),
            ("candidati", 1, "identita", "motivo", "Changed"),
            ("richiesti", 0, "fondamentali", "acquisito_utc", self.t.isoformat()),
        ):
            with self.subTest(group=group, field=field, key=key):
                changed = copy.deepcopy(right)
                changed["evidenze_economiche_alla_lettura"][group][idx][field][key] = value
                self.assertNotEqual(r._without_read_clock(left), r._without_read_clock(changed))
        changed = copy.deepcopy(right)
        changed["evidenze_economiche_alla_lettura"]["monitor_fonti"]["acquisito_utc"] = right["letto_utc"]
        self.assertNotEqual(r._without_read_clock(left), r._without_read_clock(changed))
        # A mismatched read clock is not normalized as if it were generated.
        changed = copy.deepcopy(right)
        changed["evidenze_economiche_alla_lettura"]["monitor_fonti"]["letto_utc"] = self.t.isoformat()
        self.assertNotEqual(r._without_read_clock(left), r._without_read_clock(changed))

    def test_fresh01_original_bridge_preserves_clock_and_document_stops(self):
        bundle = self._fresh01_bundle()
        when = self.t + dt.timedelta(minutes=5)
        for times, expected in (
            ((when, when-dt.timedelta(seconds=1)), "OROLOGIO_ARRETRATO_DURANTE_VALIDAZIONE"),
            ((when, when+dt.timedelta(seconds=3), when+dt.timedelta(seconds=6)),
             "FRESCHEZZA_FINALE_NON_GARANTITA"),
        ):
            clock = iter(times)
            answer = r.kdd_get_latest_verified_dossier(
                self.drive_for(bundle), FOLDER, clock=lambda: next(clock))
            self.assertEqual((answer["stato"], answer["codice"]), (r.UNVERIFIABLE, expected))
            self.assertNotIn("contesto_kdd", answer)
        # Authentic semantic validation still rejects a rehashed bad identity.
        tampered = copy.deepcopy(bundle)
        packet = tampered["packet"]
        packet["evidenze_multifonte"]["economia"]["posizioni"][0]["identita"]["coingecko_id"] = "bitcoin"
        tampered["packet_sha256"] = self.bridge.digest(packet)
        result = r.kdd_get_latest_verified_dossier(self.drive_for(tampered), FOLDER, now=when)
        self.assertEqual((result["stato"], result["codice"]),
                         (r.UNVERIFIABLE, "VALIDATORE_KDD_NON_SUPERATO"))
        self.assertNotIn("contesto_kdd", result)


class ConnectorCaptureTests(unittest.TestCase):
    def setUp(self):
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as fixtures

        self.bridge = bridge
        self.when = fixtures.T
        fixture = fixtures.WalletPacketG0Tests("test_wallet_first_all_assets_even_if_quote_missing")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.bundle = bridge.prepare(fixture.root, now=self.when, _fixture=True)
        self.capture = fixture.root / "capture"
        self.capture.mkdir()
        (self.capture / "blobs").mkdir()
        (self.capture / "prima-prove").mkdir()
        (self.capture / "dopo-prove").mkdir()
        self.files, self.blobs = publication_files(self.bundle, "captured")
        for file, (created, modified) in zip(self.files, (
                ("07:35:04.727", "07:34:05.155"), ("07:35:05.209", "07:34:05.091"))):
            file.update(createdTime="2026-11-21T"+created+"Z",
                        modifiedTime="2026-11-21T"+modified+"Z", version="3")
        self.write_capture()

    def write_capture(self, *, after=None, include_older=True):
        def normalized(row):
            names = {
                "id": "id", "name": "title", "mimeType": "mime_type", "parents": "parent_ids",
                "createdTime": "created_time", "modifiedTime": "modified_time",
                "headRevisionId": "head_revision_id", "sha256Checksum": "sha256_checksum",
                "md5Checksum": "md5_checksum", "size": "size_bytes",
            }
            return {names.get(key, key): value for key, value in row.items()}

        older, _ = publication_files(synth_handoff(
            when=self.when-dt.timedelta(hours=1)), "older")
        if not include_older:
            older = []
        for filename, files in (("prima.json", self.files),
                                ("dopo.json", self.files if after is None else after)):
            scan = {
                "folder_id": FOLDER,
                "pages": [
                    {"requested_page_token": None,
                     "response": {"files": list(map(normalized, older)), "next_page_token": "opaque"}},
                    {"requested_page_token": "opaque",
                     "response": {"files": list(map(normalized, files))}},
                ],
            }
            (self.capture / filename).write_bytes(r.canonical(scan))
        for folder in ("prima-prove", "dopo-prove"):
            for file in self.files:
                (self.capture / folder / (file["id"]+".json")).write_bytes(
                    r.canonical({"metadata": normalized(file)}))
        for file_id, raw in self.blobs.items():
            (self.capture / "blobs" / file_id).write_bytes(raw)

    def recover(self, when=None):
        reader = connector.ConnectorCaptureReader(FOLDER, self.capture)
        return r.kdd_get_latest_verified_dossier(reader, FOLDER, now=when or self.when)

    def test_observed_foldersync_timestamps_on_current_pair_with_real_bridge(self):
        plan = connector.plan_downloads(connector.ConnectorCaptureReader(FOLDER, self.capture))
        self.assertEqual([item["id"] for item in plan["file"]], ["captured-index", "captured"])
        for when, expected, status in (
            (self.when, r.RECOVERED, "RECENTE"),
            (self.when+dt.timedelta(hours=2), r.STALE, "SCADUTA"),
        ):
            with self.subTest(when=when):
                result = self.recover(when)
                self.assertEqual(result["stato"], expected)
                self.assertEqual(result["integrita_documento"], "VERIFICATA")
                self.assertEqual(result["integrita_origine"], "NON_AUTENTICATA")
                self.assertEqual(result["numero_controlli_versione"], 2)
                self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
                    self.bundle, now=when, expected_sha256=self.bridge.digest(self.bundle)))
                self.assertTrue(result["limiti_analitici"]["lacune_da_verificare"])
                for label in ("mercato", "saldo"):
                    self.assertEqual(result["fonti_base"][label]["stato"], status)

    def test_connector_plans_only_indexed_pair_with_newer_orphan(self):
        newer = dict(self.bundle, preparato_utc=(self.when + dt.timedelta(seconds=1)).isoformat())
        (_, orphan), _ = publication_files(newer, "orphan")
        pair = self.files
        raw_ids = ["captured-index", "captured"]
        for orphan_in_first_scan in (True, False):
            with self.subTest(orphan_in_first_scan=orphan_in_first_scan):
                self.files = [*pair, orphan] if orphan_in_first_scan else pair
                self.write_capture(after=[*pair, orphan])
                reader = connector.ConnectorCaptureReader(FOLDER, self.capture)
                plan = connector.plan_downloads(reader)
                self.assertEqual([file["id"] for file in plan["file"]], raw_ids)
                reader = connector.ConnectorCaptureReader(FOLDER, self.capture)
                with mock.patch.object(reader, "download", wraps=reader.download) as download:
                    result = r.kdd_get_latest_verified_dossier(reader, FOLDER, now=self.when)
                self.assertEqual(result["stato"], r.RECOVERED)
                self.assertEqual(result["file_id"], "captured")
                self.assertEqual([call.args[0] for call in download.call_args_list], raw_ids)
                self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
                    self.bundle, now=self.when, expected_sha256=self.bridge.digest(self.bundle)))

        self.files = [*pair, orphan]
        self.write_capture(after=[*pair, dict(orphan, version="4")])
        self.assertEqual(self.recover()["codice"], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")

    def test_connector_uses_read_clock_after_raw_capture(self):
        reader = connector.ConnectorCaptureReader(FOLDER, self.capture)
        clock = self.when
        raw_ids = []
        real_download = reader.download

        def download(file_id, **bounds):
            nonlocal clock
            raw_ids.append(file_id)
            raw = real_download(file_id, **bounds)
            clock = self.when + dt.timedelta(hours=2)
            return raw

        with mock.patch.object(reader, "download", side_effect=download):
            result = r.kdd_get_latest_verified_dossier(reader, FOLDER, clock=lambda: clock)
        self.assertEqual(raw_ids, ["captured-index", "captured"])
        self.assertEqual(result["stato"], r.STALE)
        self.assertEqual(result["codice"], "FONTI_BASE_SCADUTE")
        self.assertEqual(result["contesto_kdd"], self.bridge.read_context(
            self.bundle, now=clock, expected_sha256=self.bridge.digest(self.bundle)))

    def test_bad_timestamp_and_metadata_change_still_stop(self):
        valid = self.files
        self.files = [dict(valid[0], createdTime="2026-11-21T07:35:04.727"), valid[1]]
        self.write_capture()
        self.assertEqual(self.recover()["codice"], "TIMESTAMP_DRIVE_INVALIDO")
        self.files = valid
        changed = [dict(valid[0], modifiedTime="2026-11-21T07:34:04Z"), valid[1]]
        self.write_capture(after=changed)
        self.assertEqual(self.recover()["codice"], "INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")
        self.write_capture()
        point = self.capture / "dopo-prove/captured-index.json"
        receipt = json.loads(point.read_bytes())
        receipt["metadata"]["version"] = "4"
        point.write_bytes(r.canonical(receipt))
        self.assertEqual(self.recover()["codice"], "METADATI_PUNTUALI_DISCORDI_DA_INVENTARIO")

    def test_partial_publication_and_missing_raw_bytes_never_fall_back(self):
        files = self.files
        for row, code in ((files[1], "INDICE_CORRENTE_ASSENTE"),
                          (files[0], "DOSSIER_INDICIZZATO_NON_ARRIVATO")):
            with self.subTest(code=code):
                self.files = [row]
                self.write_capture(include_older=row is files[0])
                self.assertEqual(self.recover()["codice"], code)
        self.files = files
        self.write_capture()
        (self.capture / "blobs/captured").unlink()
        self.assertEqual(self.recover()["codice"], "BYTE_CONNETTORE_ASSENTI")

    def test_invalid_payload_rejected_even_with_preserved_modified_time(self):
        raw = self.blobs["captured"]
        altered = raw.replace(b'"ADA"', b'"XYZ"', 1)
        self.assertNotEqual(altered, raw)
        self.blobs["captured"] = altered
        # Even provider checksums for the altered version cannot supersede the index.
        provider = file_metadata(self.files[1]["name"], "captured", altered)
        self.files[1].update(sha256Checksum=provider["sha256Checksum"],
                             md5Checksum=provider["md5Checksum"])
        self.write_capture()
        result = self.recover()
        self.assertEqual(result["codice"], "BYTE_DOSSIER_DISCORDI_DA_INDICE")
        self.assertNotIn("contesto_kdd", result)

    def test_connector_cannot_invent_trash_state_or_skip_pages(self):
        path = self.capture / "prima.json"
        original = json.loads(path.read_bytes())
        incomplete = copy.deepcopy(original)
        incomplete["pages"].pop()
        path.write_bytes(r.canonical(incomplete))
        self.assertEqual(self.recover()["codice"], "PAGINA_CONNETTORE_ASSENTE")
        original["pages"][1]["response"]["files"][0].pop("trashed")
        path.write_bytes(r.canonical(original))
        point = self.capture / "prima-prove/captured-index.json"
        receipt = json.loads(point.read_bytes())
        receipt["metadata"].pop("trashed")
        point.write_bytes(r.canonical(receipt))
        self.assertEqual(self.recover()["codice"], "FILTRO_CANDIDATO_CONNETTORE_NON_DOCUMENTATO")

    def test_observed_normalization_requires_positive_evidence_for_exact_id(self):
        for phase in ("prima", "dopo"):
            path = self.capture / (phase + ".json")
            scan = json.loads(path.read_bytes())
            for row in scan["pages"][1]["response"]["files"]:
                row["parent_ids"] = None
                row.pop("trashed")
                row.pop("version")
                receipt_path = self.capture / (phase + "-prove") / (row["id"]+".json")
                receipt = json.loads(receipt_path.read_bytes())
                receipt["metadata"].pop("trashed")
                receipt["metadata"].pop("version")
                query = f"'{FOLDER}' in parents and trashed = false and name = '{row['title']}'"
                receipt["search"] = {"query": query, "results": [
                    {"id": "different-id", "title": row["title"]}]}
                receipt_path.write_bytes(r.canonical(receipt))
            path.write_bytes(r.canonical(scan))
        self.assertEqual(self.recover()["codice"], "STATO_CESTINO_NON_ATTESTATO_DAL_CONNETTORE")
        for phase in ("prima", "dopo"):
            for path in (self.capture / (phase + "-prove")).iterdir():
                receipt = json.loads(path.read_bytes())
                receipt["search"]["results"][0]["id"] = receipt["metadata"]["id"]
                if receipt["metadata"]["id"] == "captured":
                    receipt["search"]["results"][0]["size_bytes"] = int(receipt["metadata"]["size_bytes"])
                path.write_bytes(r.canonical(receipt))
        answer = self.recover()
        self.assertEqual(answer["stato"], r.RECOVERED)
        self.assertEqual(answer["stabilita_versioni_drive"], "NON_ATTESTATA")
        self.assertEqual(answer["numero_controlli_versione"], 0)
        self.assertEqual(answer["attestazioni_drive"]["captured"],
                         {"cartella": "METADATI_PROVIDER", "cestino": "FILTRO_PROVIDER"})
        self.assertFalse(answer["atomicita_inventario"])

    def assert_filter_rejected_before_download(self, rows, expected):
        for phase in ("prima", "dopo"):
            path = self.capture / (phase + ".json")
            scan = json.loads(path.read_bytes())
            for row in scan["pages"][1]["response"]["files"]:
                row.pop("trashed")
                receipt_path = self.capture / (phase + "-prove") / (row["id"] + ".json")
                receipt = json.loads(receipt_path.read_bytes())
                receipt["metadata"].pop("trashed")
                receipt["search"] = {
                    "query": connector._candidate_query(FOLDER, row["title"]),
                    "results": rows(row) if row["id"] == "captured" else [
                        {"id": row["id"], "title": row["title"]}],
                }
                receipt_path.write_bytes(r.canonical(receipt))
            path.write_bytes(r.canonical(scan))

        reader = connector.ConnectorCaptureReader(FOLDER, self.capture)
        with mock.patch.object(reader, "download", wraps=reader.download) as download:
            result = r.kdd_get_latest_verified_dossier(reader, FOLDER, now=self.when)
        self.assertEqual((result["stato"], download.call_count), (r.UNVERIFIABLE, 0))
        self.assertEqual(result["codice"], expected)
        self.assertNotIn("contesto_kdd", result)

        process = subprocess.run([sys.executable, "-S", "-B", "-m", "scripts.kdd_drive_connector",
                                  "plan", FOLDER, str(self.capture)],
                                 capture_output=True, text=True, timeout=10)
        plan = json.loads(process.stdout)
        self.assertEqual((process.returncode, plan["stato"], plan["codice"]),
                         (2, r.UNVERIFIABLE, expected))
        self.assertNotIn("file", plan)

    def test_filter_rejects_conflicting_size_before_any_download(self):
        self.assert_filter_rejected_before_download(
            lambda row: [{"id": row["id"], "title": row["title"],
                          "size_bytes": int(row["size_bytes"]) + 1}],
            "DIMENSIONE_FILTRO_CONNETTORE_DISCORDE")

    def test_filter_rejects_two_names_for_same_id_before_any_download(self):
        self.assert_filter_rejected_before_download(
            lambda row: [{"id": row["id"], "title": row["title"]},
                         {"id": row["id"], "title": "altro-nome.json"}],
            "IDENTITA_FILTRO_CONNETTORE_DISCORDE")

    def test_checkout_module_entry_point_runs_as_separate_python_process(self):
        command = [sys.executable, "-B", "-m", "scripts.kdd_drive_connector"]
        for action in ("plan", "validate"):
            with self.subTest(action=action):
                process = subprocess.run([*command, action, FOLDER, str(self.capture)],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                if action == "plan":
                    self.assertEqual(result["stato"], "PIANO_DOWNLOAD")
                else:
                    self.assertEqual(result["integrita_documento"], "VERIFICATA")
                    self.assertEqual(result["contesto_kdd"]["schema"], "kdd_gpt_read_context_v001")


if __name__ == "__main__":
    unittest.main()
