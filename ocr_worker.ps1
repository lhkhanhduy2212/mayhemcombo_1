# Mayhem Combo - OCR worker (Windows PowerShell 5.1, dung Windows OCR co san trong Windows).
# Giao thuc: moi dong stdin la 1 JSON yeu cau -> moi dong stdout la 1 JSON ket qua.
# Chi chup man hinh (khong dung vao game), chi chay khi app can doc bang chon augment.
param([string]$Lang = 'en-US')

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Send($obj) {
  [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress -Depth 6))
  [Console]::Out.Flush()
}

try {
  Add-Type -AssemblyName System.Drawing
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  Add-Type -Namespace MayhemCombo -Name Native -MemberDefinition @'
[DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
'@
  # Toa do man hinh that (vat ly) o moi muc DPI / scale.
  try { $null = [MayhemCombo.Native]::SetThreadDpiAwarenessContext([IntPtr](-4)) }
  catch { $null = [MayhemCombo.Native]::SetProcessDPIAware() }

  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

  $script:AsTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  } | Select-Object -First 1

  $script:Engine = $null
  try {
    $null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
    $language = New-Object Windows.Globalization.Language($Lang)
    if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) {
      $script:Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    }
  } catch { $script:Engine = $null }
  if ($null -eq $script:Engine) { $script:Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if ($null -eq $script:Engine) {
    Send @{ ok = $false; ready = $false; error = 'no_ocr_language' }
    exit 2
  }
  Send @{ ok = $true; ready = $true; lang = $script:Engine.RecognizerLanguage.LanguageTag; wanted = $Lang }
} catch {
  Send @{ ok = $false; ready = $false; error = $_.Exception.Message }
  exit 1
}

function Await($op, [Type]$type) {
  $task = $script:AsTask.MakeGenericMethod($type).Invoke($null, @($op))
  $null = $task.Wait(5000)
  return $task.Result
}

function Grab([int]$x, [int]$y, [int]$w, [int]$h) {
  $bmp = New-Object System.Drawing.Bitmap($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  try { $g.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h))) }
  finally { $g.Dispose() }
  return $bmp
}

function Scaled($src, [System.Drawing.Rectangle]$rect, [double]$scale) {
  $w = [int][Math]::Max(1, $rect.Width * $scale)
  $h = [int][Math]::Max(1, $rect.Height * $scale)
  $dst = New-Object System.Drawing.Bitmap($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($dst)
  try {
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, $w, $h)), $rect, [System.Drawing.GraphicsUnit]::Pixel)
  } finally { $g.Dispose() }
  return $dst
}

# OCR 1 anh, dua cac dong chu (toa do theo khung game) vao $acc.
function Read-Bitmap($bmp, [double]$scale, [int]$ox, [int]$oy, $acc) {
  $ms = New-Object System.IO.MemoryStream
  $ras = $null; $writer = $null; $sb = $null
  try {
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter($ras.GetOutputStreamAt(0))
    $writer.WriteBytes($ms.ToArray())
    $null = Await ($writer.StoreAsync()) ([UInt32])
    $null = $writer.DetachStream()
    $ras.Seek(0)
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $sb = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($script:Engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    foreach ($l in $res.Lines) {
      $minx = [double]::MaxValue; $miny = [double]::MaxValue; $maxx = 0.0; $maxy = 0.0
      foreach ($wd in $l.Words) {
        $r = $wd.BoundingRect
        if ($r.X -lt $minx) { $minx = $r.X }
        if ($r.Y -lt $miny) { $miny = $r.Y }
        if (($r.X + $r.Width) -gt $maxx) { $maxx = $r.X + $r.Width }
        if (($r.Y + $r.Height) -gt $maxy) { $maxy = $r.Y + $r.Height }
      }
      if ($minx -eq [double]::MaxValue) { continue }
      $null = $acc.Add(@{
          t = [string]$l.Text
          x = [int]($minx / $scale + $ox); y = [int]($miny / $scale + $oy)
          w = [int](($maxx - $minx) / $scale); h = [int](($maxy - $miny) / $scale)
        })
    }
  } finally {
    if ($sb) { $sb.Dispose() }
    if ($writer) { $writer.Dispose() }
    if ($ras) { $ras.Dispose() }
    $ms.Dispose()
  }
}

function Scan($req) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $X = [int]$req.x; $Y = [int]$req.y; $W = [int]$req.w; $H = [int]$req.h
  $acc = New-Object System.Collections.ArrayList
  if ($req.mode -eq 'band') {
    # Ca vung giua man hinh (du phong cho man hinh/bo cuc la).
    $bx = [int]($W * 0.10); $by = [int]($H * 0.18); $bw = [int]($W * 0.80); $bh = [int]($H * 0.58)
    $bmp = Grab ($X + $bx) ($Y + $by) $bw $bh
    try {
      if ($req.save) { try { $bmp.Save([string]$req.save, [System.Drawing.Imaging.ImageFormat]::Png) } catch { } }
      $s = [Math]::Min(1.0, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension / [double][Math]::Max($bw, $bh))
      if ($s -lt 1.0) {
        $img = Scaled $bmp (New-Object System.Drawing.Rectangle(0, 0, $bw, $bh)) $s
        try { Read-Bitmap $img $s $bx $by $acc } finally { $img.Dispose() }
      } else {
        Read-Bitmap $bmp 1.0 $bx $by $acc
      }
    } finally { $bmp.Dispose() }
  } else {
    # 3 tieu de the augment: cac cot cach nhau 0.34*H quanh giua man hinh, tieu de o khoang 0.33H-0.48H.
    # Cat rieng tung tieu de va phong to x2 -> Windows OCR doc chinh xac hon nhieu.
    $top = [int]($H * 0.33); $bot = [int]($H * 0.48); $half = $H * 0.155
    $left = [int][Math]::Max(0, $W / 2 - $H * 0.34 - $half)
    $right = [int][Math]::Min($W, $W / 2 + $H * 0.34 + $half)
    $bmp = Grab ($X + $left) ($Y + $top) ($right - $left) ($bot - $top)
    try {
      if ($req.save) { try { $bmp.Save([string]$req.save, [System.Drawing.Imaging.ImageFormat]::Png) } catch { } }
      foreach ($k in @(-1, 0, 1)) {
        $cx = $W / 2 + $k * $H * 0.34
        $l = [int][Math]::Max($left, $cx - $half)
        $r = [int][Math]::Min($right, $cx + $half)
        if ($r -le $l) { continue }
        $rect = New-Object System.Drawing.Rectangle(($l - $left), 0, ($r - $l), ($bot - $top))
        $img = Scaled $bmp $rect 2.0
        try { Read-Bitmap $img 2.0 $l $top $acc } finally { $img.Dispose() }
      }
    } finally { $bmp.Dispose() }
  }
  return @{ ok = $true; mode = [string]$req.mode; ms = [int]$sw.ElapsedMilliseconds; lines = $acc.ToArray() }
}

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  if ($line.Trim().Length -eq 0) { continue }
  try {
    $req = $line | ConvertFrom-Json
    if ($req.cmd -eq 'quit') { break }
    elseif ($req.cmd -eq 'ping') { Send @{ ok = $true; pong = $true } }
    elseif ($req.cmd -eq 'scan') { Send (Scan $req) }
    else { Send @{ ok = $false; error = 'unknown_cmd' } }
  } catch {
    Send @{ ok = $false; error = $_.Exception.Message }
  }
}
