// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "rdktr",
    products: [
        .library(name: "Rdktr", targets: ["Rdktr"]),
        .executable(name: "rdktr-cli", targets: ["rdktr-cli"]),
    ],
    targets: [
        .target(name: "CRdktr"),
        .target(name: "Rdktr", dependencies: ["CRdktr"]),
        .executableTarget(name: "rdktr-cli", dependencies: ["Rdktr"]),
        .testTarget(name: "RdktrTests", dependencies: ["Rdktr"]),
    ]
)
