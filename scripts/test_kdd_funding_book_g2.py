"""Independent KDD-05/12 public order-book tests. No private balances or network."""
import datetime as dt
import json
from scripts import kdd_wallet_packet_g0 as p
from scripts import kdd_bridge_g2 as bridge
import unittest
from unittest import mock

UTC = dt.timezone.utc
T = dt.datetime(2026, 10, 25, 18, 0, tzinfo=UTC)


class FundingBookTests(unittest.TestCase):
    def test_recent_book_does_not_override_stale_market_or_balance(self):
        from scripts import kdd_bridge_g2 as bridge
        packet = {"patrimonio": {"book_pubblico_150": {
            "stato": "STIMA_BOOK_CON_FEE_IPOTETICA",
            "righe": [{"indice": 0, "token": "BTC",
                       "stato": "BOOK_PUBBLICO_OSSERVATO",
                       "osservato_utc": T.isoformat()}]}}}
        fresh = bridge.stato_book_150_alla_lettura(
            packet, T, mercato_stato="RECENTE", saldo_stato="RECENTE")
        self.assertEqual(fresh["stato"], "RECENTE_SOLO_FEE_IPOTETICA")
        for market, balance in (("RECENTE", "DA_AGGIORNARE"),
                                ("DA_AGGIORNARE", "RECENTE"),
                                ("DA_AGGIORNARE", "DA_AGGIORNARE")):
            with self.subTest(market=market, balance=balance):
                result = bridge.stato_book_150_alla_lettura(
                    packet, T, mercato_stato=market, saldo_stato=balance)
                self.assertEqual(result["stato"], "DATI_BASE_NON_RECENTI")
        old = bridge.stato_book_150_alla_lettura(
            packet, T + dt.timedelta(minutes=6),
            mercato_stato="RECENTE", saldo_stato="RECENTE")
        self.assertEqual(old["stato"], "SCADUTO")


    def test_bridge_rechecks_book_age_at_read(self):
        packet = {"patrimonio": {"book_pubblico_150": {
            "stato": "STIMA_BOOK_CON_FEE_IPOTETICA",
            "righe": [{"stato": "BOOK_PUBBLICO_OSSERVATO",
                       "osservato_utc": T.isoformat()}]}}}
        fresh = bridge.stato_book_150_alla_lettura(
            packet, T, mercato_stato="RECENTE", saldo_stato="RECENTE")
        old = bridge.stato_book_150_alla_lettura(
            packet, T+dt.timedelta(minutes=6),
            mercato_stato="RECENTE", saldo_stato="RECENTE")
        self.assertEqual(fresh["stato"], "RECENTE_SOLO_FEE_IPOTETICA")
        self.assertEqual(old["stato"], "SCADUTO")
        self.assertEqual(old["book_scaduti"], 1)
        self.assertEqual(bridge.stato_book_150_alla_lettura(
            {"patrimonio": {}}, T)["stato"], "NON_ATTESTATO")
        malformed = json.loads(json.dumps(packet))
        malformed["patrimonio"]["book_pubblico_150"]["righe"][0]["osservato_utc"] = "no"
        self.assertEqual(bridge.stato_book_150_alla_lettura(
            malformed, T)["stato"], "NON_VERIFICABILE")

    def test_book_packet_rejects_wrong_wallet_pair_and_stale_time(self):
        first = {"indice": 0, "token": "ADA", "stato_identita": "VALIDA",
                 "quantita_spot": "200", "disponibile_spot": "200",
                 "fonte_prezzo_eur": {"pair": "ADA/EUR", "pair_key": "ADAEUR"}}
        second = {"indice": 1, "token": "ETH", "stato_identita": "VALIDA",
                  "quantita_spot": "1", "disponibile_spot": "1",
                  "fonte_prezzo_eur": {"pair": "ETH/EUR", "pair_key": "XETHZEUR"}}
        import costi_spot
        bids = [["2000", "0.5", 1]]
        estimate = costi_spot.stima_vendita_book_150(bids, "1")
        record = {"indice": 1, "token": "ETH", "stato": "BOOK_PUBBLICO_OSSERVATO",
                  "pair": "ETH/EUR", "pair_key": "XETHZEUR",
                  "osservato_utc": T.isoformat(), "bids_osservati": bids,
                  "stima": estimate}
        dossier = {"fotografia_portafoglio_sha256": "hash123",
                   "finanziamento_150_book_pubblico": {
                       "rilevazione_mercato_utc": T.isoformat(),
                       "righe": [{"indice": 0, "token": "ADA",
                                  "stato": "SOTTO_150_LORDI_SU_PREZZO_INDICATIVO"}, record]}}
        self.assertEqual(p.book_150_per_gpt(
            dossier, [first, second], "hash123", T.isoformat(), T)["stato"],
            "STIMA_BOOK_CON_FEE_IPOTETICA")
        self.assertEqual(p.book_150_per_gpt(
            dossier, [first, second], "another", T.isoformat(), T)["stato"],
            "NON_ATTESTATO")
        tampered = json.loads(json.dumps(dossier))
        tampered["finanziamento_150_book_pubblico"]["righe"][1]["pair"] = "BTC/EUR"
        self.assertEqual(p.book_150_per_gpt(
            tampered, [first, second], "hash123", T.isoformat(), T)["stato"],
            "NON_ATTESTATO")
        tampered_net = json.loads(json.dumps(dossier))
        tampered_net["finanziamento_150_book_pubblico"]["righe"][1]["stima"]["proventi_netto_fee_ipotesi_eur"] = "999"
        self.assertEqual(p.book_150_per_gpt(
            tampered_net, [first, second], "hash123", T.isoformat(), T)["stato"],
            "NON_ATTESTATO")
        late = p.book_150_per_gpt(
            dossier, [first, second], "hash123", T.isoformat(),
            T + dt.timedelta(minutes=7))
        self.assertEqual(late["righe"][1]["freschezza"], "SCADUTO")

    def test_book_acquisition_two_owned_assets_only_and_bounded_calls(self):
        import dossier_trade
        source = {"rilevazione_utc": T.isoformat(),
                  "markets": {"BTC": {"token": "BTC", "pair": "XBT/EUR",
                                      "pair_key": "XXBTZEUR", "prezzo_eur": "70000"},
                              "ETH": {"token": "ETH", "pair": "ETH/EUR",
                                      "pair_key": "XETHZEUR", "prezzo_eur": "2000"},
                              "SOL": {"token": "SOL", "pair": "SOL/EUR",
                                      "pair_key": "SOLEUR", "prezzo_eur": "20"}}}
        source["_verified_asset_pairs"] = {
            "XXBTZEUR": {"wsname": "XBT/EUR", "altname": "XBTEUR", "status": "online"},
            "XETHZEUR": {"wsname": "ETH/EUR", "altname": "ETHEUR", "status": "online"},
            "SOLEUR": {"wsname": "SOL/EUR", "altname": "SOLEUR", "status": "online"}}
        portfolio = {"posizioni": [
            {"token": "BTC", "quantita": "0.003", "disponibile_spot": "0.003"},
            {"token": "ETH", "quantita": "0.1", "disponibile_spot": "0.1"},
            {"token": "SOL", "quantita": "1", "disponibile_spot": "1"}]}
        calls = []
        def fake(endpoint, **kwargs):
            calls.append((endpoint, kwargs["pair"], kwargs["count"]))
            return {kwargs["pair"]: {"bids": [["70000" if kwargs["pair"] == "XXBTZEUR"
                                             else "2000" if kwargs["pair"] == "XETHZEUR"
                                             else "20", "0.5", 1]]}}
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T),\
             mock.patch.object(dossier_trade.time, "sleep"):
            out = dossier_trade.finanziamento_150_book(
                source, portfolio, saldo_recente=True, kraken_client=fake)
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(x[1] for x in calls), {"XXBTZEUR", "XETHZEUR", "SOLEUR"})
        self.assertTrue(all(x[0] == "Depth" and x[2] == 25 for x in calls))
        self.assertEqual([x["stato"] for x in out["righe"]],
                         ["BOOK_PUBBLICO_OSSERVATO",
                          "BOOK_PUBBLICO_OSSERVATO",
                          "BOOK_PUBBLICO_OSSERVATO"])
        self.assertEqual(out["richieste_depth"], 3)
        from decimal import Decimal
        self.assertEqual(Decimal(out["righe"][2]["stima"]["proventi_netto_fee_ipotesi_eur"]), Decimal("9.92"))
        def mismatched(endpoint, **kwargs):
            return {"WRONG_PAIR": {"bids": [["70000", "1", 1]]}}
        bad = dossier_trade.finanziamento_150_book(
            source, portfolio, saldo_recente=True, kraken_client=mismatched)
        self.assertEqual(bad["righe"][0]["stato"], "BOOK_NON_VERIFICATO")
        self.assertEqual(bad["righe"][1]["stato"], "BOOK_NON_VERIFICATO")
        out_stale = dossier_trade.finanziamento_150_book(
            source, portfolio, saldo_recente=False, kraken_client=fake)
        self.assertEqual(out_stale["richieste_depth"], 0)

    def test_book_150_kraken_bids_and_hypothetical_fee(self):
        import costi_spot
        rows = [["2000", "0.05", 1], ["1990", "0.20", 1]]
        quote = costi_spot.stima_vendita_book_150(
            rows, "0.2", target_eur="150", fee_ipotesi="0.008")
        self.assertEqual(quote["stato"],
                         "150_NETTI_SOLO_CON_FEE_IPOTETICA_E_BOOK_FOTOGRAFATO")
        self.assertEqual(quote["livelli_bid_utilizzati"], 2)
        self.assertTrue(quote["nessun_fill_attestato"])
        self.assertEqual(quote["fee_ipotetica_pct"], "0.800")
        self.assertIn("Fee NON verificata", quote["limite"])

    def test_book_150_partial_depth_balance_and_adversarial_rejections(self):
        import costi_spot
        rows = [["2000", "0.01", 1], ["1900", "0.01", 1]]
        quote = costi_spot.stima_vendita_book_150(rows, "1")
        self.assertEqual(quote["stato"], "PROFONDITA_BOOK_INSUFFICIENTE")
        quote = costi_spot.stima_vendita_book_150(
            [["2000", "1", 1]], "0.01")
        self.assertEqual(quote["stato"], "SALDO_DISPONIBILE_INSUFFICIENTE")
        for bids in ([["2000", "0.2"], ["2001", "0.3"]],
                     [["2000", "-1"]], [["NaN", "1"]],
                     [["2000", "0.1"], ["2000", "1"]], []):
            with self.subTest(bids=bids):
                with self.assertRaises(ValueError):
                    costi_spot.stima_vendita_book_150(bids, "1")
        with self.assertRaises(ValueError):
            costi_spot.stima_vendita_book_150([["1000", "1"]], "1",
                                             fee_ipotesi="1")


    def test_rt1_f1_exact_decimal_reaches_target_and_flexible_smaller_case(self):
        import costi_spot
        from decimal import Decimal
        exact = costi_spot.stima_vendita_book_150(
            [["14.27305907", "100"]], "100", target_eur="150", fee_ipotesi="0.008")
        self.assertEqual(exact["stato"], "150_NETTI_SOLO_CON_FEE_IPOTETICA_E_BOOK_FOTOGRAFATO")
        self.assertGreaterEqual(Decimal(exact["proventi_netto_fee_ipotesi_eur"]), Decimal("150"))
        smaller = costi_spot.stima_vendita_book_150(
            [["1", "140"]], "140", target_eur="150", fee_ipotesi="0.008")
        self.assertNotEqual(smaller["stato"], "150_NETTI_SOLO_CON_FEE_IPOTETICA_E_BOOK_FOTOGRAFATO")
        self.assertEqual(Decimal(smaller["proventi_netto_fee_ipotesi_eur"]), Decimal("138.880"))

    def test_rt1_f2_wrong_rest_key_is_rejected_before_depth(self):
        import dossier_trade
        pairs = {
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online", "altname": "XBTEUR"},
            "XETHZEUR": {"wsname": "ETH/EUR", "status": "online", "altname": "ETHEUR"}}
        source = {"rilevazione_utc": T.isoformat(), "_verified_asset_pairs": pairs,
                  "markets": {"BTC": {"token": "BTC", "pair": "XBT/EUR",
                                       "pair_key": "XETHZEUR", "prezzo_eur": "70000"}}}
        portfolio = {"posizioni": [{"token": "BTC", "quantita": "0.01",
                                     "disponibile_spot": "0.01"}]}
        calls = []
        def fake(endpoint, **kwargs):
            calls.append((endpoint, kwargs))
            return {"XETHZEUR": {"bids": [["2000", "1", 1]]}}
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T), \
             mock.patch.object(dossier_trade.time, "sleep"):
            out = dossier_trade.finanziamento_150_book(
                source, portfolio, saldo_recente=True, kraken_client=fake)
        self.assertEqual(out["richieste_depth"], 0)
        self.assertNotEqual(out["righe"][0]["stato"], "BOOK_PUBBLICO_OSSERVATO")
        self.assertEqual(calls, [])

    def test_rt2_f2_duplicate_wsname_rejected_before_depth_and_gpt(self):
        """Two different REST keys share XBT/EUR despite distinct altname."""
        import serve
        import dossier_trade
        pairs = {
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online", "altname": "XBTEUR"},
            "XETHZEUR": {"wsname": "XBT/EUR", "status": "online", "altname": "ETHEUR"}}
        source = {"rilevazione_utc": T.isoformat(), "_verified_asset_pairs": pairs,
                  "markets": {"BTC": {"token": "BTC", "pair": "XBT/EUR",
                                       "pair_key": "XXBTZEUR", "prezzo_eur": "70000"}}}
        portfolio = {"posizioni": [{"token": "BTC", "quantita": "0.01",
                                     "disponibile_spot": "0.01"}]}
        calls = []
        def depth(endpoint, **kwargs):
            calls.append((endpoint, kwargs["pair"]))
            return {kwargs["pair"]: {"bids": [["70000", "0.1", T.timestamp()]]}}
        for rows in (pairs, dict(reversed(list(pairs.items())))):
            with self.subTest(order=list(rows)):
                with self.assertRaises(serve.KrakenMarketDataUnavailable):
                    serve.spot_catalog(lambda _: rows)
                calls.clear()
                with mock.patch.object(dossier_trade.desk, "NOW", return_value=T), \
                     mock.patch.object(dossier_trade.time, "sleep"):
                    funding = dossier_trade.finanziamento_150_book(
                        dict(source, _verified_asset_pairs=rows), portfolio,
                        saldo_recente=True, kraken_client=depth)
                with self.subTest(consumer="producer"):
                    self.assertEqual(calls, [], "Ambiguous REST/wsname must never request Depth")
                    self.assertNotEqual(funding["righe"][0]["stato"], "BOOK_PUBBLICO_OSSERVATO")
                position = {"indice": 0, "token": "BTC", "stato_identita": "VALIDA",
                            "quantita_spot": "0.01", "disponibile_spot": "0.01",
                            "fonte_prezzo_eur": {"pair": "XBT/EUR", "pair_key": "XXBTZEUR"}}
                dossier = {"fotografia_portafoglio_sha256": "synthetic-digest",
                           "finanziamento_150_book_pubblico": funding}
                packet_book = p.book_150_per_gpt(
                    dossier, [position], "synthetic-digest", T.isoformat(), T)
                read = bridge.stato_book_150_alla_lettura(
                    {"patrimonio": {"book_pubblico_150": packet_book}}, T,
                    mercato_stato="RECENTE", saldo_stato="RECENTE")
                with self.subTest(consumer="GPT"):
                    self.assertFalse(any("stima" in row for row in packet_book["righe"]))
                    self.assertNotEqual(read["stato"], "RECENTE_SOLO_FEE_IPOTETICA")

    def test_rt2_f2_valid_kraken_btc_xbt_alias_keeps_depth_and_gpt(self):
        import serve
        import dossier_trade
        pairs = {
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online", "altname": "XBTEUR"},
            "XETHZEUR": {"wsname": "ETH/EUR", "status": "online", "altname": "ETHEUR"}}
        catalog = serve.spot_catalog(lambda _: pairs)
        self.assertEqual(catalog["XXBTZEUR"]["pair"], "XBT/EUR")
        source = {"rilevazione_utc": T.isoformat(), "_verified_asset_pairs": pairs,
                  "markets": {"BTC": {"token": "BTC", "pair": "XBT/EUR",
                                       "pair_key": "XXBTZEUR", "prezzo_eur": "70000"}}}
        portfolio = {"posizioni": [{"token": "BTC", "quantita": "0.01",
                                     "disponibile_spot": "0.01"}]}
        calls = []
        def depth(endpoint, **kwargs):
            calls.append((endpoint, kwargs["pair"]))
            return {kwargs["pair"]: {"bids": [["70000", "0.1", T.timestamp()]]}}
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T), \
             mock.patch.object(dossier_trade.time, "sleep"):
            funding = dossier_trade.finanziamento_150_book(
                source, portfolio, saldo_recente=True, kraken_client=depth)
        self.assertEqual(calls, [("Depth", "XXBTZEUR")])
        self.assertEqual(funding["righe"][0]["stato"], "BOOK_PUBBLICO_OSSERVATO")
        position = {"indice": 0, "token": "BTC", "stato_identita": "VALIDA",
                    "quantita_spot": "0.01", "disponibile_spot": "0.01",
                    "fonte_prezzo_eur": {"pair": "XBT/EUR", "pair_key": "XXBTZEUR"}}
        dossier = {"fotografia_portafoglio_sha256": "synthetic-digest",
                   "finanziamento_150_book_pubblico": funding}
        packet_book = p.book_150_per_gpt(
            dossier, [position], "synthetic-digest", T.isoformat(), T)
        self.assertEqual(packet_book["righe"][0]["stato"], "BOOK_PUBBLICO_OSSERVATO")
        self.assertIn("netto_fee_ipotetica_eur", packet_book["righe"][0]["stima"])
        self.assertEqual(bridge.stato_book_150_alla_lettura(
            {"patrimonio": {"book_pubblico_150": packet_book}}, T,
            mercato_stato="RECENTE", saldo_stato="RECENTE")["stato"],
            "RECENTE_SOLO_FEE_IPOTETICA")

    def test_rt1_f3_future_book_is_not_recent(self):
        row = {"stato": "BOOK_PUBBLICO_OSSERVATO",
               "osservato_utc": (T + dt.timedelta(seconds=90)).isoformat()}
        pkt = {"patrimonio": {"book_pubblico_150": {
            "stato": "STIMA_BOOK_CON_FEE_IPOTETICA", "righe": [row]}}}
        out = bridge.stato_book_150_alla_lettura(
            pkt, T, mercato_stato="RECENTE", saldo_stato="RECENTE")
        self.assertNotEqual(out["stato"], "RECENTE_SOLO_FEE_IPOTETICA")
        self.assertEqual(out["stato"], "OROLOGIO_INCOERENTE")

    def test_rt1_f7_both_invested_and_total_portfolio_denominators(self):
        from decimal import Decimal
        positions = [
            {"indice": 0, "token": "ETH", "stato_identita": "VALIDA",
             "prezzo_eur": "1000", "quantita_spot": "2", "disponibile_spot": "2",
             "valore_eur": "2000",
             "fonte_prezzo_eur": {"token": "ETH", "pair": "ETH/EUR", "valuta": "EUR"}},
            {"indice": 1, "token": "BTC", "stato_identita": "VALIDA",
             "prezzo_eur": "800", "quantita_spot": "1", "disponibile_spot": "1",
             "valore_eur": "800",
             "fonte_prezzo_eur": {"token": "BTC", "pair": "XBT/EUR", "valuta": "EUR"}}]
        result = p.alternative_liquidazione_150_lorda(
            positions, "2800", mercato_stato="RECENTE", saldo_stato="RECENTE")
        eth = result["alternative"][0]
        self.assertEqual(Decimal(eth["peso_asset_post_alleggerimento_pct"]), Decimal("69.81"))
        self.assertEqual(Decimal(eth["peso_asset_su_intero_patrimonio_pct"]), Decimal("66.07"))
        self.assertEqual(Decimal(eth["liquidita_teorica_ricavata_eur"]), Decimal("150"))
        self.assertEqual(result["alternativa_senza_operazione"]["azione"], "NON_CONVERTIRE_ORA")


    def test_rt1_real_producer_dossier_packet_and_gpt_bridge(self):
        """Actual source JSON -> verified AssetPairs -> Depth -> dossier -> GPT packet."""
        import dossier_trade
        import copy
        from scripts import test_kdd_wallet_packet_g0 as fixtures
        fixture = fixtures.WalletPacketG0Tests(
            "test_wallet_first_all_assets_even_if_quote_missing")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        asset_pairs = {
            "ADAEUR": {"wsname": "ADA/EUR", "status": "online", "altname": "ADAEUR"},
            "XETHZEUR": {"wsname": "ETH/EUR", "status": "online", "altname": "ETHEUR"}}
        source = dict(fixture.snapshot, _verified_asset_pairs=asset_pairs)
        calls = []
        def depth(endpoint, **kwargs):
            self.assertEqual(endpoint, "Depth")
            calls.append(kwargs["pair"])
            price = "2000" if kwargs["pair"] == "XETHZEUR" else "1"
            return {kwargs["pair"]: {"bids": [[price, "2", T.timestamp()]]}}
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T), \
             mock.patch.object(dossier_trade.time, "sleep"):
            funding = dossier_trade.finanziamento_150_book(
                source, fixture.portfolio, saldo_recente=True, kraken_client=depth)
        self.assertEqual(set(calls), {"XETHZEUR", "ADAEUR"})
        self.assertEqual(funding["righe"][1]["stato"], "BOOK_PUBBLICO_OSSERVATO")
        self.assertEqual(funding["righe"][0]["stato"], "BOOK_PUBBLICO_OSSERVATO")
        self.assertLess(
            float(funding["righe"][0]["stima"]["proventi_netto_fee_ipotesi_eur"]), 150)
        fixture.dossier["finanziamento_150_book_pubblico"] = funding
        fixture.dossier["fotografia_portafoglio_sha256"] = p.portfolio_identity(fixture.portfolio)
        fixture.report["fotografia_portafoglio_sha256"] = p.portfolio_identity(fixture.portfolio)
        fixture.dump()
        packet = p.build(fixture.root, now=T)
        self.assertEqual(packet["patrimonio"]["book_pubblico_150"]["stato"],
                         "STIMA_BOOK_CON_FEE_IPOTETICA")
        alternative = packet["patrimonio"]["book_pubblico_150"]["righe"][0]["stima"]
        self.assertTrue(alternative["sotto_riferimento_non_esclusa"])
        self.assertIsNone(alternative["usdc_effettivamente_disponibili_da_vendita"])
        self.assertGreater(float(alternative["netto_fee_ipotetica_eur"]), 0)
        prepared = bridge.prepare(fixture.root, now=T, _fixture=True)
        context = bridge.read_context(prepared, now=T)
        self.assertEqual(context["book_150_alla_lettura"]["stato"],
                         "RECENTE_SOLO_FEE_IPOTETICA")
        late = bridge.read_context(prepared, now=T + dt.timedelta(minutes=7))
        self.assertNotEqual(late["book_150_alla_lettura"]["stato"],
                            "RECENTE_SOLO_FEE_IPOTETICA")
        self.assertTrue(packet["nessun_ordine"])
        wrong = copy.deepcopy(source)
        wrong["_verified_asset_pairs"]["XETHZEUR"]["wsname"] = "XBT/EUR"
        calls.clear()
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T), \
             mock.patch.object(dossier_trade.time, "sleep"):
            bad = dossier_trade.finanziamento_150_book(
                wrong, fixture.portfolio, saldo_recente=True, kraken_client=depth)
        self.assertNotIn("XETHZEUR", calls)
        self.assertNotEqual(bad["righe"][1]["stato"], "BOOK_PUBBLICO_OSSERVATO")



if __name__ == "__main__":
    unittest.main()
