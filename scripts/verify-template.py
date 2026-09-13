#!/usr/bin/env python3
"""Compile LuCI .htm templates with luac before the router has to.

luci.template.parser scans a template for "<%" ... "%>" and nothing else, so a
character where it expects a tag type is only noticed when the page is
requested: "<%--" parses as the whitespace-stripping "<%-" followed by a bare
"-", and the error surfaces as a 500 on a live router. Rebuild the Lua that
parser would hand to loadstring so luac can reject it here instead.

Mirrors modules/luci-lua-runtime/src/template_parser.c and template_utils.c of
the luci revision pinned in sources.env. Each chunk emits one output line per
template line, so a luac line number is the template line number.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

# luac abbreviates a long chunk name with "...", so its path cannot be matched
# and replaced; take the line number and phrase the message from the template.
LUAC_ERROR = re.compile(r':(\d+): (.*)', re.S)


def template_source(path):
    text = path.read_bytes().decode('utf-8')  # Raw bytes: read_text folds CRLF away.
    out = []
    pos = 0
    while True:
        start = text.find('<%', pos)
        if start < 0:
            _chunk_text(out, text[pos:], at_eof=True)
            break
        _chunk_text(out, text[pos:start], at_eof=False)
        end = text.find('%>', start + 2)
        if end < 0:
            # template_reader hands back a lone escape byte, which luac rejects.
            out.append('\\033')
            break
        _chunk_code(out, text[start + 2:end])
        pos = end + 2
    return ''.join(out)


def _chunk_text(out, body, at_eof):
    if body == '':
        # An empty chunk becomes a space, except at EOF where it is dropped.
        if not at_eof:
            out.append(' ')
        return
    out.append('write("%s")%s' % (_escape(body), _newlines(body)))


def _chunk_code(out, body):
    if body.startswith('-'):  # strip whitespace before the tag
        body = body[1:].lstrip(' \t')
    if body.endswith('-'):  # strip whitespace after the tag
        body = body[:-1].rstrip(' \t')
    if body == '':
        out.append(' ')
    elif body[0] == '#':  # comment
        out.append(' ' + _newlines(body))
    elif body[0] == '+':  # include
        out.append('include("%s")%s' % (_escape(body[1:]), _newlines(body)))
    elif body[0] in ':_':  # translate, raw translate
        out.append('write("%s")%s' % (_escape(body[1:]), _newlines(body)))
    elif body[0] == '=':  # expression, body keeps its own newlines
        out.append('write(tostring(%s or ""))' % body[1:])
    else:  # code, and the trailing space is what the parser appends
        out.append(body + ' ')


def _escape(body):
    # luastr_escape with escape_xml=0. Newlines become a two-character escape
    # inside the literal, so the call above stays on one output line.
    return body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def _newlines(body):
    return '\n' * body.count('\n')


def main(paths):
    failed = False
    for name in paths:
        path = Path(name)
        with tempfile.NamedTemporaryFile('w', suffix='.lua', encoding='utf-8',
                                         delete=False) as handle:
            handle.write(template_source(path))
            compiled = Path(handle.name)
        try:
            result = subprocess.run(['luac', '-p', str(compiled)],
                                    capture_output=True, text=True)
        finally:
            compiled.unlink()
        if result.returncode == 0:
            print('%s: compiles' % name)
            continue
        error = result.stderr.strip()
        match = LUAC_ERROR.search(error)
        if match:
            print('%s:%s: %s' % (name, match.group(1), match.group(2)), file=sys.stderr)
        else:
            print('%s: %s' % (name, error), file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: verify-template.py <template.htm> [more.htm ...]')
    sys.exit(main(sys.argv[1:]))
