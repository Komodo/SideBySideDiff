import fnmatch
import logging
import os
import re
import subprocess
import tempfile
from difflib import SequenceMatcher

try:
    import pygments
    from pygments.lexers import get_lexer_for_filename
    # from pygments.lexers import guess_lexer_for_filename
    from pygments.formatters import HtmlFormatter
    _have_pygments = True
except ImportError:
    _have_pygments = False

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _

from reviewboard.diffviewer.myersdiff import MyersDiffer
from reviewboard.diffviewer.smdiff import SMDiffer
from reviewboard.scmtools.core import PRE_CREATION, HEAD


DEFAULT_DIFF_COMPAT_VERSION = 1


class UserVisibleError(Exception):
    pass


class DiffCompatError(Exception):
    pass


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


def patch(diff, file, filename):
    """Apply a diff to a file.  Delegates out to `patch` because noone
       except Larry Wall knows how to patch."""

    #log_timer = log_timed("Patching file %s" % filename)

    def convert_line_endings(data):
        # Files without a trailing newline come out of Perforce (and possibly
        # other systems) with a trailing \r. Diff will see the \r and
        # add a "\ No newline at end of file" marker at the end of the file's
        # contents, which patch understands and will happily apply this to
        # a file with a trailing \r.
        #
        # The problem is that we normalize \r's to \n's, which breaks patch.
        # Our solution to this is to just remove that last \r and not turn
        # it into a \n.
        #
        # See http://code.google.com/p/reviewboard/issues/detail?id=386
        # and http://reviews.review-board.org/r/286/
        if data == "":
            return ""

        if data[-1] == "\r":
            data = data[:-1]

        temp = data.replace('\r\n', '\n')
        temp = temp.replace('\r', '\n')
        return temp

    if diff.strip() == "":
        # Someone uploaded an unchanged file. Return the one we're patching.
        return file

    # Prepare the temporary directory if none is available
    tempdir = tempfile.mkdtemp(prefix='reviewboard.')

    (fd, oldfile) = tempfile.mkstemp(dir=tempdir)
    f = os.fdopen(fd, "w+b")
    f.write(convert_line_endings(file))
    f.close()

    diff = convert_line_endings(diff)

    # XXX: catch exception if Popen fails?
    newfile = '%s-new' % oldfile
    p = subprocess.Popen(['patch', '-o', newfile, oldfile],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    p.stdin.write(diff)
    p.stdin.close()
    patch_output = p.stdout.read()
    failure = p.wait()

    if failure:
        f = open("%s.diff" %
                 (os.path.join(tempdir, os.path.basename(filename))), "w")
        f.write(diff)
        f.close()

        #log_timer.done()

        # FIXME: This doesn't provide any useful error report on why the patch
        # failed to apply, which makes it hard to debug.  We might also want to
        # have it clean up if DEBUG=False
        raise Exception(_("The patch to '%s' didn't apply cleanly. The temporary " +
                          "files have been left in '%s' for debugging purposes.\n" +
                          "`patch` returned: %s") %
                        (filename, tempdir, patch_output))

    f = open(newfile, "r")
    data = f.read()
    f.close()

    os.unlink(oldfile)
    os.unlink(newfile)
    os.rmdir(tempdir)

    #log_timer.done()

    return data


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
    if differ.ratio() < 0.6:
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


def get_original_file(filediff):
    if filediff.source_revision != PRE_CREATION:
        return file(filediff.source_file).read()
    return ""


def get_patched_file(buffer, filediff):
    return patch(filediff.diff, buffer, filediff.dest_file)


def get_chunks(filediff, interfilediff, force_interdiff,
               enable_syntax_highlighting):
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

    def add_ranged_chunks(lines, start, end, collapsable=False):
        numlines = end - start
        chunks.append(new_chunk(lines[start:end], end - start, 'equal',
                      collapsable))

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

    file = filediff.source_file
    revision = filediff.source_revision

    old = get_original_file(filediff)
    new = get_patched_file(old, filediff)

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

    try:
        # TODO: Try to figure out the right lexer for these files
        #       once instead of twice.
        markup_a = apply_pygments(old or '', filediff.source_file)
        markup_b = apply_pygments(new or '', filediff.dest_file)
    except ValueError:
        pass

    #siteconfig = SiteConfiguration.objects.get_current()

    chunks = []
    linenum = 1

    ignore_space = False
    #for pattern in siteconfig.get("diffviewer_include_space_patterns"):
    #    if fnmatch.fnmatch(file, pattern):
    #        ignore_space = False
    #        break

    differ = Differ(a, b, ignore_space=ignore_space)

    # TODO: Make this back into a preference if people really want it.
    context_num_lines = 5
    collapse_threshold = 2 * context_num_lines + 3

    if interfilediff:
        logging.debug("Generating diff chunks for interdiff ids %s-%s",
                      filediff.id, interfilediff.id)
    else:
        logging.debug("Generating diff chunks for filediff id %s", filediff.id)

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
                add_ranged_chunks(lines, 0, last_range_start, True)
                add_ranged_chunks(lines, last_range_start, numlines)
            else:
                add_ranged_chunks(lines, 0, context_num_lines)

                if i2 == a_num_lines and j2 == b_num_lines:
                    add_ranged_chunks(lines, context_num_lines, numlines, True)
                else:
                    add_ranged_chunks(lines, context_num_lines,
                                      last_range_start, True)
                    add_ranged_chunks(lines, last_range_start, numlines)
        else:
            chunks.append(new_chunk(lines, numlines, tag))

    if interfilediff:
        logging.debug("Done generating diff chunks for interdiff ids %s-%s",
                      filediff.id, interfilediff.id)
    else:
        logging.debug("Done generating diff chunks for filediff id %s",
                      filediff.id)

    return chunks



class FileDiff:
    def __init__(self, id, source_file, source_revision, diff, dest_file):
        self.id = id
        self.source_file = source_file
        self.source_revision = source_revision
        self.diff = diff
        self.dest_file = dest_file

diff_data = """--- /tmp/fd.py	2008-10-09 10:47:14.000000000 -0700
+++ /tmp/fd2.py	2008-10-09 10:47:53.000000000 -0700
@@ -8,7 +8,7 @@
         (None, {
             'fields': ('diffset', ('source_file', 'source_revision'),
                        ('dest_file', 'dest_detail'),
-                       'binary', 'diff', 'parent_diff')
+                       'binary', 'diff', 'other', 'parent_diff')
         }),
     )
     list_display = ('source_file', 'source_revision',
@@ -23,5 +23,6 @@
 
 admin.site.register(FileDiff, FileDiffAdmin)
 admin.site.register(DiffSet, DiffSetAdmin)
+admin.site.register(DiffSetOther)
 admin.site.register(DiffSetHistory)
"""

fd = FileDiff("1", "/tmp/fd.py", "1", diff_data, "/tmp/fd_patched.py")

chunks = get_chunks(fd, None, 0, _have_pygments)

class chunkSummary:
    def __init__(self, chunks):
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

    def __repr__(self):
        if self.num_changed_lines == 0:
            return "chunkSummary:: no changes"
        elif self.num_changed_lines == 1:
            return "chunkSummary:: 1 changed line"
        elif self.num_changes == 1:
            return "chunkSummary: %d lines changed in 1 section" % (self.num_changed_lines, )
        return "chunkSummary: %d lines changed in %d sections" % (self.num_changed_lines, self.num_changes)

    template = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">
<html lang="en">
<head>
    <title><!-- Insert your title here --></title>
</head>
<body>

<table class="sidebyside" id="file">
 <colgroup>
  <col class="controls" />
  <col class="line" />
  <col class="left" />
  <col class="line" />
  <col class="right" />
 </colgroup>
 <thead>
  <tr onClick="gotoAnchor('{{file.index}}');">
   <th class="controls">&nbsp;</th>
   <th colspan="4">{{ file.depot_filename }}</th>
  </tr>
  <tr>
   <th colspan="3" class="rev">{{file.revision}}</th>
   <th colspan="2" class="rev">{{file.dest_revision}}</th>
  </tr>
 </thead>

  %s

</table>
</body>
</html>
"""

    chunk_template_not_collapsed = """
 <tbody>

  %s

 </tbody>
"""

    chunk_template_collapsed = """
 <tbody class="collapsed" id="collapsed-chunk{{file.index}}.{{forloop.counter0}}">
  <tr>
   <th class="controls">&nbsp;</th>
   <th>...</th>
   <td colspan="3">{{ chunk.numlines }} line{{chunk.numlines|pluralize}} hidden [<a href="#" onclick="javascript:expandChunk('file{{file.index}}', '{{file.filediff.id}}', '{{forloop.counter0}}', 'collapsed-chunk{{file.index}}.{{forloop.counter0}}'); return false;">{% trans "Expand" %}</a>]</td>
  </tr>
 </tbody>
"""

    line_teplate_first_line = """
  <tr line="{{line.0}}">
   <th>{{line.1}}</th>
   <td><pre>{{ line.2|showextrawhitespace }}</pre></td>
   <th>{{line.4}}</th>
   <td><pre>{{ line.5|showextrawhitespace }}</pre></td>
  </tr>
"""

    line_teplate_other_lines = """
  <tr line="{{line.0}}">
   <th>{{line.1}}</th>
   <td><pre>{{ line.2|showextrawhitespace }}</pre></td>
   <th>{{line.4}}</th>
   <td><pre>{{ line.5|showextrawhitespace }}</pre></td>
  </tr>
"""

    def toHTML(self):
        html_chunks = []
        for chunk in self.chunks:
            lines = chunk.get("lines")
            first_line = True
            html_lines = []
            for line in lines:
                if first_line:
                    line_html = self.line_teplate_first_line
                    first_line = False
                else:
                    line_html = self.line_teplate_other_lines
                line_html = line_html.replace("{{line.0}}", str(line[0]))
                line_html = line_html.replace("{{line.1}}", str(line[1]))
                line_html = line_html.replace("{{ line.2|showextrawhitespace }}", line[2])
                line_html = line_html.replace("{{line.4}}", str(line[4]))
                line_html = line_html.replace("{{ line.5|showextrawhitespace }}", line[5])
                html_lines.append(line_html)
            html_chunks.append(self.chunk_template_not_collapsed % ("\n".join(html_lines)))
        html = self.template % ("\n".join(html_chunks))
        return html

cs = chunkSummary(chunks)
print cs.toHTML()

#outfile = file("/tmp/fd.html", "w")
#outfile.write("""
#              """ % (chunks.l)