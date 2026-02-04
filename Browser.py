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
VSTEP = 18
SCROLL_STEP = 100
WIDTH, HEIGHT = 800, 600
MAX_REDIRECTS = 10
SOFT_HYPHEN = "\N{soft hyphen}"  # U+00AD

# -----------------------
# Chapter 5: block elements
# -----------------------
BLOCK_ELEMENTS = [
    "html", "body", "article", "section", "nav", "aside",
    "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "header",
    "footer", "address", "p", "hr", "pre", "blockquote",
    "ol", "ul", "menu", "li", "dl", "dt", "dd", "figure",
    "figcaption", "main", "div", "table", "form", "fieldset",
    "legend", "details", "summary",
]

# -----------------------
# Chapter 6: Inherited Properties
# -----------------------
INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
    "font-family": "Times",
}

# -----------------------
# Default stylesheet
# -----------------------
DEFAULT_STYLE_SHEET_TEXT = """
    pre { background-color: gray; }
    a { color: blue; }
    i { font-style: italic; }
    b { font-weight: bold; }
    small { font-size: 90%; }
    big { font-size: 110%; }
"""


# ============================================================
# Chapter 6: CSS Parser
# ============================================================

class CSSParser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def whitespace(self) -> None:
        """Skip whitespace characters"""
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self) -> str:
        """Parse a CSS word (property, value, tag name, etc.)"""
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception("Parsing error: expected word")
        return self.s[start:self.i]

    def literal(self, literal: str) -> None:
        """Expect and consume a literal character"""
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(f"Parsing error: expected '{literal}'")
        self.i += 1

    def ignore_until(self, chars: List[str]) -> Optional[str]:
        """Skip until one of the given characters"""
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    def pair(self) -> Tuple[str, str]:
        """Parse a property:value pair"""
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def body(self) -> Dict[str, str]:
        """Parse CSS body (property-value pairs)"""
        pairs = {}
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, val = self.pair()
                pairs[prop] = val
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception:
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def selector(self) -> Union["TagSelector", "DescendantSelector"]:
        """Parse a CSS selector"""
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            tag = self.word()
            descendant = TagSelector(tag.casefold())
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def parse(self) -> List[Tuple[Union["TagSelector", "DescendantSelector"], Dict[str, str]]]:
        """Parse CSS file into rules"""
        rules = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                body = self.body()
                self.literal("}")
                rules.append((selector, body))
            except Exception:
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules


# ============================================================
# Chapter 6: CSS Selectors
# ============================================================

class TagSelector:
    def __init__(self, tag: str):
        self.tag = tag
        self.priority = 1

    def matches(self, node: "Node") -> bool:
        return isinstance(node, Element) and self.tag == node.tag


class DescendantSelector:
    def __init__(self, ancestor: Union[TagSelector, "DescendantSelector"],
                 descendant: TagSelector):
        self.ancestor = ancestor
        self.descendant = descendant
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node: "Node") -> bool:
        if not self.descendant.matches(node):
            return False
        while node.parent:
            if self.ancestor.matches(node.parent):
                return True
            node = node.parent
        return False


# ============================================================
# Chapter 6: Styling Functions
# ============================================================

def cascade_priority(rule: Tuple[Union[TagSelector, DescendantSelector], Dict[str, str]]) -> int:
    """Return priority for cascade ordering"""
    selector, body = rule
    return selector.priority


