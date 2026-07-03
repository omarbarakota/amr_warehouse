import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mqtt_ros2_bridge.mqtt_ros2_bridge_node import normalize_topic


class TopicNormalizationTests(unittest.TestCase):
    def test_normalize_topic_strips_extra_slashes(self):
        self.assertEqual(normalize_topic('//robot//move//'), '/robot/move')

    def test_normalize_topic_handles_topic_without_leading_slash(self):
        self.assertEqual(normalize_topic('robot/goal'), '/robot/goal')

    def test_normalize_topic_handles_empty_input(self):
        self.assertEqual(normalize_topic(''), '/')


if __name__ == '__main__':
    unittest.main()
