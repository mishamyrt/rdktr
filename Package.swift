// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "rdktr",
    products: [
        .library(name: "Rdktr", targets: ["Rdktr"]),
    ],
    targets: [
        .target(
            name: "CRdktr",
            path: "core",
            exclude: ["tests"],
            sources: ["src"],
            publicHeadersPath: "include"
        ),
        .target(
            name: "Rdktr",
            dependencies: ["CRdktr"],
            path: "bindings/swift/Rdktr"
        ),
        .testTarget(
            name: "RdktrTests",
            dependencies: ["Rdktr"],
            path: "bindings/swift/RdktrTests"
        ),
    ]
)
