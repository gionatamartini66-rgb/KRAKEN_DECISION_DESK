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
                       "markets":{"ADA":{"pair":"ADA/EUR", "pair_key":"ADAEUR"},
                                  "ETH":{"pair":"ETH/EUR", "pair_key":"XETHZEUR"}},
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


if __name__=='__main__': unittest.main(verbosity=2)
