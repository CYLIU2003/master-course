param([Parameter(Mandatory=$true)][string]$Build)
$ErrorActionPreference='Stop'
$buildPath=[IO.Path]::GetFullPath($Build)
$data=Get-Content -LiteralPath (Join-Path $buildPath 'data.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$app=$null; $deck=$null
function Add-Text($slide,$value,$x,$y,$w,$h,$size) {
    $shape=$slide.Shapes.AddTextbox(1,$x,$y,$w,$h)
    $shape.TextFrame.TextRange.Text=$value
    $shape.TextFrame.TextRange.Font.Name='Noto Sans JP'
    $shape.TextFrame.TextRange.Font.NameFarEast='Noto Sans JP'
    $shape.TextFrame.TextRange.Font.NameAscii='Noto Sans JP'
    $shape.TextFrame.TextRange.Font.Size=$size
    $shape.TextFrame.TextRange.Font.Color.RGB=0x586B20
    $shape.TextFrame.MarginLeft=0; $shape.TextFrame.MarginRight=0
    $shape.TextFrame.MarginTop=0; $shape.TextFrame.MarginBottom=0
    $shape.TextFrame.TextRange.ParagraphFormat.Alignment=2
    return $shape
}
try {
    $app=New-Object -ComObject PowerPoint.Application
    $deck=$app.Presentations.Open((Join-Path $buildPath 'patched_source.pptx'),0,0,0)
    $ids=@{}
    for($i=1;$i -le 39;$i++){$ids[$i]=$deck.Slides.Item($i).SlideID}
    $inserted=$deck.Slides.InsertFromFile((Join-Path $buildPath 'final_supplement/new_slides.pptx'),39)
    if($inserted -ne 5 -or $deck.Slides.Count -ne 44){throw 'Unexpected inserted slide count'}
    for($i=40;$i -le 44;$i++){$ids[$i]=$deck.Slides.Item($i).SlideID}
    for($i=0;$i -lt $data.slide_order.Count;$i++){
        $slide=$deck.Slides.FindBySlideID($ids[[int]$data.slide_order[$i]])
        $slide.MoveTo($i+1)
        $slide.SlideShowTransition.Hidden= $(if($i -lt $data.main_slides){0}else{-1})
    }
    $maySlide=$deck.Slides.FindBySlideID($ids[41])
    $chartShapes=@($maySlide.Shapes | Where-Object {$_.HasChart -eq -1})
    if($chartShapes.Count -ne 3){throw 'Expected three May charts'}
    $geometry=@()
    for($i=0;$i -lt 3;$i++){
        $shape=$chartShapes[$i]; $chart=$shape.Chart
        $chart.Axes(1).TickLabelPosition=-4142
        $chart.Axes(1).HasTitle=0
        $chart.Axes(2).MajorUnit=$(if($i -eq 2){3000}else{500})
        for($j=1;$j -le $chart.SeriesCollection().Count;$j++){$chart.SeriesCollection($j).Smooth=0}
        $x0=$shape.Left+$chart.PlotArea.InsideLeft
        $plotWidth=$chart.PlotArea.InsideWidth
        $top=$shape.Top+$chart.PlotArea.InsideTop
        $bottom=$top+$chart.PlotArea.InsideHeight
        $line=$maySlide.Shapes.AddLine($x0+$plotWidth/2,$top,$x0+$plotWidth/2,$bottom)
        $line.Line.ForeColor.RGB=0xDDD5CB; $line.Line.Weight=0.6; $line.Line.DashStyle=4
        if($i -eq 2){
            [void](Add-Text $maySlide '5/12（月・雨）' ($x0+$plotWidth*.25-60) ($bottom+2) 120 20 12)
            [void](Add-Text $maySlide '5/13（火・晴れ）' ($x0+$plotWidth*.75-60) ($bottom+2) 120 20 12)
        }
        $geometry+=@{chart=$i+1;left=$x0;plot_width=$plotWidth;top=$top;bottom=$bottom;midnight_x=$x0+$plotWidth/2}
    }
    $weatherSlide=$deck.Slides.FindBySlideID($ids[44])
    foreach($shape in $weatherSlide.Shapes){
        if($shape.HasChart -eq -1){
            $shape.Chart.Axes(1).HasTitle=-1
            $shape.Chart.Axes(1).AxisTitle.Text='時刻 [JST h]'
            $shape.Chart.Axes(1).AxisTitle.Font.Name='Noto Sans JP'
            $shape.Chart.Axes(1).AxisTitle.Font.Size=11
        }
    }
    $deck.SaveAs((Join-Path $buildPath 'native_merge_candidate.pptx'),24)
    $geometry | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $buildPath 'date_axis_geometry.json') -Encoding utf8
    $deck.Close(); $deck=$null
    Write-Output 'Merged 44 editable slides; 18 main slides and 26 hidden appendices.'
} finally {
    if($null -ne $deck){$deck.Close()}
    if($null -ne $app){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}
