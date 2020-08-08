import unittest

from runperf import utils
import collections


class BasicUtils(unittest.TestCase):
    def test_list_of_threads(self):
        self.assertRaises(AssertionError, utils.list_of_threads, -5)
        self.assertRaises(AssertionError, utils.list_of_threads, 0)
        self.assertEqual(utils.list_of_threads(1), "1")
        self.assertEqual(utils.list_of_threads(2), "1,2")
        self.assertEqual(utils.list_of_threads(7), "1,2,3,4,5,6,7")
        self.assertEqual(utils.list_of_threads(18), "1,4,8,12,16,18")
        self.assertEqual(utils.list_of_threads(79), "1,19,38,57,76,79")
        self.assertEqual(utils.list_of_threads(2048), "1,512,1024,1536,2048")


if __name__ == '__main__':
    unittest.main()
