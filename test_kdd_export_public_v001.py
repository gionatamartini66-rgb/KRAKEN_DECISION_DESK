"""Test offline: solo fixture sintetiche e nessuna rete o dato Kraken privato."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kdd_export_public_v001 import (ExportError, prepare, publish,
                                     export_if_enabled, UTC, ENV_OPT_IN)

NOW = dt.datetime(2026, 10, 22, 17, 50, 0, tzinfo=UTC)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "KDD_RUNTIME"
        self.source.mkdir()
        self.dest = base / "KDD_TEST_SAMSUNG"
        self.dest.mkdir()
        self.raw = {
            "rilevazione_utc": "2026-10-22T17:48:00Z",
            "n_coppie_multi": 1090,
            "n_token_multi": 610,
            "wallet": {"secret_api_key": "NEVER_PUBLISH"},
            "portafoglio": {"sensitive": True},
            "feed": [{"token": "not_exported"}],
        }
        self.save()

    def save(self):
        (self.source / "ultima_rilevazione.json").write_text(json.dumps(self.raw), encoding="utf-8")

    def test_public_allowlist_prevents_private_leak(self):
        out = publish(self.source, self.dest, NOW)
        text = (self.dest / "mercato_kdd.json").read_text()
        self.assertEqual(out["n_token_multi"], 610)
        self.assertNotIn("NEVER_PUBLISH", text)
        self.assertNotIn("portafoglio", text)
        self.assertNotIn("feed", text)
        self.assertFalse(out["ordine_finanziario"])

    def test_source_timestamp_preserved(self):
        out = prepare(self.source, NOW)
        self.assertEqual(out["rilevazione_utc"], "2026-10-22T17:48:00+00:00")
        self.assertEqual(out["esportazione_utc"], "2026-10-22T17:50:00+00:00")
        self.assertEqual(out["eta_mercato_secondi"], 120)

    def test_stale_is_explicit(self):
        self.raw["rilevazione_utc"] = "2026-10-21T17:48:00Z"
        self.save()
        out = publish(self.source, self.dest, NOW)
        self.assertEqual(out["freschezza"], "SCADUTO")

    def test_boundary_freshness(self):
        self.raw["rilevazione_utc"] = (NOW - dt.timedelta(minutes=45)).isoformat()
        self.save()
        self.assertEqual(prepare(self.source, NOW)["freschezza"], "CORRENTE")

    def test_future_timestamp_rejected(self):
        self.raw["rilevazione_utc"] = "2026-10-22T18:00:00Z"
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_timezone_required(self):
        self.raw["rilevazione_utc"] = "2026-10-22T17:48:00"
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_unparseable_timestamp_rejected(self):
        self.raw["rilevazione_utc"] = "not a timestamp"
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_missing_timestamp_rejected(self):
        del self.raw["rilevazione_utc"]
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_bool_as_int_rejected(self):
        self.raw["n_token_multi"] = True
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_negative_count_rejected(self):
        self.raw["n_coppie_multi"] = -1
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_missing_count_rejected(self):
        del self.raw["n_coppie_multi"]
        self.save()
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_oversized_source_rejected(self):
        (self.source / "ultima_rilevazione.json").write_bytes(b"a" * 12_000_001)
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_corrupt_source_does_not_override_prior(self):
        target = self.dest / "mercato_kdd.json"
        target.write_text("PREVIOUS_VALID")
        (self.source / "ultima_rilevazione.json").write_text("{not json")
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)
        self.assertEqual(target.read_text(), "PREVIOUS_VALID")

    def test_source_symlink_rejected(self):
        f = self.source / "ultima_rilevazione.json"
        target = self.source / "safe_source.json"
        f.rename(target)
        f.symlink_to(target)
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)

    def test_output_symlink_rejected(self):
        target = self.dest / "elsewhere.txt"
        target.write_text("DO NOT CHANGE")
        (self.dest / "mercato_kdd.json").symlink_to(target)
        with self.assertRaises(ExportError):
            publish(self.source, self.dest, NOW)
        self.assertEqual(target.read_text(), "DO NOT CHANGE")

    def test_other_destination_rejected(self):
        wrong = self.dest.parent / "Kraken"
        wrong.mkdir()
        with self.assertRaises(ExportError):
            publish(self.source, wrong, NOW)

    def test_nonexistent_destination_rejected(self):
        with self.assertRaises(ExportError):
            publish(self.source, self.dest.parent / "KDD_TEST_SAMSUNG_MISSING", NOW)

    def test_replace_existing_success(self):
        target = self.dest / "mercato_kdd.json"
        target.write_text("OLD")
        publish(self.source, self.dest, NOW)
        self.assertEqual(json.loads(target.read_text())["schema"], "kdd_public_market_v001")

    def test_default_no_change_to_source(self):
        original = (self.source / "ultima_rilevazione.json").read_bytes()
        publish(self.source, self.dest, NOW)
        self.assertEqual(original, (self.source / "ultima_rilevazione.json").read_bytes())

    def test_never_calls_network(self):
        with mock.patch("socket.socket", side_effect=AssertionError("Network used")):
            publish(self.source, self.dest, NOW)

    def test_optin_default_disabled(self):
        self.assertIsNone(export_if_enabled(self.source, dest_dir=self.dest, environ={}))
        self.assertFalse((self.dest / "mercato_kdd.json").exists())

    def test_optin_invalid_values_disabled(self):
        for flag in ("true", "yes", "0", " 1 ", ""):
            self.assertIsNone(export_if_enabled(self.source, dest_dir=self.dest,
                                                 environ={ENV_OPT_IN: flag}))
            self.assertFalse((self.dest / "mercato_kdd.json").exists())

    def test_optin_exact_value_calls_publisher(self):
        with mock.patch("kdd_export_public_v001.publish", return_value={"freschezza": "CORRENTE"}) as send:
            out = export_if_enabled(self.source, dest_dir=self.dest,
                                    environ={ENV_OPT_IN: "1"})
        self.assertEqual(out["freschezza"], "CORRENTE")
        send.assert_called_once_with(self.source, self.dest)

    def test_optin_uses_only_public_source(self):
        (self.source / "portafoglio.json").write_text('{"key":"EXCLUDED"}')
        out = export_if_enabled(self.source, dest_dir=self.dest,
                                environ={ENV_OPT_IN: "1"})
        self.assertIn("n_coppie_multi", out)
        self.assertNotIn("EXCLUDED", (self.dest / "mercato_kdd.json").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
