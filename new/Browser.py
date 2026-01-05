# browser.py
import socket
import ssl
import sys
import time
import gzip
import tkinter
import tkinter.font
from dataclasses import dataclass, replace
from typing import Dict, Optional, Tuple, List, Union

# -----------------------
# UI constants
# -----------------------
HSTEP = 13
SCROLL_STEP = 100
WIDTH, HEIGHT = 800, 600
MAX_REDIRECTS = 10
SOFT_HYPHEN = "\N{soft hyphen}"  # U+00AD

# -----------------------
# Networking response
# -----------------------
@dataclass
class Response:
    url: "URL"
    status: int
    reason: str
    headers: Dict[str, str]
    body: bytes

# -----------------------
# URL (ch1/ch2 essentials)
# -----------------------
class URL:
    def __init__(self, url: str):
        self.original = url
        self.view_source = False
        if url.startswith("view-source:"):
            self.view_source = True
            url = url[len("view-source:"):]

        if url == "about:blank":
            self.scheme, self.host, self.port, self.path = "about", "", 0, "blank"
            self.data_mime, self.data_payload = "text/plain", ""
            return

        if "://" in url:
            self.scheme, rest = url.split("://", 1)
        else:
            if url.startswith("data:"):
                self.scheme = "data"
                rest = url[len("data:"):]
            else:
                raise ValueError(f"Unsupported URL: {url}")

        assert self.scheme in ["http", "https", "file", "data"]

        self.host = ""
        self.port = 0
        self.path = "/"
        self.data_mime = "text/plain"
        self.data_payload = ""

        if self.scheme in ["http", "https"]:
            if "/" not in rest:
                rest += "/"
            hostport, path = rest.split("/", 1)
            self.path = "/" + path
            self.port = 80 if self.scheme == "http" else 443
            if ":" in hostport:
                self.host, port_str = hostport.split(":", 1)
                self.port = int(port_str)
            else:
                self.host = hostport

        elif self.scheme == "file":
            if not rest.startswith("/"):
                rest = "/" + rest
            self.path = rest

        elif self.scheme == "data":
            if "," not in rest:
                raise ValueError("Invalid data: URL (missing comma)")
            meta, payload = rest.split(",", 1)
            self.data_payload = payload
            self.data_mime = (meta.split(";", 1)[0] or "text/plain") if meta else "text/plain"

    def cache_key(self) -> str:
        if self.scheme in ["http", "https"]:
            return f"{self.scheme}://{self.host}:{self.port}{self.path}"
        if self.scheme == "file":
            return f"file://{self.path}"
        if self.scheme == "data":
            return f"data:{self.data_mime},{self.data_payload}"
        if self.scheme == "about":
            return "about:blank"
        return self.original


# ============================================================
# Chapter 4: HTML tree (DOM-like)
# ============================================================

class Node:
    def __init__(self, parent: Optional["Element"]):
        self.parent = parent
        self.children: List["Node"] = []

class Text(Node):
    def __init__(self, text: str, parent: Optional["Element"]):
        super().__init__(parent)
        self.text = text

    def __repr__(self) -> str:
        return repr(self.text)

class Element(Node):
    def __init__(self, tag: str, attributes: Dict[str, str], parent: Optional["Element"]):
        super().__init__(parent)
        self.tag = tag
        self.attributes = attributes

    def __repr__(self) -> str:
        return "<" + self.tag + ">"

def print_tree(node: Node, indent: int = 0) -> None:
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)

