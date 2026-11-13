<#
.SYNOPSIS
  把绿色版游戏目录 + Steam 库快捷方式整理到桌面（可重复运行）

.EXAMPLE
  .\Pin-Games-To-Desktop.ps1
  .\Pin-Games-To-Desktop.ps1 -WhatIf
  .\Pin-Games-To-Desktop.ps1 -Force
#>
[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$DesktopPath = [Environment]::GetFolderPath('Desktop'),
  [string[]]$GreenRoots = @('D:\game', 'E:\game2'),
  [string[]]$SkipTopFolders = @(
    '2026.9.4更新（懒人版一键导入）',
    '3.0.1金手指',
    'ns游戏格式转换工具',
    'nxoptimizer',
    'novel',
    'WeGameApps',
    '博德3Mod-B站-在下夜独 2026.7.26',
    '存档修改器',
    '徽商银行',
    '风灵月影',
    'Lossless.Scaling.v3.1.0.2',
    '修改器',
    'forzahorizon6',
    '英雄联盟',
    'Battle.net'
  ),
  [string[]]$CollectionFolders = @('NSFW'),
  [switch]$IncludeSteam = $true,
  [switch]$IncludeLaunchers = $true,
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 桌面显示名：目录名/原文 -> 中文
$script:NameAliases = @{
  'All Will Fall' = '万物倾颓'
  'Call of Duty HQ' = '使命召唤 HQ'
  'CreatorChronicles' = '创作者编年史'
  'Escape from Duckov' = '逃离鸭科夫'
  'LegendOfHeros' = '三国英雄'
  'LongYinLiZhiZhuan' = '龙吟历之传'
  'Ravenswatch Kintaro' = '乌鸦守望'
  'RuneScape.Dragonwilds.v243922-P2P' = '符文大地：龙野'
  'SED' = '蛮风'
  'Silver Pines' = '银松'
  'Sora No Kiseki the 1st' = '空之轨迹 the 1st'
  'Terraria.v1.4.5.8-P2P' = '泰拉瑞亚'
  'The Adventures of Elliot The Millennium Tales' = '艾略特的千年物语'
  'Valheim' = '英灵神殿'
  'Solo Leveling ARISE OVERDRIVE' = '我独自升级：崛起'
  'StarCraft II' = '星际争霸2'
  'World of Warcraft' = '魔兽世界'
  'Ryujinx' = 'Switch模拟器 Ryujinx'
  'Battle.net' = '战网'
  'オツトメ咲夜さんver1.2' = '女仆咲夜'
  '子産ませ島記録 即産めるメスと繁殖した一年間について 製品版' = '子产岛记录'
  'GAME4733_1.050' = '扶他之家'
  'Orc.Massage.v07.08.2023' = '兽人按摩'
  'hs2' = '恋选2'
  '08' = '欲望模拟器'
  'MAMABOKU' = '妈妈仆'
  'ntr town' = 'NTR小镇'
  '不双修就去世' = '不双修就去世'
  '完美女友PC' = '完美女友'
}

# Steam 库正式名 -> 中文
$script:SteamNameAliases = @{
  'Stardew Valley' = '星露谷物语'
  'Winter Memories' = '冬日回忆'
  'Phantom Blade Zero' = '影之刃零'
  '鬼谷八荒 Tale of Immortal' = '鬼谷八荒'
  '乡村狂想曲' = '乡村狂想曲'
}

function Get-SafeFileName([string]$Name) {
  ($Name -replace '[\\/:*?"<>|]', '_').Trim().TrimEnd('.')
}

function Get-FriendlyName {
  param([string]$Raw, [string]$Prefix = '')
  $leaf = $Raw
  if ($script:NameAliases.ContainsKey($leaf)) {
    $leaf = $script:NameAliases[$leaf]
  }
  elseif ($leaf -match '[\u3040-\u30FF\u31F0-\u31FF]') {
    # 假名目录：无别名时用拼音占位，避免桌面乱码
    $leaf = '日文游戏-' + [Math]::Abs($Raw.GetHashCode()).ToString('x')
  }
  # NSFW 合集前缀改成「成人」
  if ($Prefix -eq 'NSFW') { $Prefix = '成人' }
  if ($Prefix) { return "$Prefix - $leaf" }
  return $leaf
}

function Get-ShortPath([string]$Path) {
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $Path }
  try {
    $fso = New-Object -ComObject Scripting.FileSystemObject
    if (Test-Path -LiteralPath $Path -PathType Container) {
      return $fso.GetFolder($Path).ShortPath
    }
    return $fso.GetFile($Path).ShortPath
  } catch {
    return $Path
  }
}

