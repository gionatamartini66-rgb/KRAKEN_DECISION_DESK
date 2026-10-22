"""Tests commit ambiguity and directory rename using synthetic temporary files."""
import unittest
from scripts import kdd_publication_lab as p

class PublicationStateTests(unittest.TestCase):
    def test_pre_file_sync_error_is_prepublication(self):
        x=p.simulate(fail_stage='fsync_file')
        self.assertEqual(x.stato,p.ERRORE_PRIMA_DELLA_PUBBLICAZIONE)
        self.assertFalse(x.osservata_pubblicazione)
    def test_pre_dir_sync_error_is_prepublication(self):
        x=p.simulate(fail_stage='fsync_pre')
        self.assertEqual(x.stato,p.ERRORE_PRIMA_DELLA_PUBBLICAZIONE)
        self.assertFalse(x.osservata_pubblicazione)
    def test_rename_error_is_at_least_uncertain(self):
        self.assertEqual(p.simulate(fail_stage='rename').stato,p.PUBBLICAZIONE_INCERTA)
    def test_post_rename_fsync_fails_but_file_was_committed(self):
        x=p.simulate(fail_stage='fsync_post')
        self.assertEqual(x.stato,p.PUBBLICAZIONE_INCERTA)
        self.assertTrue(x.osservata_pubblicazione)
    def test_confirmed_in_clean_lab(self):
        self.assertEqual(p.simulate().stato,p.PUBBLICATO_CONFERMATO)
    def test_rename_directory_does_not_pin_path(self):
        x=p.simulate(move_before_rename=True)
        self.assertTrue(x.dir_spostata)
        self.assertTrue(x.osservata_pubblicazione)
        # Success at a renamed inode proves that dirfd-based rename does NOT
        # guarantee publication at the former approved pathname.
    def test_renamed_container_post_fsync_failure(self):
        x=p.simulate(move_before_rename=True,fail_stage='fsync_post')
        self.assertEqual(x.stato,p.PUBBLICAZIONE_INCERTA)
        self.assertTrue(x.dir_spostata)

if __name__=='__main__': unittest.main()