class HTMLParser:
    SELF_CLOSING_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    HEAD_TAGS = {
        "base", "basefont", "bgsound", "noscript",
        "link", "meta", "title", "style", "script",
    }

    def __init__(self, body: str):
        self.body = body
        self.unfinished: List[Element] = []

    def parse(self) -> Element:
        i = 0
        text = ""

        while i < len(self.body):
            # ---------- 4-1: comments ----------
            if self.body.startswith("<!--", i):
                if text:
                    self.add_text(text)
                    text = ""
                end = self.body.find("-->", i + 4)
                if end == -1:
                    return self.finish()
                i = end + 3
                continue

            # ---------- tags ----------
            if self.body[i] == "<":
                if text:
                    self.add_text(text)
                    text = ""

                # 4-2: script/style raw text
                if self.body.startswith("<script", i) or self.body.startswith("<style", i):
                    tag_end = self.body.find(">", i)
                    tag_text = self.body[i + 1 : tag_end]
                    tag, attrs = self.get_attributes(tag_text)
                    self.add_tag(tag_text)

                    close = f"</{tag}>"
                    end = self.body.lower().find(close, tag_end)
                    if end == -1:
                        return self.finish()

                    raw = self.body[tag_end + 1 : end]
                    self.add_text(raw)
                    self.add_tag(f"/{tag}")
                    i = end + len(close)
                    continue

                # normal tag
                j = self.body.find(">", i)
                if j == -1:
                    break
                self.add_tag(self.body[i + 1 : j])
                i = j + 1
            else:
                text += self.body[i]
                i += 1

        if text:
            self.add_text(text)
        return self.finish()

    # ---------------------------
    # Attribute parsing (4-3/4-4)
    # ---------------------------
    def get_attributes(self, text: str):
        parts = text.split(None, 1)
        if not parts:
            return "", {}
        tag = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        n = len(rest)

        attrs = {}
        i = 0
        while True:
            while i < n and rest[i].isspace():
                i += 1
            if i >= n:
                break

            # Skip unexpected leading characters to avoid getting stuck
            if not (rest[i].isalnum() or rest[i] in "-_:"):
                i += 1
                continue

            key_start = i
            while i < n and (rest[i].isalnum() or rest[i] in "-_:"):
                i += 1
            key = rest[key_start:i].lower()

            while i < n and rest[i].isspace():
                i += 1

            val = ""
            if i < n and rest[i] == "=":
                i += 1
                while i < n and rest[i].isspace():
                    i += 1
                if i < n and rest[i] in "\"'":
                    q = rest[i]
                    i += 1
                    val_start = i
                    while i < n and rest[i] != q:
                        i += 1
                    val = rest[val_start:i]
                    if i < n:
                        i += 1
                else:
                    val_start = i
                    while i < n and not rest[i].isspace() and rest[i] != ">":
                        i += 1
                    val = rest[val_start:i]

            if key:
                attrs[key] = val
        return tag, attrs

    # ---------------------------
    # Tree construction helpers
    # ---------------------------
    def add_text(self, text: str):
        if not text.strip():
            return
        self.implicit_tags(None)
        parent = self.unfinished[-1]
        parent.children.append(Text(text, parent))

    def add_tag(self, text: str):
        if text.startswith("!"):
            return
        tag, attrs = self.get_attributes(text)
        self.implicit_tags(tag)

        # ---------- closing tag (4-6) ----------
        if tag.startswith("/"):
            name = tag[1:]
            for i in range(len(self.unfinished) - 1, 0, -1):
                if self.unfinished[i].tag == name:
                    node = self.unfinished[i]
                    del self.unfinished[i:]
                    self.unfinished[-1].children.append(node)
                    return
            return

        # ---------- self closing ----------
        if tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            parent.children.append(Element(tag, attrs, parent))
            return

        # ---------- opening ----------
        parent = self.unfinished[-1]
        self.unfinished.append(Element(tag, attrs, parent))

    def implicit_tags(self, tag):
        while True:
            open_tags = [n.tag for n in self.unfinished]

            if not open_tags:
                self.unfinished.append(Element("html", {}, None))

            elif open_tags == ["html"]:
                self.unfinished.append(Element("body", {}, self.unfinished[-1]))

            elif open_tags == ["html", "body"]:
                break
            else:
                break

    def finish(self):
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            self.unfinished[-1].children.append(node)
        return self.unfinished.pop()


# ============================================================
# Chapter 3/4: Fonts + Layout (tree traversal + style stack)
# ============================================================

# Font cache
FONTS: Dict[Tuple[int, str, str, str], Tuple[tkinter.font.Font, tkinter.Label]] = {}

def get_font(size: int, weight: str, slant: str, family: str) -> tkinter.font.Font:
    key = (size, weight, slant, family)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=slant, family=family)
        label = tkinter.Label(font=font)  # helps metrics perf on some systems :contentReference[oaicite:9]{index=9}
        FONTS[key] = (font, label)
    return FONTS[key][0]

DisplayItem = Tuple[int, int, str, tkinter.font.Font]

