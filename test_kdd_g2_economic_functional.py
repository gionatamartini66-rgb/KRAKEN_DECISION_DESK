"""G2 KDD-43: discriminating functional tests, wholly invented wallet/public HTTP fixtures.

These tests exercise the *real* KDD producer -> dossier -> packet -> GPT
bridge; fake desk.request is not a genuine live HTTP acquisition. Source
identifiers and evidence hash semantics are separately verified against
original public documents in the live smoke report.
"""
import copy
import datetime as dt
import hashlib
import json
import unittest
from unittest import mock

import dossier_trade as producer
import kdd_economic_sources as primary
import kdd_economics as econ
import kdd_network_defi as network
import scripts.kdd_bridge_g2 as bridge
import scripts.kdd_wallet_packet_g0 as packet_module
from scripts import test_kdd_wallet_packet_g0 as fixtures

T=dt.datetime(2026,11,18,8,0,tzinfo=dt.timezone.utc)
STRK_TEXT=(
    "To align long-term incentives of the Investors and Early Contributors, "
    "all tokens allocated to Investors and Early Contributors is subject to "
    "the lock-up schedule. "
    "- Up to 0.64% (64 million tokens) have been unlocked on the 15th of each "
    "month, starting April 15, 2024, and going through March 15, 2025, for "
    "a total of 7.68% (768 million tokens). "
    "- Up to 1.27% (127 million tokens) have been and will be unlocked "
    "on the 15th of each month, starting April 15, 2025, and going through "
    "March 15, 2027, for a total of 30.48% (3.048 billion tokens).")

FED_URL="https://www.federalreserve.gov/newsevents/pressreleases/monetary20261114a.htm"
EU_URL=("https://www.consilium.europa.eu/en/press/press-releases/"
        "2026/11/16/council-imposes-sanctions-on-four-entities/")
FED_RSS=(
    '<rss version="2.0"><channel><item>'
    '<title>Federal Reserve issues FOMC statement</title>'
    '<link>'+FED_URL+'</link>'
    '<pubDate>Sat, 14 Nov 2026 18:00:00 GMT</pubDate>'
    '</item></channel></rss>').encode()
EU_RSS=(
    '<rss xmlns:a10="http://www.w3.org/2005/Atom" version="2.0">'
    '<channel><item><title>Council imposes sanctions on four entities</title>'
    '<link>'+EU_URL+'</link>'
    '<a10:updated>2026-11-16T08:00:00+00:00</a10:updated>'
    '</item></channel></rss>').encode()


