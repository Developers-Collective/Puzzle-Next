'''
Licensed under the terms of the MIT License
https://github.com/luchko/QCodeEditor
https://github.com/ikoichi/markdown-editor
https://github.com/N-I-N-0/Puzzle-Next
@author: Ivan Luchko (luchko.ivan@gmail.com)
@author: <luca.restagno@gmail.com>
@author: Nin0#2257

This module contains the light QPlainTextEdit based QCodeEditor widget which 
provides the line numbers bar and the syntax and the current line highlighting.
'''
try:
    import PyQt5 as PyQt
    pyQtVersion = "PyQt5"
except ImportError:
    try:
        import PySide2 as PyQt
        pyQtVersion = "PySide2"
    except ImportError:
        raise ImportError("neither PyQt5 or PySide2 found")

# imports requied PyQt modules
if pyQtVersion == "PyQt5":
    from PyQt5.QtCore import Qt, QRect, QRegExp
    from PyQt5.QtWidgets import QWidget, QTextEdit, QPlainTextEdit
    from PyQt5.QtGui import (QColor, QPainter, QFont, QSyntaxHighlighter,
                             QTextFormat, QTextCharFormat)
else:
    from PySide2.QtCore import Qt, QRect, QRegExp
    from PySide2.QtWidgets import QWidget, QTextEdit, QPlainTextEdit
    from PySide2.QtGui import (QColor, QPainter, QFont, QSyntaxHighlighter,
                               QTextFormat, QTextCharFormat)
# classes definition

class XMLHighlighter(QSyntaxHighlighter):
    '''
    Class for highlighting xml text inherited from QSyntaxHighlighter

    reference:
        http://www.yasinuludag.com/blog/?p=49
    '''
    def __init__(self, parent=None):
        super(XMLHighlighter, self).__init__(parent)

        self.highlightingRules = []
        self.searchRules = []

        xmlElementFormat = QTextCharFormat()
        xmlElementFormat.setForeground(QColor("#00ee00"))
        self.highlightingRules.append((QRegExp("\\b[A-Za-z0-9_]+(?=[\s/>])"), xmlElementFormat))

        xmlAttributeFormat = QTextCharFormat()
        xmlAttributeFormat.setFontItalic(True)
        xmlAttributeFormat.setForeground(QColor("#d000d0"))
        self.highlightingRules.append((QRegExp("\\b[A-Za-z0-9_]+(?=\\=)"), xmlAttributeFormat))
        self.highlightingRules.append((QRegExp("="), xmlAttributeFormat))

        self.valueFormat = QTextCharFormat()
        self.valueFormat.setForeground(QColor("#55dddd"))
        self.valueStartExpression = QRegExp("\"")
        self.valueEndExpression = QRegExp("\"(?=[\s></])")

        singleLineCommentFormat = QTextCharFormat()
        singleLineCommentFormat.setForeground(QColor("#b3b3b3"))
        self.highlightingRules.append((QRegExp("<!--[^\n]*-->"), singleLineCommentFormat))

        textFormat = QTextCharFormat()
        textFormat.setForeground(QColor("#FFFFFF"))
        # (?<=...)  - lookbehind is not supported
        self.highlightingRules.append((QRegExp(">(.+)(?=</)"), textFormat))

        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor("#FFFFFF"))
        keywordPatterns = ["\\b?xml\\b", "/>", ">", "<", "</"] 
        self.highlightingRules += [(QRegExp(pattern), keywordFormat) for pattern in keywordPatterns]

    #VIRTUAL FUNCTION WE OVERRIDE THAT DOES ALL THE COLLORING
    def highlightBlock(self, text):
        #for every pattern
        for pattern, format in self.highlightingRules: 
            #Create a regular expression from the retrieved pattern
            expression = QRegExp(pattern) 
            #Check what index that expression occurs at with the ENTIRE text
            index = expression.indexIn(text) 
            #While the index is greater than 0
            while index >= 0:
                #Get the length of how long the expression is true, set the format from the start to the length with the text format
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                #Set index to where the expression ends in the text
                index = expression.indexIn(text, index + length)


        #HANDLE QUOTATION MARKS NOW.. WE WANT TO START WITH " AND END WITH ".. A THIRD " SHOULD NOT CAUSE THE WORDS INBETWEEN SECOND AND THIRD TO BE COLORED
        self.setCurrentBlockState(0)
        startIndex = 0
        if self.previousBlockState() != 1:
            startIndex = self.valueStartExpression.indexIn(text)
        while startIndex >= 0:
            endIndex = self.valueEndExpression.indexIn(text, startIndex)
            if endIndex == -1:
                self.setCurrentBlockState(1)
                commentLength = len(text) - startIndex
            else:
                commentLength = endIndex - startIndex + self.valueEndExpression.matchedLength()
            self.setFormat(startIndex, commentLength, self.valueFormat)
            startIndex = self.valueStartExpression.indexIn(text, startIndex + commentLength);

        for word in self.searchRules:
            expression = QRegExp(word)
            expression.setCaseSensitivity(Qt.CaseInsensitive)
            index = expression.indexIn(text)
            while index >= 0: 
                length = expression.matchedLength()
                keywordFormat = QTextCharFormat()
                keywordFormat.setBackground(QColor("#FF0000"))
                self.setFormat(index, length, keywordFormat)
                index = expression.indexIn(text, index + length)


class SearchHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super(SearchHighlighter, self).__init__(parent)

        self.searchRules = []

    def highlightBlock(self, text):
        for word in self.searchRules:
            expression = QRegExp(word)
            expression.setCaseSensitivity(Qt.CaseInsensitive)
            index = expression.indexIn(text)
            while index >= 0: 
                length = expression.matchedLength()
                keywordFormat = QTextCharFormat()
                keywordFormat.setBackground(QColor("#FF0000"))
                self.setFormat(index, length, keywordFormat)
                index = expression.indexIn(text, index + length)


class MarkdownHighlighter(QSyntaxHighlighter):
    'Modified version of: https://github.com/ikoichi/markdown-editor'
    def __init__(self, parent=None):
        super(MarkdownHighlighter, self).__init__(parent)

        self.h1_color               = '#6C78C4'
        self.h2_color               = '#6C78C4'
        self.h3_color               = '#6C78C4'
        self.h4_color               = '#268BD2'
        self.h5_color               = '#268BD2'
        self.h6_color               = '#268BD2'
        self.bold_color             = '#DC322F'
        self.italic_color           = '#CB4B16'
        self.link_color             = '#4E27A6'
        self.code_color             = '#008C3F'
        self.anchor_color           = '#BF6211'
        self.block_quotes_color     = '#93A1A1'
        self.html_entity_color      = '#8871C4'

        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(Qt.darkBlue)
        keywordFormat.setFontWeight(QFont.Bold)

        keywordPatterns = []

        self.highlightingRules = [(QRegExp(pattern), keywordFormat)
                for pattern in keywordPatterns]

        # italic
        italicFormat = QTextCharFormat()
        italicFormat.setForeground(QColor(self.italic_color))
        italicFormat.setFontItalic(True)
        self.highlightingRules.append((QRegExp("\*.*\*"),italicFormat))

        # bold
        boldFormat = QTextCharFormat()
        boldFormat.setForeground(QColor(self.italic_color))
        boldFormat.setFontWeight(99)
        self.highlightingRules.append((QRegExp("\*\*.*\*\*"),boldFormat))

        # h1
        h1Format = QTextCharFormat()
        h1Format.setForeground(QColor(self.h1_color))
        h1Format.setFontWeight(99)
        h1Format.setFontPointSize(18)
        self.highlightingRules.append((QRegExp("^#.*$"),h1Format))

        # h2
        h2Format = QTextCharFormat()
        h2Format.setForeground(QColor(self.h2_color))
        h2Format.setFontWeight(99)
        h2Format.setFontPointSize(16)
        self.highlightingRules.append((QRegExp("^##.*$"),h2Format))

        # h3
        h3Format = QTextCharFormat()
        h3Format.setForeground(QColor(self.h3_color))
        h3Format.setFontWeight(99)
        h3Format.setFontPointSize(14)
        self.highlightingRules.append((QRegExp("^###.*$"),h3Format))

        # h4
        h4Format = QTextCharFormat()
        h4Format.setForeground(QColor(self.h4_color))
        h4Format.setFontWeight(99)
        h4Format.setFontPointSize(12)
        self.highlightingRules.append((QRegExp("^####.*$"),h4Format))

        # h5
        h5Format = QTextCharFormat()
        h5Format.setForeground(QColor(self.h5_color))
        h5Format.setFontWeight(99)
        h5Format.setFontPointSize(10)
        self.highlightingRules.append((QRegExp("^#####.*$"),h5Format))

        # h6
        h6Format = QTextCharFormat()
        h6Format.setForeground(QColor(self.h6_color))
        h6Format.setFontWeight(99)
        h6Format.setFontPointSize(10)
        self.highlightingRules.append((QRegExp("^######.*$"),h6Format))

        # link
        linkFormat = QTextCharFormat()
        linkFormat.setForeground(QColor(self.link_color))
        self.highlightingRules.append((QRegExp("<.*>"),linkFormat))

        # anchor
        anchorFormat = QTextCharFormat()
        anchorFormat.setForeground(QColor(self.anchor_color))
        self.highlightingRules.append((QRegExp("\[.*\]\(.*\)"),anchorFormat))

        # code
        codeFormat = QTextCharFormat()
        codeFormat.setForeground(QColor(self.code_color))
        codeFormat.setFontPointSize(10)
        codeFormat.setFontWeight(75)
        self.highlightingRules.append((QRegExp("`.*`"),codeFormat))

        codeFormat2 = QTextCharFormat()
        codeFormat2.setForeground(QColor(self.code_color))
        codeFormat2.setFontPointSize(10)
        codeFormat2.setFontWeight(75)
        self.highlightingRules.append((QRegExp("\t.*$"),codeFormat2))

        # block quotes
        blockQuotesFormat = QTextCharFormat()
        blockQuotesFormat.setForeground(QColor(self.block_quotes_color))
        self.highlightingRules.append((QRegExp("^> "),blockQuotesFormat))

        # html entity
        htmlEntityFormat = QTextCharFormat()
        htmlEntityFormat.setForeground(QColor(self.html_entity_color))
        self.highlightingRules.append((QRegExp("&.*;"),htmlEntityFormat))

