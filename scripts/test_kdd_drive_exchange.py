"""Real bridge + user-interface handoff tests; no Drive/network/phone involved."""
import copy
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

    def test_handle_rejects_implicit_consent(self):
        self.original.persist_origin()
        self.assertIn("NON approvata",exchange.handle("ricevi",bridge.canonical(self.original.plan)))
        with self.assertRaises(bridge.BridgeError):
            exchange.handle("conferma",json.dumps({"sha256":"0"*64}).encode())
        with self.assertRaises(bridge.BridgeError):
            exchange.handle("conferma",json.dumps({"sha256":bridge.digest(self.original.plan),
                                                 "consent":"APPROVO_VERSIONE"}).encode())
        self.assertEqual(bridge.load_archive(),{})


if __name__ == "__main__":
    unittest.main()
