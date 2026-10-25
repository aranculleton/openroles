"""The text of a posting that no reader sees, found so that it can be left out.

A page shows nothing of a comment, of a <script> or <style> block, or of what a <noscript> or
<template> holds, and nothing of an element that is hidden (the `hidden` attribute,
aria-hidden="true", an inline display:none or visibility:hidden) or of what is inside it. A
posting can still carry text there, and read as plain text it is as good as written on the
page. `drop_hidden` leaves it out and leaves the rest of the text exactly as it was, for the
tags to be taken off afterwards.

The text is written by someone who may want a program to read what a person does not, so where
a hidden element ends is decided as a browser decides it: with the end tags a page leaves out,
without the end tags a browser ignores, and with whatever a browser leaves open to the end of
the text (a comment, a script, a hidden element, a tag whose quote never closes) hiding the
rest of it. These are the HTML standard's rules, cut down to what decides where an element
ends: how an end tag finds its element (`_Reader.end_tag`), what a start tag ends
(`_Reader.read`), and the formatting elements a browser opens again. Where the markup cannot
be followed, the rest is hidden and not shown: a text read wrongly loses some of what a reader
sees, and one read the other way shows what a reader does not.

Not covered: text hidden by a style sheet, a class, a colour, a size or a position, which
cannot be told without drawing the page, and markup that a browser repairs by moving it (a
table written out of order), which is read in the order it is written.
"""
from __future__ import annotations

import re

# A text with none of these in it has nothing to drop, and is not read at all.
_CAN_HIDE = ("<!--", "<script", "<noscript", "<template", "hidden", "style")
# A comment, or a tag with its name, its attributes up to a quote or a ">", and what stopped them.
_TOKEN = re.compile(r"""<(?:(!--)|(/?)([A-Za-z][^\s/>]*)([^>"']*)([>"']?))""")
_COMMENT_END = re.compile(r"--!?>")
_VALUE = re.compile(r"=\s*([\"'])")            # a quote that opens an attribute's value
_ATTR = re.compile(r"""([^\s/>=][^\s/>=]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]*)))?""")
_MAY_HIDE = re.compile(r"hidden|none|\\", re.I)   # what any attribute that hides has in it somewhere
# The end of a script or a style block: only the exact name, whatever the case (so not "ſcript").
_RAW = {name: re.compile(f"</{name}(?=[\\s/>])", re.I | re.A) for name in ("script", "style")}
_NEVER_SHOWN = frozenset(("noscript", "template"))
_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

# Elements that have no end tag and hold nothing.
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
# Elements a browser opens again, attributes and all, where the text goes on after they were
# closed by anything but their own end tag: `<p><b hidden>one</p><p>two` hides "two" too.
_FORMATTING = frozenset("a b big code em font i nobr s small strike strong tt u".split())
# Elements an end tag for an inline element does not reach across (it is ignored), and one for a
# formatting element does not close (it is taken off the stack, and they stay open).
_SPECIAL = frozenset((
    "address applet article aside blockquote body button caption center colgroup dd details dir div dl dt "
    "fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup html iframe li listing "
    "main marquee menu nav noembed noframes noscript object ol p plaintext pre search section select "
    "summary table tbody td template textarea tfoot th thead title tr ul xmp").split())
# Elements an end tag for a block does not reach across (it is ignored).
_WALLS = frozenset("applet caption html marquee object table td template th".split())
# The end tags that close what is inside their element, if no wall is in the way.
_BLOCK_END = frozenset((
    "address applet article aside blockquote button center dd details dialog dir div dl dt fieldset figcaption "
    "figure footer form h1 h2 h3 h4 h5 h6 header hgroup li listing main marquee menu nav object ol p pre search "
    "section summary ul").split())
# The end tags of a table's parts, which reach through a cell or a row, and stop at a table in it.
_TABLE_END = frozenset("caption colgroup table tbody td tfoot th thead tr".split())
_TABLE_WALLS = ("table", "template", "html")
# Parts of a table, which a browser ignores the start of anywhere but in a table.
_TABLE_PART = frozenset("caption col colgroup tbody td tfoot th thead tr".split())
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
# The start of any of these ends an open <p>.
_ENDS_P = frozenset((
    "address article aside blockquote center details dialog dir div dl fieldset figcaption figure footer "
    "form h1 h2 h3 h4 h5 h6 header hgroup hr li main menu nav ol p pre section summary table ul").split())
