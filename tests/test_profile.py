from contextlib import contextmanager
import http.client
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import unittest

from mailresponder.net import ServiceError
from mailresponder.server import handler_for
from mailresponder.service import Application


class ProfileReviewTests(unittest.TestCase):
    account = 'team@example.test'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(self.temp.name)
        self.app.health_cache = ({'online':False,'models':[],'selected_ready':False,'error':'Test'},float('inf'))
        self.app.gmail.write({'access_token':'local-fixture-only'})
        self.app.store.save_settings({'gmail_email':self.account},internal=True)
        self.manual = {'company':'Meine Firma','description':'Meine bisherigen Angaben','tone':'Mein Ton','signature':'Meine Signatur'}
        self.app.save_settings(self.manual)
        self.profile = {'company':'Erkanntes Studio','description':'Aus E-Mails erkannte Tätigkeit','tone':'Freundlich und direkt','signature':'Erkannte Signatur'}
        self.app.store.begin_onboarding(self.account,'history')
        self.app.store.complete_onboarding(self.account,self.profile)

    def apply(self, fields, expected=None, account=None):
        return self.app.apply_learned_profile(account or self.account,fields,
                                             expected if expected is not None else {field:self.manual[field] for field in fields})

    @contextmanager
    def http(self):
        server = ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app,'local-test-token'))
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()

        def call(path, data=None, token='local-test-token'):
            connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            connection.request('POST' if data is not None else 'GET',path,
                               json.dumps(data) if data is not None else None,
                               {'Content-Type':'application/json','X-Local-Token':token})
            response = connection.getresponse()
            status, body = response.status,json.loads(response.read())
            connection.close()
            return status,body

        try:
            yield call
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_findings_remain_visible_beside_previously_edited_values(self):
        state = self.app.state()
        self.assertEqual(state['onboarding']['profile'],self.profile)
        for field,value in self.manual.items():
            self.assertEqual(state['settings'][field],value)

    def test_only_selected_fields_replace_current_values(self):
        before = self.app.store.onboarding(self.account)
        self.assertEqual(self.apply(['company']),['company'])
        values = self.app.store.settings()
        self.assertEqual(values['company'],self.profile['company'])
        for field in ('description','tone','signature'):
            self.assertEqual(values[field],self.manual[field])
        self.assertEqual(self.app.store.onboarding(self.account),before)
        self.assertIn('company',values['manual_profile_fields'])

    def test_stale_selection_does_not_partially_overwrite_newer_edits(self):
        self.app.save_settings({'description':'Inzwischen manuell bearbeitet'})
        with self.assertRaisesRegex(ServiceError,'inzwischen'):
            self.apply(['company','description'])
        values = self.app.store.settings()
        self.assertEqual(values['company'],self.manual['company'])
        self.assertEqual(values['description'],'Inzwischen manuell bearbeitet')

    def test_unrelated_edits_do_not_prevent_selected_field_adoption(self):
        self.app.save_settings({'tone':'Neuer eigener Ton'})
        self.apply(['company'])
        self.assertEqual(self.app.store.settings()['tone'],'Neuer eigener Ton')

    def test_another_account_cannot_apply_old_findings(self):
        self.app.store.save_settings({'gmail_email':'other@example.test'},internal=True)
        with self.assertRaisesRegex(ServiceError,'Konto'):
            self.apply(['company'])
        self.assertEqual(self.app.state()['onboarding']['profile'],{})
        self.assertEqual(self.app.store.settings()['company'],self.manual['company'])

    def test_incomplete_analysis_is_not_available_for_adoption(self):
        self.app.store.onboarding_update(self.account,stage='analyzing')
        with self.assertRaisesRegex(ValueError,'noch nicht abgeschlossen'):
            self.apply(['company'])

    def test_missing_or_invalid_selections_leave_settings_unchanged(self):
        before = self.app.store.settings()
        cases = [([],{}),('company',{}),(['company','company'],{'company':self.manual['company']}),
                 (['model'],{'model':'qwen3:4b-instruct'}),(['company'],{}),(['company'],{'company':None}),
                 (['style_examples'],{'style_examples':''}),([{}],{})]
        for fields,expected in cases:
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.apply(fields,expected)
        self.assertEqual(self.app.store.settings(),before)

    def test_later_manual_changes_are_not_replaced_on_profile_restore(self):
        self.apply(['company'])
        self.app.save_settings({'company':'Später korrigiert'})
        self.app.store.restore_learned_profile(self.account)
        self.assertEqual(self.app.store.settings()['company'],'Später korrigiert')

    def test_http_exposes_findings_and_applies_only_explicit_selection(self):
        with self.http() as call:
            status,state = call('/api/state')
            self.assertEqual(status,200)
            self.assertEqual(state['onboarding']['profile'],self.profile)
            status,result = call('/api/profile/apply',{'account':self.account,'fields':['company'],
                                                       'expected':{'company':self.manual['company']}})
            self.assertEqual(status,200)
            self.assertEqual(result['applied'],['company'])
            values = call('/api/state')[1]['settings']
            self.assertEqual(values['company'],self.profile['company'])
            self.assertEqual(values['description'],self.manual['description'])

    def test_http_requires_local_access_and_rejects_stale_requests(self):
        data = {'account':self.account,'fields':['company'],'expected':{'company':self.manual['company']}}
        with self.http() as call:
            self.assertEqual(call('/api/profile/apply',data,token='')[0],403)
            self.app.save_settings({'company':'Neu bearbeitet'})
            self.assertEqual(call('/api/profile/apply',data)[0],409)
        self.assertEqual(self.app.store.settings()['company'],'Neu bearbeitet')


if __name__ == '__main__':
    unittest.main()
