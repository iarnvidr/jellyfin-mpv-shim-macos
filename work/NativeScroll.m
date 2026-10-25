// Preserve AppKit's pixel deltas, gesture phases and system momentum.
#import <Cocoa/Cocoa.h>
#import <MediaPlayer/MediaPlayer.h>
#import <objc/runtime.h>
#import <sys/socket.h>
#import <sys/un.h>
#import <fcntl.h>
#import <unistd.h>
#import <stdatomic.h>
#import <string.h>
#import <signal.h>

static dispatch_queue_t ioQueue;
static dispatch_source_t reader;
static dispatch_source_t retryTimer;
static int socketFD = -1;
static atomic_bool scrollEnabled = false;
static atomic_bool textFocused = false;
static NSString *socketPath;
static NSMutableData *inputBuffer;
static int gestureAxis = 0;
static NSTimeInterval lastScrollTime = 0;
static NSDictionary *branding;
extern void JellyfinInstallNativeMenus(void);
extern void JellyfinClosePlayerWindow(void);
static void writeCommand(NSArray *command);

static char restoreFrameKey;
static BOOL sameFrame(NSRect a, NSRect b) {
    return fabs(a.origin.x-b.origin.x) < 2 && fabs(a.origin.y-b.origin.y) < 2 &&
           fabs(a.size.width-b.size.width) < 2 && fabs(a.size.height-b.size.height) < 2;
}

