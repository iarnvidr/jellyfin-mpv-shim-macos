// Preserve AppKit's pixel deltas, gesture phases and system momentum.
#import <Cocoa/Cocoa.h>
#import <sys/socket.h>
#import <sys/un.h>
#import <fcntl.h>
#import <unistd.h>
#import <stdatomic.h>

static dispatch_queue_t ioQueue;
static dispatch_source_t reader;
static dispatch_source_t retryTimer;
static int socketFD = -1;
static atomic_bool scrollEnabled = false;
static NSString *socketPath;
static NSMutableData *inputBuffer;
static int gestureAxis = 0;
static NSTimeInterval lastScrollTime = 0;

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
            [inputBuffer replaceBytesInRange:NSMakeRange(0, length + 1) withBytes:NULL length:0];
        }
        if (inputBuffer.length > 1024 * 1024) disconnectSocket();
    });
    dispatch_resume(reader);
    writeCommand(@[@"observe_property", @9001, @"user-data/mpvtk-native-scroll"]);
    writeCommand(@[@"set_property", @"user-data/mpvtk-native-scroll-loaded", @YES]);
}

__attribute__((constructor)) static void installNativeScrolling(void) {
    @autoreleasepool {
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
