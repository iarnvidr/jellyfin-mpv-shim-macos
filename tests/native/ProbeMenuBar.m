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
    NSMutableArray *intersections = [NSMutableArray array];
    NSMutableArray *screens = [NSMutableArray array];
    NSMutableArray *axWindows = [NSMutableArray array];
    for (NSScreen *screen in NSScreen.screens) {
        NSEdgeInsets inset = screen.safeAreaInsets;
        [screens addObject:@{@"displayID": screen.deviceDescription[@"NSScreenNumber"] ?: @0,
            @"frame": NSStringFromRect(screen.frame), @"visibleFrame": NSStringFromRect(screen.visibleFrame),
            @"backingScale": @(screen.backingScaleFactor), @"safeArea": @[@(inset.top), @(inset.left), @(inset.bottom), @(inset.right)]}];
    }
#ifdef PROBE_STANDALONE
    // In-process timer must never issue synchronous AX requests to itself.
    for (NSDictionary *app in apps) {
        AXUIElementRef root = AXUIElementCreateApplication([app[@"pid"] intValue]);
        CFTypeRef found = NULL;
        if (AXUIElementCopyAttributeValue(root, kAXWindowsAttribute, &found) == kAXErrorSuccess) {
            for (id window in CFBridgingRelease(found)) {
                NSMutableDictionary *item = [@{@"pid": app[@"pid"]} mutableCopy];
                for (NSString *key in @[@"AXTitle", @"AXFullScreen", @"AXMinimized"]) {
                    CFTypeRef value = NULL;
                    if (AXUIElementCopyAttributeValue((__bridge AXUIElementRef)window, (__bridge CFStringRef)key, &value) == kAXErrorSuccess)
                        item[key] = CFBridgingRelease(value);
                }
                [axWindows addObject:item];
            }
        }
        CFRelease(root);
    }
#endif
    NSMutableArray *playerWindows = [NSMutableArray array];
    NSSet *playerPIDs = [NSSet setWithArray:[apps valueForKey:@"pid"]];
    for (NSDictionary *window in windows) {
        int level = [window[(id)kCGWindowLayer] intValue];
        if (level == CGWindowLevelForKey(kCGMainMenuWindowLevelKey) || level == CGWindowLevelForKey(kCGStatusWindowLevelKey)) {
            [bars addObject:window];
        }
        if ([playerPIDs containsObject:window[(id)kCGWindowOwnerPID]]) [playerWindows addObject:window];
        CGRect bounds;
        if (CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)window[(id)kCGWindowBounds], &bounds)
            && CGRectIntersectsRect(bounds, CGRectMake(display.origin.x, display.origin.y, display.size.width, 46)))
            [intersections addObject:window];
    }
    return @{@"time": @(NSDate.date.timeIntervalSince1970),
        @"frontmost": appIdentity(NSWorkspace.sharedWorkspace.frontmostApplication),
        @"displayBounds": @{@"x": @(display.origin.x), @"y": @(display.origin.y), @"width": @(display.size.width), @"height": @(display.size.height)},
        @"pointerPosition": @{@"x": @(cursor.x), @"y": @(cursor.y)},
        @"jellyfinProcesses": apps, @"onScreenMenuWindows": bars ?: @[], @"jellyfinWindows": playerWindows,
        @"screens": screens, @"jellyfinAXWindows": axWindows, @"menuStripIntersectingWindows": intersections,
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

static void axNodesLimited(AXUIElementRef element, NSMutableArray *nodes, int depth, int maxDepth) {
    if (depth > maxDepth || nodes.count > 1000) return;
    [nodes addObject:(__bridge id)element];
    CFTypeRef children = NULL;
    if (AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &children) != kAXErrorSuccess) return;
    for (id child in CFBridgingRelease(children)) axNodesLimited((__bridge AXUIElementRef)child, nodes, depth + 1, maxDepth);
}

static void axNodes(AXUIElementRef element, NSMutableArray *nodes, int depth) {
    axNodesLimited(element, nodes, depth, 8);
}

