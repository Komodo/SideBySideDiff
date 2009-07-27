#!/usr/bin/env python

#!/usr/bin/env python

# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
# 
# The contents of this file are subject to the Mozilla Public License
# Version 1.1 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
# 
# Software distributed under the License is distributed on an "AS IS"
# basis, WITHOUT WARRANTY OF ANY KIND, either express or implied. See the
# License for the specific language governing rights and limitations
# under the License.
# 
# The Original Code is "side by side diff" code.
# 
# The Initial Developer of the Original Code is ActiveState Software Inc.
# Portions created by ActiveState Software Inc are Copyright (C) 2008-2009
# ActiveState Software Inc. All Rights Reserved.
# 
# Contributor(s):
#   Todd Whiteman @ ActiveState Software Inc
# 
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
# 
# ***** END LICENSE BLOCK *****


#
# Overview:
#   Helper class used by Komodo to generate a side-by-side diff.
#
#   * Note: a lot of this code is reproduced from the "reviewboard" project,
#           which uses a MIT license.
#

import os
import sys
import fnmatch
import logging
import re
import subprocess
import tempfile
from difflib import SequenceMatcher

try:
    from uriparse import URIToLocalPath
except ImportError:
    import warnings
    warnings.warn("Could not import uriparse", ImportWarning)
    def URIToLocalPath(uri):
        return uri.split("file://", 1)[1]

try:
    import pygments
    from pygments.lexers import get_lexer_for_filename
    # from pygments.lexers import guess_lexer_for_filename
    from pygments.formatters import HtmlFormatter
    _have_pygments = True
except ImportError:
    import warnings
    warnings.warn("Could not import pygments", ImportWarning)
    _have_pygments = False

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _
from django.utils.html import escape

from reviewboard.diffviewer.myersdiff import MyersDiffer
from reviewboard.diffviewer.smdiff import SMDiffer


DEFAULT_DIFF_COMPAT_VERSION = 1


class UserVisibleError(Exception):
    pass


class DiffCompatError(Exception):
    pass


class OpCode(object):
    def __init__(self, tag, i1, i2, j1, j2, i_offset=0, j_offset=0):
        self.tag = tag
        self.i1 = i1
        self.i2 = i2
        self.j1 = j1
        self.j2 = j2
        self.i_offset = i_offset
        self.j_offset = j_offset

def Differ(a, b, ignore_space=False,
           compat_version=DEFAULT_DIFF_COMPAT_VERSION):
    """
    Factory wrapper for returning a differ class based on the compat version
    and flags specified.
    """
    if compat_version == 0:
        return SMDiffer(a, b)
    elif compat_version == 1:
        return MyersDiffer(a, b, ignore_space)
    else:
        raise DiffCompatError(
            "Invalid diff compatibility version (%s) passed to Differ" %
                (compat_version))


def get_line_changed_regions(oldline, newline):
    if oldline is None or newline is None:
        return (None, None)

    # Use the SequenceMatcher directly. It seems to give us better results
    # for this. We should investigate steps to move to the new differ.
    differ = SequenceMatcher(None, oldline, newline)

    # This thresholds our results -- we don't want to show inter-line diffs if
    # most of the line has changed, unless those lines are very short.

    # FIXME: just a plain, linear threshold is pretty crummy here.  Short
    # changes in a short line get lost.  I haven't yet thought of a fancy
    # nonlinear test.
    if differ.quick_ratio() < 0.6:
        return (None, None)

    oldchanges = []
    newchanges = []
    back = (0, 0)

    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        if tag == "equal":
            if (i2 - i1 < 3) or (j2 - j1 < 3):
                back = (j2 - j1, i2 - i1)
            continue

        oldstart, oldend = i1 - back[0], i2
        newstart, newend = j1 - back[1], j2

        if oldchanges != [] and oldstart <= oldchanges[-1][1] < oldend:
            oldchanges[-1] = (oldchanges[-1][0], oldend)
        elif not oldline[oldstart:oldend].isspace():
            oldchanges.append((oldstart, oldend))

        if newchanges != [] and newstart <= newchanges[-1][1] < newend:
            newchanges[-1] = (newchanges[-1][0], newend)
        elif not newline[newstart:newend].isspace():
            newchanges.append((newstart, newend))

        back = (0, 0)

    return (oldchanges, newchanges)