static void fillPlayerWindow(NSWindow *window) {
    if (!window || (window.styleMask & NSWindowStyleMaskFullScreen)) return;
    NSScreen *screen = window.screen ?: NSScreen.mainScreen;
    if (!screen) return;
    NSRect available = screen.visibleFrame;
    NSValue *restore = objc_getAssociatedObject(window, &restoreFrameKey);
    if (restore && sameFrame(window.frame, available)) {
        [window setFrame:restore.rectValue display:YES];
        objc_setAssociatedObject(window, &restoreFrameKey, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    } else {
        objc_setAssociatedObject(window, &restoreFrameKey, [NSValue valueWithRect:window.frame], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        [window setFrame:available display:YES];
    }
}

static void ignoreEngineNowPlayingInfo(id center, SEL selector, NSDictionary *info) {}
static void ignoreEnginePlaybackState(id center, SEL selector, MPNowPlayingPlaybackState state) {}

static void suppressEngineNowPlaying(void) {
    // The pinned mpv keeps publishing metadata from property observers even
    // with input-media-keys=no. Suppress its public MediaPlayer setters in
    // this engine process; the separate Dock host owns the real publisher.
    Class centerClass = object_getClass(MPNowPlayingInfoCenter.defaultCenter);
    Method info = class_getInstanceMethod(centerClass, @selector(setNowPlayingInfo:));
    Method state = class_getInstanceMethod(centerClass, @selector(setPlaybackState:));
    if (method_getImplementation(info) == (IMP)ignoreEngineNowPlayingInfo) return;
    MPNowPlayingInfoCenter.defaultCenter.nowPlayingInfo = nil;
    MPNowPlayingInfoCenter.defaultCenter.playbackState = MPNowPlayingPlaybackStateStopped;
    method_setImplementation(info, (IMP)ignoreEngineNowPlayingInfo);
    method_setImplementation(state, (IMP)ignoreEnginePlaybackState);
}

@interface JellyfinWindowControls : NSObject
- (void)closePlayer:(id)sender;
@end
@implementation JellyfinWindowControls
- (void)closePlayer:(id)sender { JellyfinClosePlayerWindow(); }
@end
static JellyfinWindowControls *windowControls;

@interface JellyfinAXElement : NSAccessibilityElement
@property(nonatomic, copy) NSDictionary *model;
@property(nonatomic, weak) NSView *view;
@property(nonatomic) NSSize sceneSize;
@end
@implementation JellyfinAXElement
- (BOOL)isAccessibilityEnabled { return [self.model[@"enabled"] boolValue]; }
- (BOOL)isAccessibilityFocused { return [self.model[@"focused"] boolValue]; }
- (NSRect)accessibilityFrame {
    NSView *view = self.view;
    if (!view.window || self.sceneSize.width <= 0 || self.sceneSize.height <= 0) return NSZeroRect;
    CGFloat sx = view.bounds.size.width / self.sceneSize.width;
    CGFloat sy = view.bounds.size.height / self.sceneSize.height;
    NSRect rect = NSMakeRect([self.model[@"x"] doubleValue]*sx,
        view.bounds.size.height-([self.model[@"y"] doubleValue]+[self.model[@"h"] doubleValue])*sy,
        [self.model[@"w"] doubleValue]*sx, [self.model[@"h"] doubleValue]*sy);
    return [view.window convertRectToScreen:[view convertRect:rect toView:nil]];
}
- (BOOL)sendAction:(NSString *)action value:(id)value {
    if (!self.isAccessibilityEnabled) return NO;
    NSMutableDictionary *message = [@{@"id": self.model[@"id"], @"action": action} mutableCopy];
    for (NSString *key in @[@"generation", @"control", @"option"]) if (self.model[key]) message[key] = self.model[key];
    if (value) message[@"value"] = value;
    NSData *json = [NSJSONSerialization dataWithJSONObject:message options:0 error:nil];
    NSString *text = [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
    dispatch_async(ioQueue, ^{ writeCommand(@[@"script-message", @"jellyfin-accessibility-action", text]); });
    return YES;
}
- (BOOL)accessibilityPerformPress { return [self sendAction:@"press" value:nil]; }
- (BOOL)accessibilityPerformIncrement { return [self sendAction:@"increment" value:nil]; }
- (BOOL)accessibilityPerformDecrement { return [self sendAction:@"decrement" value:nil]; }
- (void)setAccessibilityFocused:(BOOL)focused { if (focused) [self sendAction:@"focus" value:nil]; }
- (void)setAccessibilityValue:(id)value { [self sendAction:@"set" value:value]; }
- (id)accessibilityValue { return self.model[@"value"]; }
- (BOOL)isAccessibilitySelectorAllowed:(SEL)selector {
    NSString *role = self.model[@"role"];
    if (selector == @selector(accessibilityPerformPress)) return ![role isEqualToString:@"label"] && ![role isEqualToString:@"slider"];
    if (selector == @selector(accessibilityPerformIncrement) || selector == @selector(accessibilityPerformDecrement)) return [role isEqualToString:@"slider"];
    if (selector == @selector(setAccessibilityValue:)) return [role isEqualToString:@"text"];
    return [super isAccessibilitySelectorAllowed:selector];
}
@end

@interface JellyfinAXView : NSView
@property(nonatomic, copy) NSArray *elements;
@end
@implementation JellyfinAXView
- (BOOL)isAccessibilityElement { return NO; }
- (NSArray *)accessibilityChildren { return self.elements ?: @[]; }
- (NSView *)hitTest:(NSPoint)point { return nil; }
- (id)accessibilityHitTest:(NSPoint)point {
    for (JellyfinAXElement *element in self.elements.reverseObjectEnumerator) {
        if (NSPointInRect(point, element.accessibilityFrame)) return element;
    }
    return nil;
}
@end
static JellyfinAXView *accessibilityView;

static void updateAccessibility(NSDictionary *model) {
    NSWindow *window = NSApp.mainWindow;
    if (!window) for (NSWindow *candidate in NSApp.windows) {
        if (candidate.canBecomeMainWindow) { window = candidate; break; }
    }
    NSView *content = window.contentView;
    if (!content) return;
    if (accessibilityView.superview != content) {
        [accessibilityView removeFromSuperview];
        accessibilityView = [[JellyfinAXView alloc] initWithFrame:content.bounds];
        accessibilityView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        [content addSubview:accessibilityView];
    }
    NSMutableDictionary *previous = [NSMutableDictionary dictionary];
    for (JellyfinAXElement *element in accessibilityView.elements) previous[element.model[@"id"]] = element;
    NSMutableArray *elements = [NSMutableArray array];
    NSDictionary *roles = @{@"text": NSAccessibilityTextFieldRole, @"slider": NSAccessibilitySliderRole,
        @"checkbox": NSAccessibilityCheckBoxRole, @"popup": NSAccessibilityPopUpButtonRole,
        @"button": NSAccessibilityButtonRole, @"label": NSAccessibilityStaticTextRole};
    BOOL changed = NO;
    for (NSDictionary *node in model[@"nodes"]) {
        NSString *identifier = node[@"id"];
        if (![identifier isKindOfClass:NSString.class]) continue;
        JellyfinAXElement *element = previous[identifier];
        if (!element) { element = [JellyfinAXElement new]; changed = YES; }
        NSDictionary *old = element.model;
        element.model = node;
        element.view = accessibilityView;
        element.sceneSize = NSMakeSize([model[@"w"] doubleValue], [model[@"h"] doubleValue]);
        element.accessibilityParent = accessibilityView;
        element.accessibilityRole = roles[node[@"role"]] ?: NSAccessibilityGroupRole;
        element.accessibilitySubrole = [node[@"secure"] boolValue] ? NSAccessibilitySecureTextFieldSubrole : nil;
        element.accessibilityLabel = node[@"label"];
        element.accessibilityIdentifier = identifier;
        if (old && (old[@"value"] || node[@"value"]) && ![old[@"value"] isEqual:node[@"value"]]) NSAccessibilityPostNotification(element, NSAccessibilityValueChangedNotification);
        if ([node[@"focused"] boolValue] && ![old[@"focused"] boolValue]) NSAccessibilityPostNotification(element, NSAccessibilityFocusedUIElementChangedNotification);
        [elements addObject:element];
    }
    changed = changed || elements.count != accessibilityView.elements.count;
    accessibilityView.elements = elements;
    if (changed) NSAccessibilityPostNotification(accessibilityView, NSAccessibilityLayoutChangedNotification);
    if (NSProcessInfo.processInfo.environment[@"JELLYFIN_PLAYER_MENU_DIAGNOSTICS"]) {
        NSDictionary *diagnostic = @{@"count": @(elements.count),
            @"roles": [elements valueForKey:@"accessibilityRole"]};
        dispatch_async(ioQueue, ^{ writeCommand(@[@"set_property", @"user-data/jellyfin-accessibility-native", diagnostic]); });
    }
}

static void notifyAppHost(int signalNumber) {
    int host = [NSProcessInfo.processInfo.environment[@"JELLYFIN_PLAYER_HOST_PID"] intValue];
    if (host > 1) kill(host, signalNumber);
}

static NSData *iconPixels(NSImage *image) {
    if (!image) return nil;
    NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:64 pixelsHigh:64 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSCalibratedRGBColorSpace bytesPerRow:256 bitsPerPixel:32];
    memset(bitmap.bitmapData, 0, bitmap.bytesPerRow * bitmap.pixelsHigh);
    [NSGraphicsContext saveGraphicsState];
    NSGraphicsContext.currentContext = [NSGraphicsContext graphicsContextWithBitmapImageRep:bitmap];
    [image drawInRect:NSMakeRect(0, 0, 64, 64)];
    [NSGraphicsContext restoreGraphicsState];
    return [NSData dataWithBytes:bitmap.bitmapData length:bitmap.bytesPerRow * bitmap.pixelsHigh];
}

static void applyPlayerBranding(void) {
    suppressEngineNowPlaying();
    if ([NSProcessInfo.processInfo.environment[@"JELLYFIN_PLAYER_HOSTED"] isEqualToString:@"1"]) {
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    }
    NSBundle *bundle = NSBundle.mainBundle;
    NSString *iconPath = [bundle pathForResource:@"jellyfin" ofType:@"icns"];
    NSImage *icon = iconPath ? [[NSImage alloc] initWithContentsOfFile:iconPath] : nil;
    NSProcessInfo.processInfo.processName = @"Jellyfin Player";
    if (icon) NSApp.applicationIconImage = icon;
    for (NSWindow *window in NSApp.windows) {
        if ([window.title isEqualToString:@"mpv"]) window.title = @"Jellyfin Player";
        if (window.canBecomeMainWindow) {
            if (!windowControls) windowControls = [JellyfinWindowControls new];
            NSButton *close = [window standardWindowButton:NSWindowCloseButton];
            close.target = windowControls;
            close.action = @selector(closePlayer:);
        }
    }
    NSData *expectedPixels = iconPixels(icon);
    NSData *actualPixels = iconPixels(NSApp.applicationIconImage);
    double iconError = 255;
    if (expectedPixels.length && actualPixels.length == expectedPixels.length) {
        const unsigned char *expected = expectedPixels.bytes;
        const unsigned char *actual = actualPixels.bytes;
        double total = 0;
        for (NSUInteger i = 0; i < expectedPixels.length; i++) total += abs((int)actual[i] - (int)expected[i]);
        iconError = total / expectedPixels.length;
    }
    NSString *iconDiagnostics = NSProcessInfo.processInfo.environment[@"JELLYFIN_PLAYER_ICON_DIAGNOSTICS"];
    if (iconDiagnostics) {
        [expectedPixels writeToFile:[iconDiagnostics stringByAppendingPathComponent:@"expected-icon.rgba"] atomically:YES];
        [actualPixels writeToFile:[iconDiagnostics stringByAppendingPathComponent:@"runtime-icon.rgba"] atomically:YES];
    }
    // The stock engine hardcodes these labels even when it is a named bundle.
    for (NSMenuItem *item in NSApp.mainMenu.itemArray.firstObject.submenu.itemArray) {
        if ([item.title isEqualToString:@"About mpv"]) item.title = @"About Jellyfin Player";
        if ([item.title isEqualToString:@"Hide mpv"]) item.title = @"Hide Jellyfin Player";
        if ([item.title isEqualToString:@"Quit mpv"]) item.title = @"Quit Jellyfin Player";
    }
    branding = @{@"name": NSProcessInfo.processInfo.processName,
                 @"bundle": bundle.bundlePath,
                 // AppKit resamples Dock icons. Allow less than 1% mean RGBA
                 // deviation, rather than requiring identical antialiasing.
                 @"iconPixelMeanError": @(iconError),
                 @"iconMatchesJellyfin": @((BOOL)(iconError <= 2.0)),
                 @"engineNowPlayingSuppressed": @((BOOL)(method_getImplementation(class_getInstanceMethod(
                     object_getClass(MPNowPlayingInfoCenter.defaultCenter), @selector(setNowPlayingInfo:))) == (IMP)ignoreEngineNowPlayingInfo))};
    JellyfinInstallNativeMenus();
}

static void disconnectSocket(void) {
    atomic_store(&scrollEnabled, false);
    if (reader) { dispatch_source_cancel(reader); reader = nil; }
    if (socketFD >= 0) { close(socketFD); socketFD = -1; }
    inputBuffer = [NSMutableData data];
}

static void writeCommand(NSArray *command) {
    if (socketFD < 0) return;
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"command": command} options:0 error:nil];
    NSMutableData *line = [data mutableCopy];
    [line appendBytes:"\n" length:1];
    ssize_t written = send(socketFD, line.bytes, line.length, MSG_DONTWAIT);
    if (written != (ssize_t)line.length) disconnectSocket();
}

