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

## Before the first TestFlight build

- In App Store Connect, go to Apps → + and create the app with bundle ID
  `com.bsowens.roomer`. With automatic signing, Xcode registers the App ID
  on the first build.
- Add a 1024×1024 icon to `Roomer/Assets.xcassets/AppIcon.appiconset`.
- To archive and upload, use Product → Archive in Xcode. Fastlane or Xcode
  Cloud can be added once the app does something worth shipping.
