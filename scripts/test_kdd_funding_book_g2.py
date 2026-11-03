"""Independent KDD-05/12 public order-book tests. No private balances or network."""
import datetime as dt
import unittest
from unittest import mock

UTC = dt.timezone.utc
T = dt.datetime(2026, 10, 25, 18, 0, tzinfo=UTC)


class FundingBookTests(unittest.TestCase):
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