function New-DesktopShortcut {
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$TargetPath,
    [string]$Arguments = '',
    [string]$WorkingDirectory = '',
    [string]$IconLocation = ''
  )

  if (-not (Test-Path -LiteralPath $TargetPath)) {
    Write-Warning "目标不存在，跳过: $TargetPath"
    return
  }

  $safe = Get-SafeFileName $Name
  if (-not $safe) { return }
  $lnkPath = Join-Path $DesktopPath "$safe.lnk"

  if ((Test-Path -LiteralPath $lnkPath) -and -not $Force) {
    Write-Host "[跳过] 已存在: $safe.lnk"
    return
  }

  # 含日文路径时改用 8.3 短路径，降低快捷方式打不开/白图标概率
  $useShort = $TargetPath -match '[\u3040-\u30FF\u31F0-\u31FF]'
  $resolvedTarget = if ($useShort) { Get-ShortPath $TargetPath } else { $TargetPath }
  if (-not $WorkingDirectory) {
    $WorkingDirectory = Split-Path -Parent $TargetPath
  }
  if ($useShort) {
    $WorkingDirectory = Get-ShortPath $WorkingDirectory
  }
  if (-not $IconLocation) {
    $IconLocation = $resolvedTarget
  }

  if ($PSCmdlet.ShouldProcess($lnkPath, "Shortcut -> $resolvedTarget $Arguments")) {
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($lnkPath)
    $s.TargetPath = $resolvedTarget
    $s.Arguments = $Arguments
    $s.WorkingDirectory = $WorkingDirectory
    $s.IconLocation = $IconLocation
    $s.Save()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) | Out-Null
    Write-Host "[完成] $safe.lnk  ->  $resolvedTarget $Arguments"
  }
}

