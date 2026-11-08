"""G0 fixture regressions; ALL values invented; no real wallet source loaded."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import kdd_wallet_packet_g0 as p

UTC=dt.timezone.utc
T=dt.datetime(2026,10,25,18,0,tzinfo=UTC)


class WalletPacketG0Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        iso=T.isoformat()
        self.portfolio={
            "t0_id":"SECRET_OMIT_THIS_FIELD", "t0_sha256":"SHOULD_NOT_EXPORT_T0",
            "credenziali":"SHOULD_NOT_EXPORT_SECRET",
            "posizioni":[
                {"token":"ADA","quantita":"4.20", "disponibile_spot":"4.10", "costo_medio_eur":None},
                {"token":"ETH","quantita":"1.0", "disponibile_spot":"1.0","costo_medio_eur":None},
                {"token":"SXT","quantita":"5", "disponibile_spot":"5", "costo_medio_eur":None}
            ],
            "data_ora_saldo_privato_utc":iso,
            "fonte_quantita":"Kraken BalanceEx API privata SOLA LETTURA, "+iso,
            "liquidita_spot_api": {"EUR":{"saldo":"0.00","disponibile":"0.00"},
                                   "USDC":{"saldo":"18","disponibile":"18"},
                                   "USD":{"saldo":"0","disponibile":"0"},
                                   "EURC":{"saldo":"0","disponibile":"0"}},
            "segmenti_non_spot":{"BTC":["SHOULD_NOT_EXPORT_OTHER_WALLET"]}
        }
        self.snapshot={"rilevazione_utc":iso,
                       "markets":{"ADA":{"token":"ADA","pair":"ADA/EUR", "pair_key":"ADAEUR", "prezzo_eur":1.0},
                                  "ETH":{"token":"ETH","pair":"ETH/EUR", "pair_key":"XETHZEUR", "prezzo_eur":2000.0}},
                       "trends":{"ADA":{"var_7g_pct":12.3,"sopra_media20":True},
                                 "ETH":{"var_7g_pct":-4.25,"sopra_media20":False}},
                       "schede_v02":[{"token":"SOL","esito":"RIESAME MIRATO",
                                       "coppia_analisi":"SOL/USD","categoria":"ripartenza",
                                       "evidenze":["Volume spot vicino al picco"],
                                       "criticita":["Spread da verificare"],
                                       "password":"SHOULD_NOT_EXPORT_CREDENTIAL"}]}
        self.report={"rilevazione_utc":iso,
                     "posizioni":[{"token":"ADA","quantita":"4.2", "prezzo_eur":1.0,
                                   "valore_eur":4.2,"pl_non_realizzato_eur":None,
                                   "note":["Rivedere posizione"],"decisione":"REVISIONE OGGI"},
                                  {"token":"ETH","quantita":"1", "prezzo_eur":2000,
                                   "valore_eur":2000,"pl_non_realizzato_eur":None,
                                   "note":["Nessuna decisione"], "decisione":"ESAME"},
                                  {"token":"SXT","errore":"Nessuna quotazione EUR", "decisione":"RIVEDERE"}],
                     "saldo_stato":{"ultimo_tentativo":"RIUSCITO"},
                     "liquidita_spot_api":self.portfolio["liquidita_spot_api"],
                     "totale_stimato_eur":2004.2,"totale_parziale":True,
                     "mercato":"BTC struttura mista",
                     "extra_secret":"SHOULD_NOT_EXPORT_REPORT_PRIVATE"}
        self.dossier={"kraken_istantanea_utc":iso,
                      "grafici_4h":{"ADA":{"token":"ADA", "stato":"OK", "coppia":"ADA/EUR",
                                           "lettura_indicativa":{"ultima_chiusura_utc":(T-dt.timedelta(hours=2)).isoformat(),
                                               "ultime_4":{"minimo":1.1,"massimo":1.5},
                                               "volume_ultime_4":12.3,
                                               "extra_secret":"SHOULD_NOT_EXPORT_READINGS_EXTRA"},
                                           "serie_ohlcv_chiuse":["SHOULD_NOT_EXPORT_RAW_CANDLES"]},
                                     "ETH":{"token":"DOGE", "stato":"OK", "coppia":"ETH/EUR"}},
                      "secret":"SHOULD_NOT_EXPORT_PRIVATE_DOSSIER"}
        self.dump()

    def dump(self):
        for name,doc in [("portafoglio.json",self.portfolio), ("ultimo_report.json",self.report),
                         ("ultima_rilevazione.json",self.snapshot), ("dossier_multifonte.json",self.dossier)]:
            (self.root/name).write_text(json.dumps(doc,ensure_ascii=False), encoding="utf-8")

    def pack(self,now=T):
        return p.build(self.root, now=now)

    def _analytic_fixture(self):
        iso=T.isoformat()
        self.snapshot["binance_reference"] = {
            "status":"OK", "observed_utc":iso, "tokens":[
                {"token":"ADA", "status":"OK", "binance_pairs":[{"pair":"ADAUSDT"}],
                 "binance_base_volume_24h_subset":500, "kraken_base_volume_24h_subset":250,
                 "volume_ratio_subsets":2},
                {"token":"SOL", "status":"NOT_LISTED_FOR_QUOTE", "binance_pairs":[]}]}
        self.dossier["candidati"] = [{
            "token":"SOL", "coppia_analisi":"SOL/USD",
            "flusso_spot_kraken":{"stato":"COMPLETO_4H", "coppia":"SOL/USD",
                "osservato_utc":iso, "finestra_4h_completa":True,
                "numero_trade_ottenuti":900, "durata_campione_secondi":14401,
                "delta_4h":{"numero_trade":900, "acquisti_aggressivi_quote":1200,
                            "vendite_aggressive_quote":900, "delta_quote":300,
                            "percentuale_netto_su_volume":14.29}},
            "fondamentali_coingecko":{"id":"solana", "fonte":"https://api.coingecko.com/api/v3/coins/solana",
                "aggiornato_utc":iso, "capitalizzazione_usd":8000,
                "offerta_circolante":100, "offerta_totale":110},
            "simulazione_costi_eur_wallet":[{"coppia":"SOL/USD",
                "costo_roundtrip_eur":1.25, "n_conversioni":1}]}]
        self.dossier["contesto_derivati_btc"] = {
            "strumento":"PF_XBTUSD",
            "open-interest":{"ultimo_punto_utc":iso, "ultimo_punto_provvisorio":False,
                             "ultimo_close":123, "close_4h_fa":110},
            "cvd":{"ultimo_punto_utc":iso, "ultimo_punto_provvisorio":False,
                   "ultimo_cvd":5, "cvd_4h_fa":3, "ultimo_buy_volume":9,
                   "ultimo_sell_volume":4}}
        self.dossier["fonti_esterne"] = {"coingecko_global":{
            "fonte":"https://api.coingecko.com/api/v3/global",
            "aggiornato_sorgente_utc":T.timestamp(),
            "capitalizzazione_totale_usd":123456,
            "volume_24h_usd":5000, "dominanza_btc_pct":56.7}}
        self.dump()

    def test_issue43_economic_source_packet_bridge_and_aging(self):
        import kdd_economics as econ
        import kdd_bridge_g2 as bridge
        self._analytic_fixture()
        held = [x["token"] for x in self.portfolio["posizioni"]]
        rows = []
        for i, token in enumerate(held):
            ident = econ.identify(token, token+"/EUR", token+"EUR",
                                  catalog_verified=token in econ.PROJECTS)
            rows.append({"indice": i, "token": token, "identita": ident,
                         "fondamentali": econ.fundamentals(ident,None,T,T),
                         "evento": econ.release_event(ident,None,T,T)})
        candidate = self.dossier["candidati"][0]
        ident = econ.identify("SOL","SOL/USD","SOLUSD",catalog_verified=True)
        economic = {"schema": econ.VERSION, "acquisito_utc": T.isoformat(),
                    "posizioni": rows,
                    "candidati": [{"indice":0,"token":"SOL",
                                  "coppia_analisi":"SOL/USD","identita":ident,
                                  "fondamentali":econ.fundamentals(ident,None,T,T),
                                  "evento":econ.release_event(ident,None,T,T)}],
                    "macro":econ.macro([],T),
                    "regime":{"stato":"INDETERMINATO","qualita":"INSUFFICIENTE"}}
        self.dossier["evidenze_economiche"] = economic
        self.dump()
        packet = self.pack()
        self.assertEqual(len(packet["evidenze_multifonte"]["economia"]["posizioni"]),3)
        self.assertEqual(len(packet["evidenze_multifonte"]["economia"]["candidati"]),1)
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":packet,
                "packet_sha256":bridge.digest(packet),
                "preparato_utc":T.isoformat(),
                "provenienza":"KDD_LOCALE_DICHIARATA_NON_AUTENTICATA",
                "trasporto":"MANUALE_NON_ESEGUITO"}
        current=bridge.read_context(bundle,now=T)
        self.assertEqual(len(current["evidenze_economiche_alla_lettura"]["posizioni"]),3)
        later=bridge.read_context(bundle,now=T+dt.timedelta(days=3))
        self.assertEqual(later["evidenze_economiche_alla_lettura"]["regime"]["qualita"],"SCADUTO")
        packet["evidenze_multifonte"]["economia"]["posizioni"][0]["token"]="ETH"
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(bundle,now=T)
        # Even if the attacker recomputes the local SHA, attribution must STOP.
        packet["evidenze_multifonte"]["economia"]["posizioni"][0]["token"]="ADA"
        packet["evidenze_multifonte"]["economia"]["posizioni"][0]["identita"]["coingecko_id"]="bitcoin"
        bundle["packet_sha256"]=bridge.digest(packet)
        with self.assertRaisesRegex(bridge.BridgeError,"economica"):
            bridge.read_context(bundle,now=T)

    def test_issue43_economic_source_tamper_stops_packet(self):
        import kdd_economics as econ
        self._analytic_fixture()
        rows=[{"indice":i,"token":x["token"],
               "identita":econ.identify(x["token"],None,None),
               "fondamentali":econ.fundamentals({},None,T,T),
               "evento":econ.release_event({},None,T,T)}
              for i,x in enumerate(self.portfolio["posizioni"])]
        self.dossier["evidenze_economiche"]={
            "schema":econ.VERSION,"acquisito_utc":T.isoformat(),
            "posizioni":rows,"candidati":[],
            "regime":{"stato":"INDETERMINATO"},
            "macro":econ.macro([],T)}
        self.dump()
        with self.assertRaises(p.PacketError):
            self.pack()

    def test_analytic_handoff_multisource_to_actual_bridge_reader(self):
        self._analytic_fixture()
        pkt=self.pack()
        evidence=pkt["evidenze_multifonte"]
        self.assertEqual(evidence["benchmark_copertura"]["token_esaminati"],2)
        self.assertEqual(evidence["benchmark_copertura"]["token_con_dati"],1)
        self.assertEqual(evidence["benchmark_binance"][0]["volume_base_binance_24h"],"500")
        self.assertEqual(evidence["benchmark_binance"][0]["unita"],"quantita token base in 24h")
        candidate=evidence["candidati"][0]
        self.assertEqual(candidate["token"],"SOL")
        self.assertEqual(candidate["flusso_spot"]["coppia"],"SOL/USD")
        self.assertEqual(candidate["flusso_spot"]["delta_4h"]["delta_quote"],"300")
        self.assertEqual(candidate["fondamentali"]["id_coingecko"],"solana")
        self.assertEqual(candidate["simulazioni_costi"]["righe"][0]["costo_roundtrip_eur"],"1.25")
        self.assertEqual(evidence["derivati_btc"]["open-interest"]["valori"]["ultimo_close"],"123")
        self.assertEqual(evidence["contesto"]["dominanza_btc_pct"],"56.7")
        self.assertEqual(pkt["patrimonio"]["n_posizioni"],3)
        import kdd_bridge_g2 as bridge
        if not hasattr(bridge, "SCHEMA_BUNDLE") or not hasattr(bridge, "read_context"):
            self.skipTest("Updater packaging fixture uses a bridge placeholder; genuine bridge tested in repository")
        bundle={"schema":bridge.SCHEMA_BUNDLE, "packet":pkt,
                "packet_sha256":bridge.digest(pkt), "preparato_utc":T.isoformat(),
                "provenienza":"KDD_LOCALE_DICHIARATA_NON_AUTENTICATA",
                "trasporto":"MANUALE_NON_ESEGUITO"}
        self.assertIsInstance(bridge.read_context(bundle,now=T),dict)

    def test_analytic_handoff_wrong_pair_partial_stale_and_missing_are_not_values(self):
        self._analytic_fixture()
        flow=self.dossier["candidati"][0]["flusso_spot_kraken"]
        flow["coppia"]="ETH/USD"
        self.dossier["candidati"][0]["fondamentali_coingecko"]={"stato":"ID non verificato"}
        self.dossier["candidati"][0]["simulazione_costi_eur_wallet"][0]["coppia"]="ETH/USD"
        self.dossier["contesto_derivati_btc"]["cvd"]["ultimo_punto_utc"]=(T-dt.timedelta(hours=3)).isoformat()
        self.dump()
        ev=self.pack()["evidenze_multifonte"]
        self.assertEqual(ev["candidati"][0]["flusso_spot"]["stato"],"COPPIA_INCOERENTE")
        self.assertIsNone(ev["candidati"][0]["flusso_spot"]["delta_4h"])
        self.assertEqual(ev["candidati"][0]["fondamentali"]["stato"],"NON_VERIFICATO")
        self.assertEqual(ev["candidati"][0]["simulazioni_costi"]["righe"],[])
        self.assertEqual(ev["derivati_btc"]["cvd"]["stato"],"SCADUTO")
        self.assertIsNone(ev["derivati_btc"]["cvd"]["valori"])

    def test_r1_stale_book_cost_is_historical_without_usable_number(self):
        self._analytic_fixture()
        stale=(T-dt.timedelta(hours=3)).isoformat()
        self.snapshot["rilevazione_utc"]=stale
        self.dossier["kraken_istantanea_utc"]=stale
        # Directly exercise the analytical selector: a packet may reject a
        # stale source before this path, which would otherwise hide the defect.
        evidence=p.analytic_evidence(
            self.snapshot, self.dossier, [{"token":"SOL","stato_identita":"VALIDA"}],
            [{"token":"SOL","coppia_analisi":"SOL/USD"}], T)
        costs=evidence["candidati"][0]["simulazioni_costi"]
        self.assertEqual(costs["stato"],"COSTO_STORICO")
        self.assertEqual(costs["righe"][0]["stato"],"COSTO_STORICO")
        self.assertIsNone(costs["righe"][0]["costo_roundtrip_eur"])
        self.assertEqual(costs["freschezza"],"DA_AGGIORNARE")
        self.assertIn("storica", costs["limite"].lower())

    def test_r1_covered_rolling_15m_survives_incomplete_4h_and_closed_is_distinct(self):
        import flusso_spot
        if not hasattr(flusso_spot, "analyze"):
            self.skipTest("Updater packaging fixture has producer placeholder")
        self._analytic_fixture()
        now=T.timestamp()
        # 20m history covers rolling 15m, not the preceding four hours.
        trades=[["10","1",now-1200,"b","m",""],
                ["10","2",now-700,"s","m",""],
                ["10","4",now-60,"b","m",""]]
        flow=flusso_spot.analyze(trades,now,"SOL/USD")
        self.assertFalse(flow["finestra_4h_completa"])
        self.assertTrue(flow["finestra_15m_completa"])
        self.assertIsNone(flow["delta_4h"])
        flow["osservato_utc"]=T.isoformat()
        self.dossier["candidati"][0]["flusso_spot_kraken"]=flow
        self.dump()
        out=self.pack()["evidenze_multifonte"]["candidati"][0]["flusso_spot"]
        self.assertEqual(out["stato"],"INCOMPLETO")
        self.assertIsNone(out["delta_4h"])
        self.assertEqual(out["delta_15m_mobile"]["stato"],"DISPONIBILE")
        self.assertEqual(out["delta_15m_mobile"]["valori"]["delta_quote"],"20.0")
        self.assertEqual(out["delta_candela_15m_chiusa"]["stato"],"RIFERIMENTO_MANCANTE")
        self.assertIsNone(out["delta_candela_15m_chiusa"]["valori"])
        # An independently covered closed candle has explicit boundaries.
        end=dt.datetime.fromtimestamp((int(now)//900)*900-900,dt.timezone.utc)
        # Use synthetic timestamps relative to that boundary for full coverage.
        end_ts=end.timestamp()
        covered=[["10","1",end_ts-1000,"b","m",""],
                 ["10","2",end_ts-800,"s","m",""],
                 ["10","4",now-1,"b","m",""]]
        closed=flusso_spot.analyze(covered,now,"SOL/USD",end.isoformat())
        self.assertEqual(closed["candela_15m_chiusa"]["stato"],"COMPLETA")
        closed["osservato_utc"]=T.isoformat()
        self.dossier["candidati"][0]["flusso_spot_kraken"]=closed
        self.dump()
        out=self.pack()["evidenze_multifonte"]["candidati"][0]["flusso_spot"]
        self.assertEqual(out["delta_candela_15m_chiusa"]["stato"],"DISPONIBILE")
        self.assertEqual(out["delta_candela_15m_chiusa"]["fine_utc"],end.isoformat(timespec="seconds"))
        self.assertIsNone(out["delta_4h"])

    def test_analytic_handoff_genuine_kraken_trade_producer(self):
        import flusso_spot
        if not hasattr(flusso_spot, "analyze"):
            self.skipTest("Updater packaging fixture uses a producer placeholder; genuine producer tested in repository")
        self._analytic_fixture()
        now=T.timestamp()
        trades=[
            ["10","1",now-14500,"b","m",""],
            ["10","2",now-120,"s","m",""],
            ["10","4",now-60,"b","m",""]]
        produced=flusso_spot.analyze(trades,now,"SOL/USD")
        self.assertEqual(produced["stato"],"COMPLETO_4H")
        produced["osservato_utc"]=T.isoformat()
        self.dossier["candidati"][0]["flusso_spot_kraken"]=produced
        self.dump()
        packet=self.pack()
        flow=packet["evidenze_multifonte"]["candidati"][0]["flusso_spot"]
        self.assertEqual(flow["stato"],"DISPONIBILE")
        self.assertEqual(flow["delta_4h"]["delta_quote"],"20.0")
        self.assertEqual(flow["numero_trade"],3)
        self.assertEqual(flow["unita"],"valuta di quotazione USD")

    def test_analytic_handoff_incomplete_and_unaligned_dossier(self):
        self._analytic_fixture()
        self.dossier["candidati"][0]["flusso_spot_kraken"]["stato"]="FINESTRA_4H_NON_COPERTA"
        self.dossier["candidati"][0]["flusso_spot_kraken"]["finestra_4h_completa"]=False
        self.dump()
        self.assertEqual(self.pack()["evidenze_multifonte"]["candidati"][0]["flusso_spot"]["stato"],"INCOMPLETO")
        self.dossier["kraken_istantanea_utc"]=(T-dt.timedelta(minutes=1)).isoformat()
        self.dump()
        self.assertEqual(self.pack()["evidenze_multifonte"]["stato"],"NON_ALLINEATO")

    def test_economic_context_is_in_real_packet_path_and_not_a_recommendation(self):
        packet = self.pack()
        summary = packet["patrimonio"]["quadro_economico_per_gpt"]
        # SXT has no EUR quote: no invented percentages.
        self.assertEqual(summary["stato"], "NON_CALCOLABILE_INTEGRALMENTE")
        self.assertEqual(len(summary["quote_posizioni"]), 3)
        self.assertTrue(all(x["quota_pct"] is None for x in summary["quote_posizioni"]))
        self.assertIsNone(summary["concentrazione_top2_pct"])
        self.assertEqual(summary["liquidita_stato"],
                         "PRESENTE_PER_VALUTA_EQUIVALENZA_EUR_NON_ATTESTATA")
        self.assertEqual(summary["esempio_150_finanziamento_stato"],
                         "NON_DETERMINABILE_SENZA_CAMBIO_SPREAD_E_COSTI")
        self.assertIn("non è proposta", summary["vincoli"][0])

    def test_economic_context_exact_arithmetic_no_cross_currency_fx(self):
        positions = [{"token": "BTC", "valore_eur": "300"},
                     {"token": "ETH", "valore_eur": "100"}]
        zero_cash = {c: {"disponibile": "0"} for c in ("EUR", "EURC", "USD", "USDC")}
        result = p.quadro_economico_per_gpt(positions, zero_cash, "400")
        self.assertEqual(result["stato"], "INDICATIVO")
        self.assertEqual([x["quota_pct"] for x in result["quote_posizioni"]],
                         ["75.00", "25.00"])
        self.assertEqual(result["concentrazione_top2_pct"], "100.00")
        self.assertEqual(result["esempio_150_eur_sul_patrimonio_pct"], "37.50")
        self.assertEqual(result["liquidita_stato"], "ZERO_RILEVATO_NELLE_QUATTRO_VALUTE")
        self.assertEqual(result["esempio_150_finanziamento_stato"],
                         "NESSUNA_LIQUIDITA_SULLE_QUATTRO_VALUTE_VERIFICARE_FONTI")
        cash = {**zero_cash, "USDC": {"disponibile": "3"}}
        result = p.quadro_economico_per_gpt(positions, cash, "400")
        self.assertEqual(result["liquidita_stato"],
                         "PRESENTE_PER_VALUTA_EQUIVALENZA_EUR_NON_ATTESTATA")
        self.assertEqual(result["esempio_150_finanziamento_stato"],
                         "NON_DETERMINABILE_SENZA_CAMBIO_SPREAD_E_COSTI")

    def test_economic_context_fails_closed_on_forged_total_duplicate_invalid_values(self):
        p1 = [{"token": "BTC", "valore_eur": "100"},
              {"token": "ETH", "valore_eur": "200"}]
        with self.assertRaisesRegex(p.PacketError, "totale discordante"):
            p.quadro_economico_per_gpt(p1, {}, "200")
        duplicate = p.quadro_economico_per_gpt([p1[0], p1[0]], {}, "200")
        self.assertEqual(duplicate["stato"], "NON_CALCOLABILE_INTEGRALMENTE")
        self.assertEqual(len(duplicate["quote_posizioni"]), 2)
        self.assertTrue(all(x["quota_pct"] is None for x in duplicate["quote_posizioni"]))
        unknown = p.quadro_economico_per_gpt(
            [{"token": None, "stato_identita": "IDENTITA_NON_VALIDA", "valore_eur": None}],
            {}, None)
        self.assertEqual(unknown["quote_posizioni"][0]["token"], None)
        self.assertEqual(unknown["stato"], "NON_CALCOLABILE_INTEGRALMENTE")
        with self.assertRaisesRegex(p.PacketError, "Numero non valido"):
            p.quadro_economico_per_gpt([{"token": "BTC", "valore_eur": "-1"}], {}, "-1")
        with self.assertRaisesRegex(p.PacketError, "Numero non valido"):
            p.quadro_economico_per_gpt([{"token": "BTC", "valore_eur": "NaN"}], {}, "1")

    def test_economic_context_zero_or_missing_total_never_divides(self):
        row = [{"token": "BTC", "valore_eur": "0"}]
        self.assertEqual(p.quadro_economico_per_gpt(row, {}, "0")["stato"],
                         "NON_CALCOLABILE_INTEGRALMENTE")
        self.assertIsNone(p.quadro_economico_per_gpt(row, {}, "0")
                          ["esempio_150_eur_sul_patrimonio_pct"])
        self.assertEqual(p.quadro_economico_per_gpt(row, {}, None)["stato"],
                         "NON_CALCOLABILE_INTEGRALMENTE")

    def test_book_packet_missing_legacy_field_is_explicit(self):
        packet = self.pack()
        self.assertEqual(packet["patrimonio"]["book_pubblico_150"]["stato"],
                         "NON_ATTESTATO")

    def test_real_funding_alternatives_150_use_available_not_owned(self):
        positions = [
            {"indice": 0, "token": "BTC", "stato_identita": "VALIDA",
             "quantita_spot": "0.01", "disponibile_spot": "0.002",
             "prezzo_eur": "50000", "valore_eur": "500",
             "fonte_prezzo_eur": {"token": "BTC", "valuta": "EUR", "pair": "XBT/EUR"}},
            {"indice": 1, "token": "ETH", "stato_identita": "VALIDA",
             "quantita_spot": "1", "disponibile_spot": "0.2",
             "prezzo_eur": "2000", "valore_eur": "2000",
             "fonte_prezzo_eur": {"token": "ETH", "valuta": "EUR", "pair": "ETH/EUR"}},
            {"indice": 2, "token": "SOL", "stato_identita": "VALIDA",
             "quantita_spot": "3", "disponibile_spot": "3",
             "prezzo_eur": "100", "valore_eur": "300",
             "fonte_prezzo_eur": {"token": "SOL", "valuta": "EUR", "pair": "SOL/EUR"}},
        ]
        result = p.alternative_liquidazione_150_lorda(
            positions, "2800", mercato_stato="RECENTE", saldo_stato="RECENTE")
        a, b, c = result["alternative"]
        self.assertEqual([x["token"] for x in result["alternative"]], ["BTC", "ETH", "SOL"])
        self.assertEqual(result["n_fonti_potenziali_lorde"], 2)
        self.assertEqual(a["massimo_lordo_indicativo_eur"], "100.000")
        self.assertFalse(a["capienza_lorda_fotografia"])
        self.assertIsNone(a["quantita_teorica_150_lordi"])
        self.assertEqual(b["massimo_lordo_indicativo_eur"], "400.0")
        self.assertEqual(b["quantita_teorica_150_lordi"], "0.075")
        self.assertEqual(b["peso_asset_post_alleggerimento_pct"], "69.81")
        self.assertEqual(c["quantita_teorica_150_lordi"], "1.5")
        self.assertEqual(result["freschezza_fotografia"], "RECENTE_ALLA_COMPOSIZIONE")
        self.assertIn("non è un bid", result["limite"])
        self.assertEqual(result["alternativa_senza_operazione"]["azione"], "NON_CONVERTIRE_ORA")

    def test_funding_150_stale_and_missing_provenance_fail_without_fake_sale(self):
        row = {"indice": 0, "token": "BTC", "stato_identita": "VALIDA",
               "quantita_spot": "1", "disponibile_spot": "1",
               "prezzo_eur": "200", "valore_eur": "200",
               "fonte_prezzo_eur": {"token": "BTC", "valuta": "EUR", "pair": "XBT/EUR"}}
        stale = p.alternative_liquidazione_150_lorda(
            [row], "200", mercato_stato="DA_AGGIORNARE", saldo_stato="RECENTE")
        self.assertEqual(stale["freschezza_fotografia"], "NON_RECENTE_O_NON_ATTESTATA")
        self.assertEqual(stale["alternative"][0]["esito"], "SOGLIA_LORDA_POTENZIALE")
        for change in ({"disponibile_spot": None},
                       {"disponibile_spot": "2"},
                       {"fonte_prezzo_eur": {"token": "ETH", "valuta": "EUR", "pair": "XBT/EUR"}},
                       {"fonte_prezzo_eur": None}):
            case = {**row, **change}
            result = p.alternative_liquidazione_150_lorda([case], "200")
            self.assertEqual(result["alternative"][0]["esito"], "NON_VERIFICABILE")
            self.assertIsNone(result["alternative"][0]["capienza_lorda_fotografia"])
        unknown = {**row, "token": None, "stato_identita": "IDENTITA_NON_VALIDA"}
        result = p.alternative_liquidazione_150_lorda([unknown], "200")
        self.assertEqual(result["alternative"][0]["esito"], "IDENTITA_NON_VERIFICATA")

    def test_funding_150_packet_includes_all_rows_even_with_unknown_quote(self):
        packet = self.pack()
        result = packet["patrimonio"]["quadro_economico_per_gpt"]["alternative_liberazione_150_lordi"]
        self.assertEqual(result["n_posizioni_esaminate"], 3)
        self.assertEqual([x["token"] for x in result["alternative"]], ["ADA", "ETH", "SXT"])
        self.assertEqual(result["alternative"][2]["esito"], "NON_VERIFICABILE")
        self.assertEqual(result["n_fonti_potenziali_lorde"], 1)

    def test_wallet_first_all_assets_even_if_quote_missing(self):
        obj=self.pack()
        positions=obj['patrimonio']['posizioni']
        self.assertEqual([x['token'] for x in positions],['ADA','ETH','SXT'])
        self.assertEqual(positions[2]['prezzo_eur'],None)
        self.assertTrue(obj['patrimonio']['totale_parziale'])
        self.assertEqual(obj['patrimonio']['totale_stimato_eur_senza_cash'],'2004.2')
        self.assertIn('TUTTE le posizioni', obj['richiesta_gpt'])

    def test_privacy_allowlist_excludes_T0_secrets_raw_reports(self):
        content=json.dumps(self.pack(),ensure_ascii=False)
        for forbidden in ('SHOULD_NOT_EXPORT','t0_id','t0_sha256','costo_medio_eur','segmenti_non_spot','candles'):
            self.assertNotIn(forbidden,content)
        self.assertEqual(self.pack()['patrimonio']['liquidita_spot']['USDC']['disponibile'],'18')

    def test_different_snapshot_is_rejected(self):
        self.report['rilevazione_utc']=(T-dt.timedelta(hours=2)).isoformat()
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'acquisizioni differenti'):
            self.pack()

    def test_dossier_staleness_never_attributed_to_holdings(self):
        self.dossier['kraken_istantanea_utc']=(T-dt.timedelta(minutes=45)).isoformat()
        self.dump()
        packet=self.pack()
        self.assertFalse(packet['dossier']['coerente_con_mercato'])
        self.assertEqual(packet['patrimonio']['posizioni'][0]['grafico_4h']['stato'],'NON_DISPONIBILE')

    def test_wrong_token_4h_must_not_be_attributed(self):
        data=self.pack()['patrimonio']['posizioni']
        self.assertEqual(data[0]['grafico_4h']['stato'],'OK')
        self.assertEqual(data[0]['grafico_4h']['lettura_4h']['ultime_4']['massimo'],'1.5')
        self.assertEqual(data[1]['grafico_4h']['stato'],'NON_DISPONIBILE')

    def test_wrong_quote_pair_is_not_attributed(self):
        self.dossier['grafici_4h']['ADA']['coppia']='ADA/USDC'
        self.dump()
        self.assertEqual(self.pack()['patrimonio']['posizioni'][0]['grafico_4h']['stato'],'NON_DISPONIBILE')

    def test_4h_gaps_not_copied_as_valid_readings(self):
        self.dossier['grafici_4h']['ADA']['stato']='LACUNE_TEMPORALI'
        self.dump()
        chart=self.pack()['patrimonio']['posizioni'][0]['grafico_4h']
        self.assertEqual(chart['stato'],'LACUNE_TEMPORALI')
        self.assertNotIn('lettura_4h',chart)

    def test_old_data_marked_stale_even_when_valid(self):
        packet=self.pack(T+dt.timedelta(hours=7))
        self.assertEqual(packet['mercato']['stato'],'DA_AGGIORNARE')
        self.assertEqual(packet['saldo']['stato']['stato'],'DA_AGGIORNARE')

    def test_missing_balance_confirmation_not_marked_recent(self):
        self.portfolio['fonte_quantita']='manuale'
        self.dump()
        self.assertEqual(self.pack()['saldo']['stato']['stato'],'ORIGINE_SCONOSCIUTA')

    def test_quantity_disagreement_rejected(self):
        self.report['posizioni'][0]['quantita']='999'
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Quantita report/portafoglio diversa'):
            self.pack()

    def test_cash_disagreement_rejected(self):
        self.report['liquidita_spot_api']=json.loads(json.dumps(self.portfolio['liquidita_spot_api']))
        self.report['liquidita_spot_api']['USDC']['disponibile']='6'
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Liquidita report/portafoglio diversa'):
            self.pack()

    def test_total_disagreement_rejected(self):
        self.report['totale_stimato_eur']=2344.1
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Totale stimato non coincide'):
            self.pack()

    def test_negative_nan_and_infinite_numbers_rejected(self):
        for v in ('NaN','Infinity','-0.01'):
            with self.subTest(v=v):
                self.portfolio['posizioni'][0]['quantita']=v
                self.dump()
                with self.assertRaises(p.PacketError): self.pack()

    def test_no_private_file_is_written_in_default_mode(self):
        before={x.name:x.read_bytes() for x in self.root.iterdir()}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result=p.main(['--source-dir',str(self.root)])
        self.assertEqual(result,0)
        self.assertIn('output: NESSUNO', output.getvalue())
        self.assertEqual(before,{x.name:x.read_bytes() for x in self.root.iterdir()})

    def test_write_private_mode_file_permissions_and_no_source_modification(self):
        target=self.root/'private'/'wallet_packet_gpt_v001.json'
        before={x.name:x.read_bytes() for x in self.root.iterdir() if x.is_file()}
        with mock.patch.object(p,'PRIVATE_OUTPUT',target):
            with contextlib.redirect_stdout(io.StringIO()):
                result=p.main(['--source-dir',str(self.root),'--write-private'])
        self.assertEqual(result,0)
        self.assertEqual(target.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(target.read_text())['schema'],p.SCHEMA)
        self.assertEqual(before,{x.name:x.read_bytes() for x in self.root.iterdir() if x.is_file()})

    def test_unknown_private_output_path_rejected(self):
        with self.assertRaisesRegex(p.PacketError,'Destinazione privata non autorizzata'):
            p.write_private(self.pack(),target=self.root/'public.json')
        self.assertFalse((self.root/'public.json').exists())

    def test_symlink_source_rejected_without_following(self):
        (self.root/'portafoglio.json').unlink()
        (self.root/'portafoglio.json').symlink_to('/etc/hosts')
        with self.assertRaisesRegex(p.PacketError,'Input non regolare'):
            self.pack()

    def test_null_total_for_unvalued_positions_is_not_zero(self):
        for item in self.report["posizioni"]:
            item.pop("valore_eur", None)
            item.pop("prezzo_eur", None)
            item["errore"] = "Prezzo EUR non disponibile"
        self.report["stato_totale"] = "NON_DISPONIBILE"
        self.report["totale_stimato_eur"] = None
        self.dump()
        packet = self.pack()
        self.assertIsNone(packet["patrimonio"]["totale_stimato_eur_senza_cash"])
        self.assertTrue(packet["patrimonio"]["totale_parziale"])
        self.assertEqual(packet["patrimonio"]["stato_totale"], "NON_DISPONIBILE")

    def test_missing_total_with_real_valuations_is_rejected(self):
        self.report["totale_stimato_eur"] = None
        self.report["stato_totale"] = "NON_DISPONIBILE"
        self.dump()
        with self.assertRaisesRegex(p.PacketError, "Totale stimato mancante con posizioni valorizzate"):
            self.pack()

    def test_missing_dossier_fails_explicitly(self):
        (self.root/'dossier_multifonte.json').unlink()
        with self.assertRaisesRegex(p.PacketError,'Input non leggibile'):
            self.pack()


    def test_rt20261029_startup_original_full_both_modes(self):
        """Original full script; direct mode diagnosed, -m canonical and usable."""
        import subprocess, sys
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env.pop('PYTHONPATH',None)
        direct=subprocess.run([sys.executable,'-B','scripts/kdd_wallet_packet_g0.py','--help'],
            cwd=root,env=env,text=True,capture_output=True,timeout=15)
        # On isolated Linux without a PYTHONPATH/Termux prefix the original
        # full file must demonstrate the documented missing-root import;
        # the supported invocation is the module mode tested below.
        if sys.platform.startswith('linux') and not os.environ.get('PREFIX'):
            self.assertEqual(direct.returncode,1,direct.stderr)
            self.assertIn("No module named 'grafico_4h'",direct.stderr)
        # Direct invocation intentionally diagnosed here, without claiming PASS.
        if direct.returncode:
            self.assertEqual(direct.returncode,1)
            self.assertIn('ModuleNotFoundError',direct.stderr)
        else:
            self.assertIn('--source-dir',direct.stdout)
        module=subprocess.run([sys.executable,'-B','-m','scripts.kdd_wallet_packet_g0','--help'],
            cwd=root,env=env,text=True,capture_output=True,timeout=15)
        self.assertEqual(module.returncode,0,module.stderr)
        self.assertIn('--source-dir',module.stdout)
        before={f.name:f.read_bytes() for f in self.root.iterdir() if f.is_file()}
        executed=subprocess.run([sys.executable,'-B','-m','scripts.kdd_wallet_packet_g0',
                                  '--source-dir',str(self.root)],cwd=root,env=env,
                                  text=True,capture_output=True,timeout=20)
        self.assertEqual(executed.returncode,0,executed.stderr)
        print('KDD_CLI_FULL: direct_rc=%s module_help_rc=%s synthetic_packet_rc=%s write_private=NO' %
              (direct.returncode,module.returncode,executed.returncode))
        self.assertIn('output: NESSUNO',executed.stdout)
        self.assertEqual(before,{f.name:f.read_bytes() for f in self.root.iterdir() if f.is_file()})

    def test_rt20261029_amount_price_value_false_but_total_matches(self):
        self.report['posizioni'][0]['valore_eur']=100.0
        self.report['totale_stimato_eur']=2100.0
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Valore.*quantita'):
            self.pack()

    def test_rt20261029_pl_without_attested_cost_must_be_null(self):
        self.report['posizioni'][0]['pl_non_realizzato_eur']=10.0
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'P/L.*costo'):
            self.pack()

    def test_rt20261029_pl_with_invalid_cost_must_be_null(self):
        self.portfolio['posizioni'][0]['costo_medio_eur']='NaN'
        self.report['posizioni'][0]['pl_non_realizzato_eur']=10.0
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'P/L.*costo'):
            self.pack()

    def test_rt20261029_pl_false_with_known_cost(self):
        self.portfolio['posizioni'][0]['costo_medio_eur']='0.5'
        self.report['posizioni'][0]['pl_non_realizzato_eur']=9.0
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'P/L.*incoerente'):
            self.pack()

    def test_rt20261029_false_complete_with_unpriced_position(self):
        self.report['stato_totale']='COMPLETO'
        self.report['totale_parziale']=False
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'COMPLETO.*incomplete'):
            self.pack()

    def test_rt20261029_30min_150ms_is_stale(self):
        self.assertEqual(p.source_status(T,T+dt.timedelta(minutes=30,milliseconds=150))['stato'],
                         'DA_AGGIORNARE')
        self.assertEqual(p.source_status(T,T+dt.timedelta(minutes=30))['stato'],'RECENTE')

    def test_rt20261029_float_product_and_attested_pl_stay_valid(self):
        # Use the same finite Python float arithmetic used by build_report.
        self.portfolio['posizioni'][0]['quantita']='0.1'
        self.portfolio['posizioni'][0]['costo_medio_eur']='0.05'
        self.report['posizioni'][0]['quantita']='0.1'
        self.report['posizioni'][0]['prezzo_eur']=0.2
        self.snapshot['markets']['ADA']['prezzo_eur']=0.2
        self.report['posizioni'][0]['valore_eur']=float(0.1*0.2)
        self.report['posizioni'][0]['pl_non_realizzato_eur']=float((0.2-0.05)*0.1)
        self.report['totale_stimato_eur']=float(self.report['posizioni'][0]['valore_eur']+2000)
        self.dump()
        result=self.pack()
        self.assertIsNotNone(result['patrimonio']['posizioni'][0]['pl_indicativo_eur'])

    def test_rt20261029_forged_price_and_value_disagree_with_same_snapshot(self):
        # D1 report price comes from the same-market snapshot. Two mutually
        # coherent invented numbers must not bypass that source when present.
        self.snapshot['markets']['ADA']['prezzo_eur']=1.0
        self.report['posizioni'][0]['prezzo_eur']=10.0
        self.report['posizioni'][0]['valore_eur']=42.0
        self.report['totale_stimato_eur']=2042.0
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Prezzo.*rilevazione'):
            self.pack()

    def test_rt20261029_real_zero_and_invalid_cost_do_not_invent_pl(self):
        self.portfolio['posizioni'][0]['quantita']='0'
        self.portfolio['posizioni'][0]['costo_medio_eur']='nan'
        self.report['posizioni'][0]['quantita']='0'
        self.report['posizioni'][0]['valore_eur']=0.0
        self.report['posizioni'][0]['pl_non_realizzato_eur']=None
        self.report['totale_stimato_eur']=2000.0
        self.dump()
        out=self.pack()
        row=out['patrimonio']['posizioni'][0]
        self.assertEqual(float(row['valore_eur']),0.0)
        self.assertEqual(float(row['quantita_spot']),0.0)
        self.assertIsNone(row['pl_indicativo_eur'])


    # FIN-RT-01 — synthetic BTC, deliberately separate from pre-existing ADA fixture.
    def fin_rt01_btc(self):
        self.portfolio['posizioni']=[{'token':'BTC','quantita':'2',
                                     'disponibile_spot':'2',
                                     'costo_medio_eur':'80'}]
        self.report['posizioni']=[{'token':'BTC','quantita':'2',
                                   'prezzo_eur':100.0,'valore_eur':200.0,
                                   'pl_non_realizzato_eur':40.0}]
        self.report['totale_stimato_eur']=200.0
        self.report['stato_totale']='COMPLETO'
        self.report['totale_parziale']=False
        self.snapshot['markets']={'BTC':{'token':'BTC','pair':'XBT/EUR','pair_key':'XXBTZEUR',
                                         'prezzo_eur':100.0}}
        self.dossier['grafici_4h']={}
        self.dump()

    def test_fin_rt01_btc_row_missing_fails_closed(self):
        self.fin_rt01_btc()
        self.assertEqual(float(self.pack()['patrimonio']['posizioni'][0]['valore_eur']),200)
        del self.snapshot['markets']['BTC']
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Quotazione EUR di mercato'):
            self.pack()

    def test_fin_rt01_btc_eur_field_missing_fails_closed(self):
        self.fin_rt01_btc()
        self.assertEqual(float(self.pack()['patrimonio']['posizioni'][0]['prezzo_eur']),100)
        del self.snapshot['markets']['BTC']['prezzo_eur']
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Quotazione EUR di mercato'):
            self.pack()

    def test_fin_rt01_invalid_or_mismatched_eur_source_rejected(self):
        self.fin_rt01_btc()
        for bad in (None,'NaN','Infinity','nonsense',0,-1,101.0):
            with self.subTest(price=bad):
                self.snapshot['markets']['BTC']['prezzo_eur']=bad
                self.dump()
                with self.assertRaises(p.PacketError):
                    self.pack()
        self.snapshot['markets']['BTC']['prezzo_eur']=100.0
        self.dump()
        self.assertEqual(self.pack()['patrimonio']['posizioni'][0]['prezzo_eur'],'100.0')

    def test_fin_rt01_no_eur_source_unvalued_btc_survives(self):
        self.fin_rt01_btc()
        self.snapshot['markets'].pop('BTC')
        self.report['posizioni'][0]={'token':'BTC','quantita':'2',
                                     'errore':'Nessuna quotazione spot EUR'}
        self.report['totale_stimato_eur']=None
        self.report['stato_totale']='NON_DISPONIBILE'
        self.report['totale_parziale']=True
        self.dump()
        packet=self.pack()
        row=packet['patrimonio']['posizioni'][0]
        self.assertEqual(row['quantita_spot'],'2')
        self.assertIsNone(row['prezzo_eur'])
        self.assertIsNone(row['valore_eur'])
        self.assertIsNone(row['pl_indicativo_eur'])
        self.assertIsNone(packet['patrimonio']['totale_stimato_eur_senza_cash'])

    def test_fin_rt01_mixed_wallet_valid_eur_and_absent_eur(self):
        self.fin_rt01_btc()
        self.portfolio['posizioni'].append({'token':'ETH','quantita':'1',
                                             'disponibile_spot':'1','costo_medio_eur':None})
        self.report['posizioni'][0]={'token':'BTC','quantita':'2','errore':'Nessuna quotazione EUR'}
        self.report['posizioni'].append({'token':'ETH','quantita':'1',
                                          'prezzo_eur':2000.0,'valore_eur':2000.0,
                                          'pl_non_realizzato_eur':None})
        self.snapshot['markets']={'ETH':{'token':'ETH','pair':'ETH/EUR','pair_key':'XETHZEUR',
                                         'prezzo_eur':2000.0}}
        self.report['totale_stimato_eur']=2000.0
        self.report['stato_totale']='PARZIALE'
        self.report['totale_parziale']=True
        self.dump()
        packet=self.pack()
        rows=packet['patrimonio']['posizioni']
        self.assertEqual([x['token'] for x in rows],['BTC','ETH'])
        self.assertIsNone(rows[0]['valore_eur'])
        self.assertEqual(float(rows[1]['valore_eur']),2000.0)
        self.assertEqual(packet['patrimonio']['totale_stimato_eur_senza_cash'],'2000.0')
        self.assertTrue(packet['patrimonio']['totale_parziale'])

    def test_fin_rt01_real_zero_and_unknown_quantity_distinct(self):
        self.fin_rt01_btc()
        self.portfolio['posizioni'][0]['quantita']='0'
        self.report['posizioni'][0].update(quantita='0',valore_eur=0.0,
                                          pl_non_realizzato_eur=0.0)
        self.report['totale_stimato_eur']=0.0
        self.dump()
        row=self.pack()['patrimonio']['posizioni'][0]
        self.assertEqual(row['quantita_spot'],'0')
        self.assertEqual(float(row['valore_eur']),0.0)
        self.portfolio['posizioni'][0]['quantita']=None
        self.report['posizioni'][0]={'token':'BTC','errore':'Quantita non nota'}
        self.report['totale_stimato_eur']=None
        self.report['stato_totale']='NON_DISPONIBILE'
        self.report['totale_parziale']=True
        self.dump()
        row=self.pack()['patrimonio']['posizioni'][0]
        self.assertIsNone(row['quantita_spot'])
        self.assertIsNone(row['valore_eur'])


    def test_rt4_pair01_market_identity_mutations_fail_closed(self):
        self.fin_rt01_btc()
        self.snapshot['markets']['BTC']['token']='BTC'
        variants=(
            ('different_base', 'pair', 'ETH/EUR'),
            ('wrong_quote_usd', 'pair', 'BTC/USD'),
            ('wrong_quote_usdc', 'pair', 'ETH/USDC'),
            ('null_pair', 'pair', None),
            ('malformed_pair', 'pair', 'BTCEUR'),
            ('wrong_token', 'token', 'ETH'),
            ('null_token', 'token', None),
            ('wrong_explicit_base', 'base', 'ETH'),
            ('wrong_explicit_quote', 'quote', 'USD'),
            ('wrong_explicit_asset_base', 'asset_base', 'ETH'),
            ('wrong_explicit_quote_label', 'valuta_quotazione', 'USDC'),
            ('null_pair_key', 'pair_key', None),
            ('bad_pair_key', 'pair_key', 'ETH/EUR'),
        )
        for label,field,bad in variants:
            with self.subTest(case=label):
                good={'token':'BTC','pair':'XBT/EUR','pair_key':'XXBTZEUR',
                      'prezzo_eur':100.0}
                good[field]=bad
                self.snapshot['markets']['BTC']=good
                self.dump()
                with self.assertRaisesRegex(p.PacketError, 'Identita|Coppia|Kraken'):
                    self.pack()

    def test_rt4_pair01_valued_legacy_missing_metadata_fails_closed(self):
        self.fin_rt01_btc()
        good={'token':'BTC','pair':'XBT/EUR','pair_key':'XXBTZEUR',
              'prezzo_eur':100.0}
        for field in ('token','pair','pair_key'):
            with self.subTest(missing=field):
                self.snapshot['markets']['BTC']={k:v for k,v in good.items() if k!=field}
                self.dump()
                with self.assertRaisesRegex(p.PacketError, 'Identita|Coppia|Kraken'):
                    self.pack()

    def test_rt4_pair01_alias_btc_and_doge_positive(self):
        self.fin_rt01_btc()
        self.snapshot['markets']['BTC'].update(token='BTC',pair='XBT/EUR')
        self.dump()
        self.assertEqual(float(self.pack()['patrimonio']['posizioni'][0]['valore_eur']),200)
        self.snapshot['markets']['BTC']['token']='XBT'
        self.dump()
        self.assertEqual(float(self.pack()['patrimonio']['posizioni'][0]['valore_eur']),200)
        self.portfolio['posizioni'][0]['token']='DOGE'
        self.report['posizioni'][0]['token']='DOGE'
        self.snapshot['markets']={'DOGE':{'token':'DOGE','pair':'XDG/EUR',
                                           'pair_key':'XXDGZEUR','prezzo_eur':100.0}}
        self.dump()
        self.assertEqual(float(self.pack()['patrimonio']['posizioni'][0]['valore_eur']),200)

    def test_rt4_pair01_opacity_duplicate_key_cross_asset_detectable(self):
        self.fin_rt01_btc()
        self.snapshot['markets']['BTC']['token']='BTC'
        self.snapshot['markets']['BTC']['pair_key']='XETHZEUR'
        self.snapshot['markets']['ETH']={'token':'ETH','pair':'ETH/EUR',
                                         'pair_key':'XETHZEUR','prezzo_eur':100.0}
        self.dump()
        with self.assertRaisesRegex(p.PacketError,'Kraken|Identita'):
            self.pack()

if __name__=='__main__': unittest.main(verbosity=2)
