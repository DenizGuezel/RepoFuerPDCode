from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit


TAGS = set("p div br b strong i em u s strike ul ol li blockquote a".split())
BLOCKS = {"p", "div", "li", "ul", "ol", "blockquote"}
OMIT = {"script", "style", "template", "iframe", "object", "svg", "math"}


def safe_link(value):
    if not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"} and parts.hostname and parts.username is None and "\\" not in parts.netloc:
            return value
    except ValueError:
        pass
    return ""


class DraftHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.markup = []
        self.plain = []
        self.tags = []
        self.hidden = []

    def newline(self):
        if self.plain and not self.plain[-1].endswith("\n"):
            self.plain.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag in OMIT:
            self.hidden.append(tag)
        if self.hidden or tag not in TAGS:
            return
        if tag in BLOCKS:
            self.newline()
        if tag == "br":
            self.markup.append("<br/>")
            self.plain.append("\n")
            return
        link = safe_link(dict(attrs).get("href")) if tag == "a" else ""
        self.markup.append(f'<a href="{escape(link, quote=True)}">' if link else f"<{tag}>")
        self.tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in self.tags:
            while self.tags:
                current = self.tags.pop()
                self.markup.append(f"</{current}>")
                if current in BLOCKS:
                    self.newline()
                if current == tag:
                    break

    def handle_data(self, text):
        if not self.hidden:
            self.markup.append(escape(text, quote=False))
            self.plain.append(text)


def sanitize_draft_html(value):
    if not isinstance(value, str) or len(value.encode()) > 400_000:
        raise ValueError("Die Formatierung ist zu umfangreich. Bitte kürze den Entwurf.")
    parser = DraftHTML()
    parser.feed(value)
    parser.close()
    markup = "".join(parser.markup + [f"</{tag}>" for tag in reversed(parser.tags)])
    if len(markup.encode()) > 400_000:
        raise ValueError("Die Formatierung ist zu umfangreich. Bitte kürze den Entwurf.")
    return markup, "".join(parser.plain).replace("\u00a0", " ").strip()