def diff_line(vlinenum, oldlinenum, newlinenum, oldline, newline,
              oldmarkup, newmarkup):
    if oldline and newline and oldline != newline:
        oldregion, newregion = get_line_changed_regions(oldline, newline)
    else:
        oldregion = newregion = []

    return [vlinenum,
            oldlinenum or '', mark_safe(oldmarkup or ''), oldregion,
            newlinenum or '', mark_safe(newmarkup or ''), newregion]

def new_chunk(lines, numlines, tag, collapsable=False):
    return {
        'lines': lines,
        'numlines': numlines,
        'change': tag,
        'collapsable': collapsable,
    }

def add_ranged_chunks(chunks, lines, start, end, collapsable=False):
    numlines = end - start
    chunks.append(new_chunk(lines[start:end], end - start, 'equal',
                  collapsable))

class DifferFromFileDiffItem:
    def __init__(self, diffitem):
        self.diffitem = diffitem
        self._left_contents = None
        self._right_contents = None
        self._opcodes = None

    def _set_contents(self):
        opcodes = []
        self._left_contents = []
        self._right_contents = []
        for hunk in self.diffitem.hunks:
            left_lines = []
            right_lines = []
            last_tag = None
            for i in range(len(hunk.lines)):
                line = hunk.lines[i]
                if not line:
                    continue
                tag = line[0]
                if tag not in " +-":
                    continue
                line = line[1:]

                if last_tag != tag and last_tag is not None:
                    # State changed
                    tag_word = ""
                    if last_tag == " ":
                        tag_word = "equal"
                    elif tag == " " and last_tag == "+":
                        tag_word = left_lines and "replace" or "insert"
                    elif tag == " " and last_tag == "-":
                        tag_word = "delete"
                    if tag_word:
                        left_no = len(self._left_contents)
                        right_no = len(self._right_contents)
                        opcodes.append((tag_word,
                                        left_no, left_no+len(left_lines),
                                        right_no, right_no+len(right_lines)))
                        self._left_contents += left_lines
                        self._right_contents += right_lines
                        left_lines = []
                        right_lines = []
                last_tag = tag

                if tag == " ":
                    left_lines.append(line)
                    right_lines.append(line)
                elif tag == "-":
                    left_lines.append(line)
                elif tag == "+":
                    right_lines.append(line)

            left_no = len(self._left_contents)
            right_no = len(self._right_contents)
            if tag == " ":
                opcodes.append(("equal",
                               left_no, left_no+len(left_lines),
                               right_no, right_no+len(right_lines)))
            elif tag == "+":
                if left_lines:
                    opcodes.append(("replace",
                                   left_no, left_no+len(left_lines),
                                   right_no, right_no+len(right_lines)))
                else:
                    opcodes.append(("insert",
                                   left_no, left_no+len(left_lines),
                                   right_no, right_no+len(right_lines)))
            elif tag == "-":
                opcodes.append(("delete",
                               left_no, left_no+len(left_lines),
                               right_no, right_no+len(right_lines)))
            self._left_contents += left_lines
            self._right_contents += right_lines
        self._opcodes = opcodes

    @property
    def left_contents(self):
        if self._left_contents is None:
            self._set_contents()
        return self._left_contents

    @property
    def right_contents(self):
        if self._right_contents is None:
            self._set_contents()
        return self._right_contents

    def get_opcodes(self):
        for opcode in self._opcodes:
            yield opcode

def apply_pygments(data, filename):
    # XXX Guessing is preferable but really slow, especially on XML
    #     files.
    #if filename.endswith(".xml"):
    lexer = get_lexer_for_filename(filename, stripnl=False)
    #else:
    #    lexer = guess_lexer_for_filename(filename, data, stripnl=False)

    try:
        # This is only available in 0.7 and higher
        lexer.add_filter('codetagify')
    except AttributeError:
        pass

    return pygments.highlight(data, lexer, HtmlFormatter()).splitlines()


