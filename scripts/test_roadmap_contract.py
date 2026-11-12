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
        # KDD-01 e stato formalmente chiuso il 12/11: mutare un ID aperto.
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace("- [ ] KDD-02", "- [x] KDD-02", 1))

    def test_status_complete_without_checkbox_stops(self):
        item = next(line for line in self.content.splitlines() if "KDD-02 |" in line)
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace(item, item.replace("| PARZIALE |", "| COMPLETO |"), 1))

    def test_complete_needs_proof_and_author_go(self):
        item = next(line for line in self.content.splitlines()
                    if line.startswith("| - [ ] KDD-02 |"))
        changed = item.replace("- [ ]", "- [x]").replace("| PARZIALE |",
                                                          "| COMPLETO |")
        with self.assertRaises(contract.GateError):
            contract.parse(self.content.replace(item, changed, 1))

    def test_complete_with_proof_and_author_go_is_structurally_valid(self):
        item = next(line for line in self.content.splitlines()
                    if line.startswith("| - [ ] KDD-02 |"))
        changed = (item.replace("- [ ]", "- [x]")
                       .replace("| PARZIALE |", "| COMPLETO |")
                       .replace("CODICE/TEST:",
                                "PROVA: fixture strutturale indipendente; GO-AUTORE: decisione-test-sintetica; CODICE/TEST:", 1))
        self.assertEqual(contract.parse(self.content.replace(item, changed, 1))
                         ["KDD-02"][2], "COMPLETO")

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
                "GO-MERGE: PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE\n"
                "ROADMAP-MODALITA: DOCUMENTALE\n")
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
                "GO-MERGE: PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE\n"
                "ROADMAP-MODALITA: DOCUMENTALE\n")
        with patch.object(contract, "git", side_effect=fake_git):
            with self.assertRaises(contract.GateError):
                contract.check_pr(base, head, body)


    def test_canonical_kdd05_title_and_all_29_unchanged(self):
        rows = contract.parse(self.content)
        self.assertEqual(len(rows), 29)
        self.assertEqual(
            contract.plain(rows["KDD-05"][1]),
            "Liquidità operativa indicativa di circa 150 USDC, finanziamento e alternative")
        self.assertEqual(
            [contract.plain(row[1]) for row in rows.values()], contract.TITLES)
        current_line = next(line for line in self.content.splitlines()
                            if line.startswith("| - [ ] KDD-05 |"))
        old = self.content.replace(
            current_line,
            current_line.replace(
                "Liquidità operativa indicativa di circa 150 USDC, finanziamento e alternative",
                "Liquidità USDC e scenari per almeno 150 EUR equivalenti"),
            1)
        self.assertNotEqual(old, self.content)
        with self.assertRaises(contract.GateError):
            contract.parse(old)

    def _technical_gate(self, *, base_text=None, head_text=None, changed_files="serve.py\n",
                        mode="TECNICA-SENZA-MODIFICA", register=True,
                        ids="KDD-05", mandate=True, go=True, ref_number="31",
                        readme_before=None, readme_after=None,
                        subentro_before=None, subentro_after=None):
        base, head = "a" * 40, "b" * 40
        before = self.content if base_text is None else base_text
        after = self.content if head_text is None else head_text
        blob = "c" * 40
        def fake_git(*args):
            table = {
                ("show", f"{base}:ROADMAP_KDD.md"): before,
                ("show", f"{head}:ROADMAP_KDD.md"): after,
                ("diff", "--name-only", base, head): changed_files,
                ("rev-parse", f"{base}:ROADMAP_KDD.md"): blob + "\n",
                ("show", f"{base}:README.md"): readme_before,
                ("show", f"{head}:README.md"): readme_after,
                ("show", f"{base}:SUBENTRO_SUPERVISIONE_APICALE.md"): subentro_before,
                ("show", f"{head}:SUBENTRO_SUPERVISIONE_APICALE.md"): subentro_after}
            return table[args]
        parts = [
            f"ROADMAP-IDS: {ids}",
            "MANDATO-AUTORE: mandato reale riferito al lavoro autorizzato" if mandate
            else "SENZA-MANDATO: riferimento mancante",
            "PROVE: test e confronto GitHub verificabile",
            "GO-MERGE: PENDENTE - SERVE DECISIONE ESPLICITA DELL'AUTORE"
            if go else "GO-MERGE: AUTORIZZATO DAL PROGRAMMA",
            f"ROADMAP-MODALITA: {mode}"]
        if register:
            parts.append(f"SUPERVISIONE-REGISTRO: ROADMAP_KDD.md@{blob}; PR #{ref_number}")
        with patch.object(contract, "git", side_effect=fake_git):
            return contract.check_pr(base, head, "\n".join(parts) + "\n", pr_number="31")

    def test_technical_pr_with_independent_supervision_registration_passes(self):
        result = self._technical_gate()
        self.assertEqual(result["mode"], "TECNICA-SENZA-MODIFICA")
        self.assertEqual(result["changed_ids"], [])
        self.assertEqual(result["declared_ids"], ["KDD-05"])

    def test_technical_pr_missing_registration_mandate_and_invalid_ids_stop(self):
        for params in ({"register": False}, {"ref_number": "32"},
                       {"mandate": False}, {"ids": "KDD-99"},
                       {"ids": "KDD-05, KDD-05"}, {"go": False},
                       {"changed_files": ""}):
            with self.subTest(params=params), self.assertRaises(contract.GateError):
                self._technical_gate(**params)

    def test_fake_roadmap_modification_and_unregistered_pr_stop(self):
        with self.assertRaises(contract.GateError):
            self._technical_gate(mode="DOCUMENTALE")
        with self.assertRaises(contract.GateError):
            self._technical_gate(changed_files="ROADMAP_KDD.md\nserve.py\n")
        # A claim in the PR description cannot manufacture supervisor evidence.
        changed = self.content.replace("[PR #31]", "[PR #999]", 1)
        with self.assertRaises(contract.GateError):
            self._technical_gate(base_text=changed, head_text=changed)

    def test_rt_int_a_operational_readme_mutation_rejected_for_technical_pr(self):
        """README history remains byte-identical, but operational guidance changes."""
        archive = contract.ARCHIVE_MARKER + "\nARCHIVIO STORICO IDENTICO\n"
        before = "# Istruzioni operative\nSolo supervisione modifica il governo.\n" + archive
        after = "# Istruzioni operative\nLa costruttrice può decidere i GO.\n" + archive
        self.assertEqual(before.split(contract.ARCHIVE_MARKER)[1],
                         after.split(contract.ARCHIVE_MARKER)[1])
        self.assertNotEqual(before, after)
        with self.assertRaises(contract.GateError):
            self._technical_gate(
                changed_files="README.md\nserve.py\n",
                readme_before=before, readme_after=after)

    def test_rt_int_b_subentro_mutation_rejected_for_technical_pr(self):
        """A technical PR must not rewrite the Supervisione's handoff mandate."""
        before = "La Supervisione apicale decide il GO e conserva la Roadmap.\n"
        after = "La Costruttrice decide il GO e conserva la Roadmap.\n"
        self.assertNotEqual(before, after)
        with self.assertRaises(contract.GateError):
            self._technical_gate(
                changed_files="SUBENTRO_SUPERVISIONE_APICALE.md\nserve.py\n",
                subentro_before=before, subentro_after=after)

    def test_branch_cannot_invent_new_completo_even_with_fake_go_marker(self):
        before = self.content
        line = next(x for x in before.splitlines()
                    if x.startswith("| - [ ] KDD-02 |"))
        completed = (line.replace("- [ ]", "- [x]")
                         .replace("| PARZIALE |", "| COMPLETO |")
                         .replace("CODICE/TEST:",
                                  "PROVA: result-verified-123; GO-AUTORE: fake-author-decision-123; CODICE/TEST:", 1))
        after = before.replace(line, completed, 1)
        self.assertNotEqual(after, before)
        with self.assertRaises(contract.GateError):
            self._technical_gate(
                head_text=after, changed_files="ROADMAP_KDD.md\n",
                mode="DOCUMENTALE", ids="KDD-02")


if __name__ == "__main__":
    unittest.main()
