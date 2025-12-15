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
        text = ""
        in_tag = False
        for c in self.body:
            if c == "<":
                in_tag = True
                if text:
                    self.add_text(text)
                text = ""
            elif c == ">":
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c
        if not in_tag and text:
            self.add_text(text)
        return self.finish()

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
        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    SELF_CLOSING_TAGS = [
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ]

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"): 
            return
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
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()


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
    b = Browser()
    if len(sys.argv) > 1:
        b.load(URL(sys.argv[1]))
    b.window.mainloop()
