"""Independent synthetic regression of market freshness at report composition."""
import datetime as dt
import unittest
from unittest import mock
import decision_desk as desk

UTC = dt.timezone.utc

class MarketExpiryAtReportTests(unittest.TestCase):
    def run_case(self, market_minutes_old):
        now = dt.datetime(2026, 10, 28, 17, 20, tzinfo=UTC)
        snap = (now - dt.timedelta(minutes=market_minutes_old)).isoformat()
        wallet = {"posizioni": []}
        digest = "synthetic-wallet-digest"
        status = {
            "rilevazione_kraken_utc": snap,
            "fotografia_portafoglio_sha256": digest,
            "stato": "PRONTO_PER_ESAME_GPT",
            "stato_fonti_mercato": "COMPLETO",
            "idoneita_analisi_patrimoniale": "IDONEA",
            "motivi_incompletezza": [],
            "motivi_patrimoniali": []
        }
        dossier = {
            "kraken_istantanea_utc": snap,
            "fotografia_portafoglio_sha256": digest
        }
        with mock.patch.object(desk, "load", side_effect=[status, dossier]), \
             mock.patch.object(desk, "fotografia_portafoglio_sha256", return_value=digest), \
             mock.patch.object(desk, "NOW", return_value=now), \
             mock.patch.object(desk, "stato_saldo", return_value={"freschezza_saldo": "RECENTE"}):
            return desk.stato_dossier_per_report(
                {"rilevazione_utc": snap, "saldo_refresh": None}, portfolio=wallet
            )

    def test_50_minute_market_can_remain_eligible_with_fresh_balance(self):
        outcome = self.run_case(50)
        self.assertEqual(outcome["idoneita_analisi_patrimoniale"], "IDONEA")

    def test_70_minute_market_cannot_be_ready_even_with_fresh_balance(self):
        outcome = self.run_case(70)
        self.assertEqual(outcome["idoneita_analisi_patrimoniale"], "NON_IDONEA")
        self.assertEqual(outcome["stato_fonti_mercato"], "SCADUTO")
        self.assertEqual(outcome["stato"], "PARZIALE")
        self.assertIn("mercato scaduta", " ".join(outcome["motivi_incompletezza"]))

    def test_future_market_clock_cannot_be_ready(self):
        outcome = self.run_case(-10)
        self.assertEqual(outcome["idoneita_analisi_patrimoniale"], "NON_IDONEA")

if __name__ == "__main__":
    unittest.main()
