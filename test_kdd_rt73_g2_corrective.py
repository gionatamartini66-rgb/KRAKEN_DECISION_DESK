"""RT73 G2 corrections on real packet/bridge functions, with synthetic-only wallet.

RT-FUND uses mocked public responses: it does NOT establish real network
acquisition or independent authenticity of a CoinGecko HTTP response.
"""
import copy
import datetime as dt
import json
import unittest

from scripts import test_kdd_wallet_packet_g0 as fixtures
from test_kdd_g2_economic_functional import G2FunctionalChainTests
import kdd_wallet_packet_g0 as packet
import scripts.kdd_bridge_g2 as bridge
import kdd_economic_sources as macro

T=dt.datetime(2026,11,18,8,0,tzinfo=dt.timezone.utc)


class Rt73Corrections(unittest.TestCase):
    def _original_chain(self):
        t=G2FunctionalChainTests("test_g2_primary_starknet_macro_provenance_really_reaches_gpt_bridge")
        t.setUp()
        self.addCleanup(t.doCleanups)
        source,old_packet,bundle,read=t._real_producer_to_bridge()
        return t,source,old_packet,bundle,read

    def _three_quotes_packet(self):
        f=fixtures.WalletPacketG0Tests("test_wallet_first_all_assets_even_if_quote_missing")
        f.setUp()
        self.addCleanup(f.doCleanups)
        tickers=(
            ("BTC","BTC/EUR","BTCEUR",10.0,None,None,None),
            ("ETH","ETH/USD","ETHUSD",10.0,"20","0.5","EUR/USD"),
            ("STRK","STRK/USDC","STRKUSDC",10.0,"10","1","USDC/EUR"))
        f.portfolio["posizioni"]=[
            {"token":token,"quantita":"2","disponibile_spot":"1.5","costo_medio_eur":None}
            for token,*_ in tickers]
        markets={}
        for token,pair,key,price,qprice,rate,fxsource in tickers:
            market={"token":token,"pair":pair,"pair_key":key,"prezzo_eur":price}
            if qprice is not None:
                market.update(prezzo_quote=qprice,eur_per_quote=rate,
                              conversione_fonte=fxsource)
            markets[token]=market
        f.snapshot["markets"]=markets
        f.snapshot["fx_rilevati"]={
            "USD":{"source":"EUR/USD","eur":"0.5"},
            "USDC":{"source":"USDC/EUR","eur":"1"}}
        f.snapshot["trends"]={}
        f.report["posizioni"]=[
            {"token":token,"quantita":"2","prezzo_eur":10.0,
             "valore_eur":20.0,"pl_non_realizzato_eur":None,
             "decisione":"INDETERMINATO"}
            for token,*_ in tickers]
        f.report["totale_stimato_eur"]=60.0
        f.report["totale_parziale"]=False
        f.report["stato_totale"]="COMPLETO"
        f.dossier.pop("patrimonio_4tf",None)
        f.dump()
        result=packet.build(f.root,now=fixtures.T)
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":result,
                "packet_sha256":bridge.digest(result),
                "preparato_utc":fixtures.T.isoformat()}
        context=bridge.read_context(bundle,now=fixtures.T)
        return f,result,bundle,context

    def test_rt73_cap_01_three_quotes_same_capacity_packet_bridge(self):
        f,p,b,ctx=self._three_quotes_packet()
        original=p["patrimonio"]["posizioni"]
        self.assertEqual([x["fonte_prezzo_eur"]["pair"] for x in original],
                         ["BTC/EUR","ETH/USD","STRK/USDC"])
        assert all(x["disponibile_spot"]=="1.5" for x in original)
        capacity=p["patrimonio"]["quadro_economico_per_gpt"]["disponibilita_lorda_spot"]
        rows=capacity["posizioni"]
        self.assertEqual([r["stato"] for r in rows],
                         ["CAPACITA_LORDA_INDICATIVA"]*3)
        self.assertEqual([r["capienza_lorda_indicativa_eur"] for r in rows],
                         ["15.00"]*3)
        self.assertEqual([r["quantita_disponibile_spot"] for r in rows],["1.5"]*3)
        self.assertEqual([r["valuta_quotazione_kraken"] for r in rows],
                         ["EUR","USD","USDC"])
        self.assertEqual([r["coppia_kraken"] for r in rows],
                         ["BTC/EUR","ETH/USD","STRK/USDC"])
        self.assertEqual(rows[1]["fonte_conversione_eur"],"EUR/USD")
        self.assertEqual(rows[2]["fonte_conversione_eur"],"USDC/EUR")
        self.assertTrue(all(x["fee_reali"]=="NON_VERIFICATE" for x in rows))
        self.assertEqual(p["patrimonio"]["liquidita_spot"]["EUR"]["disponibile"],"0.00")
        self.assertEqual(p["patrimonio"]["liquidita_spot"]["USDC"]["disponibile"],"18")
        self.assertNotIn("150",json.dumps(p["patrimonio"]))
        self.assertEqual(ctx["n_posizioni"],3)
        self.assertEqual([row["token"] for row in ctx["copertura"]],["BTC","ETH","STRK"])
        self.assertEqual(ctx["copertura"][1]["mercato_spot_kraken_alla_lettura"]
                         ["valuta_quotazione"],"USD")
        self.assertEqual(ctx["copertura"][2]["mercato_spot_kraken_alla_lettura"]
                         ["valuta_quotazione"],"USDC")

    def test_rt73_cap_01_absent_inconsistent_fx_and_free_balance_fail_closed(self):
        f,p,b,ctx=self._three_quotes_packet()
        positions=p["patrimonio"]["posizioni"]
        for i,changes in ((1,{"fonte_prezzo_eur":dict(
                        positions[1]["fonte_prezzo_eur"],eur_per_quote=None)}),
                          (1,{"fonte_prezzo_eur":dict(
                        positions[1]["fonte_prezzo_eur"],eur_per_quote="0.8")}),
                          (2,{"fonte_prezzo_eur":dict(
                        positions[2]["fonte_prezzo_eur"],conversione_fonte="EUR/USD")}),
                          (2,{"mercato_spot_kraken":dict(
                        positions[2]["mercato_spot_kraken"],pair_key="DIFFERENT")}),
                          (1,{"disponibile_spot":"3"}),
                          (1,{"fonte_prezzo_eur":dict(
                        positions[1]["fonte_prezzo_eur"],eur_per_quote="invalid")}),
                          (2,{"fonte_prezzo_eur":dict(
                        positions[2]["fonte_prezzo_eur"],prezzo_quote="NaN")}),
                          (1,{"fonte_prezzo_eur":dict(
                        positions[1]["fonte_prezzo_eur"],rilevazione_utc=None)})):
            with self.subTest(row=i,changes=str(changes)):
                changed=copy.deepcopy(positions)
                changed[i].update(changes)
                value=packet.disponibilita_lorda_per_gpt(changed)["posizioni"][i]
                self.assertEqual(value["stato"],"NON_VERIFICABILE")
                self.assertIsNone(value["capienza_lorda_indicativa_eur"])
        # Original FX missing: packet's preexisting builder rejects the
        # snapshot outright; no fabricated euro valuation is produced.
        f.snapshot["fx_rilevati"].pop("USD")
        f.dump()
        with self.assertRaises(packet.PacketError):
            packet.build(f.root,now=fixtures.T)
        forged=copy.deepcopy(b)
        forged["packet"]["patrimonio"]["posizioni"][1]["fonte_prezzo_eur"][
            "eur_per_quote"]="0.8"
        forged["packet_sha256"]=bridge.digest(forged["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(forged,now=fixtures.T)

    def test_rt73_fund_01_self_consistent_hash_before_packet_is_downgraded(self):
        x,source,p,b,ctx=self._original_chain()
        original=ctx["evidenze_economiche_alla_lettura"]["posizioni"][0]
        original_proof=original["fondamentali"]["prova_acquisizione"]
        self.assertEqual(original_proof["qualifica_alla_lettura"],
                         "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE")
        modified=copy.deepcopy(source)
        proof=modified["posizioni"][0]["fondamentali"]["prova_acquisizione"]
        proof["sha256_corpo_risposta"]="a"*64
        proof["id_evidenza"]="E-FUND-bitcoin-"+"a"*16
        # Attack EARLIER: dossier source will be normalized into a perfectly
        # internally-consistent packet, not just mutate an already-built
        # derived view that the bridge would correctly reject.
        x.f.dossier["evidenze_economiche"]=modified
        x.f.dump()
        pkt=x.f.pack(now=x.clock[0])
        bundle=dict(b,packet=pkt,packet_sha256=bridge.digest(pkt))
        result=bridge.read_context(bundle,now=x.clock[0])
        btc=result["evidenze_economiche_alla_lettura"]["posizioni"][0]
        supply=btc["quadro_tokenomics"]["supply"]
        judgement=btc["giudizio_economico_integrato"]["componenti"]["fondamentali"]
        self.assertEqual(supply["validita_strutturale"],"VALIDATA")
        self.assertEqual(supply["provenienza_acquisizione"],
                         "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE")
        self.assertEqual(supply["integrita_originale_alla_lettura"],
                         "NON_RICALCOLABILE_SENZA_CORPO_HTTP")
        self.assertEqual(supply["autenticita_fonte_esterna"],"NON_ATTESTATA")
        self.assertEqual(supply["riferimento_evidenza_dichiarato"],proof["id_evidenza"])
        self.assertIsNone(supply["evidence_id"])
        self.assertIsNone(supply["fonte_http_effettiva"])
        self.assertEqual(judgement["attendibilita"],
                         "DATI_VALIDATI_HTTP_DICHIARATO_NON_RIVALIDABILE")
        self.assertIsNone(judgement["evidence_id"])
        # Subsequent read cannot promote the forged datum.
        reread=bridge.read_context(bundle,now=x.clock[0]+dt.timedelta(seconds=1))
        self.assertIsNone(reread["evidenze_economiche_alla_lettura"]["posizioni"][0]
                          ["quadro_tokenomics"]["supply"]["evidence_id"])
        # The original unmodified fixture has the SAME downgraded claim;
        # no claim that the mock was a real HTTP acquisition.
        orig_view=original["quadro_tokenomics"]["supply"]
        self.assertEqual(orig_view["provenienza_acquisizione"],
                         "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE")
        self.assertIsNone(orig_view["evidence_id"])
        self.assertEqual(result["origine"],"COERENZA_INTERNA_SOLTANTO")

    def test_rt73_fund_01_malformed_or_unpaired_claim_rejected_at_bridge(self):
        x,source,p,b,ctx=self._original_chain()
        for bad in ("g"*64,None):
            packet1=copy.deepcopy(b)
            proof=packet1["packet"]["evidenze_multifonte"]["economia"]["posizioni"][0][
                "fondamentali"]["prova_acquisizione"]
            proof["sha256_corpo_risposta"]=bad
            proof["id_evidenza"]="E-FUND-bitcoin-invalid"
            packet1["packet_sha256"]=bridge.digest(packet1["packet"])
            with self.assertRaises(bridge.BridgeError):
                bridge.read_context(packet1,now=x.clock[0])

    def test_rt73_macro_01_invalid_digest_rejected_in_dossier_and_bridge(self):
        x,source,p,b,ctx=self._original_chain()
        for bad in ("NOT_SHA","A"*64,None):
            altered=copy.deepcopy(source)
            row=next(y for y in altered["monitor_fonti"]["eventi_macro_ufficiali"]
                     if y["stato"] in ("OSSERVATO","STORICO_NON_AGGIORNATO"))
            row["sha256_feed_originale"]=bad
            x.f.dossier["evidenze_economiche"]=altered
            x.f.dump()
            with self.assertRaises(packet.PacketError):
                x.f.pack(now=x.clock[0])
            forged=copy.deepcopy(b)
            frow=next(y for y in forged["packet"]["evidenze_multifonte"]["economia"][
                "monitor_fonti"]["eventi_macro_ufficiali"]
                if y["stato"] in ("OSSERVATO","STORICO_NON_AGGIORNATO"))
            frow["sha256_feed_originale"]=bad
            forged["packet_sha256"]=bridge.digest(forged["packet"])
            with self.assertRaises(bridge.BridgeError):
                bridge.read_context(forged,now=x.clock[0])

    def test_rt73_macro_01_claim_must_have_real_observation_state(self):
        x,source,p,b,ctx=self._original_chain()
        baseline=source["monitor_fonti"]["eventi_macro_ufficiali"]
        actual=next(z for z in baseline if z["stato"]=="STORICO_NON_AGGIORNATO")
        for key,value in (("stato_acquisizione",None),
                          ("stato_acquisizione","FIRMA_AUTENTICATA"),
                          ("stato","RINVIATO_BUDGET"),
                          ("acquisito_utc",None)):
            with self.subTest(key=key,value=value):
                changed=copy.deepcopy(baseline)
                target=next(z for z in changed if z["id"]==actual["id"])
                target[key]=value
                with self.assertRaises(ValueError):
                    macro._macro_release_read(changed,x.clock[0])
        # Historical bundles without *both* newer proof fields remain legible,
        # without claiming that the original HTTP bytes were retained.
        legacy=copy.deepcopy(baseline)
        for item in legacy:
            item.pop("sha256_feed_originale",None)
            item.pop("stato_acquisizione",None)
        checked=macro._macro_release_read(legacy,x.clock[0])
        self.assertTrue(all(z["integrita_feed_alla_lettura"]==
            "IMPRONTA_ORIGINALE_NON_DISPONIBILE" for z in checked))

    def test_rt73_legacy_bundle_previous_pr73_view_only_is_compatible(self):
        # Rebuild the previous PR #73's economic display on top of the same
        # reproducible public-mock producer/packet fixture. Unlike a literal
        # source upgrade, this tests the ACTUAL bridge acceptance contract.
        x,source,p,b,ctx=self._original_chain()
        original=copy.deepcopy(b)
        economic=original["packet"]["evidenze_multifonte"]["economia"]
        for fact in economic["contesto_macro_primario"]["fatti"]:
            if fact.get("classe")=="COMUNICATO_UFFICIALE":
                fact.pop("integrita_feed_alla_lettura",None)
        for feed in economic["monitor_fonti"]["eventi_macro_ufficiali"]:
            feed.pop("integrita_feed_alla_lettura",None)
        for group in ("posizioni","candidati","richiesti"):
            for row in economic.get(group,[]):
                proof=row["fondamentali"].get("prova_acquisizione") or {}
                claim=proof.get("stato","NON_ATTESTATA_DAL_PRODUTTORE")
                proof.pop("qualifica_alla_lettura",None)
                proof.pop("integrita_originale_alla_lettura",None)
                supply=row["quadro_tokenomics"]["supply"]
                for key in ("acquisizione_http_dichiarata",
                            "integrita_originale_alla_lettura",
                            "autenticita_fonte_esterna",
                            "riferimento_evidenza_dichiarato",
                            "url_http_dichiarato"):
                    supply.pop(key,None)
                supply["provenienza_acquisizione"]=claim
                supply["evidence_id"]=proof.get("id_evidenza")
                supply["fonte_http_effettiva"]=proof.get("url_richiesto")
                supply["limite_provenienza"]=(
                    "L'hash catturato dal produttore non e firma del fornitore "
                    "e non prova autenticita esterna; senza prova HTTP i valori "
                    "sono soltanto strutturalmente validi.")
                component=row["giudizio_economico_integrato"][
                    "componenti"]["fondamentali"]
                component.pop("riferimento_evidenza_dichiarato",None)
                component.pop("integrita_originale_alla_lettura",None)
                component["provenienza_acquisizione"]=claim
                component["evidence_id"]=proof.get("id_evidenza")
                if component["stato_informazione"]=="RECENTE":
                    component["attendibilita"]=(
                        "HTTP_PRODUTTORE_CON_HASH_NON_FIRMA_FORNITORE"
                        if claim=="RISPOSTA_HTTP_PASSATA_AL_PRODUTTORE"
                        else "DATO_STRUTTURALMENTE_VALIDO_HTTP_NON_ATTESTATO")
                else:
                    component["attendibilita"]="NON_ATTUALE_O_NON_VERIFICATA"
        original["packet_sha256"]=bridge.digest(original["packet"])
        now=x.clock[0]
        modern=bridge.read_context(original,now=now)
        legacy_supply=modern["evidenze_economiche_alla_lettura"][
            "posizioni"][0]["quadro_tokenomics"]["supply"]
        self.assertEqual(legacy_supply["provenienza_acquisizione"],
                         "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE")
        self.assertIsNone(legacy_supply["evidence_id"])
        again=bridge.read_context(original,now=now+dt.timedelta(seconds=2))
        self.assertIsNone(again["evidenze_economiche_alla_lettura"][
            "posizioni"][0]["quadro_tokenomics"]["supply"]["evidence_id"])
        # Compatibility only recognizes the EXACT old display computed from
        # the still-valid source, not arbitrary old-looking derived fields.
        tampered=copy.deepcopy(original)
        tampered["packet"]["evidenze_multifonte"]["economia"][
            "posizioni"][0]["quadro_tokenomics"]["supply"][
                "offerta_circolante"]="999999999"
        tampered["packet_sha256"]=bridge.digest(tampered["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(tampered,now=now)

    def test_rt73_macro_01_source_age_precision_double_read_and_no_causality(self):
        x,source,p,b,ctx=self._original_chain()
        macro_context=ctx["evidenze_economiche_alla_lettura"]["contesto_macro_primario"]
        events=[e for e in macro_context["fatti"] if e["classe"]=="COMUNICATO_UFFICIALE"]
        self.assertEqual(len({e["fonte"] for e in events}),len(events))
        self.assertTrue(all(e["efficacia_confermata_utc"] is None
                            and e["integrita_feed_alla_lettura"]==
                            "IMPRONTA_DICHIARATA_ORIGINALE_NON_RICALCOLABILE"
                            for e in events))
        originals=ctx["evidenze_economiche_alla_lettura"]["monitor_fonti"]["eventi_macro_ufficiali"]
        fed=next(x for x in originals if x["id"]=="FED_MONETARY_RSS")
        eu=next(x for x in originals if x["id"]=="EU_COUNCIL_RSS")
        self.assertEqual(fed["eventi"][0]["precisione_pubblicazione"],"ORARIO_RSS")
        self.assertEqual(eu["eventi"][0]["precisione_pubblicazione"],"GIORNO_DA_URL")
        self.assertTrue(all(s["direzione_crypto"]=="NON_INFERIBILE"
                            for s in macro_context["scenari_condizionali"]))
        second=bridge.read_context(b,now=x.clock[0])
        self.assertEqual(second["evidenze_economiche_alla_lettura"]
                         ["contesto_macro_primario"],macro_context)
        late=bridge.read_context(b,now=x.clock[0]+dt.timedelta(days=15))
        latest=late["evidenze_economiche_alla_lettura"]["contesto_macro_primario"]
        self.assertEqual(latest["numero_feed_primari_freschi"],0)

if __name__=="__main__":
    unittest.main()