def style(node: "Node", rules: List[Tuple[Union[TagSelector, DescendantSelector], Dict[str, str]]]) -> None:
    """Apply CSS styles to node tree"""
    # Set inherited properties
    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    # Apply matching CSS rules
    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    # Apply inline style attribute (highest priority)
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    # Resolve percentage font sizes
    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    # Recurse to children
    for child in node.children:
        style(child, rules)


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
# URL (ch1/ch2 essentials + ch7 __str__)
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
            # Windows 경로 처리 개선
            if rest.startswith("/") and len(rest) > 1 and rest[1] != "/":
                import os
                if os.name == 'nt':  # Windows
                    if len(rest) > 2 and rest[2] == ':':
                        self.path = rest[1:]
                    elif rest.startswith("/./"):
                        self.path = rest[2:]
                    else:
                        self.path = rest
                else:
                    self.path = rest
            else:
                self.path = rest

        elif self.scheme == "data":
            if "," not in rest:
                raise ValueError("Invalid data: URL (missing comma)")
            meta, payload = rest.split(",", 1)
            self.data_payload = payload
            self.data_mime = (meta.split(";", 1)[0] or "text/plain") if meta else "text/plain"

    # Chapter 7: String representation for address bar
    def __str__(self) -> str:
        if self.scheme == "about":
            return "about:blank"
        if self.scheme == "data":
            return f"data:{self.data_mime},{self.data_payload[:20]}..."
        if self.scheme == "file":
            return f"file://{self.path}"
        port_part = ":" + str(self.port)
        if self.scheme == "https" and self.port == 443:
            port_part = ""
        if self.scheme == "http" and self.port == 80:
            port_part = ""
        return self.scheme + "://" + self.host + port_part + self.path

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

    # Chapter 6: Resolve relative URLs
    def resolve(self, url: str) -> "URL":
        """Convert relative URLs to absolute URLs"""
        if "://" in url:
            return URL(url)

        # Scheme-relative URL (starts with //)
        if url.startswith("//"):
            return URL(self.scheme + ":" + url)

        # Host-relative URL (starts with /)
        if url.startswith("/"):
            return URL(f"{self.scheme}://{self.host}:{self.port}{url}")

        # Path-relative URL
        dir_path, _ = self.path.rsplit("/", 1)

        # Handle parent directory (..)
        while url.startswith("../"):
            _, url = url.split("/", 1)
            if "/" in dir_path:
                dir_path, _ = dir_path.rsplit("/", 1)

        return URL(f"{self.scheme}://{self.host}:{self.port}{dir_path}/{url}")


# ============================================================
# Chapter 4: HTML tree (DOM-like)
# ============================================================

class Node:
    def __init__(self, parent: Optional["Element"]):
        self.parent = parent
        self.children: List["Node"] = []
        self.style: Dict[str, str] = {}  # Chapter 6: style dictionary

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

# Chapter 6: Tree to list helper
def tree_to_list(tree: Node, list_out: List[Node]) -> List[Node]:
    """Convert tree to flat list of nodes"""
    list_out.append(tree)
    for child in tree.children:
        tree_to_list(child, list_out)
    return list_out

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

        if tag.startswith("/"):
            name = tag[1:]
            for i in range(len(self.unfinished) - 1, 0, -1):
                if self.unfinished[i].tag == name:
                    node = self.unfinished[i]
                    del self.unfinished[i:]
                    self.unfinished[-1].children.append(node)
                    return
            return

        if tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            parent.children.append(Element(tag, attrs, parent))
            return

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
        # Handle empty document
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            self.unfinished[-1].children.append(node)
        return self.unfinished.pop()


# ============================================================
# Chapter 3/4: Fonts
# ============================================================

# Font cache
FONTS: Dict[Tuple[int, str, str, str], Tuple[tkinter.font.Font, tkinter.Label]] = {}

def get_font(size: int, weight: str, slant: str, family: str = "Times") -> tkinter.font.Font:
    key = (size, weight, slant, family)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=slant, family=family)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


# ============================================================
# Chapter 7: Rect utility class
# ============================================================

class Rect:
    def __init__(self, left: float, top: float, right: float, bottom: float):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def contains_point(self, x: float, y: float) -> bool:
        return x >= self.left and x < self.right \
            and y >= self.top and y < self.bottom


# ============================================================
# Chapter 5/7: Paint commands (display list items)
# ============================================================

