"""G2 isolated contract checks: public Kraken Spot catalog and non-SUI MTF."""
import datetime as dt
import unittest
from unittest import mock

import grafico_4h as g
import serve


class AnyKrakenSpotTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 24, 20, 42, tzinfo=dt.timezone.utc)
        self.pairs = {
            "ADAUSDT": {"wsname": "ADA/USDT", "status": "online"},
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online"},
            "SUIPERP": {"wsname": "SUI/EUR", "status": "cancel_only"},
            "ETHUSD.d": {"wsname": "ETH/USD", "status": "online"},
            "BAD": {"wsname": "<svg/onload=alert(1)>/EUR", "status": "online"},
            "DOTGBP": {"wsname": "DOT/GBP", "status": "online"},
        }
        self.calls = []

    def fake(self, endpoint, **params):
        self.calls.append((endpoint, dict(params)))
        if endpoint == "AssetPairs":
            self.assertFalse(params)
            return self.pairs
        self.assertEqual(endpoint, "OHLC")
        self.assertIn(params["pair"], ("ADAUSDT", "DOTGBP", "XXBTZEUR"))
        interval = params["interval"] * 60
        current = (int(self.now.timestamp()) // interval) * interval
        raw = []
        for i in range(81):
            close = 1 + .005*i
            raw.append([current - (80-i)*interval, str(close),
                        str(close+.015), str(close-.015), str(close),
                        "0", "125", 1])
        return {"OHLC_PAIR": raw, "last": current}

    def test_market_catalog_includes_non_eur_and_does_not_force_sui(self):
        catalog = serve.spot_catalog(self.fake)
        self.assertEqual(set(catalog), {"ADAUSDT", "XXBTZEUR", "DOTGBP"})
        self.assertEqual(catalog["ADAUSDT"]["quote"], "USDT")
        self.assertEqual(catalog["DOTGBP"]["quote"], "GBP")
        self.assertEqual(catalog["ADAUSDT"]["eligibilita_conto"], "NON_VERIFICATA")
        page = serve.spot_selector(catalog)
        self.assertIn("ADA/USDT", page)
        self.assertIn("DOT/GBP", page)
        self.assertIn('value=""', page)
        self.assertNotIn('value="SUIEUR"', page)
        self.assertNotIn("<svg", page)
        self.assertNotIn("portafoglio", page.lower())

    def test_invalid_nononline_and_injection_pair_are_refused_before_ohlc(self):
        for key in ("SUIEUR", "SUIPERP", "BAD", "../api", "", "<svg>"):
            with self.subTest(key=key):
                self.calls.clear()
                with self.assertRaises(ValueError):
                    serve.load_spot_chart(key, "4h", public_kraken=self.fake,
                                          now=self.now)
                self.assertEqual([ep for ep,_ in self.calls], ["AssetPairs"])

    def test_chart_for_ada_usdt_not_eur_or_sui(self):
        html = serve.load_spot_chart("ADAUSDT", "4h", public_kraken=self.fake,
                                     now=self.now)
        self.assertIn("Grafico ADA/USDT · 4H", html)
        self.assertIn("Volumi scambiati (ADA)", html)
        self.assertIn("pair=ADAUSDT&amp;tf=15m", html)
        self.assertIn("pair=ADAUSDT&amp;tf=1d", html)
        self.assertNotIn("Grafico SUI/EUR", html)
        self.assertNotIn(" SUI';", html)
        self.assertEqual(self.calls[1], ("OHLC", {"pair":"ADAUSDT","interval":240}))

    def test_four_independent_closed_public_frames_keep_pair_and_quote(self):
        report = serve.load_spot_comparison("ADAUSDT", public_kraken=self.fake,
                                            now=self.now)
        self.assertEqual(report["coppia"], "ADA/USDT")
        self.assertEqual(report["stato"], "COMPLETO")
        self.assertEqual([ep for ep,_ in self.calls],
                         ["AssetPairs","OHLC","OHLC","OHLC","OHLC"])
        self.assertEqual([args["interval"] for ep,args in self.calls[1:]],
                         [15,60,240,1440])
        self.assertTrue(all(args["pair"]=="ADAUSDT" for _,args in self.calls[1:]))
        page = serve.render_sui_comparison(report, pair_key="ADAUSDT")
        self.assertIn("Confronto ADA/USDT",page)
        self.assertIn(" USDT",page)
        self.assertIn(" ADA",page)
        self.assertIn("pair=ADAUSDT&amp;tf=4h",page)
        self.assertNotIn("Confronto SUI/EUR",page)

    def test_incomplete_ohlc_is_not_silently_filled(self):
        def missing(endpoint, **kwargs):
            if endpoint=="OHLC" and kwargs["interval"]==60:
                raise ConnectionError("public OHLC unavailable")
            return self.fake(endpoint,**kwargs)
        report=serve.load_spot_comparison("ADAUSDT",public_kraken=missing,
                                          now=self.now)
        self.assertEqual(report["stato"],"PARZIALE")
        self.assertEqual(report["quadro"],"CONFRONTO_INCOMPLETO")
        self.assertEqual(report["timeframe"][1]["stato"],"NON_DISPONIBILE")

    def test_invalid_frame_prevents_even_catalog_call(self):
        with self.assertRaises(ValueError):
            serve.load_spot_chart("ADAUSDT","invalid",public_kraken=self.fake)
        self.assertEqual(self.calls,[])

    def test_none_catalog_is_fail_closed(self):
        with self.assertRaises(ValueError):
            serve.spot_catalog(lambda endpoint: {})
        with self.assertRaises(ValueError):
            serve.spot_catalog(lambda endpoint: [])

    def test_legacy_sui_url_retained_but_no_longer_on_home(self):
        page=serve.with_controls("<h2>1 · Decisioni e posizioni</h2>")
        self.assertIn('href=\'/mercati/spot\'',page)
        self.assertNotIn('href=\'/grafico/sui-4h\'',page)
        self.assertNotIn('href=\'/analisi/sui-mtf\'',page)
        self.assertTrue(callable(serve.load_sui_chart))
        self.assertTrue(callable(serve.load_sui_comparison))

    def test_user_selected_pair_not_derived_from_portfolio(self):
        with mock.patch.object(serve.desk, "load",
                               side_effect=AssertionError("no private local files")):
            catalog=serve.spot_catalog(self.fake)
            report=serve.load_spot_comparison("DOTGBP",public_kraken=self.fake,
                                              now=self.now)
        self.assertIn("DOTGBP",catalog)
        self.assertEqual(report["coppia"],"DOT/GBP")


if __name__ == "__main__":
    unittest.main()