class G2FunctionalChainTests(unittest.TestCase):
    """No real balance, no orders, no private API, no actual macro price forecast."""
    def setUp(self):
        self.original_T=fixtures.T
        fixtures.T=T
        self.addCleanup(lambda: setattr(fixtures,"T",self.original_T))
        f=fixtures.WalletPacketG0Tests(
            "test_wallet_first_all_assets_even_if_quote_missing")
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f=f
        f._analytic_fixture()
        f.portfolio["posizioni"]=[
            {"token":"BTC","quantita":"0.05","disponibile_spot":"0.05","costo_medio_eur":None},
            {"token":"ETH","quantita":"1","disponibile_spot":"1","costo_medio_eur":None},
            {"token":"STRK","quantita":"500","disponibile_spot":"500","costo_medio_eur":None}]
        market={"BTC":("BTCEUR",40000),"ETH":("ETHEUR",2000),"STRK":("STRKEUR",1)}
        f.snapshot["markets"]={t:{"token":t,"pair":t+"/EUR","pair_key":key,"prezzo_eur":val}
                               for t,(key,val) in market.items()}
        f.snapshot["trends"]={}
        f.report["posizioni"]=[{
            "token":t,"quantita":f.portfolio["posizioni"][i]["quantita"],
            "prezzo_eur":v,"valore_eur":float(f.portfolio["posizioni"][i]["quantita"])*v,
            "pl_non_realizzato_eur":None,"note":["FIXTURE"],"decisione":"NESSUNA_DECISIONE"}
            for i,(t,(_,v)) in enumerate(market.items())]
        f.report["totale_stimato_eur"]=4500
        f.report["totale_parziale"]=False
        f.report["stato_totale"]="COMPLETO"
        f.dossier["candidati"][0]["kraken_pair_key"]="SOLUSD"
        f.dossier["grafici_4h"]={}
        self.pairs={key:{"wsname":t+"/EUR","altname":key,"status":"online"}
                    for t,(key,v) in market.items()}
        self.pairs["SOLUSD"]={"wsname":"SOL/USD","altname":"SOLUSD","status":"online"}
        self.clock=[T]
        self.requested=[]
        f.dump()

    def get(self,url,timeout=12):
        self.requested.append(url)
        if url==primary.STRK_URL:
            return STRK_TEXT.encode()
        if url==primary.MACRO_RELEASE_FEEDS[0][1]:return FED_RSS
        if url==primary.MACRO_RELEASE_FEEDS[1][1]:return EU_RSS
        for token in ("BTC","ETH","STRK","SOL"):
            cg=econ.PROJECTS[token][0]
            if url.startswith(econ.CG+cg+"?"):
                return json.dumps({"id":cg,"symbol":token.lower(),
                    "name":econ.PROJECTS[token][1],
                    "market_data":{
                      "last_updated":self.clock[0].isoformat(),
                      "market_cap":{"usd":1000},
                      "fully_diluted_valuation":{"usd":2000},
                      "circulating_supply":100,
                      "total_supply":200,"max_supply":300}}).encode()
        if "/releases/latest" in url:
            repo=url.split("/repos/")[1].split("/releases/latest")[0]
            return json.dumps({
                "html_url":"https://github.com/"+repo+"/releases/tag/v2",
                "tag_name":"v2","name":"Synthetic version v2",
                "published_at":"2026-11-01T10:00:00+00:00"}).encode()
        if "/pulls?" in url or "/issues?" in url or "/security-advisories?" in url:
            return b"[]"
        raise OSError("Public fixture does not emulate this source")

    def _real_producer_to_bridge(self):
        f=self.f
        candidates=[{"token":"SOL","coppia_analisi":"SOL/USD","kraken_pair_key":"SOLUSD"}]
        four={"posizioni":[{"token":t,"coppia":t+"/EUR","pair_key":key}
                            for t,(key,_) in {
                                "BTC":("BTCEUR",40000),
                                "ETH":("ETHEUR",2000),
                                "STRK":("STRKEUR",1)}.items()]}
        previous=None
        source=dict(f.snapshot,feed=[])
        with mock.patch.object(producer.desk,"request",side_effect=self.get), \
             mock.patch.object(producer.time,"sleep"), \
             mock.patch.object(network,"_http",side_effect=OSError("Mocked offline RPC")):
            for i in range(8):
                self.clock[0]=T+dt.timedelta(minutes=i)
                with producer.primary_refresh_context():
                    previous=producer.economic_evidence(
                        source,f.portfolio,four,candidates,self.clock[0],
                        asset_pairs=self.pairs,previous=previous)
        # Align every synthetic snapshot time for the existing strict packet
        # contract; this does not update a real wallet or public market.
        iso=self.clock[0].isoformat()
        f.portfolio["data_ora_saldo_privato_utc"]=iso
        f.portfolio["fonte_quantita"]="SYNTHETIC ONLY Kraken BalanceEx API privata SOLA LETTURA, "+iso
        f.snapshot["rilevazione_utc"]=iso
        f.report["rilevazione_utc"]=iso
        f.dossier["kraken_istantanea_utc"]=iso
        f.dossier["evidenze_economiche"]=previous
        f.dump()
        packet=f.pack(now=self.clock[0])
        bundle={"schema":bridge.SCHEMA_BUNDLE,"packet":packet,
                "packet_sha256":bridge.digest(packet),
                "preparato_utc":self.clock[0].isoformat(),
                "provenienza":"SOLO_FIXTURE_SINTETICA",
                "trasporto":"NESSUN_GPT"}
        return previous,packet,bundle,bridge.read_context(bundle,now=self.clock[0])

    def test_g2_primary_starknet_macro_provenance_really_reaches_gpt_bridge(self):
        source,packet,bundle,context=self._real_producer_to_bridge()
        self.assertEqual([x["token"] for x in context["evidenze_economiche_alla_lettura"]["posizioni"]],
                         ["BTC","ETH","STRK"])
        self.assertEqual([x["token"] for x in context["evidenze_economiche_alla_lettura"]["candidati"]],
                         ["SOL"])
        self.assertTrue(all("giudizio_economico_integrato" in x for x in
                            context["evidenze_economiche_alla_lettura"]["posizioni"]+
                            context["evidenze_economiche_alla_lettura"]["candidati"]))
        btc=context["evidenze_economiche_alla_lettura"]["posizioni"][0]
        supply=btc["quadro_tokenomics"]["supply"]
        self.assertEqual(supply["provenienza_acquisizione"],
                         "HTTP_DICHIARATO_ORIGINALE_NON_RIVALIDABILE")
        self.assertIsNone(supply["evidence_id"])
        self.assertTrue(supply["riferimento_evidenza_dichiarato"].startswith("E-FUND-bitcoin-"))
        self.assertRegex(supply["sha256_risposta"],r"^[0-9a-f]{64}$")
        self.assertIsNone(btc["giudizio_economico_integrato"]["componenti"]
                         ["fondamentali"]["evidence_id"])
        self.assertEqual(btc["giudizio_economico_integrato"]["componenti"]
                         ["fondamentali"]["riferimento_evidenza_dichiarato"],
                         supply["riferimento_evidenza_dichiarato"])
        strk=context["evidenze_economiche_alla_lettura"]["posizioni"][2]
        calendar=strk["quadro_tokenomics"]["calendario"]
        self.assertEqual(calendar["stato"],"DOCUMENTO_PRIMARIO_CON_MASSIMI_DATATI")
        self.assertEqual(calendar["provenienza_documento"],
                         "RISPOSTA_PUBBLICA_RICEVUTA_DAL_PRODUTTORE")
        self.assertEqual(calendar["sha256_documento_originale"],
                         hashlib.sha256(STRK_TEXT.encode()).hexdigest())
        upcoming=calendar["prossime_scadenze_documentate"]
        self.assertTrue(any(row["data_programmata"]=="2026-12-15" and
            row["quantita_massima_token"]==127000000 and
            row["esecuzione"]=="NON_ATTESTATA" and
            row["vendita"]=="NON_ATTESTATA" and
            row["evidence_id"].startswith("E-SCHEDULE-") for row in upcoming))
        facts=strk["quadro_eventi"]["eventi"]
        self.assertTrue(any(e["tipo"]=="UNLOCK_MASSIMO_DATATO_PRIMARIO"
                            and e["evidence_id"].startswith("E-EVENTO-") for e in facts))
        macro=context["evidenze_economiche_alla_lettura"]["contesto_macro_primario"]
        original=[x for x in macro["fatti"] if x.get("classe")=="COMUNICATO_UFFICIALE"]
        self.assertEqual({x["fonte"] for x in original},{FED_URL,EU_URL})
        self.assertTrue(all(x["evidence_id"].startswith("E-MACRO-") and
                            x["provenienza_feed"]=="RISPOSTA_PUBBLICA_RICEVUTA_DAL_PRODUTTORE"
                            and len(x["sha256_feed_originale"])==64
                            for x in original))
        self.assertTrue(all(x["efficacia_confermata_utc"] is None for x in original))
        self.assertTrue(packet["nessun_ordine"])
        self.assertIn("profondita_book_pubblica",packet["patrimonio"])
        self.assertIn("book_alla_lettura",context)
        self.assertNotIn("book_150_alla_lettura",context)
        self.assertNotIn("alternative_liberazione_150_lordi",
                         packet["patrimonio"]["quadro_economico_per_gpt"])
        self.assertEqual(packet["patrimonio"]["quadro_economico_per_gpt"][
                         "disponibilita_lorda_spot"]["n_posizioni"],3)
        self.assertNotIn("book_pubblico_150",packet["patrimonio"])
        # Semantic read revalidates the original source chain; recomputing the
        # transport checksum must never validate altered provenance.
        corrupted=copy.deepcopy(bundle)
        corrupted["packet"]["evidenze_multifonte"]["economia"]["posizioni"][0][
            "fondamentali"]["prova_acquisizione"]["sha256_corpo_risposta"]="g"*64
        corrupted["packet_sha256"]=bridge.digest(corrupted["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(corrupted,now=self.clock[0])

    def test_g2_structural_source_is_not_http_acquisition(self):
        identity=econ.identify("BTC","BTC/EUR","BTCEUR",catalog={
            "BTCEUR":{"pair_key":"BTCEUR","pair":"BTC/EUR","base":"BTC","quote":"EUR"}})
        t=T
        plausible={"id":"bitcoin","symbol":"btc","name":"Bitcoin","market_data":{
             "last_updated":t.isoformat(),"market_cap":{"usd":100},
             "fully_diluted_valuation":{"usd":200},
             "circulating_supply":10,"total_supply":20,"max_supply":21}}
        record=econ.fundamentals(identity,plausible,t,t)
        self.assertEqual(record["stato"],"VERIFICATO")
        self.assertEqual(record["prova_acquisizione"]["stato"],
                         "NON_ATTESTATA_DAL_PRODUTTORE")
        displayed=econ.tokenomics_view({"token":"BTC","identita":identity,
                         "fondamentali":record},
                         {"calendari":[],"politiche_emissioni":[]})
        self.assertEqual(displayed["supply"]["validita_strutturale"],"VALIDATA")
        self.assertEqual(displayed["supply"]["provenienza_acquisizione"],
                         "ACQUISIZIONE_NON_ATTESTATA")
        self.assertIsNone(displayed["supply"]["evidence_id"])

    def test_g2_regime_insufficient_wrong_source_and_conflicting_frames(self):
        t=T
        base=econ.regime({"timeframe":{"4H":{"stato":"AGGIORNATO",
            "figure_candlestick":{"stato":"AGGIORNATO","trend_precedente":"SALITA"}},
            "1D":{"stato":"AGGIORNATO",
            "figure_candlestick":{"stato":"AGGIORNATO","trend_precedente":"DISCESA"}}}},
            {"fonte":"https://api.coingecko.com/api/v3/global",
             "aggiornato_sorgente_utc":t.isoformat(),
             "var_capitalizzazione_24h_pct":-2,
             "capitalizzazione_totale_usd":1000,
             "volume_24h_usd":100},t)
        self.assertEqual(base["stato"],"TRANSIZIONE")
        core=econ.regime_participation(base,None,{},t)
        result=econ.regime_integrato(core,{},t)
        self.assertEqual(result["stato"],"TRANSIZIONE")
        self.assertTrue(all(row["evidence_id"] and row["evidence_id"].startswith("E-REGIME-")
                            for row in result["evidenze_indipendenti"]))
        tampered=copy.deepcopy(core)
        for row in tampered["famiglie_osservate"]:
            if row["famiglia"]=="ATTIVITA_AGGREGATA":
                row["fonte"]="https://evil.example/global"
        result=econ.regime_integrato(tampered,{},t)
        self.assertEqual(result["stato"],"INDETERMINATO")
        self.assertIn("Volume/capitalizzazione globale attendibile",
                      result["informazioni_mancanti"])
        stale=econ.regime_integrato(core,{},t+dt.timedelta(hours=3))
        self.assertEqual(stale["stato"],"INDETERMINATO")

    def test_g2_macro_raw_feed_hash_includes_bom(self):
        # Real public XML may begin with the UTF-8 BOM. The evidence SHA must
        # identify the ORIGINAL response bytes, not the parser-normalized text.
        original=bytes.fromhex("efbbbf")+FED_RSS
        captured={}
        text,error=primary._fetch(lambda url: original,
                                  primary.MACRO_RELEASE_FEEDS[0][1],
                                  json_data=False,digest_out=captured)
        self.assertIsNone(error)
        self.assertTrue(text.startswith("<rss"))
        self.assertEqual(captured["sha256"],hashlib.sha256(original).hexdigest())
        self.assertNotEqual(captured["sha256"],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(len(primary._macro_official_rss(
            text,primary.MACRO_RELEASE_FEEDS[0],T)),1)
