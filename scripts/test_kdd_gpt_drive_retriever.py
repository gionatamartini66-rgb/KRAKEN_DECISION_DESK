"""KDD G2-A synthetic-only, deterministic recovery and original-bridge comparisons."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import importlib.util
import json
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
        saldo = dt.datetime.fromisoformat(pkt["saldo"]["ultima_acquisizione_utc"])
        if observed > when + dt.timedelta(minutes=2):
            raise ValueError("future")
        state = lambda timestamp: "RECENTE" if when - timestamp <= dt.timedelta(minutes=30) else "DA_AGGIORNARE"
        return {"schema": "kdd_gpt_read_context_v001", "snapshot_utc": pkt["rilevazione_kdd_utc"],
                "mercato": {"stato": state(observed)}, "saldo": {"stato": state(saldo)},
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
    fid = "synthetic-" + marker + str(when.hour)
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

    def list_page(self, token):
        if self.deny_list:
            raise r.AccessUnavailable("revoked")
        if token is None:
            self.scan_number += 1
        self.requests.append(token)
        pages = self.alter_second_scan if self.scan_number >= 2 and self.alter_second_scan is not None else self.pages
        index = 0 if token is None else int(token)
        return copy.deepcopy(pages[index])

    def download(self, file_id):
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


class RecoveryG2ATests(unittest.TestCase):
    def recover(self, files, blobs, **kwargs):
        driver = FakeDrive(pages_from(files), blobs, **kwargs)
        return r.kdd_get_latest_verified_dossier(driver, FOLDER,
                                                  validator=SyntheticBridge(), now=T), driver

    def test_multipage_full_inventory_latest_timestamp_not_drive_order(self):
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
        self.assertTrue(answer["sha256_drive_confrontato"])
        self.assertNotEqual(answer["digest_logico"], answer["sha256_byte"])

    def test_corrupted_newest_never_falls_back_to_old(self):
        a, ba = file_and_bytes(when=T-dt.timedelta(minutes=10), marker="OLD")
        b, bb = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        bb = bb.replace(b'"NEW"', b'"BAD"')
        outcome, _ = self.recover([a, b], {a["id"]: ba, b["id"]: bb})
        self.assertEqual(outcome["stato"], r.UNVERIFIABLE)
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

    def test_corrupt_old_never_silently_ignored(self):
        a, ba = file_and_bytes(when=T-dt.timedelta(hours=4), marker="OLD")
        b, bb = file_and_bytes(when=T-dt.timedelta(minutes=1), marker="NEW")
        a["sha256Checksum"] = "0" * 64
        result, _ = self.recover([a, b], {a["id"]: ba, b["id"]: bb})
        self.assertEqual(result["stato"], r.UNVERIFIABLE)

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
        # The original module is intentionally NOT supplied in this isolated
        # prototype worktree. Normal mode MUST refuse success.
        if importlib.util.find_spec("scripts.kdd_bridge_g2") is not None:
            self.skipTest("KDD original bridge available; covered by integration test")
        result = r.kdd_get_latest_verified_dossier(driver, FOLDER, now=T)
        self.assertEqual(result["stato"], r.UNVERIFIABLE)
        self.assertEqual(result["codice"], "VALIDATORE_KDD_NON_SUPERATO")

    def test_read_only_rest_adapter_constructs_scoped_drive_v3_calls(self):
        seen = []
        def json_get(url, params):
            seen.append((url, params))
            return {"files": [], "nextPageToken": None, "incompleteSearch": False}
        def bytes_get(url, params):
            seen.append((url, params))
            return b"sample"
        d = r.DriveV3ReadOnlyAdapter(FOLDER, json_get, bytes_get)
        d.list_page("opaque")
        d.download("file-3")
        self.assertIn(FOLDER, seen[0][1]["q"])
        self.assertEqual(seen[0][1]["pageToken"], "opaque")
        self.assertIn("incompleteSearch", seen[0][1]["fields"])
        self.assertIn("sha256Checksum", seen[0][1]["fields"])
        self.assertEqual(seen[1][1]["alt"], "media")
        self.assertEqual(len(seen), 2)


# Running this test in an actual checkout of main@c3d14f... proves EXACT
# context equality against the original unmodified bridge, including expiry.
# It is NOT considered run when the actual bridge is unavailable.
class OriginalBridgeDifferentialTests(unittest.TestCase):
    def test_original_read_context_matches_retriever_fresh_and_stale(self):
        if importlib.util.find_spec("scripts.kdd_bridge_g2") is None:
            self.skipTest("Original KDD sources not installed in this isolated working directory")
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as fixtures
        fixture = fixtures.WalletPacketG0Tests("test_wallet_first_all_assets_even_if_quote_missing")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bundle = bridge.prepare(fixture.root, now=fixtures.T, _fixture=True)
        logical_sha = bridge.digest(bundle)
        raw = bridge.canonical(bundle) + b"\n"
        file = {"id": "original-bridge-synthetic", "name": f"kdd_handoff_{logical_sha}.json",
                "parents": [FOLDER], "mimeType": "application/json", "size": str(len(raw)),
                "sha256Checksum": hashlib.sha256(raw).hexdigest(),
                "md5Checksum": hashlib.md5(raw).hexdigest()}
        for when in (fixtures.T, fixtures.T + dt.timedelta(hours=4)):
            drive = FakeDrive(pages_from([file]), {file["id"]: raw})
            result = r.kdd_get_latest_verified_dossier(drive, FOLDER, now=when)
            original = bridge.read_context(bundle, now=when, expected_sha256=logical_sha)
            self.assertEqual(result["contesto_kdd"], original)
            self.assertEqual(result["stato"],
                             r.RECOVERED if original["mercato"]["stato"] == original["saldo"]["stato"] == "RECENTE" else r.STALE)


if __name__ == "__main__":
    unittest.main()