@dataclass(frozen=True)
class Style:
    size: int = 16
    weight: str = "normal"
    slant: str = "roman"
    family: str = "Times"
    center: bool = False
    in_sup: bool = False
    in_abbr: bool = False
    in_pre: bool = False
    tag: Optional[str] = None

@dataclass
class LineItem:
    text: str
    font: tkinter.font.Font
    is_sup: bool = False

class Layout:
    """
    Tree-based layout: recursively walk the HTML tree and lay out text nodes.
    Formatting tags change the style stack (nested tags behave correctly).
    """
    def __init__(self, tree: Element, width: int):
        self.tree = tree
        self.width = max(width, 1)
        self.display_list: List[DisplayItem] = []

        self.style_stack: List[Style] = [Style()]

        self.line: List[LineItem] = []
        self.line_width = 0
        self.cursor_y = 0
        self.document_height = HEIGHT

        self.recurse(tree)
        self.flush_line(paragraph_gap=False)
        self.document_height = max(self.cursor_y + 50, HEIGHT)

    @property
    def style(self) -> Style:
        return self.style_stack[-1]

    def current_font(self) -> tkinter.font.Font:
        s = self.style
        return get_font(s.size, s.weight, s.slant, s.family)

    def push_style(self, **changes) -> None:
        self.style_stack.append(replace(self.style, **changes))

    def pop_style_to_tag(self, tagname: str) -> None:
        for i in range(len(self.style_stack) - 1, 0, -1):
            if self.style_stack[i].tag == tagname:
                del self.style_stack[i:]
                return

    def word_fits(self, w: int) -> bool:
        return (HSTEP + self.line_width + w) <= (self.width - HSTEP)

    def push_piece(self, text: str, font: tkinter.font.Font, is_sup: bool) -> None:
        self.line.append(LineItem(text=text, font=font, is_sup=is_sup))
        self.line_width += font.measure(text)

    def push_space(self) -> None:
        font = self.current_font()
        self.push_piece(" ", font, is_sup=False)

    def flush_line(self, paragraph_gap: bool) -> None:
        if not self.line:
            if paragraph_gap:
                self.cursor_y += 20
            return

        ascents = [it.font.metrics("ascent") for it in self.line]
        max_ascent = max(ascents) if ascents else 0
        max_descent = max(it.font.metrics("descent") for it in self.line) if self.line else 0

        non_sup_ascents = [it.font.metrics("ascent") for it in self.line if not it.is_sup]
        ref_ascent = max(non_sup_ascents) if non_sup_ascents else max_ascent

        baseline = self.cursor_y + max_ascent

        if self.style.center:
            start_x = max((self.width - self.line_width) // 2, HSTEP)
        else:
            start_x = HSTEP

        x = start_x
        for it in self.line:
            ascent = it.font.metrics("ascent")
            y_top = baseline - ascent
            if it.is_sup:
                y_top = baseline - ref_ascent
            self.display_list.append((x, y_top, it.text, it.font))
            x += it.font.measure(it.text)

        self.cursor_y = baseline + max_descent
        if paragraph_gap:
            self.cursor_y += 12

        self.line.clear()
        self.line_width = 0

    # ---- text placement helpers
    def add_word_plain(self, word: str) -> None:
        font = self.current_font()
        w = font.measure(word)

        if (not self.style.in_pre) and (not self.word_fits(w)) and self.line:
            self.flush_line(paragraph_gap=False)

        self.push_piece(word, font, is_sup=self.style.in_sup)
        if not self.style.in_pre:
            self.push_space()

    def add_word_with_soft_hyphens(self, word: str) -> None:
        font = self.current_font()
        plain = word.replace(SOFT_HYPHEN, "")
        plain_w = font.measure(plain)

        if self.style.in_pre:
            self.add_word_plain(plain)
            return

        if self.word_fits(plain_w) or not self.line:
            self.add_word_plain(plain)
            return

        if SOFT_HYPHEN not in word:
            self.flush_line(paragraph_gap=False)
            self.add_word_plain(plain)
            return

        parts = word.split(SOFT_HYPHEN)
        best_i = None
        best_prefix = ""
        for i in range(1, len(parts) + 1):
            prefix = "".join(parts[:i]) + "-"
            if self.word_fits(font.measure(prefix)):
                best_i = i
                best_prefix = prefix

        if best_i is None:
            self.flush_line(paragraph_gap=False)
            self.add_word_with_soft_hyphens(word)
            return

        self.add_word_plain(best_prefix)
        self.flush_line(paragraph_gap=False)
        remainder = "".join(parts[best_i:])
        if remainder:
            self.add_word_plain(remainder)

    def add_abbr_word(self, word: str) -> None:
        normal_font = self.current_font()
        small_size = max(8, int(self.style.size * 0.8))
        small_font = get_font(small_size, "bold", self.style.slant, self.style.family)

        runs: List[Tuple[str, tkinter.font.Font]] = []
        cur_font: Optional[tkinter.font.Font] = None
        cur_text = ""

        def flush_run():
            nonlocal cur_font, cur_text
            if cur_text:
                runs.append((cur_text, cur_font))
            cur_text = ""

        for ch in word:
            if ch.islower():
                out = ch.upper()
                f = small_font
            else:
                out = ch
                f = normal_font

            if cur_font is None:
                cur_font = f
                cur_text = out
            elif f == cur_font:
                cur_text += out
            else:
                flush_run()
                cur_font = f
                cur_text = out
        flush_run()

        total_w = sum(f.measure(t) for t, f in runs)
        if (not self.style.in_pre) and (not self.word_fits(total_w)) and self.line:
            self.flush_line(paragraph_gap=False)

        for t, f in runs:
            self.push_piece(t, f, is_sup=self.style.in_sup)
        if not self.style.in_pre:
            self.push_space()

    def add_pre_text(self, text: str) -> None:
        font = self.current_font()
        for ch in text:
            if ch == "\n":
                self.flush_line(paragraph_gap=False)
            elif ch == "\t":
                self.push_piece("    ", font, is_sup=self.style.in_sup)
            else:
                if ch == SOFT_HYPHEN:
                    continue
                self.push_piece(ch, font, is_sup=self.style.in_sup)

    # ---- tree walk
    def recurse(self, node: Node) -> None:
        if isinstance(node, Text):
            if self.style.in_pre:
                self.add_pre_text(node.text)
            else:
                for w in node.text.split():
                    if self.style.in_abbr:
                        self.add_abbr_word(w)
                    else:
                        self.add_word_with_soft_hyphens(w)
            return

        assert isinstance(node, Element)
        self.open_element(node)
        for child in node.children:
            self.recurse(child)
        self.close_element(node)

    def open_element(self, elt: Element) -> None:
        tag = elt.tag

        # block-ish controls
        if tag == "br":
            self.flush_line(paragraph_gap=False)
            return
        if tag == "p":
            self.flush_line(paragraph_gap=True)
            return

        # formatting
        if tag == "b":
            self.push_style(weight="bold", tag="b")
        elif tag == "i":
            self.push_style(slant="italic", tag="i")
        elif tag == "small":
            self.push_style(size=max(8, self.style.size - 2), tag="small")
        elif tag == "big":
            self.push_style(size=self.style.size + 4, tag="big")
        elif tag == "sup":
            self.push_style(size=max(8, self.style.size // 2), in_sup=True, tag="sup")
        elif tag == "abbr":
            self.push_style(in_abbr=True, tag="abbr")
        elif tag == "pre":
            self.flush_line(paragraph_gap=True)
            self.push_style(in_pre=True, family="Courier New", tag="pre")
        elif tag == "h1" and elt.attributes.get("class", "") == "title":
            self.flush_line(paragraph_gap=True)
            self.push_style(center=True, size=24, weight="bold", tag="h1-title")
        else:
            # other tags ignored in this chapter
            pass

    def close_element(self, elt: Element) -> None:
        tag = elt.tag
        if tag in ("br", "p"):
            return
        if tag == "h1" and elt.attributes.get("class", "") == "title":
            self.flush_line(paragraph_gap=True)
            self.pop_style_to_tag("h1-title")
            return
        if tag in ("b", "i", "small", "big", "sup", "abbr"):
            self.pop_style_to_tag(tag)
        elif tag == "pre":
            self.flush_line(paragraph_gap=True)
            self.pop_style_to_tag("pre")


# ============================================================
# Browser (ch1 networking + ch2 GUI + ch3/4 layout)
# ============================================================

class Browser:
    def __init__(self, default_file: str):
        self.sockets: Dict[Tuple[str, str, int], socket.socket] = {}
        self.cache: Dict[str, Tuple[float, Response]] = {}

        self.default_file = default_file

        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack(fill="both", expand=True)

        self.scroll = 0
        self.doc_height = HEIGHT
        self.current_url: Optional[str] = None

        self.tree: Optional[Element] = None
        self.display_list: List[DisplayItem] = []

        self.window.bind("<Down>", lambda e: self.scroll_by(+SCROLL_STEP))
        self.window.bind("<Up>", lambda e: self.scroll_by(-SCROLL_STEP))
        self.window.bind("<MouseWheel>", self.on_mousewheel)
        self.window.bind("<Button-4>", lambda e: self.scroll_by(-SCROLL_STEP))
        self.window.bind("<Button-5>", lambda e: self.scroll_by(+SCROLL_STEP))
        self.window.bind("<Configure>", self.on_resize)

    def load(self, url: Optional[str]) -> None:
        if not url:
            url = f"file://{self.default_file}"
        self.current_url = url

        try:
            u = URL(url)
        except Exception:
            u = URL("about:blank")
            self.current_url = "about:blank"

        resp = self.fetch(u, redirects_left=MAX_REDIRECTS)
        body_text = self.decode_text(resp)

        if resp.url.view_source:
            # Build the DOM directly so we render every character literally (no escaping/decoding)
            root = Element("html", {}, None)
            body = Element("body", {}, root)
            pre = Element("pre", {}, body)
            pre.children.append(Text(body_text, pre))
            body.children.append(pre)
            root.children.append(body)
            self.tree = root
        else:
            body_text = self.decode_entities(body_text)

            # Chapter 4: parse into a tree
            self.tree = HTMLParser(body_text).parse()

        self.relayout()
        self.scroll = 0
        self.draw()

    def relayout(self) -> None:
        w = max(self.canvas.winfo_width(), 1)
        h = max(self.canvas.winfo_height(), 1)
        assert self.tree is not None
        layout_obj = Layout(self.tree, width=w)
        self.display_list = layout_obj.display_list
        self.doc_height = max(layout_obj.document_height, h)

    def draw(self) -> None:
        self.canvas.delete("all")
        h = max(self.canvas.winfo_height(), 1)

        for x, y, text, font in self.display_list:
            if y > self.scroll + h:
                continue
            if y + font.metrics("linespace") < self.scroll:
                continue
            self.canvas.create_text(x, y - self.scroll, text=text, font=font, anchor="nw")

        self.clamp_scroll()

    # ---- scrolling
    def clamp_scroll(self) -> None:
        h = max(self.canvas.winfo_height(), 1)
        max_scroll = max(self.doc_height - h, 0)
        self.scroll = max(0, min(self.scroll, max_scroll))

    def scroll_by(self, delta: int) -> None:
        self.scroll += delta
        self.clamp_scroll()
        self.draw()

    def on_mousewheel(self, e) -> None:
        self.scroll_by(-SCROLL_STEP if e.delta > 0 else +SCROLL_STEP)

    def on_resize(self, e) -> None:
        if e.width < 50 or e.height < 50:
            return
        if not self.tree:
            return
        self.relayout()
        self.draw()

    # ---- chapter 1: fetch/request (gzip + chunked + basic cache/redirect)
    def fetch(self, url: URL, redirects_left: int) -> Response:
        if url.scheme == "about":
            return Response(url=url, status=200, reason="OK", headers={}, body=b"")

        cache_key = url.cache_key()
        now = time.time()
        if url.scheme in ["http", "https"]:
            cached = self.cache.get(cache_key)
            if cached:
                expires_at, resp = cached
                if now < expires_at:
                    return resp
                del self.cache[cache_key]

        if url.scheme == "file":
            with open(url.path, "rb") as f:
                return Response(url=url, status=200, reason="OK", headers={}, body=f.read())

        if url.scheme == "data":
            body = url.data_payload.encode("utf-8", errors="replace")
            return Response(url=url, status=200, reason="OK", headers={"content-type": url.data_mime}, body=body)

        resp = self.request_http(url)

        if 300 <= resp.status <= 399 and "location" in resp.headers and redirects_left > 0:
            loc = resp.headers["location"]
            next_url = self.resolve_location(url, loc)
            prefix = "view-source:" if url.view_source else ""
            return self.fetch(URL(prefix + next_url), redirects_left - 1)

        if url.scheme in ["http", "https"] and resp.status == 200:
            expires_at = self.compute_cache_expiry(resp.headers.get("cache-control", ""))
            if expires_at is not None:
                self.cache[cache_key] = (expires_at, resp)

        return resp

    def request_http(self, url: URL) -> Response:
        if url.view_source:
            inner_str = url.original
            if inner_str.startswith("view-source:"):
                inner_str = inner_str[len("view-source:"):]
            inner = URL(inner_str)
            resp = self.request_http(inner)
            return replace(resp, url=url)

        key = (url.scheme, url.host, url.port)
        s = self.sockets.get(key)
        if s is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            s.connect((url.host, url.port))
            if url.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=url.host)
            self.sockets[key] = s

        headers = {
            "Host": url.host,
            "User-Agent": "toy-browser/4.0 (WebBrowserEngineering)",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip",
        }

        req = f"GET {url.path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
        s.send(req.encode("utf-8"))

        f = s.makefile("rb")
        statusline = f.readline().decode("iso-8859-1", errors="replace").rstrip("\r\n")
        if not statusline:
            self.close_socket(key)
            return self.request_http(url)

        parts = statusline.split(" ", 2)
        if len(parts) < 2:
            self.close_socket(key)
            return self.request_http(url)
        try:
            status_i = int(parts[1])
        except ValueError:
            self.close_socket(key)
            return self.request_http(url)
        reason = parts[2] if len(parts) >= 3 else ""

        resp_headers: Dict[str, str] = {}
        while True:
            line = f.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            decoded = line.decode("iso-8859-1", errors="replace").rstrip("\r\n")
            if ":" not in decoded:
                continue
            k, v = decoded.split(":", 1)
            resp_headers[k.casefold()] = v.strip()

        body = self.read_body_bytes(f, resp_headers)

        if resp_headers.get("content-encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
            resp_headers.pop("content-encoding", None)

        if resp_headers.get("connection", "").lower() == "close":
            self.close_socket(key)

        return Response(url=url, status=status_i, reason=reason, headers=resp_headers, body=body)

    def read_body_bytes(self, f, headers: Dict[str, str]) -> bytes:
        if headers.get("transfer-encoding", "").lower() == "chunked":
            chunks = []
            while True:
                line = f.readline().strip()
                size = int(line.split(b";", 1)[0], 16)
                if size == 0:
                    while True:
                        trailer = f.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                chunks.append(f.read(size))
                f.read(2)  # CRLF
            return b"".join(chunks)

        if "content-length" in headers:
            return f.read(int(headers["content-length"]))

        return f.read()

    def resolve_location(self, base: URL, loc: str) -> str:
        if "://" in loc or loc.startswith(("data:", "file:", "view-source:", "about:")):
            return loc
        if loc.startswith("/"):
            return f"{base.scheme}://{base.host}:{base.port}{loc}"
        base_dir = base.path.rsplit("/", 1)[0]
        return f"{base.scheme}://{base.host}:{base.port}{base_dir}/{loc}"

    def compute_cache_expiry(self, cache_control: str) -> Optional[float]:
        cc = cache_control.lower()
        if not cc:
            return None
        parts = [p.strip() for p in cc.split(",") if p.strip()]
        for p in parts:
            if p == "no-store":
                return None
            if p.startswith("max-age="):
                try:
                    return time.time() + int(p.split("=", 1)[1])
                except ValueError:
                    return None
            return None
        return None

    def decode_text(self, resp: Response) -> str:
        return resp.body.decode("utf-8", errors="replace")

    def decode_entities(self, text: str) -> str:
        # keep minimal entities + soft hyphen for exercise 3-3
        return (
            text.replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&amp;", "&")
                .replace("&shy;", SOFT_HYPHEN)
        )

    def close_socket(self, key: Tuple[str, str, int]) -> None:
        s = self.sockets.pop(key, None)
        if s:
            try:
                s.close()
            except Exception:
                pass


if __name__ == "__main__":
    DEFAULT_FILE = "./test.html"
    url = sys.argv[1] if len(sys.argv) > 1 else None

    b = Browser(default_file=DEFAULT_FILE)
    b.load(url)
    tkinter.mainloop()
