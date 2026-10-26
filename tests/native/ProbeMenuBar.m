// Diagnostic only: observe AppKit state without changing menu visibility.
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <unistd.h>

static NSDictionary *appIdentity(NSRunningApplication *app) {
    if (!app) return @{};
    return @{@"pid": @(app.processIdentifier), @"name": app.localizedName ?: @"",
        @"bundle": app.bundleIdentifier ?: @"", @"active": @(app.active),
        @"policy": @(app.activationPolicy), @"hidden": @(app.hidden),
        @"bundlePath": app.bundleURL.path ?: @""};
}

static NSDictionary *desktopState(void) {
    CGRect display = CGDisplayBounds(CGMainDisplayID());
    CGEventRef currentEvent = CGEventCreate(NULL);
    CGPoint cursor = CGEventGetLocation(currentEvent);
    CFRelease(currentEvent);
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
        @"displayBounds": @{@"x": @(display.origin.x), @"y": @(display.origin.y), @"width": @(display.size.width), @"height": @(display.size.height)},
        @"pointerPosition": @{@"x": @(cursor.x), @"y": @(cursor.y)},
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
            NSMutableArray *buttons = [NSMutableArray array];
            for (id node in nodes) {
                AXUIElementRef element = (__bridge AXUIElementRef)node;
                NSString *title = axText(element, kAXTitleAttribute);
                NSString *description = axText(element, kAXDescriptionAttribute);
                NSString *value = axText(element, kAXValueAttribute);
                if ([axText(element, kAXRoleAttribute) isEqualToString:@"AXButton"])
                    [buttons addObject:@{@"title": title, @"description": description, @"value": value}];
                NSArray *labels = @[title, description, value];
                if ([labels containsObject:@"Don’t Allow"] || [labels containsObject:@"Don't Allow"]) {
                    AXError pressed = AXUIElementPerformAction(element, kAXPressAction);
                    emitRecord(@{@"localNetworkPrompt": @"dismissed", @"axResult": @(pressed)}, nil);
                    return;
                }
            }
            emitRecord(@{@"localNetworkPrompt": @"found-without-matching-button", @"buttons": buttons}, nil);
        }
    }
    emitRecord(@{@"localNetworkPrompt": @"not-found"}, nil);
}

static int loginPlayer(pid_t pid, NSArray<NSString *> *values) {
    NSArray *identifiers = @[@"login-server", @"login-user", @"login-pass", @"login-connect"];
    AXUIElementRef root = AXUIElementCreateApplication(pid);
    for (NSUInteger step = 0; step < identifiers.count; step++) {
        NSMutableArray *nodes = [NSMutableArray array];
        axNodes(root, nodes, 0);
        BOOL found = NO;
        for (id node in nodes) {
            AXUIElementRef element = (__bridge AXUIElementRef)node;
            if (![axText(element, CFSTR("AXIdentifier")) isEqualToString:identifiers[step]]) continue;
            AXError result = step < 3
                ? AXUIElementSetAttributeValue(element, kAXValueAttribute, (__bridge CFStringRef)values[step])
                : AXUIElementPerformAction(element, kAXPressAction);
            emitRecord(@{@"loginControl": identifiers[step], @"axResult": @(result)}, nil);
            if (result != kAXErrorSuccess) { CFRelease(root); return 1; }
            found = YES;
            break;
        }
        if (!found) {
            NSMutableArray *controls = [NSMutableArray array];
            for (id node in nodes) {
                AXUIElementRef element = (__bridge AXUIElementRef)node;
                [controls addObject:@{@"id": axText(element, CFSTR("AXIdentifier")),
                    @"role": axText(element, kAXRoleAttribute), @"title": axText(element, kAXTitleAttribute),
                    @"description": axText(element, kAXDescriptionAttribute)}];
            }
            emitRecord(@{@"missingLoginControl": identifiers[step], @"controls": controls}, nil);
            CFRelease(root); return 1;
        }
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.75]];
    }
    CFRelease(root); return 0;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc == 4 && strcmp(argv[1], "--pointer") == 0) {
            CGPoint point = CGPointMake(atof(argv[2]), atof(argv[3]));
            CGWarpMouseCursorPosition(point);
            CGEventRef event = CGEventCreateMouseEvent(NULL, kCGEventMouseMoved, point, kCGMouseButtonLeft);
            CGEventPost(kCGHIDEventTap, event);
            CFRelease(event);
            [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
            emitRecord(@{@"pointerX": @(point.x), @"pointerY": @(point.y)}, nil);
        } else if (argc == 6 && strcmp(argv[1], "--login") == 0) {
            return loginPlayer(atoi(argv[2]), @[[NSString stringWithUTF8String:argv[3]],
                [NSString stringWithUTF8String:argv[4]], [NSString stringWithUTF8String:argv[5]]]);
        } else if (argc > 1 && strcmp(argv[1], "--dismiss-local-network") == 0) {
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
