# Roomer for iOS

A SwiftUI app. The Xcode project is generated from `project.yml` by
[XcodeGen](https://github.com/yonaskolb/XcodeGen), so the `.xcodeproj` is not
committed. That avoids merge conflicts in `project.pbxproj`.

| | |
|---|---|
| Bundle ID | `com.bsowens.roomer` |
| Minimum iOS | 18.0 |
| Devices | iPhone |
| Swift | 6 |

## One-time setup on the build Mac

1. **Install Xcode.** Get it from the Mac App Store, or run
   `xcodes install --latest` (it asks for your Apple ID). It is about 15 GB.
2. **Point the command-line tools at Xcode and accept the license:**
   ```bash
   sudo xcode-select -s /Applications/Xcode.app
   sudo xcodebuild -license accept
   xcodebuild -runFirstLaunch
   xcodebuild -downloadPlatform iOS   # iOS simulator runtime
   ```
3. **Sign in to your developer account in Xcode.** Go to Settings → Accounts →
   +, then Apple ID. Xcode creates your Apple Development certificate the
   first time it signs a build.
4. **Set your Team ID.** Find it at developer.apple.com → Account → Membership details.
   ```bash
   cp Config/Signing.local.xcconfig.example Config/Signing.local.xcconfig
   # edit DEVELOPMENT_TEAM
   ```
5. **Check the setup:** `make doctor`

## Everyday commands

```bash
make open      # generate the project and open it in Xcode
make build     # build for the simulator (SIMULATOR="iPhone 17" to override)
make test
```

Run `make generate` again after adding or removing files or editing `project.yml`.

## TestFlight via Xcode Cloud

Xcode Cloud builds every push that touches `ios/` and sends it to TestFlight.
`ci_scripts/ci_post_clone.sh` installs XcodeGen, writes the team ID, sets the
build number from `CI_BUILD_NUMBER`, and generates the project.

One-time setup, in Xcode with the project open (`make open`):

1. **Integrate → Create Workflow…**, pick the Roomer app. If no App Store
   Connect record exists yet, Xcode offers to create it (bundle ID
   `com.bsowens.roomer`).
2. Grant Xcode Cloud access to the `owens-ben/roomer` GitHub repo when asked.
3. Edit the workflow:
   - **Start Conditions:** Branch Changes → Any Branch; under Files and
     Folders, start only when files in `ios/` change.
   - **Actions:** Archive – iOS, Deployment Preparation: TestFlight (Internal Testing Only).
   - **Post-Actions:** TestFlight Internal Testing → add a group with yourself.
4. Install the TestFlight app on your iPhone and accept the invite.

A build shows up in TestFlight about 10–20 minutes after a push.
