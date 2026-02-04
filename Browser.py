# browser.py
import socket
import ssl
import sys
import time
import gzip
import tkinter
import tkinter.font
import urllib.parse  # Chapter 8: for form encoding
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

# Chapter 8: Input width
INPUT_WIDTH_PX = 200

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
# Default stylesheet (Chapter 8: added input/button styles)
# -----------------------
DEFAULT_STYLE_SHEET_TEXT = """
    pre { background-color: gray; }
    a { color: blue; }
    i { font-style: italic; }
    b { font-weight: bold; }
    small { font-size: 90%; }
    big { font-size: 110%; }
    input { background-color: lightblue; }
    button { background-color: orange; }
"""


# ============================================================
# Chapter 6: CSS Parser
# ============================================================

class CSSParser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def whitespace(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self) -> str:
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
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(f"Parsing error: expected '{literal}'")
        self.i += 1

    def ignore_until(self, chars: List[str]) -> Optional[str]:
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    def pair(self) -> Tuple[str, str]:
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def body(self) -> Dict[str, str]:
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
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            tag = self.word()
            descendant = TagSelector(tag.casefold())
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def parse(self) -> List[Tuple[Union["TagSelector", "DescendantSelector"], Dict[str, str]]]:
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
    selector, body = rule
    return selector.priority


def style(node: "Node", rules: List[Tuple[Union[TagSelector, DescendantSelector], Dict[str, str]]]) -> None:
    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

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
# URL
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
            if rest.startswith("/") and len(rest) > 1 and rest[1] != "/":
                import os
                if os.name == 'nt':
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

    def resolve(self, url: str) -> "URL":
        if "://" in url:
            return URL(url)
        if url.startswith("//"):
            return URL(self.scheme + ":" + url)
        if url.startswith("/"):
            return URL(f"{self.scheme}://{self.host}:{self.port}{url}")
        dir_path, _ = self.path.rsplit("/", 1)
        while url.startswith("../"):
            _, url = url.split("/", 1)
            if "/" in dir_path:
                dir_path, _ = dir_path.rsplit("/", 1)
        return URL(f"{self.scheme}://{self.host}:{self.port}{dir_path}/{url}")


# ============================================================
# Chapter 4: HTML tree (DOM-like) - Chapter 8: added is_focused
# ============================================================

class Node:
    def __init__(self, parent: Optional["Element"]):
        self.parent = parent
        self.children: List["Node"] = []
        self.style: Dict[str, str] = {}
        self.is_focused: bool = False  # Chapter 8


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


def tree_to_list(tree, list_out: List) -> List:
    list_out.append(tree)
    for child in getattr(tree, 'children', []):
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
            if self.body.startswith("<!--", i):
                if text:
                    self.add_text(text)
                    text = ""
                end = self.body.find("-->", i + 4)
                if end == -1:
                    return self.finish()
                i = end + 3
                continue

            if self.body[i] == "<":
                if text:
                    self.add_text(text)
                    text = ""

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
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            self.unfinished[-1].children.append(node)
        return self.unfinished.pop()


# ============================================================
# Fonts
# ============================================================

FONTS: Dict[Tuple[int, str, str, str], Tuple[tkinter.font.Font, tkinter.Label]] = {}


def get_font(size: int, weight: str, slant: str, family: str = "Times") -> tkinter.font.Font:
    key = (size, weight, slant, family)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=slant, family=family)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


# ============================================================
# Helper: Parse font properties safely
# ============================================================

def parse_font_size(font_size_str: str) -> int:
    if not font_size_str:
        return 12
    if font_size_str.startswith("var") or not font_size_str.endswith("px"):
        return 12
    try:
        return int(float(font_size_str[:-2]) * 0.75)
    except (ValueError, TypeError):
        return 12


def parse_font_weight(weight_str: str) -> str:
    if not weight_str or weight_str.startswith("var"):
        return "normal"
    if weight_str in ("normal", "bold"):
        return weight_str
    try:
        w = int(weight_str)
        return "bold" if w >= 600 else "normal"
    except (ValueError, TypeError):
        return "normal"


