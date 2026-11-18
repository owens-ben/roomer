#!/bin/sh
# Xcode Cloud runs this after cloning. The .xcodeproj isn't committed, so
# generate it here, the same way `make generate` does locally.
set -eu

cd "$CI_PRIMARY_REPOSITORY_PATH/ios"

brew install xcodegen

# Signing.local.xcconfig is gitignored; Xcode Cloud needs the team ID.
echo 'DEVELOPMENT_TEAM = SLDFZD6FKW' > Config/Signing.local.xcconfig

# Each TestFlight upload needs a higher build number.
if [ -n "${CI_BUILD_NUMBER:-}" ]; then
  sed -i '' "s/CURRENT_PROJECT_VERSION: \".*\"/CURRENT_PROJECT_VERSION: \"$CI_BUILD_NUMBER\"/" project.yml
fi

xcodegen generate
