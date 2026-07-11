# Release signing

SysControl supports trusted signing without changing the build scripts. Builds
remain ad-hoc signed when no identity is supplied, which keeps local development
and forks working.

## macOS

1. Install a `Developer ID Application` certificate in the build keychain.
2. Create a notarytool profile once:

   ```bash
   xcrun notarytool store-credentials SysControl-Notary \
     --apple-id you@example.com --team-id TEAMID --password APP_SPECIFIC_PASSWORD
   ```

3. Build with:

   ```bash
   SYSCONTROL_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
   SYSCONTROL_NOTARY_PROFILE="SysControl-Notary" \
   ./swift/build.sh release
   ```

The build signs nested Mach-O files and the app with hardened runtime, submits
the DMG, staples the notarization ticket, and validates it. Release CI should
import the certificate into an ephemeral keychain and create the notary profile
from GitHub Actions secrets before invoking the same command.

## Windows

The PyInstaller output should be Authenticode-signed before it is zipped. Use an
organization-owned code-signing certificate or a managed signing service and
run `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256` against
`dist\\SysControl\\SysControl.exe`. Certificate material must remain in the CI
secret store and should never be committed or embedded in the application.