def get_chunks(filediff, interfilediff, force_interdiff,
               enable_syntax_highlighting):


    # There are three ways this function is called:
    #
    #     1) filediff, no interfilediff
    #        - Returns chunks for a single filediff. This is the usual way
    #          people look at diffs in the diff viewer.
    #
    #          In this mode, we get the original file based on the filediff
    #          and then patch it to get the resulting file.
    #
    #          This is also used for interdiffs where the source revision
    #          has no equivalent modified file but the interdiff revision
    #          does. It's no different than a standard diff.
    #
    #     2) filediff, interfilediff
    #        - Returns chunks showing the changes between a source filediff
    #          and the interdiff.
    #
    #          This is the typical mode used when showing the changes
    #          between two diffs. It requires that the file is included in
    #          both revisions of a diffset.
    #
    #     3) filediff, no interfilediff, force_interdiff
    #        - Returns chunks showing the changes between a source
    #          diff and an unmodified version of the diff.
    #
    #          This is used when the source revision in the diffset contains
    #          modifications to a file which have then been reverted in the
    #          interdiff revision. We don't actually have an interfilediff
    #          in this case, so we have to indicate that we are indeed in
    #          interdiff mode so that we can special-case this and not
    #          grab a patched file for the interdiff version.

    assert filediff

    ignore_space = False

    if filediff.file_on_disk:
        old = filediff.get_original_file()
        
        new = filediff.get_patched_file()
        if interfilediff:
            old = new
            interdiff_orig = get_original_file(interfilediff)
            new = get_patched_file(interdiff_orig, interfilediff)
        elif force_interdiff:
            # Basically, revert the change.
            temp = old
            old = new
            new = temp
    
        # Normalize the input so that if there isn't a trailing newline, we add
        # it.
        if old and old[-1] != '\n':
            old += '\n'
    
        if new and new[-1] != '\n':
            new += '\n'
    
        a = re.split(r"\r?\n", old or '')
        b = re.split(r"\r?\n", new or '')
    
        # Remove the trailing newline, now that we've split this. This will
        # prevent a duplicate line number at the end of the diff.
        del(a[-1])
        del(b[-1])
    
        a_num_lines = len(a)
        b_num_lines = len(b)
    
        markup_a = markup_b = None
    
        if enable_syntax_highlighting and _have_pygments:
            try:
                # TODO: Try to figure out the right lexer for these files
                #       once instead of twice.
                markup_a = apply_pygments(old or '', filediff.source_file or filediff.dest_file)
                markup_b = apply_pygments(new or '', filediff.dest_file or filediff.source_file)
            except ValueError, ex:
                import warnings
                warnings.warn("apply_pygments failed: %r" % (ex, ))
                pass
    
        # If no highlighting, no pygments, or there was a pygments error (i.e. no lexer)
        if not markup_a:
            markup_a = re.split(r"\r?\n", escape(old))
        if not markup_b:
            markup_b = re.split(r"\r?\n", escape(new))
    
        #siteconfig = SiteConfiguration.objects.get_current()

        differ = Differ(a, b, ignore_space=ignore_space)
    
        if interfilediff:
            logging.debug("Generating diff chunks for interdiff ids %s-%s",
                          filediff.id, interfilediff.id)
        else:
            logging.debug("Generating diff chunks for filediff id %s", filediff.id)

    else:
        differ = DifferFromFileDiffItem(filediff)
        a = differ.left_contents
        b = differ.right_contents
        markup_a = [ escape(x) for x in a ]
        markup_b = [ escape(x) for x in b ]

    chunks = []
    linenum = 1
    # TODO: Make this back into a preference if people really want it.
    context_num_lines = 11
    collapse_threshold = 2 * context_num_lines + 3

    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        oldlines = markup_a[i1:i2]
        newlines = markup_b[j1:j2]
        numlines = max(len(oldlines), len(newlines))

        lines = map(diff_line,
                    xrange(linenum, linenum + numlines),
                    xrange(i1 + 1, i2 + 1), xrange(j1 + 1, j2 + 1),
                    a[i1:i2], b[j1:j2], oldlines, newlines)
        linenum += numlines

        if tag == 'equal' and numlines > collapse_threshold:
            last_range_start = numlines - context_num_lines

            if len(chunks) == 0:
                add_ranged_chunks(chunks, lines, 0, last_range_start, True)
                add_ranged_chunks(chunks, lines, last_range_start, numlines)
            else:
                add_ranged_chunks(chunks, lines, 0, context_num_lines)

                if i2 == a_num_lines and j2 == b_num_lines:
                    add_ranged_chunks(chunks, lines, context_num_lines, numlines, True)
                else:
                    add_ranged_chunks(chunks, lines, context_num_lines,
                                      last_range_start, True)
                    add_ranged_chunks(chunks, lines, last_range_start, numlines)
        else:
            chunks.append(new_chunk(lines, numlines, tag))

    if interfilediff:
        logging.debug("Done generating diff chunks for interdiff ids %s-%s",
                      filediff.id, interfilediff.id)
    else:
        logging.debug("Done generating diff chunks for filediff id %s",
                      filediff.id)

    return chunks


