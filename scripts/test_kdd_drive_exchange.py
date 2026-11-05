"""Real bridge + user-interface handoff tests; no Drive/network/phone involved."""
import copy
import datetime as dt
import html
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import kdd_drive_exchange as exchange
from scripts import kdd_bridge_g2 as bridge
from scripts import test_kdd_bridge_g2 as fixtures


class DriveUIHandoffTests(unittest.TestCase):
    def setUp(self):
        original=fixtures.BridgeG2Tests(
            "test_01_real_original_producer_retains_all_rows_and_eur_provenance")
        original.setUp()
        self.addCleanup(original.doCleanups)
        self.original=original
        # Explicit first-install enrollment of this freshly isolated synthetic
        # fixture; production never auto-enrolls or migrates existing history.
        if hasattr(exchange, "initialize_decision_continuity"):
            exchange.initialize_decision_continuity(
                mode="NEW", acknowledgement="INIZIALIZZO_NUOVO_STORICO")
        self.sync=Path(tempfile.mkdtemp(prefix="kdd-drive-ui-",dir=original.home))
        p=mock.patch.object(exchange,"EXCHANGE_ROOT",self.sync)
        p.start()
        self.addCleanup(p.stop)

    def test_gpt_drive_roundtrip_with_persisted_original_and_manual_consent(self):
        with mock.patch.object(bridge,"prepare",return_value=self.original.bundle):
            exported=exchange.prepare_export()
        self.assertRegex(exported,r"kdd_handoff_[0-9a-f]{64}\.json")
        out=(self.sync/exported)
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes(),bridge.canonical(self.original.bundle)+b"\n")
        self.assertEqual(bridge.verify_local_origin(self.original.bundle),
                         bridge.digest(self.original.bundle))
        self.assertIn("Nessuna proposta",exchange.render_page("TOKEN"))
        data=bridge.canonical(self.original.plan)+b"\n"
        sha=exchange.receive(data)
        self.assertEqual(sha,bridge.digest(self.original.plan))
        self.assertIn("NON APPROVATA",exchange.render_page("TOKEN"))
        self.assertEqual(bridge.load_archive(),{})
        with self.assertRaisesRegex(bridge.BridgeError,"Versione diversa"):
            exchange.confirm("0"*64)
        self.assertEqual(bridge.load_archive(),{})
        self.assertEqual(exchange.confirm(sha)["stato"],"INSERITO")
        self.assertIn("ADA",bridge.approved_html())
        self.assertEqual(exchange.confirm(sha)["stato"],"GIA_PRESENTE")

    def test_incoming_is_not_self_attesting_and_rejects_mutation(self):
        with self.assertRaises(bridge.BridgeError):
            exchange.receive(bridge.canonical(self.original.plan))
        self.original.persist_origin()
        mutated=copy.deepcopy(self.original.plan)
        mutated["posizioni"][0]["token"]="MISMATCH"
        with self.assertRaises(bridge.BridgeError):
            exchange.receive(bridge.canonical(mutated))
        self.assertIsNone(exchange.pending())
        self.assertEqual(bridge.load_archive(),{})

    def test_html_escapes_proposal_and_does_not_approve_on_upload(self):
        self.original.persist_origin()
        changed=copy.deepcopy(self.original.plan)
        changed["scenario"]="<script>unsafe()</script>"
        sha=exchange.receive(bridge.canonical(changed))
        page=exchange.render_page("TOKEN")
        self.assertNotIn("<script>unsafe()",page)
        self.assertIn(html.escape(changed["scenario"],quote=True),page)
        self.assertIn(sha,page)
        self.assertEqual(bridge.load_archive(),{})

    def test_export_failure_does_not_claim_drive_delivery(self):
        missing=self.original.home/"folder-not-configured"
        with mock.patch.object(exchange,"EXCHANGE_ROOT",missing):
            with mock.patch.object(bridge,"prepare",return_value=self.original.bundle):
                with self.assertRaisesRegex(bridge.BridgeError,"non disponibile"):
                    exchange.prepare_export()
        # Original persisted, but no shared Drive delivery was claimed.
        self.assertEqual(bridge.verify_local_origin(self.original.bundle),
                         bridge.digest(self.original.bundle))

    def test_bad_json_cannot_replace_valid_pending(self):
        self.original.persist_origin()
        sha=exchange.receive(bridge.canonical(self.original.plan))
        with self.assertRaises(bridge.BridgeError):
            exchange.receive(b'{"schema":"bad"')
        self.assertEqual(bridge.digest(exchange.pending()[0]),sha)

    def test_actual_local_http_get_and_post_drive_ui(self):
        """Exercise the real serve.Handler, not only direct helper calls."""
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve
        server=ThreadingHTTPServer(("127.0.0.1",0),serve.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(thread.join,1)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def call(method,path,body=None,with_token=True):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            headers={"Host":"127.0.0.1:8765"}
            if with_token:
                headers["X-KDD-Token"]=serve.TOKEN
            conn.request(method,path,body=body,headers=headers)
            resp=conn.getresponse()
            result=(resp.status,resp.read().decode("utf-8"))
            conn.close()
            return result
        state,page=call("GET","/gpt")
        self.assertEqual(state,200)
        self.assertIn("Apri la proposta da Drive",page)
        with mock.patch.object(bridge,"prepare",return_value=self.original.bundle):
            status,message=call("POST","/gpt/prepara",b"",False)
            self.assertEqual(status,403)
            status,message=call("POST","/gpt/prepara",b"")
            self.assertEqual(status,200,message)
        status,message=call("POST","/gpt/ricevi",bridge.canonical(self.original.plan))
        self.assertEqual(status,200,message)
        self.assertIn("NON approvata",message)
        state,page=call("GET","/gpt")
        self.assertIn("ADA",page)
        self.assertIn("NON APPROVATA",page)
        self.assertEqual(bridge.load_archive(),{})
        payload=json.dumps({"sha256":bridge.digest(self.original.plan)}).encode()
        state,message=call("POST","/gpt/conferma",payload)
        self.assertEqual(state,200,message)
        self.assertEqual(len(bridge.load_archive()),1)

    def test_foldersync_inbound_home_preview_without_approval(self):
        self.original.persist_origin()
        source=self.sync/exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(self.original.plan)+b"\n")
        import serve
        with mock.patch.object(serve,"TOKEN","SYNTHETIC"):
            home=serve.decision_home()
        self.assertIn("IN ATTESA DI DECISIONE",home)
        self.assertIn("ADA",home)
        self.assertIn(bridge.digest(self.original.plan),home)
        self.assertEqual(bridge.load_archive(),{})
        self.assertEqual(bridge.digest(exchange.pending()[0]),bridge.digest(self.original.plan))

    def test_foldersync_invalid_input_keeps_previous_pending(self):
        self.original.persist_origin()
        old=exchange.receive(bridge.canonical(self.original.plan))
        (self.sync/exchange.INCOMING_NAME).write_bytes(b'{"schema":"invalid"}')
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_synced()
        self.assertEqual(bridge.digest(exchange.pending()[0]),old)
        self.assertIn("STOP",__import__("serve").decision_home())

    def test_foldersync_symlink_never_imported(self):
        self.original.persist_origin()
        target=self.sync/"outside.json"
        target.write_bytes(bridge.canonical(self.original.plan))
        (self.sync/exchange.INCOMING_NAME).symlink_to(target)
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_synced()
        self.assertIsNone(exchange.pending())

    def test_decision_events_require_explicit_author_and_approval(self):
        self.original.persist_origin()
        sha=exchange.receive(bridge.canonical(self.original.plan))
        payload=lambda state,note: bridge.canonical({"sha256":sha,"stato":state,"nota":note})
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload("ESECUZIONE_DICHIARATA","Dichiarazione"))
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload("RIFIUTATA",""))
        self.assertEqual(exchange.record_decision(payload("RINVIATA","Attendere")), "INSERITO")
        with self.assertRaises(bridge.BridgeError):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(),{})
        self.assertIn("RINVIATA",exchange.render_page("TOKEN"))

    def test_approved_version_has_no_second_approval_and_review_is_dated(self):
        self.original.persist_origin()
        sha=exchange.receive(bridge.canonical(self.original.plan))
        self.assertEqual(exchange.confirm(sha)["stato"],"INSERITO")
        page=exchange.render_page("TOKEN")
        self.assertIn("VERSIONE APPROVATA",page)
        self.assertNotIn("Confermo questa versione nel KDD</button>",page)
        payload=lambda state,note: bridge.canonical({"sha256":sha,"stato":state,"nota":note})
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload("RISULTATO_VERIFICATO","Riscontro"))
        self.assertEqual(exchange.record_decision(payload("ESECUZIONE_DICHIARATA","Dichiarazione manuale non verificata")),"INSERITO")
        self.assertEqual(exchange.record_decision(payload("RIESAME","Nuova rilevazione da confrontare")),"INSERITO")
        self.assertEqual(len(exchange.decision_history()),2)
        self.assertEqual(len(bridge.load_archive()),1)

    def test_handle_rejects_implicit_consent(self):
        self.original.persist_origin()
        self.assertIn("NON approvata",exchange.handle("ricevi",bridge.canonical(self.original.plan)))
        with self.assertRaises(bridge.BridgeError):
            exchange.handle("conferma",json.dumps({"sha256":"0"*64}).encode())
        with self.assertRaises(bridge.BridgeError):
            exchange.handle("conferma",json.dumps({"sha256":bridge.digest(self.original.plan),
                                                 "consent":"APPROVO_VERSIONE"}).encode())
        self.assertEqual(bridge.load_archive(),{})


    def _candidate(self, name, parent=None):
        plan = copy.deepcopy(self.original.plan)
        plan["proposta_id"] = name
        plan["sostituisce_sha256"] = parent
        return plan

    def test_a_deferred_b_imported_stale_a_cannot_overwrite_even_after_restart(self):
        self.original.persist_origin()
        a = self._candidate("A")
        b = self._candidate("B")
        a_sha = exchange.receive(bridge.canonical(a))
        self.assertEqual(exchange.receive(bridge.canonical(a)), a_sha)
        with self.assertRaisesRegex(bridge.BridgeError, "in attesa"):
            exchange.receive(bridge.canonical(b))
        self.assertEqual(exchange.record_decision(bridge.canonical(
            {"sha256": a_sha, "stato": "RINVIATA", "nota": "Riesaminare"})), "INSERITO")
        self.assertEqual(exchange.receive(bridge.canonical(b)), bridge.digest(b))
        events = exchange.decision_history()
        self.assertEqual(events[0]["proposta"]["posizioni"], a["posizioni"])
        self.assertEqual(events[0]["proposta"]["snapshot_utc"], a["snapshot_utc"])
        source = self.sync / exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(a) + b"\n")
        with mock.patch.object(bridge, "_LOCAL_ORIGINS", set()):
            self.assertEqual(exchange.receive_synced(), a_sha)
            self.assertEqual(exchange.pending()[0], b)
            self.assertEqual(exchange.confirm(bridge.digest(b))["stato"], "INSERITO")
            self.assertEqual(exchange.pending()[0], b)
            self.assertEqual(len(exchange.decision_history()), 1)
        self.assertEqual(len(bridge.load_archive()), 1)

    def test_approved_a_requires_exact_parent_for_b_and_replay_is_inert(self):
        self.original.persist_origin()
        a = self._candidate("A")
        a_sha = exchange.receive(bridge.canonical(a))
        exchange.confirm(a_sha)
        b_unlinked = self._candidate("B-UNLINKED")
        with self.assertRaisesRegex(bridge.BridgeError, "Revisione"):
            exchange.receive(bridge.canonical(b_unlinked))
        self.assertEqual(exchange.pending()[0], a)
        b = self._candidate("B", a_sha)
        b_sha = exchange.receive(bridge.canonical(b))
        self.assertEqual(exchange.receive_synced(), None)
        (self.sync / exchange.INCOMING_NAME).write_bytes(bridge.canonical(a))
        self.assertEqual(exchange.receive_synced(), a_sha)
        self.assertEqual(exchange.pending()[0], b)
        self.assertEqual(exchange.confirm(b_sha)["stato"], "INSERITO")
        self.assertEqual(len(bridge.load_archive()), 2)
        self.assertEqual(exchange._approved_head(bridge.load_archive()), b_sha)

    def test_late_stale_replay_of_decided_a_does_not_hide_current_b(self):
        self.original.persist_origin()
        a = self._candidate("A")
        b = self._candidate("B")
        sha_a = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical(
            {"sha256": sha_a, "stato": "RIFIUTATA", "nota": "Superata"}))
        exchange.receive(bridge.canonical(b))
        (self.sync / exchange.INCOMING_NAME).write_bytes(bridge.canonical(a))
        real_validate = exchange.validate_raw
        def expire_only_old(raw):
            if bridge.strict_json(raw)["proposta_id"] == "A":
                raise bridge.BridgeError("Fotografia A scaduta")
            return real_validate(raw)
        with mock.patch.object(exchange, "validate_raw", side_effect=expire_only_old):
            self.assertEqual(exchange.receive_synced(), sha_a)
        self.assertEqual(exchange.pending()[0], b)
        self.assertEqual(len(exchange.decision_history()), 1)

    def test_deferred_parent_is_not_approved_parent(self):
        self.original.persist_origin()
        a = self._candidate("A")
        a_sha = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical(
            {"sha256": a_sha, "stato": "RIFIUTATA", "nota": "Motivazione"}))
        b = self._candidate("B", a_sha)
        with self.assertRaisesRegex(bridge.BridgeError, "Revisione"):
            exchange.receive(bridge.canonical(b))
        self.assertEqual(exchange.pending()[0], a)

    def test_termux_no_os_link_and_interrupted_event_stage_is_inert(self):
        self.original.persist_origin()
        a = self._candidate("A")
        a_sha = exchange.receive(bridge.canonical(a))
        payload = bridge.canonical({"sha256": a_sha, "stato": "RIFIUTATA",
                                    "nota": "Rifiuto manuale"})
        with mock.patch.object(exchange.os, "link", side_effect=AssertionError("os.link forbidden"),
                               create=True):
            self.assertEqual(exchange.record_decision(payload), "INSERITO")
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        interrupted = folder / ".kdd-event-interrupted.tmp"
        interrupted.write_bytes(b'{"partial":')
        interrupted.chmod(0o600)
        history = exchange.decision_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["proposta"], a)
        with self.assertRaisesRegex(bridge.BridgeError, "già"):
            exchange.record_decision(payload)
        page = exchange.render_page("TOKEN")
        self.assertIn("RIFIUTATA", page)
        self.assertIn(a["snapshot_utc"], page)
        self.assertEqual(len(exchange.decision_history()), 1)


    def _write_existing_event(self, sha, state, note, timestamp):
        folder = bridge.ensure_dir(
            bridge.private_directory(bridge.INBOX, create=True) / exchange.DECISION_EVENTS)
        row = {"versione_sha256": sha, "stato": state, "nota": note,
               "creato_utc": timestamp}
        path = folder / (bridge.digest(row) + ".json")
        # Reproduce the existing *committed* historical record with its
        # durability witness, rather than forging an unregistered event.
        exchange._write_witness("e", bridge.digest(row), row)
        path.write_bytes(bridge.canonical(row) + b"\n")
        path.chmod(0o600)
        return row

    def test_rt26_01_declared_result_never_certifies_market_and_legacy_remains_readable(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        payload = lambda state, note: bridge.canonical(
            {"sha256": sha, "stato": state, "nota": note})
        exchange.record_decision(payload("RIESAME", "Ho consultato il quadro"))
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload("RISULTATO_VERIFICATO", "Prova non attestata"))
        self.assertEqual(exchange.record_decision(
            payload("RISCONTRO_DICHIARATO", "Riferisco un esito")),"INSERITO")
        legacy = self._write_existing_event(
            sha, "RISULTATO_VERIFICATO", "Nota storica senza prova allegata",
            "2026-01-01T11:00:00+00:00")
        self.assertIn(legacy, exchange.decision_history())
        page = exchange.render_page("TOKEN")
        self.assertIn("RISCONTRO STORICO DICHIARATO", page)
        self.assertIn("RISCONTRO DICHIARATO DALL", page)
        self.assertIn("verifica su dati non attestata", page)
        self.assertNotIn("<option value='RISULTATO_VERIFICATO'>", page)
        self.assertNotIn("RISULTATO_VERIFICATO ·", page)

    def test_rt26_02_general_decision_not_misattributed_to_each_token(self):
        import serve
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        created = (now - dt.timedelta(minutes=5)).isoformat()
        expiry = (now + dt.timedelta(days=1)).isoformat()
        records = [
            {"token": "PORTAFOGLIO", "scelta": "RIVEDERE", "motivo": "Quadro generale",
             "creata_utc": created, "scade_utc": expiry},
            {"token": "BTC", "scelta": "ALLEGGERIRE", "motivo": "Scelta specifica",
             "creata_utc": now.isoformat(), "scade_utc": expiry},
        ]
        report = {
            "rilevazione_utc": now.isoformat(), "stato_totale": "DISPONIBILE",
            "totale_stimato_eur": "dato di prova", "schede_v02": [],
            "posizioni": [
                {"token": token, "decisione": serve.desk.decision_state(token, records, now),
                 "valore_eur": "n.d.", "note": []}
                for token in ("ADA", "BTC")
            ] + [{"token":"ETH", "decisione":"Testo non riconciliabile",
                  "valore_eur":"n.d.", "note":[]}],
        }
        with mock.patch.object(serve.desk, "load", return_value=report), \
             mock.patch.object(serve.desk, "load_decisions", return_value=records):
            html_home = serve.decision_home()
        self.assertIn("Criterio generale PORTAFOGLIO applicato alla posizione", html_home)
        self.assertIn("Decisione specifica del token da decisioni.jsonl", html_home)
        self.assertIn("origine non accertata", html_home)
        self.assertNotIn("decisione registrata autore", html_home)

    def test_rt26_03_corrupt_report_does_not_disable_original_home_or_http(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve
        # Real on-disk JSON parse path; valid original HTML stays untouched.
        (self.sync / "ultimo_report.json").write_text('{"posizioni":', encoding="utf-8")
        (self.sync / "cruscotto.html").write_text(
            "<html><body><nav>ORIGINALE_PATRIMONIO_SPOT_GRAFICI</nav>"
            "<h2>1 · Decisioni e posizioni</h2></body></html>", encoding="utf-8")
        with mock.patch.object(serve.desk, "DIR", self.sync):
            server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/", headers={"Host":"127.0.0.1:8765"})
                resp = conn.getresponse()
                body = resp.read().decode("utf-8")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            self.assertEqual(resp.status, 200)
            self.assertIn("ORIGINALE_PATRIMONIO_SPOT_GRAFICI", body)
            self.assertIn("Aggiorna dati ora", body)
            self.assertIn("/mercati/spot", body)
            self.assertIn("report assente, incompleto o non leggibile", body)
            # Also isolate unforeseen failures in the added overlay only.
            with mock.patch.object(serve, "decision_home", side_effect=RuntimeError("overlay")):
                fallback = serve.with_controls(
                    "<h2>1 · Decisioni e posizioni</h2><p>STORICO ORIGINALE</p>")
            self.assertIn("STORICO ORIGINALE", fallback)
            self.assertIn("Riepilogo aggiunto non disponibile", fallback)
            self.assertIn("Aggiorna dati ora", fallback)

    def test_rt26_04_legacy_second_tie_has_no_invented_last_event(self):
        import serve
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        self._write_existing_event(sha,"RIESAME","Primo record, ordine ignoto",timestamp)
        self._write_existing_event(sha,"RISULTATO_VERIFICATO","Secondo record, ordine ignoto",timestamp)
        history = exchange.decision_history()
        self.assertEqual(len(history),2)
        recent, ambiguous = exchange.latest_events(history)
        self.assertTrue(ambiguous)
        self.assertEqual(len(recent),2)
        self.assertEqual(len(exchange.uncertain_event_seconds(history)),1)
        page = exchange.render_page("TOKEN")
        self.assertIn("ordine nel secondo non documentato",page)
        home = serve.decision_home()
        self.assertIn("ordine reciproco non documentato",home)
        self.assertIn("Primo record, ordine ignoto",home)
        self.assertIn("Secondo record, ordine ignoto",home)
        self.assertNotIn("Ultimo evento autore",home)

    def _postflight_home_with_report(self):
        """Use a physically present, well-formed report and genuine home rendering."""
        import serve
        report = {
            "rilevazione_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stato_totale": "PARZIALE",
            "totale_stimato_eur": None,
            "posizioni": [
                {"token": row["token"], "quantita": row["quantita_spot"],
                 "valore_eur": None, "note": [], "decisione": "NESSUNA DECISIONE"}
                for row in self.original.bundle["packet"]["patrimonio"]["posizioni"]
            ],
            "schede_v02": []
        }
        (self.sync / "ultimo_report.json").write_text(
            json.dumps(report), encoding="utf-8")
        source = ("<!doctype html><html><body><header><h1>KDD</h1></header>"
                  "<h2>1 · Decisioni e posizioni</h2><p>ORIGINALE LEGACY</p>"
                  "<h2>2 · Candidati da valutare</h2><p>SCANNER</p>"
                  "<h2>3 · Macroeconomia e geopolitica</h2></body></html>")
        with mock.patch.object(serve.desk, "DIR", self.sync):
            direct = serve.decision_home()
            integrated = serve.with_controls(source)
        self.assertIn("id='kdd-decisioni'", integrated)
        self.assertIn("ORIGINALE LEGACY", integrated)
        return direct, integrated

    def test_postflight_legacy_second_tie_with_present_report(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        second = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        self._write_existing_event(sha, "RIESAME", "RIESAME a tempo indistinguibile", second)
        self._write_existing_event(sha, "RISULTATO_VERIFICATO",
                                   "RISULTATO legacy solo dichiarato", second)
        before = exchange.decision_history()
        recent, ambiguous = exchange.latest_events(before)
        self.assertTrue(ambiguous)
        self.assertEqual(len(recent), 2)
        for page in self._postflight_home_with_report():
            self.assertIn("ordine reciproco non documentato", page)
            self.assertIn("RIESAME a tempo indistinguibile", page)
            self.assertIn("RISULTATO legacy solo dichiarato", page)
            self.assertIn("RISCONTRO STORICO DICHIARATO", page)
            self.assertIn("verifica su dati non attestata", page)
            self.assertNotIn("Ultimo evento autore", page)
            self.assertNotIn("ORDINE ESEGUITO", page)
        self.assertEqual(exchange.decision_history(), before)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)

    def test_postflight_microsecond_events_are_ordered_and_visible_with_report(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        base = dt.datetime.now(dt.timezone.utc).replace(microsecond=100000)
        self._write_existing_event(sha, "RIESAME", "Riesame microsecondi", base.isoformat(timespec="microseconds"))
        self._write_existing_event(sha, "RISCONTRO_DICHIARATO", "Riscontro microsecondi",
                                   (base + dt.timedelta(microseconds=1)).isoformat(timespec="microseconds"))
        for page in self._postflight_home_with_report():
            self.assertIn("Riesame microsecondi", page)
            self.assertIn("Riscontro microsecondi", page)
            self.assertLess(page.index("Riesame microsecondi"),
                            page.index("Riscontro microsecondi"))
            self.assertNotIn("ordine reciproco non documentato", page)
            self.assertIn("RISCONTRO DICHIARATO DALL", page)
            self.assertNotIn("ORDINE ESEGUITO", page)

    def test_postflight_events_are_scoped_to_exact_proposal_version(self):
        self.original.persist_origin()
        sha_a = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha_a)
        self._write_existing_event(
            sha_a, "RIESAME", "SOLO VERSIONE A: riesame storico",
            dt.datetime.now(dt.timezone.utc).isoformat())
        old_page, old_integrated = self._postflight_home_with_report()
        self.assertIn("SOLO VERSIONE A", old_page)
        self.assertIn("APPROVATA", old_page)
        self.assertNotIn("ORDINE ESEGUITO", old_integrated)
        newer = copy.deepcopy(self.original.plan)
        newer["proposta_id"] = "VERSIONE-B-POSTFLIGHT"
        newer["sostituisce_sha256"] = sha_a
        sha_b = exchange.receive(bridge.canonical(newer))
        self.assertNotEqual(sha_a, sha_b)
        for page in self._postflight_home_with_report():
            self.assertIn("NON APPROVATA", page)
            self.assertNotIn("SOLO VERSIONE A", page)
            self.assertIn("href='/gpt'", page)

    def test_postflight_real_http_home_with_report_and_legacy_tie(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        self._write_existing_event(sha, "RIESAME", "HTTP: due eventi stesso secondo", stamp)
        self._write_existing_event(sha, "RISULTATO_VERIFICATO",
                                   "HTTP: risultato dichiarato legacy", stamp)
        # The report is written by the same genuine helper used for direct and
        # composed HTML; HTTP then reads the real files, not mocked loader data.
        self._postflight_home_with_report()
        (self.sync / "cruscotto.html").write_text(
            "<!doctype html><html><body><header><h1>KDD</h1></header>"
            "<h2>1 · Decisioni e posizioni</h2><p>ORIGINAL CONTROL</p>"
            "<h2>2 · Candidati da valutare</h2><p>SCANNER</p>"
            "<h2>3 · Macroeconomia e geopolitica</h2></body></html>", encoding="utf-8")
        with mock.patch.object(serve.desk, "DIR", self.sync):
            server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/", headers={"Host": "127.0.0.1:8765"})
                response = conn.getresponse()
                body = response.read().decode("utf-8")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        self.assertEqual(response.status, 200)
        self.assertIn("ORIGINAL CONTROL", body)
        self.assertIn("ordine reciproco non documentato", body)
        self.assertIn("HTTP: due eventi stesso secondo", body)
        self.assertIn("HTTP: risultato dichiarato legacy", body)
        self.assertIn("RISCONTRO STORICO DICHIARATO", body)
        self.assertIn("verifica su dati non attestata", body)
        self.assertIn("href='/mercati/spot'", body)
        self.assertIn("href='/gpt'", body)
        self.assertEqual(len(exchange.decision_history()), 2)

    def test_rt26_04_new_microsecond_order_without_digest_sort(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.confirm(sha)
        base = dt.datetime.now(dt.timezone.utc).replace(microsecond=100000)
        first = base.isoformat(timespec="microseconds")
        second = (base + dt.timedelta(microseconds=1)).isoformat(timespec="microseconds")
        self._write_existing_event(sha,"RIESAME","Prima azione",first)
        self._write_existing_event(sha,"RISCONTRO_DICHIARATO","Seconda azione",second)
        result = exchange.decision_history()
        self.assertEqual([row["nota"] for row in result],["Prima azione","Seconda azione"])
        self.assertFalse(exchange.uncertain_event_seconds(result))
        recent, ambiguous = exchange.latest_events(result)
        self.assertFalse(ambiguous)
        self.assertEqual(recent[0]["nota"],"Seconda azione")


    def test_generated_gpt_javascript_node_syntax_and_decision_http(self):
        """Check the actual /gpt HTML, invoke JS decision, then use real POST handler."""
        import http.client
        import subprocess
        import threading
        from http.server import ThreadingHTTPServer
        import serve

        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            request_headers = {"Host": "127.0.0.1:8765"}
            request_headers.update(headers or {})
            try:
                conn.request(method, path, body=body, headers=request_headers)
                response = conn.getresponse()
                return response.status, response.read().decode("utf-8")
            finally:
                conn.close()

        status, page = call("GET", "/gpt")
        self.assertEqual(status, 200)
        self.assertIn("kddDecision(", page)
        self.assertIn("id='kdd-decision-state'", page)
        self.assertIn("id='kdd-decision-note'", page)
        self.assertIn("<script>", page)
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]

        syntax = subprocess.run(["node", "--check"], input=script,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        # Execute exactly the generated script with DOM values selected by the
        # user. A stub captures fetch without touching any external service.
        node = """
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync(0, 'utf8');
const sha = process.argv[1];
let posted = null;
const fields = {
  'kdd-decision-state': {value: 'RINVIATA'},
  'kdd-decision-note': {value: 'Riesame deciso dall autore'},
  'feedback': {textContent: ''}
};
const context = {
  document: {getElementById(id) {
    if (!(id in fields)) throw Error('Campo assente: ' + id);
    return fields[id];
  }},
  fetch(url, options) {
    posted = {url, options};
    return Promise.resolve({ok: false, text: () => Promise.resolve('prova isolata')});
  },
  setTimeout() {},
  location: {reload() {}}
};
vm.runInNewContext(js, context);
if (typeof context.kddDecision !== 'function') throw Error('Funzione non generata');
context.kddDecision(sha);
if (!posted) throw Error('Nessuna richiesta prodotta dalla decisione');
process.stdout.write(JSON.stringify(posted));
"""
        invoked = subprocess.run(["node", "-e", node, sha], input=script,
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(invoked.returncode, 0, invoked.stderr)
        posted = json.loads(invoked.stdout)
        self.assertEqual(posted["url"], "/gpt/decisione")
        self.assertEqual(posted["options"]["method"], "POST")
        self.assertEqual(posted["options"]["headers"]["X-KDD-Token"], serve.TOKEN)
        self.assertEqual(posted["options"]["headers"]["Content-Type"], "application/json")
        payload = json.loads(posted["options"]["body"])
        self.assertEqual(payload, {"sha256": sha, "stato": "RINVIATA",
                                   "nota": "Riesame deciso dall autore"})
        self.assertEqual(bridge.load_archive(), {})

        # Replay the payload generated by JS through the actual local handler.
        status, reply = call("POST", posted["url"], posted["options"]["body"],
                             posted["options"]["headers"])
        self.assertEqual(status, 200, reply)
        self.assertIn("INSERITO", reply)
        history = exchange.decision_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["stato"], "RINVIATA")
        self.assertEqual(history[0]["nota"], "Riesame deciso dall autore")
        self.assertEqual(bridge.load_archive(), {})
        status, page = call("GET", "/gpt")
        self.assertEqual(status, 200)
        self.assertIn("RINVIATA", page)
        self.assertIn("Riesame deciso dall autore", page)


    def _chat_stage(self, proposal):
        """Exact bytes sent by a chat transport, stored only in private Termux."""
        import hashlib
        raw = bridge.canonical(proposal) + b"\n"
        file_sha = hashlib.sha256(raw).hexdigest()
        folder = bridge.private_directory(bridge.INBOX, create=True)
        path = folder / (".chat-" + file_sha + ".json")
        path.write_bytes(raw)
        path.chmod(0o600)
        return path, file_sha, bridge.digest(proposal)

    def test_direct_chat_remote_receipt_appears_on_existing_home_without_approval(self):
        import serve
        from contextlib import redirect_stdout
        import io
        self.original.persist_origin()
        path, byte_sha, proposal_sha = self._chat_stage(self.original.plan)
        self.assertFalse(any(self.sync.iterdir()))  # FolderSync remains unused.
        consent = "PUBBLICA_VERSIONE_" + proposal_sha
        output = io.StringIO()
        with redirect_stdout(output):
            result = exchange.main([
                "ricevi-chat", "--file-sha256", byte_sha,
                "--proposta-sha256", proposal_sha,
                "--consenso-pubblicazione", consent])
        self.assertEqual(result, 0)
        self.assertIn(proposal_sha, output.getvalue())
        self.assertNotIn(self.original.plan["scenario"], output.getvalue())
        self.assertEqual(bridge.digest(exchange.pending()[0]), proposal_sha)
        self.assertEqual(bridge.load_archive(), {})
        home = serve.decision_home()
        self.assertIn(proposal_sha, home)
        self.assertIn("IN ATTESA DI DECISIONE", home)
        self.assertIn("NON APPROVATA", exchange.render_page("TOKEN"))
        # Full existing KDD home over real local HTTP, not just a helper mock.
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        (self.sync / "cruscotto.html").write_text(
            "<html><body><h2>1 · Decisioni e posizioni</h2>"
            "<p>KDD original remains visible</p></body></html>", encoding="utf-8")
        with mock.patch.object(serve.desk, "DIR", self.sync):
            server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/", headers={"Host": "127.0.0.1:8765"})
                response = conn.getresponse()
                shown = response.read().decode("utf-8")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        self.assertEqual(response.status, 200)
        self.assertIn(proposal_sha, shown)
        self.assertIn("IN ATTESA DI DECISIONE", shown)
        self.assertIn("KDD original remains visible", shown)
        self.assertEqual(exchange.receive_chat(byte_sha, proposal_sha, consent),
                         proposal_sha)  # Same pending version is idempotent.
        self.assertEqual(bridge.load_archive(), {})
        self.assertTrue(path.is_file())  # Input retained for later forensic review.

    def test_direct_chat_stops_without_consent_or_matching_two_digests(self):
        self.original.persist_origin()
        source, byte_sha, proposal_sha = self._chat_stage(self.original.plan)
        consent = "PUBBLICA_VERSIONE_" + proposal_sha
        for args in [
            (byte_sha, proposal_sha, "NO"),
            ("0"*64, proposal_sha, consent),
            (byte_sha, "0"*64, consent),
            ("../outside", proposal_sha, consent),
        ]:
            with self.subTest(args=args), self.assertRaises(bridge.BridgeError):
                exchange.receive_chat(*args)
        self.assertIsNone(exchange.pending())
        self.assertEqual(bridge.load_archive(), {})
        source.write_bytes(b'{"tampered":true}')
        with self.assertRaisesRegex(bridge.BridgeError, "digest dei byte"):
            exchange.receive_chat(byte_sha, proposal_sha, consent)
        source.unlink()
        source.symlink_to(self.original.home / "nonexistent.json")
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_chat(byte_sha, proposal_sha, consent)
        source.unlink()

    def test_direct_chat_rejects_world_readable_and_unregistered_origin(self):
        path, byte_sha, proposal_sha = self._chat_stage(self.original.plan)
        consent = "PUBBLICA_VERSIONE_" + proposal_sha
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_chat(byte_sha, proposal_sha, consent)
        self.assertIsNone(exchange.pending())
        self.original.persist_origin()
        path.chmod(0o644)
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_chat(byte_sha, proposal_sha, consent)
        self.assertIsNone(exchange.pending())

    def test_direct_chat_preserves_pending_version_and_rejected_replay(self):
        self.original.persist_origin()
        a = self._candidate("CHAT-A")
        b = self._candidate("CHAT-B")
        _, bytes_a, sha_a = self._chat_stage(a)
        _, bytes_b, sha_b = self._chat_stage(b)
        self.assertEqual(exchange.receive_chat(
            bytes_a, sha_a, "PUBBLICA_VERSIONE_" + sha_a), sha_a)
        with self.assertRaisesRegex(bridge.BridgeError, "attesa"):
            exchange.receive_chat(bytes_b, sha_b, "PUBBLICA_VERSIONE_" + sha_b)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha_a)
        exchange.record_decision(bridge.canonical({
            "sha256": sha_a, "stato": "RINVIATA", "nota": "Autore rinvia A"}))
        self.assertEqual(exchange.receive_chat(
            bytes_b, sha_b, "PUBBLICA_VERSIONE_" + sha_b), sha_b)
        with self.assertRaises(bridge.BridgeError):
            exchange.receive_chat(bytes_a, sha_a, "PUBBLICA_VERSIONE_" + sha_a)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha_b)
        self.assertEqual(bridge.load_archive(), {})


    def test_direct_chat_outbound_private_cli_and_legacy_separate(self):
        """One real KDD-origin writer, no FolderSync or patrimonial stdout."""
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(bridge, "prepare", return_value=self.original.bundle):
            path, origin_sha, snapshot_sha = exchange.prepare_chat()
            self.assertEqual(origin_sha, bridge.digest(self.original.bundle))
            self.assertEqual(snapshot_sha, self.original.bundle["packet_sha256"])
            self.assertEqual(path.read_bytes(), bridge.canonical(self.original.bundle) + b"\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(any(self.sync.iterdir()))
            self.assertEqual(exchange.handle("prepara-chat", b"" ).count(str(path)), 1)
            with self.assertRaises(bridge.BridgeError):
                exchange.handle("prepara-chat", b"unexpected")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(exchange.main(["prepara-chat"]), 0)
        self.assertIn(str(path), out.getvalue())
        self.assertIn(origin_sha, out.getvalue())
        self.assertIn("NON ATTESTATO", out.getvalue())
        self.assertNotIn(self.original.bundle["packet"]["patrimonio"]["posizioni"][0]["token"], out.getvalue())
        self.assertEqual(bridge.verify_local_origin(self.original.bundle), origin_sha)
        self.assertEqual(bridge.load_archive(), {})
        self.assertFalse(any(self.sync.iterdir()))

    def test_direct_chat_outbound_http_requires_csrf_and_shares_no_drive_copy(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve
        server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(method, target, body=b"", token=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Host": "127.0.0.1:8765"}
            if token is not None:
                headers["X-KDD-Token"] = token
            conn.request(method, target, body=body, headers=headers)
            response = conn.getresponse()
            result = (response.status, response.read().decode("utf-8"))
            conn.close()
            return result

        status, page = call("GET", "/gpt")
        self.assertEqual(status, 200)
        self.assertIn("/gpt/prepara-chat", page)
        status, _ = call("POST", "/gpt/prepara-chat", token="WRONG")
        self.assertEqual(status, 403)
        status, _ = call("POST", "/gpt/prepara-chat", body=b"not-empty", token=serve.TOKEN)
        self.assertEqual(status, 422)
        with mock.patch.object(bridge, "prepare", return_value=self.original.bundle):
            status, msg = call("POST", "/gpt/prepara-chat", token=serve.TOKEN)
        self.assertEqual(status, 200, msg)
        self.assertIn("nessun invio automatico", msg)
        self.assertEqual(bridge.verify_local_origin(self.original.bundle),
                         bridge.digest(self.original.bundle))
        self.assertFalse(any(self.sync.iterdir()))
        self.assertEqual(bridge.load_archive(), {})


    def test_direct_chat_not_hidden_by_corrupt_legacy_foldersync_input(self):
        import serve
        self.original.persist_origin()
        _, file_sha, plan_sha = self._chat_stage(self.original.plan)
        self.assertEqual(exchange.receive_chat(
            file_sha, plan_sha, "PUBBLICA_VERSIONE_" + plan_sha), plan_sha)
        (self.sync / exchange.INCOMING_NAME).write_bytes(b'{"broken":')
        home = serve.decision_home()
        # The shared file was read successfully but contains malformed JSON:
        # VALIDAZIONE, never a transport EIO attributed to FolderSync.
        self.assertIn("STOP VALIDAZIONE", home)
        self.assertIn("IN ATTESA DI DECISIONE", home)
        self.assertIn(plan_sha, home)
        page = exchange.render_page("SYNTHETIC")
        self.assertIn("STOP VALIDAZIONE", page)
        self.assertIn("NON APPROVATA", page)
        self.assertIn(plan_sha, page)
        self.assertEqual(bridge.load_archive(), {})


    def test_rt33_01_two_independent_processes_cannot_both_publish(self):
        """Real forked processes: forced overlap before rename, no mock locks."""
        import multiprocessing as mp
        import os
        import time

        self.original.persist_origin()
        a, b = self._candidate("RT33-FORK-A"), self._candidate("RT33-FORK-B")
        sha_a, sha_b = bridge.digest(a), bridge.digest(b)
        self.assertNotEqual(sha_a, sha_b)
        ctx = mp.get_context("fork")
        start = ctx.Event()
        out = ctx.Queue()

        def worker(raw, start_gate, results):
            # A wide, predictable race window *inside* the old unprotected
            # transaction: both old processes would see an empty inbox.
            actual_replace = os.replace

            def slow_replace(source, target):
                if Path(target).name == exchange.INCOMING_NAME:
                    time.sleep(0.35)
                return actual_replace(source, target)

            with mock.patch.object(exchange.os, "replace", side_effect=slow_replace):
                try:
                    if not start_gate.wait(timeout=8):
                        results.put(("STOP", "timeout"))
                        return
                    results.put(("PASS", exchange.receive(raw)))
                except bridge.BridgeError as exc:
                    results.put(("STOP", str(exc)))
                except BaseException as exc:
                    results.put(("ERROR", type(exc).__name__))

        children = [
            ctx.Process(target=worker, args=(bridge.canonical(plan), start, out))
            for plan in (a, b)
        ]
        try:
            for child in children:
                child.start()
            start.set()
            outcomes = [out.get(timeout=12) for _ in children]
            for child in children:
                child.join(timeout=12)
                self.assertEqual(child.exitcode, 0)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=3)
            out.close()
            out.join_thread()
        successful = [status for state, status in outcomes if state == "PASS"]
        stopped = [status for state, status in outcomes if state == "STOP"]
        self.assertEqual(len(successful), 1, outcomes)
        self.assertEqual(len(stopped), 1, outcomes)
        self.assertEqual(successful[0], bridge.digest(exchange.pending()[0]))
        self.assertIn(successful[0], {sha_a, sha_b})
        self.assertIn("attesa", stopped[0])
        self.assertEqual(bridge.load_archive(), {})

        # No hidden overwrite, even a later caller from a separate process.
        rejected = b if successful[0] == sha_a else a
        with self.assertRaisesRegex(bridge.BridgeError, "attesa"):
            exchange.receive(bridge.canonical(rejected))
        self.assertEqual(bridge.digest(exchange.pending()[0]), successful[0])

    def test_rt33_02_eio_from_foldersync_does_not_mask_private_home_or_gpt(self):
        import errno
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve

        self.original.persist_origin()
        proposal_sha = exchange.receive(bridge.canonical(self.original.plan))
        source = self.sync / exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(self._candidate("RT33-STALE")))
        actual_lstat = Path.lstat

        def error_for_synced(path, *args, **kwargs):
            if Path(path) == source:
                raise OSError(errno.EIO, "Injected EIO on synced file")
            return actual_lstat(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=error_for_synced):
            with self.assertRaisesRegex(bridge.BridgeError, "FolderSync"):
                exchange.receive_synced()
            home = serve.decision_home()
            gpt_page = exchange.render_page("SYNTHETIC")
            self.assertIn(proposal_sha, home)
            self.assertIn("IN ATTESA DI DECISIONE", home)
            self.assertIn(proposal_sha, gpt_page)
            self.assertIn("NON APPROVATA", gpt_page)
            self.assertIn("STOP FolderSync legacy", home)
            self.assertIn("STOP FolderSync legacy", gpt_page)
            self.assertEqual(bridge.load_archive(), {})

            # Exercise the actual HTTP handler on port 0, not only helpers.
            (self.sync / "cruscotto.html").write_text(
                "<html><body><h2>1 · Decisioni e posizioni</h2>"
                "<p>Intact original home</p></body></html>", encoding="utf-8")
            with mock.patch.object(serve.desk, "DIR", self.sync):
                server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    for endpoint in ("/", "/gpt"):
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", server.server_port, timeout=5)
                        conn.request("GET", endpoint,
                                     headers={"Host": "127.0.0.1:8765"})
                        response = conn.getresponse()
                        page = response.read().decode("utf-8")
                        conn.close()
                        self.assertEqual(response.status, 200, endpoint)
                        self.assertIn(proposal_sha, page)
                        self.assertIn("STOP FolderSync legacy", page)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)
        self.assertEqual(bridge.digest(exchange.pending()[0]), proposal_sha)

    def test_rt33_02_eio_from_open_or_legacy_status_is_contained(self):
        import errno
        import os
        import serve

        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        source = self.sync / exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(self._candidate("RT33-OPEN-EIO")))
        actual_open = os.open

        def error_on_open(path, *args, **kwargs):
            if Path(path) == source:
                raise OSError(errno.EIO, "Injected open error")
            return actual_open(path, *args, **kwargs)

        with mock.patch.object(exchange.os, "open", side_effect=error_on_open):
            self.assertIn(sha, serve.decision_home())
            self.assertIn(sha, exchange.render_page("TOKEN"))
            self.assertIn("STOP FolderSync legacy", exchange.render_page("TOKEN"))

        source.unlink()
        actual_iterdir = Path.iterdir

        def error_on_listing(path, *args, **kwargs):
            if Path(path) == self.sync:
                raise OSError(errno.EIO, "Injected listing error")
            return actual_iterdir(path, *args, **kwargs)

        with mock.patch.object(Path, "iterdir", autospec=True,
                               side_effect=error_on_listing):
            page = exchange.render_page("TOKEN")
            self.assertIn(sha, page)
            self.assertIn("STOP FolderSync: archivio condiviso", page)
            self.assertIn(sha, serve.decision_home())
        self.assertEqual(bridge.load_archive(), {})


    def _rt2_private_ready(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        private = bridge.private_directory(bridge.INBOX) / exchange.INCOMING_NAME
        self.assertTrue(private.is_file())
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(bridge.load_archive(), {})
        return sha, private

    def _rt2_http_gets(self):
        """Actual localhost HTTP handler with synthetic original page, no live KDD."""
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import serve

        (self.sync / "cruscotto.html").write_text(
            "<html><body><h2>1 · Decisioni e posizioni</h2>"
            "<p>ORIGINAL-SPOT-AVAILABLE</p></body></html>", encoding="utf-8")
        with mock.patch.object(serve.desk, "DIR", self.sync):
            server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                out = {}
                for endpoint in ("/", "/gpt"):
                    conn = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=5)
                    conn.request("GET", endpoint,
                                 headers={"Host": "127.0.0.1:8765"})
                    reply = conn.getresponse()
                    status, body = reply.status, reply.read().decode("utf-8")
                    conn.close()
                    self.assertEqual(status, 200, endpoint)
                    out[endpoint] = body
                self.assertIn("ORIGINAL-SPOT-AVAILABLE", out["/"])
                return out
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def _rt2_assert_private_stop(self, *, http=False, foldersync=False):
        """An unreadable private file is never a legitimate None."""
        import serve
        with self.assertRaisesRegex(bridge.BridgeError, r"STOP (?:PERSISTENZA PRIVATA|DECISIONI)"):
            exchange.pending()
        home = serve.decision_home()
        gpt = exchange.render_page("SYNTHETIC")
        for ui in (home, gpt):
            self.assertTrue(
                "STOP PERSISTENZA PRIVATA" in ui or "STOP DECISIONI" in ui, ui)
            self.assertNotIn("Proposta GPT: ASSENTE", ui)
            self.assertNotIn("Nessuna proposta ricevuta", ui)
            self.assertNotIn("NON APPROVATA", ui)
            if foldersync:
                self.assertIn("STOP FolderSync legacy", ui)
        if http:
            for ui in self._rt2_http_gets().values():
                self.assertTrue(
                "STOP PERSISTENZA PRIVATA" in ui or "STOP DECISIONI" in ui, ui)
                self.assertNotIn("Nessuna proposta ricevuta", ui)
                if foldersync:
                    self.assertIn("STOP FolderSync legacy", ui)

    def test_rt2_a_absence_verified_with_missing_inbox_and_missing_file(self):
        import serve
        self.assertIsNone(exchange.pending())
        self.assertIn("Proposta GPT: ASSENTE", serve.decision_home())
        self.assertIn("Nessuna proposta ricevuta", exchange.render_page("TOKEN"))
        folder = bridge.private_directory(bridge.INBOX, create=True)
        self.assertFalse((folder / exchange.INCOMING_NAME).exists())
        self.assertIsNone(exchange.pending())
        self.assertIn("Proposta GPT: ASSENTE", serve.decision_home())
        self.assertIn("Nessuna proposta ricevuta", exchange.render_page("TOKEN"))
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_b_valid_proposal_same_sha_in_http_no_approval(self):
        sha, _ = self._rt2_private_ready()
        pages = self._rt2_http_gets()
        for text in pages.values():
            self.assertIn(sha, text)
            self.assertIn("NON APPROVATA", text)
            self.assertNotIn("STOP PERSISTENZA PRIVATA", text)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_c_private_eio_os_open_fstat_stat_read_bytes(self):
        import errno
        import os

        sha, private = self._rt2_private_ready()
        st = private.stat()
        real_open, real_fstat = os.open, os.fstat
        real_stat, real_fdopen = os.stat, os.fdopen

        def failing_open(path, *args, **kwargs):
            if Path(path) == private:
                raise OSError(errno.EIO, "synthetic private open")
            return real_open(path, *args, **kwargs)

        def failing_fstat(fd, *args, **kwargs):
            actual = real_fstat(fd, *args, **kwargs)
            if (actual.st_ino, actual.st_dev) == (st.st_ino, st.st_dev):
                raise OSError(errno.EIO, "synthetic private fstat")
            return actual

        def failing_stat(path, *args, **kwargs):
            if Path(path) == private:
                raise OSError(errno.EIO, "synthetic private stat")
            return real_stat(path, *args, **kwargs)

        class FailingReader:
            def __init__(self, original):
                self.original = original
            def __enter__(self):
                self.original.__enter__()
                return self
            def __exit__(self, *args):
                return self.original.__exit__(*args)
            def fileno(self):
                return self.original.fileno()
            def read(self, *args):
                raise OSError(errno.EIO, "synthetic private read bytes")

        def failing_fdopen(fd, *args, **kwargs):
            file = real_fdopen(fd, *args, **kwargs)
            info = real_fstat(file.fileno())
            if (info.st_ino, info.st_dev) == (st.st_ino, st.st_dev):
                return FailingReader(file)
            return file

        for name, function in (("open", failing_open),
                               ("fstat", failing_fstat),
                               ("stat", failing_stat),
                               ("fdopen", failing_fdopen)):
            with self.subTest(fault=name), mock.patch.object(bridge.os, name,
                                                               side_effect=function):
                self._rt2_assert_private_stop(http=(name == "open"))
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_c_private_inbox_directory_eio_and_inaccessible(self):
        import errno
        import os
        self._rt2_private_ready()
        folder = bridge.PRIVATE_ROOT / bridge.INBOX
        real_open = os.open
        def failing_open(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "synthetic private directory EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(bridge.os, "open", side_effect=failing_open):
            self._rt2_assert_private_stop()
        mode = folder.stat().st_mode & 0o777
        try:
            folder.chmod(0o755)
            self._rt2_assert_private_stop()
        finally:
            folder.chmod(mode)

    def test_rt2_e_simultaneous_foldersync_and_private_eio(self):
        import errno
        import os
        self._rt2_private_ready()
        private = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        shared = self.sync / exchange.INCOMING_NAME
        shared.write_text("synthetic", encoding="utf-8")
        real_open = os.open
        def failing_open(path, *args, **kwargs):
            if Path(path) in (private, shared):
                raise OSError(errno.EIO, "synthetic transport/private EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(bridge.os, "open", side_effect=failing_open):
            self._rt2_assert_private_stop(http=True, foldersync=True)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_f_corrupt_symlink_permissions_owner_inode_replacement(self):
        import os
        self._rt2_private_ready()
        private = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        raw = private.read_bytes()
        original = private.stat()
        original_fstat, original_stat = os.fstat, os.stat

        def put_back():
            if private.exists() or private.is_symlink():
                private.unlink()
            private.write_bytes(raw)
            private.chmod(0o600)

        try:
            private.write_bytes(b'{"bad":')
            self._rt2_assert_private_stop()
            put_back()
            private.chmod(0o644)
            self._rt2_assert_private_stop()
            put_back()
            target = self.original.home / "synthetic-target.json"
            target.write_bytes(raw)
            private.unlink()
            private.symlink_to(target)
            self._rt2_assert_private_stop()
            put_back()

            def wrong_owner(fd, *args, **kwargs):
                st = original_fstat(fd, *args, **kwargs)
                if (st.st_ino, st.st_dev) == (private.stat().st_ino, private.stat().st_dev):
                    values = list(st)
                    values[4] += 1
                    return os.stat_result(values)
                return st
            with mock.patch.object(bridge.os, "fstat", side_effect=wrong_owner):
                self._rt2_assert_private_stop()

            def wrong_inode(path, *args, **kwargs):
                st = original_stat(path, *args, **kwargs)
                if Path(path) == private:
                    values = list(st)
                    values[1] += 1
                    return os.stat_result(values)
                return st
            with mock.patch.object(bridge.os, "stat", side_effect=wrong_inode):
                self._rt2_assert_private_stop()

            real_reader = bridge.read_regular
            def vanish(path, *args, **kwargs):
                if Path(path) != private:
                    return real_reader(path, *args, **kwargs)
                private.unlink()  # disappearance BETWEEN verified lstat and open
                try:
                    return real_reader(path, *args, **kwargs)
                finally:
                    private.write_bytes(raw)
                    private.chmod(0o600)  # synthetic fixture for next HTTP read
            with mock.patch.object(bridge, "read_regular", side_effect=vanish):
                self._rt2_assert_private_stop()
            put_back()
            self.assertEqual(bridge.digest(exchange.pending()[0]),
                             bridge.digest(self.original.plan))
        finally:
            put_back()
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_e_valid_shared_input_with_private_eio_is_only_private_stop(self):
        import errno
        import os
        self._rt2_private_ready()
        shared = self.sync / exchange.INCOMING_NAME
        shared.write_bytes(bridge.canonical(self.original.plan))
        private = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        real_open = os.open

        def private_fault(path, *args, **kwargs):
            if Path(path) == private:
                raise OSError(errno.EIO, "private read only")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(bridge.os, "open", side_effect=private_fault):
            # A valid shared packet reaches the private read; this is NOT
            # a FolderSync EIO and must not fabricate two failed channels.
            self._rt2_assert_private_stop(http=True, foldersync=False)
            for page in self._rt2_http_gets().values():
                self.assertNotIn("STOP FolderSync legacy", page)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_f_transient_eio_does_not_claim_absence_then_recovers(self):
        import errno
        import os
        sha, private = self._rt2_private_ready()
        real_open = os.open
        attempts = [0]
        def one_failure(path, *args, **kwargs):
            if Path(path) == private and attempts[0] == 0:
                attempts[0] += 1
                raise OSError(errno.EIO, "transient synthetic EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(bridge.os, "open", side_effect=one_failure):
            with self.assertRaisesRegex(bridge.BridgeError, "STOP PERSISTENZA PRIVATA"):
                exchange.pending()
            self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt2_h_interprocess_incompatible_versions_still_serialized(self):
        # Independent processes and forced scheduling window: previous RT33-01
        # adversarial test must remain green on this exact HEAD.
        self.test_rt33_01_two_independent_processes_cannot_both_publish()


    def test_rt33_rt3_d1_missing_event_directory_is_genuinely_empty(self):
        self.original.persist_origin()
        a = self._candidate("RT3-NO-EVENT")
        sha = exchange.receive(bridge.canonical(a))
        self.assertEqual(exchange.decision_history(), [])
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        self.assertEqual(len(bridge.load_archive()), 1)

    def test_rt33_rt3_d1_eio_stat_hides_prior_rinvio_without_guard(self):
        """3.14 Path.exists may mask EIO, but prior human decision must not vanish."""
        import errno
        import os
        self.original.persist_origin()
        a = self._candidate("RT3-D1-A")
        b = self._candidate("RT3-D1-B")
        sha = exchange.receive(bridge.canonical(a))
        payload = bridge.canonical({"sha256": sha, "stato": "RINVIATA",
                                    "nota": "Rinviata prima del guasto eventi"})
        self.assertEqual(exchange.record_decision(payload), "INSERITO")
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        actual_stat = os.stat
        def eio_stat(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "EIO synthetic event metadata")
            return actual_stat(path, *args, **kwargs)

        with mock.patch.object(exchange.os, "stat", side_effect=eio_stat):
            for action in (lambda: exchange.confirm(sha),
                           lambda: exchange.receive(bridge.canonical(b)),
                           lambda: exchange.record_decision(payload)):
                with self.assertRaisesRegex(bridge.BridgeError,
                                            "STOP ARCHIVIO DECISIONI"):
                    action()
        self.assertEqual(bridge.load_archive(), {})
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(len(exchange.decision_history()), 1)

    def test_rt33_rt3_d1_event_directory_open_fstat_and_iter_eio(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.record_decision(bridge.canonical(
            {"sha256":sha, "stato":"RIFIUTATA", "nota":"Stop storico"}))
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        actual_open, actual_fstat = os.open, os.fstat
        actual_iterdir = Path.iterdir
        directory_inode = folder.stat()

        def bad_open(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "EIO event directory open")
            return actual_open(path, *args, **kwargs)
        def bad_fstat(fd, *args, **kwargs):
            current = actual_fstat(fd, *args, **kwargs)
            if (current.st_dev, current.st_ino) == (directory_inode.st_dev,
                                                      directory_inode.st_ino):
                raise OSError(errno.EIO, "EIO event directory fstat")
            return current
        def bad_iter(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "EIO event directory enumeration")
            return actual_iterdir(path, *args, **kwargs)

        for method, fault in (("open", bad_open), ("fstat", bad_fstat)):
            with self.subTest(method=method), mock.patch.object(
                    exchange.os, method, side_effect=fault):
                with self.assertRaisesRegex(bridge.BridgeError, "STOP ARCHIVIO DECISIONI"):
                    exchange.confirm(sha)
        with mock.patch.object(Path, "iterdir", autospec=True, side_effect=bad_iter):
            with self.assertRaisesRegex(bridge.BridgeError, "STOP ARCHIVIO DECISIONI"):
                exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_d2_stat_eio_cannot_replace_undecided_a_with_b(self):
        import errno
        import os
        self.original.persist_origin()
        a, b = self._candidate("RT3-D2-A"), self._candidate("RT3-D2-B")
        sha = exchange.receive(bridge.canonical(a))
        final = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        before = final.read_bytes()
        real_stat = os.stat
        def bad_stat(path, *args, **kwargs):
            if Path(path) == final:
                raise OSError(errno.EIO, "EIO proposal stat")
            return real_stat(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "stat", side_effect=bad_stat):
            with self.assertRaises(bridge.BridgeError):
                exchange.receive(bridge.canonical(b))
        self.assertEqual(final.read_bytes(), before)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_d2_lstat_eio_symlink_and_stale_replay(self):
        import errno
        import os
        self.original.persist_origin()
        a, b = self._candidate("RT3-D2-LSTA"), self._candidate("RT3-D2-LSTB")
        sha = exchange.receive(bridge.canonical(a))
        final = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        before = final.read_bytes()
        real_lstat = os.lstat
        def bad_lstat(path, *args, **kwargs):
            if Path(path) == final:
                raise OSError(errno.EIO, "EIO proposal lstat")
            return real_lstat(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "lstat", side_effect=bad_lstat):
            with self.assertRaises(bridge.BridgeError):
                exchange.receive(bridge.canonical(b))
        self.assertEqual(final.read_bytes(), before)
        final.unlink()
        target = self.original.home / "RT3-target.json"
        target.write_bytes(before)
        final.symlink_to(target)
        with self.assertRaises(bridge.BridgeError):
            exchange.receive(bridge.canonical(b))
        final.unlink()
        final.write_bytes(before)
        final.chmod(0o600)
        self.assertEqual(exchange.record_decision(bridge.canonical(
            {"sha256":sha, "stato":"RINVIATA", "nota":"Decisione esplicita"})), "INSERITO")
        self.assertEqual(exchange.receive(bridge.canonical(b)), bridge.digest(b))
        with self.assertRaises(bridge.BridgeError):
            exchange.receive(bridge.canonical(a))
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_d3_root_eio_visible_with_valid_private_pending(self):
        import errno
        import os
        import serve
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        root = self.sync
        real_lstat = Path.lstat
        def broken(path, *args, **kwargs):
            if Path(path) == root:
                raise OSError(errno.EIO, "FolderSync root EIO")
            return real_lstat(path, *args, **kwargs)
        # Mock the exact Path API used by receive_synced across Python 3.12/3.14:
        # its internal os.stat/os.lstat dispatch is platform-dependent.
        with mock.patch.object(Path, "lstat", autospec=True, side_effect=broken):
            with self.assertRaisesRegex(bridge.BridgeError, "FolderSync"):
                exchange.receive_synced()
            for page in (serve.decision_home(), exchange.render_page("TOKEN")):
                self.assertIn("STOP FolderSync", page)
                self.assertIn(sha, page)
                self.assertNotIn("STOP PERSISTENZA PRIVATA", page)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)

    def test_rt33_rt3_d3_source_eio_is_not_absence(self):
        import errno
        import os
        import serve
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        source = self.sync / exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(self.original.plan))
        real_stat, real_lstat = os.stat, os.lstat

        def stat_fault(path, *args, **kwargs):
            if Path(path) == source:
                raise OSError(errno.EIO, "source stat EIO")
            return real_stat(path, *args, **kwargs)
        def lstat_fault(path, *args, **kwargs):
            if Path(path) == source:
                raise OSError(errno.EIO, "source lstat EIO")
            return real_lstat(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "stat", side_effect=stat_fault), (
                mock.patch.object(exchange.os, "lstat", side_effect=lstat_fault)):
            with self.assertRaisesRegex(bridge.BridgeError, "FolderSync"):
                exchange.receive_synced()
            for page in (serve.decision_home(), exchange.render_page("TOKEN")):
                self.assertIn("STOP FolderSync", page)
                self.assertIn(sha, page)
        source.unlink()
        self.assertIsNone(exchange.receive_synced())
        with mock.patch.object(exchange, "EXCHANGE_ROOT", self.original.home / "not-created"):
            self.assertIsNone(exchange.receive_synced())
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_record_decision_target_eio_must_not_be_absence(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        actual_stat, actual_lstat = os.stat, os.lstat
        def bad_stat(path, *args, **kwargs):
            if Path(path).parent == folder and Path(path).suffix == ".json":
                raise OSError(errno.EIO, "event collision stat EIO")
            return actual_stat(path, *args, **kwargs)
        def bad_lstat(path, *args, **kwargs):
            if Path(path).parent == folder and Path(path).suffix == ".json":
                raise OSError(errno.EIO, "event collision lstat EIO")
            return actual_lstat(path, *args, **kwargs)
        payload = bridge.canonical({"sha256":sha, "stato":"RINVIATA",
                                    "nota":"No silent collision"})
        with mock.patch.object(exchange.os, "stat", side_effect=bad_stat), (
                mock.patch.object(exchange.os, "lstat", side_effect=bad_lstat)):
            with self.assertRaises(bridge.BridgeError):
                exchange.record_decision(payload)
        # Write-ahead witness survived the failed destination check:
        # the transaction is uncertain and cannot become an empty history.
        with self.assertRaisesRegex(exchange.DecisionContinuityError,
                                    "STOP DECISIONI"):
            exchange.decision_history()
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_race_two_processes_and_author_chain_still_safe(self):
        self.test_rt33_01_two_independent_processes_cannot_both_publish()


    def test_rt33_rt3_approved_archive_eio_does_not_erase_prior_chain(self):
        import errno
        import os
        self.original.persist_origin()
        a = self._candidate("RT3-APROVED-A")
        sha_a = exchange.receive(bridge.canonical(a))
        self.assertEqual(exchange.confirm(sha_a)["stato"], "INSERITO")
        private_file = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        private_file.unlink()  # Synthetic no-current-inbox, approval still exists.
        folder = bridge.PRIVATE_ROOT / bridge.ARCHIVE
        real_stat = os.stat
        def error(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "Archive metadata EIO")
            return real_stat(path, *args, **kwargs)
        b = self._candidate("RT3-APROVED-B", parent=None)
        with mock.patch.object(exchange.os, "stat", side_effect=error):
            with self.assertRaisesRegex(bridge.BridgeError, "STOP ARCHIVIO APPROVAZIONI"):
                exchange.receive(bridge.canonical(b))
        self.assertIsNone(exchange.pending())
        self.assertEqual(set(bridge.load_archive()), {sha_a})

    def test_rt33_rt3_decision_error_is_visible_not_503_in_http(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        exchange.record_decision(bridge.canonical(
            {"sha256": sha, "stato": "RINVIATA", "nota": "D1 HTTP"}))
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        real_stat = os.stat
        def fail(path, *args, **kwargs):
            if Path(path) == folder:
                raise OSError(errno.EIO, "Decision archive EIO")
            return real_stat(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "stat", side_effect=fail):
            pages = self._rt2_http_gets()
            self.assertIn("STOP DECISIONI", pages["/"])
            self.assertIn("STOP ARCHIVIO DECISIONI", pages["/gpt"])
            for content in pages.values():
                self.assertNotIn("APPROVATA · ARCHIVIO", content)
                self.assertNotIn("Confermo questa versione nel KDD</button>", content)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_receive_replace_then_exception_is_uncertain(self):
        import errno
        import os
        self.original.persist_origin()
        raw = bridge.canonical(self._candidate("RT3-REPLACE-UNCERTAIN"))
        real_replace = os.replace
        def replace_then_error(source, target):
            real_replace(source, target)
            if Path(target).name == exchange.INCOMING_NAME:
                raise OSError(errno.EIO, "simulated kernel error after replace")
        with mock.patch.object(exchange.os, "replace", side_effect=replace_then_error):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.receive(raw)
        sha = bridge.digest(bridge.strict_json(raw))
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha)
        self.assertEqual(bridge.load_archive(), {})
        self.assertEqual(exchange.receive(raw), sha)

    def test_rt33_rt3_receive_directory_fsync_uncertain_then_durable_retry(self):
        import errno
        self.original.persist_origin()
        raw = bridge.canonical(self._candidate("RT3-FSYNC-UNCERTAIN"))
        original_sync = bridge._sync_dir
        folder = bridge.PRIVATE_ROOT / bridge.INBOX
        attempts = [0]
        def fail_once(directory):
            if Path(directory) == folder and attempts[0] == 0:
                attempts[0] += 1
                raise OSError(errno.EIO, "simulated fsync directory failure")
            return original_sync(directory)
        with mock.patch.object(bridge, "_sync_dir", side_effect=fail_once):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.receive(raw)
            self.assertEqual(exchange.receive(raw), bridge.digest(bridge.strict_json(raw)))
        self.assertEqual(attempts[0], 1)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_event_after_rename_fsync_is_uncertain_no_duplicate(self):
        import errno
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        payload = bridge.canonical({"sha256": sha, "stato": "RINVIATA",
                                    "nota": "Evento incerto: non duplicare"})
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        real_sync = bridge._sync_dir
        def fail(directory):
            if Path(directory) == folder:
                raise OSError(errno.EIO, "simulated event fsync failure")
            return real_sync(directory)
        with mock.patch.object(bridge, "_sync_dir", side_effect=fail):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.record_decision(payload)
        self.assertEqual(len(exchange.decision_history()), 1)
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload)
        with self.assertRaises(bridge.BridgeError):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt33_rt3_event_after_rename_exception_is_uncertain(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        payload = bridge.canonical({"sha256": sha, "stato": "RIFIUTATA",
                                    "nota": "Evento rinominato ma incerto"})
        actual_rename = os.rename
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        def rename_then_error(source, target):
            actual_rename(source, target)
            if Path(target).parent == folder and Path(target).suffix == ".json":
                raise OSError(errno.EIO, "kernel error after rename")
        with mock.patch.object(exchange.os, "rename", side_effect=rename_then_error):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.record_decision(payload)
        self.assertEqual(len(exchange.decision_history()), 1)
        with self.assertRaises(bridge.BridgeError):
            exchange.record_decision(payload)
        self.assertEqual(bridge.load_archive(), {})


    def test_rt33_rt3_d2_second_identity_check_stops_toctou(self):
        import os
        self.original.persist_origin()
        a, b = self._candidate("RT3-TOCTOU-A"), self._candidate("RT3-TOCTOU-B")
        sha_a = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical(
            {"sha256":sha_a, "stato":"RINVIATA", "nota":"Successor allowed"}))
        final = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME
        original_bytes = final.read_bytes()
        real_identity = exchange._private_file_identity
        counts = [0]

        def non_cooperative_replacement(path):
            counts[0] += 1
            if counts[0] == 2:
                another = final.with_name(".rt3-synthetic-external.tmp")
                another.write_bytes(original_bytes)
                another.chmod(0o600)
                os.replace(another, final)  # new inode, same bytes
            return real_identity(path)

        with mock.patch.object(exchange, "_private_file_identity",
                               side_effect=non_cooperative_replacement):
            with self.assertRaisesRegex(bridge.BridgeError, "mutata"):
                exchange.receive(bridge.canonical(b))
        self.assertEqual(counts[0], 2)
        self.assertEqual(final.read_bytes(), original_bytes)
        self.assertEqual(bridge.digest(exchange.pending()[0]), sha_a)
        self.assertEqual(bridge.load_archive(), {})


    def _rt4_fork_confirm(self, sha):
        import multiprocessing as mp
        ctx = mp.get_context("fork")
        out = ctx.Queue()
        def worker():
            try:
                exchange.confirm(sha)
                out.put(("SUCCESS", ""))
            except bridge.BridgeError as exc:
                out.put(("STOP", str(exc)))
        proc = ctx.Process(target=worker)
        proc.start()
        try:
            state, detail = out.get(timeout=10)
            proc.join(timeout=10)
            self.assertEqual(proc.exitcode, 0)
            return state, detail
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
            out.close()
            out.join_thread()

    def _rt4_lost_event_history(self, state):
        self.original.persist_origin()
        a = self._candidate("RT4-A-" + state)
        sha = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical({
            "sha256": sha, "stato": state, "nota": "Scelta autore prima di perdita"}))
        folder = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        saved = folder.with_name("decision_events_hidden_rt4")
        folder.rename(saved)  # real directory disappearance, not a patch
        result, message = self._rt4_fork_confirm(sha)
        self.assertEqual(result, "STOP", message)
        self.assertIn("STOP DECISIONI", message)
        self.assertEqual(bridge.load_archive(), {})
        folder.mkdir(mode=0o700)  # apparently clean but missing the history
        result, message = self._rt4_fork_confirm(sha)
        self.assertEqual(result, "STOP", message)
        self.assertIn("STOP DECISIONI", message)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d1_rinviata_history_removed_restart_must_stop(self):
        self._rt4_lost_event_history("RINVIATA")

    def test_rt4_d1_rifiutata_history_removed_restart_must_stop(self):
        self._rt4_lost_event_history("RIFIUTATA")

    def test_rt4_d1_approved_archive_removed_then_empty_must_stop(self):
        self.original.persist_origin()
        a = self._candidate("RT4-APPROVED-A")
        sha = exchange.receive(bridge.canonical(a))
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        # Synthetic next-session state: completed approval no longer occupies
        # the incoming slot, so only historical continuity can block B.
        (bridge.PRIVATE_ROOT / bridge.INBOX / exchange.INCOMING_NAME).unlink()
        original = bridge.PRIVATE_ROOT / bridge.ARCHIVE
        original.rename(original.with_name("approvals_hidden_rt4"))
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.receive(bridge.canonical(self._candidate("RT4-B")))
        original.mkdir(mode=0o700)
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.record_decision(bridge.canonical({
                "sha256": sha, "stato":"RIESAME", "nota":"Non consentire perdita"}))

    def test_rt4_d1_deleted_witness_and_history_still_detected_by_anchor(self):
        import shutil
        self.original.persist_origin()
        a = self._candidate("RT4-DOUBLE-DELETE")
        sha = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical({
            "sha256":sha, "stato":"RINVIATA", "nota":"Doppia cancellazione"}))
        eventdir = bridge.PRIVATE_ROOT / bridge.INBOX / exchange.DECISION_EVENTS
        shutil.rmtree(eventdir)
        for f in (bridge.PRIVATE_ROOT / exchange._WITNESSES).glob("e-*.json"):
            f.unlink()
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d1_fresh_enrolled_reboot_and_transient_failure(self):
        import errno
        import os
        self.assertEqual(exchange.decision_history(), [])
        self.assertEqual(exchange._checked_approvals(), {})
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        root = bridge.PRIVATE_ROOT
        real_open = os.open
        enrollment = root / exchange._ENROLLMENT
        def fault(path, *args, **kwargs):
            if Path(path) == enrollment:
                raise OSError(errno.EIO, "Transient enrollment EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "open", side_effect=fault):
            with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                exchange.confirm(sha)
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        self.assertEqual(exchange._checked_approvals().keys(), {sha})
        with self.assertRaises(bridge.BridgeError):
            exchange.initialize_decision_continuity(
                mode="NEW", acknowledgement="INIZIALIZZO_NUOVO_STORICO")

    def test_rt4_d1_legacy_requires_explicit_reconciliation(self):
        self.original.persist_origin()
        a = self._candidate("RT4-LEGACY-A")
        sha = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical({
            "sha256":sha, "stato":"RINVIATA", "nota":"Legacy evidence"}))
        root = bridge.PRIVATE_ROOT
        (root / exchange._ENROLLMENT).rename(root / "saved-enrollment.old")
        (root / exchange._WITNESSES).rename(root / "saved-witnesses.old")
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.confirm(sha)
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="NEW", acknowledgement="INIZIALIZZO_NUOVO_STORICO")
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="RECONCILE",
                acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
                expected_sha256="0"*64)
        # Only after an *independent* evidence check in a test fixture:
        expected = exchange._continuity_snapshot(
            exchange._history_unchecked(), exchange._approvals_unchecked())
        result = exchange.initialize_decision_continuity(
            mode="RECONCILE", acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
            expected_sha256=expected)
        self.assertEqual(result["eventi"], 1)
        with self.assertRaises(bridge.BridgeError):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d3_valid_foldersync_private_outbox_eio_is_private_domain(self):
        import errno
        import os
        self.original.persist_origin()
        shared = self.sync / exchange.INCOMING_NAME
        shared.write_bytes(bridge.canonical(self.original.plan))
        outbox = bridge.PRIVATE_ROOT / bridge.OUTBOX
        real_open = os.open
        def fault(path, *args, **kwargs):
            if Path(path) == outbox:
                raise OSError(errno.EIO, "Synthetic outbox EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "open", side_effect=fault):
            with self.assertRaises(bridge.BridgeError) as caught:
                exchange.receive_synced()
            self.assertEqual(getattr(caught.exception, "domain", None), "private")
            pages = self._rt2_http_gets()
            for body in pages.values():
                self.assertIn("STOP PERSISTENZA PRIVATA", body)
                self.assertNotIn("STOP FolderSync legacy", body)
                self.assertNotIn("Proposta GPT: ASSENTE", body)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d3_valid_shared_origin_missing_bad_mode_corrupt_is_private(self):
        import shutil
        self.original.persist_origin()
        (self.sync / exchange.INCOMING_NAME).write_bytes(
            bridge.canonical(self.original.plan))
        outbox = bridge.PRIVATE_ROOT / bridge.OUTBOX
        source = outbox / (bridge.digest(self.original.bundle) + ".json")
        for fault in ("mode", "corrupt", "absent"):
            with self.subTest(fault=fault):
                if fault == "mode":
                    source.chmod(0o644)
                elif fault == "corrupt":
                    source.chmod(0o600)
                    source.write_bytes(b'{"broken":')
                else:
                    shutil.rmtree(outbox)
                try:
                    with self.assertRaises(bridge.BridgeError) as caught:
                        exchange.receive_synced()
                    self.assertEqual(getattr(caught.exception, "domain", None), "private")
                    html = exchange.render_page("TEST")
                    self.assertIn("STOP PERSISTENZA PRIVATA", html)
                    self.assertNotIn("STOP FolderSync legacy", html)
                finally:
                    outbox.mkdir(mode=0o700, exist_ok=True)
                    source.write_bytes(bridge.canonical(self.original.bundle) + b"\n")
                    source.chmod(0o600)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d3_separate_and_joint_errors_typed_no_fake_absence(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        source = self.sync / exchange.INCOMING_NAME
        source.write_bytes(bridge.canonical(self.original.plan))
        outbox = bridge.PRIVATE_ROOT / bridge.OUTBOX
        real_open = os.open
        def faults(path, *args, **kwargs):
            if Path(path) in (source, outbox):
                raise OSError(errno.EIO, "Synthetic FS/private EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "open", side_effect=faults):
            pages = self._rt2_http_gets()
            for content in pages.values():
                self.assertIn("STOP FolderSync legacy", content)
                self.assertIn("STOP PERSISTENZA PRIVATA", content)
                self.assertNotIn("NON APPROVATA", content)
        self.assertEqual(bridge.load_archive(), {})

        def only_folder(path, *args, **kwargs):
            if Path(path) == source:
                raise OSError(errno.EIO, "Shared EIO")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(exchange.os, "open", side_effect=only_folder):
            pages = self._rt2_http_gets()
            for content in pages.values():
                self.assertIn("STOP FolderSync legacy", content)
                self.assertIn(sha, content)
                self.assertIn("NON APPROVATA", content)
                self.assertNotIn("STOP PERSISTENZA PRIVATA", content)

    def test_rt4_d3_valid_folder_invalid_json_is_validation_domain(self):
        self.original.persist_origin()
        (self.sync / exchange.INCOMING_NAME).write_bytes(b'{invalid')
        with self.assertRaises(bridge.BridgeError) as caught:
            exchange.receive_synced()
        self.assertEqual(getattr(caught.exception, "domain", None), "validation")
        pages = self._rt2_http_gets()
        for content in pages.values():
            self.assertIn("STOP VALIDAZIONE", content)
            self.assertNotIn("STOP FolderSync legacy", content)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_h_interprocess_lock_and_uncertain_commit_regressions(self):
        self.test_rt33_01_two_independent_processes_cannot_both_publish()


    def test_rt4_d1_enrollment_missing_is_not_a_new_install(self):
        self.original.persist_origin()
        a = self._candidate("RT4-ALL-PROOFS-LOST")
        sha = exchange.receive(bridge.canonical(a))
        exchange.record_decision(bridge.canonical({
            "sha256":sha, "stato":"RINVIATA", "nota":"Mancano prove"}))
        import shutil
        root = bridge.PRIVATE_ROOT
        (root / exchange._ENROLLMENT).unlink()
        shutil.rmtree(root / exchange._WITNESSES)
        shutil.rmtree(root / bridge.INBOX / exchange.DECISION_EVENTS)
        with self.assertRaisesRegex(exchange.DecisionContinuityError,
                                    "STOP DECISIONI"):
            exchange.confirm(sha)
        with self.assertRaisesRegex(exchange.DecisionContinuityError,
                                    "STOP DECISIONI"):
            exchange.receive(bridge.canonical(self._candidate("RT4-LOST-B")))
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d1_unfinished_witness_transaction_stops_authority(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        marker = bridge.PRIVATE_ROOT / exchange._ENROLLMENT
        real_replace = os.replace
        payload = bridge.canonical({"sha256": sha, "stato":"RINVIATA",
                                    "nota":"Riserva prima di commit"})
        def replace_then_error(source, target):
            real_replace(source, target)
            if Path(target) == marker:
                raise OSError(errno.EIO, "Synthetic EIO after enrollment replace")
        with mock.patch.object(exchange.os, "replace", side_effect=replace_then_error):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.record_decision(payload)
        with self.assertRaisesRegex(exchange.DecisionContinuityError,
                                    "STOP DECISIONI"):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt4_d1_committed_approval_reloaded_in_fork(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        status, detail = self._rt4_fork_confirm(sha)
        self.assertEqual(status, "SUCCESS", detail)  # idempotent, no new order
        self.assertEqual(set(exchange._checked_approvals()), {sha})


    # RT5-D1-F1: all below are synthetic-only isolated filesystem tests.
    def _rt5_approve(self):
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        approved = exchange._checked_approvals()[sha]
        self.assertEqual(approved["versione_sha256"], sha)
        self.assertNotEqual(bridge.digest(approved), sha)
        root = bridge.PRIVATE_ROOT
        proof = bridge.strict_json((root / exchange._WITNESSES /
                                   ("a-" + sha + ".json")).read_bytes())
        anchor = bridge.strict_json((root / exchange._ENROLLMENT).read_bytes())
        self.assertEqual(proof["record"], approved)
        self.assertEqual(proof["record_sha256"], bridge.digest(approved))
        self.assertEqual(anchor["schema"], exchange._ENROLLMENT_SCHEMA)
        self.assertEqual(anchor["approvals"],
                         [{"versione_sha256": sha,
                           "record_sha256": bridge.digest(approved)}])
        return sha, bridge.PRIVATE_ROOT / bridge.ARCHIVE / (sha + ".json"), approved

    def _rt5_save(self, file, value):
        file.write_bytes(bridge.canonical(value) + bytes([10]))

    def test_rt5_a_full_record_metadata_differential(self):
        sha, file, original = self._rt5_approve()
        changes = (
            ("approvato_utc", "1999-01-01T00:00:00+00:00"),
            ("snapshot_id", "0"*64),
            ("nessun_ordine", False),
            ("esecuzione", "ESEGUITA"),
            ("consenso", "IGNOTO"),
            ("versione_sha256", "0"*64),
            ("proposta", {"schema": "fake"}),
            ("extra", "new"),
            ("approvato_utc", 17),
            ("nessun_ordine", 1),
            ("esecuzione", None),
        )
        try:
            for key, value in changes:
                with self.subTest(key=key, value=value):
                    changed = copy.deepcopy(original)
                    changed[key] = value
                    self._rt5_save(file, changed)
                    with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                        exchange._checked_approvals()
                    self.assertIn("STOP", bridge.approved_html())
                    self._rt5_save(file, original)
                    self.assertEqual(exchange._checked_approvals()[sha], original)
            for key in original:
                with self.subTest(missing=key):
                    changed = copy.deepcopy(original)
                    del changed[key]
                    self._rt5_save(file, changed)
                    with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                        exchange._checked_approvals()
                    self._rt5_save(file, original)
        finally:
            self._rt5_save(file, original)

    def test_rt5_b_all_http_and_direct_consumers_fail_closed(self):
        import serve
        sha, file, original = self._rt5_approve()
        self.assertIn("GPT approvata", bridge.approved_html())
        self.assertIn("APPROVATA", serve.decision_home())
        changed = copy.deepcopy(original)
        changed["approvato_utc"] = "1999-01-01T00:00:00+00:00"
        self._rt5_save(file, changed)
        try:
            for page in (bridge.approved_html(), serve.decision_home(),
                         serve.with_controls("<html><body><h2>1 · Decisioni e posizioni</h2>"
                                             "<p>SPOT-ALIVE</p></body></html>"),
                         exchange.render_page("synthetic")):
                self.assertNotIn("Proposta patrimoniale GPT approvata", page)
                self.assertNotIn("APPROVATA · ARCHIVIO", page)
                self.assertIn("STOP", page)
            http = self._rt2_http_gets()
            for endpoint, body in http.items():
                self.assertIn("STOP", body, endpoint)
                self.assertNotIn("Proposta patrimoniale GPT approvata", body, endpoint)
                self.assertNotIn("APPROVATA · ARCHIVIO", body, endpoint)
            self.assertIn("ORIGINAL-SPOT-AVAILABLE", http["/"])
            self.assertIn("href='/mercati/spot'", http["/"])
            with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                exchange.confirm(sha)
        finally:
            self._rt5_save(file, original)
        self.assertIn("APPROVATA", serve.decision_home())

    def test_rt5_c_archive_witness_enrollment_corruption_and_loss(self):
        sha, file, original = self._rt5_approve()
        root = bridge.PRIVATE_ROOT
        witness = root / exchange._WITNESSES / ("a-" + sha + ".json")
        enrollment = root / exchange._ENROLLMENT
        for name, path in (("approval", file), ("witness", witness),
                           ("enrollment", enrollment)):
            backup = path.read_bytes()
            for variant in ("corrupt", "delete", "mode"):
                with self.subTest(path=name, variant=variant):
                    if variant == "corrupt":
                        path.write_bytes(b'{"tampered":true}' + bytes([10]))
                    elif variant == "delete":
                        path.unlink()
                    else:
                        path.chmod(0o644)
                    try:
                        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                            exchange._checked_approvals()
                    finally:
                        path.write_bytes(backup)
                        path.chmod(0o600)
                    self.assertIn(sha, exchange._checked_approvals())
        # Modify both witness and archived record coherently while leaving
        # the durable enrollment hash untouched; this MUST STILL FAIL.
        e = bridge.strict_json(enrollment.read_bytes())
        proof = bridge.strict_json(witness.read_bytes())
        changed = copy.deepcopy(original)
        changed["approvato_utc"] = "1999-01-01T00:00:00+00:00"
        proof["record"] = changed
        proof["record_sha256"] = bridge.digest(changed)
        try:
            self._rt5_save(file, changed)
            self._rt5_save(witness, proof)
            with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                exchange._checked_approvals()
            self.assertEqual(bridge.strict_json(enrollment.read_bytes()), e)
        finally:
            self._rt5_save(file, original)
            proof["record"] = original
            proof["record_sha256"] = bridge.digest(original)
            self._rt5_save(witness, proof)
        self.assertIn(sha, exchange._checked_approvals())

    def test_rt5_c_replaced_archive_inode_stays_unattested(self):
        import os
        sha, file, original = self._rt5_approve()
        replacement = file.with_name(".rt5-synthetic-substitution")
        altered = copy.deepcopy(original)
        altered["approvato_utc"] = "2001-01-01T00:00:00+00:00"
        try:
            self._rt5_save(replacement, altered)
            replacement.chmod(0o600)
            os.replace(replacement, file)
            with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                exchange._checked_approvals()
        finally:
            replacement.unlink(missing_ok=True)
            self._rt5_save(file, original)
        self.assertIn(sha, exchange._checked_approvals())

    def test_rt5_d_pre_rename_uncertain_recovery_is_not_approved(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        actual_rename = os.rename
        failed = [False]
        def fault(source, destination):
            if (Path(destination).parent.name == bridge.ARCHIVE
                    and Path(destination).name == sha + ".json"):
                failed[0] = True
                raise OSError(errno.EIO, "archive before rename")
            return actual_rename(source, destination)
        with mock.patch.object(bridge.os, "rename", side_effect=fault):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.confirm(sha)
        self.assertTrue(failed[0])
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange._checked_approvals()
        self.assertEqual(bridge.reconcile_archive(), ["NON_PUBBLICATO"])
        # The original write-ahead witness remains forensic evidence: there
        # can be no automatic retry or invented successful publication.
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})

    def test_rt5_d_before_witness_failure_does_not_publish(self):
        import errno
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        with mock.patch.object(exchange, "_write_witness",
                               side_effect=OSError(errno.EIO, "before witness")):
            with self.assertRaises(OSError):
                exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})
        self.assertEqual(exchange._checked_approvals(), {})
        self.assertEqual(exchange.confirm(sha)["stato"], "INSERITO")
        self.assertEqual(exchange.confirm(sha)["stato"], "GIA_PRESENTE")
        self.assertEqual(len(exchange._checked_approvals()), 1)

    def test_rt5_d_after_witness_before_commit_stops_with_evidence(self):
        import errno
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        with mock.patch.object(bridge, "_exclusive_json_locked",
                               side_effect=OSError(errno.EIO, "before commit")):
            with self.assertRaises(OSError):
                exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})
        proof = bridge.PRIVATE_ROOT / exchange._WITNESSES / ("a-" + sha + ".json")
        self.assertTrue(proof.is_file())
        self.assertIn("record_sha256", bridge.strict_json(proof.read_bytes()))
        for action in (lambda: exchange._checked_approvals(), lambda: exchange.confirm(sha),
                       lambda: exchange.receive(bridge.canonical(self.original.plan))):
            with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
                action()

    def test_rt5_d_after_witness_fsync_uncertain_stops(self):
        import errno
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        actual_sync = bridge._sync_dir
        def fault(folder):
            if Path(folder).name == exchange._WITNESSES:
                raise OSError(errno.EIO, "post witness fsync")
            return actual_sync(folder)
        with mock.patch.object(bridge, "_sync_dir", side_effect=fault):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange._checked_approvals()

    def test_rt5_d_after_archive_rename_uncertain_explicit_recovery(self):
        import errno
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        actual_sync = bridge._sync_dir
        archive_syncs = [0]
        def fault(folder):
            if Path(folder).name == bridge.ARCHIVE:
                archive_syncs[0] += 1
                # First fsync persists the journal; second follows rename.
                if archive_syncs[0] == 2:
                    raise OSError(errno.EIO, "after archive rename before dir fsync")
            return actual_sync(folder)
        with mock.patch.object(bridge, "_sync_dir", side_effect=fault):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.confirm(sha)
        self.assertEqual(archive_syncs[0], 2)
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange._checked_approvals()
        self.assertEqual(bridge.reconcile_archive(), ["PUBBLICATO_CONFERMATO"])
        doc = exchange._checked_approvals()[sha]
        when = doc["approvato_utc"]
        self.assertEqual(exchange.confirm(sha)["stato"], "GIA_PRESENTE")
        self.assertEqual(exchange._checked_approvals()[sha]["approvato_utc"], when)
        self.assertEqual(len(bridge.load_archive()), 1)

    def test_rt5_e_legacy_id_only_cannot_auto_attest(self):
        sha, file, original = self._rt5_approve()
        root = bridge.PRIVATE_ROOT
        witness = root / exchange._WITNESSES / ("a-" + sha + ".json")
        enrollment = root / exchange._ENROLLMENT
        old = bridge.strict_json(enrollment.read_bytes())
        old["schema"] = "kdd_decision_enrollment_v001"
        old["approvals"] = [sha]
        self._rt5_save(enrollment, old)
        old_proof = {"schema": "kdd_decision_witness_v001",
                     "kind": "a", "sha": sha, "record": {"versione_sha256": sha}}
        self._rt5_save(witness, old_proof)
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange._checked_approvals()
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="NEW", acknowledgement="INIZIALIZZO_NUOVO_STORICO")
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="RECONCILE", acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
                expected_sha256="0"*64)
        # Synthetic evidence removed from original names only for an EXPLICIT
        # independently attested reconciliation test, never auto migration.
        enrollment.rename(root / "old-enrollment-forensic")
        (root / exchange._WITNESSES).rename(root / "old-witnesses-forensic")
        expected = exchange._continuity_snapshot([], {sha: original})
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="RECONCILE", acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
                expected_sha256=expected)
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange.initialize_decision_continuity(
                mode="RECONCILE", acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
                expected_sha256=expected, verified_approval_hashes={sha: "0"*64})
        result = exchange.initialize_decision_continuity(
            mode="RECONCILE", acknowledgement="RICONCILIO_STORICO_PRECEDENTE",
            expected_sha256=expected,
            verified_approval_hashes={sha: bridge.digest(original)})
        self.assertEqual(result["approvazioni"], 1)
        self.assertEqual(exchange._checked_approvals()[sha], original)

    def test_rt5_d_enrollment_replace_uncertain_preserves_staging_or_stop(self):
        import errno
        import os
        self.original.persist_origin()
        sha = exchange.receive(bridge.canonical(self.original.plan))
        root = bridge.PRIVATE_ROOT
        target = root / exchange._ENROLLMENT
        original = os.replace
        def fault(source, destination):
            original(source, destination)
            if Path(destination) == target:
                raise OSError(errno.EIO, "post replace uncertainty")
        with mock.patch.object(exchange.os, "replace", side_effect=fault):
            with self.assertRaises(bridge.PublicationUncertain):
                exchange.confirm(sha)
        self.assertEqual(bridge.load_archive(), {})
        with self.assertRaisesRegex(bridge.BridgeError, "STOP DECISIONI"):
            exchange._checked_approvals()
        self.assertTrue((root / exchange._ENROLLMENT).exists())



if __name__ == "__main__":
    unittest.main()
