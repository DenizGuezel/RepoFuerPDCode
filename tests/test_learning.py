import base64
import collections
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mailresponder.gmail import Gmail, archive_message
from mailresponder.learning import MailboxLearner, analysis_parts, extract_findings, own_text
from mailresponder.net import ServiceError
from mailresponder.service import Application
from mailresponder.store import DEFAULTS, Store


ACCOUNT="team@example.com"
SENT_TEXT="Guten Tag,\n\nwir gestalten Websites für kleine Unternehmen. Gern unterstützen wir Sie.\n\nFreundliche Grüße\nNordlicht Studio"


def mail(mid, text=SENT_TEXT, sent=False, labels=None, timestamp=1000):
    return {"id":mid,"threadId":"thread-"+mid,"internalDate":str(int(timestamp*1000)),"labelIds":labels if labels is not None else (["SENT"] if sent else ["INBOX"]),
        "payload":{"mimeType":"text/plain","headers":[{"name":"From","value":ACCOUNT if sent else "kunde@example.net"},
            {"name":"To","value":"kunde@example.net" if sent else ACCOUNT},{"name":"Subject","value":"Website-Anfrage"}],
            "body":{"data":base64.urlsafe_b64encode(text.encode()).decode()}}}


class Mailbox:
    def __init__(self,messages=None,account=ACCOUNT,page_size=2):
        self.messages={m["id"]:m for m in (messages if messages is not None else [mail("a",text="Wir benötigen eine Website."),mail("b",sent=True)])}
        self.account=account
        self.page_size=page_size
        self.pages=[]
        self.gets=collections.Counter()
        self.connected_value=True
        self.failed_message=None
        self.changed=set()
        self.active=[]
        self.queries=[]
        self.profile_calls=0

    def connected(self):return self.connected_value
    def configured(self):return True
    def disconnect(self):self.connected_value=False

    def api(self,path):
        assert path=="/profile"
        self.profile_calls+=1
        return {"emailAddress":self.account,"historyId":"100"}

    def list_messages_page(self,token=""):
        self.pages.append(token)
        start=int(token or 0)
        rows=list(self.messages.values())[start:start+self.page_size]
        result={"messages":[{"id":m["id"],"threadId":m["threadId"]} for m in rows]}
        if start+len(rows)<len(self.messages):result["nextPageToken"]=str(start+len(rows))
        return result

    def get_message(self,mid):
        self.gets[mid]+=1
        if self.failed_message==mid:raise ServiceError("Unterbrochener Testabruf")
        return self.messages[mid]

    def changed_threads(self,history):return self.changed,"101"
    def list_threads(self,query):
        self.queries.append(query)
        return iter(self.active)
    def get_thread(self,tid):return {"id":tid,"messages":[m for m in self.messages.values() if m["threadId"]==tid]}


