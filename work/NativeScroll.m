// Preserve AppKit's pixel deltas, gesture phases and system momentum.
#import <Cocoa/Cocoa.h>
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
static NSString *socketPath;
static NSMutableData *inputBuffer;
static int gestureAxis = 0;
static NSTimeInterval lastScrollTime = 0;
static NSDictionary *branding;

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
                 @"iconMatchesJellyfin": @((BOOL)(iconError <= 2.0))};
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
                NSString *action = event[@"data"][@"action"];
                id request = event[@"data"][@"request"] ?: @"";
                dispatch_async(dispatch_get_main_queue(), ^{
                    if ([action isEqualToString:@"hide"]) [NSApp hide:nil];
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
            [inputBuffer replaceBytesInRange:NSMakeRange(0, length + 1) withBytes:NULL length:0];
        }
        if (inputBuffer.length > 1024 * 1024) disconnectSocket();
    });
    dispatch_resume(reader);
    writeCommand(@[@"observe_property", @9001, @"user-data/mpvtk-native-scroll"]);
    writeCommand(@[@"observe_property", @9002, @"user-data/jellyfin-window-action"]);
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
