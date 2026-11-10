import json
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from mailresponder.net import ServiceError
from mailresponder.service import Application
from mailresponder.store import DEFAULTS
from mailresponder.website import (MAX_TEXT, Response, WebsiteHTML, WebsiteReader,
                                   _PinnedHTTPS, fetch_public, public_ip, website_facts, website_url)


def html(text, links=''):
    return Response(200,{'content-type':'text/html; charset=utf-8'},
                    ('<html><head><title>Testunternehmen</title></head><body><p>'+text+'</p>'+links+'</body></html>').encode())


class PublicNetworkTests(unittest.TestCase):
    def test_url_normalization_and_rejected_address_types(self):
        self.assertEqual(website_url('firma.example/über-uns#team'),'https://firma.example/%C3%BCber-uns')
        self.assertEqual(website_url('https://FIRMA.EXAMPLE:443/'),'https://firma.example/')
        for url in ('file:///etc/passwd','ftp://firma.example/','https://user:password@firma.example',
                    'http://localhost','http://127.0.0.1','http://[::1]','https://firma.example:8443',
                    'https://firma.local','https://firma.example/\r\nTest:yes','https://firma.example\\@127.0.0.1'):
            with self.subTest(url=url),self.assertRaises(ValueError):website_url(url)

    def test_private_and_transition_addresses_are_rejected(self):
        for value in ('127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','100.64.0.1','224.0.0.1',
                      '::1','fc00::1','fe80::1','::ffff:192.168.1.1','64:ff9b::c0a8:101','2002:c0a8:101::1'):
            with self.subTest(value=value):self.assertFalse(public_ip(value))
        self.assertTrue(public_ip('8.8.8.8'))
        self.assertTrue(public_ip('2001:4860:4860::8888'))

    def test_mixed_public_and_private_dns_never_opens_a_connection(self):
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443)) for ip in ('8.8.8.8','127.0.0.1')]
        with patch('mailresponder.website.socket.getaddrinfo',return_value=addresses),patch('mailresponder.website._PinnedHTTPS') as connect:
            with self.assertRaises(ValueError):fetch_public('https://firma.example')
            connect.assert_not_called()

    def test_transport_pins_the_validated_ip_without_authentication(self):
        response=Mock(status=200)
        response.getheaders.return_value=[('Content-Type','text/html')]
        response.read.return_value=b'<p>Test</p>'
        connection=Mock()
        connection.getresponse.return_value=response
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        with patch('mailresponder.website.socket.getaddrinfo',return_value=addresses) as dns,patch('mailresponder.website._PinnedHTTPS',return_value=connection):
            self.assertEqual(fetch_public('https://firma.example/unternehmen').status,200)
            dns.assert_called_once()
            self.assertEqual(connection.public_address,'8.8.8.8')
            self.assertEqual(set(connection.request.call_args.kwargs['headers']),{'User-Agent','Accept','Accept-Encoding'})
            connection.close.assert_called_once()

    def test_tls_checks_the_original_hostname_on_the_pinned_socket(self):
        context=Mock()
        connection=_PinnedHTTPS('firma.example',443,timeout=4,context=context)
        connection.public_address='8.8.8.8'
        raw=Mock()
        with patch('mailresponder.website.socket.create_connection',return_value=raw) as connect:connection.connect()
        connect.assert_called_once_with(('8.8.8.8',443),4)
        context.wrap_socket.assert_called_once_with(raw,server_hostname='firma.example')

    def test_oversized_page_is_not_accepted(self):
        response=Mock(status=200)
        response.getheaders.return_value=[]
        response.read.return_value=b'x'*11
        connection=Mock()
        connection.getresponse.return_value=response
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        with patch('mailresponder.website.socket.getaddrinfo',return_value=addresses),patch('mailresponder.website._PinnedHTTPS',return_value=connection):
            with self.assertRaisesRegex(ServiceError,'zu groß'):fetch_public('https://firma.example',limit=10)


