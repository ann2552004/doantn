$ErrorActionPreference = 'Stop'

$srcDir = 'C:\do an\bieu_do_vsl_giong_Hoan_dung_ten_svg (1)'
$outDir = 'C:\do an\bieu_do_usecase_tu_tuan_tu_excalidraw'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function U([int[]]$codes) {
    return -join ($codes | ForEach-Object { [char]$_ })
}

function Normalize([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace '\r?\n', ' '
    $s = [regex]::Replace($s, '\s*\|\s*', ' ')
    $s = [regex]::Replace($s, '\s+', ' ')
    return $s.Trim()
}

function Wrap-Text([string]$text, [int]$maxChars) {
    $words = (Normalize $text) -split ' '
    $lines = New-Object System.Collections.Generic.List[string]
    $line = ''
    foreach ($word in $words) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            $line = $word
        } elseif (($line.Length + 1 + $word.Length) -le $maxChars) {
            $line += ' ' + $word
        } else {
            $lines.Add($line)
            $line = $word
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($line)) { $lines.Add($line) }
    if ($lines.Count -eq 0) { $lines.Add('') }
    return @($lines)
}

function New-Element([string]$id, [string]$type, [double]$x, [double]$y, [double]$w, [double]$h) {
    return [ordered]@{
        id = $id
        type = $type
        x = $x
        y = $y
        width = $w
        height = $h
        angle = 0
        backgroundColor = 'transparent'
        strokeColor = '#000000'
        strokeWidth = 1
        strokeStyle = 'solid'
        roughness = 0
        opacity = 100
        groupIds = @()
        frameId = $null
        index = $null
        roundness = $null
        seed = (Get-Random -Minimum 100000 -Maximum 999999)
        version = 1
        versionNonce = (Get-Random -Minimum 100000 -Maximum 999999)
        isDeleted = $false
        boundElements = @()
        updated = [int][double]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
        link = $null
        locked = $false
        fillStyle = 'solid'
    }
}

function New-Shape([string]$id, [string]$type, [double]$x, [double]$y, [double]$w, [double]$h, [string]$fill) {
    $e = New-Element $id $type $x $y $w $h
    $e.backgroundColor = $fill
    $e.roundness = $null
    return $e
}

function New-Text([string]$id, [double]$x, [double]$y, [string]$text, [int]$fontSize, [int]$maxChars) {
    $lines = Wrap-Text $text $maxChars
    $joined = $lines -join "`n"
    $w = [math]::Max(65, [math]::Min(280, ($lines | Measure-Object -Property Length -Maximum).Maximum * ($fontSize * 0.53) + 8))
    $h = [math]::Max(18, $lines.Count * ($fontSize * 1.25))
    $e = New-Element $id 'text' $x $y $w $h
    $e.backgroundColor = 'transparent'
    $e.strokeWidth = 2
    $e.text = $joined
    $e.fontSize = $fontSize
    $e.fontFamily = 2
    $e.textAlign = 'left'
    $e.verticalAlign = 'top'
    $e.containerId = $null
    $e.originalText = $joined
    $e.autoResize = $false
    $e.lineHeight = 1.25
    return $e
}

function Add-CenteredText($elements, [string]$id, [double]$cx, [double]$cy, [string]$text, [int]$fontSize, [int]$maxChars) {
    $e = New-Text $id 0 0 $text $fontSize $maxChars
    $e.x = $cx - ($e.width / 2)
    $e.y = $cy - ($e.height / 2)
    $elements.Add($e)
}

function Add-Line($elements, [string]$id, [double]$x1, [double]$y1, [double]$x2, [double]$y2, [string]$type) {
    $e = New-Element $id $type $x1 $y1 ($x2 - $x1) ($y2 - $y1)
    $e.points = @(@(0, 0), @($x2 - $x1, $y2 - $y1))
    $e.backgroundColor = 'transparent'
    $e.startArrowhead = $null
    $e.endArrowhead = $null
    $e.startBinding = $null
    $e.endBinding = $null
    $elements.Add($e)
}

function Add-Actor($elements, [string]$label, [double]$cx, [double]$cy) {
    $head = New-Shape 'actor-head' 'ellipse' ($cx - 16) ($cy - 58) 32 32 '#ffffff'
    $elements.Add($head)
    Add-Line $elements 'actor-body' $cx ($cy - 26) $cx ($cy + 28) 'line'
    Add-Line $elements 'actor-arms' ($cx - 34) ($cy - 8) ($cx + 34) ($cy - 8) 'line'
    Add-Line $elements 'actor-left-leg' $cx ($cy + 28) ($cx - 26) ($cy + 72) 'line'
    Add-Line $elements 'actor-right-leg' $cx ($cy + 28) ($cx + 26) ($cy + 72) 'line'
    $labelEl = New-Text 'actor-label' ($cx - 70) ($cy + 84) $label 15 20
    $labelEl.width = [math]::Max(120, $labelEl.width)
    $labelEl.x = $cx - ($labelEl.width / 2)
    $elements.Add($labelEl)
}