class DiffItem(object):
    def __init__(self, id, filediffex, cwd=None, hl_enabled=True, file_on_disk=True):
        self.id = id
        self.filediffex = filediffex
        self.cwd = cwd
        self.enable_syntax_highlighting = hl_enabled
        self.file_on_disk = file_on_disk

        self._left_file_uri = None
        self._left_contents = None
        self._right_file_uri = None
        self._right_contents = None
        self.source_revision = ""
        self.dest_revision = ""

        self.chunks = None
        self.changed_chunks = []
        self.has_changes = False
        self.num_changes = 0
        self.num_changed_lines = 0

    def __repr__(self):
        result = []
        if self.left_file_uri:
            result.append("left file uri:         %r" % (self.left_file_uri, ))
        if self.source_revision:
            result.append("left version:          %r" % (self.source_revision, ))
        if self._left_contents:
            result.append("left_contents length:  %d" % (len(self._left_contents), ))
        if self.right_file_uri:
            result.append("right file uri:        %r" % (self.right_file_uri, ))
        if self.dest_revision:
            result.append("right version:         %r" % (self.dest_revision, ))
        if self._right_contents:
            result.append("right_contents length: %d" % (len(self._right_contents), ))
        if self.filediffex.diff:
            result.append("diff length:           %d" % (len(self.diff), ))

        result.append("left == right:           %r" % (self.get_original_file() == self.get_patched_file()), )

        if self.num_changed_lines == 0:
            s = "DiffItem:: no changes"
        elif self.num_changed_lines == 1:
            s = "DiffItem:: 1 changed line"
        elif self.num_changes == 1:
            s = "DiffItem: %d lines changed in 1 section" % (self.num_changed_lines, )
        else:
            s = "DiffItem: %d lines changed in %d sections" % (self.num_changed_lines,
                                                               self.num_changes)
        return "%s\n%s\n" % (s, "\n".join(result))

    @property
    def hunks(self):
        return self.filediffex.hunks

    @property
    def diff(self):
        return self.filediffex.diff

    @property
    def left_file_uri(self):
        return ""

    @property
    def right_file_uri(self):
        if self._right_file_uri is None:
            self._right_file_uri = self.filediffex.best_path(self.cwd)
        return self._right_file_uri

    @property
    def source_file(self):
        if self.left_file_uri:
            return URIToLocalPath(self.left_file_uri)
        return ""

    @property
    def dest_file(self):
        if self.right_file_uri:
            return URIToLocalPath(self.right_file_uri)
        return ""

    # XXX - This is not portable. Need to replace this function, perhaps:
    #       http://code.google.com/p/python-patch
    def _patch_file(self, diff, file_contents, reversed=False):
        from xpcom import components
        result = None
        fd, tfname = tempfile.mkstemp()
        try:
            os.fdopen(fd, "wb").write(file_contents)
            MY_ID = "sbsdiff@activestate.com";
            em = components.classes["@mozilla.org/extensions/manager;1"].\
                     getService(components.interfaces.nsIExtensionManager)
            afile = em.getInstallLocation(MY_ID).getItemFile(MY_ID, "platform")
            # Patch is not that common on installations, so it's # included by
            # default in the extension itself.
            if sys.platform.startswith("win"):
                afile.append("WINNT")
                afile.append("patch.exe")
            else:
                if sys.platform.startswith("linux"):
                    # Detertmine the architecutre.
                    import platform
                    afile.append("Linux-%s" % (platform.architecture()[0]))
                elif sys.platform.startswith("darwin"):
                    afile.append("Darwin")
                afile.append("patch")
            argv = [afile.path, tfname]
            if reversed:
                argv.insert(1, "--reverse")
            PIPE = subprocess.PIPE
            p = subprocess.Popen(argv, stdin=PIPE, stdout=PIPE, stderr=PIPE)
            stdout, stderr = p.communicate(diff)
            if p.returncode == 0:
                result = file(tfname, "rb").read()
        finally:
            os.remove(tfname)
        return result

    def get_original_file(self, allow_patching=True):
        from xpcom import components
        if self._left_contents is None:
            if self.left_file_uri:
                koFileEx = components.classes["@activestate.com/koFileEx;1"] \
                              .createInstance(components.interfaces.koIFileEx)
                koFileEx.URI = self.left_file_uri
                koFileEx.open('rb')
                self._left_contents = koFileEx.readfile()
                koFileEx.close()
            elif allow_patching and self.diff and (self._right_contents or self.right_file_uri):
                right_contents = self.get_patched_file(allow_patching=False)
                if right_contents is not None:
                    # Apply the patch to get the right contents.
                    self._left_contents = self._patch_file(self.diff, right_contents, reversed=True)
        return self._left_contents

    def get_patched_file(self, allow_patching=True):
        from xpcom import components
        if self._right_contents is None:
            if self.right_file_uri:
                koFileEx = components.classes["@activestate.com/koFileEx;1"] \
                              .createInstance(components.interfaces.koIFileEx)
                koFileEx.URI = self.right_file_uri
                koFileEx.open('rb')
                self._right_contents = koFileEx.readfile()
                koFileEx.close()
            elif allow_patching and self.diff and (self._left_contents or self.left_file_uri):
                left_contents = self.get_original_file(allow_patching=False)
                if left_contents is not None:
                    # Apply the patch to get the right contents.
                    self._right_contents = self._patch_file(self.diff, left_contents)
        return self._right_contents

    def load_chunks(self):
        chunks = get_chunks(self, None, 0, self.enable_syntax_highlighting)
        self.chunks = chunks
        self.has_changes = False
        self.changed_chunks = []
        self.num_changed_lines = 0
        for chunk in chunks:
            if chunk.get("change") != "equal":
                self.has_changes = True
                self.changed_chunks.append(chunk)
                self.num_changed_lines += chunk.get("numlines", 0)
        self.num_changes = len(self.changed_chunks)

    def toHTML(self):
        import reviewboard.settings
        from django.core.management import setup_environ
        from django.template.loader import render_to_string
        setup_environ(reviewboard.settings)
        return render_to_string('diffviewer/diff_file_fragment.html',
                                { 'file': self,
                                  'collapseall': True })



