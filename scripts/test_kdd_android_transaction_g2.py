"""G2 Android rename protocol: process-kill, faults and invariant discriminators.
Synthetic private fixtures only; no Android, accounts, Drive, shared storage or trading.
"""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from scripts import kdd_bridge_g2 as bridge
from scripts import test_kdd_bridge_g2 as legacy_bridge_tests
from scripts.test_kdd_wallet_packet_g0 import T


class AndroidTransactionTests(unittest.TestCase):
    def setUp(self):
        # Reuse the genuine producer fixture; do not mock wallet.build.
        b = legacy_bridge_tests.BridgeG2Tests("test_01_real_original_producer_retains_all_rows_and_eur_provenance")
        b.setUp()
        self.addCleanup(b.doCleanups)
        self.base = b
        self.home, self.private = b.home, b.private
        self.bundle, self.plan = b.bundle, b.plan

    def folder(self, area):
        return bridge.private_directory(area, create=True)

    def obj(self, area):
        if area == bridge.OUTBOX:
            return self.bundle
        version = bridge.digest(self.plan)
        return {"versione_sha256":version,"consenso":"CONFERMATO_DA_COMANDO_UTENTE",
                "approvato_utc":T.isoformat(),"snapshot_id":self.plan["snapshot_id"],
                "proposta":self.plan,"nessun_ordine":True,
                "esecuzione":"NON_ATTESTATA"}

    def version(self, area):
        return bridge.digest(self.bundle if area == bridge.OUTBOX else self.plan)

    def run_child(self, area, phase, payload, *, root=None):
        """A real separate Python process; SIGKILL never executes its finally."""
        td = Path(tempfile.mkdtemp(prefix="child-", dir=self.home))
        fixture = td/"payload.json"
        fixture.write_bytes(bridge.canonical(payload)+b"\n")
        script = r"""
import json,os,signal,sys
from pathlib import Path
from scripts import kdd_bridge_g2 as bridge
bridge.PRIVATE_ROOT=Path(sys.argv[1])
area,phase,fixture=sys.argv[2:]
folder=bridge.private_directory(area,create=True)
obj=json.loads(Path(fixture).read_text())
name=(bridge.digest(obj) if area==bridge.OUTBOX
      else obj["versione_sha256"])+".json"
actual=os.rename
def watched(src,dest):
    if phase=="before-rename":
        os.kill(os.getpid(),signal.SIGKILL)
    result=actual(src,dest)
    if phase=="after-rename":
        os.kill(os.getpid(),signal.SIGKILL)
    return result
os.rename=watched
print(bridge.exclusive_json(folder,name,obj),flush=True)
"""
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(bridge.__file__).resolve().parents[1])
        return subprocess.run([sys.executable,"-B","-c",script,
                               str(root or self.private),area,phase,str(fixture)],
                              cwd=env["PYTHONPATH"],env=env,text=True,
                              capture_output=True,timeout=25)

    def test_g2_no_hardlink_dependency_and_basic_idempotent_approval(self):
        self.base.persist_origin()
        with mock.patch.object(bridge.os,"link",None,create=True):
            self.assertEqual(bridge.verify_local_origin(self.bundle),bridge.digest(self.bundle))
            approved=bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                            "APPROVO_VERSIONE",now=T)
            self.assertEqual(approved["stato"],"INSERITO")
            second=bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                          "APPROVO_VERSIONE",now=T)
            self.assertEqual(second["stato"],"GIA_PRESENTE")
        folder=self.folder(bridge.ARCHIVE)
        self.assertEqual(len(bridge.load_archive()),1)
        self.assertFalse(list(folder.glob(".pending-*")))
        self.assertFalse(list(folder.glob(".resolved-*")))
        self.assertFalse(list(folder.glob(".cancelled-*")))
        self.assertEqual((folder/(bridge.digest(self.plan)+".json")).stat().st_nlink,1)

    def test_g2_real_sigkill_before_and_after_rename_both_areas(self):
        for area in (bridge.ARCHIVE,bridge.OUTBOX):
            for phase in ("before-rename","after-rename"):
                with self.subTest(area=area,phase=phase):
                    # Distinct synthetic state for each test case.
                    isolated=self.home/(area+"-"+phase)
                    with mock.patch.object(bridge,"PRIVATE_ROOT",isolated):
                        name=self.version(area)+".json"
                        dead=self.run_child(area,phase,self.obj(area),root=isolated)
                        self.assertEqual(dead.returncode,-9,dead.stderr)
                        folder=self.folder(area)
                        pending=folder/(".pending-"+name)
                        final=folder/name
                        self.assertTrue(pending.is_file())
                        self.assertEqual(final.exists(),phase=="after-rename")
                        if area==bridge.OUTBOX:
                            with self.assertRaises(bridge.BridgeError):
                                bridge.verify_local_origin(self.bundle)
                        else:
                            if phase=="before-rename":
                                # Pending without a published final hides the
                                # tentative decision without falsely approving.
                                self.assertEqual(bridge.load_archive(),{})
                            else:
                                with self.assertRaises(bridge.BridgeError):
                                    bridge.load_archive()
                        # The next process, not the killed writer, reconciles.
                        next_process=subprocess.run([
                            sys.executable,"-B","-c",
                            "from pathlib import Path;from scripts import kdd_bridge_g2 as b;"
                            "import sys;b.PRIVATE_ROOT=Path(sys.argv[1]);"
                            "print(b.reconcile_directory(sys.argv[2]))",
                            str(isolated),area],
                            cwd=str(Path(bridge.__file__).resolve().parents[1]),
                            env={**os.environ,"PYTHONPATH":str(Path(bridge.__file__).resolve().parents[1])},
                            text=True,capture_output=True,timeout=25)
                        self.assertEqual(next_process.returncode,0,next_process.stderr)
                        expected=("PUBBLICATO_CONFERMATO" if phase=="after-rename"
                                  else "NON_PUBBLICATO")
                        self.assertIn(expected,next_process.stdout)
                        self.assertFalse(pending.exists())
                        self.assertFalse(list(folder.glob(".kdd-stage-*.tmp")))
                        self.assertEqual(final.exists(),phase=="after-rename")
                        self.assertEqual(bridge.reconcile_directory(area),[])
                        if final.exists():
                            self.assertEqual(final.stat().st_nlink,1)
                            self.assertEqual(bridge.read_regular(final,expected_parent=folder),
                                             bridge.canonical(self.obj(area))+b"\n")

    def test_g2_fsync_postrename_uncertain_keeps_read_gate(self):
        for area in (bridge.ARCHIVE,bridge.OUTBOX):
            isolated=self.home/("fsync-"+area)
            with mock.patch.object(bridge,"PRIVATE_ROOT",isolated):
                folder=self.folder(area)
                name=self.version(area)+".json"
                actual=bridge._sync_dir
                def fail_after_rename(path):
                    if (folder/name).exists():
                        raise OSError("SYNTHETIC directory fsync failure")
                    return actual(path)
                with mock.patch.object(bridge,"_sync_dir",side_effect=fail_after_rename):
                    with self.assertRaises(bridge.PublicationUncertain):
                        bridge.exclusive_json(folder,name,self.obj(area))
                self.assertTrue((folder/name).is_file())
                self.assertTrue((folder/(".pending-"+name)).is_file())
                if area==bridge.ARCHIVE:
                    with self.assertRaises(bridge.BridgeError):
                        bridge.load_archive()
                else:
                    with self.assertRaises(bridge.BridgeError):
                        bridge.verify_local_origin(self.bundle)
                self.assertEqual(bridge.reconcile_directory(area),
                                 ["PUBBLICATO_CONFERMATO"])
                self.assertFalse((folder/(".pending-"+name)).exists())
                self.assertEqual(bridge.exclusive_json(folder,name,self.obj(area)),
                                 "GIA_PRESENTE")

    def test_g2_symlink_journal_and_unknown_staging_stop_without_deletion(self):
        for area in (bridge.OUTBOX,bridge.ARCHIVE):
            isolated=self.home/("symlink-"+area)
            with mock.patch.object(bridge,"PRIVATE_ROOT",isolated):
                folder=self.folder(area)
                name=self.version(area)+".json"
                journal=folder/(".pending-"+name)
                journal.symlink_to(folder/"absent-target")
                with self.assertRaises(bridge.BridgeError):
                    bridge.reconcile_directory(area)
                with self.assertRaises(bridge.BridgeError):
                    bridge.exclusive_json(folder,name,self.obj(area))
                self.assertTrue(journal.is_symlink())
                journal.unlink()
                alien=folder/".kdd-stage-unknown.tmp"
                alien.write_text("SYNTHETIC")
                alien.chmod(0o600)
                with self.assertRaisesRegex(bridge.BridgeError,"Staging senza"):
                    bridge.exclusive_json(folder,name,self.obj(area))
                self.assertTrue(alien.is_file())

    def test_g2_verified_journal_identity_rejects_wrong_inode_and_permissions(self):
        for area in (bridge.OUTBOX,bridge.ARCHIVE):
            isolated=self.home/("tamper-"+area)
            with mock.patch.object(bridge,"PRIVATE_ROOT",isolated):
                folder=self.folder(area)
                name=self.version(area)+".json"
                proc=self.run_child(area,"before-rename",self.obj(area),root=isolated)
                self.assertEqual(proc.returncode,-9)
                journal=folder/(".pending-"+name)
                marker=bridge.strict_json(journal.read_bytes())
                stage=folder/marker["stage"]
                os.chmod(stage,0o644)
                with self.assertRaises(bridge.BridgeError):
                    bridge.reconcile_directory(area)
                self.assertTrue(stage.is_file())
                self.assertTrue(journal.is_file())
                os.chmod(stage,0o600)
                marker["inode"]+=1
                journal.write_bytes(bridge.canonical(marker)+b"\n")
                journal.chmod(0o600)
                with self.assertRaises(bridge.BridgeError):
                    bridge.reconcile_directory(area)
                self.assertTrue(stage.exists())
                self.assertFalse((folder/name).exists())

    def test_g2_concurrent_cooperative_writers_exactly_one(self):
        for area in (bridge.OUTBOX,bridge.ARCHIVE):
            isolated=self.home/("concurrent-"+area)
            with mock.patch.object(bridge,"PRIVATE_ROOT",isolated):
                folder=self.folder(area)
                obj=self.obj(area); name=self.version(area)+".json"
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(lambda _:bridge.exclusive_json(folder,name,obj),(1,2)))
                self.assertCountEqual(results,["INSERITO","GIA_PRESENTE"])
                self.assertEqual(len(list(folder.glob(name))),1)
                self.assertEqual(bridge.read_regular(folder/name,expected_parent=folder),
                                 bridge.canonical(obj)+b"\n")

    def test_g2_concurrent_revisions_one_head(self):
        self.base.persist_origin()
        root=bridge.digest(self.plan)
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,root,
                                               "APPROVO_VERSIONE",now=T)["stato"],"INSERITO")
        candidates=[]
        for i in (1,2):
            q=copy.deepcopy(self.plan)
            q["proposta_id"]="SYNTH-R-"+str(i)
            q["sostituisce_sha256"]=root
            candidates.append(q)
        def submit(q):
            try:
                return bridge.approved_import(q,self.bundle,bridge.digest(q),
                                              "APPROVO_VERSIONE",now=T)["stato"]
            except bridge.BridgeError:
                return "STOP"
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(submit,candidates))
        self.assertCountEqual(statuses,["INSERITO","STOP"])
        self.assertEqual(len(bridge.load_archive()),2)

    def test_g2_missing_origin_coherent_forgery_and_consent_not_implicit(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                   "APPROVO_VERSIONE",now=T)
        forged=copy.deepcopy(self.bundle)
        forged["provenienza"]="KDD_LOCALE_DICHIARATA_NON_AUTENTICATA"
        forged["packet"]["scenario_mercato_kdd"]="Mutated fixture"
        forged["packet_sha256"]=bridge.digest(forged["packet"])
        forged_plan=copy.deepcopy(self.plan)
        forged_plan["snapshot_id"]=forged["packet_sha256"]
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(forged_plan,forged,bridge.digest(forged_plan),
                                   "APPROVO_VERSIONE",now=T)
        self.base.persist_origin()
        for consent,version in [("NO",bridge.digest(self.plan)),("APPROVO_VERSIONE","0"*64)]:
            with self.assertRaises(bridge.BridgeError):
                bridge.approved_import(self.plan,self.bundle,version,consent,now=T)
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                               "APPROVO_VERSIONE",now=T)["stato"],"INSERITO")

    def test_g2_spot_validator_rejects_future_schema_but_storage_is_generic(self):
        # This is a DATA contract fixture, NOT a Futures position or engine.
        fake={"schema":"kdd_future_analysis_packet_v001", "strumento":"SYNTH",
              "collaterale":"TEST-NON-REALI","no_trading":True}
        with self.assertRaises(bridge.BridgeError):
            bridge.read_context(fake,now=T)
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_proposal(fake,self.bundle,now=T)
        # The SAME generic byte persistence handles a named version; no
        # financial-field interpretation in exclusive_json itself.
        folder=self.folder(bridge.OUTBOX)
        name=bridge.digest(fake)+".json"
        self.assertEqual(bridge.exclusive_json(folder,name,fake),"INSERITO")
        self.assertEqual(bridge.strict_json(bridge.read_regular(folder/name)),fake)
        with self.assertRaises(bridge.BridgeError):
            bridge._validate_transaction_document(folder,name,
                          bridge.read_regular(folder/name))

    def test_g2_dashboard_does_not_propagate_corruption(self):
        self.base.persist_origin()
        self.assertEqual(bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                               "APPROVO_VERSIONE",now=T)["stato"],"INSERITO")
        folder=self.folder(bridge.ARCHIVE)
        (folder/(bridge.digest(self.plan)+".json")).write_text('{"broken":')
        self.assertIn("STOP",bridge.approved_html())
        import serve
        self.assertIn("Proposte",serve.with_controls("<html><body><h2>1 · Decisioni e posizioni</h2></body></html>"))

    def test_g2_mutant_origin_bypass_detected_on_temporary_copy(self):
        original=Path(bridge.__file__).read_text()
        needle="    verify_local_origin(bundle)\n    validate_proposal(proposal, bundle, now=now)"
        self.assertIn(needle,original)
        mutant=original.replace(needle,
                                "    # MUTANT: origin check suppressed\n    validate_proposal(proposal, bundle, now=now)",1)
        path=self.home/"mutated_bridge_g2.py"
        path.write_text(mutant)
        spec=importlib.util.spec_from_file_location("mutated_bridge_g2",path)
        broken=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(broken)
        broken.PRIVATE_ROOT=self.private
        # A valid positive proposal with missing outbox MUST be rejected by
        # original; mutation is falsified when it instead publishes.
        with self.assertRaises(bridge.BridgeError):
            bridge.approved_import(self.plan,self.bundle,bridge.digest(self.plan),
                                   "APPROVO_VERSIONE",now=T)
        result=broken.approved_import(self.plan,self.bundle,broken.digest(self.plan),
                                      "APPROVO_VERSIONE",now=T)
        self.assertEqual(result["stato"],"INSERITO")
        self.assertEqual(len(broken.load_archive()),1)


if __name__=="__main__":
    unittest.main()
