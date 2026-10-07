param([Parameter(Mandatory=$true)][string]$BuildRoot)
$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot 'source_base.pptx'
$destination=Join-Path $BuildRoot 'candidate.pptx'
$before=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$app=$null;$deck=$null
try {
 $app=New-Object -ComObject PowerPoint.Application
 $deck=$app.Presentations.Open([IO.Path]::GetFullPath($source),-1,0,0)
 if($deck.Slides.Count -ne 44){throw 'Expected 44 original slides'}
 $added=$deck.Slides.InsertFromFile([IO.Path]::GetFullPath((Join-Path $BuildRoot 'appendix.pptx')),44,1,12)
 if($added -ne 12 -or $deck.Slides.Count -ne 56){throw 'Weather appendix coverage failed'}
 $deck.SaveAs([IO.Path]::GetFullPath($destination),24)
 if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $before){throw 'Original deck changed'}
 Write-Output '12 weather slides appended through native PowerPoint; source untouched.'
} finally {
 if($null -ne $deck){$deck.Close()}
 if($null -ne $app){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}
