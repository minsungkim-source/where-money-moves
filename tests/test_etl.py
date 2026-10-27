"""Regression tests for the parsers. Each guard exists because a real file once looked like this.

  python -m unittest discover -s tests -v

BOT sheets are synthesised (the real zip is 9MB); SSO and DOPA use a real file each, trimmed to nothing.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "etl"))

import etl          # noqa: E402
import summary      # noqa: E402
import th_dopa      # noqa: E402
import th_sso       # noqa: E402

W = 16  # read_all asks openpyxl for 16 columns


def pad(*cells):
    return tuple(list(cells) + [None] * (W - len(cells)))


def bot_rows(layout=3, n=210, month="July 2026", mutate=None):
    """A BOT district sheet: title, as-of, unit, header, sub-header, Head Office, one province, n districts."""
    sub = ["Current", "Saving", "Time ", "Promissory Note", " NCD", "Total", "Overdraft", "Loan"]
    sub += ["Bills and Others", "Total"] if layout == 3 else ["Bills", "Others", "Total"]
    rows = [pad("Report on Deposits and Credits Classified by Districts*"), pad(f"Outstanding As of {month}"),
            pad(*([None] * 11 + ["Unit : Million Baht"])), pad("Provinces/Districts", "No.of branches", "Deposits"),
            pad(None, None, *sub)]

    def rec(name, br, dep_parts, cr_parts):
        return pad(name, br, *dep_parts, sum(dep_parts), *cr_parts, sum(v for v in cr_parts if isinstance(v, (int, float))))

    cr = (10, 100, 5) if layout == 3 else (10, 100, 3, 2)
    rows.append(rec("Head Office", 29, (1, 2, 3, 0, 0), cr))
    rows.append(pad("Bangkok ", "", "", "", "", "", "", ""))
    for i in range(n):
        rows.append(rec(f"District {i}", 5, (10, 20, 30, 0, 0), cr))
    if mutate:
        mutate(rows)
    rows.append(pad("Remark :   *  Especially Districts which have four commercial banks or more."))
    return rows


class BotSheet(unittest.TestCase):
    def test_both_layouts_parse(self):
        for layout in (3, 4):
            head, recs = etl.parse_sheet(bot_rows(layout), f"layout{layout}")
            self.assertEqual(len(recs), 210)
            self.assertEqual(recs[0]["deposits"], 60 * etl.MB)          # million baht → baht, once
            self.assertEqual(recs[0]["credits"], 115 * etl.MB)
            self.assertEqual(head["branches"], 29)                       # head office kept apart, not a district

    def test_unknown_subheader_stops(self):
        rows = bot_rows()
        rows[4] = pad(None, None, "Current", "Saving", "Time", "Promissory Note", "NCD", "Total", "Overdraft", "Loan", "Leasing", "Total")
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(rows, "x")

    def test_shifted_column_is_caught_by_sum_check(self):
        def shift(rows):
            r = list(rows[10]); r[7] = r[7] + 999; rows[10] = tuple(r)   # total no longer equals its parts
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(mutate=shift), "x")

    def test_masked_credit_parts_are_allowed(self):
        def mask(rows):                                                    # 'n.a.' = five or fewer debtors
            r = list(rows[10]); r[8] = "n.a."; r[10] = "n.a."; rows[10] = tuple(r)
        _, recs = etl.parse_sheet(bot_rows(mutate=mask), "x")
        self.assertEqual(recs[3]["credits"], 115 * etl.MB)

    def test_masked_parts_larger_than_total_still_stop(self):
        def bad(rows):
            r = list(rows[10]); r[8] = "n.a."; r[9] = 99999; rows[10] = tuple(r)
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(mutate=bad), "x")

    def test_total_row_ends_the_table(self):                              # 2023-01..04 sheets carry a Total row
        def total(rows):
            rows.append(pad("Total", 4640, 1, 1, 1, 0, 0, 3, 1, 1, 1, 3))
            rows.append(pad("Ghost", 4, 1, 1, 1, 0, 0, 3, 1, 1, 1, 3))
        _, recs = etl.parse_sheet(bot_rows(mutate=total), "x")
        self.assertEqual(len(recs), 210)

    def test_too_few_districts_stops(self):
        with self.assertRaises(etl.ParserDriftError):
            etl.parse_sheet(bot_rows(n=120), "x")

    def test_period_from_label_or_sheet_name(self):
        self.assertEqual(etl._period_of("Outstanding As of July 2026", "Jul 26"), "2026-07")
        self.assertEqual(etl._period_of(None, "Jan 25"), "2025-01")       # 2025_S2's Jan sheet has no label
        self.assertEqual(etl._period_of("Outstanding As of Jun 2023", "Jun23"), "2023-06")


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        provs, dists, cls.aliases = etl.load_reference()
        cls.pidx = etl.build_province_index(provs)
        cls.by_prov = {}
        for d in dists:
            cls.by_prov.setdefault(d["parent_province_tis1099_code"], []).append(d)

    def test_bot_province_spellings(self):
        for raw, tis in (("Chiengmai", "50"), ("Trad", "23"), ("Pahtthalung", "93"), ("SongKla", "90"),
                         ("Phranakonsiayutthaya", "14"), ("Bangkok ", "10")):
            self.assertEqual(etl.match_province(raw, self.pidx), tis, raw)

    def test_district_fuzzy_and_aliases(self):
        cases = (("50", "Muang Chiangmai", "5001"), ("10", "Latphrao", "1038"), ("12", "#N/A", "1203"),
                 ("54", "Muang Phrea", "5401"), ("14", "Bangpain", "1406"))
        for prov, raw, want in cases:
            self.assertEqual(etl.match_district(prov, raw, self.by_prov, self.aliases)[0], want, raw)

    def test_ambiguous_district_is_refused(self):
        with self.assertRaises(LookupError):
            etl.match_district("50", "Mae", self.by_prov, {})


class Sso(unittest.TestCase):
    def setUp(self):
        provs, _, _ = etl.load_reference()
        self.pidx = etl.build_province_index(provs)
        self.body = (FIX / "sso-t11-2568.xlsx").read_bytes()

    def test_real_file(self):
        out = th_sso.parse(self.body, 2568, self.pidx)
        self.assertEqual(len(out), 77)
        self.assertEqual(out["10"]["insured"], 4167672)                  # Bangkok total, not its area offices
        self.assertEqual(sum(v["insured"] for v in out.values()), 12183749)

    def test_wrong_year_stops(self):
        with self.assertRaises(etl.ParserDriftError):
            th_sso.parse(self.body, 2569, self.pidx)


class Dopa(unittest.TestCase):
    def setUp(self):
        self.text = (FIX / "dopa-c-2567.html").read_text(encoding="utf-8")

    def test_real_file(self):
        out = th_dopa.parse(self.text, 2567)
        self.assertEqual(len(out), 77)
        self.assertEqual(sum(v["population"] for v in out.values()), 65951210)

    def test_identical_duplicate_table_is_accepted(self):                 # stat_c66 ships the table twice
        self.assertEqual(th_dopa.parse(self.text + self.text, 2567), th_dopa.parse(self.text, 2567))

    def test_different_duplicate_table_stops(self):
        other = self.text.replace("65,951,210", "65,951,211", 1)
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.parse(self.text + other, 2567)

    def test_wrong_year_stops(self):
        with self.assertRaises(etl.ParserDriftError):
            th_dopa.parse(self.text, 2568)


class Summary(unittest.TestCase):
    def test_timestamps_are_not_a_change(self):
        a = {"generated_at": "2026-10-01T00:00:00", "latest": "2026-07", "x": [{"generated_at": 1, "v": 2}]}
        b = json.loads(json.dumps(a)); b["generated_at"] = "2026-11-15T03:00:00"; b["x"][0]["generated_at"] = 9
        self.assertEqual(summary.strip_stamps(a), summary.strip_stamps(b))
        b["latest"] = "2026-08"
        self.assertNotEqual(summary.strip_stamps(a), summary.strip_stamps(b))


if __name__ == "__main__":
    unittest.main()