function Find-MainGameExe {
  param([Parameter(Mandatory)][string]$Folder)

  $skipDir = '(?i)(\\redist\\|\\redistributable\\|\\_commonredist\\|\\directx\\|\\dotnet\\|\\crashreport\\|\\uninstall\\|\\updater\\|\\support\\|\\easyanticheat\\|\\battleye\\|\\__installer\\|\\temp\\|\\cache\\|\\shader\\|\\crashpad\\|\\cef\\|\\webview\\|\\plugins?\\|\\mods?\\|\[modding\]|\\dnspy|\\studio get\\|\\trainer\\|\\cheat\\|\\金手指\\|\\修改器\\|\\风灵月影\\|\\Binaries\\Win64\\|\\\[utility\]\\|\\\[optional\]\\|\\\[modding\])'
  $skipExe = '(?i)^(unins|setup|install|update|crash|report|redis|vcredist|directx|dotnet|unitycrash|easyanticheat|battleye|cefsharp|webview|repair|patcher|downloader|diagnostic|tinydl|ffmpeg|blizzarderror|wowvoiceproxy|blizzardbrowser|codsecure|bootstrapper|sc2 editor|tkeditor|dnspy|studioget|汉化启动)'
  $preferNames = @(
    'honeyselect2.exe', 'initsetting.exe',
    'cod.exe', 'starcraft ii.exe', 'battle.net launcher.exe', 'battle.net.exe',
    'leagueclient.exe', 'world of warcraft launcher.exe', 'wow.exe',
    'terraria.exe', 'valheim.exe', 'ravenswatch.exe', 'rsdragonwilds.exe',
    'elliot.exe', 'sora_1st.exe', 'threekingdom.exe', 'savagewind.exe',
    'duckov.exe', 'ryujinx.exe', 'solo_leveling_arise_overdrive.exe',
    'otutome_sakuya.exe', 'perfectlover.exe', 'orcmassage.exe'
  )

  $exes = @(Get-ChildItem -LiteralPath $Folder -Filter *.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Length -gt 150KB -and
      $_.Name -notmatch $skipExe -and
      ($_.FullName.Substring($Folder.Length) -notmatch $skipDir)
    })

  if ($exes.Count -eq 0) { return $null }

  foreach ($p in $preferNames) {
    $hit = $exes | Where-Object { $_.Name -ieq $p } | Select-Object -First 1
    if ($hit) { return $hit }
  }

  $rootExe = $exes | Where-Object { $_.DirectoryName -eq $Folder } | Sort-Object Length -Descending | Select-Object -First 1
  if ($rootExe) { return $rootExe }

  $folderLeaf = Split-Path $Folder -Leaf
  $byName = $exes | Where-Object {
    $base = $_.BaseName
    $folderLeaf -like "*$base*" -or $base -like "*$folderLeaf*" -or
    ($folderLeaf -replace '\W', '') -like ("*" + ($base -replace '\W', '') + "*")
  } | Sort-Object Length -Descending | Select-Object -First 1
  if ($byName) { return $byName }

  $nonShip = $exes | Where-Object { $_.Name -notmatch '(?i)shipping|studio' } | Sort-Object Length -Descending | Select-Object -First 1
  if ($nonShip) { return $nonShip }

  return ($exes | Sort-Object Length -Descending | Select-Object -First 1)
}

function Add-GreenFolderShortcut {
  param([string]$FolderPath, [string]$RawName, [string]$Prefix = '')

  $display = Get-FriendlyName -Raw $RawName -Prefix $Prefix
  $exe = Find-MainGameExe -Folder $FolderPath
  if (-not $exe) {
    Write-Host "[无EXE] $display ($FolderPath)"
    return
  }
  New-DesktopShortcut -Name $display -TargetPath $exe.FullName -WorkingDirectory $exe.DirectoryName
}

# ---------- 清理旧的易乱码/错误快捷方式 ----------
$stalePatterns = @(
  'NSFW - *',
  'All Will Fall.lnk',
  'Call of Duty HQ.lnk',
  'Creator Chronicles.lnk',
  'Elliot Millennium Tales.lnk',
  'Escape from Duckov.lnk',
  'Legend of Heroes.lnk',
  'Long Yin Li Zhi Zhuan.lnk',
  'Phantom Blade Zero.lnk',
  'Ravenswatch.lnk',
  'RuneScape*',
  'Ryujinx.lnk',
  'Savage Wind.lnk',
  'Silver Pines.lnk',
  'Solo Leveling*',
  'Sora *',
  'StarCraft II.lnk',
  'Stardew Valley.lnk',
  'Terraria.lnk',
  'Valheim.lnk',
  'Winter Memories.lnk',
  'World of Warcraft.lnk',
  'Battle.net.lnk',
  '鬼谷八荒 Tale of Immortal.lnk'
)
foreach ($pat in $stalePatterns) {
  Get-ChildItem -LiteralPath $DesktopPath -Filter $pat -ErrorAction SilentlyContinue | ForEach-Object {
    if ($PSCmdlet.ShouldProcess($_.FullName, 'Remove stale shortcut')) {
      Remove-Item -LiteralPath $_.FullName -Force
      Write-Host "[删除旧项] $($_.Name)"
    }
  }
}

