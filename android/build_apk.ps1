# Build KaryaSetu.apk without Gradle, using the Android SDK tools directly.
#   aapt2 (resources) -> javac (compile) -> d8 (dex) -> zip -> zipalign -> apksigner
# Native tools write warnings to stderr, so rely on exit codes, not stream state.
$ErrorActionPreference = "Continue"

$SDK = "$env:LOCALAPPDATA\Android\Sdk"
$BT = "$SDK\build-tools\37.0.0"
$PLATFORM = "$SDK\platforms\android-34\android.jar"
$ROOT = $PSScriptRoot
$OUT = "$ROOT\build"

if (Test-Path $OUT) { Remove-Item -Recurse -Force $OUT }
New-Item -ItemType Directory -Force "$OUT\classes", "$OUT\dex", "$OUT\gen" | Out-Null

Write-Host "[1/7] Compiling resources (aapt2)..."
& "$BT\aapt2.exe" compile --dir "$ROOT\res" -o "$OUT\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

Write-Host "[2/7] Linking base APK (aapt2 link)..."
& "$BT\aapt2.exe" link -o "$OUT\base.apk" -I $PLATFORM `
    --manifest "$ROOT\AndroidManifest.xml" "$OUT\res.zip" `
    --java "$OUT\gen" --min-sdk-version 24 --target-sdk-version 34 --auto-add-overlay
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host "[3/7] Compiling Java..."
$sources = @(Get-ChildItem -Recurse "$ROOT\src" -Filter *.java | ForEach-Object FullName)
$sources += @(Get-ChildItem -Recurse "$OUT\gen" -Filter *.java -ErrorAction SilentlyContinue | ForEach-Object FullName)
$srcArgs = ($sources | ForEach-Object { '"' + $_ + '"' }) -join ' '
cmd /c "javac -source 1.8 -target 1.8 -bootclasspath `"$PLATFORM`" -d `"$OUT\classes`" $srcArgs 2>nul"
if ($LASTEXITCODE -ne 0) {
    Write-Host "      (falling back to --release 11)"
    cmd /c "javac --release 11 -classpath `"$PLATFORM`" -d `"$OUT\classes`" $srcArgs"
    if ($LASTEXITCODE -ne 0) { throw "javac failed" }
}

Write-Host "[4/7] Dexing (d8)..."
$classFiles = @(Get-ChildItem -Recurse "$OUT\classes" -Filter *.class | ForEach-Object FullName)
& "$BT\d8.bat" --release --min-api 24 --lib $PLATFORM --output "$OUT\dex" @classFiles
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host "[5/7] Adding classes.dex to APK..."
python -c @"
import zipfile
with zipfile.ZipFile(r'$OUT\base.apk', 'a', zipfile.ZIP_DEFLATED) as z:
    z.write(r'$OUT\dex\classes.dex', 'classes.dex')
print('  classes.dex added')
"@
if ($LASTEXITCODE -ne 0) { throw "adding dex failed" }

Write-Host "[6/7] Aligning (zipalign)..."
& "$BT\zipalign.exe" -f 4 "$OUT\base.apk" "$OUT\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

Write-Host "[7/7] Signing (apksigner)..."
$KS = "$ROOT\karyasetu.jks"
$KEYTOOL = "C:\Program Files\Java\jdk-25\bin\keytool.exe"
if (-not (Test-Path $KS)) {
    cmd /c "`"$KEYTOOL`" -genkeypair -keystore `"$KS`" -storepass karyasetu123 -keypass karyasetu123 -alias karyasetu -keyalg RSA -keysize 2048 -validity 10000 -dname `"CN=KaryaSetu, O=KaryaSetu`" 2>nul"
    if (-not (Test-Path $KS)) { throw "keystore generation failed" }
}
& "$BT\apksigner.bat" sign --ks $KS --ks-pass pass:karyasetu123 --key-pass pass:karyasetu123 `
    --out "$ROOT\WorkHub.apk" "$OUT\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }

& "$BT\apksigner.bat" verify "$ROOT\WorkHub.apk"
$size = [math]::Round((Get-Item "$ROOT\WorkHub.apk").Length / 1KB)
Write-Host ""
Write-Host "DONE -> $ROOT\WorkHub.apk ($size KB)"