class Model:
    def __init__(self):
        self.batches=[]
        self.fail_at=None
        self.on_request=None

    def status(self,selected):return {"online":True,"selected_ready":True,"models":[],"error":""}
    def validate(self,name):return {"model_info":{"architecture":"local"}}

    def request(self,url,method,data,**kwargs):
        assert url=="http://127.0.0.1:11434/api/chat"
        assert data["options"]["num_ctx"]<=4096
        messages=json.loads(data["messages"][1]["content"])["messages"]
        self.batches.append([m["id"] for m in messages])
        if self.fail_at==len(self.batches):raise ServiceError("Testmodell unterbrochen")
        if self.on_request:self.on_request()
        findings=[]
        invalid=[]
        for item in messages:
            if not item["outgoing"]:
                # Incorrectly assigning a customer's style/company must be rejected by the validator.
                invalid.extend([
                    {"field":"tone","value":"Kundenstil","source":item["id"],"quote":item["text"][:100]},
                    {"field":"company","value":"Fremde Kundenfirma","source":item["id"],"quote":item["text"][:100]}])
                continue
            if "Nordlicht Studio" in item["text"]:
                for field,value,quote in [
                    ("company","Nordlicht Studio","Nordlicht Studio"),
                    ("description","Websites für kleine Unternehmen","wir gestalten Websites für kleine Unternehmen"),
                    ("tone","Freundlich und direkt","Gern unterstützen wir Sie"),
                    ("salutation","Sie","unterstützen wir Sie"),
                    ("signature","Freundliche Grüße\nNordlicht Studio","Freundliche Grüße\nNordlicht Studio"),
                    ("style_analysis","Kurze Absätze und direkte Hilfsangebote.","Gern unterstützen wir Sie")]:
                    if quote in item["text"]:findings.append({"field":field,"value":value,"source":item["id"],"quote":quote})
        return {"message":{"content":json.dumps({"findings":(findings+invalid)[:6]},ensure_ascii=False)},"done_reason":"stop"}


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Application(self.temp.name)
        self.gmail=Mailbox()
        self.model=Model()
        self.app.gmail=self.gmail
        self.app.model=self.model

    def tearDown(self):
        self.app.stop.set()
        self.temp.cleanup()

    def restart(self):
        app=Application(self.temp.name)
        app.gmail=self.gmail
        app.model=self.model
        return app

    def test_complete_history_including_sent_is_imported_and_profile_is_inferred(self):
        self.gmail.messages["c"]=mail("c",text="Archivierte Anfrage",labels=[])
        self.app.sync()
        self.assertEqual(self.gmail.pages,["","2"])
        self.assertEqual(set(self.gmail.gets),{"a","b","c"})
        settings=self.app.store.settings()
        self.assertEqual(settings["company"],"Nordlicht Studio")
        self.assertIn("Websites",settings["description"])
        self.assertEqual(settings["tone"],"Freundlich und direkt")
        self.assertIn("Kurze Absätze",settings["style_analysis"])
        self.assertEqual(settings["signature"],"Freundliche Grüße\nNordlicht Studio")
        initial=self.app.store.onboarding(ACCOUNT)
        self.assertEqual(initial["stage"],"complete")
        self.assertEqual(initial["imported"],3)
        self.assertEqual(initial["sent"],1)

    def test_successful_initialization_never_repeats_on_sync_or_restart(self):
        self.app.sync()
        count=len(self.model.batches)
        pages=list(self.gmail.pages)
        gets=self.gmail.gets.copy()
        completed=self.app.store.onboarding(ACCOUNT)["completed"]
        self.app.sync()
        self.restart().sync()
        self.assertEqual(len(self.model.batches),count)
        self.assertEqual(self.gmail.pages,pages)
        self.assertEqual(self.gmail.gets,gets)
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["completed"],completed)

    def test_interrupted_download_resumes_without_reloading_completed_messages(self):
        self.gmail.failed_message="b"
        with self.assertRaises(ServiceError):self.app.sync()
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"downloading")
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["downloaded"],1)
        pages=list(self.gmail.pages)
        self.gmail.failed_message=None
        self.restart().sync()
        self.assertEqual(self.gmail.gets["a"],1)
        self.assertEqual(self.gmail.gets["b"],2)
        self.assertEqual(self.gmail.pages,pages)
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_interrupted_analysis_resumes_at_next_unfinished_part(self):
        self.gmail.messages={"long":mail("long",text=SENT_TEXT+"\n"+"Eine ausführliche Nachricht. "*500,sent=True)}
        self.model.fail_at=2
        with self.assertRaises(ServiceError):self.app.sync()
        record=self.app.store.onboarding(ACCOUNT)
        self.assertEqual(record["stage"],"analyzing")
        self.assertGreater(record["parts_done"],0)
        completed_parts=set(self.model.batches[0])
        gets=self.gmail.gets.copy()
        previous=len(self.model.batches)
        self.model.fail_at=None
        self.restart().sync()
        resumed={part for batch in self.model.batches[previous:] for part in batch}
        self.assertFalse(completed_parts.intersection(resumed))
        self.assertEqual(self.gmail.gets,gets)
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_listing_checkpoint_survives_restart(self):
        self.gmail.messages["c"]=mail("c")
        original=self.gmail.list_messages_page
        failed=[False]
        def list_page(token=""):
            if token and not failed[0]:
                failed[0]=True
                raise ServiceError("Unterbrochene Auflistung")
            return original(token)
        self.gmail.list_messages_page=list_page
        with self.assertRaises(ServiceError):self.app.sync()
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["listed"],2)
        self.restart().sync()
        self.assertEqual(self.gmail.pages,["","2"])
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["imported"],3)

    def test_manual_fields_and_edits_during_analysis_take_precedence(self):
        self.app.save_settings({"company":"Meine Firma","signature":"Meine Signatur"})
        self.model.on_request=lambda:self.app.save_settings({"tone":"Mein eigener Ton"})
        self.app.sync()
        values=self.app.store.settings()
        self.assertEqual(values["company"],"Meine Firma")
        self.assertEqual(values["signature"],"Meine Signatur")
        self.assertEqual(values["tone"],"Mein eigener Ton")
        self.assertIn("Websites",values["description"])

    def test_clearing_a_field_manually_does_not_repopulate_it_on_reconnect(self):
        self.app.sync()
        self.app.save_settings({"tone":""})
        self.app.disconnect()
        self.gmail.connected_value=True
        self.app.sync()
        self.assertEqual(self.app.store.settings()["tone"],"")

    def test_reconnecting_same_account_does_not_restart_initialization(self):
        self.app.sync()
        batches=len(self.model.batches)
        pages=list(self.gmail.pages)
        completed=self.app.store.onboarding(ACCOUNT)["completed"]
        self.app.disconnect()
        with self.app.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail_archive").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM learning_facts").fetchone()[0],0)
        self.gmail.connected_value=True
        self.restart().sync()
        record=self.app.store.onboarding(ACCOUNT)
        self.assertEqual(record["completed"],completed)
        self.assertEqual(record["imported"],2)
        self.assertEqual(len(self.model.batches),batches)
        self.assertEqual(self.gmail.pages,pages)

    def test_different_account_has_its_own_first_run(self):
        self.app.sync()
        other="other@example.org"
        self.app.disconnect()
        self.gmail=Mailbox(account=other)
        self.app.gmail=self.gmail
        self.app.sync()
        self.assertTrue(self.gmail.pages)
        self.assertEqual(self.app.store.onboarding(other)["stage"],"complete")
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_historical_incoming_mail_does_not_receive_automatic_drafts(self):
        self.app.store.save_settings({"automatic":True})
        self.gmail.changed={"thread-a"}
        self.gmail.active=["thread-a"]
        self.app.sync()
        self.assertIsNotNone(self.app.store.thread("thread-a"))
        self.assertIsNone(self.app.store.claim())

    def test_imported_sent_mail_is_available_as_optional_contact_context(self):
        self.app.sync()
        history=self.app.store.history("kunde@example.net","current-thread",ACCOUNT)
        self.assertTrue(any("Nordlicht Studio" in item["body"] for item in history))
        self.assertEqual(self.app.store.history("kunde@example.net","current-thread","other@example.net"),[])

    def test_messages_arriving_during_initialization_are_not_lost(self):
        self.app.store.save_settings({"automatic":True})
        self.gmail.messages["new"]=mail("new",text="Eine neue Anfrage",timestamp=time.time()+1)
        self.gmail.changed={"thread-new"}
        self.gmail.active=["thread-new"]
        self.app.sync()
        self.assertIsNotNone(self.app.store.claim())

    def test_expired_history_after_long_first_run_does_not_use_a_14_day_limit(self):
        began=time.time()-40*86400
        self.app.store.begin_onboarding(ACCOUNT,"old-history")
        self.app.store.complete_onboarding(ACCOUNT,{})
        with self.app.store.connection() as db:
            db.execute("UPDATE onboarding SET started=? WHERE account=?",(began,ACCOUNT))
        self.app.store.save_settings({"automatic":True,"gmail_email":ACCOUNT,"history_id":"old-history"},internal=True)
        def expired(history):raise ServiceError("History abgelaufen",404)
        self.gmail.changed_threads=expired
        self.gmail.messages["during-first-run"]=mail("during-first-run",text="Neue Anfrage während langer Einrichtung",timestamp=time.time()-20*86400)
        self.gmail.active=["thread-during-first-run"]
        self.app.sync()
        self.assertNotIn("newer_than",self.gmail.queries[-1])
        self.assertIn(f"after:{int(began)-60}",self.gmail.queries[-1])
        self.assertIsNotNone(self.app.store.claim())
        self.assertEqual(self.gmail.pages,[])
        self.assertEqual(self.model.batches,[])

    def test_spam_trash_and_drafts_are_downloaded_but_not_used_as_style_examples(self):
        self.gmail.messages={key:mail(key,sent=True,labels=[label]) for key,label in [("s","SPAM"),("t","TRASH"),("d","DRAFT")]}
        self.app.sync()
        self.assertEqual(set(self.gmail.gets),{"s","t","d"})
        self.assertEqual(self.model.batches,[])
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_empty_mailbox_completes_once_without_inventing_a_company(self):
        self.gmail.messages={}
        self.app.sync()
        self.app.sync()
        self.assertEqual(self.gmail.pages,[""])
        self.assertEqual(self.app.store.settings()["company"],"")
        self.assertEqual(self.model.batches,[])

    def test_pause_preserves_initialization_for_resume(self):
        self.app.store.save_settings({"paused":True})
        self.app.sync()
        self.assertEqual(self.gmail.pages,[])
        self.app.store.save_settings({"paused":False})
        self.app.sync()
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_deleted_message_during_import_is_not_an_endless_retry(self):
        original=self.gmail.get_message
        def get_message(mid):
            if mid=="a":raise ServiceError("Nicht mehr vorhanden",404)
            return original(mid)
        self.gmail.get_message=get_message
        self.app.sync()
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["imported"],1)
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"complete")

    def test_untrusted_settings_cannot_mark_first_run_complete(self):
        self.app.save_settings({"onboarding":"complete","history_id":"evil"})
        self.assertEqual(self.app.store.onboarding(ACCOUNT)["stage"],"pending")
        self.assertNotIn("history_id",self.app.store.settings())


