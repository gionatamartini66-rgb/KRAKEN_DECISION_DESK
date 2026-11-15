"""G2 checks of dynamic project/primary-source/consumer paths. Synthetic, offline."""
import copy
import datetime as dt
import json
import unittest
from unittest import mock
import kdd_economics as economic
import kdd_economic_sources as sources

UTC = dt.timezone.utc
T = dt.datetime(2026,11,15,10,0,tzinfo=UTC)


class PrimaryFollowupTests(unittest.TestCase):
    def identity(self, token):
        pair=token+"/EUR"
        key=token+"EUR"
        return economic.identify(token,pair,key,catalog={key:{
            "pair_key":key,"pair":pair,"base":token,"quote":"EUR"}})

    def row(self, token, observed=T, circ=100):
        ident=self.identity(token)
        return {"indice":0,"token":token,"identita":ident,
                "fondamentali":{"stato":"VERIFICATO","origine":"ACQUISIZIONE_PUBBLICA",
                    "fonte":economic.CG+ident["coingecko_id"],
                    "rilevato_utc":observed.isoformat(),
                    "offerta_circolante":circ,"offerta_totale":200,
                    "offerta_massima":300},
                "evento":economic.release_event(ident,None,observed,observed)}

    def items(self, tokens=("BTC","ETH","SOL","NEAR"), extra=None, observed=T, circ=100):
        rows=[self.row(t,observed,circ) for t in tokens]
        for n,row in enumerate(rows):row["indice"]=n
        candidates=[] if extra is None else [extra]
        return {"posizioni":rows,"candidati":candidates}

    def fetch(self, url):
        if url.startswith(sources.ECB):
            if "/EXR/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "EXR.D.USD.EUR.SP00.A,2026-11-13,1.08\n"
                        "EXR.D.USD.EUR.SP00.A,2026-11-14,1.09\n").encode()
            if "/HICP/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "HICP.M.U2.N.000000.4D0.ANR,2026-10,2.3\n").encode()
            if "/FM/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "FM.D.U2.EUR.4F.KR.DFR.LEV,2026-11-14,2.5\n").encode()
            raise AssertionError("unexpected macro series")
        if "/pulls?" in url:
            repo=url.split("/repos/")[1].split("/pulls?")[0]
            return json.dumps([{
                "number":701,"title":"Protocol documentation proposal",
                "html_url":"https://github.com/"+repo+"/pull/701",
                "base":{"repo":{"full_name":repo}},
                "created_at":"2026-11-12T09:00:00+00:00",
                "updated_at":"2026-11-14T09:00:00+00:00",
                "merged_at":None,
            }]).encode()
        if url.startswith("https://raw.githubusercontent.com/"):
            return json.dumps({
                "schema":sources.ECON_SCHEDULE_SCHEMA,
                "progetto_id":"bitcoin","pubblicato_utc":"2026-11-12T08:00:00+00:00",
                "unita":"TOKEN","eventi":[{
                    "tipo":"UNLOCK_PROGRAMMATO","evento_utc":"2026-12-01T12:00:00+00:00",
                    "quantita_token":100,"allocazione":"example"}]}).encode()
        raise AssertionError("source URL not registered: "+url)

    def test_two_refreshes_rotate_and_preserve_historical_supply(self):
        records=[]
        def fetch(url):
            records.append(url)
            return self.fetch(url)
        a=sources.collect(T,self.items(),{},fetch)
        b=sources.collect(T+dt.timedelta(hours=1),self.items(
            observed=T+dt.timedelta(hours=1),circ=112),a,fetch)
        self.assertEqual(a["schema"],sources.SCHEMA)
        self.assertEqual(a["richieste_pubbliche"],3)
        self.assertEqual(b["richieste_pubbliche"],3)
        self.assertEqual(len(a["progetti"]),4)
        self.assertEqual(len(b["progetti"]),4)
        self.assertEqual({x["progetto_id"] for x in a["progetti"] if x["stato"]=="OSSERVATO"},
                         {"bitcoin","ethereum"})
        self.assertEqual({x["progetto_id"] for x in b["progetti"] if x["stato"]=="OSSERVATO"},
                         {"solana","bitcoin"})
        self.assertEqual({x["progetto_id"] for x in b["progetti"] if x["stato"]=="STORICO_NON_AGGIORNATO"},
                         {"ethereum"})
        self.assertEqual(a["indicatori_macro"][0]["id"],"USD_EUR")
        self.assertEqual(b["indicatori_macro"][1]["id"],"EA_HICP")
        self.assertEqual(len(b["storico_supply"]),8)
        self.assertEqual(len(b["variazioni_supply"]),4)
        for x in b["variazioni_supply"]:
            self.assertEqual(x["variazioni"]["offerta_circolante"],12)
            self.assertIn("non provano unlock",x["limite"])
        self.assertFalse(any(x["stato"]=="DOCUMENTO_PRIMARIO_CON_SCHEDULE" for x in b["calendari"]))
        self.assertEqual(len(records),6)

    def test_stale_read_without_new_fetch_and_no_false_sale(self):
        a=sources.collect(T,self.items(),{},self.fetch)
        current=sources.at_read(a,self.items(),T)
        self.assertEqual(current["copertura"]["progetti"],4)
        self.assertEqual(current["copertura"]["governance_osservati"],2)
        self.assertEqual(current["copertura"]["indicatori_macro_osservati"],1)
        self.assertTrue(all(e["stato_decisione_rete"]=="NON_ATTESTATO"
                       for p in current["progetti"] for e in p["eventi"]))
        stale=sources.at_read(a,self.items(),T+dt.timedelta(days=10))
        self.assertEqual(stale["copertura"]["governance_osservati"],0)
        self.assertEqual(stale["copertura"]["indicatori_macro_osservati"],0)

    def test_wrong_project_news_or_macro_source_rejected(self):
        a=sources.collect(T,self.items(),{},self.fetch)
        forged=copy.deepcopy(a)
        forged["progetti"][0]["repository_governance"]="attacker/bips"
        with self.assertRaises(ValueError):
            sources.at_read(forged,self.items(),T)
        forged=copy.deepcopy(a)
        forged["progetti"][0]["eventi"][0]["fonte"]="https://github.com/attacker/bips/pull/701"
        with self.assertRaises(ValueError):
            sources.at_read(forged,self.items(),T)
        forged=copy.deepcopy(a)
        forged["indicatori_macro"][0]["fonte"]="https://evil.example/api"
        with self.assertRaises(ValueError):
            sources.at_read(forged,self.items(),T)
        forged=copy.deepcopy(a)
        forged["richieste_pubbliche"]=100
        with self.assertRaises(ValueError):
            sources.at_read(forged,self.items(),T)

    def test_rate_limit_bad_csv_bad_github_response_no_fictitious_zero(self):
        def broken(url):
            if "data-api" in url:return b"KEY,TIME_PERIOD,OBS_VALUE\nbad,wrong,0"
            if "/pulls?" in url:return b'{"not":"a list"}'
            raise OSError("provider down")
        a=sources.collect(T,self.items(),{},broken)
        self.assertEqual(a["richieste_pubbliche"],3)
        self.assertTrue(all(p["stato"]!="OSSERVATO" for p in a["progetti"]))
        self.assertEqual(a["indicatori_macro"][0]["stato"],"FONTE_NON_DISPONIBILE")
        self.assertIsNone(a["indicatori_macro"][0]["valore"])
        b=sources.at_read(a,self.items(),T)
        self.assertEqual(b["copertura"]["governance_osservati"],0)

    def test_new_dynamic_asset_and_replaced_universe(self):
        coin={"id":"new-unseen-token","name":"Unseen Project","symbol":"UNSEEN"}
        search={"coins":[coin]}
        markets={coin["id"]:{"name":coin["name"],"tickers":[{
            "market":{"identifier":"kraken"},"base":"UNSEEN","target":"EUR",
            "is_stale":False,"is_anomaly":False}]}}
        discovered=economic.resolve_public("UNSEEN","UNSEEN/EUR",search,markets,T)
        self.assertEqual(discovered["stato"],"RISOLTO")
        catalog={"UNSEENEUR":{"pair_key":"UNSEENEUR","pair":"UNSEEN/EUR",
                               "base":"UNSEEN","quote":"EUR"}}
        identity=economic.identify("UNSEEN","UNSEEN/EUR","UNSEENEUR",
                                   catalog=catalog,discovered=discovered)
        self.assertEqual(identity["stato"],"IDENTITA_VERIFICATA_DA_CATALOGO")
        novel={"indice":0,"token":"UNSEEN","coppia_analisi":"UNSEEN/EUR",
               "identita":identity,"fondamentali":{
                   "stato":"VERIFICATO","origine":"ACQUISIZIONE_PUBBLICA",
                   "fonte":economic.CG+coin["id"],"rilevato_utc":T.isoformat(),
                   "offerta_circolante":24,"offerta_totale":100,"offerta_massima":None}}
        a=sources.collect(T,self.items(),{},self.fetch)
        replaced={"posizioni":[novel],"candidati":[self.row("BTC")]}
        replaced["candidati"][0]["indice"]=0
        b=sources.collect(T+dt.timedelta(hours=1),replaced,a,self.fetch)
        self.assertEqual(set(x["progetto_id"] for x in b["progetti"]),{"bitcoin","new-unseen-token"})
        self.assertEqual(next(x for x in b["progetti"] if x["progetto_id"]=="new-unseen-token")["stato"],
                         "SENZA_FONTE_PRIMARIA_ASSOCIATA")
        self.assertEqual(next(x for x in b["calendari"] if x["progetto_id"]=="new-unseen-token")["stato"],
                         "SENZA_CALENDARIO_PRIMARIO")
        self.assertEqual(sources.at_read(b,replaced,T+dt.timedelta(hours=1))["copertura"]["progetti"],2)

    def test_machine_readable_primary_schedule_is_planned_not_sale(self):
        existing=dict(economic._CURATED["BTC"])
        existing["official_schedule"]={"repository":"bitcoin/bips","path":"schedules/btc.json","ref":"main"}
        with mock.patch.dict(economic._CURATED,{"BTC":existing}):
            a=sources.collect(T,self.items(tokens=("BTC",)),{},self.fetch)
            self.assertEqual(a["richieste_pubbliche"],3)
            record=a["calendari"][0]
            self.assertEqual(record["stato"],"DOCUMENTO_PRIMARIO_CON_SCHEDULE")
            self.assertEqual(record["eventi"][0]["stato"],"PROGRAMMATO_NON_CIRCOLANTE")
            self.assertEqual(record["eventi"][0]["vendita"],"NON_ATTESTATA")
            checked=sources.at_read(a,self.items(tokens=("BTC",)),T)
            self.assertEqual(checked["copertura"]["calendari_primari_attuali"],1)
            def forged(url):
                if "raw.githubusercontent.com" in url:
                    return self.fetch(url).replace(b'"bitcoin"',b'"different-project"')
                return self.fetch(url)
            b=sources.collect(T,self.items(tokens=("BTC",)),{},forged)
            self.assertEqual(b["calendari"][0]["stato"],"FONTE_NON_DISPONIBILE")

    def test_existing_economic_reader_consumes_followup(self):
        items=self.items(tokens=("BTC",))
        a=sources.collect(T,items,{},self.fetch)
        observed=items["posizioni"][0]
        source={"schema":economic.VERSION,"acquisito_utc":T.isoformat(),
                "posizioni":[observed],"candidati":[],
                "fonti_economiche":economic.sources_matrix(),
                "regime":{"stato":"INDETERMINATO","qualita":"INSUFFICIENTE"},
                "macro":economic.macro([],T),"monitor_fonti":a}
        result=economic.at_read(source,[{"token":"BTC"}],[],T)
        self.assertIn("monitor_fonti",result)
        self.assertEqual(result["monitor_fonti"]["copertura"]["progetti"],1)
        with self.assertRaises(ValueError):
            economic.at_read(dict(source,monitor_fonti=dict(a,progetti=[])),[{"token":"BTC"}],[],T)


    def test_regime_cross_checks_futures_without_claiming_institutional_buying(self):
        base={"stato":"RIALZISTA","qualita":"PARZIALE",
              "mancanti":["Derivati con copertura e confronto partecipazione/volumi tra rilevazioni"],
              "famiglie_osservate":[],"contrari":[],"favorevoli":[]}
        derivatives={"open-interest":{
            "ultimo_close":110,"close_4h_fa":100,
            "ultimo_punto_utc":T.isoformat(),"ultimo_punto_provvisorio":False},
            "cvd":{"ultimo_cvd":-40,"cvd_4h_fa":-10,
                   "ultimo_punto_utc":T.isoformat(),"ultimo_punto_provvisorio":False}}
        primary={"indicatori_macro":[{"id":"USD_EUR","stato":"OSSERVATO",
                                     "fonte":"https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
                                     "periodo":"2026-11-14","unita":"USD per EUR","valore":1.09}]}
        r=economic.regime_participation(base,derivatives,primary,T)
        self.assertEqual(r["stato"],"RIALZISTA")
        self.assertEqual(r["qualita"],"PARZIALE_CON_CONTRADDIZIONI")
        self.assertEqual(len(r["contrari"]),1)
        self.assertEqual(len(r["famiglie_osservate"]),2)
        self.assertIn("non identifica",r["famiglie_osservate"][0]["limite"])
        later=economic.regime_participation(base,derivatives,primary,T+dt.timedelta(hours=6))
        self.assertIn("OI e CVD", " ".join(later["mancanti"]))
        self.assertNotEqual(later["qualita"],"PARZIALE_CON_CONTRADDIZIONI")



if __name__=="__main__":
    unittest.main()