static void acknowledgeWindow(NSWindow *window, id request, NSUInteger remaining) {
    BOOL visible = window.isVisible && !window.isMiniaturized && !NSApp.isHidden;
    if (!visible && remaining) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * 50), dispatch_get_main_queue(), ^{
            acknowledgeWindow(window, request, remaining - 1);
        });
        return;
    }
    NSDictionary *ack = @{@"request": request, @"visible": @(visible),
                         @"windowTitle": window.title ?: @"", @"windowClass": window ? NSStringFromClass(window.class) : @"none"};
    dispatch_async(ioQueue, ^{ writeCommand(@[@"set_property", @"user-data/jellyfin-window-ack", ack]); });
}

static void connectSocket(void) {
    if (socketFD >= 0 || !socketPath) return;
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    if ([socketPath lengthOfBytesUsingEncoding:NSUTF8StringEncoding] >= sizeof(address.sun_path)) return;
    strlcpy(address.sun_path, socketPath.fileSystemRepresentation, sizeof(address.sun_path));
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return;
    int noSignal = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof(noSignal));
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) { close(fd); return; }
    fcntl(fd, F_SETFL, O_NONBLOCK);
    socketFD = fd;
    inputBuffer = [NSMutableData data];
    reader = dispatch_source_create(DISPATCH_SOURCE_TYPE_READ, fd, 0, ioQueue);
    dispatch_source_set_event_handler(reader, ^{
        char bytes[8192];
        ssize_t count;
        while ((count = read(fd, bytes, sizeof(bytes))) > 0) [inputBuffer appendBytes:bytes length:count];
        if (count == 0) { disconnectSocket(); return; }
        for (;;) {
            const char *data = inputBuffer.bytes;
            const char *newline = memchr(data, '\n', inputBuffer.length);
            if (!newline) break;
            NSUInteger length = (NSUInteger)(newline - data);
            NSData *line = [inputBuffer subdataWithRange:NSMakeRange(0, length)];
            NSDictionary *event = [NSJSONSerialization JSONObjectWithData:line options:0 error:nil];
            if ([event isKindOfClass:NSDictionary.class] && [event[@"id"] integerValue] == 9001) {
                id enabled = event[@"data"];
                atomic_store(&scrollEnabled, [enabled respondsToSelector:@selector(boolValue)] && [enabled boolValue]);
            }
            if ([event isKindOfClass:NSDictionary.class] && [event[@"id"] integerValue] == 9002 && [event[@"data"] isKindOfClass:NSDictionary.class]) {
                NSDictionary *payload = event[@"data"];
                NSString *action = payload[@"action"];
                id request = payload[@"request"] ?: @"";
                dispatch_async(dispatch_get_main_queue(), ^{
                    if ([action isEqualToString:@"hide"]) [NSApp hide:nil];
                    if ([action isEqualToString:@"close"]) {
                        notifyAppHost(SIGWINCH);
                        for (NSWindow *window in NSApp.windows) if (window.canBecomeMainWindow) [window orderOut:nil];
                    }
                    if ([action isEqualToString:@"zoom"]) {
                        NSWindow *window = NSApp.mainWindow;
                        NSRect before = window.frame;
                        fillPlayerWindow(window);
                        NSRect frame = window.frame, available = window.screen.visibleFrame;
                        NSDictionary *geometry = @{@"request": request, @"filled": @(sameFrame(frame, available)),
                            @"before": @[@(before.origin.x), @(before.origin.y), @(before.size.width), @(before.size.height)],
                            @"frame": @[@(frame.origin.x), @(frame.origin.y), @(frame.size.width), @(frame.size.height)]};
                        dispatch_async(ioQueue, ^{ writeCommand(@[@"set_property", @"user-data/jellyfin-window-geometry", geometry]); });
                    }
                    if ([action isEqualToString:@"show"]) {
                        [NSApp unhide:nil];
                        [NSApp activateIgnoringOtherApps:YES];
                        NSWindow *window = NSApp.mainWindow;
                        if (!window) {
                            for (NSWindow *candidate in NSApp.windows) {
                                if (candidate.canBecomeMainWindow) { window = candidate; break; }
                            }
                        }
                        [window deminiaturize:nil];
                        [window makeKeyAndOrderFront:nil];
                        acknowledgeWindow(window, request, 30);
                    }
                });
            }
            if ([event[@"id"] integerValue] == 9003 && [event[@"data"] isKindOfClass:NSDictionary.class]) {
                NSDictionary *payload = event[@"data"];
                atomic_store(&textFocused, [payload[@"focused"] boolValue]);
            }
            if ([event[@"id"] integerValue] == 9004 && [event[@"data"] isKindOfClass:NSDictionary.class]) {
                NSDictionary *model = event[@"data"];
                dispatch_async(dispatch_get_main_queue(), ^{ updateAccessibility(model); });
            }
            [inputBuffer replaceBytesInRange:NSMakeRange(0, length + 1) withBytes:NULL length:0];
        }
        if (inputBuffer.length > 1024 * 1024) disconnectSocket();
    });
    dispatch_resume(reader);
    writeCommand(@[@"observe_property", @9001, @"user-data/mpvtk-native-scroll"]);
    writeCommand(@[@"observe_property", @9002, @"user-data/jellyfin-window-action"]);
    writeCommand(@[@"observe_property", @9003, @"user-data/jellyfin-native-edit"]);
    writeCommand(@[@"observe_property", @9004, @"user-data/jellyfin-accessibility"]);
    writeCommand(@[@"set_property", @"user-data/mpvtk-native-scroll-loaded", @YES]);
    dispatch_async(dispatch_get_main_queue(), ^{
        applyPlayerBranding();
        NSDictionary *identity = branding;
        dispatch_async(ioQueue, ^{ writeCommand(@[@"set_property", @"user-data/jellyfin-macos-branding", identity]); });
    });
}

