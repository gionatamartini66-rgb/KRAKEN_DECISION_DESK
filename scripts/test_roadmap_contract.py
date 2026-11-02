"""Independent negative/positive checks for the KDD roadmap guard; no network."""
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import check_roadmap_contract as contract


class RoadmapContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = Path("ROADMAP_KDD.md").read_text(encoding="utf-8")

    def test_29_rows_exactly_in_order(self):
        rows = contract.parse(self.content)
        self.assertEqual(len(rows), 29)
        self.assertEqual(list(rows), [f"KDD-{i:02d}" for i in range(1, 30)])

    def test_deleted_row_stops(self):
        item = next(line for line in self.content.splitlines() if "KDD-17 |" in line)
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace(item + "\n", "", 1))

    def test_renumbered_and_duplicate_id_stop(self):
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace("KDD-17 |", "KDD-16 |", 1))

    def test_title_rewrite_stops(self):
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace("Quattro timeframe per ogni posizione",
                                                "Un timeframe facoltativo", 1))

    def test_checkbox_without_go_stops(self):
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace("- [ ] KDD-01", "- [x] KDD-01", 1))

    def test_status_complete_without_checkbox_stops(self):
        item = next(line for line in self.content.splitlines() if "KDD-02 |" in line)
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace(item, item.replace("| PARZIALE |", "| COMPLETO |"), 1))

    def test_complete_needs_proof_and_author_go(self):
        item = next(line for line in self.content.splitlines() if "KDD-01 |" in line)
        changed = item.replace("- [ ]", "- [x]").replace("| PRESENTE_DA_ACCETTARE |",
                                                          "| COMPLETO |")
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace(item, changed, 1))

    def test_complete_with_proof_and_author_go_is_structurally_valid(self):
        item = next(line for line in self.content.splitlines() if "KDD-01 |" in line)
        changed = (item.replace("- [ ]", "- [x]")
                       .replace("| PRESENTE_DA_ACCETTARE |", "| COMPLETO |")
                       .replace("**E**:", "PROVA: PR #21 + refresh reale 02/11; GO-AUTORE: decisione-autore-ref-123; **E**:", 1))
        self.assertEqual(contract.parse(self.content.replace(item, changed, 1))
                         ["KDD-01"][2], "COMPLETO")

    def test_pr_requires_mandate_and_exact_ids(self):
        base = "a" * 40
        head = "b" * 40
        before = self.content
        original = next(line for line in self.content.splitlines() if "KDD-03 |" in line)
        after = self.content.replace(original, original.replace(" | PARZIALE |", " | NON_DIMOSTRATO |"), 1)
        def fake_git(*argv):
            if argv == ("show", f"{base}:ROADMAP_KDD.md"):
                return before
            if argv == ("show", f"{head}:ROADMAP_KDD.md"):
                return after
            if argv == ("diff", "--name-only", base, head):
                return "decision_desk.py\nROADMAP_KDD.md\n"
            raise AssertionError(argv)
        body = ("ROADMAP-IDS: KDD-03\n"
                "MANDATO-AUTORE: intervento tracciato su KDD-03\n"
                "PROVE: collegamento al collaudo e al diff completo\n"
                "GO-MERGE: PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE\n")
        with patch.object(contract, "git", side_effect=fake_git):
            self.assertEqual(contract.check_pr(base, head, body)["changed_ids"], ["KDD-03"])
            with self.assertRaises(contract.GateError):
                contract.check_pr(base, head, body.replace("KDD-03\n", "KDD-08\n", 1))
            with self.assertRaises(contract.GateError):
                contract.check_pr(base, head, body.replace("MANDATO-AUTORE", "SENZA-MANDATO"))

    def test_pr_cannot_modify_governo(self):
        base, head = "a"*40, "b"*40
        before = self.content
        original = next(x for x in before.splitlines() if "KDD-05 |" in x)
        after = before.replace(original, original.replace("| PARZIALE |", "| NON_DIMOSTRATO |"), 1)
        def fake_git(*argv):
            if argv == ("show", f"{base}:ROADMAP_KDD.md"):
                return before
            if argv == ("show", f"{head}:ROADMAP_KDD.md"):
                return after
            if argv == ("diff", "--name-only", base, head):
                return "GOVERNO_KDD.md\nROADMAP_KDD.md\n"
            raise AssertionError(argv)
        body = ("ROADMAP-IDS: KDD-05\n"
                "MANDATO-AUTORE: intervento circoscritto su KDD-05\n"
                "PROVE: verifica indipendente repertoriata per questo lavoro\n"
                "GO-MERGE: PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE\n")
        with patch.object(contract, "git", side_effect=fake_git):
            with self.assertRaises(contract.GateError):
                contract.check_pr(base, head, body)


if __name__ == "__main__":
    unittest.main()
