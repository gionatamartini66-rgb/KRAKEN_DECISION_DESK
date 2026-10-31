"""Transparent R5 -> Android regression map. NO skips, xfails or deletions.

The 18 legacy tests below intentionally exercise R5 hardlink/nlink2 and
immutable per-attempt completed receipts that are NOT states of the Android
rename protocol. Historical R5 suite runs, unmodified, in a distinct CI job.
Every other original R5 bridge test executes unchanged against Android bridge.
Each replacement is a named, executable new Android test; gaps are explicit.
"""
import unittest
from scripts.test_kdd_bridge_g2 import BridgeG2Tests
from scripts.test_kdd_android_transaction_g2 import AndroidTransactionTests

REPLACED_R5 = {
    "test_r2_orphan_stage_inert_archive_recoverable": ("stage_orphan", "test_g2_symlink_journal_and_unknown_staging_stop_without_deletion"),
    "test_r2_post_link_interrupt_yields_complete_final_and_idempotent_retry": ("nlink2_postlink", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt2_malicious_stage_wrong_inode_and_symlink_stops": ("stage_inode", "test_g2_verified_journal_identity_rejects_wrong_inode_and_permissions"),
    "test_rt3_a_forced_attempt_collision_preserves_prior_and_current_evidence": ("perattempt_marker", "test_g2_symlink_journal_and_unknown_staging_stop_without_deletion"),
    "test_rt3_a_legacy_forensic_marker_remains_separate_from_new_attempt": ("old_receipts", "test_g2_symlink_journal_and_unknown_staging_stop_without_deletion"),
    "test_r2_interruption_before_link_no_partial_final_retry": ("link_crash", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_r2_live_reader_never_sees_uncommitted_partial_final": ("link_hook", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt1_04_postlink_semantic_failure_is_publication_uncertain": ("link_specific", "test_g2_fsync_postrename_uncertain_keeps_read_gate"),
    "test_rt1_04_unclean_prelink_crash_requires_explicit_reconcile": ("link_hook", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt2_extra_unattributable_hardlink_rejected": ("nlink3", "test_g2_verified_journal_identity_rejects_wrong_inode_and_permissions"),
    "test_rt2_orphan_stage_not_deleted_by_glob": ("postlink_hardlink", "test_g2_symlink_journal_and_unknown_staging_stop_without_deletion"),
    "test_rt2_postlink_exception_before_link_return_remains_uncertain": ("link_wrapper", "test_g2_fsync_postrename_uncertain_keeps_read_gate"),
    "test_rt2_real_sigkill_after_link_archive_nlink2_and_recovery": ("nlink2", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt2_real_sigkill_before_cleanup_outbox": ("hardlink_cleanup", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt2_real_sigkill_during_reconciliation_then_retry": ("stage_unlink_recovery", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt3_a_changed_attempt_id_is_rejected_without_cleanup": ("forensic_receipt", "test_g2_verified_journal_identity_rejects_wrong_inode_and_permissions"),
    "test_rt3_a_four_consecutive_cancelled_attempts_same_version_both_areas": ("forensic_receipts", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
    "test_rt3_a_real_sigkill_before_and_after_forensic_marking": ("old_rename_marker", "test_g2_real_sigkill_before_and_after_rename_both_areas"),
}


def main():
    full = sorted(name for name in dir(BridgeG2Tests) if name.startswith("test_"))
    if len(REPLACED_R5) != 18 or not set(REPLACED_R5).issubset(full):
        raise SystemExit("STOP: regression map stale against R5 original")
    android = set(name for name in dir(AndroidTransactionTests) if name.startswith("test_"))
    bad = [(old, substitute) for old, (_, substitute) in REPLACED_R5.items()
           if substitute not in android]
    if bad:
        raise SystemExit("STOP: missing explicit Android replacement: "+repr(bad))
    retained = sorted(set(full) - set(REPLACED_R5))
    print("R5 historical methods:", len(full),
          "| physically obsolete on Android:", len(REPLACED_R5),
          "| unchanged original tests executed:", len(retained), flush=True)
    for old, (reason, substitute) in sorted(REPLACED_R5.items()):
        print("HISTORICAL-ONLY R5:", old,
              "| obsolete mechanism:", reason,
              "| Android replacement:", substitute, flush=True)
    suite = unittest.TestSuite(BridgeG2Tests(n) for n in retained)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("STOP: retained R5 properties regressed")


if __name__ == "__main__":
    main()