class WebsiteReadingTests(unittest.TestCase):
    def reader(self, mapping):
        calls=[]
        def fetch(url, **kwargs):
            calls.append(url)
            if url.endswith('/robots.txt') and url not in mapping:return Response(404,{},b'')
            result=mapping[url]
            if isinstance(result,Exception):raise result
            return result
        return WebsiteReader(fetch,sleep=lambda _:None),calls

    def test_scripts_forms_navigation_and_hidden_text_are_removed(self):
        parser=WebsiteHTML()
        parser.feed('<html><head><title>Studio &amp; Partner</title></head><body><nav>Navigation<a href="/about">About</a></nav><script>secret()</script><style>.x{}</style><div hidden>Hidden</div><div style="display: none">Invisible</div><form>Form details</form><main><h1>Studio</h1><p>Wir gestalten Websites &amp; beraten Unternehmen.</p></main></body></html>')
        self.assertIn('Wir gestalten Websites & beraten Unternehmen.',parser.content())
        for word in ('Navigation','secret','Hidden','Invisible','Form details'):self.assertNotIn(word,parser.content())
        self.assertIn('/about',parser.links)
        parser.feed('<meta name><meta name="description"><div style>Lesbarer Text trotz leerer Attribute.</div>')
        self.assertIn('Lesbarer Text trotz leerer Attribute.',parser.content())

    def test_only_relevant_same_site_pages_are_read_and_count_is_bounded(self):
        paths=['about','unternehmen','services','contact','impressum','team']
        links=''.join(f'<a href="/{path}">{path}</a>' for path in paths)
        links+='<a href="https://other.example/about">External</a><a href="/services.pdf">PDF</a><a href="/contact?send=1">Query</a>'
        body='Wir gestalten Websites und beraten kleine Unternehmen bei digitalen Projekten.'
        mapping={'https://firma.example/':html(body,links),**{f'https://firma.example/{path}':html(body) for path in paths}}
        reader,calls=self.reader(mapping)
        pages,warnings=reader.read('firma.example')
        self.assertEqual(len(pages),5)
        self.assertEqual(warnings,[])
        self.assertFalse(any('other.example' in url or '?' in url or '.pdf' in url for url in calls))

    def test_failed_pages_also_count_toward_the_request_limit(self):
        paths=['about','unternehmen','services','contact','impressum','team']
        links=''.join(f'<a href="/{path}">{path}</a>' for path in paths)
        mapping={'https://firma.example/':html('Wir gestalten Websites und beraten kleine Unternehmen bei digitalen Projekten.',links),
                 **{f'https://firma.example/{path}':Response(404,{},b'') for path in paths}}
        reader,calls=self.reader(mapping)
        pages,_=reader.read('firma.example')
        self.assertEqual(len(pages),1)
        self.assertEqual(len([url for url in calls if not url.endswith('/robots.txt')]),5)

    def test_robots_disallow_prevents_the_page_request(self):
        reader,calls=self.reader({'https://firma.example/robots.txt':Response(200,{},b'User-agent: *\nDisallow: /')})
        with self.assertRaisesRegex(ServiceError,'erlaubt'):reader.read('firma.example')
        self.assertEqual(calls,['https://firma.example/robots.txt'])

    def test_redirect_target_rules_are_checked_before_requesting_content(self):
        reader,calls=self.reader({'https://firma.example/robots.txt':Response(200,{},b'User-agent: *\nDisallow: /private'),
                                 'https://firma.example/':Response(302,{'location':'/private/company'},b'')})
        with self.assertRaisesRegex(ServiceError,'Zielseite'):reader.read('firma.example')
        self.assertNotIn('https://firma.example/private/company',calls)

    def test_private_and_other_domain_redirects_are_not_followed(self):
        for target in ('http://127.0.0.1:11434/api/tags','https://other.example/about'):
            reader,calls=self.reader({'https://firma.example/':Response(302,{'location':target},b'')})
            with self.subTest(target=target),self.assertRaises((ValueError,ServiceError)):reader.read('firma.example')
            self.assertNotIn(target,calls)

    def test_failed_subpage_preserves_successful_text_with_a_warning(self):
        reader,_=self.reader({'https://firma.example/':html('Wir gestalten Websites und beraten kleine Unternehmen bei digitalen Projekten.','<a href="/contact">Kontakt</a>'),
                             'https://firma.example/contact':ServiceError('Unterseite nicht erreichbar.')})
        pages,warnings=reader.read('firma.example')
        self.assertEqual(len(pages),1)
        self.assertIn('Unterseite nicht erreichbar.',warnings)

    def test_javascript_only_pages_do_not_become_blank_knowledge(self):
        reader,_=self.reader({'https://firma.example/':Response(200,{'content-type':'text/html'},b'<div id="app"></div><script>render()</script>')})
        with self.assertRaisesRegex(ServiceError,'JavaScript'):reader.read('firma.example')

    def test_long_text_is_flagged_and_long_crawl_delay_is_respected(self):
        reader,_=self.reader({'https://firma.example/':html('Unser Unternehmen bietet Beratung. '*1000)})
        pages,warnings=reader.read('firma.example')
        self.assertEqual(len(pages[0]['text']),MAX_TEXT)
        self.assertTrue(warnings)
        reader,calls=self.reader({'https://firma.example/robots.txt':Response(200,{},b'User-agent: *\nCrawl-delay: 60')})
        with self.assertRaisesRegex(ServiceError,'Abrufpausen'):reader.read('firma.example')
        self.assertEqual(len(calls),1)


