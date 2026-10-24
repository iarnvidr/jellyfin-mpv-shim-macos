import CryptoKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 4,
      let key = Data(base64Encoded: arguments[1]),
      let signature = Data(base64Encoded: arguments[2]) else { exit(2) }
let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: key)
let archive = try Data(contentsOf: URL(fileURLWithPath: arguments[3]))
guard publicKey.isValidSignature(signature, for: archive) else { exit(1) }
print("Ed25519 signature valid")