class DrawText:
    def __init__(self, x1: float, y1: float, text: str, font: tkinter.font.Font, color: str):
        self.rect = Rect(x1, y1, x1 + font.measure(text), y1 + font.metrics("linespace"))
        self.text = text
        self.font = font
        self.color = color

    @property
    def top(self) -> float:
        return self.rect.top

    @property
    def bottom(self) -> float:
        return self.rect.bottom

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_text(
            self.rect.left, self.rect.top - scroll,
            text=self.text, font=self.font, anchor="nw", fill=self.color
        )


class DrawRect:
    def __init__(self, rect: Rect, color: str):
        self.rect = rect
        self.color = color

    @property
    def top(self) -> float:
        return self.rect.top

    @property
    def bottom(self) -> float:
        return self.rect.bottom

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_rectangle(
            self.rect.left, self.rect.top - scroll,
            self.rect.right, self.rect.bottom - scroll,
            width=0, fill=self.color
        )


class DrawLine:
    def __init__(self, x1: float, y1: float, x2: float, y2: float, color: str, thickness: int):
        self.rect = Rect(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    @property
    def top(self) -> float:
        return self.rect.top

    @property
    def bottom(self) -> float:
        return self.rect.bottom

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_line(
            self.rect.left, self.rect.top - scroll,
            self.rect.right, self.rect.bottom - scroll,
            fill=self.color, width=self.thickness
        )


class DrawOutline:
    def __init__(self, rect: Rect, color: str, thickness: int):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    @property
    def top(self) -> float:
        return self.rect.top

    @property
    def bottom(self) -> float:
        return self.rect.bottom

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_rectangle(
            self.rect.left, self.rect.top - scroll,
            self.rect.right, self.rect.bottom - scroll,
            width=self.thickness, outline=self.color
        )


# ============================================================
# Chapter 7: TextLayout - individual word layout
# ============================================================

class TextLayout:
    def __init__(self, node: Node, word: str, parent: "LineLayout", previous: Optional["TextLayout"]):
        self.node = node
        self.word = word
        self.children: List = []
        self.parent = parent
        self.previous = previous
        self.x: float = 0
        self.y: float = 0
        self.width: float = 0
        self.height: float = 0
        self.font: Optional[tkinter.font.Font] = None

    def layout(self) -> None:
        weight = self.node.style["font-weight"]
        style_val = self.node.style["font-style"]
        if style_val == "normal":
            style_val = "roman"
        size = int(float(self.node.style["font-size"][:-2]) * 0.75)
        family = self.node.style.get("font-family", "Times")
        self.font = get_font(size, weight, style_val, family)

        self.width = self.font.measure(self.word)

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = self.font.metrics("linespace")

    def paint(self) -> List[DrawText]:
        color = self.node.style["color"]
        return [DrawText(self.x, self.y, self.word, self.font, color)]


# ============================================================
# Chapter 7: LineLayout - single line of text
# ============================================================

class LineLayout:
    def __init__(self, node: Node, parent: "BlockLayout", previous: Optional["LineLayout"]):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children: List[TextLayout] = []
        self.x: float = 0
        self.y: float = 0
        self.width: float = 0
        self.height: float = 0

    def layout(self) -> None:
        self.width = self.parent.width
        self.x = self.parent.x

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        for word in self.children:
            word.layout()

        if not self.children:
            self.height = 0
            return

        max_ascent = max([word.font.metrics("ascent") for word in self.children])
        baseline = self.y + 1.25 * max_ascent
        for word in self.children:
            word.y = baseline - word.font.metrics("ascent")
        max_descent = max([word.font.metrics("descent") for word in self.children])
        self.height = 1.25 * (max_ascent + max_descent)

    def paint(self) -> List:
        return []


# ============================================================
# Chapter 5/7: Layout tree (DocumentLayout + BlockLayout)
# ============================================================

class DocumentLayout:
    def __init__(self, node: Element):
        self.node = node
        self.parent = None
        self.children: List["BlockLayout"] = []
        self.x = HSTEP
        self.y = VSTEP
        self.width: float = 0
        self.height: float = 0

    def layout(self) -> None:
        child = BlockLayout(self.node, self, previous=None)
        self.children = [child]
        self.width = WIDTH - 2 * HSTEP
        child.layout()
        self.height = child.height

    def paint(self) -> List:
        return []


class BlockLayout:
    def __init__(self, node: Node, parent: Union["DocumentLayout", "BlockLayout"],
                 previous: Optional["BlockLayout"]):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children: List[Union["BlockLayout", LineLayout]] = []
        self.x: float = 0
        self.y: float = 0
        self.width: float = 0
        self.height: float = 0
        self.cursor_x: float = 0

    def layout_mode(self) -> str:
        if isinstance(self.node, Text):
            return "inline"
        assert isinstance(self.node, Element)

        for child in self.node.children:
            if isinstance(child, Element) and child.tag in BLOCK_ELEMENTS:
                return "block"

        if self.node.children:
            return "inline"
        return "block"

    def layout(self) -> None:
        self.x = self.parent.x
        self.width = self.parent.width

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        mode = self.layout_mode()

        if mode == "block":
            previous = None
            for child in self.node.children:
                next_block = BlockLayout(child, self, previous)
                self.children.append(next_block)
                previous = next_block
        else:
            self.cursor_x = 0
            self.new_line()
            self.recurse(self.node)

        for child in self.children:
            child.layout()

        self.height = sum([child.height for child in self.children])

    def recurse(self, node: Node) -> None:
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(node, word)
        else:
            if node.tag == "br":
                self.new_line()
            for child in node.children:
                self.recurse(child)

    def new_line(self) -> None:
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def word(self, node: Node, word: str) -> None:
        weight = node.style["font-weight"]
        style_val = node.style["font-style"]
        if style_val == "normal":
            style_val = "roman"
        size = int(float(node.style["font-size"][:-2]) * 0.75)
        family = node.style.get("font-family", "Times")
        font = get_font(size, weight, style_val, family)

        w = font.measure(word)
        if self.cursor_x + w > self.width:
            self.new_line()
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        text = TextLayout(node, word, line, previous_word)
        line.children.append(text)
        self.cursor_x += w + font.measure(" ")

    def self_rect(self) -> Rect:
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    def paint(self) -> List:
        cmds = []
        if isinstance(self.node, Element):
            bgcolor = self.node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                cmds.append(DrawRect(self.self_rect(), bgcolor))
        return cmds


def paint_tree(layout_obj: Union[DocumentLayout, BlockLayout, LineLayout, TextLayout],
               out: List) -> None:
    out.extend(layout_obj.paint())
    for child in layout_obj.children:
        paint_tree(child, out)


# ============================================================
# Chapter 7: Tab class - manages individual web pages
# ============================================================

class Tab:
    def __init__(self, tab_height: float, browser: "Browser"):
        self.browser = browser
        self.url: Optional[URL] = None
        self.history: List[URL] = []
        self.tab_height = tab_height
        self.scroll: float = 0
        self.nodes: Optional[Element] = None
        self.document: Optional[DocumentLayout] = None
        self.display_list: List = []

    def load(self, url: URL) -> None:
        self.url = url
        self.history.append(url)
        body = self.browser.fetch_url(url)
        body = self.browser.decode_entities(body)
        self.nodes = HTMLParser(body).parse()

        rules = CSSParser(DEFAULT_STYLE_SHEET_TEXT).parse()
        links = [node.attributes["href"]
                 for node in tree_to_list(self.nodes, [])
                 if isinstance(node, Element)
                 and node.tag == "link"
                 and node.attributes.get("rel") == "stylesheet"
                 and "href" in node.attributes]
        for link in links:
            try:
                style_url = url.resolve(link)
                style_body = self.browser.fetch_url(style_url)
                rules.extend(CSSParser(style_body).parse())
            except:
                continue
        style(self.nodes, sorted(rules, key=cascade_priority))

        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)

    def draw(self, canvas: tkinter.Canvas, offset: float) -> None:
        for cmd in self.display_list:
            if cmd.rect.top > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)

    def scrolldown(self) -> None:
        max_y = max(self.document.height + 2 * VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)

    def scrollup(self) -> None:
        self.scroll = max(self.scroll - SCROLL_STEP, 0)

    def click(self, x: float, y: float) -> None:
        y += self.scroll
        objs = [obj for obj in tree_to_list(self.document, [])
                if isinstance(obj, TextLayout)
                and obj.x <= x < obj.x + obj.width
                and obj.y <= y < obj.y + obj.height]
        if not objs:
            return
        elt = objs[-1].node
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elt = elt.parent

    def go_back(self) -> None:
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)


