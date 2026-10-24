#import <AppKit/AppKit.h>
#import <Sparkle/Sparkle.h>

// Test-only user driver: take the same Install / Relaunch actions as the UI.
// The released host application and Sparkle's installer remain unmodified.
@interface Driver : NSObject <SPUUserDriver, SPUUpdaterDelegate>
@property(nonatomic, copy) NSString *feed;
@property(nonatomic) BOOL probe;
@property(nonatomic) BOOL legacy;
@property(nonatomic, strong) SPUUpdater *updater;
@end
@implementation Driver
- (NSString *)feedURLStringForUpdater:(SPUUpdater *)updater { return self.feed; }
- (void)updater:(SPUUpdater *)updater didFindValidUpdate:(SUAppcastItem *)item {
    fprintf(stderr, "FOUND %s\n", item.versionString.UTF8String);
    if (self.probe) exit(0);
}
- (void)updater:(SPUUpdater *)updater didFinishUpdateCycleForUpdateCheck:(SPUUpdateCheck)check error:(NSError *)error {
    if (error) { fprintf(stderr, "FAILED %s\n", error.description.UTF8String); exit(1); }
}
- (BOOL)updater:(SPUUpdater *)updater shouldDownloadReleaseNotesForUpdate:(SUAppcastItem *)item { return NO; }
- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest *)request reply:(void (^)(SUUpdatePermissionResponse *))reply {
    reply([[SUUpdatePermissionResponse alloc] initWithAutomaticUpdateChecks:NO sendSystemProfile:NO]);
}
- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation {}
- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem *)item state:(SPUUserUpdateState *)state reply:(void (^)(SPUUserUpdateChoice))reply {
    reply(SPUUserUpdateChoiceInstall);
}
- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData *)data {}
- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError *)error {}
- (void)showUpdateNotFoundWithError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    fprintf(stderr, "NO UPDATE %s\n", error.description.UTF8String); exit(1);
}
- (void)showUpdaterError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    fprintf(stderr, "UPDATE ERROR %s\n", error.description.UTF8String); exit(1);
}
- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation { fprintf(stderr, "DOWNLOAD\n"); }
- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)length {}
- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {}
- (void)showDownloadDidStartExtractingUpdate { fprintf(stderr, "EXTRACT\n"); }
- (void)showExtractionReceivedProgress:(double)progress {}
- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply { reply(SPUUserUpdateChoiceInstall); }
- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)terminated retryTerminatingApplication:(void (^)(void))retry {
    fprintf(stderr, "INSTALL applicationTerminated=%d\n", terminated);
}
- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched acknowledgement:(void (^)(void))acknowledgement {
    fprintf(stderr, "INSTALLED relaunched=%d\n", relaunched); acknowledgement(); exit(relaunched || self.legacy ? 0 : 1);
}
- (void)dismissUpdateInstallation {}
- (void)showUpdateInFocus {}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 3) return 2;
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        static Driver *driver;
        driver = [Driver new];
        driver.feed = [NSString stringWithUTF8String:argv[2]];
        driver.probe = argc == 4 && strcmp(argv[3], "probe") == 0;
        driver.legacy = argc == 4 && strcmp(argv[3], "legacy") == 0;
        NSBundle *host = [NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]];
        driver.updater = [[SPUUpdater alloc] initWithHostBundle:host applicationBundle:host userDriver:driver delegate:driver];
        NSError *error = nil;
        if (![driver.updater startUpdater:&error]) {
            fprintf(stderr, "START ERROR %s\n", error.description.UTF8String); return 1;
        }
        if (driver.probe) [driver.updater checkForUpdateInformation];
        else [driver.updater checkForUpdates];
        [NSApp run];
    }
}
