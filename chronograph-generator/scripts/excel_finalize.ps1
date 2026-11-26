param([Parameter(Mandatory=$true)][string]$Src, [Parameter(Mandatory=$true)][string]$Dst)
# Has Excel itself recalculate and save the workbook, in a separate hidden instance (the user's Excel windows are
# not touched). A file written by another program is treated by Excel as needing recalculation: in a manual-calculation
# session every formula then shows as a stale value (struck through, flagged) even when its stored result is right.
# A file Excel has calculated and saved loads clean. Prints one JSON line.
$ErrorActionPreference = 'Stop'
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.AskToUpdateLinks = $false
$xl.EnableEvents = $false
$res = [ordered]@{ saved = $false; error = $null }
try {
  $wb = $xl.Workbooks.Open((Resolve-Path -LiteralPath $Src).Path, 0, $false)
  $xl.Calculation = -4105            # automatic
  $xl.CalculateFull()
  $wb.SaveAs($Dst, 51)               # xlOpenXMLWorkbook (.xlsx)
  $wb.Close($false)
  $res.saved = $true
} catch { $res.error = $_.Exception.Message }
finally {
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  [GC]::Collect()
}
[pscustomobject]$res | ConvertTo-Json -Compress
