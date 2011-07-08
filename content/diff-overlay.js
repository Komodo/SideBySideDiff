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

// Globals

var g_diff_result = null;
var g_diff_cwd = null;
var g_sbsDiff = null;
var g_diffFormat = "contextual";


// Overriding functionality - overrides the diff.js loadDiffResult function.

var _original_loadDiffResult = loadDiffResult;
var loadDiffResult = function overwritten_loadDiffResult(result, cwd) {
    g_diff_result = result;
    g_diff_cwd = cwd;
    _original_loadDiffResult(result, cwd);
    if (g_diffFormat == 'side-by-side') {
        loadSBSDiff();
    }
}


// Side-by-side diff implementation.

function loadSBSDiff() {
    var koIDiff = Components.classes["@activestate.com/koDiff;1"].
                    createInstance(Components.interfaces.koIDiff);
    koIDiff.initWithDiffContent(g_diff_result);
    g_sbsDiff = Components.classes["@activestate.com/sbsDiff;1"].
                createInstance(Components.interfaces.sbsIDiff)
    g_sbsDiff.enable_syntax_highlighting = document.getElementById('enable_highlighting_checkbox').checked;
    g_sbsDiff.cwd = g_diff_cwd;
    if (!g_diff_cwd) {
        // Cannot show full context diffs.
        document.getElementById('enable_highlighting_checkbox').setAttribute('disabled', 'true');
    } else {
        document.getElementById('enable_highlighting_checkbox').removeAttribute('disabled');
    }
    var html = g_sbsDiff.generateSbsDiff(koIDiff);

    // Convert Unicode into UTF-8.
    var unicodeConverter = Components.classes["@mozilla.org/intl/scriptableunicodeconverter"]
                           .createInstance(Components.interfaces.nsIScriptableUnicodeConverter);
    unicodeConverter.charset = "UTF-8";
    html = unicodeConverter.ConvertFromUnicode(html);

    // Get the extension's on-disk location.
    var aFile = Components.classes["@mozilla.org/file/directory_service;1"].
                        getService( Components.interfaces.nsIProperties).
                        get("ProfD", Components.interfaces.nsIFile);
    aFile.append("extensions");
    aFile.append("sbsdiff@activestate.com");
    aFile.append("content");
    aFile.append("diff.html");
    if (aFile.exists())
        aFile.remove(false);
    aFile.create(Components.interfaces.nsIFile.NORMAL_FILE_TYPE, parseInt("0660", 8));
    var stream = Components.classes["@mozilla.org/network/safe-file-output-stream;1"]
                           .createInstance(Components.interfaces.nsIFileOutputStream);
    stream.init(aFile, 0x04 | 0x08 | 0x20, parseInt("0600", 8), 0); // write, create, truncate
    stream.write(html, html.length);
    if (stream instanceof Components.interfaces.nsISafeOutputStream) {
        stream.finish();
    } else {
        stream.close();
    }

    // do whatever you need to the created file
    //dump("file.path: " + ko.uriparse.localPathToURI(aFile.path) + "\n");
    var filepath = "chrome://sbsdiff/content/diff.html";
    // Set src to "", in order to clear any existing path (to reload itself).
    document.getElementById("sbs_diff_browser").setAttribute("src", "");
    document.getElementById("sbs_diff_browser").setAttribute("src", filepath);
}


function changeDiffStyle(style) {
    g_diffFormat = style;
    var deck = document.getElementById('deck');
    if (style == 'contextual') {
        deck.selectedIndex = 0;
    } else if (style == 'side-by-side') {
        deck.selectedIndex = 1;
        loadSBSDiff();
    }
}

function reloadDiffResult() {
    loadSBSDiff();
}

function diffViewer_revealInEditor(menuitem, event) {
    //ko.logging.dumpEvent(event);
    //dump("\n\n");
    //ko.logging.dumpObject(document.popupNode);
    var name;
    var chunk_id;
    var lineno = 0;
    var node = document.popupNode;
    while (node) {
        if (node.nodeName.toLowerCase() == "tbody") {
            chunk_id = node.getAttribute("id");
            break;
        } else if ((lineno == 0) && (node.nodeName.toLowerCase() == "tr")) {
            for (var i=node.childNodes.length-1; i >=0; i--) {
                var child = node.childNodes[i];
                if (child.nodeName.toLowerCase() == "th") {
                    lineno = parseInt(child.textContent);
                    if (lineno > 0)
                        break;
                }
            }
        }
        node = node.parentNode;
    }
    if (!chunk_id || (chunk_id.substr(0, 6) != "chunk.")) {
        alert("Unable to reveal the position at this location");
        return;
    }
    // We now know which file and which chunk. If we have a full-contextual
    // diff then we may know the line number as well.
    var filepath = g_sbsDiff.filepathFromChunkId(chunk_id);
    var uri = ko.uriparse.pathToURI(filepath);
    if (lineno <= 0 || !g_diff_cwd) {
        lineno = g_sbsDiff.diffLinenoFromChunkId(chunk_id);
    }
    var kowin = ko.windowManager.getMainWindow();
    kowin.ko.views.manager.doFileOpenAtLineAsync(uri, lineno, null,
                                                  null, -1,
                                                  function(v) {
                                                    if (v) {
                                                        kowin.focus();
                                                    }
                                                  });
}

function sbsEnableUI() {
    var deck = document.getElementById('deck');
    if (deck.selectedIndex == 0) {
        document.getElementById('enable_highlighting_checkbox').setAttribute('disabled', true);
    } else if (g_diff_cwd) {
        document.getElementById('enable_highlighting_checkbox').removeAttribute('disabled');
        g_diffFormat = "side-by-side";
    }
    
}

function sbsOnload() {
    var deck = document.getElementById('deck');
    if (g_diffFormat == "contextual") {
        deck.selectedIndex = 0;
    } else if (g_diffFormat == "side-by-side") {
        deck.selectedIndex = 1;
    }
    document.getElementById("diff_style_menulist").selectedIndex = deck.selectedIndex;
    sbsEnableUI();
}

function sbsOnunload() {
    var prefs = Components.classes["@mozilla.org/preferences-service;1"]
                        .getService(Components.interfaces.nsIPrefService);
    var sbs_prefs = prefs.getBranch("extensions.sbsdiff.");
    sbs_prefs.setCharPref("format", g_diffFormat);
}

(function() {
    try {
        var prefs = Components.classes["@mozilla.org/preferences-service;1"]
                            .getService(Components.interfaces.nsIPrefService);
        var sbs_prefs = prefs.getBranch("extensions.sbsdiff.");
        g_diffFormat = sbs_prefs.getCharPref("format");
    } catch (ex) {
        // There are no prefs yet, leave as is.
    }
})();

window.addEventListener("load", sbsOnload, false);
window.addEventListener("unload", sbsOnunload, false);
