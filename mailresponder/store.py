import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


LOCKED_SEND_STATES = {"sending", "sent", "send_uncertain"}
SEND_UNCERTAIN = "Gmail hat den Versand nicht eindeutig bestätigt. Prüfe den Ordner „Gesendet“ in Gmail, bevor du erneut antwortest."
EMPTY_DRAFT = {
    "draft": "", "draft_html": "", "draft_id": "", "remote_hash": "", "processed_id": "",
    "user_edited": 0, "notes": [], "sources": [], "generated_by": "", "duration": None,
}


DEFAULTS = {
    "company": "", "description": "", "signature": "", "tone": "Freundlich und professionell",
    "salutation": "Sie", "length": "Kompakt", "style_examples": "", "style_analysis": "", "instructions": "",
    "excluded_senders": "", "gmail_query": "in:inbox -category:promotions -category:social",
    "model": "qwen3:4b-instruct", "context_size": 4096, "automatic": False,
    "paused": False, "use_history": False, "sync_seconds": 120,
}


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "mailresponder.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, updated REAL NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_search USING fts5(id UNINDEXED, title, content);
                CREATE TABLE IF NOT EXISTS threads(
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, account TEXT NOT NULL DEFAULT '',
                    sender TEXT NOT NULL, sender_name TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, messages TEXT NOT NULL, received REAL NOT NULL,
                    latest_id TEXT NOT NULL, headers TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                    draft TEXT NOT NULL DEFAULT '', draft_html TEXT NOT NULL DEFAULT '', draft_id TEXT NOT NULL DEFAULT '',
                    remote_hash TEXT NOT NULL DEFAULT '', processed_id TEXT NOT NULL DEFAULT '',
                    user_edited INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '', duration REAL, generated_by TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
                    created REAL NOT NULL, automatic INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, created REAL NOT NULL, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS onboarding(
                    account TEXT PRIMARY KEY, stage TEXT NOT NULL DEFAULT 'listing',
                    started REAL NOT NULL, completed REAL, page_token TEXT NOT NULL DEFAULT '',
                    history_id TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    profile TEXT NOT NULL DEFAULT '{}', imported INTEGER NOT NULL DEFAULT 0,
                    sent INTEGER NOT NULL DEFAULT 0, analyzed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS mail_archive(
                    account TEXT NOT NULL, id TEXT NOT NULL, thread_id TEXT NOT NULL,
                    fetched INTEGER NOT NULL DEFAULT 0, missing INTEGER NOT NULL DEFAULT 0,
                    sender TEXT NOT NULL DEFAULT '', recipients TEXT NOT NULL DEFAULT '[]',
                    subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
                    labels TEXT NOT NULL DEFAULT '[]', outgoing INTEGER NOT NULL DEFAULT 0,
                    received REAL NOT NULL DEFAULT 0, PRIMARY KEY(account,id));
                CREATE TABLE IF NOT EXISTS learning_parts(
                    account TEXT NOT NULL, id TEXT NOT NULL, message_id TEXT NOT NULL,
                    text TEXT NOT NULL, outgoing INTEGER NOT NULL, received REAL NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account,id));
                CREATE TABLE IF NOT EXISTS learning_facts(
                    account TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL,
                    message_id TEXT NOT NULL, quote TEXT NOT NULL, received REAL NOT NULL,
                    PRIMARY KEY(account,field,value,message_id));
                CREATE INDEX IF NOT EXISTS archive_pending ON mail_archive(account,fetched);
                CREATE INDEX IF NOT EXISTS archive_received ON mail_archive(account,received DESC);
                CREATE INDEX IF NOT EXISTS parts_pending ON learning_parts(account,done,received);
            """)
            db.execute("BEGIN IMMEDIATE")
            if "draft_html" not in {row["name"] for row in db.execute("PRAGMA table_info(threads)")}:
                db.execute("ALTER TABLE threads ADD COLUMN draft_html TEXT NOT NULL DEFAULT ''")
            db.execute("UPDATE threads SET status='send_uncertain',error=? WHERE status='sending'", (SEND_UNCERTAIN,))
            # An interrupted generation can be retried; remote draft checks prevent duplicate writes.
            db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
            db.execute("UPDATE threads SET status='queued' WHERE status='generating'")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self):
        with self.connection() as db:
            values = {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}
        return {**DEFAULTS, **values}

    def save_settings(self, changes, internal=False):
        with self.connection() as db:
            for key, value in changes.items():
                if internal or key in DEFAULTS:
                    db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def save_user_settings(self, changes):
        profile_keys = {"company", "description", "tone", "salutation", "length", "signature", "style_examples", "style_analysis"}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE key='manual_profile_fields'").fetchone()
            manual = set(json.loads(row[0])) if row else set()
            manual.update(set(changes).intersection(profile_keys))
            for key,value in {**{k:v for k,v in changes.items() if k in DEFAULTS}, "manual_profile_fields":sorted(manual)}.items():
                db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key,json.dumps(value)))

    def begin_onboarding(self, account, history_id):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO onboarding(account,started,history_id) VALUES (?,?,?)", (account,time.time(),history_id))
        return self.onboarding(account)

    def onboarding(self, account):
        with self.connection() as db:
            row=db.execute("SELECT * FROM onboarding WHERE account=?",(account,)).fetchone()
            if not row:
                return {"stage":"pending", "listed":0, "downloaded":0, "sent":0, "parts_total":0, "parts_done":0, "error":"", "completed":None, "profile":{}}
            result=dict(row)
            result["profile"]=json.loads(result["profile"])
            if result["stage"]=="complete":
                result.update(listed=result["imported"],downloaded=result["imported"],parts_total=result["analyzed"],parts_done=result["analyzed"])
                return result
            counts=db.execute("SELECT count(*) AS listed, sum(fetched) AS downloaded, sum(outgoing) AS sent FROM mail_archive WHERE account=?",(account,)).fetchone()
            parts=db.execute("SELECT count(*) AS total, coalesce(sum(done),0) AS done FROM learning_parts WHERE account=?",(account,)).fetchone()
            result.update(listed=counts["listed"],downloaded=counts["downloaded"] or 0,sent=counts["sent"] or 0,parts_total=parts["total"],parts_done=parts["done"])
            return result

    def onboarding_update(self, account, **values):
        if not values or not set(values) <= {"stage","page_token","error"}:
            raise ValueError("Ungültiger Einrichtungsschritt.")
        with self.connection() as db:
            db.execute("UPDATE onboarding SET "+",".join(k+"=?" for k in values)+" WHERE account=?",list(values.values())+[account])

    def record_mail_page(self, account, messages, next_token):
        # Store a page and its continuation together, so a crash cannot skip message IDs.
        with self.connection() as db:
            for message in messages:
                db.execute("INSERT OR IGNORE INTO mail_archive(account,id,thread_id) VALUES (?,?,?)",(account,message["id"],message["threadId"]))
            db.execute("UPDATE onboarding SET page_token=?,stage=?,error='' WHERE account=?",(next_token,"listing" if next_token else "downloading",account))

    def pending_archive_messages(self, account, limit=50):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,thread_id FROM mail_archive WHERE account=? AND fetched=0 ORDER BY id LIMIT ?",(account,limit))]

    def save_archive_message(self, account, message, parts):
        with self.connection() as db:
            db.execute("UPDATE mail_archive SET fetched=1,missing=?,sender=?,recipients=?,subject=?,body=?,labels=?,outgoing=?,received=? WHERE account=? AND id=?",(
                int(message.get("missing",False)),message.get("sender",""),json.dumps(message.get("recipients",[])),message.get("subject",""),message.get("body",""),json.dumps(message.get("labels",[])),int(message.get("outgoing",False)),message.get("received",0),account,message["id"]))
            for index,text in enumerate(parts):
                db.execute("INSERT OR IGNORE INTO learning_parts(account,id,message_id,text,outgoing,received) VALUES (?,?,?,?,?,?)",(account,f'{message["id"]}:{index}',message["id"],text,int(message["outgoing"]),message["received"]))

    def learning_batch(self, account, char_budget):
        with self.connection() as db:
            rows=db.execute("SELECT p.*,a.subject FROM learning_parts p JOIN mail_archive a ON a.account=p.account AND a.id=p.message_id WHERE p.account=? AND p.done=0 ORDER BY p.received,p.id LIMIT 12",(account,)).fetchall()
        result=[]
        used=0
        for row in rows:
            item=dict(row)
            cost=len(item["text"])+min(160,len(item["subject"]))+160
            if result and used+cost>char_budget:
                break
            result.append(item)
            used+=cost
        return result

    def finish_learning_batch(self, account, parts, facts):
        with self.connection() as db:
            for fact in facts:
                db.execute("INSERT OR IGNORE INTO learning_facts VALUES (?,?,?,?,?,?)",(account,fact["field"],fact["value"],fact["message_id"],fact["quote"],fact["received"]))
            for part in parts:
                db.execute("UPDATE learning_parts SET done=1 WHERE account=? AND id=?",(account,part["id"]))

    def learned_facts(self, account):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT field,value,count(*) AS votes,max(received) AS recent FROM learning_facts WHERE account=? GROUP BY field,value ORDER BY votes DESC,recent DESC,value",(account,))]

    @staticmethod
    def _apply_profile(db, account, profile):
        values={r["key"]:json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}
        manual=set(values.get("manual_profile_fields",[]))
        origins=values.get("learned_profile_origins",{})
        for key,value in profile.items():
            if key not in DEFAULTS or not value or key in manual:
                continue
            current=values.get(key,DEFAULTS[key])
            previous=origins.get(key,{})
            if current!=DEFAULTS[key] and current!=previous.get("value"):
                continue
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(key,json.dumps(value)))
            origins[key]={"account":account,"value":value}
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("learned_profile_origins",json.dumps(origins)))

    def complete_onboarding(self, account, profile):
        # Serialize with user edits: an edit committed during analysis always takes precedence.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._apply_profile(db,account,profile)
            db.execute("UPDATE onboarding SET stage='complete',completed=?,error='',profile=?,imported=(SELECT count(*) FROM mail_archive WHERE account=? AND missing=0),sent=(SELECT count(*) FROM mail_archive WHERE account=? AND outgoing=1),analyzed=(SELECT count(*) FROM learning_parts WHERE account=? AND done=1) WHERE account=?",(time.time(),json.dumps(profile),account,account,account,account))

    def restore_learned_profile(self, account):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT stage,profile FROM onboarding WHERE account=?",(account,)).fetchone()
            if row and row["stage"]=="complete":
                self._apply_profile(db,account,json.loads(row["profile"]))

    def event(self, message):
        with self.connection() as db:
            db.execute("INSERT INTO events(created,message) VALUES (?,?)", (time.time(), message))
            db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 100)")

    def events(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 12")]

    def documents(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM knowledge ORDER BY updated DESC")]

    def save_document(self, title, content, doc_id=None):
        title, content = title.strip(), content.strip()
        if not title or not content:
            raise ValueError("Bitte gib einen Titel und einen Inhalt an.")
        if len(title) > 180 or len(content) > 200000:
            raise ValueError("Der Eintrag ist zu lang (maximal 200.000 Zeichen).")
        doc_id = doc_id or uuid.uuid4().hex
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?)", (doc_id, title, content, time.time()))
            db.execute("DELETE FROM knowledge_search WHERE id=?", (doc_id,))
            # Search chunks so a long document does not consume the model's whole context.
            for offset in range(0, len(content), 1000):
                db.execute("INSERT INTO knowledge_search VALUES (?,?,?)", (doc_id, title, content[offset:offset+1200]))
        return doc_id

    def delete_document(self, doc_id):
        with self.connection() as db:
            db.execute("DELETE FROM knowledge WHERE id=?", (doc_id,))
            db.execute("DELETE FROM knowledge_search WHERE id=?", (doc_id,))

    def search(self, query, limit=3):
        words = list(dict.fromkeys(re.findall(r"[\wäöüÄÖÜß]{3,}", query.lower())))
        stop = {"und", "der", "die", "das", "mit", "für", "eine", "einen", "einer", "ist", "sind", "ich", "wir", "sie", "hallo", "vielen", "danke", "bitte", "the", "and", "you"}
        words = [w for w in words if w not in stop][:40]
        if not words:
            return []
        expression = " OR ".join('"' + w + '"' for w in words)
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,title,content FROM knowledge_search WHERE knowledge_search MATCH ? ORDER BY bm25(knowledge_search) LIMIT ?",
                (expression, limit))]

    @staticmethod
    def decode(row):
        if not row:
            return None
        result = dict(row)
        for key in ("messages", "headers", "notes", "sources"):
            result[key] = json.loads(result[key])
        return result

    def threads(self):
        with self.connection() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM threads ORDER BY received DESC")]

    def thread(self, thread_id):
        with self.connection() as db:
            return self.decode(db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone())

    def upsert_thread(self, item, *, queue_automatically=False):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM threads WHERE id=?", (item["id"],)).fetchone()
            if old and (old["latest_id"] == item["latest_id"] or old["status"] == "sending"
                        or (old["status"] in LOCKED_SEND_STATES and item.get("outgoing"))):
                return False
            status = item.get("status", "new")
            if old and old["status"] not in LOCKED_SEND_STATES and (old["user_edited"] or old["draft_id"]):
                status = "protected"
            values = {k: item[k] for k in ("id", "source", "sender", "sender_name", "subject", "body", "received", "latest_id")}
            values.update(account=item.get("account", ""), messages=json.dumps(item["messages"]), headers=json.dumps(item["headers"]), status=status)
            if old:
                if old["status"] in LOCKED_SEND_STATES:
                    values.update({key: json.dumps(value) if isinstance(value, list) else value
                                   for key, value in EMPTY_DRAFT.items()})
                fields = [k for k in values if k != "id"]
                db.execute("UPDATE threads SET " + ",".join(k+"=?" for k in fields) + ",revision=revision+1,error='' WHERE id=?", [values[k] for k in fields]+[item["id"]])
            else:
                fields = list(values)
                db.execute("INSERT INTO threads ("+",".join(fields)+") VALUES ("+",".join("?" for _ in fields)+")", list(values.values()))
            if queue_automatically and status == "new":
                self._queue(db, item["id"], automatic=True)
        return True

    def update_thread(self, thread_id, **values):
        allowed = {"status", "draft", "draft_html", "draft_id", "remote_hash", "processed_id", "user_edited", "notes", "sources", "error", "duration", "generated_by"}
        if not values or not set(values) <= allowed:
            raise ValueError("Ungültige Änderung.")
        with self.connection() as db:
            db.execute("UPDATE threads SET "+",".join(k+"=?" for k in values)+",revision=revision+1 WHERE id=?", [json.dumps(v) if isinstance(v, list) else v for v in values.values()]+[thread_id])

    def finish_generation(self, thread_id, revision, values):
        # Compare-and-swap: never replace edits made while the model was running.
        with self.connection() as db:
            encoded = [json.dumps(v) if isinstance(v, list) else v for v in values.values()]
            cursor = db.execute("UPDATE threads SET "+",".join(k+"=?" for k in values)+",revision=revision+1 WHERE id=? AND revision=?", encoded+[thread_id, revision])
            return cursor.rowcount == 1

    def queue(self, thread_id, automatic=False):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._queue(db, thread_id, automatic)

    @staticmethod
    def _queue(db, thread_id, automatic):
        row = db.execute("SELECT status,user_edited FROM threads WHERE id=?", (thread_id,)).fetchone()
        if not row:
            raise ValueError("Nachricht nicht gefunden.")
        status = row["status"]
        if status in LOCKED_SEND_STATES or status == "protected" or row["user_edited"]:
            raise ValueError("Dieser Entwurf ist geschützt.")
        existing = db.execute("SELECT state FROM jobs WHERE thread_id=?", (thread_id,)).fetchone()
        if existing and existing["state"] == "queued":
            if not automatic:
                db.execute("UPDATE jobs SET automatic=0 WHERE thread_id=?", (thread_id,))
            if status == "queued":
                return False
        elif existing and existing["state"] == "running" and status == "generating":
            return False
        else:
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, thread_id, "queued", time.time(), int(automatic)))
        db.execute("UPDATE threads SET status='queued',error='',revision=revision+1 WHERE id=?", (thread_id,))
        return True

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE jobs SET state='done' WHERE state='queued'
                          AND NOT EXISTS(SELECT 1 FROM threads WHERE id=jobs.thread_id AND status='queued')""")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
                db.execute("UPDATE threads SET status='generating' WHERE id=?", (row["thread_id"],))
                return dict(row)
        return None

    def finish_job(self, job_id):
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))

    def history(self, sender, current_id, account):
        with self.connection() as db:
            results=[self.decode(r) for r in db.execute("SELECT * FROM threads WHERE sender=? AND id!=? AND source='gmail' AND account=? ORDER BY received DESC LIMIT 2", (sender, current_id, account))]
            archived=db.execute("SELECT thread_id AS id,subject,body,received FROM mail_archive WHERE account=? AND fetched=1 AND missing=0 AND thread_id!=? AND (sender=? OR instr(recipients,?)>0) AND labels NOT LIKE '%\"SPAM\"%' AND labels NOT LIKE '%\"TRASH\"%' AND labels NOT LIKE '%\"DRAFT\"%' ORDER BY received DESC LIMIT 10",(account,current_id,sender,json.dumps(sender))).fetchall()
            results.extend(dict(row) for row in archived)
        distinct={}
        for row in sorted(results,key=lambda r:r["received"],reverse=True):
            distinct.setdefault(row["id"],row)
        return list(distinct.values())[:2]

    def remove_gmail_data(self):
        with self.connection() as db:
            db.execute("DELETE FROM jobs WHERE thread_id IN (SELECT id FROM threads WHERE source='gmail')")
            db.execute("DELETE FROM threads WHERE source='gmail'")
            db.execute("DELETE FROM mail_archive")
            db.execute("DELETE FROM learning_parts")
            db.execute("DELETE FROM learning_facts")
            # Keep completed one-time markers and compact inferred profiles, so reconnecting does not
            # restart a historical import. Interrupted imports must restart after their data was erased.
            db.execute("DELETE FROM onboarding WHERE stage!='complete'")
            db.execute("DELETE FROM settings WHERE key IN ('history_id','last_sync','gmail_email')")
