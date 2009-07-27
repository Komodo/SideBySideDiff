/* ***** BEGIN LICENSE BLOCK *****
 * Version: MPL 1.1/GPL 2.0/LGPL 2.1
 * 
 * The contents of this file are subject to the Mozilla Public License
 * Version 1.1 (the "License"); you may not use this file except in
 * compliance with the License. You may obtain a copy of the License at
 * http://www.mozilla.org/MPL/
 * 
 * Software distributed under the License is distributed on an "AS IS"
 * basis, WITHOUT WARRANTY OF ANY KIND, either express or implied. See the
 * License for the specific language governing rights and limitations
 * under the License.
 * 
 * The Original Code is "side by side diff" code.
 * 
 * The Initial Developer of the Original Code is ActiveState Software Inc.
 * Portions created by ActiveState Software Inc are Copyright (C) 2008-2009
 * ActiveState Software Inc. All Rights Reserved.
 * 
 * Contributor(s):
 *   Todd Whiteman @ ActiveState Software Inc
 * 
 * Alternatively, the contents of this file may be used under the terms of
 * either the GNU General Public License Version 2 or later (the "GPL"), or
 * the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
 * in which case the provisions of the GPL or the LGPL are applicable instead
 * of those above. If you wish to allow use of your version of this file only
 * under the terms of either the GPL or the LGPL, and not to allow others to
 * use your version of this file under the terms of the MPL, indicate your
 * decision by deleting the provisions above and replace them with the notice
 * and other provisions required by the GPL or the LGPL. If you do not delete
 * the provisions above, a recipient may use your version of this file under
 * the terms of any one of the MPL, the GPL or the LGPL.
 * 
 * ***** END LICENSE BLOCK ***** */

// Constants
var BACKWARD = -1;
var FORWARD  = 1;
var INVALID  = -1;
var DIFF_SCROLLDOWN_AMOUNT = 100;
var VISIBLE_CONTEXT_SIZE = 5;

function getEl(id) {
    return document.getElementById(id);
}
function expandChunkKomodo(file_id, chunk_index, num_lines) {
    var orig_scrollHeight = document.documentElement.scrollHeight;

    getEl('chunk.' + file_id + '.' + chunk_index).style.display = '';
    getEl('chunk-collapse.' + file_id + '.' + chunk_index).style.display = '';
    getEl('chunk-expand.' + file_id + '.' + chunk_index).style.display = 'none';

    document.documentElement.scrollTop += (document.documentElement.scrollHeight - orig_scrollHeight);
}

function collapseChunkKomodo(file_id, chunk_index, num_lines) {
    var orig_scrollHeight = document.documentElement.scrollHeight;
    var orig_scrollTop = document.documentElement.scrollTop;

    getEl('chunk.' + file_id + '.' + chunk_index).style.display = 'none';
    getEl('chunk-collapse.' + file_id + '.' + chunk_index).style.display = 'none';
    getEl('chunk-expand.' + file_id + '.' + chunk_index).style.display = '';

    document.documentElement.scrollTop = orig_scrollTop + (document.documentElement.scrollHeight - orig_scrollHeight);
}

function scrollToAnchor(anchor, noscroll) {
    if (anchor == INVALID) {
        return false;
    }

    if (!noscroll) {
        window.scrollTo(0, getEl(gAnchors[anchor]).getY() -
                           DIFF_SCROLLDOWN_AMOUNT);
    }

    SetHighlighted(gSelectedAnchor, false);
    SetHighlighted(anchor, true);
    gSelectedAnchor = anchor;

    return true;
}

function GetNextAnchor(dir, commentAnchors) {
    for (var anchor = gSelectedAnchor + dir; ; anchor = anchor + dir) {
        if (anchor < 0 || anchor >= gAnchors.length) {
            return INVALID;
        }

        var name = gAnchors[anchor].name;

        if (name == "index_header" || name == "index_footer") {
            return INVALID;
        } else if ((!commentAnchors && name.substr(0, 4) != "file") ||
                   (commentAnchors && name.substr(0, 4) == "file")) {
            return anchor;
        }
    }
}

function GetNextFileAnchor(dir) {
    var fileId = gAnchors[gSelectedAnchor].name.split(".")[0];
    var newAnchor = parseInt(fileId) + dir;
    return GetAnchorByName(newAnchor);
}

function SetHighlighted(anchor, highlighted) {
    var anchorNode = gAnchors[anchor];
    var nextNode = getEl(gAnchors[anchor]).getNextSibling();
    var controlsNode;

    if (anchorNode.parentNode.tagName == "TH") {
        controlsNode = anchorNode;
    } else if (nextNode.className == "sidebyside") {
        controlsNode = nextNode.rows[0].cells[0];
    } else {
        return;
    }

    controlsNode.innerHTML = (highlighted ? "▶" : "");
}
