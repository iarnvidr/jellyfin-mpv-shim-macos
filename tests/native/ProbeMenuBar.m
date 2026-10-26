// Diagnostic only: observe AppKit state without changing menu visibility.
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <unistd.h>

static NSDictionary *appIdentity(NSRunningApplication *app) {
    if (!app) return @{};
    return @{@"pid": @(app.processIdentifier), @"name": app.localizedName ?: @"",
        @"bundle": app.bundleIdentifier ?: @"", @"active": @(app.active),
        @"policy": @(app.activationPolicy), @"hidden": @(app.hidden)};
}

static NSDictionary *desktopState(void) {
    NSMutableArray *apps = [NSMutableArray array];
    for (NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
        if ([app.bundleIdentifier hasPrefix:@"org.jellyfin.mpvshim"]) [apps addObject:appIdentity(app)];
    }
    NSArray *windows = CFBridgingRelease(CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID));
    NSMutableArray *bars = [NSMutableArray array];
    for (NSDictionary *window in windows) {
        int level = [window[(id)kCGWindowLayer] intValue];
        if (level == CGWindowLevelForKey(kCGMainMenuWindowLevelKey) || level == CGWindowLevelForKey(kCGStatusWindowLevelKey)) {
            [bars addObject:window];
        }
    }
    return @{@"time": @(NSDate.date.timeIntervalSince1970),
        @"frontmost": appIdentity(NSWorkspace.sharedWorkspace.frontmostApplication),
        @"jellyfinProcesses": apps, @"onScreenMenuWindows": bars ?: @[],
        @"accessibilityTrusted": @(AXIsProcessTrusted()),
        @"screenRecordingAllowed": @(CGPreflightScreenCaptureAccess()),
        @"globalAutoHideMenuBar": [NSUserDefaults.standardUserDefaults objectForKey:@"_HIHideMenuBar"] ?: NSNull.null};
}

static void emitRecord(NSDictionary *record, NSString *path) {
    NSData *json = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:nil];
    if (!json) return;
    NSMutableData *line = [json mutableCopy];
    [line appendBytes:"\n" length:1];
    if (path) {
        if (![NSFileManager.defaultManager fileExistsAtPath:path]) [NSData.data writeToFile:path atomically:YES];
        NSFileHandle *file = [NSFileHandle fileHandleForWritingAtPath:path];
        [file seekToEndOfFile]; [file writeData:line]; [file closeFile];
    } else { [NSFileHandle.fileHandleWithStandardOutput writeData:line]; }
}

#ifdef PROBE_STANDALONE
static NSString *axText(AXUIElementRef element, CFStringRef attribute) {
    CFTypeRef value = NULL;
    if (AXUIElementCopyAttributeValue(element, attribute, &value) != kAXErrorSuccess) return @"";
    id object = CFBridgingRelease(value);
    return [object isKindOfClass:NSString.class] ? object : @"";
}

static void axNodes(AXUIElementRef element, NSMutableArray *nodes, int depth) {
    if (depth > 8 || nodes.count > 1000) return;
    [nodes addObject:(__bridge id)element];
    CFTypeRef children = NULL;
    if (AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &children) != kAXErrorSuccess) return;
    for (id child in CFBridgingRelease(children)) axNodes((__bridge AXUIElementRef)child, nodes, depth + 1);
}

static void dismissLocalNetworkPrompt(void) {
    for (NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
        AXUIElementRef root = AXUIElementCreateApplication(app.processIdentifier);
        CFTypeRef windows = NULL;
        AXError result = AXUIElementCopyAttributeValue(root, kAXWindowsAttribute, &windows);
        CFRelease(root);
        if (result != kAXErrorSuccess) continue;
        for (id window in CFBridgingRelease(windows)) {
            NSMutableArray *nodes = [NSMutableArray array];
            axNodes((__bridge AXUIElementRef)window, nodes, 0);
            NSMutableString *text = [NSMutableString string];
            for (id node in nodes) {
                AXUIElementRef element = (__bridge AXUIElementRef)node;
                [text appendFormat:@" %@ %@ %@", axText(element, kAXTitleAttribute),
                    axText(element, kAXDescriptionAttribute), axText(element, kAXValueAttribute)];
            }
            if ([text rangeOfString:@"local network" options:NSCaseInsensitiveSearch].location == NSNotFound) continue;
            for (id node in nodes) {
                AXUIElementRef element = (__bridge AXUIElementRef)node;
                NSString *title = axText(element, kAXTitleAttribute);
                if ([title isEqualToString:@"Don’t Allow"] || [title isEqualToString:@"Don't Allow"]) {
                    AXError pressed = AXUIElementPerformAction(element, kAXPressAction);
                    emitRecord(@{@"localNetworkPrompt": @"dismissed", @"axResult": @(pressed)}, nil);
                    return;
                }
            }
        }
    }
    emitRecord(@{@"localNetworkPrompt": @"not-found"}, nil);
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc > 1 && strcmp(argv[1], "--dismiss-local-network") == 0) {
            dismissLocalNetworkPrompt();
        } else if (argc > 1) {
            NSRunningApplication *app = [NSRunningApplication runningApplicationWithProcessIdentifier:atoi(argv[1])];
            BOOL activated = [app activateWithOptions:NSApplicationActivateIgnoringOtherApps];
            [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:2]];
            NSMutableDictionary *record = [desktopState() mutableCopy];
            record[@"activationAccepted"] = @(activated);
            record[@"requestedPID"] = @(atoi(argv[1]));
            emitRecord(record, nil);
        } else { emitRecord(desktopState(), nil); }
    }
    return 0;
}
#else
__attribute__((constructor)) static void installMenuBarProbe(void) {
    NSString *path = NSProcessInfo.processInfo.environment[@"JELLYFIN_MENU_PROBE_OUTPUT"];
    if (!path) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        NSTimer *timer = [NSTimer timerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) {
            NSMutableDictionary *record = [desktopState() mutableCopy];
            record[@"pid"] = @(getpid());
            record[@"policy"] = @(NSApp.activationPolicy);
            record[@"active"] = @(NSApp.active);
            record[@"menuBarVisible"] = @(NSMenu.menuBarVisible);
            record[@"presentationOptions"] = @(NSApp.presentationOptions);
            record[@"systemPresentationOptions"] = @(NSApp.currentSystemPresentationOptions);
            record[@"menus"] = [NSApp.mainMenu.itemArray valueForKey:@"title"] ?: @[];
            NSMutableArray *windows = [NSMutableArray array];
            for (NSWindow *window in NSApp.windows) {
                [windows addObject:@{@"title": window.title ?: @"", @"visible": @(window.visible),
                    @"key": @(window.keyWindow), @"styleMask": @(window.styleMask),
                    @"frame": NSStringFromRect(window.frame)}];
            }
            record[@"windows"] = windows;
            emitRecord(record, path);
        }];
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    });
}
#endif