# ============================================================
# Chapter 7: Chrome class - browser UI
# ============================================================

class Chrome:
    def __init__(self, browser: "Browser"):
        self.browser = browser
        self.focus: Optional[str] = None
        self.address_bar: str = ""

        self.font = get_font(20, "normal", "roman")
        self.font_height = self.font.metrics("linespace")

        self.padding = 5
        self.tabbar_top = 0
        self.tabbar_bottom = self.font_height + 2 * self.padding

        plus_width = self.font.measure("+") + 2 * self.padding
        self.newtab_rect = Rect(
            self.padding, self.padding,
            self.padding + plus_width,
            self.padding + self.font_height
        )

        self.urlbar_top = self.tabbar_bottom
        self.urlbar_bottom = self.urlbar_top + self.font_height + 2 * self.padding

        back_width = self.font.measure("<") + 2 * self.padding
        self.back_rect = Rect(
            self.padding,
            self.urlbar_top + self.padding,
            self.padding + back_width,
            self.urlbar_bottom - self.padding
        )

        self.address_rect = Rect(
            self.back_rect.right + self.padding,
            self.urlbar_top + self.padding,
            WIDTH - self.padding,
            self.urlbar_bottom - self.padding
        )

        self.bottom = self.urlbar_bottom

    def tab_rect(self, i: int) -> Rect:
        tabs_start = self.newtab_rect.right + self.padding
        tab_width = self.font.measure("Tab X") + 2 * self.padding
        return Rect(
            tabs_start + tab_width * i, self.tabbar_top,
            tabs_start + tab_width * (i + 1), self.tabbar_bottom
        )

    def paint(self) -> List:
        cmds = []

        # Background
        cmds.append(DrawRect(Rect(0, 0, WIDTH, self.bottom), "white"))
        cmds.append(DrawLine(0, self.bottom, WIDTH, self.bottom, "black", 1))

        # New tab button
        cmds.append(DrawOutline(self.newtab_rect, "black", 1))
        cmds.append(DrawText(
            self.newtab_rect.left + self.padding,
            self.newtab_rect.top,
            "+", self.font, "black"
        ))

        # Tab bar
        for i, tab in enumerate(self.browser.tabs):
            bounds = self.tab_rect(i)
            cmds.append(DrawLine(
                bounds.left, 0, bounds.left, bounds.bottom,
                "black", 1
            ))
            cmds.append(DrawLine(
                bounds.right, 0, bounds.right, bounds.bottom,
                "black", 1
            ))
            cmds.append(DrawText(
                bounds.left + self.padding, bounds.top + self.padding,
                f"Tab {i}", self.font, "black"
            ))

            if tab == self.browser.active_tab:
                cmds.append(DrawLine(
                    0, bounds.bottom, bounds.left, bounds.bottom,
                    "black", 1
                ))
                cmds.append(DrawLine(
                    bounds.right, bounds.bottom, WIDTH, bounds.bottom,
                    "black", 1
                ))

        # Back button
        cmds.append(DrawOutline(self.back_rect, "black", 1))
        cmds.append(DrawText(
            self.back_rect.left + self.padding,
            self.back_rect.top,
            "<", self.font, "black"
        ))

        # Address bar
        cmds.append(DrawOutline(self.address_rect, "black", 1))
        if self.focus == "address bar":
            cmds.append(DrawText(
                self.address_rect.left + self.padding,
                self.address_rect.top,
                self.address_bar, self.font, "black"
            ))
            w = self.font.measure(self.address_bar)
            cmds.append(DrawLine(
                self.address_rect.left + self.padding + w,
                self.address_rect.top,
                self.address_rect.left + self.padding + w,
                self.address_rect.bottom,
                "red", 1
            ))
        else:
            url = str(self.browser.active_tab.url) if self.browser.active_tab.url else ""
            cmds.append(DrawText(
                self.address_rect.left + self.padding,
                self.address_rect.top,
                url, self.font, "black"
            ))

        return cmds

    def click(self, x: float, y: float) -> None:
        self.focus = None
        if self.newtab_rect.contains_point(x, y):
            self.browser.new_tab(URL("about:blank"))
        elif self.back_rect.contains_point(x, y):
            self.browser.active_tab.go_back()
        elif self.address_rect.contains_point(x, y):
            self.focus = "address bar"
            self.address_bar = ""
        else:
            for i, tab in enumerate(self.browser.tabs):
                if self.tab_rect(i).contains_point(x, y):
                    self.browser.active_tab = tab
                    break

    def keypress(self, char: str) -> None:
        if self.focus == "address bar":
            self.address_bar += char

    def backspace(self) -> None:
        if self.focus == "address bar" and self.address_bar:
            self.address_bar = self.address_bar[:-1]

    def enter(self) -> None:
        if self.focus == "address bar":
            self.browser.active_tab.load(URL(self.address_bar))
            self.focus = None