__attribute__((constructor)) static void installNativeScrolling(void) {
    @autoreleasepool {
        [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidHideNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { notifyAppHost(SIGUSR1); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSWindowDidMiniaturizeNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { notifyAppHost(SIGUSR1); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidUnhideNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { notifyAppHost(SIGUSR2); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSWindowDidDeminiaturizeNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { notifyAppHost(SIGUSR2); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidFinishLaunchingNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { applyPlayerBranding(); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidBecomeActiveNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) { applyPlayerBranding(); }];
        [NSNotificationCenter.defaultCenter addObserverForName:NSWindowDidBecomeKeyNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
            NSWindow *window = note.object;
            if ([window.title isEqualToString:@"mpv"]) window.title = @"Jellyfin Player";
            if (!windowControls) windowControls = [JellyfinWindowControls new];
            NSButton *close = [window standardWindowButton:NSWindowCloseButton];
            close.target = windowControls;
            close.action = @selector(closePlayer:);
        }];
        NSArray<NSString *> *arguments = NSProcessInfo.processInfo.arguments;
        for (NSUInteger i = 0; i < arguments.count; i++) {
            NSString *arg = arguments[i];
            if ([arg hasPrefix:@"--input-ipc-server="]) socketPath = [arg substringFromIndex:19];
            else if ([arg isEqualToString:@"--input-ipc-server"] && i + 1 < arguments.count) socketPath = arguments[i + 1];
        }
        if (!socketPath) return;
        ioQueue = dispatch_queue_create("org.jellyfin.mpvshim.native-scroll", DISPATCH_QUEUE_SERIAL);
        retryTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, ioQueue);
        dispatch_source_set_timer(retryTimer, DISPATCH_TIME_NOW, NSEC_PER_SEC, NSEC_PER_MSEC * 50);
        dispatch_source_set_event_handler(retryTimer, ^{ connectSocket(); });
        dispatch_resume(retryTimer);
        dispatch_async(dispatch_get_main_queue(), ^{
            suppressEngineNowPlaying();
            [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown handler:^NSEvent *(NSEvent *event) {
                if (!atomic_load(&textFocused)) return event;
                NSEventModifierFlags modifiers = event.modifierFlags;
                BOOL command = (modifiers & NSEventModifierFlagCommand) != 0;
                BOOL option = (modifiers & NSEventModifierFlagOption) != 0;
                BOOL shift = (modifiers & NSEventModifierFlagShift) != 0;
                NSString *operation = nil;
                if (event.keyCode == 123) operation = command ? (shift ? @"SHOME" : @"HOME") : option ? (shift ? @"CSLEFT" : @"CLEFT") : nil;
                if (event.keyCode == 124) operation = command ? (shift ? @"SEND" : @"END") : option ? (shift ? @"CSRIGHT" : @"CRIGHT") : nil;
                if (event.keyCode == 51 && option) operation = @"CBS";
                NSDictionary *editing = @{@"z": shift ? @"REDO" : @"UNDO", @"x": @"CUT", @"c": @"CTRLC", @"v": @"PASTE", @"a": @"CTRLA"};
                if (command && editing[event.charactersIgnoringModifiers.lowercaseString]) operation = editing[event.charactersIgnoringModifiers.lowercaseString];
                if (!operation) return event;
                dispatch_async(ioQueue, ^{ writeCommand(@[@"script-message", @"jellyfin-native-edit", operation]); });
                return nil;
            }];
            // macOS uses the menu bar for these actions. Do not let either
            // mpvtk or mpv's fallback bindings open a right-click menu.
            [NSEvent addLocalMonitorForEventsMatchingMask:(NSEventMaskRightMouseDown | NSEventMaskRightMouseUp | NSEventMaskLeftMouseDown | NSEventMaskLeftMouseUp) handler:^NSEvent *(NSEvent *event) {
                if (event.type == NSEventTypeRightMouseDown || event.type == NSEventTypeRightMouseUp ||
                    (event.modifierFlags & NSEventModifierFlagControl)) return nil;
                // The engine's native title bar otherwise performs video-aspect
                // zoom. Use the same fill/restore behavior as our drawn header.
                if ((event.type == NSEventTypeLeftMouseDown || event.type == NSEventTypeLeftMouseUp) && event.clickCount == 2 && event.window &&
                    !(event.window.styleMask & NSWindowStyleMaskFullScreen)) {
                    NSRect content = [event.window convertRectToScreen:event.window.contentLayoutRect];
                    NSPoint point = [event.window convertPointToScreen:event.locationInWindow];
                    if (point.y >= NSMaxY(content)) {
                        if (event.type == NSEventTypeLeftMouseUp) return nil;
                        NSString *action = [NSUserDefaults.standardUserDefaults stringForKey:@"AppleActionOnDoubleClick"];
                        if ([action isEqualToString:@"Minimize"]) [event.window performMiniaturize:nil];
                        else if (![action isEqualToString:@"None"]) fillPlayerWindow(event.window);
                        return nil;
                    }
                }
                return event;
            }];
            [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskScrollWheel handler:^NSEvent *(NSEvent *event) {
                if (!event.hasPreciseScrollingDeltas || !atomic_load(&scrollEnabled) || !event.window) return event;
                NSView *view = event.window.contentView;
                NSPoint location = [view convertPoint:event.locationInWindow fromView:nil];
                CGFloat scale = event.window.backingScaleFactor;
                CGFloat y = view.isFlipped ? location.y : view.bounds.size.height - location.y;
                if ((event.phase & NSEventPhaseBegan) || event.timestamp - lastScrollTime > 0.3) gestureAxis = 0;
                lastScrollTime = event.timestamp;
                if (!gestureAxis && (event.scrollingDeltaX != 0 || event.scrollingDeltaY != 0)) {
                    gestureAxis = fabs(event.scrollingDeltaX) > fabs(event.scrollingDeltaY) ? 2 : 1;
                }
                NSDictionary *payload = @{
                    @"x": @(location.x * scale), @"y": @(y * scale),
                    @"dx": @(gestureAxis == 2 ? -event.scrollingDeltaX * scale : 0),
                    @"dy": @(gestureAxis == 1 ? -event.scrollingDeltaY * scale : 0),
                    @"phase": @(event.phase), @"momentum": @(event.momentumPhase)
                };
                NSData *json = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
                NSString *text = [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
                dispatch_async(ioQueue, ^{ writeCommand(@[@"script-message", @"mpvtk-native-scroll", text]); });
                return nil;
            }];
        });
    }
}