#         functionFormat = QTextCharFormat()
#         functionFormat.setFontItalic(True)
#         functionFormat.setForeground(Qt.blue)
#         self.highlightingRules.append((QRegExp("\\b[A-Za-z0-9_]+(?=\\()"),functionFormat))
#
#         self.commentStartExpression = QRegExp("/\\*")
#         self.commentEndExpression = QRegExp("\\*/")

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)


class QCodeEditor(QPlainTextEdit):
    '''
    QCodeEditor inherited from QPlainTextEdit providing:
        numberBar - set by DISPLAY_LINE_NUMBERS flag equals True
        curent line highligthing - set by HIGHLIGHT_CURRENT_LINE flag equals True
        setting up QSyntaxHighlighter

    references:
        https://john.nachtimwald.com/2009/08/19/better-qplaintextedit-with-line-numbers/    
        http://doc.qt.io/qt-5/qtwidgets-widgets-codeeditor-example.html
    '''

    class NumberBar(QWidget):
        '''class that deifnes textEditor numberBar'''
        def __init__(self, editor):
            QWidget.__init__(self, editor)
            
            self.editor = editor
            self.editor.blockCountChanged.connect(self.updateWidth)
            self.editor.updateRequest.connect(self.updateContents)
            self.font = QFont()
            self.numberBarColor = QColor("#171717")


        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(event.rect(), self.numberBarColor)

            block = self.editor.firstVisibleBlock()

            # Iterate over all visible text blocks in the document.
            while block.isValid():
                blockNumber = block.blockNumber()
                block_top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()

                # Check if the position of the block is out side of the visible area.
                if not block.isVisible() or block_top >= event.rect().bottom():
                    break

                # We want the line number for the selected line to be bold.
                if blockNumber == self.editor.textCursor().blockNumber() and self.editor.hasFocus():
                    self.font.setBold(True)
                    painter.setPen(QColor("#FFFFFF"))
                else:
                    self.font.setBold(False)
                    painter.setPen(QColor("#717171"))
                painter.setFont(self.font)

                # Draw the line number right justified at the position of the line.
                paint_rect = QRect(0, block_top, self.width(), self.editor.fontMetrics().height())
                painter.drawText(paint_rect, Qt.AlignRight, str(blockNumber+1))

                block = block.next()

            painter.end()

            QWidget.paintEvent(self, event)


        def getWidth(self):
            count = self.editor.blockCount()
            width = self.fontMetrics().width(str(count)) + 10
            return width


        def updateWidth(self):
            width = self.getWidth()
            if self.width() != width:
                self.setFixedWidth(width)
                self.editor.setViewportMargins(width, 0, 0, 0);


        def updateContents(self, rect, scroll):
            if scroll:
                self.scroll(0, scroll)
            else:
                self.update(0, rect.y(), self.width(), rect.height())

            if rect.contains(self.editor.viewport().rect()):   
                fontSize = self.editor.currentCharFormat().font().pointSize()
                self.font.setPointSize(fontSize)
                self.font.setStyle(QFont.StyleNormal)
                self.updateWidth()


    def __init__(self, DISPLAY_LINE_NUMBERS=True, HIGHLIGHT_CURRENT_LINE=True, SyntaxHighlighter=None, *args):
        '''
        Parameters
        ----------
        DISPLAY_LINE_NUMBERS : bool 
            switch on/off the presence of the lines number bar
        HIGHLIGHT_CURRENT_LINE : bool
            switch on/off the current line highliting
        SyntaxHighlighter : QSyntaxHighlighter
            should be inherited from QSyntaxHighlighter
        '''
        super(QCodeEditor, self).__init__()

        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self.DISPLAY_LINE_NUMBERS = DISPLAY_LINE_NUMBERS

        if DISPLAY_LINE_NUMBERS:
            self.number_bar = self.NumberBar(self)

        if HIGHLIGHT_CURRENT_LINE:
            self.currentLineNumber = None
            self.currentLineColor = QColor("#171717")
            self.cursorPositionChanged.connect(self.highligtCurrentLine)
            self.original_out = self.focusOutEvent
            self.focusOutEvent = self.focusOut

        if SyntaxHighlighter is not None: # add highlighter to textdocument
           self.highlighter = SyntaxHighlighter(self.document())


        self.appendPlainText("\n\n\n\n\n\n\n\n\n\n")
        self.clear()


    def focusOut(self, event):
        self.original_out(event)
        self.highligtCurrentLine(True)


    def resizeEvent(self, *e):
        '''overload resizeEvent handler'''
        if self.DISPLAY_LINE_NUMBERS:   # resize number_bar widget
            cr = self.contentsRect()
            rec = QRect(cr.left(), cr.top(), self.number_bar.getWidth(), cr.height())
            self.number_bar.setGeometry(rec)
        QPlainTextEdit.resizeEvent(self, *e)


    def highligtCurrentLine(self, hidden = False):
        if(hidden):
            hi_selection = QTextEdit.ExtraSelection()
            hi_selection.cursor = self.textCursor()
            hi_selection.cursor.clearSelection()
            self.setExtraSelections([hi_selection])
        else:
            newCurrentLineNumber = self.textCursor().blockNumber()
            if newCurrentLineNumber != self.currentLineNumber:
                self.currentLineNumber = newCurrentLineNumber
                hi_selection = QTextEdit.ExtraSelection()
                hi_selection.format.setBackground(self.currentLineColor)
                hi_selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                hi_selection.cursor = self.textCursor()
                hi_selection.cursor.clearSelection()
                self.setExtraSelections([hi_selection])