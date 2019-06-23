import json
import unittest
from decimal import Decimal

from electrumsv.commands import Commands
from bitcoinx import PrivateKey


privkey = PrivateKey.from_WIF('L2o1ztYYR9t7DcXGzsV2zKWJUXEmfh3C6vmKM3CCAAfeJ44AkLcr')
pubkey_hex = privkey.public_key.to_hex()


class TestCommands(unittest.TestCase):

    def test_setconfig_non_auth_number(self):
        self.assertEqual(7777, Commands._setconfig_normalize_value('rpcport', "7777"))
        self.assertEqual(7777, Commands._setconfig_normalize_value('rpcport', '7777'))
        self.assertAlmostEqual(Decimal(2.3), Commands._setconfig_normalize_value('somekey', '2.3'))

    def test_setconfig_non_auth_number_as_string(self):
        self.assertEqual("7777", Commands._setconfig_normalize_value('somekey', "'7777'"))

    def test_setconfig_non_auth_boolean(self):
        self.assertEqual(True, Commands._setconfig_normalize_value('show_console_tab', "true"))
        self.assertEqual(True, Commands._setconfig_normalize_value('show_console_tab', "True"))

    def test_setconfig_non_auth_list(self):
        self.assertEqual(['file:///var/www/', 'https://electrumsv.io'],
            Commands._setconfig_normalize_value('url_rewrite',
                "['file:///var/www/','https://electrumsv.io']"))
        self.assertEqual(['file:///var/www/', 'https://electrumsv.io'],
            Commands._setconfig_normalize_value('url_rewrite',
                '["file:///var/www/","https://electrumsv.io"]'))

    def test_setconfig_auth(self):
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcuser', "7777"))
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcuser', '7777'))
        self.assertEqual("7777", Commands._setconfig_normalize_value('rpcpassword', '7777'))
        self.assertEqual("2asd", Commands._setconfig_normalize_value('rpcpassword', '2asd'))
        self.assertEqual("['file:///var/www/','https://electrumsv.io']",
            Commands._setconfig_normalize_value('rpcpassword',
                "['file:///var/www/','https://electrumsv.io']"))
