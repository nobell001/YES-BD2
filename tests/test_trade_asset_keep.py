"""招募契约书 / 史莱姆 keep rules (Leo, 2026-11-10)."""

import unittest

from src.tasks.map_trade.asset_keep import (
    ContractCounts,
    contracts_to_keep,
    contracts_to_sell,
    slime_keep_range,
    slime_left_is_fine,
)


class ContractKeepTest(unittest.TestCase):
    def test_leo_example_surplus_top_and_all_low_are_sold(self):
        # 设 3 个；有 5 本最高级、30 本最低级 → 卖 2 本最高级和 30 本最低级。
        sell = contracts_to_sell(ContractCounts(top=5, low=30), 3)
        self.assertEqual(sell, ContractCounts(top=2, middle=0, low=30))

    def test_leo_example_not_enough_sells_nothing(self):
        # 设 3 个；250 本最低级 + 3 本次级只够 2.8 个 → 一本都不能卖。
        sell = contracts_to_sell(ContractCounts(middle=3, low=250), 3)
        self.assertEqual(sell, ContractCounts())

    def test_top_kept_first_then_middle_then_low(self):
        keep = contracts_to_keep(ContractCounts(top=2, middle=25, low=400), 4)
        self.assertEqual(keep, ContractCounts(top=2, middle=20, low=0))
        keep = contracts_to_keep(ContractCounts(top=1, middle=5, low=400), 3)
        self.assertEqual(keep, ContractCounts(top=1, middle=5, low=150))

    def test_middle_rounds_up_so_the_recruit_stays_whole(self):
        # 95 lowest still needed after the top tier: 10 middle books, not 9.
        keep = contracts_to_keep(ContractCounts(top=0, middle=30, low=5), 1)
        self.assertEqual(keep, ContractCounts(middle=10))

    def test_what_stays_is_always_worth_the_setting_when_anything_is_sold(self):
        for top in range(0, 5):
            for middle in range(0, 35, 3):
                for low in range(0, 420, 37):
                    for recruits in range(0, 6):
                        owned = ContractCounts(top, middle, low)
                        keep = contracts_to_keep(owned, recruits)
                        sell = contracts_to_sell(owned, recruits)
                        if sell != ContractCounts():
                            self.assertGreaterEqual(keep.worth, recruits * 100, (owned, recruits))
                        if owned.worth < recruits * 100:
                            self.assertEqual(sell, ContractCounts(), (owned, recruits))

    def test_zero_keeps_nothing(self):
        owned = ContractCounts(top=2, middle=4, low=34)
        self.assertEqual(contracts_to_sell(owned, 0), owned)

    def test_bad_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            ContractCounts(top=-1)
        with self.assertRaises(ValueError):
            contracts_to_keep(ContractCounts(), -1)
        with self.assertRaises(ValueError):
            contracts_to_keep(ContractCounts(), True)


class SlimeKeepTest(unittest.TestCase):
    def test_leo_example_range(self):
        # 黄色史莱姆留 20000 → 剩 19000~22000 都可以。
        self.assertEqual(slime_keep_range(20000), (19000, 22000))

    def test_left_amount_inside_the_range(self):
        self.assertTrue(slime_left_is_fine(33458, 13004, 20000))  # 剩 20454
        self.assertTrue(slime_left_is_fine(33458, 14458, 20000))  # 剩 19000
        self.assertTrue(slime_left_is_fine(33458, 11458, 20000))  # 剩 22000
        self.assertFalse(slime_left_is_fine(33458, 14459, 20000))  # 剩 18999
        self.assertFalse(slime_left_is_fine(33458, 11457, 20000))  # 剩 22001

    def test_nothing_selected_or_more_than_owned_is_never_fine(self):
        self.assertFalse(slime_left_is_fine(100, 0, 100))
        self.assertFalse(slime_left_is_fine(100, 101, 0))

    def test_small_keep_amounts_are_exact(self):
        self.assertEqual(slime_keep_range(10), (10, 11))
        self.assertEqual(slime_keep_range(0), (0, 0))


if __name__ == "__main__":
    unittest.main()