def parse_font_style(style_str: str) -> str:
    if not style_str or style_str.startswith("var"):
        return "roman"
    if style_str == "italic" or style_str == "oblique":
        return "italic"
    return "roman"


# ============================================================
# Rect utility class
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
# Paint commands
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
        color = self.color if self.color and not self.color.startswith("var") else "black"
        try:
            canvas.create_text(
                self.rect.left, self.rect.top - scroll,
                text=self.text, font=self.font, anchor="nw", fill=color
            )
        except tkinter.TclError:
            canvas.create_text(
                self.rect.left, self.rect.top - scroll,
                text=self.text, font=self.font, anchor="nw", fill="black"
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
        if not self.color or self.color.startswith("var"):
            return
        try:
            canvas.create_rectangle(
                self.rect.left, self.rect.top - scroll,
                self.rect.right, self.rect.bottom - scroll,
                width=0, fill=self.color
            )
        except tkinter.TclError:
            pass


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
        color = self.color if self.color and not self.color.startswith("var") else "black"
        try:
            canvas.create_line(
                self.rect.left, self.rect.top - scroll,
                self.rect.right, self.rect.bottom - scroll,
                fill=color, width=self.thickness
            )
        except tkinter.TclError:
            pass


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
        color = self.color if self.color and not self.color.startswith("var") else "black"
        try:
            canvas.create_rectangle(
                self.rect.left, self.rect.top - scroll,
                self.rect.right, self.rect.bottom - scroll,
                width=self.thickness, outline=color
            )
        except tkinter.TclError:
            pass


# ============================================================
# Chapter 8: InputLayout - for input and button elements
# ============================================================

class InputLayout:
    def __init__(self, node: Element, parent: "LineLayout", previous):
        self.node = node
        self.children: List = []
        self.parent = parent
        self.previous = previous
        self.x: float = 0
        self.y: float = 0
        self.width: float = INPUT_WIDTH_PX
        self.height: float = 0
        self.font: Optional[tkinter.font.Font] = None

    def layout(self) -> None:
        weight = parse_font_weight(self.node.style.get("font-weight", "normal"))
        style_val = parse_font_style(self.node.style.get("font-style", "normal"))
        size = parse_font_size(self.node.style.get("font-size", "16px"))
        family = self.node.style.get("font-family", "Times")
        if family.startswith("var"):
            family = "Times"
        self.font = get_font(size, weight, style_val, family)

        self.width = INPUT_WIDTH_PX

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = self.font.metrics("linespace")

    def should_paint(self) -> bool:
        return True

    def self_rect(self) -> Rect:
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    def paint(self) -> List:
        cmds = []

        # Background color
        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            cmds.append(DrawRect(self.self_rect(), bgcolor))

        # Text content
        if self.node.tag == "input":
            text = self.node.attributes.get("value", "")
        elif self.node.tag == "button":
            if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
                text = self.node.children[0].text
            else:
                text = ""
        else:
            text = ""

        color = self.node.style.get("color", "black")
        cmds.append(DrawText(self.x, self.y, text, self.font, color))

        # Cursor for focused input
        if self.node.is_focused:
            cx = self.x + self.font.measure(text)
            cmds.append(DrawLine(cx, self.y, cx, self.y + self.height, "black", 1))

        return cmds


# ============================================================
# TextLayout
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
        weight = parse_font_weight(self.node.style.get("font-weight", "normal"))
        style_val = parse_font_style(self.node.style.get("font-style", "normal"))
        size = parse_font_size(self.node.style.get("font-size", "16px"))
        family = self.node.style.get("font-family", "Times")
        if family.startswith("var"):
            family = "Times"
        self.font = get_font(size, weight, style_val, family)

        self.width = self.font.measure(self.word)

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = self.font.metrics("linespace")

    def should_paint(self) -> bool:
        return True

    def paint(self) -> List[DrawText]:
        color = self.node.style.get("color", "black")
        return [DrawText(self.x, self.y, self.word, self.font, color)]


# ============================================================
# LineLayout
# ============================================================

class LineLayout:
    def __init__(self, node: Node, parent: "BlockLayout", previous: Optional["LineLayout"]):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children: List = []  # TextLayout or InputLayout
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

        for child in self.children:
            child.layout()

        if not self.children:
            self.height = 0
            return

        max_ascent = max([child.font.metrics("ascent") for child in self.children])
        baseline = self.y + 1.25 * max_ascent
        for child in self.children:
            child.y = baseline - child.font.metrics("ascent")
        max_descent = max([child.font.metrics("descent") for child in self.children])
        self.height = 1.25 * (max_ascent + max_descent)

    def should_paint(self) -> bool:
        return True

    def paint(self) -> List:
        return []


# ============================================================
# DocumentLayout
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

    def should_paint(self) -> bool:
        return True

    def paint(self) -> List:
        return []


# ============================================================
# BlockLayout (Chapter 8: added input handling)
# ============================================================

class BlockLayout:
    def __init__(self, node: Node, parent: Union["DocumentLayout", "BlockLayout"],
                 previous: Optional["BlockLayout"]):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children: List = []
        self.x: float = 0
        self.y: float = 0
        self.width: float = 0
        self.height: float = 0
        self.cursor_x: float = 0

    def layout_mode(self) -> str:
        if isinstance(self.node, Text):
            return "inline"
        assert isinstance(self.node, Element)

        # Chapter 8: input/button treated as inline
        if any([isinstance(child, Element) and child.tag in BLOCK_ELEMENTS
                for child in self.node.children]):
            return "block"
        elif self.node.children or self.node.tag == "input":
            return "inline"
        else:
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
            elif node.tag == "input" or node.tag == "button":
                self.input(node)
            else:
                for child in node.children:
                    self.recurse(child)

    def new_line(self) -> None:
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def word(self, node: Node, word: str) -> None:
        weight = parse_font_weight(node.style.get("font-weight", "normal"))
        style_val = parse_font_style(node.style.get("font-style", "normal"))
        size = parse_font_size(node.style.get("font-size", "16px"))
        family = node.style.get("font-family", "Times")
        if family.startswith("var"):
            family = "Times"
        font = get_font(size, weight, style_val, family)

        w = font.measure(word)
        if self.cursor_x + w > self.width:
            self.new_line()
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        text = TextLayout(node, word, line, previous_word)
        line.children.append(text)
        self.cursor_x += w + font.measure(" ")

    # Chapter 8: Handle input/button elements
    def input(self, node: Element) -> None:
        w = INPUT_WIDTH_PX
        if self.cursor_x + w > self.width:
            self.new_line()
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        input_layout = InputLayout(node, line, previous_word)
        line.children.append(input_layout)

        weight = parse_font_weight(node.style.get("font-weight", "normal"))
        style_val = parse_font_style(node.style.get("font-style", "normal"))
        size = parse_font_size(node.style.get("font-size", "16px"))
        family = node.style.get("font-family", "Times")
        if family.startswith("var"):
            family = "Times"
        font = get_font(size, weight, style_val, family)
        self.cursor_x += w + font.measure(" ")

    def self_rect(self) -> Rect:
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    # Chapter 8: Don't paint background for input/button (InputLayout does it)
    def should_paint(self) -> bool:
        return isinstance(self.node, Text) or \
            (self.node.tag != "input" and self.node.tag != "button")

    def paint(self) -> List:
        cmds = []
        if isinstance(self.node, Element):
            bgcolor = self.node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                cmds.append(DrawRect(self.self_rect(), bgcolor))
        return cmds


# Chapter 8: Updated paint_tree to use should_paint
def paint_tree(layout_obj, out: List) -> None:
    if layout_obj.should_paint():
        out.extend(layout_obj.paint())
    for child in layout_obj.children:
        paint_tree(child, out)


# ============================================================
# Chapter 8: Tab class - added focus, render, submit_form, keypress
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
        self.rules: List = []
        self.focus: Optional[Element] = None  # Chapter 8: focused input element

    def load(self, url: URL, payload: Optional[str] = None) -> None:
        self.url = url
        self.history.append(url)
        self.scroll = 0
        body = self.browser.fetch_url(url, payload)
        body = self.browser.decode_entities(body)
        self.nodes = HTMLParser(body).parse()

        self.rules = CSSParser(DEFAULT_STYLE_SHEET_TEXT).parse()
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
                self.rules.extend(CSSParser(style_body).parse())
            except:
                continue
        self.render()

    # Chapter 8: Separate render from load
    def render(self) -> None:
        style(self.nodes, sorted(self.rules, key=cascade_priority))
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

    # Chapter 8: Updated click to handle input/button
    def click(self, x: float, y: float) -> None:
        # Unfocus previous element
        if self.focus:
            self.focus.is_focused = False
        self.focus = None

        y += self.scroll
        objs = [obj for obj in tree_to_list(self.document, [])
                if hasattr(obj, 'x') and hasattr(obj, 'y') and hasattr(obj, 'width') and hasattr(obj, 'height')
                and obj.x <= x < obj.x + obj.width
                and obj.y <= y < obj.y + obj.height]
        if not objs:
            return self.render()

        elt = objs[-1].node
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elif elt.tag == "input":
                elt.attributes["value"] = ""
                self.focus = elt
                elt.is_focused = True
                return self.render()
            elif elt.tag == "button":
                # Find parent form
                while elt:
                    if elt.tag == "form" and "action" in elt.attributes:
                        return self.submit_form(elt)
                    elt = elt.parent
                return
            elt = elt.parent
        self.render()

    # Chapter 8: Form submission
    def submit_form(self, elt: Element) -> None:
        inputs = [node for node in tree_to_list(elt, [])
                  if isinstance(node, Element)
                  and node.tag == "input"
                  and "name" in node.attributes]

        body = ""
        for input_node in inputs:
            name = input_node.attributes["name"]
            value = input_node.attributes.get("value", "")
            name = urllib.parse.quote(name)
            value = urllib.parse.quote(value)
            body += "&" + name + "=" + value
        body = body[1:] if body else ""

        url = self.url.resolve(elt.attributes["action"])
        self.load(url, body)

    # Chapter 8: Handle keypress for focused input
    def keypress(self, char: str) -> None:
        if self.focus:
            self.focus.attributes["value"] = self.focus.attributes.get("value", "") + char
            self.render()

    def go_back(self) -> None:
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)