class WebsiteKnowledgeTests(unittest.TestCase):
    pages=[{'url':'https://firma.example/','title':'Testunternehmen','text':'Wir gestalten Websites und beraten kleine Unternehmen.'}]

    def model(self, facts):
        model=Mock()
        model.request.return_value={'message':{'content':json.dumps({'facts':facts})}}
        return model

    def test_only_literal_quotes_with_known_sources_are_accepted(self):
        facts=[{'source':self.pages[0]['url'],'quote':'Wir gestalten Websites'},
               {'source':self.pages[0]['url'],'quote':'Wir garantieren jeden Umsatz.'},
               {'source':'https://other.example/','quote':'Wir gestalten Websites'}]
        self.assertEqual(website_facts(self.model(facts),self.pages,DEFAULTS),[facts[0]])

    def test_remote_model_results_are_rejected(self):
        model=self.model([])
        model.request.return_value['remote_host']='https://remote.example'
        with self.assertRaises(ServiceError):website_facts(model,self.pages,DEFAULTS)

    def test_preview_does_not_modify_knowledge_or_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Application(temp)
            app.save_settings({'company':'Private profile marker'})
            app.model=self.model([{'source':self.pages[0]['url'],'quote':'Wir gestalten Websites'}])
            before=app.store.settings()
            with patch('mailresponder.service.WebsiteReader') as reader:
                reader.return_value.read.return_value=(self.pages,[])
                result=app.import_website('firma.example')
            self.assertEqual(app.store.documents(),[])
            self.assertEqual(app.store.settings(),before)
            self.assertIn('Quelle: https://firma.example/',result['content'])
            self.assertEqual(result['facts_count'],1)
            self.assertNotIn('Private profile marker',json.dumps(app.model.request.call_args.args))
            app.store.save_document(result['title'],result['content'])
            self.assertTrue(app.store.search('Websites'))

    def test_busy_or_offline_local_model_still_allows_text_import(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Application(temp)
            with patch('mailresponder.service.WebsiteReader') as reader:
                reader.return_value.read.return_value=(self.pages,[])
                app.inference_lock.acquire()
                try:result=app.import_website('firma.example')
                finally:app.inference_lock.release()
                self.assertTrue(result['warnings'])
                self.assertIn(self.pages[0]['text'],result['content'])
                app.model=Mock()
                app.model.validate.side_effect=ServiceError('Offline')
                result=app.import_website('firma.example')
                self.assertTrue(result['warnings'])
                self.assertIn(self.pages[0]['text'],result['content'])
            self.assertEqual(app.store.documents(),[])


if __name__ == '__main__':
    unittest.main()