static int menuAutoHide(NSString *choice) {
    NSString *directory = @"/System/Library/ExtensionKit/Extensions";
    NSMutableArray *bundles = [NSMutableArray array];
    for (NSString *entry in [NSFileManager.defaultManager contentsOfDirectoryAtPath:directory error:nil]) {
        if ([entry.lowercaseString containsString:@"menubar"] || [entry.lowercaseString containsString:@"menu-bar"]) {
            NSBundle *bundle = [NSBundle bundleWithPath:[directory stringByAppendingPathComponent:entry]];
            if (bundle.bundleIdentifier) [bundles addObject:bundle.bundleIdentifier];
        }
    }
    if (!bundles.count) {
        emitRecord(@{@"menuAutoHide": @"unavailable", @"reason": @"No Menu Bar settings extension in system manifest"}, nil);
        return 1;
    }
    NSURL *url = [NSURL URLWithString:[@"x-apple.systempreferences:" stringByAppendingString:bundles.firstObject]];
    [NSWorkspace.sharedWorkspace openURL:url];
    NSMutableArray *nodes = nil;
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:25];
    NSArray *choices = @[@"Always", @"Never", @"In Full Screen Only", @"On Desktop Only"];
    while (deadline.timeIntervalSinceNow > 0) {
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.5]];
        NSRunningApplication *app = [NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.apple.systempreferences"].firstObject;
        if (!app) continue;
        AXUIElementRef root = AXUIElementCreateApplication(app.processIdentifier);
        nodes = [NSMutableArray array];
        axNodesLimited(root, nodes, 0, 40);
        CFRelease(root);
        for (id node in nodes) {
            AXUIElementRef element = (__bridge AXUIElementRef)node;
            if (![axText(element, kAXRoleAttribute) isEqualToString:@"AXPopUpButton"]) continue;
            NSString *value = axText(element, kAXValueAttribute);
            NSString *label = [NSString stringWithFormat:@"%@ %@", axText(element, kAXTitleAttribute), axText(element, kAXDescriptionAttribute)];
            if (![choices containsObject:value] && [label rangeOfString:@"Automatically hide" options:NSCaseInsensitiveSearch].location == NSNotFound) continue;
            if ([choice isEqualToString:@"read"]) {
                emitRecord(@{@"menuAutoHide": @"read", @"current": value, @"label": label, @"extension": bundles.firstObject}, nil);
                return 0;
            }
            AXError pressed = AXUIElementPerformAction(element, kAXPressAction);
            if (pressed != kAXErrorSuccess) break;
            [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.5]];
            AXUIElementRef menuRoot = AXUIElementCreateApplication(app.processIdentifier);
            NSMutableArray *menuNodes = [NSMutableArray array];
            axNodesLimited(menuRoot, menuNodes, 0, 40);
            CFRelease(menuRoot);
            for (id menuNode in menuNodes) {
                AXUIElementRef item = (__bridge AXUIElementRef)menuNode;
                NSString *role = axText(item, kAXRoleAttribute);
                if (![role isEqualToString:@"AXMenuItem"] && ![role isEqualToString:@"AXButton"]) continue;
                if (![axText(item, kAXTitleAttribute) isEqualToString:choice] && ![axText(item, kAXDescriptionAttribute) isEqualToString:choice]) continue;
                AXError selected = AXUIElementPerformAction(item, kAXPressAction);
                [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:1]];
                emitRecord(@{@"menuAutoHide": @"selection-attempt", @"previous": value, @"requested": choice, @"axResult": @(selected)}, nil);
                return selected == kAXErrorSuccess ? 0 : 1;
            }
        }
    }
    NSMutableArray *dump = [NSMutableArray array];
    for (id node in nodes) {
        AXUIElementRef element = (__bridge AXUIElementRef)node;
        [dump addObject:@{@"role": axText(element, kAXRoleAttribute), @"title": axText(element, kAXTitleAttribute),
            @"description": axText(element, kAXDescriptionAttribute), @"value": axText(element, kAXValueAttribute)}];
    }
    emitRecord(@{@"menuAutoHide": @"unavailable", @"extensionCandidates": bundles, @"controls": dump}, nil);
    return 1;
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
        if (argc >= 3 && strcmp(argv[1], "--controls") == 0) {
            AXUIElementRef root = AXUIElementCreateApplication(atoi(argv[2]));
            NSMutableArray *nodes = [NSMutableArray array]; axNodes(root, nodes, 0);
            NSMutableArray *controls = [NSMutableArray array];
            for (id node in nodes) {
                AXUIElementRef element = (__bridge AXUIElementRef)node;
                NSMutableDictionary *item = [@{@"id": axText(element, CFSTR("AXIdentifier")),
                    @"title": axText(element, kAXTitleAttribute), @"description": axText(element, kAXDescriptionAttribute),
                    @"value": axText(element, kAXValueAttribute), @"role": axText(element, kAXRoleAttribute)} mutableCopy];
                CFTypeRef position = NULL, size = NULL; CGPoint point; CGSize extent;
                if (AXUIElementCopyAttributeValue(element, kAXPositionAttribute, &position) == kAXErrorSuccess &&
                    AXUIElementCopyAttributeValue(element, kAXSizeAttribute, &size) == kAXErrorSuccess &&
                    AXValueGetValue(position, kAXValueCGPointType, &point) && AXValueGetValue(size, kAXValueCGSizeType, &extent))
                    item[@"bounds"] = @[@(point.x), @(point.y), @(extent.width), @(extent.height)];
                if (position) CFRelease(position); if (size) CFRelease(size);
                [controls addObject:item];
            }
            CFRelease(root); emitRecord(@{@"controls": controls}, nil);
        } else if ((argc == 4 || argc == 5) && strcmp(argv[1], "--click") == 0) {
            CGPoint point = CGPointMake(atof(argv[2]), atof(argv[3]));
            NSString *mode = argc == 5 ? [NSString stringWithUTF8String:argv[4]] : @"left";
            BOOL right = [mode isEqualToString:@"right"];
            BOOL control = [mode isEqualToString:@"control"];
            if (control) {
                CGEventRef modifier = CGEventCreateKeyboardEvent(NULL, 59, true);
                CGEventSetType(modifier, kCGEventFlagsChanged); CGEventSetFlags(modifier, kCGEventFlagMaskControl);
                CGEventPost(kCGHIDEventTap, modifier); CFRelease(modifier);
            }
            for (NSNumber *type in @[@(kCGEventMouseMoved), @(right ? kCGEventRightMouseDown : kCGEventLeftMouseDown),
                                     @(right ? kCGEventRightMouseUp : kCGEventLeftMouseUp)]) {
                CGEventRef event = CGEventCreateMouseEvent(NULL, type.unsignedIntValue, point, right ? kCGMouseButtonRight : kCGMouseButtonLeft);
                CGEventSetFlags(event, control ? kCGEventFlagMaskControl : 0);
                CGEventSetIntegerValueField(event, kCGMouseEventClickState, 1);
                CGEventPost(kCGHIDEventTap, event); CFRelease(event);
                [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            }
            if (control) {
                CGEventRef modifier = CGEventCreateKeyboardEvent(NULL, 59, false);
                CGEventSetType(modifier, kCGEventFlagsChanged); CGEventSetFlags(modifier, 0);
                CGEventPost(kCGHIDEventTap, modifier); CFRelease(modifier);
            }
            emitRecord(@{@"clickX": @(point.x), @"clickY": @(point.y), @"mode": mode}, nil);
        } else if (argc == 3 && strcmp(argv[1], "--key") == 0) {
            NSString *key = [NSString stringWithUTF8String:argv[2]];
            CGKeyCode code = [key isEqualToString:@"cmd-tab"] ? 48 : 4;
            if (![@[@"cmd-tab", @"cmd-h"] containsObject:key]) return 2;
            CGEventRef modifier = CGEventCreateKeyboardEvent(NULL, 55, true);
            CGEventSetType(modifier, kCGEventFlagsChanged);
            CGEventSetFlags(modifier, kCGEventFlagMaskCommand);
            CGEventPost(kCGHIDEventTap, modifier); CFRelease(modifier);
            for (NSNumber *down in @[@YES, @NO]) {
                CGEventRef event = CGEventCreateKeyboardEvent(NULL, code, down.boolValue);
                CGEventSetFlags(event, kCGEventFlagMaskCommand); CGEventPost(kCGHIDEventTap, event); CFRelease(event);
                [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            }
            modifier = CGEventCreateKeyboardEvent(NULL, 55, false);
            CGEventSetType(modifier, kCGEventFlagsChanged); CGEventSetFlags(modifier, 0);
            CGEventPost(kCGHIDEventTap, modifier); CFRelease(modifier);
            emitRecord(@{@"key": key}, nil);
        } else if (argc == 3 && strcmp(argv[1], "--menu-auto-hide") == 0) {
            return menuAutoHide([NSString stringWithUTF8String:argv[2]]);
        } else if (argc == 4 && strcmp(argv[1], "--pointer") == 0) {
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
                    @"isOnActiveSpace": @([window isOnActiveSpace]), @"level": @(window.level),
                    @"frame": NSStringFromRect(window.frame)}];
            }
            record[@"windows"] = windows;
            emitRecord(record, path);
        }];
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    });
}
#endif