# ============================================================
# Chapter 8: Chrome class - added blur, updated keypress
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

        cmds.append(DrawRect(Rect(0, 0, WIDTH, self.bottom), "white"))
        cmds.append(DrawLine(0, self.bottom, WIDTH, self.bottom, "black", 1))

        cmds.append(DrawOutline(self.newtab_rect, "black", 1))
        cmds.append(DrawText(
            self.newtab_rect.left + self.padding,
            self.newtab_rect.top,
            "+", self.font, "black"
        ))

        for i, tab in enumerate(self.browser.tabs):
            bounds = self.tab_rect(i)
            cmds.append(DrawLine(bounds.left, 0, bounds.left, bounds.bottom, "black", 1))
            cmds.append(DrawLine(bounds.right, 0, bounds.right, bounds.bottom, "black", 1))
            cmds.append(DrawText(
                bounds.left + self.padding, bounds.top + self.padding,
                f"Tab {i}", self.font, "black"
            ))

            if tab == self.browser.active_tab:
                cmds.append(DrawLine(0, bounds.bottom, bounds.left, bounds.bottom, "black", 1))
                cmds.append(DrawLine(bounds.right, bounds.bottom, WIDTH, bounds.bottom, "black", 1))

        cmds.append(DrawOutline(self.back_rect, "black", 1))
        cmds.append(DrawText(
            self.back_rect.left + self.padding,
            self.back_rect.top,
            "<", self.font, "black"
        ))

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

    # Chapter 8: Returns True if chrome handled the keypress
    def keypress(self, char: str) -> bool:
        if self.focus == "address bar":
            self.address_bar += char
            return True
        return False

    def backspace(self) -> None:
        if self.focus == "address bar" and self.address_bar:
            self.address_bar = self.address_bar[:-1]

    def enter(self) -> None:
        if self.focus == "address bar":
            self.browser.active_tab.load(URL(self.address_bar))
            self.focus = None

    # Chapter 8: Remove focus from address bar
    def blur(self) -> None:
        self.focus = None