# The special elements the start of an <li> does not end an earlier <li> across.
_NOT_ACROSS_LI = ("address", "div", "p")

_CSS_COMMENT = re.compile(r"/\*.*?(?:\*/|\Z)", re.S)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})\s?|(.))", re.S)


def _css_char(m) -> str:
    if m.group(2):
        return m.group(2)
    code = int(m.group(1), 16)
    return chr(code) if 0 < code <= 0x10FFFF else "\ufffd"


def _css_hides(style: str) -> bool:
    """Whether an inline style says display:none or visibility:hidden, in any spacing or case,
    with or without !important, and however a comment or an escape is put in it. A property
    given twice counts if either says so."""
    for declaration in _CSS_ESCAPE.sub(_css_char, _CSS_COMMENT.sub("", style)).split(";"):
        name, _, value = declaration.partition(":")
        value = value.strip().lower()
        if value.endswith("important") and value[:-9].rstrip().endswith("!"):
            value = value[:-9].rstrip()[:-1].rstrip()
        if (name.strip().lower(), value) in (("display", "none"), ("visibility", "hidden")):
            return True
    return False


def _hides(attrs: str) -> bool:
    """Whether a tag's attributes hide its element: `hidden` (with a value or none),
    aria-hidden="true", or an inline style that hides. Read as a browser reads them: a word
    inside another attribute's value ("hidden" in a class or a title) hides nothing, and the
    first of an attribute given twice is the one that counts."""
    seen = set()
    for m in _ATTR.finditer(attrs):
        name = m.group(1).lower()
        if name in seen:
            continue
        seen.add(name)
        value = next((g for g in m.group(2, 3, 4) if g is not None), "")
        if (name == "hidden" or (name == "aria-hidden" and value.strip().lower() == "true")
                or (name == "style" and _css_hides(value))):
            return True
    return False


def _tag_end(s: str, i: int) -> int:
    """Where the tag whose name ends at `i` ends: just past its ">", with a quoted attribute
    value read as one piece, so a ">" inside it does not end the tag. -1 when no ">" follows,
    and -2 when a quote that opens a value is never closed, which a browser reads as the tag
    running to the end of the text."""
    gt = s.find(">", i)
    while True:
        quote = _VALUE.search(s, i, gt if gt >= 0 else len(s))
        if quote is None:
            return gt + 1 if gt >= 0 else -1
        close = s.find(quote.group(1), quote.end())
        if close < 0:
            return -2
        i = close + 1
        if 0 <= gt < i:
            gt = s.find(">", i)