function Add-BoundArrow($elements, $root, $child, [string]$id, [string]$labelId) {
    $rx = $root.x + ($root.width / 2)
    $ry = $root.y + ($root.height / 2)
    $cx = $child.x + ($child.width / 2)
    $cy = $child.y + ($child.height / 2)
    $dx = $cx - $rx
    $dy = $cy - $ry
    $a = New-Element $id 'arrow' $rx $ry $dx $dy
    $a.points = @(@(0, 0), @($dx, $dy))
    $a.backgroundColor = 'transparent'
    $a.strokeStyle = 'dashed'
    $a.endArrowhead = 'arrow'
    $a.startArrowhead = $null
    $a.startBinding = [ordered]@{ elementId = $root.id; focus = 0; gap = 8 }
    $a.endBinding = [ordered]@{ elementId = $child.id; focus = 0; gap = 8 }
    $elements.Add($a)
    $root.boundElements += [ordered]@{ id = $id; type = 'arrow' }
    $child.boundElements += [ordered]@{ id = $id; type = 'arrow' }
    $lx = $rx + ($dx * 0.52) - 33
    $ly = $ry + ($dy * 0.52) - 10
    $labelEl = New-Text $labelId $lx $ly '<<include>>' 12 20
    $labelEl.width = 66
    $elements.Add($labelEl)
}

$admin = U @(0x0051,0x0075,0x1EA3,0x006E,0x0020,0x0074,0x0072,0x1ECB,0x0020,0x0076,0x0069,0x00EA,0x006E)
$nha = U @(0x004E,0x0068,0x00E0)
$participantCounts = @{
    'hinh_2_16' = 5; 'hinh_2_17' = 5; 'hinh_2_18' = 5; 'hinh_2_19' = 5; 'hinh_2_20' = 5
    'hinh_2_21' = 5; 'hinh_2_22' = 5; 'hinh_2_23' = 6; 'hinh_2_24' = 5; 'hinh_2_25' = 7
}

$files = @(Get-ChildItem -LiteralPath $srcDir -Filter '*tuan_tu*.svg' | Sort-Object Name)
$manifest = New-Object System.Collections.Generic.List[string]

