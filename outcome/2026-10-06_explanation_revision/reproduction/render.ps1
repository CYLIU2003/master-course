param([Parameter(Mandatory=$true)][string]$Pptx,[Parameter(Mandatory=$true)][string]$RenderDir,[string]$Pdf)
$ErrorActionPreference='Stop'
$app=$null;$deck=$null
New-Item -ItemType Directory -Path $RenderDir -Force | Out-Null
try {
 $app=New-Object -ComObject PowerPoint.Application
 $before=(Get-FileHash -LiteralPath $Pptx -Algorithm SHA256).Hash
 $deck=$app.Presentations.Open([IO.Path]::GetFullPath($Pptx),-1,0,0)
 if($deck.Slides.Count -ne 44){throw 'Slide count changed'}
 for($i=1;$i -le $deck.Slides.Count;$i++){
  $deck.Slides.Item($i).Export((Join-Path $RenderDir "slide-$i.png"),'PNG',1280,720)
 }
 if($Pdf){
  if(Test-Path -LiteralPath $Pdf){throw 'PDF destination already exists; use a new output path'}
  $deck.SaveAs([IO.Path]::GetFullPath($Pdf),32)
 }
 if((Get-FileHash -LiteralPath $Pptx -Algorithm SHA256).Hash -ne $before){throw 'Source changed during export'}
 Write-Output 'Native PowerPoint opened and rendered all 44 slides.'
} finally {
 if($null -ne $deck){$deck.Close()}
 if($null -ne $app){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}
