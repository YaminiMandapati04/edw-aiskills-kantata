param([Parameter(Mandatory=$true)][string[]]$Paths)
# Opens each workbook read-only in a separate, hidden Excel instance (the user's open Excel windows are not touched)
# and prints one JSON line per file: whether Excel opened it and whether it had to repair it.
# Excel writes a repair log (error*.xml) to %TEMP% whenever it repairs a file on open; with alerts off, a file that
# needs repair fails to open ("Unable to get the Open property of the Workbooks class").
$ErrorActionPreference = 'Stop'
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.AskToUpdateLinks = $false
$xl.EnableEvents = $false
try {
  # a blank workbook first, so the instance can be put in manual calculation like a user's session where another
  # manual workbook opened first; a file that loads with stale cells there shows them struck through and flagged
  $blank = $xl.Workbooks.Add()
  foreach ($p in $Paths) {
    $xl.Calculation = -4135
    $full = (Resolve-Path -LiteralPath $p).Path
    $before = @(Get-ChildItem $env:TEMP -Filter 'error*.xml' -ErrorAction SilentlyContinue | ForEach-Object FullName)
    $res = [ordered]@{ file = $full; opened = $false; repaired = $false; sheets = $null; log = $null; error = $null; recalc = $null }
    try {
      # UpdateLinks = 0, ReadOnly = true
      $wb = $xl.Workbooks.Open($full, 0, $true)
      $res.opened = $true
      $res.sheets = $wb.Worksheets.Count
      # 0 xlDone: nothing to recalculate; 2 xlPending: Excel holds stale cells (struck through in a manual session)
      $stale = switch ([int]$xl.CalculationState) { 0 { 'none' } 2 { 'stale' } 1 { 'calculating' } default { "$($xl.CalculationState)" } }
      $xl.Calculation = -4105
      $xl.CalculateFull()
      $vals = [ordered]@{}
      foreach ($ws in $wb.Worksheets) {
        try { $fcells = $ws.UsedRange.SpecialCells(-4123) } catch { $fcells = $null }   # xlCellTypeFormulas
        if ($fcells -ne $null) {
          foreach ($c in $fcells.Cells) {
            $v = $c.Value2
            if ($v -is [double] -or $v -is [int]) { $vals[$c.Address($false, $false)] = [double]$v }
            elseif ($v -is [int32]) { $vals[$c.Address($false, $false)] = [double]$v }
            else { $vals[$c.Address($false, $false)] = "$($c.Text)" }
          }
        }
      }
      $res.recalc = [ordered]@{ stale_in_manual_session = $stale; values = $vals }
      $wb.Close($false)
    } catch { $res.error = $_.Exception.Message }
    $after = @(Get-ChildItem $env:TEMP -Filter 'error*.xml' -ErrorAction SilentlyContinue | ForEach-Object FullName)
    $new = @($after | Where-Object { $before -notcontains $_ })
    if ($new.Count -gt 0) { $res.repaired = $true; $res.log = (Get-Content -LiteralPath $new[0] -Raw) }
    [pscustomobject]$res | ConvertTo-Json -Compress -Depth 5
  }
  $blank.Close($false)
} finally {
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  [GC]::Collect()
}