# ============================================================
# Browser (ch7: multi-tab, chrome UI)
# ============================================================

class Browser:
    def __init__(self):
        self.sockets: Dict[Tuple[str, str, int], socket.socket] = {}
        self.cache: Dict[str, Tuple[float, Response]] = {}

        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT, bg="white")
        self.canvas.pack(fill="both", expand=True)

        self.tabs: List[Tab] = []
        self.active_tab: Optional[Tab] = None
        self.chrome = Chrome(self)

        self.window.bind("<Down>", self.handle_down)
        self.window.bind("<Up>", self.handle_up)
        self.window.bind("<Button-1>", self.handle_click)
        self.window.bind("<Key>", self.handle_key)
        self.window.bind("<Return>", self.handle_enter)
        self.window.bind("<BackSpace>", self.handle_backspace)
        self.window.bind("<MouseWheel>", self.handle_mousewheel)

    def new_tab(self, url: URL) -> None:
        new_tab = Tab(HEIGHT - self.chrome.bottom, self)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()

    def handle_down(self, e) -> None:
        self.active_tab.scrolldown()
        self.draw()

    def handle_up(self, e) -> None:
        self.active_tab.scrollup()
        self.draw()

    def handle_click(self, e) -> None:
        if e.y < self.chrome.bottom:
            self.chrome.click(e.x, e.y)
        else:
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
        self.draw()

    def handle_key(self, e) -> None:
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) < 0x7f):
            return
        self.chrome.keypress(e.char)
        self.draw()

    def handle_enter(self, e) -> None:
        self.chrome.enter()
        self.draw()

    def handle_backspace(self, e) -> None:
        self.chrome.backspace()
        self.draw()

    def handle_mousewheel(self, e) -> None:
        if e.delta > 0:
            self.active_tab.scrollup()
        else:
            self.active_tab.scrolldown()
        self.draw()

    def draw(self) -> None:
        self.canvas.delete("all")
        self.active_tab.draw(self.canvas, self.chrome.bottom)
        for cmd in self.chrome.paint():
            cmd.execute(0, self.canvas)

    # ---- Networking methods ----
    def fetch_url(self, url: URL) -> str:
        resp = self.fetch(url, redirects_left=MAX_REDIRECTS)
        return resp.body.decode("utf-8", errors="replace")

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
            "User-Agent": "toy-browser/7.0 (WebBrowserEngineering)",
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

    def decode_entities(self, text: str) -> str:
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
    url_arg = sys.argv[1] if len(sys.argv) > 1 else "file://./test.html"
    browser = Browser()
    browser.new_tab(URL(url_arg))
    tkinter.mainloop()
