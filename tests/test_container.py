from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from mailresponder import container
from mailresponder.net import ServiceError


class ContainerTests(unittest.TestCase):
    def test_defaults_and_custom_port(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(container.configuration(), (Path('/data'), 8765, True))
        with patch.dict("os.environ", {"AMR_PORT":"8766", "AMR_DOWNLOAD_MODEL":"0"}, clear=True):
            self.assertEqual(container.configuration(), (Path('/data'), 8766, False))

    def test_invalid_configuration_is_rejected_before_starting_services(self):
        for value in ('0', '65536', 'invalid'):
            with self.subTest(value=value), patch.dict("os.environ", {"AMR_PORT":value}, clear=True):
                with self.assertRaisesRegex(ValueError, "AMR_PORT"):
                    container.configuration()
        with patch.dict("os.environ", {"AMR_DOWNLOAD_MODEL":"invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "AMR_DOWNLOAD_MODEL"):
                container.configuration()

    def test_cached_local_model_is_validated_without_another_download(self):
        with patch.object(container, 'LocalModel') as model, patch.object(container.subprocess, 'Popen') as spawn:
            model.return_value.status.return_value = {"selected_ready":True}
            container.ensure_model('qwen3:4b-instruct')
            spawn.assert_not_called()
            model.return_value.validate.assert_called_once_with('qwen3:4b-instruct')

    def test_download_failure_blocks_the_app_and_cleans_up_the_child(self):
        with patch.object(container, 'LocalModel') as model, patch.object(container.subprocess, 'Popen') as spawn, patch.object(container, 'stop_ollama') as stop:
            model.return_value.status.return_value = {"selected_ready":False}
            spawn.return_value.wait.return_value = 1
            with self.assertRaisesRegex(ServiceError, 'Modelldownload'):
                container.ensure_model('qwen3:4b-instruct')
            model.return_value.validate.assert_not_called()
            stop.assert_called_once_with(spawn.return_value)

    def test_interrupt_during_download_stops_the_download_process(self):
        with patch.object(container, 'LocalModel') as model, patch.object(container.subprocess, 'Popen') as spawn, patch.object(container, 'stop_ollama') as stop:
            model.return_value.status.return_value = {"selected_ready":False}
            spawn.return_value.wait.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                container.ensure_model('qwen3:4b-instruct')
            stop.assert_called_once_with(spawn.return_value)

    def test_cloud_models_are_never_downloaded(self):
        with patch.object(container.subprocess, 'Popen') as spawn:
            for name in ('qwen:cloud', 'remote/model', 'bad name'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    container.ensure_model(name)
            spawn.assert_not_called()

    def test_store_and_model_setup_happen_under_the_instance_lock(self):
        events = []

        @contextmanager
        def lock(_):
            events.append('locked')
            try:
                yield
            finally:
                events.append('unlocked')

        child = Mock()
        with patch.object(container, 'configuration', return_value=(Path('/data'), 8766, True)), \
             patch.object(container, 'instance_lock', side_effect=lock), \
             patch.object(container, 'start_ollama', return_value=child), \
             patch.object(container, 'stop_ollama', side_effect=lambda _: events.append('stopped')), \
             patch.object(container, 'LocalModel') as model, \
             patch.object(container, 'Store') as store, \
             patch.object(container, 'ensure_model', side_effect=lambda _: events.append('model')), \
             patch.object(container, '_serve', side_effect=KeyboardInterrupt) as serve, \
             patch.dict('os.environ', {}, clear=True):
            model.return_value.status.return_value = {'online':True}
            store.side_effect = lambda _: events.append('store') or Mock(settings=lambda: {'model':'qwen3:4b-instruct'})
            with self.assertRaises(KeyboardInterrupt):
                container.run()
            serve.assert_called_once_with(8766, Path('/data'), False, False, host='0.0.0.0')
        self.assertEqual(events, ['locked', 'store', 'model', 'stopped', 'unlocked'])


if __name__ == '__main__':
    unittest.main()