# ============================================================
# Browser (Chapter 8: added focus, updated event handlers)
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
        self.focus: Optional[str] = None  # Chapter 8: "content" or None

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

    # Chapter 8: Updated to manage focus between chrome and content
    def handle_click(self, e) -> None:
        if e.y < self.chrome.bottom:
            self.focus = None
            self.chrome.click(e.x, e.y)
        else:
            self.focus = "content"
            self.chrome.blur()
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
        self.draw()

    # Chapter 8: Route keypresses to chrome or content
    def handle_key(self, e) -> None:
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) < 0x7f):
            return

        if self.chrome.keypress(e.char):
            self.draw()
        elif self.focus == "content":
            self.active_tab.keypress(e.char)
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
    # Chapter 8: Added payload parameter for POST
    def fetch_url(self, url: URL, payload: Optional[str] = None) -> str:
        resp = self.fetch(url, redirects_left=MAX_REDIRECTS, payload=payload)
        return resp.body.decode("utf-8", errors="replace")

    def fetch(self, url: URL, redirects_left: int, payload: Optional[str] = None) -> Response:
        if url.scheme == "about":
            return Response(url=url, status=200, reason="OK", headers={}, body=b"")

        cache_key = url.cache_key()
        now = time.time()
        # Don't cache POST requests
        if url.scheme in ["http", "https"] and payload is None:
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

        resp = self.request_http(url, payload)

        if 300 <= resp.status <= 399 and "location" in resp.headers and redirects_left > 0:
            loc = resp.headers["location"]
            next_url = self.resolve_location(url, loc)
            prefix = "view-source:" if url.view_source else ""
            return self.fetch(URL(prefix + next_url), redirects_left - 1)

        if url.scheme in ["http", "https"] and resp.status == 200 and payload is None:
            expires_at = self.compute_cache_expiry(resp.headers.get("cache-control", ""))
            if expires_at is not None:
                self.cache[cache_key] = (expires_at, resp)

        return resp

    # Chapter 8: Added payload support for POST requests
    def request_http(self, url: URL, payload: Optional[str] = None) -> Response:
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

        # Chapter 8: POST vs GET
        method = "POST" if payload else "GET"
        headers = {
            "Host": url.host,
            "User-Agent": "toy-browser/8.0 (WebBrowserEngineering)",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip",
        }
        if payload:
            headers["Content-Length"] = str(len(payload.encode("utf-8")))
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = f"{method} {url.path} HTTP/1.1\r\n"
        req += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        req += "\r\n"
        if payload:
            req += payload
        s.send(req.encode("utf-8"))

        f = s.makefile("rb")
        statusline = f.readline().decode("iso-8859-1", errors="replace").rstrip("\r\n")
        if not statusline:
            self.close_socket(key)
            return self.request_http(url, payload)

        parts = statusline.split(" ", 2)
        if len(parts) < 2:
            self.close_socket(key)
            return self.request_http(url, payload)
        try:
            status_i = int(parts[1])
        except ValueError:
            self.close_socket(key)
            return self.request_http(url, payload)
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
                f.read(2)
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
