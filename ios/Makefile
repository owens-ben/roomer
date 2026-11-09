SCHEME      := Roomer
PROJECT     := Roomer.xcodeproj
SIMULATOR   ?= iPhone 17
DESTINATION := platform=iOS Simulator,name=$(SIMULATOR)

.PHONY: generate open build test clean doctor

generate:
	xcodegen generate

open: generate
	open $(PROJECT)

build: generate
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -destination '$(DESTINATION)' build

test: generate
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -destination '$(DESTINATION)' test

clean:
	rm -rf $(PROJECT) build DerivedData

doctor:
	@xcode-select -p
	@xcodebuild -version
	@xcrun simctl list runtimes | grep -i ios || echo "No iOS simulator runtime installed"
	@security find-identity -v -p codesigning
	@test -f Config/Signing.local.xcconfig && echo "Signing.local.xcconfig: present" || echo "Signing.local.xcconfig: MISSING (see README)"
