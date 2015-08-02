#!/usr/bin/env python3
# coding: utf-8
import re
import sys
import fnmatch

if sys.version_info[0] < 3:
    print("This script requires Python version 3.x")
    sys.exit(1)

__cleanupRegex = re.compile(r'<(a|span|div)\s+([a-z]+=("[^"]+"|\'[^\']+\')\s*)+>(.+?)</(a|span|div)>\s*')
__cleanupDetectRegex = re.compile(r"<(a|span|div)")

def cleanupTranslatedString(s):
    """
    Minor but fast cleanup of the msgstr in order to avoid hits in
    invisible parts like HTML.
    """
    if not __cleanupDetectRegex.search(s):
        return s
    return __cleanupRegex.sub(r"\1", s)

_extractImgRegex = re.compile(r"(https?://ka-perseus-graphie\.s3\.amazonaws\.com/[0-9a-f]{40,40}\.(png|svg))")

class Rule(object):
    """
    A baseclass for rules.
    Remember to implement __call__(self, msgstr, msgid),
    which must return the hit or None if no hit is found.
    """
    def __init__(self, name):
        self.name = name
        # If you need to save some state, you can do it here.
        # This MUST NOT be filled by subclasses.
        self.custom_info = {}
    def get_machine_name(self):
        """Get a machine-readable name from a rule name"""
        name = self.name.lower().replace("'", "").replace("\"", "")
        name = name.replace("(","").replace(")","").replace("{","")
        name = name.replace("}","").replace("\\", "").replace(",","")
        name = name.replace("*","").replace("/", "-").replace("%", "")
        name = re.sub(r"\s+", "-", name)
        name = re.sub(r"-+", "-", name)
        name = re.sub(r"^-", "", name)
        return name
    def apply_to_po(self, po, filename="[unknown file]", ignore_untranslated=True):
        """
        Apply to a dictionary of parsed PO files.
        Yields tuples entry, hit, filename
        """
        for entry in po:
            # Ignore strings which are the same orig/msgid
            # This accounts for the fact that we don't know how
            if ignore_untranslated and entry.msgstr == entry.msgid:
                continue
            # Translated string cleanup
            msgstr = cleanupTranslatedString(entry.msgstr)
            # Apply the rule
            hit = self(msgstr, entry.msgid, filename=filename)
            if hit:
                #Find images in both original and new string
                origImages = [h[0] for h in _extractImgRegex.findall(entry.msgid)]
                translatedImages = [h[0] for h in _extractImgRegex.findall(entry.msgstr)]
                yield (entry, hit, filename, origImages, translatedImages)

class SimpleRegexRule(Rule):
    """
    A simple rule type that matches a regex to the translated string.
    Partial matches (via re.search) are considered hits.
    """
    def __init__(self, name, regex, flags=re.UNICODE):
        super().__init__(name)
        self.re = re.compile(regex, flags)
        self.regex_str = regex
    def __call__(self, msgstr, msgid, filename=None):
        hit = self.re.search(msgstr)
        if hit:
            return hit.group(0)
        return None

class SimpleSubstringRule(Rule):
    """
    A simple rule type that hits when a given substring is found in the msgstr.
    """
    def __init__(self, name, substr, case_insensitive=False):
        super().__init__(name)
        self.substr = substr
        self.ci = case_insensitive
        if self.ci:
            self.substr = self.substr.lower()
    def __call__(self, msgstr, msgid, filename=None):
        # Case-insensitive preprocessing
        if self.ci:
            msgstr = msgstr.lower()
        if msgstr.find(self.substr) != -1:
            return self.substr
        return None

class TranslationConstraintRule(Rule):
    """
    Enforces that a certain regex in the original string will
    be translated a certain way

    i.e. the rule hits when regexOrig has >= 1 match in the msgid
    while regexTranslated has 0 machte
    """
    def __init__(self, name, regexOrig, regexTranslated, flags=re.UNICODE):
        super().__init__(name)
        self.reOrig = re.compile(regexOrig, flags)
        self.reTranslated = re.compile(regexTranslated, flags)
        self.regex_orig_str = regexOrig
        self.regex_translated_str = regexTranslated
    def __call__(self, msgstr, msgid, filename=None):
        if self.reOrig.search(msgid) and not self.reTranslated.search(msgstr):
            return "[failed constraint]"
        return None

class NegativeTranslationConstraintRule(Rule):
    """
    Enforces that a certain regex in the original string will
    NOT be translated a certain way,

    i.e. the rule hits when regexOrig has >= 1 match in the msgid
    while regexTranslated has a match.
    """
    def __init__(self, name, regexOrig, regexTranslated, flags=re.UNICODE):
        super().__init__(name)
        self.reOrig = re.compile(regexOrig, flags)
        self.reTranslated = re.compile(regexTranslated, flags)
        self.regex_orig_str = regexOrig
        self.regex_translated_str = regexTranslated
    def __call__(self, msgstr, msgid, filename=None):
        if self.reOrig.search(msgid) and self.reTranslated.search(msgstr):
            return "[failed constraint]"
        return None

