import tkinter
import tkinter.font
import os
from pathlib import Path

from URL import URL

X_POS = 100
Y_POS = 100
WIDTH = 800
HEIGHT = 600
HSTEP = 13
VSETEP = 18
SCROLL_STEP = 100

FONTS = {}

def get_font(size, weight, style):
    key = (size, weight, style)
    if key not in FONTS:
        # Use a default family for better layout consistency
        font = tkinter.font.Font(family='Arial', size=size, weight=weight, slant=style)
        # label is used to ensure font metrics are available
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent

    def __repr__(self):
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.attributes = attributes
        self.children = []
        self.parent = parent

    def __repr__(self):
        return f"<{self.tag}>"


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished = []

    def parse(self):
        # Tokenize first (lex) so we can cleanly handle comments and scripts
        for typ, val in self.lex():
            if typ == 'text':
                self.add_text(val)
            elif typ == 'tag':
                self.add_tag(val)
            elif typ == 'script':
                self.add_script(val)
        return self.finish()

    def lex(self):
        """A simple lexer yielding ('text', text), ('tag', tagtext), and ('script', scripttext).

        Comments (<!-- ... -->) are ignored — lex will not yield any token
        for comment content so the parser creates no Text/Element for them.
        
        <script> tags are handled specially: content between <script> and </script>
        is yielded as ('script', content) regardless of any < or > characters inside.
        """
        i = 0
        s = self.body
        n = len(s)
        buf = []
        while i < n:
            c = s[i]
            if c == '<':
                # flush text buffer
                if buf:
                    yield ('text', ''.join(buf))
                    buf = []
                # detect comment
                if s.startswith('!--', i+1):
                    # find closing -->
                    end = s.find('-->', i+4)
                    if end == -1:
                        # unterminated comment — skip rest
                        return
                    i = end + 3
                    continue
                # detect <script> tag
                if s[i+1:i+7].lower() == 'script' and (i+7 >= n or s[i+7] in ' \t\n\r>'): 
                    # find the closing '>' of opening <script> tag
                    tag_end = s.find('>', i+1)
                    if tag_end == -1:
                        # malformed tag; treat rest as text
                        buf.append(s[i:])
                        break
                    tagtext = s[i+1:tag_end]
                    yield ('tag', tagtext)
                    i = tag_end + 1
                    
                    # now find the closing </script>
                    script_start = i
                    script_end = s.find('</script>', i)
                    if script_end == -1:
                        # no closing tag, treat rest as script
                        script_content = s[script_start:]
                        yield ('script', script_content)
                        return
                    else:
                        script_content = s[script_start:script_end]
                        yield ('script', script_content)
                        # yield closing </script> tag
                        yield ('tag', '/script')
                        i = script_end + len('</script>')
                    continue
                # otherwise find next '>'
                end = s.find('>', i+1)
                if end == -1:
                    # malformed tag; treat rest as text
                    buf.append(s[i:])
                    break
                tagtext = s[i+1:end]
                yield ('tag', tagtext)
                i = end + 1
            else:
                buf.append(c)
                i += 1
        if buf:
            yield ('text', ''.join(buf))

    def get_attributes(self, text):
        parts = text.split()
        tag = parts[0].casefold()
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                attributes[attrpair.casefold()] = ""
        return tag, attributes

    def add_text(self, text):
        if text.isspace():
            return
        # Ensure implicit tags (html/head/body) are present
        self.implicit_tags(None)
        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)
    
    def add_script(self, script_content):
        """Handle JavaScript content from <script> tags.
        
        Currently stores the script content but does not execute it.
        This function is a placeholder for future JavaScript execution.
        
        Args:
            script_content: The JavaScript code as a string
        """
        # TODO: Implement JavaScript execution
        # For now, we simply ignore the script content
        # Future implementation could:
        # 1. Parse JavaScript using a JS parser
        # 2. Execute JavaScript in a sandboxed environment
        # 3. Handle DOM manipulation from JavaScript
        pass

    SELF_CLOSING_TAGS = [
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ]

    HEAD_TAGS = [
        "base", "basefont", "bgsound", "noscript",
        "link", "meta", "title", "style", "script",
    ]
    # Tags that should implicitly close when a sibling of the same tag opens
    REOPEN_CLOSE_TAGS = ["p", "li", "div"]

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"): 
            return
        # Insert any implicit ancestor/structure tags before handling this tag
        self.implicit_tags(tag)
        # If a start-tag of a reopen-close family appears while the same
        # tag is already the immediate open element, implicitly close the
        # previous one (treat as sibling). Example: <p>one<p>two -> close
        # first <p> before opening second.
        if not tag.startswith("/") and tag in self.REOPEN_CLOSE_TAGS:
            if self.unfinished and self.unfinished[-1].tag == tag:
                # close previous
                self.add_tag(f"/{tag}")
        if tag.startswith("/"):
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self):
        # Ensure implicit root tags exist if nothing was opened
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    def implicit_tags(self, tag):
        """Auto-insert implicit structural tags like html/head/body.

        Simple rules:
        - If nothing is open and next tag isn't 'html', open 'html'.
        - If only 'html' is open and next tag isn't 'head','body','/html',
          open 'head' if next tag is a head tag, otherwise open 'body'.
        - If 'html'->'head' is open and the next tag doesn't belong to head,
          close 'head'.
        """
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS:
                self.add_tag("/head")
            else:
                break