# ---------- 绿色版根目录 ----------
foreach ($root in $GreenRoots) {
  if (-not (Test-Path -LiteralPath $root)) {
    Write-Warning "绿色版目录不存在: $root"
    continue
  }

  Write-Host "`n==== 扫描 $root ===="
  Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $top = $_.Name
    if ($SkipTopFolders -contains $top) {
      Write-Host "[忽略] $top"
      return
    }

    if ($CollectionFolders -contains $top) {
      Write-Host "[合集] $top"
      Get-ChildItem -LiteralPath $_.FullName -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        Add-GreenFolderShortcut -FolderPath $_.FullName -RawName $_.Name -Prefix $top
      }
      return
    }

    Add-GreenFolderShortcut -FolderPath $_.FullName -RawName $top
  }
}

# ---------- 平台启动器 / 特殊路径 ----------
if ($IncludeLaunchers) {
  Write-Host "`n==== 启动器 / 特殊入口 ===="
  $specials = @(
    @{ Name = '战网'; Path = 'E:\game2\Battle.net\Battle.net Launcher.exe' },
    @{ Name = '英雄联盟'; Path = 'E:\game2\WeGameApps\英雄联盟\LeagueClient\LeagueClient.exe' }
  )
  foreach ($s in $specials) {
    if (Test-Path -LiteralPath $s.Path) {
      New-DesktopShortcut -Name $s.Name -TargetPath $s.Path
    }
  }
}

# ---------- Steam ----------
if ($IncludeSteam) {
  Write-Host "`n==== Steam 库 ===="
  $steamPath = $null
  $reg = Get-ItemProperty -Path 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
  if ($reg -and $reg.SteamPath) { $steamPath = $reg.SteamPath }
  if (-not $steamPath) { $steamPath = 'C:\Program Files (x86)\Steam' }

  $steamExe = Join-Path $steamPath 'steam.exe'
  $skipSteamIds = @('228980')
  $skipSteamNames = @('Wallpaper Engine')

  if (-not (Test-Path -LiteralPath $steamExe)) {
    Write-Warning "未找到 steam.exe: $steamExe"
  } else {
    $libs = New-Object System.Collections.Generic.List[string]
    [void]$libs.Add((Join-Path $steamPath 'steamapps'))
    $vdf = Join-Path $steamPath 'steamapps\libraryfolders.vdf'
    if (Test-Path -LiteralPath $vdf) {
      foreach ($line in [IO.File]::ReadAllLines($vdf, [Text.UTF8Encoding]::new($false))) {
        if ($line -match '"path"\s+"([^"]+)"') {
          $p = ($Matches[1] -replace '\\\\', '\')
          $apps = Join-Path $p 'steamapps'
          if (Test-Path -LiteralPath $apps) { [void]$libs.Add($apps) }
        }
      }
    }

    $seen = @{}
    foreach ($lib in ($libs | Select-Object -Unique)) {
      Get-ChildItem -LiteralPath $lib -Filter 'appmanifest_*.acf' -ErrorAction SilentlyContinue | ForEach-Object {
        $txt = [IO.File]::ReadAllText($_.FullName, [Text.UTF8Encoding]::new($false))
        $id = $null; $name = $null
        if ($txt -match '"appid"\s+"(\d+)"') { $id = $Matches[1] }
        if ($txt -match '"name"\s+"([^"]+)"') { $name = $Matches[1] }
        if (-not $id -or -not $name) { return }
        if ($skipSteamIds -contains $id) { return }
        if ($skipSteamNames -contains $name) { return }
        if ($seen.ContainsKey($id)) { return }
        $seen[$id] = $true

        $display = $name
        if ($script:SteamNameAliases.ContainsKey($name)) {
          $display = $script:SteamNameAliases[$name]
        }

        # steam:// 比 -applaunch 更稳（图标仍用 steam.exe，jpg 不能当 .lnk 图标）
        New-DesktopShortcut -Name $display -TargetPath $steamExe `
          -Arguments "steam://rungameid/$id" -WorkingDirectory $steamPath -IconLocation $steamExe
      }
    }
  }
}

Write-Host "`n全部完成。桌面: $DesktopPath"
