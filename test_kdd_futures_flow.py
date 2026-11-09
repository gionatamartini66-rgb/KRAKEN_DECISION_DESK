"""Regression tests for genuine public Kraken Futures data shapes (synthetic only)."""
import datetime as dt
import json
import unittest
from unittest.mock import patch

import kdd_futures_flow as flow


class FuturesFlowTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 9, 17, 25, tzinfo=dt.timezone.utc)
        self.ticker = {
            "result": "success", "serverTime": "2026-11-09T17:24:35Z",
            "tickers": [{"symbol": "PF_XBTUSD", "suspended": False,
                         "fundingRate": -0.0123,
                         "fundingRatePrediction": 0.025,
                         "lastTime": "2026-11-09T17:24:30Z"}]}
        self.history = {
            "result": "success", "serverTime": "2026-11-09T17:24:35Z",
            "history": [
                {"time": "2026-11-09T17:24:30Z", "price": 74900, "size": "0.2",
                 "side": "buy", "type": "liquidation", "trade_id": 101, "uid": "exec-101"},
                {"time": "2026-11-09T17:24:20Z", "price": 74910, "size": "0.1",
                 "side": "sell", "type": "fill", "trade_id": 102, "uid": "exec-102"},
                {"time": "2026-11-09T17:23:20Z", "price": 74920, "size": "0.8",
                 "side": "buy", "type": "block", "trade_id": 103, "uid": "exec-103"}]}

    def fake_request(self, url, timeout=13):
        self.assertTrue(url.startswith(flow.BASE))
        self.assertEqual(timeout, 13)
        return json.dumps(self.ticker if url.endswith("tickers")
                          else self.history).encode()

    def test_public_funding_liquidations_vap_and_consumer(self):
        calls = []
        def request(url, timeout=13):
            calls.append(url)
            return self.fake_request(url, timeout)
        result = flow.collect(self.now.timestamp(), request=request)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["strumento"], "PF_XBTUSD")
        self.assertEqual(result["funding"]["stato"], "OSSERVATO")
        self.assertEqual(result["funding"]["funding_rate_grezzo"], "-0.0123")
        self.assertEqual(result["esecuzioni"]["stato"], "CAMPIONE_RECENTE")
        self.assertEqual(result["esecuzioni"]["n_liquidazioni_nel_campione"], 1)
        self.assertEqual(result["esecuzioni"]["n_block_nel_campione"], 1)
        self.assertEqual(result["esecuzioni"]["n_esecuzioni"], 3)
        self.assertEqual(sum(x["n_esecuzioni"] for x in
                             result["esecuzioni"]["profilo_volumi_campione"]), 3)
        self.assertEqual(result["heatmap"]["stato"], "NON_DISPONIBILE")
        read = flow.at_read(result, self.now)
        self.assertEqual(read["funding"]["stato"], "OSSERVATO")
        self.assertEqual(read["esecuzioni"]["n_liquidazioni_nel_campione"], 1)
        expired = flow.at_read(result, self.now + dt.timedelta(minutes=18))
        self.assertEqual(expired["funding"]["stato"], "SCADUTO")
        self.assertEqual(expired["esecuzioni"]["stato"], "SCADUTO")
        self.assertNotIn("funding_rate_grezzo", expired["funding"])
        self.assertNotIn("n_liquidazioni_nel_campione", expired["esecuzioni"])

    def test_zero_observed_liquidations_is_only_sample_zero(self):
        for row in self.history["history"]:
            row["type"] = "fill"
        out = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(out["esecuzioni"]["n_liquidazioni_nel_campione"], 0)
        self.assertIn("non equivale a zero sul mercato", out["esecuzioni"]["limite"])

    def test_api_missing_duplicate_or_wrong_contract_fails_closed(self):
        self.ticker["tickers"] = [{"symbol": "PI_XBTUSD", "suspended": False,
                                  "fundingRate": .1, "fundingRatePrediction": .2}]
        out = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(out["funding"]["stato"], "NON_VERIFICATO")
        self.assertEqual(out["esecuzioni"]["stato"], "CAMPIONE_RECENTE")
        source = self._fresh()
        source["strumento"] = "PI_XBTUSD"
        self.assertEqual(flow.at_read(source, self.now)["stato"], "NON_VERIFICATO")

    def _fresh(self):
        self.ticker["tickers"] = [{
            "symbol": "PF_XBTUSD", "suspended": False,
            "fundingRate": -.1, "fundingRatePrediction": .2,
            "lastTime": "2026-11-09T17:24:30Z"}]
        return flow.collect(self.now, request=self.fake_request)

    def test_stale_trades_and_malformed_types_are_not_attributed(self):
        self._fresh()
        for i, row in enumerate(self.history["history"]):
            row["time"] = "2026-11-09T16:00:00Z"
        bad = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(bad["esecuzioni"]["stato"], "SCADUTO")
        self.assertEqual(bad["funding"]["stato"], "OSSERVATO")
        self.history["history"][0]["time"] = "2026-11-09T17:24:30Z"
        self.history["history"][0]["type"] = "unrecognized"
        bad = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(bad["esecuzioni"]["stato"], "NON_VERIFICATO")

    def test_live_ordering_variance_is_sorted_without_dropping_trades(self):
        # Actual Kraken /history can be out of timestamp order.
        self.history["history"] = list(reversed(self.history["history"]))
        observed = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(observed["esecuzioni"]["stato"], "CAMPIONE_RECENTE")
        self.assertEqual(observed["esecuzioni"]["n_esecuzioni"], 3)
        self.assertEqual(observed["esecuzioni"]["n_liquidazioni_nel_campione"], 1)
        self.assertEqual(observed["esecuzioni"]["primo_trade_utc"], "2026-11-09T17:23:20+00:00")

    def test_funding_nonfinite_and_trade_size_zero_fail_closed(self):
        self.ticker["tickers"][0]["fundingRate"] = "NaN"
        self.history["history"][0]["size"] = 0
        out = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(out["funding"]["stato"], "NON_VERIFICATO")
        self.assertEqual(out["esecuzioni"]["stato"], "NON_VERIFICATO")

    def test_no_cross_exchange_whale_attribution(self):
        out = self._fresh()
        self.assertEqual(out["copertura"], "Solo perpetual BTC Kraken Futures, NON cross-exchange")
        self.assertNotIn("whale", json.dumps(out).lower().replace("identifica whale", ""))
        self.assertEqual(len(out["esecuzioni"]["tre_maggiori_esecuzioni"]), 3)

    def test_packet_consumes_same_futures_and_rechecks_age(self):
        from scripts import kdd_wallet_packet_g0 as pkt
        sample = self._fresh()
        when = self.now.isoformat()
        dossier = {"kraken_istantanea_utc": when,
                   "contesto_derivati_btc": {"strumento": "PF_XBTUSD",
                                            "flusso_futures": sample}}
        snapshot = {"rilevazione_utc": when, "feed": [], "trends": {}}
        evidence = pkt.analytic_evidence(snapshot, dossier, [], [], self.now)
        futures = evidence["derivati_btc"]["flusso_futures"]
        self.assertEqual(futures["esecuzioni"]["n_liquidazioni_nel_campione"], 1)
        self.assertEqual(futures["funding"]["funding_rate_grezzo"], "-0.1")
        expired = pkt.analytic_evidence(snapshot, dossier, [], [],
                                        self.now + dt.timedelta(minutes=18))
        self.assertEqual(expired["derivati_btc"]["flusso_futures"]["funding"]["stato"], "SCADUTO")

    def test_live_dossier_adapter_collects_without_private_calls(self):
        import dossier_trade as dtmod
        def mock_request(url, timeout=13):
            if "/api/charts/v1/analytics/" in url:
                raise OSError("legacy OI/CVD temporarily unavailable")
            return self.fake_request(url, timeout=timeout)
        with patch.object(dtmod.desk, "request", side_effect=mock_request), \
             patch.object(dtmod.time, "sleep"):
            result = dtmod.derivatives_context(self.now.timestamp())
        self.assertEqual(result["open-interest"]["errore"], "OSError")
        self.assertEqual(result["cvd"]["errore"], "OSError")
        self.assertEqual(result["flusso_futures"]["esecuzioni"]["n_liquidazioni_nel_campione"], 1)


if __name__ == "__main__":
    unittest.main()
