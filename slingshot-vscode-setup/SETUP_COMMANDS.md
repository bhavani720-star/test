# Sapient Slingshot 3.4 in VS Code: setup commands

Run every command in the **VS Code terminal** (PowerShell): menu **Terminal > New Terminal**, with your project folder open.
The full guide, with what to expect and fixes for common errors, is in `Slingshot_3.4_VSCode_Setup_Steps.docx` in this folder.

## Step 1. Check Node.js and npm

```powershell
node -v; npm -v
```

Expected: two version numbers (for example `v26.13.0` and `11.20.0`).

## Step 2. Slingshot extension 3.4.0

In **Extensions**, find **Sapient Slingshot** (Publicis-Sapient) > gear > **Install Specific Version...** > **3.4.0**.
Keep **Auto Update** unticked and do not click **Update to v3.6.1**. Check:

```powershell
code --list-extensions --show-versions | Select-String -Pattern slingshot
```

Expected: `publicis-sapient.slingshot@3.4.0`

## Step 3. JFrog identity token

1. In Edge open `https://artifactory.lseg.com/ui/user_profile`.
2. Note your **JFrog username** at the top (**User Profile: ...**). It is not your email.
3. **Authentication Settings > Generate an Identity Token**, then copy the **Reference Token** (starts with `cmVm`), not the Token ID.

## Steps 4-5. Write .npmrc and test Artifactory

Check the LSEG certificate file is there (should say `True`):

```powershell
Test-Path "$HOME\winroots.pem"
```

Optional: back up an existing `.npmrc` first:

```powershell
Copy-Item "$HOME\.npmrc" "$HOME\.npmrc.bak"
```

Write `.npmrc` (one line). At **JFrog username** type your username and press Enter; at **Paste the JFrog Reference Token** right-click to paste the token (it stays hidden) and press Enter:

```powershell
$u = Read-Host "JFrog username"; $s = Read-Host "Paste the JFrog Reference Token" -AsSecureString; $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); $t = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b); $a = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${u}:$t")); Remove-Variable t, s, b; $r = "//artifactory.lseg.com/artifactory/api/npm/npm-registry-remote/"; $ca = ("$HOME\winroots.pem" -replace '\\', '/'); Set-Content "$HOME\.npmrc" -Encoding ascii -Value @("registry=https:$r", "${r}:_auth=$a", "${r}:always-auth=true", "cafile=$ca"); Remove-Variable a; npm view express version
```

Expected: a harmless warning `npm warn Unknown user config "always-auth"`, then a version number such as `5.3.0`.

Check any time (does not show the token):

```powershell
Test-Path "$HOME\winroots.pem"; ".npmrc size: " + (Get-Item "$HOME\.npmrc").Length + " bytes"; npm config get registry; npm view express version
```

Note: this uses `cafile=...winroots.pem` instead of `strict-ssl=false`, so npm's certificate checks stay on.

## Step 6. .slingshot.config.js in the project root

Download the config file from the team's Teams message. Teams saves it as `slingshot.config.js` (no leading dot). Copy it into the project root **with** the dot:

```powershell
Copy-Item "$HOME\Downloads\slingshot.config.js" ".\.slingshot.config.js"
```

```powershell
Get-ChildItem -Force .slingshot.config.js | Select-Object Name, Length, LastWriteTime
```

Expected: `.slingshot.config.js`, 549 bytes.

## Step 7. Sign in to Slingshot

1. **Accounts** icon (bottom of the left bar) > **Sign in with Publicis Sapient to use Sapient Slingshot**.
2. **Do you want Code to open the external website?** > **Open**.
3. Edge: the Slingshot login page and Microsoft single sign-on go through; **Authentication Successful** > close the tab.
4. Back in VS Code: **Select Project** > **SFI POC** > **Continue**.
5. The Slingshot panel says **Successfully signed in to Publicis Sapient**.

## If something goes wrong

| What you see | What to do |
|---|---|
| `E401 Incorrect or missing password` | Use the JFrog username (not the email) and the Reference Token (not the Token ID). Run the steps 4-5 command again. |
| `PtrToStringAuth` error | Windows PowerShell 5.1: use the command above (it uses `PtrToStringBSTR`). |
| npm still goes to `registry.npmjs.org` | `.npmrc` was not written to your home folder. Run the steps 4-5 command again. |
| Certificate errors | Check `winroots.pem` exists and the `cafile` line is in `.npmrc`; then ask the team. |
| `Failed to get AI Provider List response from API` | You are not signed in yet. Do step 7. |
| Text in the terminal looks jumbled | Press Esc, run `cls`, paste the command again. |

Keep the token secret: paste it only at the hidden prompt, never in notes, chats or screenshots. If it was exposed, revoke it in JFrog (**User Profile > Identity Tokens**, revoke (x) on its row) and make a new one.
