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

import os
import sys

from xpcom import components, ServerException, nsError
from xpcom.server import WrapObject, UnwrapObject


rvb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pylib", "reviewboard")
if rvb_path not in sys.path:
    sys.path.append(rvb_path)
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"


class sbsDiff:
    _com_interfaces_ = [components.interfaces.sbsIDiff]
    _reg_clsid_ = "{63a9448f-cfd2-4bed-9358-84fabf68d910}"
    _reg_contractid_ = "@activestate.com/sbsDiff;1"
    _reg_desc_ = "Side by side diff component for generating HTML diffs"


    def __init__(self):
        self.enable_syntax_highlighting = True
        self.cwd = None
        self.koDiff = None

    html_template = """
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">
<html lang="en">
<head>
    <title>Diff</title>
    <link rel="stylesheet" type="text/css" href="chrome://sbsdiff/skin/common.css" />
    <link rel="stylesheet" type="text/css" href="chrome://sbsdiff/skin/diffviewer.css" />
    <link rel="stylesheet" type="text/css" href="chrome://sbsdiff/skin/syntax.css" />

    <script type="text/javascript" src="chrome://sbsdiff/content/diffviewer.js"></script>

</head>
<body>

%s

</body>
</html>
"""

    def generateSbsDiff(self, koIDiff):
        #diff_data = file("/tmp/fd.patch").read()
        import sbs_diff_helper
        reload(sbs_diff_helper)
        self.koDiff = UnwrapObject(koIDiff)
        sbsdiff = sbs_diff_helper.SideBySideDiff(self.koDiff,
                                                 self.cwd,
                                                 self.enable_syntax_highlighting)
        return self.html_template % (sbsdiff.toHTML())

    def filepathFromChunkId(self, chunk_id):
        sp = chunk_id.split(".")
        if len(sp) == 3:
            try:
                file_pos = int(sp[1]) - 1
                if file_pos >= 0 and file_pos < len(self.koDiff.diffex.file_diffs):
                    return self.koDiff.diffex.file_diffs[file_pos].best_path(self.cwd)
            except ValueError:
                pass

    def diffLinenoFromChunkId(self, chunk_id):
        sp = chunk_id.split(".")
        if len(sp) == 3:
            try:
                file_pos = int(sp[1]) - 1
                if file_pos >= 0 and file_pos < len(self.koDiff.diffex.file_diffs):
                    fd = self.koDiff.diffex.file_diffs[file_pos]
                    diff_lineno = fd.hunks[0].start_line
                    return self.koDiff.diffex.file_pos_from_diff_pos(diff_lineno, 0)[1]
            except ValueError:
                pass
        return -1