class ParsingAndModelTests(unittest.TestCase):
    def test_first_run_request_has_no_date_or_inbox_filter_and_includes_sent(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail=Gmail(Path(temp))
            calls=[]
            gmail.api=lambda path:calls.append(path) or {"messages":[]}
            gmail.list_messages_page("next")
            query=parse_qs(urlparse(calls[0]).query)
            self.assertNotIn("q",query)
            self.assertEqual(query["includeSpamTrash"],["true"])
            self.assertEqual(query["maxResults"],["500"])
            self.assertEqual(query["pageToken"],["next"])

    def test_long_mail_is_not_truncated_in_archive_and_every_part_is_created(self):
        raw=mail("long",text="A"*120000,sent=True)
        parsed=archive_message(raw)
        self.assertEqual(len(parsed["body"]),120000)
        parts=analysis_parts(parsed,4096)
        self.assertEqual("".join(parts),parsed["body"])
        self.assertGreater(len(parts),50)

    def test_quoted_customers_are_not_own_writing_style(self):
        text="Guten Tag,\n\nunsere eigene Antwort.\n\nAm Mittwoch schrieb Kunde:\nFremder Schreibstil"
        self.assertNotIn("Fremder",own_text(text))
        self.assertNotIn("Fremder",own_text("Hallo\n> Fremder Schreibstil\nEigener Text"))

    def test_html_quotes_are_archived_but_excluded_from_own_style(self):
        raw=mail("html",sent=True)
        raw["payload"]["mimeType"]="text/html"
        raw["payload"]["body"]["data"]=base64.urlsafe_b64encode(b'<p>Unsere Antwort.</p><div class="gmail_quote"><div>Fremde Antwort.</div></div>').decode()
        parsed=archive_message(raw)
        self.assertIn("Fremde Antwort",parsed["body"])
        self.assertNotIn("Fremde Antwort","".join(analysis_parts(parsed,4096)))

    def test_customers_style_and_unverifiable_quotes_are_rejected(self):
        batch=[{"id":"x:0","message_id":"x","outgoing":0,"received":1,"subject":"Anfrage","text":"Wir sind Kundenfirma GmbH."}]
        model=Model()
        settings=dict(DEFAULTS)
        self.assertEqual(extract_findings(model,batch,settings,ACCOUNT),[])
        model.request=lambda *args,**kwargs:{"message":{"content":json.dumps({"findings":[{"field":"company","value":"Erfunden GmbH","source":"x:0","quote":"Nicht vorhandenes Zitat"}]})}}
        self.assertEqual(extract_findings(model,batch,settings,ACCOUNT),[])

    def test_remote_model_response_cannot_complete_learning(self):
        model=Model()
        model.request=lambda *args,**kwargs:{"remote_host":"https://ollama.com","message":{"content":'{"findings":[]}'}}
        with self.assertRaises(ServiceError):extract_findings(model,[],dict(DEFAULTS),ACCOUNT)


if __name__=="__main__":unittest.main()
