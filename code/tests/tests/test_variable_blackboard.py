import unittest
import tomli
import datetime
from variable_blackboard import Blackboard


def get_config(file):
    with open(f"./{file}.toml", "rb") as f:
        toml_conf = tomli.load(f)
    return toml_conf


class TestInitConfig(unittest.TestCase):
    def setUp(self):
        self.blackboard = Blackboard(get_config("testing_init_config"), {})

    def test_init_rmap(self):
        self.assertEqual({'single': ['id', 'timestamp'], 'retain': ['type', 'raw_mode'], 'static': ['location']},
                         self.blackboard.variable_rmap)

    def test_init_fmap(self):
        self.assertEqual({'id': 'single', 'type': 'retain', 'raw_mode': 'retain', 'location': 'static'},
                         self.blackboard.variable_fmap)

    def test_init_patterns(self):
        self.assertEqual({'id': 'job_(.*)', 'type': 'type_(.*)', 'raw_mode': 'dir_(.*)'},
                         self.blackboard.patterns)

    def test_init_blackboard(self):
        self.assertEqual({'id': None, 'type': 'banana', 'raw_mode': 'receive', 'location': 'Cutting'},
                         self.blackboard._blackboard)

    def test_init_triggered_by_variable(self):
        self.assertEqual({'id': ['scan_event', 'mode_change_event'], 'mode': ['mode_change_event']},
                         self.blackboard.triggered_by_variable)

    def test_init_outputs(self):
        print(self.blackboard.outputs)
        self.assertEqual({'mode_change_event': {'topic': '{{location}}/control/mode_change',
                                                'name': 'mode_change_event',
                                                'payload': {'mode_changed_to': 'mode'},
                                                'trigger_policy': 'all',
                                                'triggers': ['mode', 'id']
                                                },
                          'scan_event': {'name': 'scan_event',
                                         'topic': '{{location}}/feeds/jobs',
                                         'triggers': ['id'],
                                         'payload': {'job_id': 'id',
                                                     'job_type': 'type',
                                                     'location': 'location',
                                                     'timestamp': 'timestamp'}
                                         }
                          }, self.blackboard.outputs)

    def test_init_trigger_tracking(self):
        self.assertEqual({'scan_event': set(), 'mode_change_event': set()},
                         self.blackboard.trigger_tracking)


class TestInternalSteps(unittest.TestCase):
    def setUp(self):
        self.blackboard = Blackboard(get_config("testing_init_config"), {})

    def test_extract_variable(self):
        self.assertEqual(('id', '12345'), self.blackboard.extract_variable("job_12345"))
        self.assertEqual(('raw_mode', '12345'), self.blackboard.extract_variable("dir_12345"))
        self.assertEqual(('type', '12345'), self.blackboard.extract_variable("type_12345"))

    def test_process_hook(self):
        self.assertEqual({}, self.blackboard.process_hooks('id', "1234"))
        self.assertEqual({"mode": "I"}, self.blackboard.process_hooks('raw_mode', "receive"))

    def test_get_triggered(self):
        self.assertEqual([], self.blackboard.get_triggered("mode"))
        self.assertEqual(['scan_event', 'mode_change_event'], self.blackboard.get_triggered("id"))
        self.assertEqual(['scan_event'], self.blackboard.get_triggered("id"))
        self.assertEqual(['mode_change_event'], self.blackboard.get_triggered("mode"))

    def test_get_outputs(self):
        self.blackboard._blackboard['id'] = "1234"
        timestamp = datetime.datetime.now().isoformat()
        self.blackboard._blackboard['timestamp'] = timestamp
        self.assertEqual(self.blackboard.get_outputs(['scan_event']), [{
            'topic': 'Cutting/feeds/jobs',
            'payload': {'job_id': '1234', 'job_type': 'banana', 'location': 'Cutting', 'timestamp': timestamp}}])

        self.assertEqual(self.blackboard.singles_to_clear, {'id', 'timestamp'})
        self.blackboard.clear_singles()
        self.assertEqual(self.blackboard._blackboard,
                         {'id': None, 'timestamp': None, 'type': 'banana', 'raw_mode': 'receive',
                          'location': 'Cutting'})

        self.blackboard._blackboard['id'] = "12345"
        self.blackboard._blackboard['mode'] = "send"
        timestamp = datetime.datetime.now().isoformat()
        self.blackboard._blackboard['timestamp'] = timestamp
        self.assertEqual(self.blackboard.get_outputs(['scan_event', 'mode_change_event']), [
            {
                'topic': 'Cutting/feeds/jobs',
                'payload': {'job_id': '12345', 'job_type': 'banana', 'location': 'Cutting', 'timestamp': timestamp}
            }, {
                'topic': 'Cutting/control/mode_change',
                'payload': {'mode_changed_to': "send"}
            }
        ])
        self.assertEqual(self.blackboard.singles_to_clear, {'id', 'timestamp'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