foreach ($file in $files) {
    $key = ($file.BaseName -replace '_tuan_tu.*$', '')
    $xml = [xml](Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8)
    $texts = New-Object System.Collections.Generic.List[string]
    foreach ($node in $xml.SelectNodes("//*[local-name()='text']")) {
        $v = Normalize $node.InnerText
        if (-not [string]::IsNullOrWhiteSpace($v) -and -not $texts.Contains($v)) { $texts.Add($v) }
    }
    if ($texts.Count -lt 3) { continue }
    $titleSource = $texts[0]
    $participantCount = [int]$participantCounts[$key]
    $participants = @($texts | Select-Object -Skip 1 -First $participantCount)
    $messages = @($texts | Select-Object -Skip (1 + $participantCount))
    $messages = @($messages | ForEach-Object { Normalize $_ } | Where-Object { $_ } | Select-Object -Unique)
    if ($messages.Count -eq 0) { continue }

    $titleParts = $titleSource -split '\.', 2
    $figure = $titleParts[0]
    $tailWords = @($titleSource -split ' ' | Select-Object -Last 2)
    $rootLabel = ($tailWords -join ' ').Trim()
    if ($rootLabel.Length -gt 0) { $rootLabel = $rootLabel.Substring(0,1).ToUpperInvariant() + $rootLabel.Substring(1) }
    if ($key -eq 'hinh_2_17') { $rootLabel = $rootLabel -replace 'Video/camera','Nguồn video/camera' }
    if ($key -eq 'hinh_2_20') { $rootLabel = $rootLabel -replace '^Đo tốc độ$','Đo tốc độ phương tiện' }
    if ($key -eq 'hinh_2_21') { $rootLabel = $rootLabel -replace '^Tính VSL$','Tính tốc độ VSL' }
    if ($key -eq 'hinh_2_25') { $rootLabel = $rootLabel -replace '^Nhiều camera$','Quản lý nhiều camera' }
    $role = if ($key -eq 'hinh_2_16') { $admin } else { $nha + ' vận hành' }

    $cols = if ($messages.Count -ge 9) { 5 } elseif ($messages.Count -ge 7) { 4 } else { 3 }
    $rows = [math]::Ceiling($messages.Count / [double]$cols)
    $cardW = 280
    $gap = 62
    $canvasW = [math]::Max(1800, ($cols * $cardW) + (($cols - 1) * $gap) + 360)
    $canvasH = 980
    $rootW = 320
    $rootH = 96
    $rootX = ($canvasW - $rootW) / 2
    $rootY = 430
    $root = New-Shape 'root' 'ellipse' $rootX $rootY $rootW $rootH '#ffffff'
    $elements = New-Object System.Collections.Generic.List[object]
    $bg = New-Shape 'background' 'rectangle' 0 0 $canvasW $canvasH '#ffffff'
    $bg.strokeColor = '#ffffff'; $bg.strokeWidth = 0
    $elements.Add($bg)
    $title = New-Text 'title' 0 28 ($figure + ' - UML use case: ' + $rootLabel) 20 80
    $title.x = ($canvasW - $title.width) / 2
    $elements.Add($title)
    $elements.Add($root)
    Add-CenteredText $elements 'root-label' ($rootX + $rootW/2) ($rootY + $rootH/2) $rootLabel 17 25

    $actorCx = [math]::Max(90, $rootX - 105)
    $actorCy = $rootY + ($rootH / 2)
    Add-Actor $elements $role $actorCx $actorCy
    $actorArrow = New-Element 'actor-to-root' 'arrow' ($actorCx + 38) $actorCy ($rootX - 10 - ($actorCx + 38)) 0
    $actorArrow.points = @(@(0,0), @($actorArrow.width,0))
    $actorArrow.backgroundColor = 'transparent'; $actorArrow.endArrowhead = 'arrow'; $actorArrow.startArrowhead = $null
    $elements.Add($actorArrow)

    $topCount = [math]::Ceiling($messages.Count / 2.0)
    $rowY = @(130, 730)
    for ($i = 0; $i -lt $messages.Count; $i++) {
        $row = if ($i -lt $topCount) { 0 } else { 1 }
        $col = if ($row -eq 0) { $i } else { $i - $topCount }
        $rowCount = if ($row -eq 0) { $topCount } else { $messages.Count - $topCount }
        $totalRowW = ($rowCount * $cardW) + (($rowCount - 1) * $gap)
        $left = ($canvasW - $totalRowW) / 2
        $lines = Wrap-Text $messages[$i] 25
        $h = [math]::Max(86, ($lines.Count * 23) + 28)
        $x = $left + ($col * ($cardW + $gap))
        $child = New-Shape ('child-' + $i) 'ellipse' $x $rowY[$row] $cardW $h '#ffffff'
        $elements.Add($child)
        Add-CenteredText $elements ('child-' + $i + '-label') ($x + $cardW/2) ($rowY[$row] + $h/2) $messages[$i] 17 25
        Add-BoundArrow $elements $root $child ('include-child-' + $i) ('include-label-child-' + $i)
    }

    $doc = [ordered]@{
        type = 'excalidraw'
        version = 2
        source = 'mcp-excalidraw-server'
        elements = @($elements)
        appState = [ordered]@{ viewBackgroundColor = '#ffffff'; gridSize = $null; zoom = [ordered]@{ value = 1 }; scrollX = 0; scrollY = 0 }
        files = [ordered]@{}
    }
    $safeName = $file.BaseName -replace '_tuan_tu_', '_usecase_'
    $outFile = Join-Path $outDir ($safeName + '.excalidraw')
    $json = $doc | ConvertTo-Json -Depth 50
    [System.IO.File]::WriteAllText($outFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    $manifest.Add(($safeName + '.excalidraw | ' + $titleSource + ' | actor=' + $role + ' | includes=' + $messages.Count))
}

$readme = @(
    'UML USE CASE CONVERTED FROM SEQUENCE DIAGRAMS',
    '==============================================',
    '',
    'Source: ' + $srcDir,
    'Output: ' + $outDir,
    'Scope: all SVG files whose name contains tuan_tu (10 diagrams, Hinh 2.16-2.25).',
    '',
    'Design decisions:',
    '- Converted each sequence diagram into one root use case plus included functional use cases.',
    '- Actors are compact stick figures; the login diagram uses the administrator role, the remaining diagrams use the operator role.',
    '- White ellipse nodes, black 1px borders, clean Helvetica-like Excalidraw font, no hand-drawn roughness or shadows.',
    '- Include relationships use dashed arrows with free-standing <<include>> labels to keep typography consistent.',
    '- Original SVG files were not modified.',
    '',
    'Generated files:'
) + @($manifest)
[System.IO.File]::WriteAllLines((Join-Path $outDir 'README.txt'), $readme, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ('Generated ' + $manifest.Count + ' diagrams in ' + $outDir)