class Layout:
    def __init__(self, tree):
        self.display_list = []

        self.cursor_x = HSTEP
        self.cursor_y = VSETEP
        self.weight = "normal"
        self.style = "roman"
        self.size = 12

        self.line = []
        self.recurse(tree)
        self.flush()

    def recurse(self, tree):
        if isinstance(tree, Text):
            for word in tree.text.split():
                self.word(word)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "small":
            self.size -= 2
        elif tag == "big":
            self.size += 4
        elif tag == "br":
            self.flush()

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 2
        elif tag == "big":
            self.size -= 4
        elif tag == "p":
            self.flush()
            self.cursor_y += VSETEP

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        w = font.measure(word)
        if self.cursor_x + w > WIDTH - HSTEP:
            self.flush()
        self.line.append((self.cursor_x, word, font))
        # add a space width
        self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for x, word, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])
        # Slightly tighter line spacing than original 1.25
        baseline = self.cursor_y + 1.10 * max_ascent
        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))
        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + 1.10 * max_descent
        self.cursor_x = HSTEP
        self.line = []


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.window.title("Simple Browser")
        self.window.geometry(f"{WIDTH}x{HEIGHT}+{X_POS}+{Y_POS}")
        self.window.resizable(True, True)

        # Simple Canvas (no scrollbar)
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT, bg="white")
        self.canvas.pack(fill=tkinter.BOTH, expand=True)

        self.window.bind('<Control-q>', lambda e: self.window.quit())

        self.display_list = []

        self.draw_init_content()

    # Scrollbar and scrolling removed: static rendering only

    def draw_init_content(self):
        canvas_width = self.canvas.winfo_width() or WIDTH
        canvas_height = self.canvas.winfo_height() or HEIGHT
        for i in range(0, canvas_width, HSTEP):
            self.canvas.create_line(i, 0, i, canvas_height, fill="lightgray")
        for j in range(0, canvas_height, VSETEP):
            self.canvas.create_line(0, j, canvas_width, j, fill="lightgray")
        self.canvas.create_text(canvas_width//2, canvas_height//2, text="Welcome to the Simple Browser!", font=("Arial", 24), fill="black")

    def load(self, url: URL):
        try:
            body = url.request()
            # parse HTML and create layout/display list
            self.nodes = HTMLParser(body).parse()
            self.display_list = Layout(self.nodes).display_list
        except Exception as e:
            # show error in GUI
            msg = f"❌ 오류 발생: {e}"
            self.display_list = [(HSTEP, VSETEP, msg, get_font(12, 'normal', 'roman'))]
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        canvas_height = self.canvas.winfo_height() or HEIGHT
        canvas_width = self.canvas.winfo_width() or WIDTH
        for x, y, word, font in self.display_list:
            # static rendering: place words at their computed y coordinate
            self.canvas.create_text(x, y, text=word, font=font, anchor="nw")

if __name__ == "__main__":
    import sys
    # Allow a quick parser test: python Browser.py --test
    def test_parser_comments():
        samples = [
            ("Hello <!-- skip this -->World", "Hello World"),
            ("<meta charset=\"utf-8\"><p>Para<!--x-->Two</p>", "Para Two"),
            ("<!-- full comment --><b>Bold</b>", "Bold"),
        ]
        for src, expect in samples:
            p = HTMLParser(src)
            tree = p.parse()
            # collect text nodes
            def collect(node):
                out = []
                if isinstance(node, Text):
                    out.append(' '.join(node.text.split()))
                for ch in getattr(node, 'children', []):
                    out.append(collect(ch))
                return ' '.join([x for x in out if x])
            result = collect(tree)
            print('SRC:', src)
            print('PARSED TEXT:', result)
            print('EXPECTED (approx):', expect)
            print('---')

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_parser_comments()
        sys.exit(0)
    b = Browser()
    if len(sys.argv) > 1:
        b.load(URL(sys.argv[1]))
    b.window.mainloop()
