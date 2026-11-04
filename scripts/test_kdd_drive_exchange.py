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
        self.assertIn("STOP FolderSync legacy", home)
        self.assertIn("IN ATTESA DI DECISIONE", home)
        self.assertIn(plan_sha, home)
        page = exchange.render_page("SYNTHETIC")
        self.assertIn("STOP FolderSync legacy", page)
        self.assertIn("NON APPROVATA", page)
        self.assertIn(plan_sha, page)
        self.assertEqual(bridge.load_archive(), {})


if __name__ == "__main__":
    unittest.main()
