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
        portfolio = {"posizioni": [
            {"token": "BTC", "quantita": "0.003", "disponibile_spot": "0.003"},
            {"token": "ETH", "quantita": "0.1", "disponibile_spot": "0.1"},
            {"token": "SOL", "quantita": "1", "disponibile_spot": "1"}]}
        calls = []
        def fake(endpoint, **kwargs):
            calls.append((endpoint, kwargs["pair"], kwargs["count"]))
            return {kwargs["pair"]: {"bids": [["70000" if kwargs["pair"] == "XXBTZEUR"
                                             else "2000", "0.5", 1]]}}
        with mock.patch.object(dossier_trade.desk, "NOW", return_value=T),\
             mock.patch.object(dossier_trade.time, "sleep"):
            out = dossier_trade.finanziamento_150_book(
                source, portfolio, saldo_recente=True, kraken_client=fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(x[1] for x in calls), {"XXBTZEUR", "XETHZEUR"})
        self.assertTrue(all(x[0] == "Depth" and x[2] == 25 for x in calls))
        self.assertEqual([x["stato"] for x in out["righe"]],
                         ["BOOK_PUBBLICO_OSSERVATO",
                          "BOOK_PUBBLICO_OSSERVATO",
                          "SOTTO_150_LORDI_SU_PREZZO_INDICATIVO"])
        self.assertEqual(out["richieste_depth"], 2)
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


if __name__ == "__main__":
    unittest.main()
