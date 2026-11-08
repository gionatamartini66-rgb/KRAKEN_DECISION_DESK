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
    def test_hammer_context_changes_with_prior_trend(self):
        def evidence(delta):
            for i,b in enumerate(self.bars):
                o=100+delta*i
                b.update(open=o, high=o+1, low=o-1, close=o+.1)
            b=self.bars[-1]
            b.update(open=b["open"], close=b["open"]+.1,
                     high=b["open"]+.25, low=b["open"]-1)
            return k.recognize(self.data(),now=self.now)
        down=evidence(-.3)
        up=evidence(.3)
        def hammer(x):return next(f for f in x["figure"] if f["figura"]=="HAMMER_PIN_BAR")
        self.assertNotEqual(hammer(down)["contesto"]["trend_antecedente"],
                            hammer(up)["contesto"]["trend_antecedente"])
        self.assertNotEqual(hammer(down)["conflitti"],hammer(up)["conflitti"])

    def test_double_test_requires_closed_reaction(self):
        level=98.0
        for b in self.bars[-7:]:
            b.update(open=98.5,high=99,low=level,close=98.5)
        self.assertNotIn("DOPPIO_TEST_LIVELLO",
            [f["figura"] for f in k.recognize(self.data(),now=self.now)["figure"]])

    def test_deep_wick_not_retest(self):
        for b in self.bars:
            b.update(open=100, high=101, low=99, close=100)
        self.bars[-3].update(open=100, high=104, low=99, close=103)
        self.bars[-2].update(open=103, high=105, low=102, close=104)
        self.bars[-1].update(open=104, high=105, low=90, close=103)
        self.assertNotIn("RETEST_DOPO_BREAKOUT",
            [f["figura"] for f in k.recognize(self.data(),now=self.now)["figure"]])

    def test_historical_hammer_invalidated_after_closed_bar(self):
        b=self.bars[-2]
        b.update(open=100, high=100.2, low=99, close=100.1)
        self.bars[-1].update(open=99, high=99.5, low=98, close=98.5)
        figures=k.recognize(self.data(),now=self.now)["figure"]
        self.assertTrue(any(f["figura"]=="HAMMER_PIN_BAR" and
                            f["stato"]=="INVALIDATA" for f in figures))

    def test_cross_timeframe_contradiction_and_missing(self):
        frames={label:{"figure_candlestick":{"stato":"AGGIORNATO",
                "trend_precedente":"DISCESA" if label in ("15m","1H") else "SALITA"}}
                for label in k.FRAMES}
        self.assertTrue(k.compare_context(frames)["contraddizione_alto_basso"])
        frames["1D"]={}
        self.assertEqual(k.compare_context(frames)["trend_per_timeframe"]["1D"],"NON_DISPONIBILE")
    def test_rt42_f3_01_double_test_context_immutable_after_future_bars(self):
        # 60 contiguous 15m candles. Historical support at index 40,
        # touches at 54 and 56, closed rebound at 55, later breakout.
        for b in self.bars:
            b.update(open=100, high=101, low=99, close=100, volume=100)
        self.bars[40].update(low=98, close=99)
        self.bars[54].update(open=99, low=98, close=98.4)
        self.bars[55].update(open=98.4, low=98.3, high=100, close=99.5)
        self.bars[56].update(open=99, low=98, close=98.4)
        self.bars[57].update(open=99, low=98.5, high=99.8, close=99)
        self.bars[58].update(open=100, low=99, high=102, close=101.5)
        self.bars[59].update(open=101.5, low=100, high=104, close=103)
        def run(n):
            data=self.data()
            data["candles"]=self.bars[:n]
            close=dt.datetime.fromtimestamp(
                data["candles"][-1]["time"]+self.sec,dt.timezone.utc)
            data["closed_at_utc"]=close.isoformat()
            data["observed_utc"]=(close+dt.timedelta(seconds=120)).isoformat()
            return k.recognize(data,now=close+dt.timedelta(seconds=120))
        before=run(58)
        after=run(60)
        def event(result):
            return next(x for x in result["figure"]
                        if x["figura"]=="DOPPIO_TEST_LIVELLO"
                        and len(x["fasi_utc"])==2)
        a,b=event(before),event(after)
        for field in ("evento_chiusura_utc","contesto","conflitti",
                      "forma_osservata","fasi_utc","livello_testato"):
            self.assertEqual(a[field],b[field],field)
        self.assertEqual(a["stato"],"IN_ATTESA_CONFERMA")
        self.assertEqual(b["stato"],"REAZIONE_CHIUSA_OSSERVATA")
        self.assertEqual(b["risoluzione_utc"],
                         dt.datetime.fromtimestamp(self.bars[58]["time"]+self.sec,
                                                   dt.timezone.utc).isoformat(timespec="seconds"))

    def test_rt42_f3_01_historical_hammer_context_immutable(self):
        b=self.bars[-3]
        b.update(open=100,high=100.2,low=99,close=100.1)
        def run(n):
            data=self.data()
            data["candles"]=self.bars[:n]
            close=dt.datetime.fromtimestamp(data["candles"][-1]["time"]+self.sec,
                                            dt.timezone.utc)
            data["closed_at_utc"]=close.isoformat()
            data["observed_utc"]=(close+dt.timedelta(seconds=120)).isoformat()
            return k.recognize(data,now=close+dt.timedelta(seconds=120))
        a=next(f for f in run(58)["figure"] if f["figura"]=="HAMMER_PIN_BAR")
        self.bars[-2].update(open=99,high=99.5,low=98,close=98.5)
        b=next(f for f in run(60)["figure"] if f["figura"]=="HAMMER_PIN_BAR"
               and f["evento_chiusura_utc"]==a["evento_chiusura_utc"])
        for field in ("evento_chiusura_utc","contesto","conflitti",
                      "forma_osservata","fasi_utc"):
            self.assertEqual(a[field],b[field],field)
        self.assertEqual(b["stato"],"INVALIDATA")