class SideBySideDiff(object):
    def __init__(self, koIDiff, cwd=None, hl_enabled=True):
        self.koIDiff = koIDiff
        self.cwd = cwd
        self.hl_enabled = hl_enabled

    def toHTML(self):
        cwd = self.cwd
        file_on_disk = ((cwd and True) or False)
        file_count = 1
        html_pieces = ['<div id="diff-details"><p><label>Files Changed:</label></p>', "<ol>"]
        file_pieces = []
        for filediffex in self.koIDiff.diffex.file_diffs:
            # Add the index.
            shortest_path = None
            for key, path in filediffex.paths.items():
                if path and (shortest_path is None or len(path) < len(shortest_path)):
                    shortest_path = path
            html_pieces.append('  <li><a href="#file.%d">%s</a>: %s change%s [' % (
                               file_count, escape(shortest_path),
                               len(filediffex.hunks),
                               len(filediffex.hunks) > 1 and "s" or ""))
            hunk_count = 1
            for hunk in filediffex.hunks:
                html_pieces.append('    <a href="#chunk.%d.%d" >%d</a>' % (
                                    file_count, hunk_count, hunk_count))
                hunk_count += 1
            html_pieces.append("]\n  </li>")

            # Add the diff.
            d = DiffItem("%s" % (file_count), filediffex, cwd=cwd,
                         hl_enabled=self.hl_enabled,
                         file_on_disk=file_on_disk)
            file_count += 1
            d.load_chunks()
            #print d
            file_pieces.append(d.toHTML())
        html_pieces.append("</div>")
        html_pieces += file_pieces
        return "\n\n".join(html_pieces)
