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


    def test_read_time_funding_numeric_mutations_are_rejected(self):
        import copy
        source = self._fresh()
        for name in ("funding_rate_grezzo", "funding_rate_previsione_grezza"):
            for bad in ("NaN", "Infinity", "-Infinity", "nonsense", True, False,
                        float("nan"), float("inf"), None):
                with self.subTest(name=name, bad=str(bad)):
                    forged = copy.deepcopy(source)
                    forged["funding"][name] = bad
                    read = flow.at_read(forged, self.now)
                    self.assertEqual(read["funding"]["stato"], "NON_VERIFICATO")
                    self.assertNotIn("funding_rate_grezzo", read["funding"])
        self.assertEqual(flow.at_read(source, self.now)["funding"]
                         ["funding_rate_grezzo"], "-0.1")
        for bad in ("NaN", "Infinity", True, "no-number"):
            self.ticker["tickers"][0]["fundingRatePrediction"] = bad
            self.assertEqual(flow.collect(self.now, request=self.fake_request)
                             ["funding"]["stato"], "NON_VERIFICATO")

    def test_read_time_summary_counts_bins_and_raw_tape_cannot_disagree(self):
        import copy
        sample = self._fresh()
        self.assertEqual(sample["esecuzioni"]["n_liquidazioni_nel_campione"], 1)
        for name, bad in (("n_liquidazioni_nel_campione", 99),
                          ("n_liquidazioni_nel_campione", 99999),
                          ("n_esecuzioni", 99), ("n_block_nel_campione", -1),
                          ("durata_campione_secondi", float("inf"))):
            with self.subTest(name=name, bad=bad):
                forged = copy.deepcopy(sample)
                forged["esecuzioni"][name] = bad
                observed = flow.at_read(forged, self.now)["esecuzioni"]
                self.assertEqual(observed["stato"], "NON_VERIFICATO")
                self.assertNotIn("n_esecuzioni", observed)
        for name, bad in (("volume_size_grezzo", "9999999"),
                          ("n_esecuzioni", 99), ("prezzo_da", "-9")):
            with self.subTest(name=name):
                forged = copy.deepcopy(sample)
                forged["esecuzioni"]["profilo_volumi_campione"][0][name] = bad
                self.assertEqual(flow.at_read(forged, self.now)["esecuzioni"]
                                 ["stato"], "NON_VERIFICATO")
        for field, bad in (("size", "-1"), ("size", "Infinity"),
                           ("price", "NaN"), ("type", "liquidation")):
            forged = copy.deepcopy(sample)
            forged["esecuzioni"]["trade_normalizzati"][0][field] = bad
            self.assertEqual(flow.at_read(forged, self.now)["esecuzioni"]
                             ["stato"], "NON_VERIFICATO")
        for field in ("copertura", "richieste_pubbliche_massime", "heatmap"):
            forged = copy.deepcopy(sample)
            forged[field] = "market-wide liquidation heatmap"
            self.assertEqual(flow.at_read(forged, self.now)["stato"],
                             "NON_VERIFICATO")
        for section, label in (("funding", "unita"), ("funding", "limite"),
                               ("esecuzioni", "unita"), ("esecuzioni", "limite")):
            forged = copy.deepcopy(sample)
            forged[section][label] = "whales, USD notional, full heatmap"
            self.assertEqual(flow.at_read(forged, self.now)[section]["stato"],
                             "NON_VERIFICATO")

    def test_trade_ids_duplicates_conflicts_and_equal_time_price(self):
        import copy
        self.history["history"][1]["time"] = self.history["history"][0]["time"]
        self.history["history"][1]["price"] = self.history["history"][0]["price"]
        distinct = self._fresh()
        self.assertEqual(distinct["esecuzioni"]["n_esecuzioni"], 3)
        self.assertEqual(len(distinct["esecuzioni"]["trade_normalizzati"]), 3)
        # A byte-for-byte repeated public trade is counted only once.
        repeat = copy.deepcopy(self.history["history"][0])
        self.history["history"].append(repeat)
        duplicate = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(duplicate["esecuzioni"]["n_esecuzioni"], 3)
        self.assertEqual(flow.at_read(duplicate, self.now)["esecuzioni"]
                         ["n_esecuzioni"], 3)
        self.history["history"][-1]["size"] = "0.9999"
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["esecuzioni"]["stato"], "NON_VERIFICATO")
        self.history["history"][-1] = copy.deepcopy(repeat)
        self.history["history"][-1]["trade_id"] = 999  # same uid, different ID
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["esecuzioni"]["stato"], "NON_VERIFICATO")
        del self.history["history"][-1]
        self.history["history"][0]["trade_id"] = None
        self.history["history"][0]["uid"] = None
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["esecuzioni"]["stato"], "NON_VERIFICATO")

    def test_source_clock_consistency_and_staleness(self):
        import copy
        good = self._fresh()
        future = (self.now + dt.timedelta(minutes=20)).isoformat()
        self.ticker["tickers"][0]["lastTime"] = future
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["funding"]["stato"], "NON_VERIFICATO")
        self.ticker["serverTime"] = future
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["funding"]["stato"], "NON_VERIFICATO")
        del self.ticker["serverTime"]
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["funding"]["stato"], "NON_VERIFICATO")
        self.history["serverTime"] = "2026-11-09T17:24:00Z"
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["esecuzioni"]["stato"], "NON_VERIFICATO")
        self.history["serverTime"] = future
        self.assertEqual(flow.collect(self.now, request=self.fake_request)
                         ["esecuzioni"]["stato"], "NON_VERIFICATO")
        old = flow.at_read(good, self.now+dt.timedelta(minutes=18))
        self.assertEqual(old["esecuzioni"]["stato"], "SCADUTO")
        self.assertEqual(old["funding"]["stato"], "SCADUTO")
        self.assertNotIn("trade_normalizzati", old["esecuzioni"])
        self.assertNotIn("funding_rate_grezzo", old["funding"])
        tamper = copy.deepcopy(good)
        tamper["esecuzioni"]["ultimo_trade_utc"] = future
        self.assertEqual(flow.at_read(tamper, self.now)["esecuzioni"]["stato"],
                         "NON_VERIFICATO")

    def test_public_errors_zero_sample_and_old_oi_cvd(self):
        import urllib.error
        import dossier_trade
        from unittest.mock import patch
        for condition in ("http429", "http503", "invalid_json", "empty", "missing"):
            with self.subTest(condition=condition):
                def request(url, timeout=13):
                    if condition.startswith("http"):
                        raise urllib.error.HTTPError(url, int(condition[4:]), "blocked", None, None)
                    if condition == "invalid_json":
                        return b"{broken json"
                    data = dict(self.ticker if url.endswith("tickers") else self.history)
                    if condition == "empty":
                        data["history"] = []
                    if condition == "missing":
                        data.pop("serverTime", None)
                    return json.dumps(data).encode()
                result = flow.collect(self.now, request=request)
                if condition != "empty":
                    self.assertEqual(result["funding"]["stato"], "NON_VERIFICATO")
                self.assertEqual(result["esecuzioni"]["stato"], "NON_VERIFICATO")
        # Existing, independent OI/CVD data cannot be erased by tape failures.
        seen = []
        def request(url, timeout=13):
            seen.append(url)
            if "analytics/" in url:
                raise OSError("OI/CVD temporarily unavailable")
            raise urllib.error.HTTPError(url, 503, "futures tape unavailable", None, None)
        with patch.object(dossier_trade.desk, "request", side_effect=request), \
             patch.object(dossier_trade.time, "sleep"):
            result = dossier_trade.derivatives_context(self.now.timestamp())
        self.assertEqual(result["open-interest"]["errore"], "OSError")
        self.assertEqual(result["cvd"]["errore"], "OSError")
        self.assertEqual(result["flusso_futures"]["esecuzioni"]["stato"], "NON_VERIFICATO")
        self.assertEqual(sum("/derivatives/api/v3/" in x for x in seen), 2)

    def test_rt2_trade_id_int32_contract_at_collection_and_read(self):
        import copy
        for value in (1, 2147483647):
            with self.subTest(accepted=value):
                self.history["history"][0]["trade_id"] = value
                observed = flow.collect(self.now, request=self.fake_request)
                self.assertEqual(observed["esecuzioni"]["stato"], "CAMPIONE_RECENTE")
                after_wire = json.loads(json.dumps(observed))
                self.assertEqual(flow.at_read(after_wire, self.now)["esecuzioni"]
                                 ["n_esecuzioni"], 3)
        baseline = flow.collect(self.now, request=self.fake_request)
        for value in (2147483648, 0, True, False, -1, "1"):
            with self.subTest(rejected=repr(value)):
                self.history["history"][0]["trade_id"] = value
                captured = flow.collect(self.now, request=self.fake_request)
                self.assertEqual(captured["esecuzioni"]["stato"], "NON_VERIFICATO")
                poisoned = copy.deepcopy(baseline)
                poisoned["esecuzioni"]["trade_normalizzati"][0]["trade_id"] = value
                self.assertEqual(flow.at_read(poisoned, self.now)["esecuzioni"]
                                 ["stato"], "NON_VERIFICATO")
        self.history["history"][0]["trade_id"] = 2147483647
        duplicate = copy.deepcopy(self.history["history"][0])
        self.history["history"].append(duplicate)
        observed = flow.collect(self.now, request=self.fake_request)
        self.assertEqual(observed["esecuzioni"]["n_esecuzioni"], 3)
        self.assertEqual(flow.at_read(observed, self.now)["esecuzioni"]["n_esecuzioni"], 3)

    def test_rt2_raw_funding_engineering_quarantine_acquire_and_read(self):
        import copy
        # This is engineering anomaly quarantine, not Kraken's contractual limit.
        self.assertEqual(str(flow.MAX_ABS_FUNDING_RAW), "1")
        for field, persisted in (("fundingRate", "funding_rate_grezzo"),
                                 ("fundingRatePrediction", "funding_rate_previsione_grezza")):
            for value in ("0.000001", "-0.0123", "0", "1", "-1"):
                with self.subTest(field=field, accepted=value):
                    self._fresh()
                    self.ticker["tickers"][0][field] = value
                    captured = flow.collect(self.now, request=self.fake_request)
                    self.assertEqual(captured["funding"]["stato"], "OSSERVATO")
                    wire = json.loads(json.dumps(captured))
                    read = flow.at_read(wire, self.now)
                    self.assertEqual(read["funding"]["stato"], "OSSERVATO")
                    self.assertEqual(read["funding"][persisted], value)
            for bad in ("1.000000000001", "-1.000000000001", "1E+308",
                        "1E+1000", "-1E+308", "NaN", "Infinity", True, None):
                with self.subTest(field=field, rejected=repr(bad)):
                    valid = self._fresh()
                    self.ticker["tickers"][0][field] = bad
                    captured = flow.collect(self.now, request=self.fake_request)
                    self.assertEqual(captured["funding"]["stato"], "NON_VERIFICATO")
                    if bad in ("1.000000000001", "-1.000000000001", "1E+308",
                               "1E+1000", "-1E+308"):
                        self.assertEqual(captured["funding"]["motivo"],
                                         "FUNDING_FUORI_SOGLIA_INGEGNERISTICA")
                    mutated = copy.deepcopy(valid)
                    mutated["funding"][persisted] = bad
                    after_wire = json.loads(json.dumps(mutated))
                    read = flow.at_read(after_wire, self.now)
                    self.assertEqual(read["funding"]["stato"], "NON_VERIFICATO")
                    self.assertNotIn("funding_rate_grezzo", read["funding"])
                    if bad in ("1.000000000001", "-1.000000000001", "1E+308",
                               "1E+1000", "-1E+308"):
                        self.assertEqual(read["funding"]["motivo"],
                                         "FUNDING_FUORI_SOGLIA_INGEGNERISTICA")

    def test_real_producer_serialized_packet_and_bridge_revalidate(self):
        import copy
        import dossier_trade
        from scripts import kdd_wallet_packet_g0 as wallet
        from scripts import kdd_bridge_g2 as bridge
        from scripts import test_kdd_wallet_packet_g0 as fixture_mod

        fixture = fixture_mod.WalletPacketG0Tests(
            "test_wallet_first_all_assets_even_if_quote_missing")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._analytic_fixture()
        moment = fixture_mod.T
        def ts(s):
            return (moment - dt.timedelta(seconds=s)).isoformat()
        self.ticker["serverTime"] = ts(5)
        self.ticker["tickers"][0]["lastTime"] = ts(9)
        self.history["serverTime"] = ts(5)
        for i, item in enumerate(self.history["history"]):
            item["time"] = ts(10 + i*5)
        def request(url, timeout=13):
            if "/api/charts/" in url:
                raise OSError("OI/CVD synthetic offline")
            return self.fake_request(url, timeout)
        with patch.object(dossier_trade.desk, "request", side_effect=request), \
             patch.object(dossier_trade.time, "sleep"):
            producer = dossier_trade.derivatives_context(moment.timestamp())
        self.assertEqual(producer["flusso_futures"]["esecuzioni"]["stato"],
                         "CAMPIONE_RECENTE")
        # Keep existing OI/CVD fixture; attach only the new public producer.
        fixture.dossier["contesto_derivati_btc"]["flusso_futures"] = producer["flusso_futures"]
        fixture.dump()
        pkt = wallet.build(fixture.root, now=moment)
        self.assertEqual(pkt["evidenze_multifonte"]["derivati_btc"]["open-interest"]
                         ["stato"], "DISPONIBILE")
        self.assertEqual(pkt["evidenze_multifonte"]["derivati_btc"]["cvd"]["stato"],
                         "DISPONIBILE")
        def bundle(packet):
            return {"schema": bridge.SCHEMA_BUNDLE, "packet": packet,
                    "packet_sha256": bridge.digest(packet),
                    "preparato_utc": moment.isoformat(timespec="seconds")}
        wire = json.loads(json.dumps(bundle(pkt)))
        current = bridge.read_context(wire, now=moment)
        self.assertEqual(current["flusso_futures_alla_lettura"]["esecuzioni"]
                         ["n_liquidazioni_nel_campione"], 1)
        stale = bridge.read_context(wire, now=moment+dt.timedelta(minutes=18))
        self.assertEqual(stale["flusso_futures_alla_lettura"]["esecuzioni"]
                         ["stato"], "SCADUTO")
        self.assertNotIn("n_esecuzioni",
                         stale["flusso_futures_alla_lettura"]["esecuzioni"])
        # Tamper dossier before actual packet build, not a fake processor.
        fixture.dossier["contesto_derivati_btc"]["flusso_futures"][
            "esecuzioni"]["n_liquidazioni_nel_campione"] = 99
        fixture.dump()
        bad_source_pkt = wallet.build(fixture.root, now=moment)
        self.assertEqual(bad_source_pkt["evidenze_multifonte"]["derivati_btc"]
                         ["flusso_futures"]["esecuzioni"]["stato"], "NON_VERIFICATO")
        # Tamper a valid packet, recompute local transport digest, then read.
        attacked = copy.deepcopy(wire)
        attacked["packet"]["evidenze_multifonte"]["derivati_btc"]["flusso_futures"][
            "esecuzioni"]["n_liquidazioni_nel_campione"] = 99
        attacked["packet_sha256"] = bridge.digest(attacked["packet"])
        context = bridge.read_context(attacked, now=moment)
        self.assertEqual(context["flusso_futures_alla_lettura"]["esecuzioni"]
                         ["stato"], "NON_VERIFICATO")
        self.assertNotIn("n_liquidazioni_nel_campione",
                         context["flusso_futures_alla_lettura"]["esecuzioni"])
        # Out-of-domain funding cannot recover a positive verdict after
        # read-back of the serialized GPT handoff and renewed local digest.
        poisoned_funding = copy.deepcopy(wire)
        poisoned_funding["packet"]["evidenze_multifonte"]["derivati_btc"][
            "flusso_futures"]["funding"]["funding_rate_grezzo"] = "1E+308"
        poisoned_funding["packet_sha256"] = bridge.digest(poisoned_funding["packet"])
        consumed = bridge.read_context(
            json.loads(json.dumps(poisoned_funding)), now=moment)
        self.assertEqual(consumed["flusso_futures_alla_lettura"]["funding"]
                         ["stato"], "NON_VERIFICATO")
        self.assertEqual(consumed["flusso_futures_alla_lettura"]["funding"]
                         ["motivo"], "FUNDING_FUORI_SOGLIA_INGEGNERISTICA")
        self.assertNotIn("funding_rate_grezzo",
                         consumed["flusso_futures_alla_lettura"]["funding"])
        # Dossier tamper, before packet build, also fails on real consumer.
        fixture.dossier["contesto_derivati_btc"]["flusso_futures"][
            "funding"]["funding_rate_previsione_grezza"] = "1E+1000"
        fixture.dump()
        bad_funding_packet = wallet.build(fixture.root, now=moment)
        self.assertEqual(bad_funding_packet["evidenze_multifonte"]["derivati_btc"]
                         ["flusso_futures"]["funding"]["stato"], "NON_VERIFICATO")
        # Existing OI/CVD and other asset rows survive quarantine.
        self.assertEqual(bad_funding_packet["evidenze_multifonte"]["derivati_btc"]
                         ["open-interest"]["stato"], "DISPONIBILE")
        self.assertEqual(bad_funding_packet["patrimonio"]["n_posizioni"], 3)
        # An old packet without Futures remains usable, but not verified.
        old = copy.deepcopy(wire)
        del old["packet"]["evidenze_multifonte"]["derivati_btc"]["flusso_futures"]
        old["packet_sha256"] = bridge.digest(old["packet"])
        self.assertEqual(bridge.read_context(old, now=moment)
                         ["flusso_futures_alla_lettura"]["stato"], "NON_VERIFICATO")


if __name__ == "__main__":
    unittest.main()
