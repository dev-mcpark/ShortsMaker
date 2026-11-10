"""Studio enables manual actions without starting providers or the schedule clock."""

import os
import unittest
from unittest.mock import patch

from shorts_maker.gui import __main__ as studio
from shorts_maker.utils.config import settings


class StudioStartupTests(unittest.TestCase):
    def test_manual_start_enables_generation_when_not_explicitly_configured(self):
        with patch.dict(os.environ), patch.object(settings, 'paid_production_enabled', False), \
                patch.object(studio.ui, 'run') as server:
            os.environ.pop('PAID_PRODUCTION_ENABLED', None)
            studio.run()
            self.assertTrue(settings.paid_production_enabled)
            self.assertEqual(server.call_args.kwargs['host'], '127.0.0.1')
            self.assertFalse(server.call_args.kwargs['reload'])

    def test_explicit_generation_setting_is_preserved(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), \
                    patch.dict(os.environ, {'PAID_PRODUCTION_ENABLED': str(enabled).lower()}), \
                    patch.object(settings, 'paid_production_enabled', enabled), \
                    patch.object(studio.ui, 'run'):
                studio.run()
                self.assertEqual(settings.paid_production_enabled, enabled)


if __name__ == '__main__':
    unittest.main()
