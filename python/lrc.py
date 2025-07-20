# -*- coding: utf-8 -*-
#
# Copyright (C) 2011  Tiger Soldier
#
# This file is part of OSD Lyrics.
#
# OSD Lyrics is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OSD Lyrics is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OSD Lyrics.  If not, see <https://www.gnu.org/licenses/>.
#

import re
import dbus.types

__all__ = (
    'AttrToken',
    'TimeToken',
    'StringToken',
    'tokenize',
    'parse_lrc',
)

LINE_PATTERN = re.compile(r'(\[[^\[]*?\])')
TIMESTAMP_PATTERN = re.compile(r'^\[(\d+(:\d+){0,2}(\.\d+)?)\]$')
ATTR_PATTERN = re.compile(r'^\[([\w\d]+):(.*)\]$')
ENHANCED_WORD_PATTERN = re.compile(r'<(\d+(:\d+){0,2}(\.\d+)?)>([^<]*)')

class AttrToken:
    """
    Represents tags with the form of ``[key:value]``
    """

    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return '{%s: %s}' % (self.key, self.value)

class StringToken(object):
    """
    Represents a line of lyric text, with optional word-level timing
    """

    def __init__(self, text, word_timings=None):
        self.text = text
        self.word_timings = word_timings or []  # List of (timestamp_ms, word) tuples

    def __repr__(self):
        return '"%s"\n' % self.text

class TimeToken(object):
    """
    Represents tags with the form of ``[h:m:s.ms]``

    The time attribute is the timestamp in milliseconds
    """

    def __init__(self, string):
        parts = string.split(':')
        parts.reverse()
        factor = 1000
        ms = int(float(parts[0]) * factor)
        for s in parts[1:]:
            factor = factor * 60
            ms = ms + factor * int(s)
        self.time = ms

    def __repr__(self):
        return '[%s]' % self.time

def parse_enhanced_words(text_part):
    """Parse enhanced LRC word timings from text"""
    word_timings = []
    words = []
    
    for match in ENHANCED_WORD_PATTERN.finditer(text_part):
        timestamp_str = match.group(1)
        word = match.group(4).strip()
        
        # Convert timestamp to milliseconds (reuse TimeToken logic)
        parts = timestamp_str.split(':')
        parts.reverse()
        factor = 1000
        ms = int(float(parts[0]) * factor)
        for s in parts[1:]:
            factor = factor * 60
            ms = ms + factor * int(s)
        
        if word:  # Only add non-empty words
            word_timings.append((ms, word))
            words.append(word)
    
    return word_timings, ' '.join(words)

def tokenize(content):
    """ Split the content of LRC file into tokens

    Returns a list of tokens

    Arguments:
    - `content`: UTF8 string, the content to be tokenized
    """
    def parse_tag(tag):
        m = TIMESTAMP_PATTERN.match(tag)
        if m:
            return TimeToken(m.group(1))
        m = ATTR_PATTERN.match(tag)
        if m:
            return AttrToken(m.group(1), m.group(2))
        return None

    def tokenize_line(line):
        pos = 0
        tokens = []
        while pos < len(line) and line[pos] == '[':
            has_tag = False
            m = LINE_PATTERN.search(line, pos)
            if m and m.start() == pos:
                tag = m.group()
                token = parse_tag(tag)
                if token:
                    tokens.append(token)
                    has_tag = True
                    pos = m.end()
            if not has_tag:
                break
        
        # Parse the remaining text part for enhanced word timings
        text_part = line[pos:]
        if '<' in text_part and '>' in text_part:
            # This is enhanced LRC with word-level timing
            word_timings, clean_text = parse_enhanced_words(text_part)
            tokens.append(StringToken(clean_text, word_timings))
        else:
            # Standard LRC text
            tokens.append(StringToken(text_part))
        
        return tokens

    lines = content.splitlines()
    tokens = []
    for line in lines:
        tokens.extend(tokenize_line(line))
    return tokens

def parse_lrc(content):
    """
    Parse an lrc file

    Arguments:
    - `content`: LRC file content encoded in UTF8

    Return values: attr, lyrics
    - `attr`: A dict represents attributes in LRC file
    - `lyrics`: A list of dict with 3 keys: id, timestamp, text, and word_timings.
      The list is sorted in ascending order by timestamp. Id increases from 0.
    """
    tokens = tokenize(content)
    attrs = {}
    lyrics = []
    timetags = []
    for token in tokens:
        if isinstance(token, AttrToken):
            attrs[token.key] = token.value
        elif isinstance(token, TimeToken):
            timetags.append(token.time)
        else:
            for timestamp in timetags:
                lyric_entry = {
                    'timestamp': dbus.types.Int64(timestamp),
                    'text': token.text
                }
                # Add word timings if available (enhanced LRC)
                if token.word_timings:
                    lyric_entry['word_timings'] = token.word_timings
                
                lyrics.append(lyric_entry)
            timetags = []
    
    lyrics.sort(key=lambda a: a['timestamp'])
    i = 0
    for lyric in lyrics:
        lyric['id'] = dbus.types.UInt32(i)
        i = i + 1
    return attrs, lyrics

def test():
    TEST_CASE1 = \
        """[ti:焔の扉~hearty edition][ar:FictionJunction YUUKA]
[al:焔の扉]
[02:45.59]その日まで
[52.78]
[03:48][35]焔の扉へ
[1:03:56.66][03:14.77]
おわり
"""

    # Test case for enhanced LRC
    TEST_CASE2 = \
        """[ti:Test Song][ar:Test Artist]
[00:03.80]<00:03.80>Like <00:04.15>an <00:04.34>unraveling <00:05.23>thread<00:06.03>
[00:10.00]Regular lyrics without word timing
"""

    def test_tokenizer():
        print("=== Testing Standard LRC ===")
        tokens = tokenize(TEST_CASE1)
        for token in tokens:
            print(token)
        
        print("\n=== Testing Enhanced LRC ===")
        tokens = tokenize(TEST_CASE2)
        for token in tokens:
            print(token)
            if isinstance(token, StringToken) and token.word_timings:
                print("  Word timings:", token.word_timings)

    def test_parser():
        print("\n=== Testing Standard LRC Parser ===")
        attr, lyrics = parse_lrc(TEST_CASE1)
        print("Attributes:", attr)
        for line in lyrics:
            print('%s: %s -> %s' % (line['id'], line['timestamp'], line['text']))
        
        print("\n=== Testing Enhanced LRC Parser ===")
        attr, lyrics = parse_lrc(TEST_CASE2)
        print("Attributes:", attr)
        for line in lyrics:
            print('%s: %s -> %s' % (line['id'], line['timestamp'], line['text']))
            if 'word_timings' in line:
                print('  Word timings:', line['word_timings'])

    test_tokenizer()
    test_parser()

if __name__ == '__main__':
    test()

