"""Synthetic falsification of KDD-11 closed-bar geometry."""
import datetime as dt
import unittest
import kdd_candles as k

class CandleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sec=900
        self.end=(1794000000//900)*900
        self.now=dt.datetime.fromtimestamp(self.end+120,dt.timezone.utc)
        self.bars=[]
        for i in range(60):
            o=100+i*.01
            self.bars.append({"time":self.end-60*self.sec+i*self.sec,
                              "open":o,"high":o+1,"low":o-1,
                              "close":o+.1,"volume":100})
    def data(self):
        return {"timeframe":"15m","interval_seconds":self.sec,
                "candles":self.bars,"pair":"BTC/EUR","pair_key":"XXBTZEUR",
                "observed_utc":self.now.isoformat(),
                "closed_at_utc":dt.datetime.fromtimestamp(self.end,dt.timezone.utc).isoformat(),
                "source":"synthetic Kraken Spot"}
    def test_doji_and_awaiting_confirmation(self):
        b=self.bars[-1];b["close"]=b["open"]
        result=k.recognize(self.data(),now=self.now)
        self.assertIn("DOJI",[f["figura"] for f in result["figure"]])
        self.assertTrue(all(f["stato"]=="IN_ATTESA_CONFERMA" for f in result["figure"]))
    def test_zero_range_no_false_doji(self):
        b=self.bars[-1];b.update(high=b["open"],low=b["open"],close=b["open"])
        self.assertNotIn("DOJI",[f["figura"] for f in k.recognize(self.data(),now=self.now)["figure"]])
    def test_gap_rejected(self):
        self.bars[-2]["time"]-=1
        with self.assertRaises(ValueError): k.recognize(self.data(),now=self.now)
    def test_future_rejected(self):
        with self.assertRaises(ValueError):
            k.recognize(self.data(),now=self.now-dt.timedelta(days=1))
    def test_negative_volume_rejected(self):
        self.bars[-1]["volume"]=-1
        with self.assertRaises(ValueError):k.recognize(self.data(),now=self.now)
    def test_zero_previous_volume_no_ratio(self):
        for b in self.bars:b["volume"]=0
        self.assertIsNone(k.recognize(self.data(),now=self.now)["volume_vs_media20"])
    def test_microprice(self):
        for b in self.bars:
            for name in ("open","high","low","close"):b[name]*=1e-8
        self.assertEqual(k.recognize(self.data(),now=self.now)["barre"],60)
    def test_ohlc_change_changes_evidence(self):
        first=k.recognize(self.data(),now=self.now)
        self.bars[-1]["close"]=self.bars[-1]["open"]
        self.assertNotEqual(first,k.recognize(self.data(),now=self.now))
    def test_stale_not_current(self):
        later=self.now+dt.timedelta(days=2)
        self.assertEqual(k.recognize(self.data(),now=later)["stato"],"SCADUTO")

    def test_dossier_packet_recomputation_and_tamper_stop(self):
        import patrimonio_4tf as portfolio
        from scripts import kdd_wallet_packet_g0 as wallet
        now=dt.datetime.fromtimestamp((1794000000//86400)*86400+120,dt.timezone.utc)
        row={"coppia":"BTC/EUR","pair_key":"XXBTZEUR",
             "asset_base":"BTC","valuta_quotazione":"EUR",
             "stato":"COMPLETO","timeframe":{}}
        for label,sec in k.FRAMES.items():
            end=int((now.timestamp()-120)//sec)*sec
            bars=[{"time":end-60*sec+i*sec,
                   "open":100+i*.01,"high":101+i*.01,"low":99+i*.01,
                   "close":100+i*.01,"volume":100} for i in range(60)]
            source={"timeframe":label,"interval_seconds":sec,"candles":bars,
                    "observed_utc":now.isoformat(timespec="seconds"),
                    "closed_at_utc":dt.datetime.fromtimestamp(end,dt.timezone.utc).isoformat(timespec="seconds"),
                    "pair":"BTC/EUR","pair_key":"XXBTZEUR","token":"BTC",
                    "source":"Kraken Spot synthetic"}
            row["timeframe"][label]=portfolio.analyze_frame(source,now)
        packet=wallet.technical_in_packet(row,now)
        for label in k.FRAMES:
            self.assertEqual(packet["timeframe"][label]["figure_candlestick"],
                             row["timeframe"][label]["figure_candlestick"])
        row["timeframe"]["4H"]["figure_candlestick"]["figure"]=[{"figura":"FALSA"}]
        with self.assertRaises(wallet.PacketError):
            wallet.technical_in_packet(row,now)