class BooleanNotRule(Rule):
    """Apply a boolean NOT to a child rule"""
    def __init__(self, child):
        super().__init__(child.name)
        self.child = child
    def __call__(self, msgstr, msgid, filename=None):
        if self.child(msgstr, msgid):
            return None
        else:
            return "[failed boolean NOT]"

class BooleanAndRule(Rule):
    """Apply a boolean AND to a child rule. Returns the hit of the first child."""
    def __init__(self, name, childA, childB):
        super().__init__(name)
        self.childA = childA
        self.childB = childB
    def __call__(self, msgstr, msgid, filename=None):
        hitA = self.childA(msgstr, msgid)
        if not hitA: return None # Shortcut-return
        hitB = self.childB(msgstr, msgid)
        if hitB: return hitA
        return None

class BooleanOrRule(Rule):
    """Apply a boolean AND to a child rule. Returns the hit of the first child."""
    def __init__(self, name, childA, childB):
        super().__init__(name)
        self.childA = childA
        self.childB = childB
    def __call__(self, msgstr, msgid, filename=None):
        hitA = self.childA(msgstr, msgid)
        if hitA: return hitA # Shortcut-return
        return self.childB(msgstr, msgid)


def SimpleGlobRule(name, glob):
    """Rule wrapper that translates a glob-ish rule to a regex rule"""
    return SimpleRegexRule(name, fnmatch.translate(glob))

class ExactCopyRule(Rule):
    """
    Requires that when a list of regex matches is present in the orignal text,
    the exact same list of matches is also present in the same order.

    This can be used, for example, to ensure GUI elements, numbers or URLs are the same in
    both the translated text and the original.
    """
    def __init__(self, name, regex, aliases={}):
        super().__init__(name)
        self.regex = re.compile(regex)
        self.aliases = aliases
    def __call__(self, msgstr, msgid, filename=None):
        origMatches = self.regex.findall(msgid)
        translatedMatches = self.regex.findall(msgstr)
        # Apply aliases
        origMatches = [self.aliases[x] or x for x in origMatches]
        translatedMatches = [self.aliases[x] or x for x in translatedMatches]
        # Find index of first mismatch
        try:
            idx = next(idx for idx, (x, y) in
                       enumerate(zip(origMatches, translatedMatches)) if x != y)
            return "[First expression mismatch at index %d]" % (idx + 1)
        except StopIteration:  # No mismatch
            return None

class IgnoreByFilenameRegexWrapper(Rule):
    """
    Ignore a rule (i.e. force zero hits) for a set of filenames defined by a regex.

    If you want to ignore a rule for all filenames starting with "learn.", you'd use:

    """
    def __init__(self, filenameRegex, child, invert=False):
        """
        Keyword arguments:
            invert: Set this to true to invert this regex, i.e. mismatches of the regex lead to a ignored entry
        """
        super().__init__(child.name)
        self.child = child
        self.invert = invert
        self.filenameRegex = re.compile(filenameRegex)
    def __call__(self, msgstr, msgid, filename=None):
        if bool(self.filenameRegex.match(filename)) != self.invert:
            return None
        return self.child(msgstr, msgid)

class IgnoreByFilenameListWrapper(Rule):
    """
    Ignore a rule (i.e. force zero hits) for a set of filenames defined by a list of exact hits.
    """
    def __init__(self, filenames, child):
        super().__init__(child.name)
        self.child = child
        self.filenames = frozenset(filenames)
    def __call__(self, msgstr, msgid, filename=None):
        if filename in self.filenames:
            return None
        return self.child(msgstr, msgid)

class IgnoreByMsgidRegexWrapper(Rule):
    """
    Ignore a rule if a regex search in the msgid returns a certain value.

    This can be useful to ignore special cases of translation which
    are distinguishable by the untranslated (english) text, e.g.
    "Green's theorem" as a special case of untranslated "green".

    Note that if a single regex hit is found, the entire string is ignore
    """
    def __init__(self, msgidRegex, child):
        super().__init__(child.name)
        self.child = child
        self.msgidRegex = re.compile(msgidRegex)
    def __call__(self, msgstr, msgid, filename=None):
        if self.msgidRegex.search(msgid):
            return None
        return self.child(msgstr, msgid)

def findRule(rules, name):
    "Find a rule by name"
    for rule in rules:
        if rule.name == name:
            return rule
    return None
