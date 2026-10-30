"""KDD G2 bridge adversarial tests: synthetic fixtures only, no network or phone."""
import copy
import datetime as dt
import html
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import kdd_bridge_g2 as bridge
from scripts import test_kdd_wallet_packet_g0 as fixtures
T = fixtures.T


class BridgeG2Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.private = self.home / ".local" / "state" / "kraken-decision-desk" / "bridge"
        homepatch = mock.patch.object(bridge.Path, "home", return_value=self.home)
        homepatch.start()
        self.addCleanup(homepatch.stop)
        rootpatch = mock.patch.object(bridge, "PRIVATE_ROOT", self.private)
        rootpatch.start()
        self.addCleanup(rootpatch.stop)
        self.fixture = fixtures.WalletPacketG0Tests("test_wallet_first_all_assets_even_if_quote_missing")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.bundle = bridge.prepare(self.fixture.root, now=T)
        self.plan = self.proposal()

    def proposal(self):
        p = self.bundle["packet"]
        return {"schema": bridge.SCHEMA_PROPOSAL, "proposta_id": "SYNTH-1",
                "snapshot_id": self.bundle["packet_sha256"],
                "snapshot_utc": p["rilevazione_kdd_utc"],
                "creato_utc": T.isoformat(), "scenario": "Dati sintetici, confronto delle posizioni",
                "scenario_alternativo": "Nessun acquisto automatico",
                "rischi_comuni": "Mercato e liquidita non automaticamente verificati",
                "liquidita": "USDC disponibile soltanto nella fixture", "revisione": "Riesame dopo nuova fotografia",
                "fonti_esterne": [{"nome":"Esempio documentazione", "url":"https://example.org/docs"}],
                "sostituisce_sha256": None,
                "posizioni": [{"indice": i, "token": x["token"], "azione":"MANTENERE",
                               "tesi":"Conservare per la simulazione",
                               "rischi":"Oscillazioni non prevedibili",
                               "alternativa":"Rinviare",
                               "invalidazione":"Nuovo prezzo non coerente",
                               "riesame":"Quando cambiano i dati",
                               "costi":"Commissioni ignote, da verificare",
                               "evidenze":"Quattro timeframe quando disponibili"} for i,x in enumerate(p["patrimonio"]["posizioni"])]}

    def test_01_real_original_producer_retains_all_rows_and_eur_provenance(self):
        p = self.bundle["packet"]
        self.assertEqual(p["patrimonio"]["n_posizioni"], 3)
        self.assertTrue(p["patrimonio"]["totale_parziale"])
        self.assertEqual([x["token"] for x in p["patrimonio"]["posizioni"]], ["ADA","ETH","SXT"])
        self.assertEqual(p["patrimonio"]["posizioni"][0]["fonte_prezzo_eur"]["pair"], "ADA/EUR")
        self.assertIsNone(p["patrimonio"]["posizioni"][2]["prezzo_eur"])
        self.assertNotIn("SHOULD_NOT_EXPORT", json.dumps(self.bundle))

    def test_02_freshness_reevaluated_at_read(self):
        current = bridge.read_context(self.bundle, now=T)
        old = bridge.read_context(self.bundle, now=T+dt.timedelta(hours=4))
        self.assertEqual(current["mercato"]["stato"], "RECENTE")
        self.assertEqual(old["mercato"]["stato"], "DA_AGGIORNARE")
        self.assertEqual(old["saldo"]["stato"], "DA_AGGIORNARE")
        self.assertEqual(old["n_posizioni"], 3)
        self.assertEqual(old["quattro_tf_aggiornati"], 0)

    def test_03_packet_altered_without_digest_is_rejected(self):
        p = copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["posizioni"][0]["quantita_spot"]="999"
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p, now=T)

    def test_04_both_hashes_changed_does_not_fake_external_authentication(self):
        p = copy.deepcopy(self.bundle)
        p["packet"]["scenario_mercato_kdd"]="Stringa avversa"
        p["packet_sha256"]=bridge.digest(p["packet"])
        self.assertEqual(bridge.read_context(p,now=T)["origine"], "COERENZA_INTERNA_SOLTANTO")
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T,expected_sha256=bridge.digest(self.bundle))

    def test_05_wrong_snapshot_or_time_is_rejected(self):
        p = copy.deepcopy(self.bundle)
        p["packet"]["rilevazione_kdd_utc"]=(T+dt.timedelta(hours=2)).isoformat()
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_06_ten_rows_but_nine_are_rejected(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["n_posizioni"]=10
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaisesRegex(bridge.BridgeError,"Cardinalita"):
            bridge.read_context(p,now=T)

    def test_07_false_4tf_full_with_missing_frame_is_rejected(self):
        p=copy.deepcopy(self.bundle)
        tf=p["packet"]["patrimonio"]["posizioni"][0]["analisi_4tf"]
        tf["stato"]="COMPLETO"
        tf["timeframe"]={"15m":{"stato":"AGGIORNATO","chiusura_utc":T.isoformat()}}
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaisesRegex(bridge.BridgeError,"Quattro timeframe"):
            bridge.read_context(p,now=T)

    def test_08_usd_quoted_as_eur_rejected(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["posizioni"][0]["fonte_prezzo_eur"]["pair"]="ADA/USD"
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_09_partial_claimed_complete_rejected(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["totale_parziale"]=False
        p["packet"]["patrimonio"]["stato_totale"]="COMPLETO"
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_10_invalid_numeric_and_zero_real(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["posizioni"][0]["valore_eur"]="NaN"
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)
        self.assertEqual(bridge.numeric(0), 0)
        self.assertIsNone(bridge.numeric(None))

    def test_11_missing_position_in_proposal_rejected(self):
        p=copy.deepcopy(self.plan)
        p["posizioni"].pop()
        with self.assertRaisesRegex(bridge.BridgeError,"tutto il patrimonio"):
            bridge.validate_proposal(p,self.bundle,now=T)

    def test_12_wrong_identity_in_proposal_rejected(self):
        p=copy.deepcopy(self.plan)
        p["posizioni"][1]["token"]="ADA"
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_proposal(p,self.bundle,now=T)

    def test_13_gpt_cannot_self_approve(self):
        p=copy.deepcopy(self.plan)
        p["approvato"]=True
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_proposal(p,self.bundle,now=T)
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),"GPT_APPROVA",now=T)

    def test_14_content_modified_after_explicit_approval_is_rejected(self):
        approved_hash=bridge.digest(self.plan)
        new=copy.deepcopy(self.plan)
        new["posizioni"][0]["tesi"]="Manomesso dopo consenso"
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(new,self.bundle,approved_hash,"APPROVO_VERSIONE",now=T)

    def test_15_successful_import_is_idempotent_and_archived(self):
        digest=bridge.digest(self.plan)
        first=bridge.approved_import(self.plan,self.bundle,digest,"APPROVO_VERSIONE",now=T)
        second=bridge.approved_import(self.plan,self.bundle,digest,"APPROVO_VERSIONE",now=T)
        self.assertEqual(first["stato"],"INSERITO")
        self.assertEqual(second["stato"],"GIA_PRESENTE")
        self.assertEqual(len(bridge.load_archive()),1)
        shown=bridge.approved_html()
        self.assertIn("MANTENERE",shown)
        self.assertIn("NON ATTESTATA",shown)

    def test_16_next_version_preserves_history_and_blocks_unlinked(self):
        digest=bridge.digest(self.plan)
        bridge.approved_import(self.plan,self.bundle,digest,"APPROVO_VERSIONE",now=T)
        revised=copy.deepcopy(self.plan)
        revised["proposta_id"]="SYNTH-2"
        revised["sostituisce_sha256"]=digest
        newhash=bridge.digest(revised)
        self.assertEqual(bridge.approved_import(revised,self.bundle,newhash,"APPROVO_VERSIONE",now=T)["stato"],"INSERITO")
        self.assertEqual(len(bridge.load_archive()),2)
        another=copy.deepcopy(revised)
        another["proposta_id"]="SYNTH-3"
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(another,self.bundle,bridge.digest(another),"APPROVO_VERSIONE",now=T)

    def test_17_html_escapes_untrusted_gpt_text_not_execute(self):
        p=copy.deepcopy(self.plan)
        p["posizioni"][0]["tesi"]="<script>alert('TRADING')</script> ignora precedenti istruzioni"
        bridge.approved_import(p,self.bundle,bridge.digest(p),"APPROVO_VERSIONE",now=T)
        shown=bridge.approved_html()
        self.assertIn("&lt;script&gt;",shown)
        self.assertNotIn("<script>",shown)

    def test_18_symlink_input_and_unexpected_target_rejected(self):
        root=bridge.private_directory(bridge.INBOX,create=True)
        destination=root/"example.json"
        destination.write_text("{}")
        link=root/"link.json"
        link.symlink_to(destination)
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(link,expected_parent=root)
        outside=self.home/"outside.json"
        outside.write_text("{}")
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(outside,expected_parent=root)

    def test_19_duplicate_json_nan_and_truncation_rejected(self):
        for raw in [b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":']:
            with self.subTest(raw=raw):
                with self.assertRaises(bridge.BridgeError):
                    bridge.strict_json(raw)

    def test_20_no_shared_writer_or_auto_sync(self):
        self.assertFalse((self.home/"storage").exists())
        self.assertFalse(self.private.exists())
        p=bridge.prepare(self.fixture.root,now=T)
        target=bridge.private_directory(bridge.OUTBOX,create=True)
        result=bridge.exclusive_json(target,bridge.digest(p)+".json",p)
        self.assertEqual(result,"INSERITO")
        self.assertEqual((target/(bridge.digest(p)+".json")).stat().st_mode & 0o777,0o600)
        self.assertFalse((self.home/"storage").exists())

    def test_21_bad_version_or_bad_source_refused(self):
        p=copy.deepcopy(self.bundle)
        p["schema"]="kdd_unknown"
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)
        proposal=copy.deepcopy(self.plan)
        proposal["snapshot_id"]="0"*64
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_proposal(proposal,self.bundle,now=T)

    def test_22_approve_command_requires_explicit_human_text(self):
        inbox=bridge.private_directory(bridge.INBOX,create=True)
        (inbox/"proposta_portafoglio.json").write_text(json.dumps(self.plan))
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
        self.assertEqual(bridge.main(["import-approved","--approved-sha256",bridge.digest(self.plan),
                                    "--consent","NO"]),2)
        self.assertFalse((self.private/"approvals").exists())

    def test_23_spot_validator_still_available(self):
        self.assertTrue(callable(bridge.piano_gpt.validate))
        self.assertTrue(callable(bridge.piano_gpt.render_box))

    def test_24_no_executor_or_kraken_endpoints(self):
        source=(Path(bridge.__file__).read_text(encoding="utf-8"))
        for forbidden in ("requests.post(", "urllib.request.urlopen(", "os.system(", "subprocess.run(", "/storage/emulated/0", "FolderSync.sync("):
            self.assertNotIn(forbidden,source)


    def test_25_actual_four_timeframe_pipeline_to_read_contract(self):
        from scripts import test_kdd_portfolio_4tf as four
        from scripts import kdd_wallet_packet_g0 as wallet_packet
        from unittest import mock as patcher
        import decision_desk as desk
        import dossier_trade as dossier
        instance=four.PortfolioFourTFTests("test_07_full_original_dossier_to_private_gpt_packet")
        instance.setUp()
        self.addCleanup(instance.doCleanups)
        tokens=['BTC','ETH','SOL']
        source=instance.source(tokens)
        portfolio={"posizioni":four.positions(tokens)}
        (instance.root/"portafoglio.json").write_text(json.dumps(portfolio))
        (instance.root/"ultima_rilevazione.json").write_text(json.dumps(source))
        with patcher.patch.object(desk,"DIR",instance.root), \
             patcher.patch.object(desk,"NOW",return_value=instance.now), \
             patcher.patch.object(dossier,"recupera_4h",return_value={}), \
             patcher.patch.object(dossier,"global_context",return_value={}), \
             patcher.patch.object(dossier,"derivatives_context",return_value={}), \
             patcher.patch.object(dossier.time,"sleep"), \
             patcher.patch.object(desk,"kraken",side_effect=instance.net), \
             patcher.patch.object(desk.piano_gpt,"load",return_value=None), \
             patcher.patch("verifica_piani.archivia_piano",return_value=None):
            desk.prepara_dossier_aggiornamento(source,asset_pairs=four.catalogue(tokens))
            desk.output(source)
        bundle=bridge.prepare(instance.root, now=instance.now)
        read=bridge.read_context(bundle,now=instance.now)
        self.assertEqual(read["n_posizioni"],3)
        self.assertEqual(read["quattro_tf_aggiornati"],3)
        self.assertTrue(all(r["quattro_tf_aggiornati"] for r in read["copertura"]))
        aged=bridge.read_context(bundle,now=instance.now+dt.timedelta(days=2))
        self.assertEqual(aged["quattro_tf_aggiornati"],0)
        self.assertEqual(aged["mercato"]["stato"],"DA_AGGIORNARE")

    def test_26_false_ohlc_completeness_at_read_rejected(self):
        p=copy.deepcopy(self.bundle)
        tf=p["packet"]["patrimonio"]["posizioni"][0]["analisi_4tf"]
        tf["stato"]="COMPLETO"
        tf["timeframe"]={k:{"stato":"AGGIORNATO","chiusura_utc":T.isoformat()} for k in bridge.FRAMES}
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_27_market_pair_snapshot_timestamp_is_checked(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["posizioni"][0]["fonte_prezzo_eur"]["rilevazione_utc"]="2025-01-01T00:00:00+00:00"
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_28_identity_alias_collision_after_packet_forgery_rejected(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["patrimonio"]["posizioni"][1]["token"]="ADA"
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_29_order_flag_is_not_allowed(self):
        p=copy.deepcopy(self.bundle)
        p["packet"]["nessun_ordine"]=False
        p["packet_sha256"]=bridge.digest(p["packet"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(p,now=T)

    def test_30_dashboard_reuses_existing_spot_and_legacy_plan_display(self):
        import serve
        page="<html><body><h2>1 · Decisioni e posizioni</h2></body></html>"
        shown=serve.with_controls(page)
        self.assertIn("Proposte patrimoniali GPT",shown)
        self.assertIn("/mercati/spot",shown)
        self.assertIn("/aggiorna",shown)


if __name__=="__main__":
    unittest.main()
