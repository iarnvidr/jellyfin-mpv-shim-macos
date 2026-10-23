# Installation, upgrade and recovery (0.2.0 preparation)

This guide describes intended recovery behavior, not a tested release procedure. 0.2.0 is not yet released or qualified. Use only a release artifact whose provenance and integrity you have verified.

## First open

The prototype has been ad-hoc signed; it is not notarized. macOS may show an unidentified-developer warning or require approval. The exact prompt and supported per-app approval route must be observed and documented against the final artifact and OS before release. If macOS blocks opening, use only the applicable **Open Anyway** / per-app Privacy & Security approval for this app if offered, then reopen it. Do not disable Gatekeeper globally, remove quarantine attributes as a general workaround, or treat Sparkle signatures as Apple notarization.

## 0.1.0 to 0.2.0: one-time manual upgrade

The 0.1.0 component updater cannot update the wrapper/native code. The first transition must be a manual download of the complete 0.2.0 app and replacement of the old app; the old updater cannot deliver this migration. Later Sparkle updates are intended to replace the whole app, but are not yet qualified.

Quit the app, retain a copy of the prior app if you need to recover, and install the new complete app using the release-specific instructions. Do not delete user settings or legacy `Library/Application Support/Jellyfin MPV Shim/Updates/` and `Runtimes/` data as part of this upgrade. The intended new launcher ignores those legacy selections and uses its bundled environment; this behavior is pending acceptance testing. Existing connection/settings retention must be verified before release.

## Manual rollback / recovery

No automatic application-health rollback is claimed. Sparkle authenticity validation only checks an update's signature; it does not prove that the new app launches or works. If a new app fails, quit it and manually reinstall a previously retained compatible application from a verified release. Preserve user configuration and legacy runtime folders while diagnosing. If the previous app is unavailable, obtain a verified prior release; do not assume withdrawing an appcast restores an installed application. Feed withdrawal only stops future update offers and must be managed by maintainers.

Before publishing, maintainers must document a tested manual recovery path and retain prior release assets. Do not promise that restoring an older app preserves forward-migrated data until that migration is tested.

## Sparkle signing-key backup (maintainer procedure; setup not claimed)

Release signing requires a private Ed25519 key outside Git, a narrowly scoped GitHub Actions secret for the signing workflow, and a protected recoverable backup. **This repository makes no claim that the key, secret, or backup has been generated or configured.** Before enabling publication:

1. Generate the key using the pinned Sparkle release's documented signing utility on a controlled maintainer machine; capture the matching public key and verify it against a test update.
2. Store the private key only in the authorized GitHub secret store for the protected release workflow. Never commit, attach to an artifact, paste in logs, or place in ordinary workspace backups.
3. Create an encrypted offline backup under maintainer-controlled access, record the recovery custodian/location without recording the key itself, and test restoration in a non-production test feed.
4. Restrict access, document rotation/revocation and incident response, and confirm public key in the app matches the key used for signed archives before release.

Until all steps and an end-to-end packaged update test have evidence, publication/update gates remain pending.