class _Reader:
    """The open elements of some HTML as its tags are read one by one, enough of them to know
    where each hidden element ends, and the stretches of the text that no reader sees.

    `open` holds the open elements' names, innermost last; every other list holds positions
    in it, in order, so that its last item is the innermost of its kind and is found in one
    step, however deep the markup goes."""

    def __init__(self, text: str):
        self.text = text
        self.kept: list = []            # the pieces of `text` that stay, in order
        self.upto = 0                   # text[self.upto:] is not in `kept` yet
        self.open: list = []
        self.where: dict = {}           # a name -> the positions of its open elements
        self.special: list = []         # the special elements,
        self.not_across_li: list = []   # those an <li> does not end an earlier one across,
        self.wall: list = []            # the walls,
        self.table_wall: list = []      # the tables and the like,
        self.opens_again: list = []     # and the hidden formatting elements
        self.hidden = -1                # the position of the outermost hidden element, if any
        self.hidden_at = 0              # and where in `text` it starts
        self.sealed = False             # whether the rest of the text is hidden, whatever follows

    def drop(self, start: int, stop: int) -> None:
        """Leave out text[start:stop]: a space stands in, where a word could be cut in two."""
        self.kept += (self.text[self.upto:start], " ")
        self.upto = stop

    def push(self, name: str, start: int, hides: bool) -> None:
        k = len(self.open)
        self.open.append(name)
        self.where.setdefault(name, []).append(k)
        if name in _SPECIAL:
            self.special.append(k)
            if name not in _NOT_ACROSS_LI:
                self.not_across_li.append(k)
        if name in _WALLS:
            self.wall.append(k)
        if name in _TABLE_WALLS:
            self.table_wall.append(k)
        if hides and name in _FORMATTING:
            self.opens_again.append(k)
        if hides and self.hidden < 0:
            self.hidden, self.hidden_at = k, start

    def close(self, k: int, resume: int) -> None:
        """End the open elements from the k-th on. If the hidden one is among them, what it
        held is dropped, and the text is kept again from `resume`: unless a hidden formatting
        element is ended from outside, which a browser opens again where the text goes on."""
        if self.opens_again and self.opens_again[-1] > k:
            self.sealed = True
            return
        while len(self.open) > k:
            top = len(self.open) - 1
            self.where[self.open.pop()].pop()
            for marks in (self.special, self.not_across_li, self.wall, self.table_wall, self.opens_again):
                if marks and marks[-1] == top:
                    marks.pop()
        if self.hidden >= k:
            self.drop(self.hidden_at, resume)
            self.hidden = -1

    def end_nearest(self, name: str, not_across: list, resume: int) -> None:
        """End the nearest open `name` and what is inside it, as the start of a block ends a
        <p> and the next <li> ends an <li>: not across a wall, nor across one of `not_across`."""
        at = self.where.get(name)
        if at and not (self.wall and self.wall[-1] > at[-1]) and not (not_across and not_across[-1] > at[-1]):
            self.close(at[-1], resume)

    def end_tag(self, name: str, resume: int) -> None:
        """What a browser does with an end tag, which depends on the element: the end tag of a
        block or a table's part reaches through what is open inside its element, unless a wall
        is in the way (and the tag is ignored), the end tag of an inline element is ignored if
        a special element is open inside it, and the end tag of a formatting element then takes
        only that element off the stack. An end tag that closes nothing is ignored."""
        at = self.where.get(name)
        if not at:
            return
        k = at[-1]
        if name in _TABLE_END:
            if not (self.table_wall and self.table_wall[-1] > k):
                self.close(k, resume)
        elif name in _BLOCK_END:
            list_between = name == "li" and any(self.where.get(w) and self.where[w][-1] > k for w in ("ul", "ol"))
            if not (self.wall and self.wall[-1] > k) and not list_between:
                self.close(k, resume)
        elif not (self.special and self.special[-1] > k):
            self.close(k, resume)
        elif name in _FORMATTING:
            if k == self.hidden:
                self.sealed = True      # what is open inside it may be hidden, and is not followed
            else:
                self.where[name].pop()
                self.open[k] = ""       # taken off the stack, though the elements above it stay
                self.where.setdefault("", []).append(k)

    def read(self) -> str:
        s, n, pos = self.text, len(self.text), 0
        rest = None                     # where the rest of the text is lost to a tag whose quote never closes
        while not self.sealed:
            m = _TOKEN.search(s, pos)
            if m is None:
                break
            i = m.start()
            if m.group(1):              # a comment
                found = _COMMENT_END.search(s, i + 2)
                pos = found.end() if found else n
                if self.hidden < 0:
                    self.drop(i, pos)
                continue
            closing, name, attrs, ender = m.group(2, 3, 4, 5)
            name = name.translate(_LOWER)
            if ender == ">":
                end = m.end()
            else:
                end = _tag_end(s, m.end(3))
                if end < 0:
                    rest = i if end == -2 else None
                    break
                attrs = s[m.start(4):end - 1]
            pos = end
            if closing:
                self.end_tag(name, end)
            elif name in _RAW:          # its text is not read as tags
                found = _RAW[name].search(s, end)
                pos = _tag_end(s, found.end()) if found else -1
                pos = pos if pos > 0 else n
                if self.hidden < 0:
                    self.drop(i, pos)
            else:
                if name in _ENDS_P:
                    self.end_nearest("p", [], i)
                if name == "li":
                    self.end_nearest("li", self.not_across_li, i)
                if name in _HEADINGS and self.open and self.open[-1] in _HEADINGS:
                    self.close(len(self.open) - 1, i)
                if name == "a":
                    self.end_tag("a", i)
                if name in _TABLE_PART and not self.where.get("table"):
                    continue
                if name not in _VOID and not self.sealed:
                    self.push(name, i, name in _NEVER_SHOWN
                              or (_MAY_HIDE.search(attrs) is not None and _hides(attrs)))
        if self.hidden >= 0:
            rest = self.hidden_at
        if rest is not None:
            self.drop(rest, n)
        if not self.kept:
            return self.text
        return "".join(self.kept) + s[self.upto:]


def drop_hidden(s: str) -> str:
    """`s` without what no reader sees, and otherwise as it was: see the module's docstring.
    A text with nothing in it that could hide anything is returned as it is, unread."""
    if "<" not in s:
        return s
    low = s.lower()
    if not any(word in low for word in _CAN_HIDE):
        return s
    return _Reader(s).read()
