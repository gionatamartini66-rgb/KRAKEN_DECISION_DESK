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
        from contextlib import redirect_stdout
        import io
        inbox=bridge.private_directory(bridge.INBOX,create=True)
        (inbox/"proposta_portafoglio.json").write_text(json.dumps(self.plan))
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
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
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(forged))
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
        (inbox/"pacchetto_riferimento.json").write_text(json.dumps(self.bundle))
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
        real_fsync = bridge.os.fsync
        count = {"n":0}
        def fail_directory(fd):
            count["n"] += 1
            if count["n"] == 2:
                raise OSError("synthetic crash during directory fsync")
            return real_fsync(fd)
        with mock.patch.object(bridge.os, "fsync", side_effect=fail_directory):
            with self.assertRaises(OSError):
                bridge.exclusive_json(folder, name, entry)
        self.assertEqual(bridge.strict_json((folder/name).read_bytes()), entry)
        self.assertEqual(bridge.exclusive_json(folder, name, entry), "GIA_PRESENTE")
        with self.assertRaises(bridge.BridgeError):
            bridge.exclusive_json(folder, name, {"probe":"mutated"})

    def test_r2_orphan_stage_inert_archive_recoverable(self):
        folder = bridge.private_directory(bridge.ARCHIVE, create=True)
        (folder/".kdd-stage-interrupted.tmp").write_bytes(b'{"truncated":')
        (folder/".kdd-stage-interrupted.tmp").chmod(0o600)
        self.assertEqual(bridge.load_archive(), {})
        version = bridge.digest(self.plan)
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,version,"APPROVO_VERSIONE",now=T)["stato"],"INSERITO")
        self.assertEqual(len(bridge.load_archive()),1)

    def test_r2_concurrent_same_version_exactly_once(self):
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


if __name__=="__main__":
    unittest.main()
