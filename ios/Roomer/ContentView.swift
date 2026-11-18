import SwiftUI

struct ContentView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView {
                Label("Roomer", systemImage: "house")
            } description: {
                Text("Know who's in which room.")
            } actions: {
                Text(Self.versionString)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .navigationTitle("Roomer")
        }
    }

    static var versionString: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "Version \(version) (\(build))"
    }
}

#Preview {
    ContentView()
}
