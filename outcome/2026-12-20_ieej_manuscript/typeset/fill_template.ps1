param(
  [string]$Dir = 'C:\master-course\outcome\2026-12-20_ieej_manuscript',
  [string]$OutName = 'manuscript_v1'
)
# Fill the official IEEJ template (template\iee_sample.doc, converted to work_template.docx) with
# build\blocks.json (from md_to_blocks.py) and build\header.json. All text comes from UTF-8 JSON so
# this file stays ASCII (Windows PowerShell 5.1 reads BOM-less scripts as ANSI).
$ErrorActionPreference = 'Stop'
$blocks = (Get-Content "$Dir\build\blocks.json" -Raw -Encoding UTF8 | ConvertFrom-Json).blocks
$head = Get-Content "$Dir\build\header.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$w = New-Object -ComObject Word.Application
$w.Visible = $false
try {
  $doc = $w.Documents.Open("$Dir\work_template.docx", $false, $true)
  $doc.SaveAs2("$Dir\$OutName.docx", 16)
  $hStyle = $doc.Paragraphs(9).Style
  $bStyle = $doc.Paragraphs(10).Style
  for ($k = $doc.Shapes.Count; $k -ge 1; $k--) { $doc.Shapes($k).Delete() }
  $doc.Range($doc.Paragraphs(9).Range.Start, $doc.Content.End).Delete() | Out-Null

  function Set-ParaText($i, $text) {
    $p = $doc.Paragraphs($i).Range
    $doc.Range($p.Start, $p.End - 1).Text = $text
  }
  Set-ParaText 1 $head.title
  Set-ParaText 3 $head.authors
  Set-ParaText 5 $head.title_en
  Set-ParaText 6 $head.authors_en

  function Add-Para($style) {
    $doc.Content.InsertParagraphAfter()
    $p = $doc.Paragraphs.Last
    $p.Style = $style
    $p.Range.Font.Superscript = 0
    $p.Range.HighlightColorIndex = 0
    return $p
  }
  function Add-Run($p, $text, $flag) {
    $s = $p.Range.End - 1
    $doc.Range($s, $s).InsertAfter($text)
    $r = $doc.Range($s, $s + $text.Length)
    $r.Font.Superscript = [int]($flag -eq 'sup')
    $r.HighlightColorIndex = $(if ($flag -eq 'hl') { 7 } else { 0 })
    if ($flag -eq 'sub') { $r.Font.Bold = 0 }
  }
  function Add-Caption($text) {
    $p = Add-Para $bStyle
    Add-Run $p $text ''
    $p.Alignment = 1
    $p.Range.Font.Size = 8
    $p.LineSpacingRule = 4; $p.LineSpacing = 12
    return $p
  }
  $colWidth = [single]$doc.Sections(2).PageSetup.TextColumns(1).Width

  # The first block reuses the empty heading paragraph left after the English block.
  $first = $true
  foreach ($b in $blocks) {
    switch ($b.kind) {
      'heading' {
        if ($first) { $p = $doc.Paragraphs.Last; $first = $false } else { $p = Add-Para $hStyle }
        Add-Run $p $b.text ''
      }
      'para' {
        $p = Add-Para $bStyle
        $p.FirstLineIndent = 9
        foreach ($r in $b.runs) { Add-Run $p $r[0] $r[1] }
      }
      'table' {
        Add-Caption $b.caption | Out-Null
        $p = Add-Para $bStyle
        $rows = $b.rows.Count; $cols = $b.rows[0].Count
        $t = $doc.Tables.Add($p.Range, $rows, $cols)
        $t.Borders.Enable = 1
        $t.PreferredWidthType = 3; $t.PreferredWidth = [single]($colWidth * 0.9)
        $t.Rows.Alignment = 1
        for ($i = 0; $i -lt $rows; $i++) { for ($j = 0; $j -lt $cols; $j++) {
          $c = $t.Cell($i + 1, $j + 1).Range
          $c.Text = $b.rows[$i][$j][0]; $c.Font.Bold = [int][bool]$b.rows[$i][$j][1]
          $c.Font.Size = 8; $c.ParagraphFormat.Alignment = 1; $c.ParagraphFormat.FirstLineIndent = 0
          $c.ParagraphFormat.LineSpacingRule = 4; $c.ParagraphFormat.LineSpacing = 11
        } }
        if ($b.note) { $n = Add-Caption $b.note; $n.Alignment = 0 }
      }
      'figure' {
        $p = Add-Para $bStyle
        $t = $doc.Tables.Add($p.Range, 1, 1)
        $t.Borders.Enable = 1
        $t.PreferredWidthType = 3; $t.PreferredWidth = [single]$colWidth
        $t.Rows(1).HeightRule = 2; $t.Rows(1).Height = 150
        $c = $t.Cell(1, 1).Range
        $c.Text = '[figure placeholder]'; $c.ParagraphFormat.Alignment = 1; $c.Font.Size = 8
        Add-Caption $b.caption | Out-Null
      }
      'refhead' {
        $p = Add-Para $hStyle
        Add-Run $p $b.text ''
        $p.Alignment = 1
      }
      'ref' {
        $p = Add-Para $bStyle
        Add-Run $p $b.text ''
        $p.Range.Font.Size = 8
        $p.LineSpacingRule = 4; $p.LineSpacing = 12
        $p.LeftIndent = 12; $p.FirstLineIndent = -12
      }
    }
  }
  $doc.Save()
  $doc.ExportAsFixedFormat("$Dir\$OutName.pdf", 17)
  $pages = $doc.ComputeStatistics(2)
  $chars = $doc.ComputeStatistics(3)
  "pages=$pages chars=$chars colWidth=$colWidth"
  $doc.Close($false)
} finally { try { $w.Documents.Close(0) } catch {}; $w.Quit() }

