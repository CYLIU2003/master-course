param(
    [Parameter(Mandatory=$true)][string]$InputPptx,
    [Parameter(Mandatory=$true)][string]$OutputPptx,
    [Parameter(Mandatory=$true)][string]$Evidence
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $InputPptx).Path
$destination = [IO.Path]::GetFullPath($OutputPptx)
if (Test-Path -LiteralPath $destination) { throw 'Output already exists' }
$data = Get-Content -LiteralPath $Evidence -Raw -Encoding UTF8 | ConvertFrom-Json
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
function Add-DateLabel($slide, $value, $center, $top, $width, $size) {
    $label = $slide.Shapes.AddTextbox(1, $center - $width / 2, $top, $width, 30)
    $label.TextFrame.MarginLeft = 0
    $label.TextFrame.MarginRight = 0
    $label.TextFrame.MarginTop = 0
    $label.TextFrame.TextRange.Text = $value
    $label.TextFrame.TextRange.Font.Name = 'Noto Sans JP'
    $label.TextFrame.TextRange.Font.NameFarEast = 'Noto Sans JP'
    $label.TextFrame.TextRange.Font.NameComplexScript = 'Noto Sans JP'
    $label.TextFrame.TextRange.Font.Size = [double]$size
    $label.TextFrame.TextRange.Font.Color.RGB = 7365209
    $label.TextFrame.TextRange.ParagraphFormat.Alignment = 2
}
try {
    $deck = $app.Presentations.Open($source, -1, 0, 0)
    for ($page = 1; $page -le $deck.Slides.Count; $page++) {
        $slide = $deck.Slides.Item($page)
        $charts = @($slide.Shapes | Where-Object { $_.HasChart -eq -1 })
        foreach ($shape in $charts) {
            if ($shape.Chart.ChartType -in @(-4169, 72, 73, 74, 75)) {
                $shape.Chart.ChartType = 75
                for ($i = 1; $i -le $shape.Chart.SeriesCollection().Count; $i++) {
                    $shape.Chart.SeriesCollection($i).Smooth = $false
                }
            }
        }
        if ($page -ne 15 -and $page -ne 17 -and $page -lt 25) { continue }
        for ($chartIndex = 0; $chartIndex -lt $charts.Count; $chartIndex++) {
            $shape = $charts[$chartIndex]
            $chart = $shape.Chart
            $axis = $chart.Axes(1)
            $maximum = [double]$axis.MaximumScale
            $left = [double]$chart.PlotArea.InsideLeft
            $top = [double]$chart.PlotArea.InsideTop
            $width = [double]$chart.PlotArea.InsideWidth
            $height = [double]$chart.PlotArea.InsideHeight
            $axis.TickLabelPosition = -4142 # xlTickLabelPositionNone
            $axis.HasTitle = $false
            $axis.HasMajorGridlines = $true
            $axis.MajorUnit = $(if ($page -eq 17) { 1 } else { 24 })
            $axis.MajorGridlines.Format.Line.ForeColor.RGB = 14277081
            $axis.MajorGridlines.Format.Line.Weight = 0.6
            $axis.MajorGridlines.Format.Line.DashStyle = 4
            $chart.PlotArea.InsideLeft = $left
            $chart.PlotArea.InsideTop = $top
            $chart.PlotArea.InsideWidth = $width
            $chart.PlotArea.InsideHeight = $height
            $labelTop = $shape.Top + $top + $height + 3
            if ($page -eq 17) {
                $week = $(if ($chartIndex -eq 0) { $data.weeks[2] } else { $data.weeks[10] })
                $start = [datetime]::Parse($week.summary.week).AddHours(($week.power.full_period.peak_slot - 12) / 4)
                for ($hour = 0; $hour -le 6; $hour++) {
                    Add-DateLabel $slide ($start.AddHours($hour).ToString('HH:mm')) ($shape.Left + $left + $width * $hour / $maximum) $labelTop 42 12
                }
                continue
            }
            $starts = @($(if ($page -eq 15) { @('2025-03-03', '2025-11-10') } else { @($data.weeks[$page - 25].summary.week) }))
            for ($row = 0; $row -lt $starts.Count; $row++) {
                $start = [datetime]::Parse($starts[$row])
                for ($day = 0; $day -lt 7; $day++) {
                    $date = $start.AddDays($day)
                    $weekday = @('日','月','火','水','木','金','土')[[int]$date.DayOfWeek]
                    Add-DateLabel $slide ($date.ToString('M/d') + '(' + $weekday + ')') ($shape.Left + $left + $width * ($day * 24 + 12) / $maximum) ($labelTop + $row * 18) 76 12.5
                }
                # The short terminal overnight period has its own centered date.
                Add-DateLabel $slide ($start.AddDays(7).ToString('M/d') + "`n翌朝") ($shape.Left + $left + $width * ((168 + $maximum) / 2) / $maximum) ($labelTop + $row * 18) 34 9
            }
        }
    }
    $deck.SaveAs($destination, 24)
} finally {
    if ($null -ne $deck) { $deck.Close() }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
