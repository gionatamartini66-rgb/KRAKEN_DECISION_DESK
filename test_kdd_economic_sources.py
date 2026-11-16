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
        if "/issues?" in url:
            repo=url.split("/repos/")[1].split("/issues?")[0]
            return json.dumps([{"number":8234,"title":"Project issue about upgrade",
                "html_url":"https://github.com/"+repo+"/issues/8234",
                "created_at":"2026-11-12T00:00:00+00:00",
                "updated_at":"2026-11-13T00:00:00+00:00",
                "labels":[{"name":"upgrade"}]}]).encode()
        if "/security-advisories?" in url:
            name=url.split("/repos/")[1].split("/security-advisories?")[0]
            return json.dumps([{"ghsa_id":"GHSA-abcd-efgh-ijkl",
                "html_url":"https://github.com/"+name+"/security/advisories/GHSA-abcd-efgh-ijkl",
                "state":"published","summary":"Repository advisory",
                "published_at":"2026-11-12T00:00:00+00:00","withdrawn_at":None}]).encode()
        if url.startswith(sources.ECB):
            if "/EXR/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "EXR.D.USD.EUR.SP00.A,2026-11-13,1.08\n"
                        "EXR.D.USD.EUR.SP00.A,2026-11-14,1.09\n").encode()
            if "/HICP/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "HICP.M.U2.N.000000.4D0.ANR,2026-10,2.3\n").encode()
            if "/FM/" in url:
                code=("FM.D.U2.EUR.4F.KR.MRR_FR.LEV" if "MRR_FR.LEV" in url
                      else "FM.D.U2.EUR.4F.KR.DFR.LEV")
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        +code+",2026-11-14,2.5\n").encode()
            if "/BSI/" in url:
                return ("KEY,TIME_PERIOD,OBS_VALUE\n"
                        "BSI.M.U2.Y.V.M30.X.I.U2.2300.Z01.A,2026-10,3.1\n").encode()
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

    def test_out_of_real_refresh_has_no_primary_api_and_no_false_rate_limit(self):
        import dossier_trade as dossier
        self.assertFalse(dossier._PRIMARY_REAL_REFRESH.get())
        with dossier.primary_refresh_context():
            self.assertTrue(dossier._PRIMARY_REAL_REFRESH.get())
        self.assertFalse(dossier._PRIMARY_REAL_REFRESH.get())
        items=self.items(tokens=("BTC","SOL","SUI"))
        def forbidden(url):
            raise AssertionError("Unscheduled URL: "+url)
        def rpc_forbidden(url,payload):
            raise AssertionError("Unscheduled JSON RPC")
        result=sources.collect(T,items,{},forbidden,network_allowed=False,
                skipped_reason="FUORI_REFRESH",rpc_fetch=rpc_forbidden,
                collect_project_issues=True)
        self.assertEqual(result["richieste_pubbliche"],0)
        self.assertEqual(result["progetti"][0]["stato"],"NON_ACQUISITO_FUORI_REFRESH")
        self.assertEqual(result["indicatori_macro"][0]["motivo"],"NON_ACQUISITO_FUORI_REFRESH")
        self.assertEqual(result["segnalazioni_repo"][0]["stato"],"NON_ACQUISITO_FUORI_REFRESH")
        self.assertEqual(result["politiche_emissioni"][1]["stato"],"NON_ACQUISITO_FUORI_REFRESH")
        sources.at_read(result,items,T)

    def test_restricted_kraken_pair_remains_visible_without_revalidating_project(self):
        import dossier_trade as producer
        from unittest import mock
        ident=self.identity("SOL")
        self.assertEqual(ident["stato"],"IDENTITA_VERIFICATA_DA_CATALOGO")
        previous={"schema":economic.VERSION,
                  "acquisito_utc":(T-dt.timedelta(hours=1)).isoformat(),
                  "posizioni":[{"indice":0,"token":"SOL","identita":ident}],
                  "candidati":[]}
        # Today's four-timeframe row has lost the online pair. The *same*
        # AssetPairs response still carries that REST key and restricted mode.
        pairs={"SOLEUR":{"wsname":"SOL/EUR","status":"cancel_only"}}
        with mock.patch.object(producer.desk,"request",side_effect=OSError("offline")), \
             mock.patch.object(producer.time,"sleep"):
            actual=producer.economic_evidence(
                {"feed":[]},{"posizioni":[{"token":"SOL"}]},
                {"posizioni":[{"token":"SOL","coppia":None,"pair_key":None}]},
                [],T,asset_pairs=pairs,previous=previous)
        self.assertEqual(actual["posizioni"][0]["identita"]["stato"],"NON_VERIFICATO")
        self.assertEqual(actual["posizioni"][0]["identita"]["pair_key"],"SOLEUR")
        self.assertEqual(actual["posizioni"][0]["identita"]["coppia"],"SOL/EUR")
        self.assertEqual(actual["monitor_fonti"]["stati_coppie_kraken"]
                         ["posizioni"][0]["status_kraken"],"cancel_only")
        got=economic.at_read(actual,[{"token":"SOL"}],[],T)
        review=got["posizioni"][0]["valutazione_fonti_primarie"]
        self.assertEqual(review["stato"],"SOLO_COPPIA_KRAKEN_VERIFICATA")
        self.assertIsNone(review["progetto_id"])
        self.assertEqual(len(review["fatti"]),1)
        self.assertEqual(review["fatti"][0]["dettaglio"]["status"],"cancel_only")
        self.assertFalse(any(f["tipo"]=="PARAMETRI_EMISSIONE" for f in review["fatti"]))
        self.assertEqual(economic.at_read(got,[{"token":"SOL"}],[],T)
                         ["posizioni"][0]["valutazione_fonti_primarie"],review)
        late=economic.at_read(got,[{"token":"SOL"}],[],T+dt.timedelta(hours=2))
        self.assertEqual(late["posizioni"][0]["valutazione_fonti_primarie"]
                         ["stato"],"IDENTITA_NON_VERIFICATA")
        # Different current wsname: old key MUST NOT be reused.
        different={"SOLEUR":{"wsname":"ETH/EUR","status":"cancel_only"}}
        with mock.patch.object(producer.desk,"request",side_effect=OSError("offline")), \
             mock.patch.object(producer.time,"sleep"):
            mismatched=producer.economic_evidence(
                {"feed":[]},{"posizioni":[{"token":"SOL"}]},
                {"posizioni":[{"token":"SOL","coppia":None,"pair_key":None}]},
                [],T,asset_pairs=different,previous=previous)
        self.assertIsNone(mismatched["posizioni"][0]["identita"]["pair_key"])
        # Stale prior reference, likewise never granted.
        old=dict(previous,acquisito_utc=(T-dt.timedelta(days=8)).isoformat())
        with mock.patch.object(producer.desk,"request",side_effect=OSError("offline")), \
             mock.patch.object(producer.time,"sleep"):
            stale=producer.economic_evidence(
                {"feed":[]},{"posizioni":[{"token":"SOL"}]},
                {"posizioni":[{"token":"SOL","coppia":None,"pair_key":None}]},
                [],T,asset_pairs=pairs,previous=old)
        self.assertIsNone(stale["posizioni"][0]["identita"]["pair_key"])

    def test_primary_labelled_issues_are_not_verified_network_upgrades(self):
        roster=self.items(tokens=("BTC","ETH","SOL"))
        first=sources.collect(T,roster,{},self.fetch,collect_project_issues=True)
        self.assertEqual(first["richieste_pubbliche"],5)
        self.assertEqual(first["segnalazioni_repo"][0]["stato"],"OSSERVATO")
        ev=first["segnalazioni_repo"][0]["eventi"][0]
        self.assertEqual(ev["esito_proposta"],"NON_ATTESTATO")
        self.assertIsNone(ev["evento_utc"])
        self.assertIn("non attesta",ev["limite"])
        second=sources.collect(T+dt.timedelta(hours=1),roster,first,self.fetch,
                               collect_project_issues=True)
        self.assertEqual(second["segnalazioni_repo"][0]["stato"],"STORICO")
        self.assertEqual(second["segnalazioni_repo"][1]["stato"],"OSSERVATO")
        sources.at_read(second,roster,T+dt.timedelta(hours=1))
        forged=copy.deepcopy(first)
        forged["segnalazioni_repo"][0]["eventi"][0]["esito_proposta"]="APPROVATO"
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T)
        forged=copy.deepcopy(first)
        forged["segnalazioni_repo"][0]["eventi"][0]["fonte"]="https://github.com/attacker/code/issues/8234"
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T)
        empty=sources.collect(T,roster,{},lambda url:
            b"[]" if "/issues?" in url else self.fetch(url),collect_project_issues=True)
        self.assertEqual(empty["segnalazioni_repo"][0]["stato"],"NESSUNA_ISSUE_NEL_CAMPIONE")
        no_extra=sources.collect(T,roster,{},self.fetch)
        self.assertEqual(no_extra["segnalazioni_repo"][0]["stato"],"NON_RICHIESTO")
        self.assertEqual(no_extra["richieste_pubbliche"],4)

    def test_concurrent_official_events_not_hidden_and_later_revision_changes_view(self):
        # Eight labelled issues + six proposals + five GHSA notices coexist for
        # one project. Review must retain plurality and disclose capped rows.
        roster=self.items(tokens=("BTC",))
        iteration={"n":1}
        def public(url):
            if "/security-advisories?" in url:
                repo=url.split("/repos/")[1].split("/security-advisories?")[0]
                return json.dumps([{
                    "ghsa_id":f"GHSA-abcd-efgh-{i:04d}",
                    "html_url":f"https://github.com/{repo}/security/advisories/GHSA-abcd-efgh-{i:04d}",
                    "state":"published",
                    "summary":("Updated advisory" if iteration["n"]==2 and i==0
                               else "Original security advisory"),
                    "published_at":"2026-11-12T08:00:00+00:00",
                    "withdrawn_at":("2026-11-14T09:00:00+00:00"
                                    if iteration["n"]==2 and i==0 else None)}
                    for i in range(5)]).encode()
            if "/issues?" in url:
                repo=url.split("/repos/")[1].split("/issues?")[0]
                return json.dumps([{
                    "number":8100+i,"title":f"Technical issue {i}",
                    "html_url":f"https://github.com/{repo}/issues/{8100+i}",
                    "created_at":"2026-11-12T08:00:00+00:00",
                    "updated_at":"2026-11-14T08:00:00+00:00",
                    "labels":[{"name":"upgrade"}]}
                    for i in range(8)]).encode()
            if "/pulls?" in url:
                repo=url.split("/repos/")[1].split("/pulls?")[0]
                return json.dumps([{
                    "number":700+i,"title":f"Governance proposal {i}",
                    "html_url":f"https://github.com/{repo}/pull/{700+i}",
                    "base":{"repo":{"full_name":repo}},
                    "created_at":"2026-11-12T08:00:00+00:00",
                    "updated_at":"2026-11-14T08:00:00+00:00",
                    "merged_at":None}
                    for i in range(6)]).encode()
            return self.fetch(url)
        first=sources.collect(T,roster,{},public,collect_project_issues=True)
        checked=sources.at_read(first,roster,T)
        r=sources.decision_review(checked,roster["posizioni"][0],"posizioni")
        types=[f["tipo"] for f in r["fatti"]]
        self.assertEqual(types.count("AVVISO_SICUREZZA_REPOSITORY"),5)
        self.assertEqual(types.count("ISSUE_TECNICA_ETICHETTATA"),4)
        self.assertEqual(types.count("PROPOSTA_GOVERNANCE_DOCUMENTALE"),3)
        self.assertEqual(r["non_mostrati_per_tipo"]["ISSUE_TECNICA_ETICHETTATA"],4)
        self.assertEqual(r["numero_fatti_visibili"],12)
        self.assertEqual(r["fatti_totali_nel_campione"],19)
        self.assertEqual(r["non_mostrati_per_tipo"]["PROPOSTA_GOVERNANCE_DOCUMENTALE"],3)
        self.assertGreaterEqual(len(r["ipotesi_concorrenti"]),3)
        self.assertIn("RIVEDERE",r["condizione_di_riesame"])
        iteration["n"]=2
        after=T+dt.timedelta(hours=1)
        second=sources.collect(after,roster,first,public,collect_project_issues=True)
        revised=sources.decision_review(sources.at_read(second,roster,after),
                                        roster["posizioni"][0],"posizioni")
        self.assertNotEqual(r["fatti"],revised["fatti"])
        self.assertTrue(any("ritirato" in f["fatto"] for f in revised["fatti"]))
        self.assertTrue(any(f["dettaglio"].get("titolo")=="Updated advisory"
                            for f in revised["fatti"]
                            if f["tipo"]=="AVVISO_SICUREZZA_REPOSITORY"))
        self.assertEqual(revised["non_mostrati_per_tipo"]["ISSUE_TECNICA_ETICHETTATA"],4)
        late=sources.decision_review(
            sources.at_read(second,roster,after+dt.timedelta(days=16)),
            roster["posizioni"][0],"posizioni")
        self.assertEqual(late["stato"],"NESSUNA_EVIDENZA_PRIMARIA_ATTUALE")
        self.assertEqual(late["fatti"],[])

    def test_repositories_rotate_security_advisories_without_claiming_token_compromise(self):
        roster=self.items(tokens=("BTC","ETH","SOL"))
        first=sources.collect(T,roster,{},self.fetch)
        one=[x for x in first["avvisi_repository"] if x["stato"]=="OSSERVATO"]
        self.assertEqual(len(one),1)
        self.assertEqual(one[0]["progetto_id"],"bitcoin")
        self.assertEqual(one[0]["avvisi"][0]["impatto_sul_token"],"NON_ATTESTATO")
        second=sources.collect(T+dt.timedelta(hours=1),roster,first,self.fetch)
        self.assertEqual(second["avvisi_repository"][0]["stato"],"STORICO")
        self.assertEqual(second["avvisi_repository"][1]["stato"],"OSSERVATO")
        sources.at_read(second,roster,T+dt.timedelta(hours=1))
        forged=copy.deepcopy(first)
        forged["avvisi_repository"][0]["avvisi"][0]["fonte"]="https://attacker.example/advisory"
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T)
        inflated=copy.deepcopy(first)
        inflated["avvisi_repository"][0]["avvisi"][0]["impatto_sul_token"]="COMPROMESSO"
        with self.assertRaises(ValueError):
            sources.at_read(inflated,roster,T)
        empty=sources.collect(T,roster,{},lambda url:
            b"[]" if "/security-advisories?" in url else self.fetch(url))
        self.assertEqual(empty["avvisi_repository"][0]["stato"],"NESSUN_AVVISO_NEL_CAMPIONE")

    def test_two_refreshes_rotate_and_preserve_historical_supply(self):
        records=[]
        def fetch(url):
            records.append(url)
            return self.fetch(url)
        a=sources.collect(T,self.items(),{},fetch)
        b=sources.collect(T+dt.timedelta(hours=1),self.items(
            observed=T+dt.timedelta(hours=1),circ=112),a,fetch)
        self.assertEqual(a["schema"],sources.SCHEMA)
        self.assertEqual(a["richieste_pubbliche"],4)
        self.assertEqual(b["richieste_pubbliche"],4)
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
        self.assertEqual(b["indicatori_macro"][2]["stato"],"RINVIATO_BUDGET")
        reread=sources.at_read(b,self.items(observed=T+dt.timedelta(hours=1),circ=112),T+dt.timedelta(hours=1))
        self.assertEqual(next(p for p in reread["progetti"] if p["progetto_id"]=="ethereum")["stato"],
                         "STORICO_NON_AGGIORNATO")
        self.assertEqual(reread["indicatori_macro"][0]["stato"],"STORICO_NON_AGGIORNATO")
        self.assertEqual(len(b["storico_supply"]),8)
        self.assertGreaterEqual(len(b["storico_eventi"]),3)
        self.assertEqual(len(b["variazioni_supply"]),4)
        for x in b["variazioni_supply"]:
            self.assertEqual(x["variazioni"]["offerta_circolante"],12)
            self.assertIn("non provano unlock",x["limite"])
        self.assertFalse(any(x["stato"]=="DOCUMENTO_PRIMARIO_CON_SCHEDULE" for x in b["calendari"]))
        self.assertEqual(len(records),8)

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
        forged["storico_eventi"][0]["fonte"]="https://github.com/attacker/changed/pull/701"
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
        self.assertEqual(a["richieste_pubbliche"],4)
        self.assertTrue(all(p["stato"]!="OSSERVATO" for p in a["progetti"]))
        self.assertEqual(a["indicatori_macro"][0]["stato"],"FONTE_NON_DISPONIBILE")
        self.assertIsNone(a["indicatori_macro"][0]["valore"])
        b=sources.at_read(a,self.items(),T)
        self.assertEqual(b["copertura"]["governance_osservati"],0)

    def test_explicit_local_cli_request_preserves_config_and_does_not_call_kraken(self):
        import decision_desk as desk
        conf={"scanner":{"volume_24h_min_eur":400000},
              "analisi_asset_richiesti":[
                  {"token":"ARB","richiesto_utc":T.isoformat(),
                   "origine":"CLI_ESPLICITO_LOCALE"},
                  {"token":"SOL","richiesto_utc":T.isoformat(),
                   "origine":"CLI_ESPLICITO_LOCALE"}]}
        def keep(name,record):
            self.assertEqual(name,"config.json")
            self.assertIs(record,conf)
        with mock.patch.object(desk,"load",return_value=conf), \
             mock.patch.object(desk,"save",side_effect=keep) as saved, \
             mock.patch.object(desk,"NOW",return_value=T), \
             mock.patch.object(desk,"kraken",side_effect=AssertionError("Private Kraken API invoked")), \
             mock.patch.object(desk,"request",side_effect=AssertionError("Public network invoked")):
            desk.request_public_asset(type("Args",(),{"token":"PEPE"})())
            self.assertEqual([x["token"] for x in conf["analisi_asset_richiesti"]],
                             ["ARB","SOL","PEPE"])
            self.assertEqual(conf["scanner"]["volume_24h_min_eur"],400000)
            self.assertEqual(conf["analisi_asset_richiesti"][-1]["origine"],
                             "CLI_ESPLICITO_LOCALE")
            desk.request_public_asset(type("Args",(),{"token":"PEPE"})())
            self.assertEqual([x["token"] for x in conf["analisi_asset_richiesti"]],
                             ["ARB","SOL","PEPE"])
            desk.request_public_asset(type("Args",(),{"token":"ETH"})())
            self.assertEqual([x["token"] for x in conf["analisi_asset_richiesti"]],
                             ["SOL","PEPE","ETH"])
            self.assertEqual(saved.call_count,3)
            with self.assertRaises(ValueError):
                desk.request_public_asset(type("Args",(),{"token":"NOT VALID!"})())
            self.assertEqual(saved.call_count,3)

    def test_requested_pepe_outside_wallet_scanner_is_a_third_verified_group(self):
        import dossier_trade as producer
        from unittest import mock
        record={"token":"PEPE","richiesto_utc":T.isoformat(),
                "origine":"CLI_ESPLICITO_LOCALE"}
        pairs={"PEPEEUR":{"wsname":"PEPE/EUR","status":"online"}}
        def forbidden(url, timeout=12):
            raise OSError("provider offline for this test")
        with mock.patch.object(producer.desk,"request",side_effect=forbidden), \
             mock.patch.object(producer.time,"sleep"):
            result=producer.economic_evidence({"feed":[]},
                {"posizioni":[]},{"posizioni":[]},[],T,asset_pairs=pairs,
                requested=[record])
        self.assertEqual(result["posizioni"],[])
        self.assertEqual(result["candidati"],[])
        self.assertEqual(len(result["richiesti"]),1)
        self.assertEqual(result["richiesti"][0]["token"],"PEPE")
        self.assertEqual(result["richiesti"][0]["identita"]["coingecko_id"],"pepe")
        expected=[{"token":"PEPE","coppia_analisi":"PEPE/EUR",
                   "richiesto_utc":T.isoformat(),"origine":"CLI_ESPLICITO_LOCALE"}]
        got=economic.at_read(result,[],[],T,requested=expected)
        self.assertEqual(got["richiesti"][0]["valutazione_fonti_primarie"]["progetto_id"],"pepe")
        self.assertEqual(next(x for x in got["monitor_fonti"]["calendari"]
                              if x["progetto_id"]=="pepe")["stato"],"SENZA_CALENDARIO_PRIMARIO")
        self.assertEqual(got["richiesti"][0]["stato_richiesta"],"RICHIESTA_ATTIVA")
        expired=economic.at_read(got,[],[],T+dt.timedelta(days=8),requested=expected)
        self.assertEqual(expired["richiesti"][0]["stato_richiesta"],
                         "RICHIESTA_SCADUTA_DA_RINNOVARE")
        forged=copy.deepcopy(result)
        forged["richiesti"][0]["token"]="BTC"
        with self.assertRaises(ValueError):
            economic.at_read(forged,[],[],T,requested=expected)
        # Once the request is removed at next refresh, no phantom PEPE is kept.
        with mock.patch.object(producer.desk,"request",side_effect=forbidden), \
             mock.patch.object(producer.time,"sleep"):
            removed=producer.economic_evidence({"feed":[]},
                {"posizioni":[]},{"posizioni":[]},[],T+dt.timedelta(minutes=1),
                asset_pairs=pairs,previous=result,requested=[])
        self.assertEqual(removed["richiesti"],[])
        self.assertEqual(removed["monitor_fonti"]["progetti"],[])

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

    def test_arb_real_project_primary_mdx_rule_and_missing_exact_unlocks(self):
        raw=(
            "all investor and team tokens are subject to 4 year lockups, "
            "with the first unlocks happening one year after the "
            "[token generation event (3/16/2023)](https://arbiscan.io/tx/example) "
            "and then monthly unlocks for the remaining three years. "
            "The Arbitrum Foundation's allocation is subject to a lockup "
            "that began on 4/17/2023 and linearly unlocks over the course "
            "of four years.")
        def firstparty(url):
            if url==sources.ARB_VESTING_URL: return raw.encode()
            return self.fetch(url)
        item=self.items(tokens=("ARB","SUI","PEPE"))
        first=sources.collect(T,item,{},firstparty)
        self.assertEqual(first["richieste_pubbliche"],2)
        arb=next(x for x in first["calendari"] if x["progetto_id"]=="arbitrum")
        self.assertEqual(arb["stato"],"DOCUMENTO_PRIMARIO_REGOLA_VESTING")
        self.assertEqual(arb["eventi"],[])
        self.assertEqual(arb["regole"][0]["quantita_token"],None)
        self.assertEqual(arb["periodi_mensili_derivati"][0],"2026-11")
        checked=sources.at_read(first,item,T)
        self.assertEqual(checked["copertura"]["regole_vesting_primarie_attuali"],1)
        review=sources.decision_review(checked,item["posizioni"][0],"posizioni")
        self.assertTrue(any(x["tipo"]=="REGOLA_VESTING_MENSILE_PRIMARIA"
                            for x in review["fatti"]))
        self.assertFalse(any("UNLOCK_SOLO_PROGRAMMATO"==x["tipo"] for x in review["fatti"]))
        later=sources.at_read(first,item,T+dt.timedelta(days=31))
        self.assertEqual(next(x for x in later["calendari"] if x["progetto_id"]=="arbitrum")
                         ["stato"],"REGOLA_VESTING_STORICA")
        forged=copy.deepcopy(first)
        event=next(x for x in forged["calendari"] if x["progetto_id"]=="arbitrum")
        event["eventi"]=[{"tipo":"UNLOCK_PROGRAMMATO","evento_utc":"2026-12-16T00:00:00Z",
                         "quantita_token":1,"allocazione":"team"}]
        with self.assertRaises(ValueError):sources.at_read(forged,item,T)
        forged=copy.deepcopy(first)
        next(x for x in forged["calendari"] if x["progetto_id"]=="arbitrum")[
            "regole"][0]["quantita_token"]=123000
        with self.assertRaises(ValueError):sources.at_read(forged,item,T)
        missing=sources.collect(T,item,{},lambda url:
                b"not an official source" if url==sources.ARB_VESTING_URL else self.fetch(url))
        self.assertEqual(next(x for x in missing["calendari"] if x["progetto_id"]=="arbitrum")
                         ["stato"],"FONTE_NON_DISPONIBILE")
        absent=next(x for x in first["calendari"] if x["progetto_id"]=="pepe")
        self.assertEqual(absent["stato"],"SENZA_CALENDARIO_PRIMARIO")


    def test_real_strk_primary_document_reports_maximum_quantified_dated_not_executed(self):
        doc=(
          "To align long-term incentives of the Investors and Early Contributors, "
          "all tokens allocated to Investors and Early Contributors is subject to the lock-up schedule. "
          "- Up to 0.64% (64 million tokens) have been unlocked on the 15th of each month, "
          "starting April 15, 2024, and going through March 15, 2025, "
          "for a total of 7.68% (768 million tokens) unlocked by March 15, 2025. "
          "- Up to 1.27% (127 million tokens) have been and will be unlocked "
          "on the 15th of each month, starting April 15, 2025, "
          "and going through March 15, 2027, for a total of 30.48% (3.048 billion tokens).")
        def firstparty(url):
            if url==sources.STRK_URL: return doc.encode()
            return self.fetch(url)
        roster=self.items(tokens=("BTC","STRK","SUI"))
        first=sources.collect(T,roster,{},firstparty)
        # One schedule GET per refresh; use normal source rotation.
        result=first
        for i in range(1,3):
            result=sources.collect(T+dt.timedelta(hours=i),roster,result,firstparty)
        strk=next(x for x in result["calendari"] if x["progetto_id"]=="starknet")
        self.assertEqual(strk["stato"],"DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI")
        self.assertEqual(strk["eventi"][0]["data_prevista"],"2026-11-15")
        self.assertEqual(strk["eventi"][1]["data_prevista"],"2026-12-15")
        self.assertEqual(strk["eventi"][0]["quantita_massima_token"],127000000)
        self.assertEqual(strk["eventi"][0]["realizzato"],"NON_ATTESTATO")
        self.assertEqual(strk["eventi"][0]["ora_evento"],"NON_ATTESTATA")
        checked=sources.at_read(result,roster,T+dt.timedelta(hours=2))
        self.assertEqual(checked["copertura"]["calendari_con_massimi_datati_primari"],1)
        review=sources.decision_review(checked,roster["posizioni"][1],"posizioni")
        self.assertEqual(review["fatti"][0]["tipo"],"UNLOCK_MASSIMO_DATATO_PRIMARIO")
        forged=copy.deepcopy(result)
        next(x for x in forged["calendari"] if x["progetto_id"]=="starknet")[
            "eventi"][0]["quantita_massima_token"]=128000000
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T+dt.timedelta(hours=2))
        forged=copy.deepcopy(result)
        next(x for x in forged["calendari"] if x["progetto_id"]=="starknet")[
            "eventi"][0]["realizzato"]="SI"
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T+dt.timedelta(hours=2))
        missing=sources.collect(T,roster,{},lambda url:
            b"outside project source" if url==sources.STRK_URL else self.fetch(url))
        # Without any valid STRK official page no calendar may be fabricated.
        self.assertNotEqual(next(x for x in missing["calendari"]
                                 if x["progetto_id"]=="starknet")["stato"],
                            "DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI")

    def test_machine_readable_primary_schedule_is_planned_not_sale(self):
        existing=dict(economic._CURATED["BTC"])
        existing["official_schedule"]={"repository":"bitcoin/bips","path":"schedules/btc.json","ref":"main"}
        with mock.patch.dict(economic._CURATED,{"BTC":existing}):
            a=sources.collect(T,self.items(tokens=("BTC",)),{},self.fetch)
            self.assertEqual(a["richieste_pubbliche"],4)
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

    def test_sui_primary_monthly_forecast_is_not_unlock_and_detects_revisions(self):
        sample=[
            {"year":2026,"month":10,"circulatingSupplyValue":4100000000,
             "circulatingSupplyPercentage":.41},
            {"year":2026,"month":11,"circulatingSupplyValue":4139000000,
             "circulatingSupplyPercentage":.4139},
            {"year":2026,"month":12,"circulatingSupplyValue":4159000000,
             "circulatingSupplyPercentage":.4159},
            {"year":2027,"month":1,"circulatingSupplyValue":4200000000,
             "circulatingSupplyPercentage":.42}]
        roster=self.items(tokens=("SUI",))
        seen=[]
        def fetch(url):
            seen.append(url)
            if url==sources.SUI_CIRCULATION:
                return json.dumps(sample).encode()
            return self.fetch(url)
        first=sources.collect(T,roster,{},fetch)
        self.assertEqual(first["richieste_pubbliche"],2)
        self.assertIn(sources.SUI_CIRCULATION,seen)
        row=first["calendari"][0]
        self.assertEqual(row["stato"],"PROIEZIONE_PRIMARIA_NON_UNLOCK")
        self.assertEqual(row["mese_circolazione"],"2026-11")
        self.assertEqual(row["circolante_mese_token"],4139000000)
        self.assertEqual(row["stime_mensili"][0]["aumento_previsto_token"],20000000)
        self.assertEqual(row["eventi"],[])
        self.assertIsNone(row["pubblicato_utc"])
        self.assertEqual(row["stato_vesting"],"NON_VERIFICATO")
        self.assertEqual(row["stato_vendita"],"NON_ATTESTATA")
        checked=sources.at_read(first,roster,T)
        self.assertEqual(checked["calendari"][0]["stato"],"PROIEZIONE_PRIMARIA_NON_UNLOCK")
        self.assertEqual(sources.at_read(first,roster,T+dt.timedelta(days=36))
                         ["calendari"][0]["stato"],"PROIEZIONE_STORICA")
        tampered=copy.deepcopy(first)
        tampered["calendari"][0]["stime_mensili"][0]["data_sblocco_utc"]="2026-12-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"forged"):
            sources.at_read(tampered,roster,T)
        tampered=copy.deepcopy(first)
        tampered["calendari"][0]["fonte"]="https://attacker.example/api"
        with self.assertRaises(ValueError):
            sources.at_read(tampered,roster,T)
        changed=copy.deepcopy(sample)
        changed[-1]["circulatingSupplyValue"]=4210000000
        changed[-1]["circulatingSupplyPercentage"]=.421
        def fetch_changed(url):
            if url==sources.SUI_CIRCULATION:
                return json.dumps(changed).encode()
            return self.fetch(url)
        second=sources.collect(T+dt.timedelta(hours=1),roster,first,fetch_changed)
        self.assertEqual(len(second["revisioni_piani"]),1)
        self.assertEqual(second["revisioni_piani"][0]["stato"],"REVISIONE_PIANO_PUBBLICATO")
        # A primary API with inconsistent supply/cap may not create events.
        broken=copy.deepcopy(sample)
        broken[2]["circulatingSupplyPercentage"]=.9
        bad=sources.collect(T,roster,{},lambda url:
            json.dumps(broken).encode() if url==sources.SUI_CIRCULATION else self.fetch(url))
        self.assertEqual(bad["calendari"][0]["stato"],"FONTE_NON_DISPONIBILE")
        self.assertEqual(bad["calendari"][0]["eventi"],[])

    def test_kraken_spot_pair_status_reused_without_extra_api_and_no_fake_delisting(self):
        items=self.items(tokens=("BTC","SOL"))
        pairs={"BTCEUR":{"wsname":"BTC/EUR","status":"online"},
               "SOLEUR":{"wsname":"SOL/EUR","status":"cancel_only"}}
        first=sources.collect(T,items,{},self.fetch,asset_pairs=pairs)
        states=first["stati_coppie_kraken"]["posizioni"]
        self.assertEqual([p["status_kraken"] for p in states],["online","cancel_only"])
        self.assertEqual(first["richieste_pubbliche"],4)
        self.assertEqual(sources.at_read(first,items,T)
                         ["stati_coppie_kraken"]["posizioni"][1]["stato_alla_lettura"],"OSSERVATO")
        pairs2=copy.deepcopy(pairs)
        pairs2["SOLEUR"]["status"]="post_only"
        second=sources.collect(T+dt.timedelta(minutes=10),items,first,self.fetch,asset_pairs=pairs2)
        changed=second["stati_coppie_kraken"]["posizioni"][1]["cambiamento"]
        self.assertEqual((changed["prima"],changed["dopo"]),("cancel_only","post_only"))
        self.assertIn("non attestati",changed["limite"])
        self.assertEqual(sources.at_read(second,items,T+dt.timedelta(hours=2))
                         ["stati_coppie_kraken"]["posizioni"][1]["stato_alla_lettura"],"SCADUTO")
        third=sources.collect(T+dt.timedelta(minutes=10),items,first,self.fetch,
                              asset_pairs={"BTCEUR":pairs["BTCEUR"]})
        self.assertEqual(third["stati_coppie_kraken"]["posizioni"][1]["stato"],
                         "COPPIA_NON_PRESENTE_NELLA_RISPOSTA")
        self.assertIsNone(third["stati_coppie_kraken"]["posizioni"][1]["cambiamento"])
        tampered=copy.deepcopy(first)
        tampered["stati_coppie_kraken"]["posizioni"][1]["coppia"]="SOL/USDT"
        with self.assertRaises(ValueError):
            sources.at_read(tampered,items,T)
        # A forged listing/delisting label cannot pass as a Kraken trading mode.
        fake=copy.deepcopy(first)
        fake["stati_coppie_kraken"]["posizioni"][1]["status_kraken"]="delisted"
        with self.assertRaises(ValueError):
            sources.at_read(fake,items,T)
        fabricated=sources.collect(T,items,{},self.fetch,
                        asset_pairs={"BTCEUR":pairs["BTCEUR"],
                                     "SOLEUR":{"wsname":"SOL/EUR","status":"delisted"}})
        self.assertEqual(fabricated["stati_coppie_kraken"]["posizioni"][1]
                         ["stato"],"STATUS_NON_CONFORME")

    def test_current_solana_primary_inflation_governor_and_forged_unlock_rejected(self):
        roster=self.items(tokens=("SOL",))
        calls=[]
        def rpc(url,params):
            calls.append((url,params))
            return {"jsonrpc":"2.0","id":1,"result":{
                "initial":.08,"taper":.15,"terminal":.015,"foundation":.05,
                "foundationTerm":7}}
        first=sources.collect(T,roster,{},self.fetch,rpc_fetch=rpc)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],sources.SOLANA_RPC)
        self.assertEqual(calls[0][1]["method"],"getInflationGovernor")
        policy=first["politiche_emissioni"][0]
        self.assertEqual(policy["stato"],"OSSERVATO")
        self.assertEqual(policy["valori"]["initial"],.08)
        self.assertEqual(policy["stato_unlock"],"NON_ATTESTATO")
        self.assertEqual(policy["vendita"],"NON_ATTESTATA")
        self.assertEqual(sources.at_read(first,roster,T)["copertura"]["politiche_emissioni_osservate"],1)
        late=sources.at_read(first,roster,T+dt.timedelta(days=15))
        self.assertEqual(late["politiche_emissioni"][0]["stato_alla_lettura"],"SCADUTO")
        forged=copy.deepcopy(first)
        forged["politiche_emissioni"][0]["valori"]["initial"]=5.5
        with self.assertRaisesRegex(ValueError,"forged"):
            sources.at_read(forged,roster,T)
        forged=copy.deepcopy(first)
        forged["politiche_emissioni"][0]["stato_unlock"]="VERIFICATO"
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T)
        changed=sources.collect(T+dt.timedelta(hours=1),roster,first,self.fetch,
            rpc_fetch=lambda url,params:{"result":{"initial":.09,"taper":.15,
                "terminal":.015,"foundation":.05,"foundationTerm":7},"error":None})
        self.assertEqual(changed["politiche_emissioni"][0]["confronto"]["cambiati"],["initial"])
        outage=sources.collect(T,roster,{},self.fetch,
                rpc_fetch=lambda url,params:{"error":{"code":429},"result":None})
        self.assertEqual(outage["politiche_emissioni"][0]["stato"],"FONTE_NON_DISPONIBILE")
        self.assertIsNone(outage["politiche_emissioni"][0]["valori"])

    def test_official_cftc_futures_positions_are_not_spot_institutional_flows(self):
        spec=next(s for s in sources.MACRO_SERIES if s[0]=="CFTC_BTC_TFF")
        rows=[["CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE","261103",
               "2026-11-03","090741","CME ","00","090"]+["1"]*85+["FutOnly"]]
        btc=[sources.CFTC_BTC_CONTRACT,"261110","2026-11-10",
             sources.CFTC_BTC_MARKET_CODE,"CME ","00","133"]
        btc+=["17527","6027","5548","490","4379","1976","187",
              "5114","7705","427","124","308","17","16765",
              "16658","762","869"]
        btc+=["0"]*70+["(5 Bitcoins)","133741","CME ","133 ","F85","FutOnly"]
        rows.append(btc)
        import csv,io
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerows(rows)
        got=sources._cftc_btc_tff(output.getvalue(),spec,T)
        # Canonical live CFTC row shape as published 2026-11-03: 87
        # columns. Earlier synthetic 90+ columns concealed the parser bug.
        real_head=[
            sources.CFTC_BTC_CONTRACT,"261103","2026-11-03","133741",
            "CME ","00","133 ",
            "17527","6027","5548","490","4379","1976","187",
            "5114","7705","427","124","308","17","16765","16658",
            "762","869"]
        real_line=real_head+["0"]*(87-24-6)+[
             "(5 Bitcoins)","133741","CME ","133 ","F85","FutOnly"]
        self.assertEqual(len(real_line),87)
        output=io.StringIO();csv.writer(output).writerow(real_line)
        official_shape=sources._cftc_btc_tff(output.getvalue(),spec,T)
        self.assertIsNotNone(official_shape)
        self.assertEqual(official_shape["classificazioni"]["asset_manager"]
                         ["saldo_long_meno_short"],2403)
        wrong_multiplier=real_line[:]
        wrong_multiplier[-6]="(0.1 Bitcoin)"
        output=io.StringIO();csv.writer(output).writerow(wrong_multiplier)
        self.assertIsNone(sources._cftc_btc_tff(output.getvalue(),spec,T))
        self.assertEqual(got["valore"],17527)
        self.assertEqual(got["classificazioni"]["asset_manager"]["saldo_long_meno_short"],2403)
        self.assertEqual(got["classificazioni"]["leveraged_money"]["saldo_long_meno_short"],-2591)
        self.assertEqual(got["stato_pubblicazione"],"DATA_RAPPORTO_NON_DATA_PUBBLICAZIONE")
        self.assertTrue(sources._cftc_read_valid(got))
        corrupt=copy.deepcopy(got)
        corrupt["classificazioni"]["dealer"]["saldo_long_meno_short"]=10000000
        self.assertFalse(sources._cftc_read_valid(corrupt))
        # Wrong contract / Coinbase micro cannot be used as BTC CME 5-BTC.
        btc[3]="133742"
        output=io.StringIO();csv.writer(output).writerow(btc)
        self.assertIsNone(sources._cftc_btc_tff(output.getvalue(),spec,T))
        older=sources._cftc_btc_tff(rows[0][0] if False else output.getvalue(),
                                    spec,T)
        self.assertIsNone(older)

    def test_ecb_primary_rotation_includes_refinancing_and_m3_without_double_fetch(self):
        roster=self.items(tokens=("BTC",))
        prev={}
        seen=[]
        for cycle in range(5):
            now=T+dt.timedelta(hours=cycle)
            obs=sources.collect(now,roster,prev,
                lambda url:(seen.append(url),self.fetch(url))[1])
            checked=sources.at_read(obs,roster,now)
            ids=[x["id"] for x in checked["indicatori_macro"] if x["stato"]=="OSSERVATO"]
            self.assertEqual(ids,[sources.MACRO_SERIES[cycle][0]])
            prev=obs
        self.assertEqual(len({url for url in seen if url.startswith(sources.ECB)}),5)
        self.assertEqual(len([url for url in seen if url.startswith(sources.ECB)]),5)
        self.assertEqual(next(x for x in prev["indicatori_macro"]
                              if x["id"]=="EA_M3_GROWTH")["valore"],3.1)
        # Monthly period freshness must be measured from *end* of period,
        # not the first day (a false stale classification for M3 September).
        september=dict(next(x for x in prev["indicatori_macro"]
                             if x["id"]=="EA_M3_GROWTH"))
        september["periodo"]="2026-09"
        september["valore"]=3.1
        september["stato"]="OSSERVATO"
        revised=dict(prev,indicatori_macro=[
            september if x["id"]=="EA_M3_GROWTH" else x
            for x in prev["indicatori_macro"]])
        validated=sources.at_read(revised,roster,T+dt.timedelta(hours=4))
        self.assertEqual(next(x for x in validated["indicatori_macro"]
                              if x["id"]=="EA_M3_GROWTH")["stato"],"OSSERVATO")

    def test_ecb_temporal_comparison_and_regime_history_are_not_false_consensus(self):
        roster=self.items(tokens=("BTC",))
        first=sources.collect(T,roster,{},self.fetch)
        prev=first
        rounds=len(sources.MACRO_SERIES)
        for i in range(1,rounds+1):
            prev=sources.collect(T+dt.timedelta(hours=i),roster,prev,self.fetch)
        usd=next(x for x in prev["indicatori_macro"] if x["id"]=="USD_EUR")
        self.assertEqual(usd["stato"],"OSSERVATO")
        self.assertEqual(usd["delta_dalla_rilevazione_precedente"],0)
        self.assertIn("non sorpresa",usd["limite_confronto"])
        forged=copy.deepcopy(prev)
        next(x for x in forged["indicatori_macro"] if x["id"]=="USD_EUR")[
            "delta_dalla_rilevazione_precedente"]=10.5
        with self.assertRaises(ValueError):
            sources.at_read(forged,roster,T+dt.timedelta(hours=rounds))
        base={"stato":"LATERALE","qualita":"PARZIALE","favorevoli":[],"contrari":[],
              "mancanti":[],"famiglie_osservate":[]}
        before={"acquisito_utc":T.isoformat(),"stato":"TRANSIZIONE","qualita":"PARZIALE",
                "storico_regimi":[]}
        current=economic.regime_participation(
            base,{},prev,T+dt.timedelta(hours=rounds),previous=before)
        self.assertEqual(current["storico_regimi"][0]["stato"],"TRANSIZIONE")
        self.assertEqual(current["confronto_precedente"]["stato_precedente"],"TRANSIZIONE")
        row=roster["posizioni"][0]
        snapshot={"schema":economic.VERSION,"acquisito_utc":(T+dt.timedelta(hours=rounds)).isoformat(),
                  "posizioni":[row],"candidati":[],"fonti_economiche":economic.sources_matrix(),
                  "regime":current,"macro":economic.macro([],T+dt.timedelta(hours=rounds)),
                  "monitor_fonti":prev}
        economic.at_read(snapshot,[{"token":"BTC"}],[],T+dt.timedelta(hours=rounds))
        false=copy.deepcopy(snapshot)
        false["regime"]["storico_regimi"][0]["stato"]="RIALZISTA"
        with self.assertRaises(ValueError):
            economic.at_read(false,[{"token":"BTC"}],[],T+dt.timedelta(hours=rounds))
        future=copy.deepcopy(snapshot)
        future["regime"]["storico_regimi"][0]["acquisito_utc"]=(T+dt.timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):
            economic.at_read(future,[{"token":"BTC"}],[],T+dt.timedelta(hours=rounds))

    def test_ten_holdings_candidate_primary_review_double_read_and_source_swap(self):
        # Publicly named project identities; invented data, NOT the live wallet.
        tokens=("BNB","FET","JUP","NEAR","RENDER","SOL","SUI","ETH","BTC","XRP")
        candidate=self.row("KAS")
        candidate["coppia_analisi"]="KAS/EUR"
        items=self.items(tokens=tokens,extra=candidate)
        pairs={token+"EUR":{"wsname":token+"/EUR","status":"online"}
               for token in tokens+("KAS",)}
        pairs["SOLEUR"]["status"]="cancel_only"
        series=[(2026,9,4100000000),(2026,10,4130000000),
                (2026,11,4139000000),(2026,12,4150000000),
                (2027,1,4170000000),(2027,2,4190000000)]
        def public(url):
            if url==sources.SUI_CIRCULATION:
                return json.dumps([{"year":y,"month":m,"circulatingSupplyValue":q,
                    "circulatingSupplyPercentage":q/10000000000}
                    for y,m,q in series]).encode()
            return self.fetch(url)
        def solana(url,request):
            self.assertEqual(request.get("method"),"getInflationGovernor")
            return {"result":{"initial":.08,"taper":.15,"terminal":.015,
                              "foundation":0.0,"foundationTerm":0}}
        primary=sources.collect(T,items,{},public,asset_pairs=pairs,
                                rpc_fetch=solana,collect_project_issues=True)
        self.assertEqual(primary["richieste_pubbliche"],7)
        initial={"schema":economic.VERSION,"acquisito_utc":T.isoformat(),
            "posizioni":items["posizioni"],"candidati":items["candidati"],
            "macro":economic.macro([],T),"fonti_economiche":economic.sources_matrix(),
            "regime":{"stato":"INDETERMINATO","qualita":"INSUFFICIENTE"},
            "monitor_fonti":primary}
        position_targets=[{"token":token} for token in tokens]
        candidates=[{"token":"KAS","coppia_analisi":"KAS/EUR"}]
        first=economic.at_read(initial,position_targets,candidates,T)
        self.assertEqual(len(first["posizioni"]),10)
        self.assertEqual(len(first["candidati"]),1)
        by_token={r["token"]:r["valutazione_fonti_primarie"]
                  for r in first["posizioni"]}
        self.assertEqual(by_token["SOL"]["progetto_id"],"solana")
        self.assertTrue(any(f["tipo"]=="PARAMETRI_EMISSIONE"
                            for f in by_token["SOL"]["fatti"]))
        self.assertTrue(any(f["tipo"]=="STATO_COPPIA_KRAKEN"
                            and f["dettaglio"]["status"]=="cancel_only"
                            for f in by_token["SOL"]["fatti"]))
        self.assertIn("restrizione",by_token["SOL"]["ipotesi_non_attestata"])
        self.assertTrue(any(f["tipo"]=="PROIEZIONE_CIRCOLAZIONE"
                            for f in by_token["SUI"]["fatti"]))
        self.assertFalse(any("UNLOCK_SOLO_PROGRAMMATO"==f["tipo"]
                             for f in by_token["SUI"]["fatti"]))
        self.assertEqual(first["candidati"][0]["valutazione_fonti_primarie"]["progetto_id"],
                         "kaspa")
        self.assertEqual(first["candidati"][0]["valutazione_fonti_primarie"]["stato"],
                         "COPERTURA_PRIMARIA_PARZIALE")
        self.assertEqual(first["candidati"][0]["valutazione_fonti_primarie"]["fatti"][0]
                         ["tipo"],"STATO_COPPIA_KRAKEN")
        twice=economic.at_read(first,position_targets,candidates,T)
        self.assertEqual(twice["posizioni"][5]["valutazione_fonti_primarie"],
                         first["posizioni"][5]["valutazione_fonti_primarie"])
        false=copy.deepcopy(first)
        false["posizioni"][5]["valutazione_fonti_primarie"]["fatti"][0]["fatto"] = (
            "Kraken certifica una vendita avvenuta")
        with self.assertRaisesRegex(ValueError,"alterata"):
            economic.at_read(false,position_targets,candidates,T)
        late=economic.at_read(first,position_targets,candidates,
                               T+dt.timedelta(days=36))
        self.assertEqual(late["posizioni"][6]["valutazione_fonti_primarie"]["stato"],
                         "NESSUNA_EVIDENZA_PRIMARIA_ATTUALE")
        self.assertEqual(late["posizioni"][5]["valutazione_fonti_primarie"]["stato"],
                         "NESSUNA_EVIDENZA_PRIMARIA_ATTUALE")
        self.assertEqual(len(late["candidati"]),1)
        self.assertEqual(late["candidati"][0]["valutazione_fonti_primarie"]["stato"],
                         "NESSUNA_EVIDENZA_PRIMARIA_ATTUALE")
        switched=copy.deepcopy(initial)
        next(row for row in switched["monitor_fonti"]["calendari"]
             if row["progetto_id"]=="sui")["fonte"]="https://attacker.example/sui"
        with self.assertRaises(ValueError):
            economic.at_read(switched,position_targets,candidates,T)

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



    def test_dynamic_identity_expiry_does_not_corrupt_historical_double_read(self):
        coin={"id":"unseen-market-verified","name":"Unseen","symbol":"UNSEEN"}
        discovered=economic.resolve_public(
            "UNSEEN","UNSEEN/EUR",{"coins":[coin]},
            {coin["id"]:{"name":"Unseen","tickers":[{
                "market":{"identifier":"kraken"},"base":"UNSEEN","target":"EUR",
                "is_stale":False,"is_anomaly":False}]}},T)
        catalog={"UNSEENEUR":{"pair_key":"UNSEENEUR","pair":"UNSEEN/EUR",
                              "base":"UNSEEN","quote":"EUR"}}
        identity=economic.identify("UNSEEN","UNSEEN/EUR","UNSEENEUR",
                                   catalog=catalog,discovered=discovered)
        row={"indice":0,"token":"UNSEEN","identita":identity,
             "fondamentali":economic.fundamentals(identity,None,T,T),
             "evento":economic.release_event(identity,None,T,T)}
        items={"posizioni":[row],"candidati":[]}
        primary_data=sources.collect(T,items,None,self.fetch)
        original={"schema":economic.VERSION,"acquisito_utc":T.isoformat(),
                  "posizioni":[row],"candidati":[],
                  "fonti_economiche":economic.sources_matrix(),
                  "regime":{"stato":"INDETERMINATO","qualita":"INSUFFICIENTE"},
                  "macro":economic.macro([],T),"monitor_fonti":primary_data}
        later=T+dt.timedelta(days=8)
        read1=economic.at_read(original,[{"token":"UNSEEN"}],[],later)
        self.assertEqual(read1["posizioni"][0]["identita"]["stato"],"NON_VERIFICATO")
        read2=economic.at_read(read1,[{"token":"UNSEEN"}],[],later)
        self.assertEqual(read2["monitor_fonti"]["copertura"]["progetti"],1)
        self.assertEqual(read2["monitor_fonti"]["progetti"][0]["stato"],
                         "SENZA_FONTE_PRIMARIA_ASSOCIATA")


if __name__=="__main__":
    unittest.main()
