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
        self.bundle = bridge.prepare(self.fixture.root, now=T, _fixture=True)
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

    def persist_origin(self):
        # The original G2 fixture used volatile _LOCAL_ORIGINS. R3 must
        # actually deposit a distinct, owner-only KDD-produced original.
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        bridge.exclusive_json(folder,bridge.digest(self.bundle)+".json",self.bundle)

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
        self.persist_origin()
        p=copy.deepcopy(self.plan)
        p["approvato"]=True
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_proposal(p,self.bundle,now=T)
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),"GPT_APPROVA",now=T)

    def test_14_content_modified_after_explicit_approval_is_rejected(self):
        self.persist_origin()
        approved_hash=bridge.digest(self.plan)
        new=copy.deepcopy(self.plan)
        new["posizioni"][0]["tesi"]="Manomesso dopo consenso"
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(new,self.bundle,approved_hash,"APPROVO_VERSIONE",now=T)

    def test_15_successful_import_is_idempotent_and_archived(self):
        self.persist_origin()
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
        self.persist_origin()
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
        self.persist_origin()
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
        p=bridge.prepare(self.fixture.root,now=T,_fixture=True)
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
        (inbox/"proposta_portafoglio.json").chmod(0o600)
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
        (inbox/"pacchetto_riferimento.json").chmod(0o600)
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
        bundle=bridge.prepare(instance.root, now=instance.now, _fixture=True)
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


    def test_31_byte_digest_exact_export_and_after_transport(self):
        import hashlib
        out=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        bridge.exclusive_json(out,name,self.bundle)
        path=out/name
        byte_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        result=bridge.read_bundle(path,now=T,expected_sha256=byte_sha)
        self.assertEqual(result["n_posizioni"],3)
        self.assertNotEqual(byte_sha,bridge.digest(self.bundle))
        with self.assertRaises(bridge.BridgeError):
            bridge.read_bundle(path,now=T,expected_sha256=bridge.digest(self.bundle))

    def test_32_truncated_or_replaced_transfer_rejected(self):
        import hashlib
        out=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        bridge.exclusive_json(out,name,self.bundle)
        path=out/name
        original_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_bundle(path,now=T,expected_sha256=original_sha)
        path.write_bytes(b'{"schema":"kdd_private_handoff_v001"')
        with self.assertRaises(bridge.BridgeError):
            bridge.read_bundle(path,now=T,expected_sha256=original_sha)

    def test_33_preview_is_not_approval(self):
        self.persist_origin()
        from contextlib import redirect_stdout
        import io
        inbox=bridge.private_directory(bridge.INBOX,create=True)
        (inbox/"proposta_portafoglio.json").write_text(json.dumps(self.plan))
        (inbox/"proposta_portafoglio.json").chmod(0o600)
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
        (inbox/"pacchetto_riferimento.json").chmod(0o600)
        buf=io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(bridge.main(["preview-proposal"]),0)
        self.assertIn(bridge.digest(self.plan),buf.getvalue())
        self.assertFalse((self.private/bridge.ARCHIVE).exists())


    def test_r1_coherent_replacement_proposal_and_packet_still_rejected(self):
        forged = copy.deepcopy(self.bundle)
        forged["packet"]["scenario_mercato_kdd"] = "FOTO FALSA CONSISTENTE"
        forged["packet_sha256"] = bridge.digest(forged["packet"])
        altered = copy.deepcopy(self.plan)
        altered["snapshot_id"] = bridge.digest(forged["packet"])
        bridge.validate_proposal(altered, forged, now=T)
        with self.assertRaisesRegex(bridge.BridgeError, "originaria"):
            bridge.approved_import(altered, forged, bridge.digest(altered), "APPROVO_VERSIONE", now=T)
        self.assertFalse((self.private / bridge.ARCHIVE).exists())

    def test_r1_cli_rejects_coherent_replaced_pair_without_kdd_outbox(self):
        from contextlib import redirect_stdout
        import io
        forged = copy.deepcopy(self.bundle)
        forged["packet"]["scenario_mercato_kdd"] = "ORIGINE SOSTITUITA"
        forged["packet_sha256"] = bridge.digest(forged["packet"])
        altered = copy.deepcopy(self.plan)
        altered["snapshot_id"] = bridge.digest(forged["packet"])
        inbox = bridge.private_directory(bridge.INBOX, create=True)
        (inbox/"proposta_portafoglio.json").write_text(json.dumps(altered))
        (inbox/"proposta_portafoglio.json").chmod(0o600)
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(forged))
        (inbox/"pacchetto_riferimento.json").chmod(0o600)
        with redirect_stdout(io.StringIO()) as out:
            rc = bridge.main(["import-approved", "--approved-sha256", bridge.digest(altered),
                              "--consent", "APPROVO_VERSIONE"])
        self.assertEqual(rc, 2)
        self.assertIn("originaria", out.getvalue())
        self.assertFalse((self.private / bridge.ARCHIVE).exists())

    def test_r1_persistent_kdd_private_origin_survives_process_restart_simulation(self):
        from contextlib import redirect_stdout
        import io
        out = bridge.private_directory(bridge.OUTBOX, create=True)
        bridge.exclusive_json(out, bridge.digest(self.bundle)+".json", self.bundle)
        inbox = bridge.private_directory(bridge.INBOX, create=True)
        (inbox/"proposta_portafoglio.json").write_text(json.dumps(self.plan))
        (inbox/"proposta_portafoglio.json").chmod(0o600)
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
        (inbox/"pacchetto_riferimento.json").chmod(0o600)
        with mock.patch.object(bridge, "_LOCAL_ORIGINS", set()):
            with redirect_stdout(io.StringIO()) as stream:
                rc = bridge.main(["import-approved", "--approved-sha256", bridge.digest(self.plan),
                                  "--consent", "APPROVO_VERSIONE"])
        self.assertEqual(rc, 0, stream.getvalue())
        self.assertEqual(len(bridge.load_archive()), 1)

    def test_r2_interruption_before_link_no_partial_final_retry(self):
        folder = bridge.private_directory(bridge.ARCHIVE, create=True)
        name = bridge.digest(self.plan)+".json"
        entry = {"probe":"synthetic","versione":1}
        with mock.patch.object(bridge.os, "link", side_effect=OSError("injected crash")):
            with self.assertRaises(OSError):
                bridge.exclusive_json(folder, name, entry)
        self.assertFalse((folder/name).exists())
        self.assertEqual(bridge.exclusive_json(folder, name, entry), "INSERITO")
        self.assertEqual(bridge.exclusive_json(folder, name, entry), "GIA_PRESENTE")
        self.assertEqual(bridge.strict_json((folder/name).read_bytes()), entry)

    def test_r2_post_link_interrupt_yields_complete_final_and_idempotent_retry(self):
        folder = bridge.private_directory(bridge.ARCHIVE, create=True)
        name = bridge.digest(self.plan)+".json"
        entry = {"probe":"postcommit", "versione":1}
        # The R3 durable journal adds earlier fsync calls; inject at the
        # *post-link directory sync* (same original oracle, correct phase).
        real_sync=bridge._sync_dir
        count = {"n":0}
        def fail_directory(directory):
            count["n"] += 1
            if count["n"] == 2:
                raise OSError("synthetic crash after hardlink during directory fsync")
            return real_sync(directory)
        with mock.patch.object(bridge, "_sync_dir", side_effect=fail_directory):
            with self.assertRaises(OSError):
                bridge.exclusive_json(folder, name, entry)
        self.assertEqual(bridge.strict_json((folder/name).read_bytes()), entry)
        self.assertEqual(bridge.exclusive_json(folder, name, entry), "GIA_PRESENTE")
        with self.assertRaises(bridge.BridgeError):
            bridge.exclusive_json(folder, name, {"probe":"mutated"})

    def test_r2_orphan_stage_inert_archive_recoverable(self):
        self.persist_origin()
        folder = bridge.private_directory(bridge.ARCHIVE, create=True)
        (folder/".kdd-stage-interrupted.tmp").write_bytes(b'{"truncated":')
        (folder/".kdd-stage-interrupted.tmp").chmod(0o600)
        self.assertEqual(bridge.load_archive(), {})
        version = bridge.digest(self.plan)
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,version,"APPROVO_VERSIONE",now=T)["stato"],"INSERITO")
        self.assertEqual(len(bridge.load_archive()),1)

    def test_r2_concurrent_same_version_exactly_once(self):
        self.persist_origin()
        from concurrent.futures import ThreadPoolExecutor
        version = bridge.digest(self.plan)
        def writer(_):
            return bridge.approved_import(self.plan,self.bundle,version,"APPROVO_VERSIONE",now=T)["stato"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(writer, range(12)))
        self.assertEqual(statuses.count("INSERITO"),1)
        self.assertEqual(statuses.count("GIA_PRESENTE"),11)
        self.assertEqual(len(bridge.load_archive()),1)

    def test_r2_concurrent_conflicting_revisions_cannot_both_succeed(self):
        self.persist_origin()
        from concurrent.futures import ThreadPoolExecutor
        root = bridge.digest(self.plan)
        bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)
        candidates = []
        for label in ("REV-A","REV-B"):
            candidate = copy.deepcopy(self.plan)
            candidate["proposta_id"]=label
            candidate["sostituisce_sha256"]=root
            candidates.append(candidate)
        def writer(p):
            try:
                return bridge.approved_import(p,self.bundle,bridge.digest(p),"APPROVO_VERSIONE",now=T)["stato"]
            except bridge.BridgeError:
                return "RIFIUTATO"
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(writer,candidates))
        self.assertEqual(sorted(statuses),["INSERITO","RIFIUTATO"])
        self.assertEqual(len(bridge.load_archive()),2)

    def test_r2_live_reader_never_sees_uncommitted_partial_final(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        entry={"probe":"ready"}
        key=bridge.digest(self.plan)
        linked=Event()
        release=Event()
        genuine=bridge.os.link
        def held_link(*args,**kwargs):
            linked.set()
            if not release.wait(5):
                raise OSError("test barrier")
            return genuine(*args,**kwargs)
        with mock.patch.object(bridge.os,"link",side_effect=held_link):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(bridge.exclusive_json,folder,key+".json",entry)
                self.assertTrue(linked.wait(5))
                self.assertFalse((folder/(key+".json")).exists())
                # Interrupted stage is not a commit; archive stays readable.
                self.assertEqual(bridge.load_archive(), {})
                release.set()
                self.assertEqual(future.result(timeout=5),"INSERITO")
        self.assertEqual(bridge.strict_json((folder/(key+".json")).read_bytes()),entry)

    def test_read_bundle_marks_byte_digest_separately_from_json_coherence(self):
        import hashlib
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        bridge.exclusive_json(folder,name,self.bundle)
        file=folder/name
        bytehash=hashlib.sha256(file.read_bytes()).hexdigest()
        semantic=bridge.read_context(self.bundle,now=T)
        received=bridge.read_bundle(file,now=T,expected_sha256=bytehash)
        self.assertEqual(semantic["origine"],"COERENZA_INTERNA_SOLTANTO")
        self.assertEqual(received["integrita_trasporto"],"SHA256_BYTE_ESATTI_CONFRONTATO")
        self.assertNotEqual(received["origine"], semantic["origine"])
        self.assertIn("NON_AUTENTICATA",received["origine"])
        with self.assertRaises(bridge.BridgeError):
            bridge.read_bundle(file,now=T,expected_sha256=bridge.digest(self.bundle))


    def test_rt1_01_arbitrary_coherent_source_requires_test_only_seam(self):
        with self.assertRaisesRegex(bridge.BridgeError, "canonica"):
            bridge.prepare(self.fixture.root,now=T)
        # argparse must reject an unsupported operational source selector.
        with self.assertRaises(SystemExit):
            bridge.main(["prepare","--source-dir",str(self.fixture.root)])
        self.assertEqual(bridge.prepare(self.fixture.root,now=T,_fixture=True)["packet_sha256"],
                         self.bundle["packet_sha256"])

    def test_rt1_01_canonical_operational_root_uses_only_fixed_path(self):
        import shutil
        source=self.home/"kraken-decision-desk"/"KRAKEN_DECISION_DESK_V001"
        source.mkdir(parents=True)
        for f in bridge.SOURCE_FILES:
            shutil.copy2(self.fixture.root/f,source/f)
        doc=bridge.prepare(now=T)
        self.assertEqual(doc["packet_sha256"],self.bundle["packet_sha256"])
        self.assertFalse((self.private/bridge.OUTBOX).exists())
        out=bridge.private_directory(bridge.OUTBOX,create=True)
        bridge.exclusive_json(out,bridge.digest(doc)+".json",doc)
        self.assertEqual(bridge.verify_local_origin(doc),bridge.digest(doc))

    def test_rt1_01_source_symlink_and_midflight_directory_change_stopped(self):
        link=self.home/"aliased"
        link.symlink_to(self.fixture.root,target_is_directory=True)
        with self.assertRaises(bridge.BridgeError):
            bridge.prepare(link,now=T,_fixture=True)
        real_build=bridge.wallet.build
        def mutate(root,now=None):
            packet=real_build(root,now=now)
            (root/"ultimo_report.json").write_text('{"tampered":true}')
            return packet
        with mock.patch.object(bridge.wallet,"build",side_effect=mutate):
            with self.assertRaises(bridge.BridgeError):
                bridge.prepare(self.fixture.root,now=T,_fixture=True)

    def test_rt1_01_volatile_origin_never_approves_without_file(self):
        with mock.patch.object(bridge,"_LOCAL_ORIGINS",{bridge.digest(self.bundle)}):
            with self.assertRaisesRegex(bridge.BridgeError,"persistita"):
                bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                       "APPROVO_VERSIONE",now=T)

    def test_rt1_02_nested_trade_claim_and_unknown_root_refused(self):
        for level in ("root","row","source"):
            plan=copy.deepcopy(self.plan)
            if level=="root":
                plan["audit"]={"approvato":True}
            elif level=="row":
                plan["posizioni"][0]["eseguito"]=True
                plan["posizioni"][0]["ordine"]="BUY"
            else:
                plan["fonti_esterne"][0]["meta"]={"esecuzione":"CONFERMATA"}
            with self.subTest(level=level),self.assertRaises(bridge.BridgeError):
                bridge.validate_proposal(plan,self.bundle,now=T)

    def test_rt1_02_duplicate_nested_keys_in_json_rejected(self):
        raw=b'{"fonti_esterne":[{"nome":"a","url":"https://example.org","nome":"b"}]}'
        with self.assertRaises(bridge.BridgeError):
            bridge.strict_json(raw)

    def test_rt1_02_narrative_false_trade_claim_is_not_attested(self):
        self.persist_origin()
        plan=copy.deepcopy(self.plan)
        plan["posizioni"][0]["tesi"]="Il modello dice: ordine già eseguito; affermazione non verificata"
        bridge.validate_proposal(plan,self.bundle,now=T)
        bridge.approved_import(plan,self.bundle,bridge.digest(plan),"APPROVO_VERSIONE",now=T)
        shown=bridge.approved_html()
        self.assertIn("ordine già eseguito",shown)
        self.assertIn("NON ATTESTATA",shown)
        self.assertIn("generato da GPT",shown)

    def test_rt1_03_descriptor_checks_0600_vs_0644_and_symlink(self):
        folder=bridge.private_directory(bridge.INBOX,create=True)
        f=folder/"source.json"
        f.write_text('{"ok":true}')
        f.chmod(0o600)
        self.assertIn(b'"ok"',bridge.read_regular(f,expected_parent=folder))
        f.chmod(0o644)
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(f,expected_parent=folder)
        link=folder/"sym.json"
        link.symlink_to(f)
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(link,expected_parent=folder)

    def test_rt1_03_idempotence_rejects_world_readable_final(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        doc={"probe":"immutable"}
        dest=folder/"SYNTH.json"
        bridge.exclusive_json(folder,dest.name,doc)
        dest.chmod(0o644)
        with self.assertRaises(bridge.BridgeError):
            bridge.exclusive_json(folder,dest.name,doc)

    def test_rt1_03_directory_0700_vs_0755_and_concurrent_created_dir(self):
        folder=bridge.private_directory(bridge.INBOX,create=True)
        bridge.ensure_dir(folder)
        folder.chmod(0o755)
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_dir(folder)
        folder.chmod(0o700)
        bridge.ensure_dir(folder)
        with mock.patch.object(bridge.Path,"mkdir",side_effect=FileExistsError("synthetic")):
            with self.assertRaises(bridge.BridgeError):
                bridge.ensure_dir(folder/"missing")

    def test_rt1_03_replacement_between_open_and_check_fails(self):
        folder=bridge.private_directory(bridge.INBOX,create=True)
        path=folder/"target.json"
        path.write_text('{"old":true}')
        path.chmod(0o600)
        alternate=folder/"replacement.json"
        alternate.write_text('{"new":true}')
        alternate.chmod(0o600)
        real_stat=bridge.os.stat
        done={"ok":False}
        def replace_after_open(p,*args,**kwargs):
            if str(p)==str(path) and not done["ok"] and kwargs.get("follow_symlinks") is False:
                done["ok"]=True
                alternate.replace(path)
            return real_stat(p,*args,**kwargs)
        with mock.patch.object(bridge.os,"stat",side_effect=replace_after_open):
            with self.assertRaisesRegex(bridge.BridgeError,"sostituito"):
                bridge.read_regular(path,expected_parent=folder)

    def test_rt1_03_fifo_not_regular_rejected_without_hang(self):
        folder=bridge.private_directory(bridge.INBOX,create=True)
        fifo=folder/"pipe.json"
        os.mkfifo(fifo,0o600)
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(fifo,expected_parent=folder)

    def test_rt1_04_uncertain_commit_blocks_new_revision_until_reconcile(self):
        self.persist_origin()
        root=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        original_sync=bridge._sync_dir
        n={"i":0}
        def failure(directory):
            n["i"]+=1
            if n["i"]==2:
                raise OSError("fsync post link simulated")
            return original_sync(directory)
        with mock.patch.object(bridge,"_sync_dir",side_effect=failure):
            with self.assertRaises(bridge.PublicationUncertain) as caught:
                bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)
        self.assertEqual(caught.exception.state,"PUBBLICAZIONE_INCERTA")
        self.assertTrue((folder/(root+".json")).exists())
        self.assertTrue((folder/(".pending-"+root+".json")).exists())
        revised=copy.deepcopy(self.plan)
        revised["proposta_id"]="NEXT"
        revised["sostituisce_sha256"]=root
        with self.assertRaisesRegex(bridge.BridgeError,"INCERTA"):
            bridge.approved_import(revised,self.bundle,bridge.digest(revised),"APPROVO_VERSIONE",now=T)
        self.assertEqual(bridge.reconcile_archive(),["PUBBLICATO_CONFERMATO"])
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)["stato"],"GIA_PRESENTE")
        self.assertEqual(bridge.approved_import(revised,self.bundle,bridge.digest(revised),"APPROVO_VERSIONE",now=T)["stato"],"INSERITO")

    def test_rt1_04_unclean_prelink_crash_requires_explicit_reconcile(self):
        self.persist_origin()
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        root=bridge.digest(self.plan)
        with mock.patch.object(bridge.os,"link",side_effect=KeyboardInterrupt("synthetic abrupt stop")):
            with self.assertRaises(KeyboardInterrupt):
                bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)
        self.assertFalse((folder/(root+".json")).exists())
        self.assertTrue((folder/(".pending-"+root+".json")).exists())
        with self.assertRaisesRegex(bridge.BridgeError,"INCERTA"):
            bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)
        self.assertEqual(bridge.reconcile_archive(),["NON_PUBBLICATO"])
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,root,"APPROVO_VERSIONE",now=T)["stato"],"INSERITO")

    def test_rt1_04_cli_status_does_not_print_payload(self):
        from contextlib import redirect_stdout
        import io
        self.persist_origin()
        inbox=bridge.private_directory(bridge.INBOX,create=True)
        for name,obj in (("proposta_portafoglio.json",self.plan),("pacchetto_riferimento.json",self.bundle)):
            p=inbox/name
            p.write_text(json.dumps(obj))
            p.chmod(0o600)
        with mock.patch.object(bridge,"approved_import",side_effect=bridge.PublicationUncertain("fake secret PRICE-EXAMPLE")):
            out=io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(bridge.main(["import-approved","--approved-sha256",bridge.digest(self.plan),"--consent","APPROVO_VERSIONE"]),2)
        self.assertIn("PUBBLICAZIONE_INCERTA",out.getvalue())
        self.assertNotIn("PRICE-EXAMPLE",out.getvalue())

    def test_rt1_05_dashboard_fails_closed_without_taking_home_offline(self):
        import serve
        page="<h2>1 · Decisioni e posizioni</h2><p>Storico Spot conservato</p>"
        for err in (OSError("permission"), RuntimeError("unexpected"), ValueError("bad archive")):
            with mock.patch.object(serve.bridge_g2,"approved_html",side_effect=err):
                shown=serve.with_controls(page)
            self.assertIn("Archivio GPT temporaneamente non verificabile",shown)
            self.assertIn("Nessuna proposta è stata certificata",shown)
            for expected in ("/mercati/spot", "/aggiorna", "Storico Spot conservato"):
                self.assertIn(expected,shown)

    def test_rt1_05_archive_corrupt_and_access_exception_are_diagnostic(self):
        self.persist_origin()
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        damaged=folder/("0"*64+".json")
        damaged.write_bytes(b'{"truncated":')
        damaged.chmod(0o600)
        self.assertIn("STOP",bridge.approved_html())
        with mock.patch.object(bridge,"load_archive",side_effect=OSError("private access")):
            self.assertIn("STOP",bridge.approved_html())


    def test_rt1_04_postlink_semantic_failure_is_publication_uncertain(self):
        self.persist_origin()
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        version=bridge.digest(self.plan)
        with mock.patch.object(bridge,"_finalize_pending",side_effect=bridge.BridgeError("synthetic postlink verification")):
            with self.assertRaises(bridge.PublicationUncertain):
                bridge.approved_import(self.plan,self.bundle,version,"APPROVO_VERSIONE",now=T)
        self.assertTrue((folder/(".pending-"+version+".json")).exists())
        with self.assertRaisesRegex(bridge.BridgeError,"INCERTA"):
            bridge.approved_import(self.plan,self.bundle,version,"APPROVO_VERSIONE",now=T)
        self.assertEqual(bridge.reconcile_archive(),["PUBBLICATO_CONFERMATO"])

    def test_rt1_05_serve_real_corruption_and_unreadable_archive(self):
        import serve
        page="<h2>1 · Decisioni e posizioni</h2><p>Patrimonio e Spot invariati</p>"
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        bad=folder/("f"*64+".json")
        bad.write_bytes(b'{"incomplete":')
        bad.chmod(0o600)
        shown=serve.with_controls(page)
        self.assertIn("Archivio non verificabile",shown)
        self.assertIn("Patrimonio e Spot invariati",shown)
        self.assertIn("/mercati/spot",shown)
        bad.unlink()
        folder.chmod(0o755)
        try:
            shown=serve.with_controls(page)
            self.assertIn("Archivio non verificabile",shown)
            self.assertIn("/aggiorna",shown)
        finally:
            folder.chmod(0o700)

    def test_rt1_05_serve_when_archive_load_raises_io(self):
        import serve
        page="<h2>1 · Decisioni e posizioni</h2><p>Analisi ancora disponibili</p>"
        with mock.patch.object(bridge,"load_archive",side_effect=OSError("synthetic filesystem fault")):
            html=serve.with_controls(page)
        self.assertIn("Archivio non verificabile",html)
        self.assertIn("Analisi ancora disponibili",html)
        self.assertIn("/mercati/spot",html)


    # R4 uses the actual checked-out bridge file in distinct Python processes.
    # Kill paths never execute a Python finally block.
    def _r4_entry(self):
        version=bridge.digest(self.plan)
        return {"versione_sha256":version,"consenso":"CONFERMATO_DA_COMANDO_UTENTE",
                "approvato_utc":T.isoformat(timespec="seconds"),
                "snapshot_id":self.plan["snapshot_id"],"proposta":self.plan,
                "nessun_ordine":True,"esecuzione":"NON_ATTESTATA"}

    def _r4_worker(self, kind, name, obj, phase, *, recover=False):
        import subprocess
        import sys
        import signal
        import uuid
        fixture=self.home/("worker-"+uuid.uuid4().hex+".json")
        fixture.write_text(json.dumps(obj))
        fixture.chmod(0o600)
        script=r"""
import json,os,sys,signal
from pathlib import Path
from scripts import kdd_bridge_g2 as bridge
bridge.PRIVATE_ROOT=Path(sys.argv[1])
kind,name,fixture,phase=sys.argv[2:]
folder=bridge.private_directory(kind,create=True)
if phase in ("before-link","after-link"):
    original_link=os.link
    def broken_link(*args,**kwargs):
        if phase=="before-link":
            os.kill(os.getpid(),signal.SIGKILL)
        original_link(*args,**kwargs)
        os.kill(os.getpid(),signal.SIGKILL)
    bridge.os.link=broken_link
if phase=="before-cleanup":
    old_unlink=Path.unlink
    def stop_unlink(path,*args,**kwargs):
        if path.name.startswith(".kdd-stage-"):
            os.kill(os.getpid(),signal.SIGKILL)
        return old_unlink(path,*args,**kwargs)
    Path.unlink=stop_unlink
if phase=="during-recovery":
    old_unlink=Path.unlink
    def stop_after_unlink(path,*args,**kwargs):
        answer=old_unlink(path,*args,**kwargs)
        if path.name.startswith(".kdd-stage-"):
            os.kill(os.getpid(),signal.SIGKILL)
        return answer
    Path.unlink=stop_after_unlink
if phase=="recover" or phase=="during-recovery":
    print(json.dumps(bridge.reconcile_directory(kind)),flush=True)
elif phase=="publish":
    with bridge._archive_write_lock(folder):
        print(bridge.exclusive_json(folder,name,json.loads(Path(fixture).read_text())),flush=True)
else:
    with bridge._archive_write_lock(folder):
        bridge.exclusive_json(folder,name,json.loads(Path(fixture).read_text()))
"""
        cmd=[sys.executable,"-B","-c",script,str(self.private),kind,name,str(fixture),phase]
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(bridge.__file__).resolve().parents[1])
        return subprocess.run(cmd,env=env,cwd=env["PYTHONPATH"],
                              capture_output=True,text=True,timeout=18)

    def test_rt2_real_sigkill_before_link_archive(self):
        self.persist_origin()
        version=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        proc=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"before-link")
        self.assertEqual(proc.returncode,-9,proc.stderr)
        self.assertFalse((folder/(version+".json")).exists())
        self.assertTrue((folder/(".pending-"+version+".json")).exists())
        recovery=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"recover")
        self.assertEqual(recovery.returncode,0,recovery.stderr)
        self.assertIn("NON_PUBBLICATO",recovery.stdout)
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,version,
                          "APPROVO_VERSIONE",now=T)["stato"],"INSERITO")

    def test_rt2_real_sigkill_after_link_archive_nlink2_and_recovery(self):
        self.persist_origin()
        version=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        kill=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"after-link")
        self.assertEqual(kill.returncode,-9,kill.stderr)
        dest=folder/(version+".json")
        marker=bridge.strict_json((folder/(".pending-"+version+".json")).read_bytes())
        stage=folder/marker["stage"]
        self.assertTrue(stage.exists())
        self.assertEqual(dest.stat().st_nlink,2)
        self.assertEqual((dest.stat().st_dev,dest.stat().st_ino),
                         (stage.stat().st_dev,stage.stat().st_ino))
        with self.assertRaises(bridge.BridgeError):
            bridge.read_regular(dest,expected_parent=folder)  # nlink1 still mandatory
        self.assertIn("STOP",bridge.approved_html())
        recovery=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"recover")
        self.assertEqual(recovery.returncode,0,recovery.stderr)
        self.assertIn("PUBBLICATO_CONFERMATO",recovery.stdout)
        self.assertFalse(stage.exists())
        self.assertEqual(dest.stat().st_nlink,1)
        self.assertEqual(bridge.load_archive()[version]["consenso"],"CONFERMATO_DA_COMANDO_UTENTE")
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,version,
                            "APPROVO_VERSIONE",now=T)["stato"],"GIA_PRESENTE")

    def test_rt2_real_sigkill_before_cleanup_outbox(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        kill=self._r4_worker(bridge.OUTBOX,name,self.bundle,"before-cleanup")
        self.assertEqual(kill.returncode,-9,kill.stderr)
        dest=folder/name
        self.assertEqual(dest.stat().st_nlink,2)
        with self.assertRaises(bridge.BridgeError):
            bridge.verify_local_origin(self.bundle)
        repair=self._r4_worker(bridge.OUTBOX,name,self.bundle,"recover")
        self.assertEqual(repair.returncode,0,repair.stderr)
        self.assertIn("PUBBLICATO_CONFERMATO",repair.stdout)
        self.assertEqual(dest.stat().st_nlink,1)
        self.assertEqual(bridge.verify_local_origin(self.bundle),bridge.digest(self.bundle))
        self.assertEqual(bridge.exclusive_json(folder,name,self.bundle),"GIA_PRESENTE")

    def test_rt2_real_sigkill_during_reconciliation_then_retry(self):
        self.persist_origin()
        version=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        crash=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"after-link")
        self.assertEqual(crash.returncode,-9,crash.stderr)
        second=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"during-recovery")
        self.assertEqual(second.returncode,-9,second.stderr)
        self.assertTrue((folder/(".pending-"+version+".json")).exists())
        self.assertEqual((folder/(version+".json")).stat().st_nlink,1)
        third=self._r4_worker(bridge.ARCHIVE,version+".json",self._r4_entry(),"recover")
        self.assertEqual(third.returncode,0,third.stderr)
        self.assertIn("PUBBLICATO_CONFERMATO",third.stdout)
        self.assertEqual(bridge.reconcile_archive(),[])
        self.assertEqual(len(bridge.load_archive()),1)

    def test_rt2_two_independent_processes_reconcile_same_version(self):
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        version=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        self.assertEqual(self._r4_worker(bridge.ARCHIVE,version+".json",
                         self._r4_entry(),"after-link").returncode,-9)
        with ThreadPoolExecutor(max_workers=2) as pool:
            procs=list(pool.map(lambda _:self._r4_worker(bridge.ARCHIVE,version+".json",
                         self._r4_entry(),"recover"),range(2)))
        self.assertTrue(all(p.returncode==0 for p in procs),[p.stderr for p in procs])
        results=" ".join(p.stdout for p in procs)
        self.assertEqual(results.count("PUBBLICATO_CONFERMATO"),1)
        self.assertEqual((folder/(version+".json")).stat().st_nlink,1)
        self.assertEqual(len(bridge.load_archive()),1)

    def test_rt2_malicious_stage_wrong_inode_and_symlink_stops(self):
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        version=bridge.digest(self.plan)
        self.assertEqual(self._r4_worker(bridge.ARCHIVE,version+".json",
                         self._r4_entry(),"after-link").returncode,-9)
        marker=bridge.strict_json((folder/(".pending-"+version+".json")).read_bytes())
        stage=folder/marker["stage"]
        dest=folder/(version+".json")
        stage.unlink()
        stage.write_text('{"fake":true}')
        stage.chmod(0o600)
        with self.assertRaises(bridge.BridgeError):
            bridge.reconcile_archive()
        self.assertTrue(dest.exists())
        stage.unlink()
        stage.symlink_to(dest)
        with self.assertRaises(bridge.BridgeError):
            bridge.reconcile_archive()
        self.assertTrue(dest.exists())

    def test_rt2_wrong_digest_and_nonprivate_permissions_stop(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        self.assertEqual(self._r4_worker(bridge.OUTBOX,name,self.bundle,"after-link").returncode,-9)
        pending=folder/(".pending-"+name)
        marker=bridge.strict_json(pending.read_bytes())
        altered=dict(marker)
        altered["sha256_bytes"]="0"*64
        pending.write_bytes(bridge.canonical(altered)+b"\n")
        pending.chmod(0o600)
        with self.assertRaises(bridge.BridgeError):
            bridge.reconcile_outbox()
        pending.write_bytes(bridge.canonical(marker)+b"\n")
        pending.chmod(0o600)
        (folder/name).chmod(0o644)
        with self.assertRaises(bridge.BridgeError):
            bridge.reconcile_outbox()
        (folder/name).chmod(0o600)
        self.assertEqual(bridge.reconcile_outbox(),["PUBBLICATO_CONFERMATO"])

    def test_rt2_extra_unattributable_hardlink_rejected(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        self.assertEqual(self._r4_worker(bridge.OUTBOX,name,self.bundle,"after-link").returncode,-9)
        extra=folder/"extraneous.link"
        os.link(folder/name,extra)
        self.assertEqual((folder/name).stat().st_nlink,3)
        with self.assertRaises(bridge.BridgeError):
            bridge.reconcile_outbox()
        extra.unlink()
        self.assertEqual(bridge.reconcile_outbox(),["PUBBLICATO_CONFERMATO"])

    def test_rt2_orphan_stage_not_deleted_by_glob(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        stray=folder/".kdd-stage-unrelated.tmp"
        stray.write_bytes(b"stray")
        stray.chmod(0o600)
        self.assertEqual(self._r4_worker(bridge.OUTBOX,name,self.bundle,"after-link").returncode,-9)
        self.assertEqual(bridge.reconcile_outbox(),["PUBBLICATO_CONFERMATO"])
        self.assertEqual(stray.read_bytes(),b"stray")

    def test_rt2_cleanup_error_does_not_mask_uncertain_fsync(self):
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        entry=self._r4_entry()
        version=bridge.digest(self.plan)
        genuine_sync=bridge._sync_dir
        count={"n":0}
        def broken_sync(directory):
            count["n"]+=1
            if count["n"]==2:
                raise OSError("injected fsync after final link")
            return genuine_sync(directory)
        with mock.patch.object(bridge,"_sync_dir",side_effect=broken_sync), \
             mock.patch.object(bridge.Path,"unlink",side_effect=OSError("cleanup failure")):
            with self.assertRaises(bridge.PublicationUncertain):
                bridge.exclusive_json(folder,version+".json",entry)
        self.assertTrue((folder/(".pending-"+version+".json")).exists())
        self.assertEqual(bridge.reconcile_archive(),["PUBBLICATO_CONFERMATO"])

    def test_rt2_successful_link_cleanup_failure_is_uncertain(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        with mock.patch.object(bridge.Path,"unlink",side_effect=OSError("cleanup failure")):
            with self.assertRaises(bridge.PublicationUncertain):
                bridge.exclusive_json(folder,name,self.bundle)
        self.assertTrue((folder/(".pending-"+name)).exists())
        self.assertEqual(bridge.reconcile_outbox(),["PUBBLICATO_CONFERMATO"])

    def test_rt2_pending_guard_prevents_new_revision_and_dashboard_safe(self):
        import serve
        self.persist_origin()
        version=bridge.digest(self.plan)
        folder=bridge.private_directory(bridge.ARCHIVE,create=True)
        self.assertEqual(self._r4_worker(bridge.ARCHIVE,version+".json",
                         self._r4_entry(),"after-link").returncode,-9)
        revised=copy.deepcopy(self.plan)
        revised["proposta_id"]="NEW-REVISION"
        revised["sostituisce_sha256"]=version
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(revised,self.bundle,bridge.digest(revised),
                                  "APPROVO_VERSIONE",now=T)
        shown=serve.with_controls("<h2>1 · Decisioni e posizioni</h2><p>Spot retained</p>")
        self.assertIn("STOP",shown)
        self.assertIn("/mercati/spot",shown)
        self.assertIn("Spot retained",shown)
        self.assertEqual(bridge.reconcile_archive(),["PUBBLICATO_CONFERMATO"])


    def test_rt2_two_independent_publishers_same_outbox_version(self):
        from concurrent.futures import ThreadPoolExecutor
        # The parent establishes the fixture's private home. Both independent
        # child processes then race on publishing (not on fixture bootstrapping).
        bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        with ThreadPoolExecutor(max_workers=2) as pool:
            procs=list(pool.map(lambda _:self._r4_worker(
                bridge.OUTBOX,name,self.bundle,"publish"),range(2)))
        self.assertTrue(all(x.returncode==0 for x in procs),[x.stderr for x in procs])
        self.assertEqual(sum("INSERITO" in x.stdout for x in procs),1)
        self.assertEqual(sum("GIA_PRESENTE" in x.stdout for x in procs),1)
        folder=bridge.private_directory(bridge.OUTBOX)
        self.assertEqual((folder/name).stat().st_nlink,1)
        self.assertEqual(bridge.verify_local_origin(self.bundle),bridge.digest(self.bundle))

    def test_rt2_postlink_exception_before_link_return_remains_uncertain(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        real_link=bridge.os.link
        def linked_then_error(*args,**kwargs):
            real_link(*args,**kwargs)
            raise OSError("synthetic error after link syscall succeeded")
        with mock.patch.object(bridge.os,"link",side_effect=linked_then_error):
            with self.assertRaises(bridge.PublicationUncertain):
                bridge.exclusive_json(folder,name,self.bundle)
        self.assertEqual((folder/name).stat().st_nlink,2)
        self.assertEqual(bridge.reconcile_outbox(),["PUBBLICATO_CONFERMATO"])
        self.assertEqual(bridge.exclusive_json(folder,name,self.bundle),"GIA_PRESENTE")


    # RT3: the original module is imported by separate children. A killed
    # child never executes finally; the next child reads persistent Linux inodes.
    def test_rt3_a_four_consecutive_cancelled_attempts_same_version_both_areas(self):
        for area in (bridge.OUTBOX, bridge.ARCHIVE):
            with self.subTest(area=area):
                version = bridge.digest(self.bundle if area==bridge.OUTBOX else self.plan)
                obj = self.bundle if area==bridge.OUTBOX else self._r4_entry()
                name = version + ".json"
                folder = bridge.private_directory(area, create=True)
                records = []
                for attempt_number in range(4):
                    killed = self._r4_worker(area,name,obj,"before-link")
                    self.assertEqual(killed.returncode,-9,killed.stderr)
                    self.assertTrue((folder/(".pending-"+name)).is_file())
                    self.assertFalse((folder/name).exists())
                    second = self._r4_worker(area,name,obj,"recover")
                    self.assertEqual(second.returncode,0,second.stderr)
                    self.assertIn("NON_PUBBLICATO",second.stdout)
                    self.assertEqual(bridge.reconcile_directory(area),[])
                    marks = sorted(folder.glob(".cancelled-"+version+"-*.json"))
                    self.assertEqual(len(marks),attempt_number+1)
                    self.assertTrue(set(records).issubset(set(marks)))
                    records = marks
                    parsed=[bridge.strict_json(m.read_bytes()) for m in records]
                    self.assertEqual(len({m["attempt_id"] for m in parsed}),attempt_number+1)
                    for m in parsed:
                        self.assertEqual(m["schema"],bridge.PENDING_SCHEMA_R5)
                        self.assertEqual(m["filename"],name)
                        self.assertTrue(m["stage"].startswith(".kdd-stage-"+m["attempt_id"]+"-"))
                        self.assertFalse((folder/m["stage"]).exists())
                third = self._r4_worker(area,name,obj,"publish")
                self.assertEqual(third.returncode,0,third.stderr)
                self.assertIn("INSERITO",third.stdout)
                self.assertEqual(len(list(folder.glob(".cancelled-"+version+"-*.json"))),4)
                self.assertEqual(len(list(folder.glob(".resolved-"+version+"-*.json"))),1)
                final=folder/name
                self.assertEqual(final.stat().st_nlink,1)
                if area==bridge.ARCHIVE:
                    self.persist_origin()
                    self.assertEqual(len(bridge.load_archive()),1)
                    self.assertEqual(bridge.approved_import(self.plan,self.bundle,version,
                                     "APPROVO_VERSIONE",now=T)["stato"],"GIA_PRESENTE")
                else:
                    self.assertEqual(bridge.verify_local_origin(self.bundle),version)
                    self.assertEqual(bridge.exclusive_json(folder,name,self.bundle),"GIA_PRESENTE")
                self.assertEqual(len(list(folder.glob(".cancelled-"+version+"-*.json"))),4)

    def test_rt3_a_legacy_forensic_marker_remains_separate_from_new_attempt(self):
        area=bridge.ARCHIVE
        version=bridge.digest(self.plan)
        name=version+".json"
        folder=bridge.private_directory(area,create=True)
        p=self._r4_worker(area,name,self._r4_entry(),"before-link")
        self.assertEqual(p.returncode,-9,p.stderr)
        journal=folder/(".pending-"+name)
        legacy=bridge.strict_json(journal.read_bytes())
        legacy.pop("attempt_id")
        legacy["schema"]=bridge.PENDING_SCHEMA_R4
        journal.write_bytes(bridge.canonical(legacy)+b"\n")
        journal.chmod(0o600)
        self.assertEqual(bridge.reconcile_archive(),["NON_PUBBLICATO"])
        historic=folder/(".cancelled-"+name)
        self.assertTrue(historic.is_file())
        historic_bytes=historic.read_bytes()
        p=self._r4_worker(area,name,self._r4_entry(),"before-link")
        self.assertEqual(p.returncode,-9,p.stderr)
        self.assertEqual(bridge.reconcile_archive(),["NON_PUBBLICATO"])
        self.assertEqual(historic.read_bytes(),historic_bytes)
        self.assertEqual(len(list(folder.glob(".cancelled-"+version+"-*.json"))),1)
        self.assertEqual(bridge.load_archive(),{})

    def test_rt3_a_changed_attempt_id_is_rejected_without_cleanup(self):
        folder=bridge.private_directory(bridge.OUTBOX,create=True)
        name=bridge.digest(self.bundle)+".json"
        killed=self._r4_worker(bridge.OUTBOX,name,self.bundle,"before-link")
        self.assertEqual(killed.returncode,-9,killed.stderr)
        journal=folder/(".pending-"+name)
        marker=bridge.strict_json(journal.read_bytes())
        saved_stage=folder/marker["stage"]
        marker["attempt_id"]="0"*32 if marker["attempt_id"]!="0"*32 else "1"*32
        journal.write_bytes(bridge.canonical(marker)+b"\n")
        journal.chmod(0o600)
        with self.assertRaisesRegex(bridge.BridgeError,"Identita tentativo"):
            bridge.reconcile_outbox()
        self.assertTrue(journal.is_file())
        self.assertTrue(saved_stage.exists())
        self.assertFalse((folder/name).exists())

    def test_rt3_b_dangling_and_live_symlink_journals_fail_closed(self):
        for area in (bridge.ARCHIVE, bridge.OUTBOX):
            for dangling in (True,False):
                with self.subTest(area=area,dangling=dangling):
                    # Each symlink case owns a fresh, independent private
                    # fixture: never reuse a successful outbox from RT3-A.
                    with mock.patch.object(bridge,"PRIVATE_ROOT",
                           self.home/("rt3-symlink-"+area+"-"+str(dangling))):
                        folder=bridge.private_directory(area,create=True)
                        obj=self.bundle if area==bridge.OUTBOX else self._r4_entry()
                        name=(bridge.digest(self.bundle) if area==bridge.OUTBOX
                              else bridge.digest(self.plan))+".json"
                        pending=folder/(".pending-"+name)
                        target=self.home/("no-such-target" if dangling else "live-target")
                        if not dangling:
                            target.write_text('{"legitimate":false}')
                            target.chmod(0o600)
                        pending.symlink_to(target)
                        with self.assertRaises(bridge.BridgeError):
                            bridge.reconcile_directory(area)
                        self.assertTrue(pending.is_symlink())
                        self.assertFalse((folder/name).exists())
                        with self.assertRaises(bridge.BridgeError):
                            bridge.exclusive_json(folder,name,obj)
                        self.assertTrue(pending.is_symlink())
                        if area==bridge.OUTBOX:
                            with self.assertRaises(bridge.BridgeError):
                                bridge.verify_local_origin(self.bundle)
                        else:
                            self.persist_origin()
                            with self.assertRaises(bridge.BridgeError):
                                bridge.approved_import(self.plan,self.bundle,
                                    bridge.digest(self.plan),"APPROVO_VERSIONE",now=T)
                            self.assertIn("STOP",bridge.approved_html())
                        pending.unlink()
                        if not dangling:
                            target.unlink()
                        self.assertEqual(bridge.reconcile_directory(area),[])

    def _r5_mark_worker(self,area,name,phase):
        import subprocess
        import sys
        script=r"""
import os,signal,sys
from pathlib import Path
from scripts import kdd_bridge_g2 as bridge
bridge.PRIVATE_ROOT=Path(sys.argv[1])
area,name,phase=sys.argv[2:]
old_rename=os.rename
def kill_on_marker(*args,**kwargs):
    if phase=="pre-mark":
        os.kill(os.getpid(),signal.SIGKILL)
    result=old_rename(*args,**kwargs)
    if phase=="post-mark":
        os.kill(os.getpid(),signal.SIGKILL)
    return result
os.rename=kill_on_marker
bridge.reconcile_directory(area)
"""
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(bridge.__file__).resolve().parents[1])
        return subprocess.run([sys.executable,"-B","-c",script,str(self.private),
                               area,name,phase],env=env,cwd=env["PYTHONPATH"],
                              text=True,capture_output=True,timeout=18)

    def test_rt3_a_real_sigkill_before_and_after_forensic_marking(self):
        for area in (bridge.ARCHIVE,bridge.OUTBOX):
            for linked in (False,True):
                for point in ("pre-mark","post-mark"):
                    with self.subTest(area=area,linked=linked,point=point):
                        obj=self.bundle if area==bridge.OUTBOX else self._r4_entry()
                        ver=bridge.digest(self.bundle) if area==bridge.OUTBOX else bridge.digest(self.plan)
                        folder=bridge.private_directory(area,create=True)
                        name=ver+".json"
                        # Each subtest uses a newly named document? The same
                        # version may already exist after a previous linked test.
                        # Use one isolated private-root per phase while keeping
                        # the original module and separate child processes.
                        local_root=self.private
                        isolated=self.home/(area+str(linked)+point)
                        with mock.patch.object(bridge,"PRIVATE_ROOT",isolated), \
                             mock.patch.object(self,"private",isolated):
                            if linked:
                                killed=self._r4_worker(area,name,obj,"after-link")
                            else:
                                killed=self._r4_worker(area,name,obj,"before-link")
                            self.assertEqual(killed.returncode,-9,killed.stderr)
                            before=self._r5_mark_worker(area,name,point)
                            self.assertEqual(before.returncode,-9,before.stderr)
                            pending=bridge.private_directory(area)/(".pending-"+name)
                            if point=="pre-mark":
                                self.assertTrue(pending.is_file())
                                self.assertEqual(bridge.reconcile_directory(area),
                                    ["PUBBLICATO_CONFERMATO" if linked else "NON_PUBBLICATO"])
                            else:
                                self.assertFalse(pending.exists())
                                self.assertEqual(bridge.reconcile_directory(area),[])
                            prefix=".resolved-" if linked else ".cancelled-"
                            marks=list(bridge.private_directory(area).glob(prefix+ver+"-*.json"))
                            self.assertEqual(len(marks),1)
                            self.assertEqual(bridge.reconcile_directory(area),[])
                            if linked:
                                self.assertEqual((bridge.private_directory(area)/name).stat().st_nlink,1)
                            else:
                                self.assertFalse((bridge.private_directory(area)/name).exists())


    def test_rt3_a_forced_attempt_collision_preserves_prior_and_current_evidence(self):
        for area in (bridge.ARCHIVE,bridge.OUTBOX):
            with self.subTest(area=area):
                isolated=self.home/("rt3-collision-"+area)
                with mock.patch.object(bridge,"PRIVATE_ROOT",isolated), \
                     mock.patch.object(self,"private",isolated):
                    folder=bridge.private_directory(area,create=True)
                    version=bridge.digest(self.bundle) if area==bridge.OUTBOX else bridge.digest(self.plan)
                    doc=self.bundle if area==bridge.OUTBOX else self._r4_entry()
                    name=version+".json"
                    first=self._r4_worker(area,name,doc,"before-link")
                    self.assertEqual(first.returncode,-9,first.stderr)
                    journal=folder/(".pending-"+name)
                    old_marker=bridge.strict_json(journal.read_bytes())
                    self.assertEqual(bridge.reconcile_directory(area),["NON_PUBBLICATO"])
                    historic=folder/(".cancelled-"+version+"-"+old_marker["attempt_id"]+".json")
                    original_bytes=historic.read_bytes()
                    second=self._r4_worker(area,name,doc,"before-link")
                    self.assertEqual(second.returncode,-9,second.stderr)
                    journal=folder/(".pending-"+name)
                    current=bridge.strict_json(journal.read_bytes())
                    self.assertNotEqual(current["attempt_id"],old_marker["attempt_id"])
                    current_stage=folder/current["stage"]
                    forced_name=".kdd-stage-"+old_marker["attempt_id"]+"-forced.tmp"
                    forced_stage=folder/forced_name
                    current_stage.rename(forced_stage)
                    current["attempt_id"]=old_marker["attempt_id"]
                    current["stage"]=forced_name
                    journal.write_bytes(bridge.canonical(current)+b"\n")
                    journal.chmod(0o600)
                    with self.assertRaisesRegex(bridge.BridgeError,"Marcatura forense"):
                        bridge.reconcile_directory(area)
                    self.assertEqual(historic.read_bytes(),original_bytes)
                    self.assertTrue(journal.is_file())
                    self.assertTrue(forced_stage.is_file())
                    self.assertFalse((folder/name).exists())
                    self.assertEqual(len(list(folder.glob(".cancelled-"+version+"-*.json"))),1)


if __name__=="__main__":
    unittest.main()
